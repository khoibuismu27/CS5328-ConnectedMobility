"""
demo.py  --  End-to-end runnable proof

No Quanser, no QLabs, no lab network required. It starts a twin node and two
"car" senders on localhost and drives real TCP traffic through the full stack:
framing -> schema -> registry -> node -> sync channel -> message log.

It deliberately injects the nasty cases so you can SEE them handled:
  - a duplicate sequence number        (dropped by the ordering gate)
  - an out-of-order (old) sequence     (dropped by the ordering gate)
  - a malformed, non-JSON frame        (dropped by the node, node survives)
  - a sender going silent              (flagged stale by the sweep)

Run:  python demo.py
Then inspect messages.jsonl to see "log every message" in action.
"""

from __future__ import annotations

import socket
import time

from node import Node
from registry import Registry, Entity
from schema import make_hello, make_state, make_heartbeat
from sync_channel import MessageLog, SyncChannel
from wire import send_frame


def log(line: str) -> None:
    print(line)


def main() -> None:
    # --- logging + sync channel (bullet 3) -------------------------------
    msg_log = MessageLog("messages.jsonl")
    msg_log.start()
    sync = SyncChannel(log=msg_log, stale_timeout_s=1.0, on_log=log)

    # --- twin node listening for car state (bullet 1) --------------------
    twin = Node("twin", bind_host="127.0.0.1", bind_port=0,
                handler=sync.handle, on_log=log)
    twin.start()
    twin_host, twin_port = "127.0.0.1", twin.actual_port

    # --- registry (bullet 2) --------------------------------------------
    registry = Registry()
    registry.upsert(Entity("twin", twin_host, twin_port, kind="twin"))

    # Two cars self-register via hello, then send state to the twin.
    for car_id in ("car-1", "car-2"):
        registry.register_from_hello(car_id, "127.0.0.1", 0, kind="car")
        twin.send_to(twin_host, twin_port,
                     make_hello(car_id, seq=0, host="127.0.0.1", port=0))

    time.sleep(0.2)
    print("\n--- registry snapshot ---")
    for ent in registry.snapshot():
        print(" ", ent)

    print("\n--- normal state stream from car-1 (seq 1,2,3) ---")
    for seq in (1, 2, 3):
        twin.send_to(twin_host, twin_port,
                     make_state("car-1", seq, x=seq * 0.5, y=1.0, yaw=0.0))
        time.sleep(0.05)

    print("\n--- inject a DUPLICATE (seq 3 again) and an OLD (seq 2) ---")
    twin.send_to(twin_host, twin_port,
                 make_state("car-1", 3, x=99.0, y=99.0, yaw=0.0))  # dup
    twin.send_to(twin_host, twin_port,
                 make_state("car-1", 2, x=88.0, y=88.0, yaw=0.0))  # old
    time.sleep(0.1)

    print("\n--- inject a MALFORMED frame (node must survive) ---")
    with socket.create_connection((twin_host, twin_port), timeout=2.0) as s:
        send_frame(s, b"this is not json at all")
    # car-2 sends a valid message right after, proving the node still works.
    twin.send_to(twin_host, twin_port,
                 make_state("car-2", 1, x=2.0, y=2.0, yaw=1.57))
    time.sleep(0.1)

    print("\n--- let car-1 go silent; sweep should flag it stale ---")
    time.sleep(1.2)  # longer than stale_timeout_s
    sync.sweep_stale()

    print("\n--- final accepted state ---")
    print("  car-1 latest:", sync.latest_state("car-1"))
    print("  car-2 latest:", sync.latest_state("car-2"))

    twin.stop()
    msg_log.stop()
    print("\nDone. See messages.jsonl for the full message log.")


if __name__ == "__main__":
    main()
