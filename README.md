# Sprint 1 — Connected Mobility comms

## What maps to which bullet

| Sprint 1 bullet | Files |
|---|---|
| TCP socket layer (car ↔ car) on the lab network | `wire.py`, `node.py` |
| Message schema v0 + entity/IP registry | `schema.py`, `registry.py` |
| Central/twin sync channel; log every message | `sync_channel.py` |
| Repo + skeleton; test/deploy baseline | `test_comms.py`, `demo.py`, this README |

## Run it

```bash
python test_comms.py      # unit tests for framing + schema (8 tests)
python demo.py            # full end-to-end run on localhost
cat messages.jsonl        # the "log every message" output
```

`demo.py` intentionally injects a duplicate seq, an out-of-order seq, and a
malformed frame, and makes a sender go silent — so you can watch each one
handled instead of taking it on faith.

## The bugs

These are the usual reasons a socket layer "runs on localhost" but won't
connect on the lab floor, or corrupts the twin once traffic picks up:

1. **Message framing.** TCP is a byte stream, not messages. Without
   length-prefix framing (`wire.py`), two messages glue together or one splits.
   This is almost certainly involved if yours "garbles" messages.
2. **Partial send/recv.** `send` may send part of the buffer; `recv(n)` returns
   up to n bytes. Use `sendall` and loop reads until a full frame — both done
   in `wire.py`.
3. **Bind address.** `node.py` binds `0.0.0.0`, not `127.0.0.1`. Localhost bind
   is the classic "works in testing, can't connect on the network" bug.
4. **`SO_REUSEADDR`.** Set before bind so a restart doesn't hit
   "Address already in use."
5. **numpy + NaN in JSON.** Sensor data is numpy float32 (not JSON-serializable
   by default) and lidar/depth produce NaN/inf (which `json` writes as invalid
   JSON). `schema.py` coerces to native floats and rejects non-finite values.
6. **Versioned schema.** Every message carries `schema_version` so v0 can
   actually evolve.
7. **Malformed-packet safety.** One bad packet is logged and dropped; the node
   keeps serving (`node._serve_conn`). It does not crash a car.
8. **Dedup + ordering.** `sync_channel.py` accepts only strictly-newer sequence
   numbers per sender.
9. **Staleness.** Silent senders get flagged via `sweep_stale()`.
10. **Logging off the hot path.** `MessageLog` writes on a background thread so
    disk latency stays out of the receive path.

## Registry: static vs dynamic

`registry.py` supports both. Load a static seed with
`Registry.from_file("registry_seed.json")` (see `registry_seed.example.json`),
or let entities self-register from `hello` messages. **Your team should decide
which** — static is simpler for fixed lab assignments; dynamic handles changing
DHCP addresses. Document the choice in your design.

## What is deliberately NOT here

- The actual QLabs/PAL twin update — that's `apply_to_twin`, your team's call.
- Encryption/auth — out of scope for a lab network in Sprint 1; note it as a
  known gap.
- A connection pool — this uses connection-per-message for simplicity. Fine for
  low-rate telemetry; revisit if your update rate is high.
