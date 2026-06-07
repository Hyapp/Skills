#!/usr/bin/env python3
"""Environment precheck for render-feishu plugin.

Run before any wave starts (Phase 3 entry). Checks:
- lark-cli is in PATH
- lark-cli can execute (auth not expired)

Exit 0 = all checks pass, Exit 1 = environment not ready (stderr has details).

Usage:
    python check_env.py <session_dir>
"""
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    session_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    errors = []

    # 1. lark-cli in PATH
    lc = shutil.which("lark-cli")
    if not lc:
        errors.append("lark-cli not found in PATH")
    else:
        # 2. lark-cli can execute (basic smoke test)
        try:
            r = subprocess.run(
                [lc, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                errors.append(f"lark-cli --version failed (exit {r.returncode}): {r.stderr.strip()}")
        except FileNotFoundError:
            errors.append("lark-cli not found in PATH")
        except subprocess.TimeoutExpired:
            errors.append("lark-cli --version timed out")
        except OSError as e:
            errors.append(f"lark-cli execution error: {e}")

    if errors:
        print("Environment precheck failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("Environment precheck passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
