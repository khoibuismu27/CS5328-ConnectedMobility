# Assignment 3 — Software Testing Report
## Team 4: Connected Mobility — Lyle-CS Smart City Digital Twin Platform

**Course:** CS 5328 — Software Engineering
**Team:** Team 4 — Connected Mobility
**Team members:** _[add names]_
**Date:** 2026-11-13
**Test code repository:** _[add GitHub URL after pushing this folder]_

---

### Scope and test environment

Connected Mobility is the sense/act bridge of the platform: it connects the
transportation devices (QCars in the Quanser environment) to the software
platform, ingesting telemetry up to the Digital Twin and relaying commands back
down to the vehicles. The units and interfaces tested here are the Sprint-1
messaging layer: **message schema v0 + parsing, the entity/IP registry, command
validation, the TCP broadcast transport with IP filter, and central/Digital-Twin
sync**.

**Environment:** Python 3.13, `pytest` 9.1.1. All tests are automated and
executed with `pytest -v`. Final run: **15 passed** (`test_run.log`).

**Mock vs. integrated (required disclosure).** Tests run against the Connected
Mobility code itself, which is real. The counterpart subsystems are
**mocks/simulators**, clearly labeled in code:

| Mocked element | Stands in for | Used in |
|---|---|---|
| `MockBus` (in-memory broadcast) | lab Wi-Fi/TCP socket network (Quanser side) | Part II, III |
| `MockDigitalTwin` | Team 3 Digital Twin service | Part II, III |
| `MockTrafficManagement`, `MockDashboard` | Team 2 / Team 1 subsystems | Part III |

No test in this report was executed against the physical Quanser hardware or
another team's live service. Those runs must be added and reported separately
once the integrated platform is available (see *Outstanding work* at the end).

---

## Part I — Unit Testing (30 pts)

### Unit A — Device-message parsing
`connected_mobility.message.parse_message(raw) -> Message`

- **Purpose:** Convert raw bytes received on the socket into a validated,
  structurally sound `Message`, or reject them. This is the platform's first
  line of defense against malformed or unsafe device data.
- **Inputs:** `bytes`/`str` — one UTF-8 JSON object (schema, seq, ts, src, dst,
  type, payload).
- **Expected outputs:** a frozen `Message` object on success; a `MessageError`
  on any malformed, incomplete, wrong-schema, unknown-type, or non-finite input.

### Unit B — Command validation
`connected_mobility.command.validate_command(msg, registry) -> ValidationResult`

- **Purpose:** Decide whether a `COMMAND` message is safe to dispatch to a
  vehicle before it becomes actuation. Enforces the LAIL safety envelope
  (throttle ±0.1, steering ±0.5 rad), a known command verb, a registered
  destination, and command freshness.
- **Inputs:** a parsed `Message` of type `COMMAND`; the `EntityRegistry`.
- **Expected outputs:** `ValidationResult(ok=True)` when safe to dispatch;
  `ValidationResult(ok=False, reason=...)` otherwise. Unsafe commands are
  **rejected, not silently clamped**, so faults stay visible.

### Unit test cases and results

| Test ID | Unit | Description | Type | Expected | Actual | Pass/Fail |
|---|---|---|---|---|---|---|
| UT-01 | A | Parse a well-formed telemetry frame | Normal | Returns `Message` with correct fields/type | As expected | **Pass** |
| UT-02 | A | Parse a truncated / non-JSON frame | Invalid | Raises `MessageError` | As expected | **Pass** |
| UT-03 | A | Parse a frame with `NaN` in the payload | Edge | Raises `MessageError` (non-finite rejected) | As expected | **Pass** |
| UT-03b | A | Parse a frame missing required field `seq` | Invalid | Raises `MessageError` naming `seq` | As expected | **Pass** |
| UT-04 | B | Validate a DRIVE command within limits, registered dst | Normal | `ok=True` | As expected | **Pass** |
| UT-05 | B | Validate a DRIVE command with throttle 0.8 | Edge | Rejected; reason names the 0.1 limit | As expected | **Pass** |
| UT-06 | B | Validate a command to an unregistered destination | Invalid | Rejected; reason "not registered" | As expected | **Pass** |
| UT-06b | B | Validate a command with a 10 s-old timestamp | Edge | Rejected as stale | As expected | **Pass** |

**Unit testing result: 8 tests, 8 passed, 0 failed.** (The assignment requires
≥4; 8 are provided across the two units, each with normal and edge/invalid
cases.)

---

## Part II — Integration Testing (35 pts)

### Interface under test
**Connected Mobility messaging layer ↔ Quanser cars + Central/Digital-Twin node.**

- **Interacting components:** the Connected Mobility transport + sync logic, and
  (a) QCar nodes on the network, (b) the central node wired to `CentralSync` and
  the Digital Twin.
- **Data exchanged:** newline-delimited JSON messages (schema v0). `TELEMETRY`
  (car → CENTRAL: x, y, yaw, speed) flows up and is synced into the twin;
  `COMMAND` (CENTRAL → car) flows down and is acted on only by the car whose
  registered IP matches (the IP filter).
- **Expected behavior:** a command reaches exactly its addressed car; telemetry
  updates the twin; failures (twin down, stale/duplicate data) are contained and
  logged without crashing the service.

### Integration test cases and results

| Test ID | Description | Type | Expected | Actual | Pass/Fail |
|---|---|---|---|---|---|
| IT-01 | CENTRAL dispatches DRIVE to carB | Normal | carB acts; carA/carC filtered out by IP filter | As expected | **Pass** |
| IT-02 | carA telemetry synced to Digital Twin | Normal | Twin holds carA state; central logs it | As expected | **Pass** |
| IT-03 | Telemetry arrives while Digital Twin is **unavailable** | **Failure** | Failure logged, no crash, re-syncs on recovery | As expected | **Pass** |
| IT-04 | BROADCAST command | Normal | Every car acts (other IP-filter branch) | As expected | **Pass** |
| IT-05 | Duplicate + out-of-order telemetry | **Failure** | Stale frames rejected; twin keeps newest state | **Revealed a defect — see below; fixed, now Pass** | **Pass** |

**Integration testing result: 5 tests, 5 passed, 0 failed** (after the IT-05
fix; the assignment requires ≥3 including one failure scenario — IT-03 and IT-05
are both failure scenarios).

#### Defect found by IT-05 (genuine finding)
When first run, **IT-05 failed**: the central sync accepted a duplicate/older
sequence number and let stale telemetry (seq 5, x=99.0) overwrite the twin's
good state (seq 5, x=5.0) — see `evidence_IT05_before_fix.log`. This violates
the digital-twin robustness rule in the DEVELOPER_GUIDE / QLabs README §11
("reject duplicate or out-of-order sequence numbers"). **Fix:** `CentralSync`
now tracks the last accepted sequence number per car and drops any
non-increasing `seq` for `TELEMETRY`. Re-run: pass.

#### Cross-team coordination evidence
_[Attach here: the agreed message schema / interface contract with Team 3
(Digital Twin) and the Quanser lab — e.g. meeting notes, a shared schema doc,
or chat confirming field names and the central-sync expectation. The Sprint-1
notes confirm the messaging mechanism with the Quanser TA; cite that artifact.]_

---

## Part III — System Testing (25 pts)

### Connected Mobility's role in the end-to-end scenario
Scenario: **Simulated Transportation Data → Connected Mobility → Digital Twin →
Traffic Management → Dashboard.** Connected Mobility ingests simulated car
telemetry, validates it, syncs it to the Digital Twin (feeding Traffic
Management and the Dashboard), and relays the resulting command back down to the
car. The tests exercise the largest end-to-end flow currently available; Teams
1/2/3 are mocked.

### System test cases and results

| Test ID | Description | Requirement traced | Expected | Actual | Pass/Fail |
|---|---|---|---|---|---|
| ST-01 | Full sense→sync→act loop: 3 telemetry frames up to the twin + dashboard; Traffic Mgmt issues STOP; command reaches carA | UC-02 Stream Telemetry + UC-05 Dispatch Command | Twin shows latest speed; command validated and delivered to carA | As expected | **Pass** |
| ST-02 | A connected device goes silent | UC-06 Detect/Recover from Device Fault | Device flagged stale after timeout; twin keeps last good state, invents no new state | As expected | **Pass** |

**System testing result: 2 tests, 2 passed, 0 failed** (assignment requires ≥2).

**Team 4 contribution to the overall system test:** Connected Mobility provides
and validates the data path that the whole scenario depends on — telemetry
ingestion, the twin-sync point, and command relay. ST-01/ST-02 demonstrate that
this bridge behaves correctly end-to-end against mocked neighbors, which is the
prerequisite for wiring in the real Digital Twin and Traffic Management in
Sprint 2.

---

## Part IV — Testing Summary and Reflection (10 pts)

| Testing Level | Tests | Passed | Failed | Major Findings |
|---|---|---|---|---|
| Unit Testing | 8 | 8 | 0 | Parsing and command safety-envelope checks behave as specified; non-finite, malformed, over-limit, stale, and unregistered inputs are all rejected. |
| Integration Testing | 5 | 5 | 0* | IT-05 initially **failed**, revealing that duplicate/out-of-order telemetry could overwrite the twin with stale data; fixed via per-car sequence tracking. Twin-unavailable failure is handled gracefully. |
| System Testing | 2 | 2 | 0 | End-to-end sense→sync→act loop works against mocked neighbors; device-fault detection contains a silent device. |

\* 0 failing in the final run; 1 pre-fix failure (IT-05) is documented above.

**1. Main differences among unit, integration, and system testing.**
Unit testing checks one component in isolation (does `parse_message` or
`validate_command` behave correctly for valid and invalid inputs?). Integration
testing checks that two components interoperate across an interface (does a
command dispatched at CENTRAL reach the right car; does telemetry actually land
in the twin; what happens when the twin is down?). System testing checks the
whole end-to-end scenario against requirements (does simulated data flow all the
way to a command back to the car, and is a device fault detected?). The scope
widens and the failures caught shift from "wrong logic" to "wrong contract" to
"wrong behavior against a requirement."

**2. Problems the tests revealed.**
The unit and system tests passed on first run, which is expected: they were
written alongside the reference code and exercise logic we controlled directly —
so their bug-finding power is limited (a point to improve, below). The
integration tests were more revealing: **IT-05 caught a real defect** — the
central sync did not enforce sequence ordering, so a duplicate or out-of-order
frame could overwrite the Digital Twin with stale data. This is the kind of bug
that is invisible in single-message unit tests and only appears once you test a
*stream* crossing the component boundary. It was fixed and re-verified.

**3. Testing that should be improved before V1.0.**
- **Replace mocks with the real transport and Digital Twin.** The IP filter and
  sync are tested over an in-memory bus; they must be re-tested over real
  TCP sockets on the lab network and against Team 3's live service.
- **Concurrency / timing.** Real cars send concurrently; add tests for
  interleaved streams, dropped packets, and latency, which the single-threaded
  mock bus cannot surface.
- **Coordinate / unit conversion.** The twin-sync path does not yet validate
  coordinate-frame and unit conversions (metres vs. pixels, radians vs.
  degrees) — a known hazard called out in the DEVELOPER_GUIDE.
- **Hardware-in-the-loop system tests** with the Quanser QCar/QLabs, including
  the safety behaviors (zero on stale command, clean shutdown).
- **Cross-team integration tests** jointly owned with Teams 2 and 3, using an
  agreed interface contract and shared test data.

---

## Outstanding work before submission (owned by Team 4)

These items are required by the assignment but cannot be produced from the
reference environment; they are the team's to complete:

1. **Push this folder to GitHub** and paste the repository URL at the top.
2. **Reconcile with the actual module:** confirm the reference functions match
   the team's real Sprint-1 code, or swap the real code in behind the same test
   imports, and re-run.
3. **Attach cross-team coordination evidence** (Part II) — the agreed interface
   with Team 3 / Quanser.
4. **Add and separately report any runs against the live integrated platform /
   physical Quanser**, distinguished from the mock-based results above.
