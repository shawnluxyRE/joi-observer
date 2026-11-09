"""Bounded, read-only filesystem worker; never imported to perform an operation."""

import errno
import json
import os
import sys


LIMIT = 1024 * 1024
PROC_FILES = frozenset(("/proc/stat", "/proc/meminfo", "/proc/self/mountinfo"))


def main() -> int:
    try:
        if len(sys.argv) != 3:
            raise ValueError("Invalid operation")
        operation, path = sys.argv[1:]
        if operation == "read" and path in PROC_FILES:
            with open(path, "rb") as stream:
                result = stream.read(LIMIT + 1)
            if len(result) > LIMIT:
                raise OSError(errno.EFBIG, "Output limit")
        elif operation == "statvfs" and path.startswith("/") and "\x00" not in path:
            value = os.statvfs(path)
            result = json.dumps([value.f_frsize, value.f_blocks, value.f_bfree]).encode("ascii")
        else:
            raise ValueError("Invalid operation")
        sys.stdout.buffer.write(result)
        return 0
    except (OSError, ValueError, AttributeError) as error:
        # Only a numeric errno crosses this private protocol. Paths and OS error
        # messages must never leak to the application's terminal or error log.
        sys.stderr.write(str(getattr(error, "errno", None) or errno.EINVAL))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
