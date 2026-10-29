"""
sync_channel.py  --  central/twin sync channel + log every message

THE PROBLEMS THIS SOLVES
------------------------
This is the piece that takes car state messages and keeps the twin's view of
each car current -- the "digital shadow" half of the loop in your slides. The
hazards here are exactly the ones README section 11 and the DEVELOPER_GUIDE
call out, and they're where naive sync code quietly corrupts the twin:

  1. Out-of-order / duplicate packets. TCP keeps bytes in order within ONE
     connection, but this node takes a fresh connection per message and may
     hear from many senders, so at the APPLICATION level you still see
     duplicates and reordering. We track the highest seq seen per sender and
     drop anything not strictly newer. (README 11: "reject duplicate or
     out-of-order sequence numbers.")

  2. Stale senders. A car that goes silent must not leave the twin frozen at a
     last-known pose forever and believing it's current. Each sender has a
     last-update time; mark_stale() flags senders past a timeout so downstream
     logic can react (hold, warn, stop). (README 11: "detect stale data with a
     timeout.")

  3. Logging in the hot path. "Log every message" is a real requirement, but a
     synchronous file write per message will drag your update rate down. We log
     through a background queue+thread, so the receive path just enqueues and
     moves on. Logs are JSON Lines (one JSON object per line) -- trivially
     greppable and replayable.

  4. Ownership. apply_to_twin() is the ONLY place pose is written, and it's a
     clearly marked stub. The DEVELOPER_GUIDE is explicit that the twin design
     is Team 3's / your team's call, and warns never to let two things drive the
     same actor. So this module decides WHAT the latest valid state is and hands
     it off; it does not itself fight QVL or PAL for control of the actor.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from schema import Message, MSG_STATE, MSG_HELLO, MSG_HEARTBEAT


# --------------------------------------------------------------------------
# Message logger: "log every message", off the hot path.
# --------------------------------------------------------------------------

class MessageLog:
    """
    Append-only JSON Lines logger backed by a background writer thread.

    The receive path calls record() which just puts a dict on a queue and
    returns. A single daemon thread drains the queue and writes. This keeps the
    file open once (not reopened per message) and keeps disk latency out of the
    control loop.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._q: queue.Queue[dict | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="msglog", daemon=True
        )
        self._started = False

    def start(self) -> None:
        self._started = True
        self._thread.start()

    def record(self, direction: str, msg: Message,
               peer: tuple[str, int] | None = None) -> None:
        """direction is 'rx' or 'tx'. Non-blocking."""
        self._q.put({
            "logged_ts": time.time(),
            "dir": direction,
            "peer": f"{peer[0]}:{peer[1]}" if peer else None,
            "msg_type": msg.msg_type,
            "sender_id": msg.sender_id,
            "seq": msg.seq,
            "sent_ts": msg.sent_ts,
            "body": msg.body,
        })

    def stop(self) -> None:
        if self._started:
            self._q.put(None)  # sentinel tells the writer to flush and exit
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            while True:
                item = self._q.get()
                if item is None:
                    f.flush()
                    return
                f.write(json.dumps(item) + "\n")
                f.flush()  # flush each line so a crash still leaves a full log


# --------------------------------------------------------------------------
# Per-sender tracking.
# --------------------------------------------------------------------------

@dataclass
class SenderState:
    sender_id: str
    last_seq: int = -1          # highest seq accepted so far
    last_update_ts: float = 0.0  # when we last accepted a message (our clock)
    latest: dict = field(default_factory=dict)  # last accepted state body
    stale: bool = False


# --------------------------------------------------------------------------
# The sync channel.
# --------------------------------------------------------------------------

class SyncChannel:
    def __init__(
        self,
        log: MessageLog,
        stale_timeout_s: float = 2.0,
        apply_to_twin: Callable[[str, dict], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self._log = log
        self._stale_timeout = stale_timeout_s
        self._senders: dict[str, SenderState] = {}
        self._lock = threading.Lock()
        self._diag = on_log or (lambda line: None)
        # The ONE place pose reaches the twin. Default stub just reports; your
        # team wires this to the actual twin update (QVL pose OR PAL, never both).
        self._apply = apply_to_twin or self._default_apply

    def _default_apply(self, sender_id: str, state: dict) -> None:
        self._diag(f"[twin] would update {sender_id} -> "
                   f"x={state.get('x'):.3f} y={state.get('y'):.3f} "
                   f"yaw={state.get('yaw'):.3f}")

    def handle(self, msg: Message, peer: tuple[str, int]) -> None:
        """
        Entry point wired into a Node as its handler. Logs every message, then
        routes by type. State messages run the dedup/ordering gate before they
        are allowed to touch the twin.
        """
        self._log.record("rx", msg, peer)

        if msg.msg_type == MSG_STATE:
            self._handle_state(msg)
        elif msg.msg_type == MSG_HEARTBEAT:
            self._mark_seen(msg.sender_id, msg.seq, accept_state=False)
        elif msg.msg_type == MSG_HELLO:
            self._diag(f"[sync] hello from {msg.sender_id} "
                       f"@ {msg.body.get('host')}:{msg.body.get('port')}")

    def _handle_state(self, msg: Message) -> None:
        with self._lock:
            st = self._senders.setdefault(
                msg.sender_id, SenderState(msg.sender_id)
            )
            # Ordering/dedup gate: accept ONLY strictly newer sequence numbers.
            if msg.seq <= st.last_seq:
                self._diag(f"[sync] drop stale/dup seq {msg.seq} from "
                           f"{msg.sender_id} (have {st.last_seq})")
                return
            st.last_seq = msg.seq
            st.last_update_ts = time.time()
            st.latest = dict(msg.body)
            st.stale = False
            state_copy = dict(st.latest)

        # Hand the accepted state to the twin OUTSIDE the lock, so a slow twin
        # update can't block other senders' messages.
        self._apply(msg.sender_id, state_copy)

    def _mark_seen(self, sender_id: str, seq: int, accept_state: bool) -> None:
        with self._lock:
            st = self._senders.setdefault(sender_id, SenderState(sender_id))
            st.last_update_ts = time.time()
            st.stale = False

    # ---- staleness ------------------------------------------------------

    def sweep_stale(self) -> list[str]:
        """
        Flag senders we haven't heard from within stale_timeout_s. Call this
        periodically (a timer thread, or once per control tick). Returns the
        ids newly marked stale, so the caller can react (hold pose, stop, warn).
        """
        now = time.time()
        newly_stale = []
        with self._lock:
            for st in self._senders.values():
                if not st.stale and st.last_update_ts > 0 and \
                        (now - st.last_update_ts) > self._stale_timeout:
                    st.stale = True
                    newly_stale.append(st.sender_id)
        for sid in newly_stale:
            self._diag(f"[sync] sender {sid} is STALE "
                       f"(> {self._stale_timeout}s silent)")
        return newly_stale

    def latest_state(self, sender_id: str) -> dict | None:
        with self._lock:
            st = self._senders.get(sender_id)
            return dict(st.latest) if st and st.latest else None
