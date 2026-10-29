"""
test_comms.py  --  unit tests for the framing and schema layers

These isolate the two components most likely to be where YOUR code broke
(framing boundaries, numpy/NaN serialization) so you can diff behavior exactly.

Run:  python -m pytest test_comms.py -v
  or: python test_comms.py   (falls back to a plain runner if pytest absent)
"""

from __future__ import annotations

import socket
import threading

from wire import send_frame, recv_frame, ProtocolError
from schema import (
    Message, SchemaError, make_state, make_hello,
    MSG_STATE, SCHEMA_VERSION,
)


# ---- framing ------------------------------------------------------------

def test_two_messages_do_not_glue_together():
    """The core TCP trap: two sends, read back as two distinct messages."""
    a, b = socket.socketpair()
    try:
        send_frame(a, b"first")
        send_frame(a, b"second")
        assert recv_frame(b) == b"first"
        assert recv_frame(b) == b"second"
    finally:
        a.close(); b.close()


def test_large_message_survives_fragmentation():
    """A payload bigger than one TCP segment must reassemble correctly."""
    a, b = socket.socketpair()
    payload = b"x" * 200_000
    try:
        t = threading.Thread(target=send_frame, args=(a, payload))
        t.start()
        got = recv_frame(b)
        t.join()
        assert got == payload
    finally:
        a.close(); b.close()


def test_closed_peer_raises():
    a, b = socket.socketpair()
    a.close()
    try:
        try:
            recv_frame(b)
            assert False, "expected ConnectionError"
        except ConnectionError:
            pass
    finally:
        b.close()


# ---- schema -------------------------------------------------------------

def test_roundtrip_state():
    msg = make_state("car-1", 7, x=1.0, y=2.0, yaw=0.5, speed=0.3)
    back = Message.from_bytes(msg.to_bytes())
    assert back.sender_id == "car-1"
    assert back.seq == 7
    assert back.body["x"] == 1.0
    assert back.schema_version == SCHEMA_VERSION


def test_nan_is_rejected():
    msg = make_state("car-1", 1, x=float("nan"), y=0.0, yaw=0.0)
    try:
        msg.to_bytes()
        assert False, "expected SchemaError for NaN"
    except SchemaError:
        pass


def test_numpy_scalars_serialize():
    """Sensor data arrives as numpy types; they must serialize, not crash."""
    try:
        import numpy as np
    except ImportError:
        return  # numpy optional for this test
    msg = make_state("car-1", 1, x=np.float32(1.5), y=np.float64(2.5),
                     yaw=np.float32(0.0))
    back = Message.from_bytes(msg.to_bytes())
    assert abs(back.body["x"] - 1.5) < 1e-6


def test_unknown_field_rejected():
    raw = b'{"msg_type":"heartbeat","sender_id":"x","seq":1,"bogus":1}'
    try:
        Message.from_bytes(raw)
        assert False, "expected SchemaError for unexpected field"
    except SchemaError:
        pass


def test_bad_json_rejected():
    try:
        Message.from_bytes(b"not json")
        assert False, "expected SchemaError"
    except SchemaError:
        pass


if __name__ == "__main__":
    # Minimal runner so this works without pytest installed.
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} tests passed")
