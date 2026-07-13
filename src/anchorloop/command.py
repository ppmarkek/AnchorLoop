from __future__ import annotations

import os


_DISPLAY_COMMAND_ENV = "ANCHORLOOP_COMMAND"
_DEFAULT_COMMAND = "anchor"
_MAX_COMMAND_LENGTH = 512


def command_prefix() -> str:
    """Return the safe command prefix used only in human-facing guidance."""

    candidate = os.environ.get(_DISPLAY_COMMAND_ENV, _DEFAULT_COMMAND).strip()
    if (
        not candidate
        or len(candidate) > _MAX_COMMAND_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        return _DEFAULT_COMMAND
    return candidate


def display_command(arguments: str = "") -> str:
    prefix = command_prefix()
    return f"{prefix} {arguments}" if arguments else prefix
