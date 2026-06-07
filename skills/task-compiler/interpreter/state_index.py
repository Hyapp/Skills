#!/usr/bin/env python3
"""
State index — general-purpose key-value state store for workflow execution.

Main Agent uses this to track arbitrary state across context compressions:
wave progress, generated resource tokens, error counts, file paths, etc.

Storage: <session_dir>/state_index.json

Usage:
    python state_index.py <session_dir> <action> [args]

Actions:
    set <key> <value>          Store a value (JSON-decoded if possible)
    get <key>                  Print value (exit 1 if not found)
    delete <key>               Remove a key
    push <key> <value>         Append to a list at key (creates if missing)
    list <key>                 Print list items (one per line)
    incr <key> [step]          Increment numeric value (default step=1)
    keys [glob]                List keys matching glob (default: *)
    snapshot                   Dump all key-value pairs as JSON
    log [limit]                Show last N state changes (default: 20)
    info                       Print stats (key count, file size, modified keys)
"""
import json
import os
import sys
import datetime
from pathlib import Path

INDEX_FILE = "state_index.json"


def _load(session_dir: Path) -> dict:
    path = session_dir / INDEX_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"data": {}, "log": []}
    return {"data": {}, "log": []}


def _save(session_dir: Path, idx: dict):
    path = session_dir / INDEX_FILE
    path.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")


def _log(idx: dict, action: str, key: str, value):
    idx.setdefault("log", []).append({
        "ts": datetime.datetime.now().isoformat(),
        "action": action,
        "key": key,
        "value": value,
    })
    # Keep log bounded: last 5000 entries
    if len(idx["log"]) > 5000:
        idx["log"] = idx["log"][-5000:]


def _parse_value(s: str):
    """Try JSON decode, fallback to raw string."""
    if not s:
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return s


def _format_value(v) -> str:
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def cmd_set(session_dir: Path, key: str, value_raw: str):
    idx = _load(session_dir)
    value = _parse_value(value_raw)
    idx["data"][key] = value
    _log(idx, "set", key, value)
    _save(session_dir, idx)


def cmd_get(session_dir: Path, key: str):
    idx = _load(session_dir)
    val = idx.get("data", {}).get(key)
    if val is None:
        print(f"Key not found: {key}", file=sys.stderr)
        sys.exit(1)
    print(_format_value(val))


def cmd_delete(session_dir: Path, key: str):
    idx = _load(session_dir)
    if key in idx.get("data", {}):
        del idx["data"][key]
        _log(idx, "delete", key, None)
        _save(session_dir, idx)


def cmd_push(session_dir: Path, key: str, value_raw: str):
    idx = _load(session_dir)
    value = _parse_value(value_raw)
    lst = idx["data"].setdefault(key, [])
    if not isinstance(lst, list):
        lst = [lst]
    lst.append(value)
    idx["data"][key] = lst
    _log(idx, "push", key, value)
    _save(session_dir, idx)


def cmd_list(session_dir: Path, key: str):
    idx = _load(session_dir)
    val = idx.get("data", {}).get(key)
    if val is None:
        sys.exit(0)
    if isinstance(val, list):
        for item in val:
            print(_format_value(item))
    else:
        print(_format_value(val))


def cmd_incr(session_dir: Path, key: str, step_raw: str = "1"):
    idx = _load(session_dir)
    step = int(step_raw)
    current = idx.get("data", {}).get(key, 0)
    if not isinstance(current, (int, float)):
        current = 0
    new_val = current + step
    idx["data"][key] = new_val
    _log(idx, "incr", key, new_val)
    _save(session_dir, idx)
    print(new_val)


def cmd_keys(session_dir: Path, pattern: str = "*"):
    import fnmatch
    idx = _load(session_dir)
    keys = sorted(idx.get("data", {}).keys())
    for k in keys:
        if fnmatch.fnmatch(k, pattern):
            print(k)


def cmd_snapshot(session_dir: Path):
    idx = _load(session_dir)
    print(json.dumps(idx.get("data", {}), indent=2, ensure_ascii=False))


def cmd_log(session_dir: Path, limit_raw: str = "20"):
    idx = _load(session_dir)
    limit = max(1, int(limit_raw))
    entries = idx.get("log", [])
    for entry in entries[-limit:]:
        ts = entry.get("ts", "")
        action = entry.get("action", "")
        key = entry.get("key", "")
        val = entry.get("value", "")
        if isinstance(val, str):
            val_preview = val[:80]
        else:
            val_preview = json.dumps(val, ensure_ascii=False)[:80]
        print(f"{ts}  {action:8s}  {key} = {val_preview}")


def cmd_info(session_dir: Path):
    idx = _load(session_dir)
    data = idx.get("data", {})
    log = idx.get("log", [])
    path = session_dir / INDEX_FILE
    size = path.stat().st_size if path.exists() else 0
    info = {
        "key_count": len(data),
        "file_size": size,
        "log_entries": len(log),
        "recent_keys": sorted(data.keys())[-20:],
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    session_dir = Path(sys.argv[1]).resolve()
    action = sys.argv[2]

    if not session_dir.exists():
        print(f"Session directory not found: {session_dir}", file=sys.stderr)
        sys.exit(1)

    if action == "set" and len(sys.argv) >= 5:
        cmd_set(session_dir, sys.argv[3], sys.argv[4])
    elif action == "get" and len(sys.argv) >= 4:
        cmd_get(session_dir, sys.argv[3])
    elif action == "delete" and len(sys.argv) >= 4:
        cmd_delete(session_dir, sys.argv[3])
    elif action == "push" and len(sys.argv) >= 5:
        cmd_push(session_dir, sys.argv[3], sys.argv[4])
    elif action == "list" and len(sys.argv) >= 4:
        cmd_list(session_dir, sys.argv[3])
    elif action == "incr":
        step = sys.argv[4] if len(sys.argv) >= 5 else "1"
        cmd_incr(session_dir, sys.argv[3], step)
    elif action == "keys":
        pattern = sys.argv[3] if len(sys.argv) >= 4 else "*"
        cmd_keys(session_dir, pattern)
    elif action == "snapshot":
        cmd_snapshot(session_dir)
    elif action == "log":
        limit = sys.argv[3] if len(sys.argv) >= 4 else "20"
        cmd_log(session_dir, limit)
    elif action == "info":
        cmd_info(session_dir)
    else:
        print(f"Unknown action or missing args: {action}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
