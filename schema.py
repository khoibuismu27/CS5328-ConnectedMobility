"""
schema.py  --  Message schema v0

THE PROBLEM THIS SOLVES
-----------------------
A schema that is called "v0" but has no version field cannot evolve: the day
you change it, every peer that speaks the old shape breaks with no way to tell
what happened. So schema_version is baked into every message from the start.

Two more traps this guards against, both specific to THIS project:
  1. numpy types. Sensor data off the QCar comes back as numpy float32/float64,
     and json.dumps() raises TypeError on those. We coerce to native float/int.
  2. NaN / inf. The README and DEVELOPER_GUIDE both warn that lidar/depth
     produce NaN and out-of-range samples. Python's json HAPPILY writes
     `NaN`/`Infinity`, which is invalid JSON that many parsers reject. We
     reject non-finite numbers explicitly instead of letting them onto the wire.

This is schema v0 on purpose: a small, honest, versioned envelope. It is NOT a
prescription of your team's full data model -- it's the minimum that makes the
socket layer safe to build on. Add fields as your design firms up; bump the
version when you change the *meaning* of existing ones.

WHY A DATACLASS + to_bytes/from_bytes INSTEAD OF RAW DICTS
Centralizing (de)serialization in one place means validation happens in exactly
one place. Every receiver gets the same checks for free, so one malformed packet
can't crash a car because somebody forgot to validate on their end.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any

SCHEMA_VERSION = 0

# Message types we speak in v0. Keep this closed so a typo in a type string is
# caught instead of silently routed nowhere.
MSG_HELLO = "hello"        # announce presence to the registry / peers
MSG_STATE = "state"        # a car's pose/telemetry update
MSG_HEARTBEAT = "heartbeat"  # "I'm still alive" with no new state
KNOWN_TYPES = {MSG_HELLO, MSG_STATE, MSG_HEARTBEAT}


class SchemaError(Exception):
    """Raised when a message doesn't conform to schema v0."""


def _finite_float(value: Any, name: str) -> float:
    """Coerce to a native float and reject NaN/inf. Accepts numpy scalars."""
    try:
        f = float(value)  # float() handles numpy float32/float64 and ints
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"field {name!r} is not a number: {value!r}") from exc
    if not math.isfinite(f):
        raise SchemaError(f"field {name!r} is not finite: {f!r}")
    return f


@dataclass
class Message:
    """
    One v0 message envelope.

    Fields:
      msg_type     one of KNOWN_TYPES
      sender_id    stable logical id of the sender (e.g. "car-1"), NOT its IP
      seq          per-sender sequence number, strictly increasing
      sent_ts      sender's wall-clock time (epoch seconds), for staleness checks
      body         free-form dict payload; validated per msg_type below
      schema_version  stamped automatically; present on every message
    """
    msg_type: str
    sender_id: str
    seq: int
    sent_ts: float = field(default_factory=time.time)
    body: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # ---- validation -----------------------------------------------------

    def validate(self) -> "Message":
        """Check structural invariants. Returns self so calls can chain."""
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaError(
                f"schema_version {self.schema_version} != expected {SCHEMA_VERSION}"
            )
        if self.msg_type not in KNOWN_TYPES:
            raise SchemaError(f"unknown msg_type {self.msg_type!r}")
        if not isinstance(self.sender_id, str) or not self.sender_id:
            raise SchemaError("sender_id must be a non-empty string")
        if not isinstance(self.seq, int) or self.seq < 0:
            raise SchemaError("seq must be a non-negative integer")
        self.sent_ts = _finite_float(self.sent_ts, "sent_ts")
        if not isinstance(self.body, dict):
            raise SchemaError("body must be an object")

        # Per-type body checks. A 'state' message is the one that actually moves
        # a twin, so it gets the strictest treatment: finite x/y/yaw required.
        if self.msg_type == MSG_STATE:
            for key in ("x", "y", "yaw"):
                if key not in self.body:
                    raise SchemaError(f"state message missing body.{key}")
                self.body[key] = _finite_float(self.body[key], f"body.{key}")
        return self

    # ---- (de)serialization ---------------------------------------------

    def to_bytes(self) -> bytes:
        """
        Serialize to UTF-8 JSON bytes, validated first.

        allow_nan=False makes json.dumps RAISE on any NaN/inf that slipped
        through, instead of emitting invalid JSON. Belt and suspenders with
        validate().
        """
        self.validate()
        return json.dumps(asdict(self), allow_nan=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Message":
        """
        Parse bytes from the wire into a validated Message, or raise SchemaError.

        Every failure mode -- bad UTF-8, bad JSON, missing/extra fields, wrong
        types, non-finite numbers -- comes out as SchemaError so callers have
        exactly one exception type to guard against when handling untrusted
        network input.
        """
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("payload is not valid UTF-8") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"payload is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise SchemaError("top-level JSON must be an object")

        allowed = {f for f in Message.__dataclass_fields__}
        unexpected = set(data) - allowed
        if unexpected:
            raise SchemaError(f"unexpected fields: {sorted(unexpected)}")
        missing = {"msg_type", "sender_id", "seq"} - set(data)
        if missing:
            raise SchemaError(f"missing required fields: {sorted(missing)}")

        return cls(
            msg_type=data["msg_type"],
            sender_id=data["sender_id"],
            seq=data["seq"],
            sent_ts=data.get("sent_ts", time.time()),
            body=data.get("body", {}),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        ).validate()


# Convenience constructors -- make the common messages hard to get wrong.

def make_hello(sender_id: str, seq: int, host: str, port: int) -> Message:
    return Message(MSG_HELLO, sender_id, seq, body={"host": host, "port": port})


def make_state(sender_id: str, seq: int, x: float, y: float, yaw: float,
               speed: float | None = None) -> Message:
    body: dict[str, Any] = {"x": x, "y": y, "yaw": yaw}
    if speed is not None:
        body["speed"] = speed
    return Message(MSG_STATE, sender_id, seq, body=body)


def make_heartbeat(sender_id: str, seq: int) -> Message:
    return Message(MSG_HEARTBEAT, sender_id, seq)
