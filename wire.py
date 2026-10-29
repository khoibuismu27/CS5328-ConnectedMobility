"""
wire.py  --  TCP message framing

THE PROBLEM THIS SOLVES
-----------------------
TCP is a *byte stream*, not a message stream. If you send three messages and
then call recv() once on the other side, you might get:
  - all three glued together, or
  - the first one plus half of the second, or
  - just the first 10 bytes of the first one.
TCP guarantees order and delivery, NOT message boundaries.

So you cannot do `msg = sock.recv(4096)` and assume `msg` is one message.
That is the single most common reason a "working on localhost" socket layer
falls apart the moment traffic picks up or runs over a real network.

THE FIX: length-prefixed framing.
Every message on the wire is:  [4-byte big-endian length][that many bytes].
The reader first reads exactly 4 bytes to learn the length, then reads exactly
that many bytes. No guessing, no gluing, no splitting.

This module is pure stdlib and has no Quanser or project dependencies, so it is
trivially unit-testable on its own.
"""

from __future__ import annotations

import socket
import struct

# ">I" = big-endian ("network byte order") unsigned 4-byte int.
# 4 bytes lets a single message be up to ~4 GB, which is far more than enough.
_HEADER = struct.Struct(">I")

# Safety cap: refuse absurd lengths so a corrupt or malicious 4-byte header
# can't make us try to allocate gigabytes. Tune for your real max message size.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024  # 8 MB


class ProtocolError(Exception):
    """Raised when the bytes on the wire don't follow the framing contract."""


def send_frame(sock: socket.socket, payload: bytes) -> None:
    """
    Send one length-prefixed message.

    Uses sendall(), NOT send(). send() may transmit only part of the buffer and
    return how many bytes it actually sent; if you ignore that return value you
    silently truncate messages. sendall() loops until everything is sent or it
    raises. Always use sendall() for message-oriented code.
    """
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"refusing to send {len(payload)} bytes (max {MAX_MESSAGE_BYTES})"
        )
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    """
    Read EXACTLY n bytes, looping until we have them all.

    recv(n) returns *up to* n bytes, not exactly n. On a real network a single
    recv may hand back fewer bytes than asked even for a tiny message, so we
    accumulate in a loop. An empty bytes return means the peer closed the
    connection cleanly -- mid-frame, that's an error for us.
    """
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("peer closed connection mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock: socket.socket) -> bytes:
    """
    Receive one length-prefixed message, or raise.

    Returns the payload bytes (header stripped). Blocks until a full message
    is available. Raises ConnectionError if the peer disconnects, ProtocolError
    if the advertised length is implausible.
    """
    header = _recv_exactly(sock, _HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"incoming frame claims {length} bytes (max {MAX_MESSAGE_BYTES}); "
            "stream is probably out of sync or corrupt"
        )
    return _recv_exactly(sock, length)
