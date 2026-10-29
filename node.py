"""
node.py  --  the TCP endpoint each process runs

THE PROBLEMS THIS SOLVES
------------------------
A Node both LISTENS for inbound connections and can DIAL out to peers, which is
what "car-to-car communication" needs -- every car is both a sender and a
receiver. The failure modes this gets right, each one a classic "works on my
machine, not on the lab floor" bug:

  - Binds to 0.0.0.0 by default, not 127.0.0.1. Binding to localhost means
    nothing else on the lab network can reach you; it only ever works when
    client and server are the same machine. This is probably the #1 reason a
    socket layer "runs" in testing and then can't connect on the floor.

  - Sets SO_REUSEADDR before bind, so restarting the process doesn't fail with
    "Address already in use" for a minute while the OS holds the old port.

  - One thread per accepted connection, so a slow or silent peer can't freeze
    the whole node. The listener thread is a daemon so it dies with the process.

  - Every inbound frame is parsed through schema.Message.from_bytes, which
    validates it. A malformed packet raises SchemaError and is dropped with a
    log line -- it does not crash the node. One bad peer can't take you down.

  - Clean shutdown: a stop() that closes the listening socket and joins threads,
    plus context-manager support so `with Node(...) as n:` always cleans up.

This is deliberately threads-not-asyncio: it's easier for a team to read, and
the per-connection model maps cleanly onto "a handful of cars." If you outgrow
it, the framing/schema/registry layers underneath are transport-agnostic.
"""

from __future__ import annotations

import socket
import threading
from typing import Callable

from schema import Message, SchemaError
from wire import send_frame, recv_frame, ProtocolError

# A handler takes a validated Message plus the peer's (host, port) address.
Handler = Callable[[Message, tuple[str, int]], None]


class Node:
    def __init__(
        self,
        node_id: str,
        bind_host: str = "0.0.0.0",
        bind_port: int = 0,
        handler: Handler | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.node_id = node_id
        self.bind_host = bind_host
        self.bind_port = bind_port
        self._handler: Handler = handler or (lambda msg, addr: None)
        self._log = on_log or (lambda line: None)

        self._listen_sock: socket.socket | None = None
        self._listen_thread: threading.Thread | None = None
        self._conn_threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.actual_port: int | None = None  # resolved after start() for port 0

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow immediate reuse of the address on restart.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.bind_port))
        sock.listen(16)
        # When bind_port was 0 the OS picked a free port; record the real one.
        self.actual_port = sock.getsockname()[1]
        self._listen_sock = sock
        self._log(f"[{self.node_id}] listening on "
                  f"{self.bind_host}:{self.actual_port}")

        self._listen_thread = threading.Thread(
            target=self._accept_loop, name=f"{self.node_id}-accept", daemon=True
        )
        self._listen_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._listen_sock is not None:
            # Closing the listening socket unblocks accept().
            try:
                self._listen_sock.close()
            except OSError:
                pass
        if self._listen_thread is not None:
            self._listen_thread.join(timeout=2.0)
        for t in list(self._conn_threads):
            t.join(timeout=2.0)
        self._log(f"[{self.node_id}] stopped")

    def __enter__(self) -> "Node":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---- inbound --------------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._listen_sock is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._listen_sock.accept()
            except OSError:
                break  # socket closed by stop()
            t = threading.Thread(
                target=self._serve_conn, args=(conn, addr),
                name=f"{self.node_id}-conn", daemon=True,
            )
            self._conn_threads.append(t)
            t.start()

    def _serve_conn(self, conn: socket.socket, addr: tuple[str, int]) -> None:
        with conn:
            while not self._stop.is_set():
                try:
                    raw = recv_frame(conn)
                except (ConnectionError, ProtocolError, OSError):
                    break  # peer gone or stream desynced; drop the connection
                try:
                    msg = Message.from_bytes(raw)
                except SchemaError as exc:
                    # Bad packet: log and keep serving. Do NOT crash.
                    self._log(f"[{self.node_id}] dropped bad message from "
                              f"{addr}: {exc}")
                    continue
                try:
                    self._handler(msg, addr)
                except Exception as exc:  # a handler bug must not kill the node
                    self._log(f"[{self.node_id}] handler error on "
                              f"{msg.msg_type} from {msg.sender_id}: {exc}")

    # ---- outbound -------------------------------------------------------

    def send_to(self, host: str, port: int, msg: Message,
                timeout: float = 3.0) -> bool:
        """
        Open a short-lived connection, send one framed message, close.

        Returns True on success, False on any network failure (logged). A
        connection-per-message model is simple and robust for low-rate
        telemetry; for high rates, keep a pooled connection per peer instead.
        """
        try:
            with socket.create_connection((host, port), timeout=timeout) as s:
                send_frame(s, msg.to_bytes())
            return True
        except (OSError, ProtocolError, SchemaError) as exc:
            self._log(f"[{self.node_id}] send to {host}:{port} failed: {exc}")
            return False
