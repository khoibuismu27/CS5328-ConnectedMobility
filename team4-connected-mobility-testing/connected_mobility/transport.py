"""
Connected Mobility - Mock TCP broadcast transport with IP filter.

*** THIS IS A SIMULATOR, NOT THE PRODUCTION SOCKET LAYER. ***

The real Sprint-1 transport opens TCP sockets on the lab Wi-Fi network: a car
broadcasts a message and every car receives it, but a car only *acts* on a
message when the destination IP matches its own (the "IP filter"). Messages
also sync to the central node / Digital Twin.

For automated testing we replace the OS sockets with an in-memory MockBus that
preserves exactly that behavior (broadcast delivery + per-node IP filter)
without needing real hardware or the lab network. Swapping the real socket
transport in later does not change the message schema, the registry, the IP
filter logic, or the command/telemetry handling that the tests exercise.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .message import BROADCAST, CENTRAL, Message, parse_message, MessageError
from .registry import EntityRegistry


class Node:
    """A network participant (a car or the central node) on the MockBus."""

    def __init__(self, entity_id: str, ip: str, registry: EntityRegistry) -> None:
        self.entity_id = entity_id
        self.ip = ip
        self.registry = registry
        registry.register(entity_id, ip)
        # Messages this node accepted after the IP filter.
        self.acted: List[Message] = []
        # Raw frames this node received but dropped (filtered out or invalid).
        self.dropped: List[bytes] = []
        self._bus: Optional["MockBus"] = None
        # Optional hook invoked with each accepted Message.
        self.on_accept: Optional[Callable[[Message], None]] = None

    def attach(self, bus: "MockBus") -> None:
        self._bus = bus

    def _accepts(self, msg: Message) -> bool:
        """IP filter: does this node act on the message?

        A node acts when the destination resolves to its own IP, when the
        message is addressed to its entity id directly, or when it is a
        broadcast. The central node additionally accepts CENTRAL-addressed
        messages.
        """
        if msg.dst == BROADCAST:
            return True
        if msg.dst == self.entity_id:
            return True
        if msg.dst == CENTRAL and self.entity_id == CENTRAL:
            return True
        # IP-based match: resolve the destination entity's registered IP.
        dst_ip = self.registry.lookup_ip(msg.dst)
        return dst_ip is not None and dst_ip == self.ip

    def deliver(self, raw: bytes) -> None:
        """Called by the bus for every broadcast frame."""
        try:
            msg = parse_message(raw)
        except MessageError:
            self.dropped.append(raw)
            return
        if self._accepts(msg):
            self.acted.append(msg)
            if self.on_accept is not None:
                self.on_accept(msg)
        else:
            self.dropped.append(raw)

    def broadcast(self, raw: bytes) -> None:
        """Send a frame to every node on the bus (including self-exclusion)."""
        if self._bus is None:
            raise RuntimeError(f"node {self.entity_id} is not attached to a bus")
        self._bus.broadcast(raw, sender=self)


class MockBus:
    """In-memory broadcast medium standing in for the lab TCP network."""

    def __init__(self) -> None:
        self.nodes: List[Node] = []
        # Every raw frame put on the wire, for evidence/inspection.
        self.frames: List[bytes] = []

    def add(self, node: Node) -> Node:
        node.attach(self)
        self.nodes.append(node)
        return node

    def broadcast(self, raw: bytes, sender: Optional[Node] = None) -> None:
        self.frames.append(raw)
        for node in self.nodes:
            if node is sender:
                continue  # a car does not act on its own broadcast
            node.deliver(raw)
