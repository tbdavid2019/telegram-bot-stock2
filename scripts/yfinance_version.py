"""Compare stable PyPI releases numerically; reject ambiguous version input."""

import re
import sys


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise ValueError(f"Unsupported stable version: {value!r}")
    parts = [int(part) for part in value.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(current, latest):
    return version_key(latest) > version_key(current)


if __name__ == "__main__":
    try:
        sys.exit(0 if is_newer(sys.argv[1], sys.argv[2]) else 1)
    except (ValueError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
