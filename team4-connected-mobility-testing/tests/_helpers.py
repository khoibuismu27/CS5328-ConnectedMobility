"""Shared helpers for building test messages."""

from __future__ import annotations

import json
import time

from connected_mobility.message import SCHEMA_VERSION


def make_frame(
    *,
    seq: int,
    src: str,
    dst: str,
    type: str,
    payload: dict,
    ts: float | None = None,
    schema: int = SCHEMA_VERSION,
) -> bytes:
    """Build a well-formed JSON frame (bytes) as it would arrive on the wire."""
    if ts is None:
        ts = time.time()
    obj = {
        "schema": schema,
        "seq": seq,
        "ts": ts,
        "src": src,
        "dst": dst,
        "type": type,
        "payload": payload,
    }
    return (json.dumps(obj) + "\n").encode("utf-8")


def telemetry_frame(seq: int, src: str, *, x=0.0, y=0.0, yaw=0.0, speed=0.0,
                    ts: float | None = None, dst: str = "CENTRAL") -> bytes:
    return make_frame(
        seq=seq, src=src, dst=dst, type="TELEMETRY",
        payload={"x": x, "y": y, "yaw": yaw, "speed": speed}, ts=ts,
    )


def drive_frame(seq: int, src: str, dst: str, *, throttle, steering,
                ts: float | None = None) -> bytes:
    return make_frame(
        seq=seq, src=src, dst=dst, type="COMMAND",
        payload={"verb": "DRIVE", "throttle": throttle, "steering": steering}, ts=ts,
    )
