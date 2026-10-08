"""A single exception type for user-facing failures.

Anything the CLI catches and prints as a clean error message must be an
Ipadmp4Error -- a condition the user caused and can fix (a missing file, a
file ffprobe can't read, ffmpeg not installed). Anything else is a bug and
should crash with a full traceback instead of being hidden.
"""

from __future__ import annotations


class Ipadmp4Error(Exception):
    """A user-facing error: bad input or a missing tool -- not a bug."""
