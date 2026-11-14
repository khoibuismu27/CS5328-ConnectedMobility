"""
Part I - Unit Testing (Team 4: Connected Mobility)

Two units under test:
  Unit A - Device-message parsing      (connected_mobility.message.parse_message)
  Unit B - Command validation          (connected_mobility.command.validate_command)

Each unit has a normal case and at least one edge/invalid case.
Test IDs match the Testing Report (UT-01 .. UT-06).
"""

import time

import pytest

from connected_mobility.message import (
    parse_message, MessageError, MessageType, BROADCAST,
)
from connected_mobility.command import validate_command, MAX_ABS_THROTTLE
from connected_mobility.registry import EntityRegistry

from tests._helpers import telemetry_frame, drive_frame, make_frame


# ----------------------------------------------------------------------------
# Unit A: Device-message parsing
# ----------------------------------------------------------------------------

def test_UT01_parse_valid_telemetry():
    """UT-01 (normal): a well-formed telemetry frame parses into a Message
    with the correct fields and type."""
    frame = telemetry_frame(seq=7, src="carA", x=1.5, y=-2.0, yaw=0.3, speed=0.4)
    msg = parse_message(frame)

    assert msg.type is MessageType.TELEMETRY
    assert msg.seq == 7
    assert msg.src == "carA"
    assert msg.dst == "CENTRAL"
    assert msg.payload["x"] == 1.5
    assert msg.payload["speed"] == 0.4


def test_UT02_parse_malformed_json_rejected():
    """UT-02 (invalid): a frame that is not valid JSON is rejected with
    MessageError, never partially applied."""
    bad = b'{"schema": 0, "seq": 1, "src": "carA"'  # truncated / not closed
    with pytest.raises(MessageError):
        parse_message(bad)


def test_UT03_parse_nan_payload_rejected():
    """UT-03 (edge): NaN / infinite numeric values in the payload are rejected
    (robustness rule from the DEVELOPER_GUIDE: never apply non-finite data)."""
    # json.dumps emits NaN by default, so build the frame directly.
    frame = b'{"schema":0,"seq":1,"ts":0.0,"src":"carA","dst":"CENTRAL",' \
            b'"type":"TELEMETRY","payload":{"x":NaN,"y":0.0}}'
    with pytest.raises(MessageError):
        parse_message(frame)


def test_UT03b_missing_required_field_rejected():
    """UT-03b (invalid): a frame missing a required field (seq) is rejected."""
    frame = b'{"schema":0,"ts":0.0,"src":"carA","dst":"CENTRAL",' \
            b'"type":"TELEMETRY","payload":{}}'
    with pytest.raises(MessageError, match="seq"):
        parse_message(frame)


# ----------------------------------------------------------------------------
# Unit B: Command validation
# ----------------------------------------------------------------------------

@pytest.fixture
def registry():
    reg = EntityRegistry()
    reg.register("carA", "192.168.2.11")
    reg.register("carB", "192.168.2.12")
    return reg


def test_UT04_valid_drive_command_accepted(registry):
    """UT-04 (normal): a DRIVE command within the safety envelope and to a
    registered destination is accepted."""
    frame = drive_frame(seq=1, src="CENTRAL", dst="carB",
                        throttle=0.05, steering=0.2, ts=time.time())
    msg = parse_message(frame)
    result = validate_command(msg, registry)
    assert result.ok, result.reason


def test_UT05_throttle_over_limit_rejected(registry):
    """UT-05 (edge): throttle beyond the +/-0.1 safety limit is rejected and the
    reason names the limit -- the command must NOT be clamped silently."""
    frame = drive_frame(seq=2, src="CENTRAL", dst="carB",
                        throttle=0.8, steering=0.0, ts=time.time())
    msg = parse_message(frame)
    result = validate_command(msg, registry)
    assert not result.ok
    assert "throttle" in result.reason
    assert str(MAX_ABS_THROTTLE) in result.reason


def test_UT06_command_to_unregistered_destination_rejected(registry):
    """UT-06 (invalid): a command addressed to an unknown entity is rejected
    (we have no IP to route it to)."""
    frame = drive_frame(seq=3, src="CENTRAL", dst="carZ",
                        throttle=0.05, steering=0.0, ts=time.time())
    msg = parse_message(frame)
    result = validate_command(msg, registry)
    assert not result.ok
    assert "not registered" in result.reason


def test_UT06b_stale_command_rejected(registry):
    """UT-06b (edge): a command with an old timestamp is rejected as stale."""
    old_ts = time.time() - 10.0
    frame = drive_frame(seq=4, src="CENTRAL", dst="carB",
                        throttle=0.05, steering=0.0, ts=old_ts)
    msg = parse_message(frame)
    result = validate_command(msg, registry, now=time.time())
    assert not result.ok
    assert "stale" in result.reason
