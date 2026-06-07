#!/usr/bin/env python3
"""Default output validator for agent nodes.

Fixed, idempotent validator built into task-compiler.
Checks each listed file exists and is non-empty.

Usage:
    python validate_output.py <file1> [<file2> ...]

Returns:
    exit 0: all files valid
    exit 1: any file missing or empty, errors on stdout
"""
import sys
import os


def main():
    files = sys.argv[1:]
    if not files:
        print("Usage: validate_output.py <file1> [<file2> ...]")
        sys.exit(1)

    errors = []
    for path in files:
        if not os.path.exists(path):
            errors.append(f"output 文件不存在: {path}")
        else:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if not content.strip():
                errors.append(f"输出文件为空: {path}")

    if errors:
        print("\n".join(errors))
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
