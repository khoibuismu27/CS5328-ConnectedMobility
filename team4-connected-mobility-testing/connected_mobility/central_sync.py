"""
Connected Mobility - Central / Digital-Twin sync and logging.

The central node receives every message on the bus, keeps an append-only sync
log (evidence + replay), and forwards validated telemetry to the Digital Twin
so the twin's live state reflects each car. It also detects device faults:
if a registered car stops sending telemetry for longer than a timeout, it is
flagged STALE and its last command intent is not re-applied.

MockDigitalTwin stands in for Team 3's subsystem. *** IT IS A MOCK. *** The
real Digital Twin is a separate team's service; here we only need something
that records "state was pushed for entity X" so Connected Mobility's side of
the interface can be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .message import Message, MessageType
from .registry import EntityRegistry


DEFAULT_STALE_TIMEOUT_S = 3.0


class MockDigitalTwin:
    """Mock of Team 3's Digital Twin: stores last-known state per entity."""

    def __init__(self) -> None:
        self.state: Dict[str, dict] = {}
        self.update_count = 0
        # Set True to simulate the twin being unavailable (failure testing).
        self.unavailable = False

    def update_state(self, entity_id: str, state: dict) -> None:
        if self.unavailable:
            raise ConnectionError("Digital Twin unavailable")
        self.state[entity_id] = dict(state)
        self.update_count += 1

    def get_state(self, entity_id: str) -> Optional[dict]:
        return self.state.get(entity_id)


@dataclass
class _LogEntry:
    seq: int
    src: str
    dst: str
    type: str
    ts: float


@dataclass
class CentralSync:
    """Central node logic: log every message, sync telemetry to the twin,
    flag stale devices."""

    registry: EntityRegistry
    twin: MockDigitalTwin
    stale_timeout_s: float = DEFAULT_STALE_TIMEOUT_S
    sync_log: List[_LogEntry] = field(default_factory=list)
    last_seen: Dict[str, float] = field(default_factory=dict)
    last_seq: Dict[str, int] = field(default_factory=dict)
    twin_errors: List[str] = field(default_factory=list)
    rejected_out_of_order: int = 0

    def on_message(self, msg: Message) -> None:
        """Handle one message arriving at the central node."""
        self.sync_log.append(
            _LogEntry(seq=msg.seq, src=msg.src, dst=msg.dst, type=msg.type.value, ts=msg.ts)
        )
        if msg.type is MessageType.TELEMETRY:
            # Reject duplicate / out-of-order frames per the digital-twin
            # robustness rule: a seq that is not strictly greater than the last
            # accepted seq for this car is stale and must not reach the twin.
            if msg.seq <= self.last_seq.get(msg.src, -1):
                self.rejected_out_of_order += 1
                return
            self.last_seq[msg.src] = msg.seq
            self.last_seen[msg.src] = msg.ts
            try:
                self.twin.update_state(msg.src, msg.payload)
            except ConnectionError as exc:
                # Failure is logged, not fatal: Connected Mobility keeps running
                # and will re-sync when the twin returns. Roll back the accepted
                # seq so the retried frame is not treated as a duplicate.
                self.last_seq.pop(msg.src, None)
                self.twin_errors.append(f"seq={msg.seq} src={msg.src}: {exc}")

    def stale_devices(self, now: float) -> List[str]:
        """Return registered devices whose last telemetry is older than the
        timeout (device-fault detection, UC-06)."""
        stale = []
        for entity_id, ts in self.last_seen.items():
            if now - ts > self.stale_timeout_s:
                stale.append(entity_id)
        return sorted(stale)
