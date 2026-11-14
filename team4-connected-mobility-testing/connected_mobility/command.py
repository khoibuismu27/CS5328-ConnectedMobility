"""
Connected Mobility - Command validation.

Before a COMMAND message is relayed to a car and turned into actuation, it must
be validated. An invalid or unsafe command must be rejected and never
dispatched. This is Team 4's "command validation" unit.

Safety envelope is taken directly from the LAIL DEVELOPER_GUIDE and the PAL
QCar control example (05_pal_virtual_qcar_control.py), which limit absolute
throttle to 0.1 and absolute steering to 0.5 rad. These are hard safety limits,
not style choices: a command outside them must be refused, not clamped
silently, so the fault is visible.

Validation also enforces that:
  * the message really is a COMMAND;
  * the command verb is one the platform supports;
  * the destination entity is registered (we know where to send it);
  * the command is not stale (old timestamp => possibly a replayed/queued
    command that no longer reflects intent).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .message import Message, MessageType
from .registry import EntityRegistry


# Hard safety limits (DEVELOPER_GUIDE section 4; PAL example limits).
MAX_ABS_THROTTLE = 0.1          # unitless PAL throttle command
MAX_ABS_STEERING = 0.5          # radians

# A command older than this many seconds is considered stale.
DEFAULT_MAX_AGE_S = 2.0

# Supported command verbs.
SUPPORTED_VERBS = frozenset({"DRIVE", "STOP", "SET_LEDS"})


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a command. `ok` True means safe to dispatch."""
    ok: bool
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        return self.ok


def validate_command(
    msg: Message,
    registry: EntityRegistry,
    *,
    now: Optional[float] = None,
    max_age_s: float = DEFAULT_MAX_AGE_S,
) -> ValidationResult:
    """Validate a COMMAND message against the safety envelope and registry.

    Returns ValidationResult(ok=True) when the command is safe to dispatch,
    otherwise ValidationResult(ok=False, reason=...). Never raises on a merely
    invalid command -- the caller inspects the result and logs the reason.
    """
    if now is None:
        now = time.time()

    if msg.type is not MessageType.COMMAND:
        return ValidationResult(False, f"not a COMMAND message (type={msg.type.value})")

    # Destination must be a registered entity we can route to.
    if not registry.is_registered(msg.dst):
        return ValidationResult(False, f"destination not registered: {msg.dst!r}")

    # Staleness check (reject future-dated and too-old commands).
    age = now - msg.ts
    if age > max_age_s:
        return ValidationResult(False, f"stale command: age {age:.3f}s > {max_age_s}s")
    if age < -max_age_s:
        return ValidationResult(False, f"command timestamp is in the future by {-age:.3f}s")

    payload = msg.payload
    verb = payload.get("verb")
    if verb not in SUPPORTED_VERBS:
        return ValidationResult(False, f"unsupported command verb: {verb!r}")

    if verb == "DRIVE":
        throttle = payload.get("throttle")
        steering = payload.get("steering")
        if not isinstance(throttle, (int, float)) or isinstance(throttle, bool):
            return ValidationResult(False, f"throttle must be numeric, got {throttle!r}")
        if not isinstance(steering, (int, float)) or isinstance(steering, bool):
            return ValidationResult(False, f"steering must be numeric, got {steering!r}")
        if abs(throttle) > MAX_ABS_THROTTLE:
            return ValidationResult(
                False,
                f"throttle {throttle} exceeds safety limit +/-{MAX_ABS_THROTTLE}",
            )
        if abs(steering) > MAX_ABS_STEERING:
            return ValidationResult(
                False,
                f"steering {steering} exceeds safety limit +/-{MAX_ABS_STEERING} rad",
            )

    # STOP and SET_LEDS carry no motion risk beyond the above; accept them.
    return ValidationResult(True)
