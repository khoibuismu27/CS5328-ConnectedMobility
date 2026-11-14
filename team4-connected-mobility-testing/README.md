# Team 4 — Connected Mobility: Assignment 3 Testing

Automated unit, integration, and system tests for the Connected Mobility
subsystem of the Lyle-CS Smart City Digital Twin Platform.

## What this is

A reference implementation of the Sprint-1 Connected Mobility messaging layer
(message schema v0, entity/IP registry, command validation, TCP broadcast
transport with IP filter, central/Digital-Twin sync) plus the automated test
suite for Assignment 3. It is aligned to the architecture Team 4 built in
Sprint 1 so the tests can run without the physical Quanser hardware or other
teams' live services.

### Mock disclosure (required by the assignment)

The following are **mocks/simulators**, clearly labeled in code and in the
Testing Report:

- `transport.MockBus` — in-memory stand-in for the lab Wi-Fi/TCP network.
  Preserves real broadcast + IP-filter behavior; it does not open OS sockets.
- `central_sync.MockDigitalTwin` — stand-in for Team 3's Digital Twin service.
- `test_system.MockTrafficManagement`, `MockDashboard` — stand-ins for Teams 2
  and 1 in the end-to-end flow.

All message parsing, registry, IP-filter, command-validation, and sync logic
under test is the real Connected Mobility code.

## Layout

```
connected_mobility/      reference module (code under test)
  message.py             message schema v0 + device-message parsing   (Unit A)
  registry.py            entity <-> IP registry
  command.py             command validation + safety envelope          (Unit B)
  transport.py           MockBus broadcast transport + IP filter        (mock)
  central_sync.py        central logging + Digital-Twin sync            (mock twin)
tests/
  test_unit.py           Part I   — UT-01 .. UT-06
  test_integration.py    Part II  — IT-01 .. IT-05
  test_system.py         Part III — ST-01, ST-02
TESTING_REPORT.md        the graded report (Parts I–IV)
test_run.log             captured passing run (evidence)
evidence_IT05_before_fix.log   captured failing run for the defect IT-05 found
```

## Running the tests

Requires Python 3.9+ and pytest.

```bash
pip install -r requirements.txt
pytest -v
```

Expected result: **15 passed**. See `TESTING_REPORT.md` for the full test-case
table, results, and reflection.

## Adapting to the live module / platform

Before final submission, Team 4 should:

1. Replace the reference functions with the team's actual module where they
   differ (the test imports — `parse_message`, `validate_command`,
   `EntityRegistry`, the transport, `CentralSync` — are the integration points).
2. Re-run any integration/system test against the real Quanser environment /
   Digital Twin when available, and report those results separately from the
   mock-based results.
3. Record cross-team coordination evidence (agreed message schema / interface
   with Team 3 Digital Twin and the Quanser lab).
