"""
Connected Mobility - Message schema v0 and device-message parsing.

This module is Team 4's "device-message parsing" unit. It defines the wire
format used between QCars, the central node (Digital Twin sync point), and the
Connected Mobility service, and it parses raw bytes received over the TCP
socket layer into a validated Message object.

Design is aligned to the Sprint-1 architecture and to the robustness rules in
the LAIL DEVELOPER_GUIDE / QLabs README section 11 ("Extending into a networked
digital twin"):
  * every packet carries a sequence number and a sender timestamp;
  * NaN / infinite numeric values are rejected;
  * malformed or incomplete packets are rejected, never partially applied.

Wire format: a single UTF-8 JSON object, newline-terminated on the socket.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


# Message schema version. Bump this when the wire format changes so the
# central node can reject incompatible senders.
SCHEMA_VERSION = 0

# Addressing constants used in the `dst` field.
BROADCAST = "BROADCAST"   # every car inspects it; IP filter decides who acts.
CENTRAL = "CENTRAL"       # addressed to the central / Digital-Twin sync node.


class MessageType(str, Enum):
    """The kinds of messages Connected Mobility understands."""
    TELEMETRY = "TELEMETRY"   # car -> central: pose/speed/heading (UC-02).
    COMMAND = "COMMAND"       # central -> car: dispatch an actuation (UC-05).
    ACK = "ACK"               # car -> central: acknowledges a command.


class MessageError(ValueError):
    """Raised when a raw message cannot be parsed into a valid Message."""


# Required top-level fields for every message, with the python type each must
# parse to after json.loads.
_REQUIRED_FIELDS = {
    "schema": int,
    "seq": int,
    "ts": (int, float),
    "src": str,
    "dst": str,
    "type": str,
    "payload": dict,
}


@dataclass(frozen=True)
class Message:
    """A parsed, structurally valid Connected Mobility message."""
    schema: int
    seq: int
    ts: float
    src: str
    dst: str
    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)

    def is_broadcast(self) -> bool:
        return self.dst == BROADCAST


def _reject_non_finite(payload: Dict[str, Any]) -> None:
    """Reject NaN / +-inf anywhere in the (one-level) numeric payload.

    Stale or garbage float values must never reach actuation or the twin.
    """
    for key, value in payload.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise MessageError(f"non-finite value for payload field '{key}': {value!r}")
        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, float) and not math.isfinite(item):
                    raise MessageError(
                        f"non-finite value in payload field '{key}[{i}]': {item!r}"
                    )


def parse_message(raw: bytes | str) -> Message:
    """Parse raw bytes/str from the socket layer into a validated Message.

    Validation performed (any failure raises MessageError):
      1. decodes as UTF-8 and parses as a JSON object;
      2. all required fields are present and of the correct type;
      3. schema version matches SCHEMA_VERSION;
      4. seq is a non-negative integer;
      5. `type` is one of the known MessageType values;
      6. payload contains no NaN / infinite numbers.

    Returns a frozen Message. Does not interpret command semantics -- that is
    the job of the command-validation unit (command.py).
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MessageError(f"message is not valid UTF-8: {exc}") from exc

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MessageError(f"message is not valid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise MessageError(f"message must be a JSON object, got {type(obj).__name__}")

    # Presence + type checks for every required field.
    for name, expected in _REQUIRED_FIELDS.items():
        if name not in obj:
            raise MessageError(f"missing required field: '{name}'")
        if not isinstance(obj[name], expected):
            # bool is a subclass of int; reject it where a real int is required.
            if expected is int and isinstance(obj[name], bool):
                raise MessageError(f"field '{name}' must be an int, got bool")
            exp_name = (
                expected.__name__ if isinstance(expected, type)
                else "/".join(t.__name__ for t in expected)
            )
            raise MessageError(
                f"field '{name}' must be {exp_name}, got {type(obj[name]).__name__}"
            )

    if obj["schema"] != SCHEMA_VERSION:
        raise MessageError(
            f"unsupported schema version {obj['schema']} (expected {SCHEMA_VERSION})"
        )

    if isinstance(obj["seq"], bool) or obj["seq"] < 0:
        raise MessageError(f"seq must be a non-negative integer, got {obj['seq']!r}")

    try:
        msg_type = MessageType(obj["type"])
    except ValueError as exc:
        raise MessageError(f"unknown message type: {obj['type']!r}") from exc

    _reject_non_finite(obj["payload"])

    return Message(
        schema=obj["schema"],
        seq=obj["seq"],
        ts=float(obj["ts"]),
        src=obj["src"],
        dst=obj["dst"],
        type=msg_type,
        payload=obj["payload"],
    )


def serialize_message(msg: Message) -> bytes:
    """Serialize a Message back to newline-terminated JSON bytes for the socket."""
    obj = {
        "schema": msg.schema,
        "seq": msg.seq,
        "ts": msg.ts,
        "src": msg.src,
        "dst": msg.dst,
        "type": msg.type.value,
        "payload": msg.payload,
    }
    return (json.dumps(obj) + "\n").encode("utf-8")
