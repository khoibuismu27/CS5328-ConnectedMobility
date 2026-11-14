"""
Part II - Integration Testing (Team 4: Connected Mobility)

Interface under test:
    Connected Mobility messaging layer  <->  Quanser cars + Central/Digital-Twin

  * The "cars" are Node objects on the MockBus, standing in for QCars on the
    lab Wi-Fi/TCP network (the Quanser environment).
  * The "central / Digital Twin" is a CENTRAL Node wired to CentralSync +
    MockDigitalTwin, standing in for Team 3's subsystem.

*** All counterpart subsystems here are MOCKS/SIMULATORS. *** They exercise
Connected Mobility's real schema, registry, IP filter, and sync logic without
the physical Quanser hardware or Team 3's live service. Tests that run against
the integrated platform must be reported separately.

Test IDs match the Testing Report (IT-01 .. IT-04).
"""

import time

import pytest

from connected_mobility.message import BROADCAST, CENTRAL, MessageType
from connected_mobility.registry import EntityRegistry
from connected_mobility.transport import MockBus, Node
from connected_mobility.central_sync import CentralSync, MockDigitalTwin

from tests._helpers import telemetry_frame, drive_frame, make_frame


@pytest.fixture
def harness():
    """A small smart-city network: carA, carB, carC and a CENTRAL node wired
    to central sync + a mock Digital Twin."""
    registry = EntityRegistry()
    twin = MockDigitalTwin()
    central_logic = CentralSync(registry=registry, twin=twin)

    bus = MockBus()
    carA = bus.add(Node("carA", "192.168.2.11", registry))
    carB = bus.add(Node("carB", "192.168.2.12", registry))
    carC = bus.add(Node("carC", "192.168.2.13", registry))
    central = bus.add(Node(CENTRAL, "192.168.2.1", registry))
    central.on_accept = central_logic.on_message

    return {
        "registry": registry, "twin": twin, "central_logic": central_logic,
        "bus": bus, "carA": carA, "carB": carB, "carC": carC, "central": central,
    }


def test_IT01_command_relayed_to_matching_car_only(harness):
    """IT-01 (normal): CENTRAL dispatches a DRIVE command addressed to carB.
    The IP filter means carB acts on it while carC does not."""
    frame = drive_frame(seq=10, src=CENTRAL, dst="carB",
                        throttle=0.05, steering=0.1, ts=time.time())
    harness["central"].broadcast(frame)

    assert len(harness["carB"].acted) == 1
    assert harness["carB"].acted[0].type is MessageType.COMMAND
    assert len(harness["carC"].acted) == 0           # filtered out by IP filter
    assert len(harness["carA"].acted) == 0


def test_IT02_telemetry_syncs_to_digital_twin(harness):
    """IT-02 (normal): carA telemetry addressed to CENTRAL is received by the
    central node, logged, and synced into the Digital Twin's live state."""
    frame = telemetry_frame(seq=20, src="carA", x=3.0, y=4.0, yaw=0.0, speed=0.25)
    harness["carA"].broadcast(frame)

    twin_state = harness["twin"].get_state("carA")
    assert twin_state is not None
    assert twin_state["x"] == 3.0 and twin_state["speed"] == 0.25
    assert harness["central_logic"].sync_log[-1].src == "carA"


def test_IT03_digital_twin_unavailable_is_handled(harness):
    """IT-03 (FAILURE scenario): the Digital Twin is down when telemetry
    arrives. Connected Mobility must log the failure and keep running -- not
    crash -- and must re-sync once the twin recovers."""
    harness["twin"].unavailable = True
    harness["carA"].broadcast(telemetry_frame(seq=30, src="carA", x=1.0))

    # The failure was recorded, no exception propagated, nothing synced.
    assert len(harness["central_logic"].twin_errors) == 1
    assert harness["twin"].get_state("carA") is None

    # Twin recovers; the next telemetry message syncs normally.
    harness["twin"].unavailable = False
    harness["carA"].broadcast(telemetry_frame(seq=31, src="carA", x=2.0))
    assert harness["twin"].get_state("carA")["x"] == 2.0


def test_IT04_broadcast_acted_on_by_all_cars(harness):
    """IT-04 (normal): a BROADCAST-addressed message is acted on by every car
    (the other branch of the IP filter)."""
    frame = make_frame(seq=40, src=CENTRAL, dst=BROADCAST, type="COMMAND",
                       payload={"verb": "STOP"}, ts=time.time())
    harness["central"].broadcast(frame)

    assert len(harness["carA"].acted) == 1
    assert len(harness["carB"].acted) == 1
    assert len(harness["carC"].acted) == 1


def test_IT05_duplicate_and_out_of_order_telemetry_rejected(harness):
    """IT-05 (FAILURE scenario): the central sync must reject duplicate and
    out-of-order telemetry per the digital-twin robustness rule (README s.11:
    'reject duplicate or out-of-order sequence numbers'). A newer frame is
    accepted; an older or repeated seq for the same car must NOT overwrite the
    twin with stale data."""
    carA, twin, central_logic = harness["carA"], harness["twin"], harness["central_logic"]

    carA.broadcast(telemetry_frame(seq=5, src="carA", x=5.0, ts=1000.0))   # accept
    carA.broadcast(telemetry_frame(seq=3, src="carA", x=3.0, ts=1001.0))   # out-of-order -> reject
    carA.broadcast(telemetry_frame(seq=5, src="carA", x=99.0, ts=1002.0))  # duplicate -> reject

    # The twin must still hold the seq-5 state; stale frames were dropped.
    assert twin.get_state("carA")["x"] == 5.0
    assert twin.update_count == 1
    assert central_logic.rejected_out_of_order == 2
