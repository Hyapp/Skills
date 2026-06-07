#!/usr/bin/env python3
"""Runtime IR validation for render-feishu plugin.

Checks IR structure before execution. Called by the main Agent in Phase 3
before running render.py. Exit 0 = valid, exit 1 = invalid (stderr has details).

Usage:
    python validate.py <session_dir>

The session directory must contain _ir.yaml (the IR file).
"""
import json
import sys
from pathlib import Path

import yaml


def main():
    if len(sys.argv) < 2:
        print("Usage: validate.py <session_dir>", file=sys.stderr)
        sys.exit(1)

    session_dir = Path(sys.argv[1])
    ir_path = session_dir / "_ir.yaml"

    errors = []

    # 1. IR file exists
    if not ir_path.exists():
        errors.append(f"IR file not found: {ir_path}")
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    # 2. Parseable YAML
    try:
        ir = yaml.safe_load(ir_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        errors.append(f"IR YAML parse error: {e}")
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    if not isinstance(ir, dict):
        errors.append("IR root is not a dict")
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    # 3. Required fields
    if not ir.get("title"):
        errors.append("missing 'title'")

    sections = ir.get("sections", [])
    if not sections:
        errors.append("sections is empty or missing")

    # 4. sheet_ref validation
    sheets_data = ir.get("context", {}).get("sheets", {})
    for i, sec in enumerate(sections):
        if sec.get("type") == "sheet":
            ref = sec.get("sheet_ref")
            if not ref:
                errors.append(f"sections[{i}]: sheet missing 'sheet_ref'")
            elif ref not in sheets_data:
                errors.append(f"sections[{i}]: sheet_ref '{ref}' not found in context.sheets")
            else:
                data = sheets_data[ref]
                if not data.get("headers"):
                    errors.append(f"sections[{i}]: sheet_ref '{ref}' has no headers")
                if not data.get("rows"):
                    errors.append(f"sections[{i}]: sheet_ref '{ref}' has no rows")

    # 5. render-order path validation
    for i, sec in enumerate(sections):
        if sec.get("type") == "render-order":
            path = sec.get("path", "")
            if not path:
                errors.append(f"sections[{i}]: render-order missing 'path'")
            else:
                target = (session_dir / path).resolve()
                if not target.exists():
                    errors.append(f"sections[{i}]: render-order path not found: {path}")

    if errors:
        print("IR validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    print("IR validation passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
