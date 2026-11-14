"""
Connected Mobility - Entity / IP registry.

Maps logical entity IDs (e.g. "carA", "carB", "CENTRAL") to the IP addresses
they occupy on the lab's local Wi-Fi/TCP network, and back again. The socket
layer uses this to implement the IP filter: a broadcast message is acted on
only by the car whose registered IP matches the message destination.

This is shared infrastructure used by both the transport layer and command
validation (a command to an unregistered destination must be rejected).
"""

from __future__ import annotations

import ipaddress
from typing import Dict, Optional


class RegistryError(ValueError):
    """Raised on invalid registration input or lookup misuse."""


class EntityRegistry:
    """Bidirectional entity_id <-> ip_address map with validation."""

    def __init__(self) -> None:
        self._id_to_ip: Dict[str, str] = {}
        self._ip_to_id: Dict[str, str] = {}

    @staticmethod
    def _normalize_ip(ip: str) -> str:
        """Validate and canonicalize an IPv4/IPv6 address string."""
        try:
            return str(ipaddress.ip_address(ip))
        except ValueError as exc:
            raise RegistryError(f"invalid IP address: {ip!r}") from exc

    def register(self, entity_id: str, ip: str) -> None:
        """Register (or re-register) an entity at an IP address.

        Rejects empty IDs and malformed IPs. If the IP is already bound to a
        *different* entity, the old binding is removed so the reverse lookup
        never returns a stale entity for a reused address.
        """
        if not entity_id or not isinstance(entity_id, str):
            raise RegistryError(f"entity_id must be a non-empty string, got {entity_id!r}")
        ip = self._normalize_ip(ip)

        # Drop any previous IP this entity held, and any previous entity at this IP.
        old_ip = self._id_to_ip.get(entity_id)
        if old_ip is not None and old_ip != ip:
            self._ip_to_id.pop(old_ip, None)
        old_id = self._ip_to_id.get(ip)
        if old_id is not None and old_id != entity_id:
            self._id_to_ip.pop(old_id, None)

        self._id_to_ip[entity_id] = ip
        self._ip_to_id[ip] = entity_id

    def lookup_ip(self, entity_id: str) -> Optional[str]:
        """Return the IP for an entity, or None if it is not registered."""
        return self._id_to_ip.get(entity_id)

    def lookup_entity(self, ip: str) -> Optional[str]:
        """Return the entity_id bound to an IP, or None if unbound."""
        try:
            ip = self._normalize_ip(ip)
        except RegistryError:
            return None
        return self._ip_to_id.get(ip)

    def is_registered(self, entity_id: str) -> bool:
        return entity_id in self._id_to_ip

    def unregister(self, entity_id: str) -> None:
        ip = self._id_to_ip.pop(entity_id, None)
        if ip is not None:
            self._ip_to_id.pop(ip, None)

    def __len__(self) -> int:
        return len(self._id_to_ip)
