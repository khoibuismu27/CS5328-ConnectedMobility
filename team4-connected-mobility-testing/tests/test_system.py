"""
Part III - System Testing (Team 4: Connected Mobility)

End-to-end company scenario (Lyle-CS Smart City Digital Twin Platform):

    Simulated Transportation Data -> Connected Mobility -> Digital Twin
                                  -> Traffic Management -> Dashboard

Connected Mobility's role in this flow is the sense/act bridge: it ingests
simulated car telemetry, validates it, syncs it to the Digital Twin, and
relays commands (originating from Traffic Management) back down to the cars.

*** MOCK DISCLOSURE ***  Only Connected Mobility's code is real here. The
simulated data source, Digital Twin, Traffic Management, and Dashboard are
lightweight mocks so Team 4 can test its two system-level requirements before
the live integrated platform exists. The largest available end-to-end flow is
exercised; the missing live connections are documented in the Testing Report.

Test IDs match the Testing Report (ST-01, ST-02).
"""

import time

from connected_mobility.message import CENTRAL, MessageType, parse_message
from connected_mobility.registry import EntityRegistry
from connected_mobility.transport import MockBus, Node
from connected_mobility.central_sync import CentralSync, MockDigitalTwin
from connected_mobility.command import validate_command

from tests._helpers import telemetry_frame, drive_frame


class MockTrafficManagement:
    """Mock of Team 2: reads twin state and decides a command.

    Trivial policy for the test: if a car's speed exceeds a threshold, issue a
    STOP; the point under test is the data path, not the traffic algorithm.
    """
    def __init__(self, twin: MockDigitalTwin):
        self.twin = twin

    def decide(self, entity_id: str) -> str | None:
        state = self.twin.get_state(entity_id)
        if state is None:
            return None
        return "STOP" if state.get("speed", 0.0) > 0.3 else None


class MockDashboard:
    """Mock of Team 1: records what it would display."""
    def __init__(self):
        self.displayed = []

    def render(self, entity_id, state):
        self.displayed.append((entity_id, dict(state)))


def _build_city():
    registry = EntityRegistry()
    twin = MockDigitalTwin()
    central_logic = CentralSync(registry=registry, twin=twin, stale_timeout_s=3.0)
    bus = MockBus()
    carA = bus.add(Node("carA", "192.168.2.11", registry))
    central = bus.add(Node(CENTRAL, "192.168.2.1", registry))
    central.on_accept = central_logic.on_message
    return registry, twin, central_logic, bus, carA, central


def test_ST01_end_to_end_sense_sync_act():
    """ST-01: Simulated telemetry flows up through Connected Mobility to the
    Digital Twin and Dashboard; a Traffic-Management command flows back down and
    reaches the car.

    Requirement traced: UC-02 (Stream Vehicle Telemetry) + UC-05 (Dispatch
    Command to Device).
    """
    registry, twin, central_logic, bus, carA, central = _build_city()
    traffic = MockTrafficManagement(twin)
    dashboard = MockDashboard()

    # 1. Simulated transportation data: carA streams 3 telemetry frames.
    now = time.time()
    for i, speed in enumerate([0.10, 0.25, 0.40]):
        carA.broadcast(telemetry_frame(seq=i, src="carA", x=float(i), speed=speed, ts=now + i))

    # 2. Digital Twin reflects the latest telemetry; Dashboard renders it.
    assert twin.get_state("carA")["speed"] == 0.40
    dashboard.render("carA", twin.get_state("carA"))
    assert dashboard.displayed[-1][1]["speed"] == 0.40

    # 3. Traffic Management decides a command from twin state (speed > 0.3 -> STOP).
    decision = traffic.decide("carA")
    assert decision == "STOP"

    # 4. Command flows back DOWN through Connected Mobility to carA.
    cmd = drive_frame(seq=100, src=CENTRAL, dst="carA",
                      throttle=0.0, steering=0.0, ts=time.time())
    # (A STOP is a zero-throttle DRIVE here; it must pass command validation.)
    assert validate_command(parse_message(cmd), registry).ok
    central.broadcast(cmd)

    assert len(carA.acted) == 1
    assert carA.acted[0].type is MessageType.COMMAND
    # Full loop: telemetry logged at central AND command delivered to the car.
    assert any(e.type == "TELEMETRY" for e in central_logic.sync_log)


def test_ST02_device_fault_detected_and_contained():
    """ST-02: A connected device goes silent. Connected Mobility detects the
    stale device so the platform does not act on dead data.

    Requirement traced: UC-06 (Detect and Recover from Device Fault).
    """
    registry, twin, central_logic, bus, carA, central = _build_city()

    t0 = 1000.0
    carA.broadcast(telemetry_frame(seq=0, src="carA", x=1.0, speed=0.2, ts=t0))
    # Immediately after, the device is healthy.
    assert central_logic.stale_devices(now=t0 + 1.0) == []

    # carA goes silent. After the stale timeout it is flagged as a fault.
    stale = central_logic.stale_devices(now=t0 + 5.0)
    assert stale == ["carA"]

    # The twin still holds the LAST good state (not corrupted by the fault),
    # and no newer state was invented while the device was dark.
    assert twin.get_state("carA")["x"] == 1.0
    assert twin.update_count == 1
