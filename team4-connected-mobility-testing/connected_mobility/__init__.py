"""Connected Mobility reference module (Team 4, Lyle-CS Smart City Digital Twin).

Reference implementation of the Sprint-1 messaging layer used for the
Assignment 3 testing deliverable: message schema + parsing, entity/IP registry,
command validation, a mock TCP broadcast transport with IP filter, and
central/Digital-Twin sync.
"""

from .message import (
    SCHEMA_VERSION,
    BROADCAST,
    CENTRAL,
    Message,
    MessageType,
    MessageError,
    parse_message,
    serialize_message,
)
from .registry import EntityRegistry, RegistryError
from .command import (
    validate_command,
    ValidationResult,
    MAX_ABS_THROTTLE,
    MAX_ABS_STEERING,
    SUPPORTED_VERBS,
)
from .transport import MockBus, Node
from .central_sync import CentralSync, MockDigitalTwin

__all__ = [
    "SCHEMA_VERSION", "BROADCAST", "CENTRAL",
    "Message", "MessageType", "MessageError", "parse_message", "serialize_message",
    "EntityRegistry", "RegistryError",
    "validate_command", "ValidationResult",
    "MAX_ABS_THROTTLE", "MAX_ABS_STEERING", "SUPPORTED_VERBS",
    "MockBus", "Node",
    "CentralSync", "MockDigitalTwin",
]
