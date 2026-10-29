"""
registry.py  --  entity / IP registry

THE PROBLEM THIS SOLVES
-----------------------
Something has to map a logical entity id ("car-1", "twin", "central") to where
it actually lives on the lab network (host, port). Teams usually start by
hardcoding a dict of IPs in the code, which goes stale the instant a car gets a
new DHCP address, and gives you no record of who is actually online.

This registry supports BOTH styles so your team can decide:
  - a static seed loaded from a JSON file (good for fixed lab assignments), and
  - dynamic self-registration via `hello` messages (good when addresses move).

Design choices worth defending in review:
  - It's thread-safe (a Lock), because the server accepts connections on
    multiple threads and they all touch the registry.
  - last_seen is recorded on every update, which is what the staleness logic in
    the sync channel keys off of.
  - Entities are addressed by logical id, never by IP, everywhere else in the
    system. IPs live ONLY here. That keeps the one thing that changes often in
    exactly one place.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Entity:
    entity_id: str
    host: str
    port: int
    kind: str = "car"          # "car" | "twin" | "central" | ...
    last_seen: float = 0.0     # epoch seconds; 0 = never seen live


class Registry:
    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._lock = threading.Lock()

    # ---- static seed ----------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "Registry":
        """
        Load a static seed registry from JSON, shaped like:
            [
              {"entity_id": "car-1", "host": "192.168.2.11", "port": 9101,
               "kind": "car"},
              {"entity_id": "twin",  "host": "192.168.2.50", "port": 9200,
               "kind": "twin"}
            ]
        Missing optional fields fall back to defaults.
        """
        reg = cls()
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        for rec in records:
            reg.upsert(
                Entity(
                    entity_id=rec["entity_id"],
                    host=rec["host"],
                    port=int(rec["port"]),
                    kind=rec.get("kind", "car"),
                )
            )
        return reg

    # ---- mutation -------------------------------------------------------

    def upsert(self, entity: Entity) -> None:
        """Insert or update an entity, stamping last_seen."""
        with self._lock:
            entity.last_seen = time.time()
            self._entities[entity.entity_id] = entity

    def register_from_hello(self, entity_id: str, host: str, port: int,
                            kind: str = "car") -> None:
        """Dynamic self-registration, called when a `hello` arrives."""
        self.upsert(Entity(entity_id, host, int(port), kind))

    def touch(self, entity_id: str) -> None:
        """Refresh last_seen for an already-known entity (e.g. on heartbeat)."""
        with self._lock:
            ent = self._entities.get(entity_id)
            if ent is not None:
                ent.last_seen = time.time()

    # ---- queries --------------------------------------------------------

    def get(self, entity_id: str) -> Entity | None:
        with self._lock:
            return self._entities.get(entity_id)

    def address_of(self, entity_id: str) -> tuple[str, int]:
        ent = self.get(entity_id)
        if ent is None:
            raise KeyError(f"unknown entity {entity_id!r}")
        return (ent.host, ent.port)

    def all(self) -> list[Entity]:
        with self._lock:
            return list(self._entities.values())

    def live(self, max_age_s: float) -> list[Entity]:
        """Entities seen within the last max_age_s seconds."""
        cutoff = time.time() - max_age_s
        with self._lock:
            return [e for e in self._entities.values() if e.last_seen >= cutoff]

    def snapshot(self) -> list[dict]:
        """Plain-dict view, handy for logging or a dashboard endpoint."""
        with self._lock:
            return [asdict(e) for e in self._entities.values()]
