#!/usr/bin/env python3
"""
Execution state management — deterministic state machine for workflow execution.

Usage:
    python execution_state.py <session_dir> <action> [options]

Actions:
    init                     Create execution_state.yaml from build_plan.json
    status                   Print current wave, pending nodes, next action
    wave-complete            Mark current wave done, advance, output next dispatch
    rollback <wave_index>    Roll back to given wave, list nodes to re-run
"""
import json
import os
import sys
from pathlib import Path

STATE_FILE = "execution_state.yaml"


def read_build_plan(session_dir: Path) -> dict:
    path = session_dir / "build_plan.json"
    if not path.exists():
        print(f"build_plan.json not found: {path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def read_state(session_dir: Path) -> dict | None:
    path = session_dir / STATE_FILE
    if not path.exists():
        return None
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_state(session_dir: Path, state: dict):
    import yaml
    path = session_dir / STATE_FILE
    path.write_text(
        yaml.dump(state, allow_unicode=True, default_flow_style=None, sort_keys=False),
        encoding="utf-8",
    )
    print(f"  [state] written to {STATE_FILE}")


# ── Init ──

def cmd_init(session_dir: Path):
    plan = read_build_plan(session_dir)
    waves = plan.get("waves", [])
    execution_order = plan.get("execution_order", [])
    node_index = {e["id"]: e for e in execution_order}

    wave_states = []
    for w in waves:
        node_states = []
        for nid in w:
            entry = node_index.get(nid, {})
            node_states.append({
                "id": nid,
                "type": entry.get("type", "unknown"),
                "status": "pending",
            })
        wave_states.append({
            "wave": len(wave_states),
            "status": "pending",
            "nodes": node_states,
        })

    state = {
        "workflow": plan.get("workflow", {}).get("name", "unknown"),
        "mode": plan.get("workflow", {}).get("mode", "static"),
        "failed_nodes": plan.get("failed_nodes", []),
        "skipped_nodes": plan.get("skipped_nodes", []),
        "waves": wave_states,
    }

    # Detect already-completed from node_results
    node_results = plan.get("nodes", {})
    for ws in wave_states:
        all_done = True
        for ns in ws["nodes"]:
            nr = node_results.get(ns["id"], {})
            if nr.get("status") == "completed":
                ns["status"] = "completed"
            elif nr.get("status") == "failed":
                ns["status"] = "failed"
                all_done = False
            else:
                all_done = False
        if all_done:
            ws["status"] = "completed"

    write_state(session_dir, state)
    cmd_status(session_dir)


# ── Status ──

def cmd_status(session_dir: Path):
    state = read_state(session_dir)
    if not state:
        print("No execution state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    current_wave = None
    completed_count = 0
    total_count = 0
    pending_nodes = []
    next_action = "all-complete"

    for ws in state["waves"]:
        for ns in ws["nodes"]:
            total_count += 1
            if ns["status"] == "completed":
                completed_count += 1
            elif ns["status"] == "pending":
                if current_wave is None:
                    current_wave = ws["wave"]
                if ws["wave"] == current_wave:
                    pending_nodes.append(ns["id"])

    if current_wave is None:
        next_action = "all-complete"
    elif pending_nodes:
        next_action = f"dispatch: {', '.join(pending_nodes)} (wave {current_wave})"
    elif current_wave is not None and not pending_nodes:
        # All nodes in current wave dispatched but not all completed
        next_action = f"await: wave {current_wave} in progress, check SubAgent results"

    output = {
        "session": session_dir.name,
        "workflow": state["workflow"],
        "current_wave": current_wave,
        "status": "completed" if next_action == "all-complete" else "in_progress",
        "completed_count": completed_count,
        "total_count": total_count,
        "pending_nodes": pending_nodes,
        "next_action": next_action,
    }
    if state.get("failed_nodes"):
        output["failed_nodes"] = state["failed_nodes"]
    if state.get("skipped_nodes"):
        output["skipped_nodes"] = state["skipped_nodes"]

    print(json.dumps(output, ensure_ascii=False))

    # Return exit code for terminal states
    if next_action == "all-complete":
        sys.exit(0)


# ── Wave Complete ──

def cmd_wave_complete(session_dir: Path):
    state = read_state(session_dir)
    if not state:
        print("No execution state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    # Find current wave (first not-completed wave with any node running)
    found_active = False
    for ws in state["waves"]:
        statuses = {ns["status"] for ns in ws["nodes"]}
        if ws["status"] == "in_progress" or "dispatched" in statuses or "running" in statuses:
            # Mark all nodes in this wave as completed (caller confirms success)
            for ns in ws["nodes"]:
                if ns["status"] in ("dispatched", "running", "in_progress"):
                    ns["status"] = "pending"
            ws["status"] = "completed"
            found_active = True
            break

    if not found_active:
        # No active wave — look for first wave that's fully pending
        for ws in state["waves"]:
            if ws["status"] == "pending":
                ws["status"] = "completed"
                found_active = True
                break

    if not found_active:
        # Nothing to advance — check if all are complete
        all_done = all(ws["status"] == "completed" for ws in state["waves"])
        if all_done:
            print(json.dumps({"status": "all-complete", "next_action": "all-complete"}, ensure_ascii=False))
            write_state(session_dir, state)
            sys.exit(0)
        else:
            print("No active wave found and not all complete.", file=sys.stderr)
            sys.exit(1)

    write_state(session_dir, state)

    # Mark all pending/completed nodes in earlier waves as completed for accuracy
    for ws in state["waves"]:
        if ws["status"] == "completed":
            for ns in ws["nodes"]:
                if ns["status"] == "pending":
                    ns["status"] = "completed"

    write_state(session_dir, state)
    cmd_status(session_dir)


# ── Mark dispatched nodes ──

def cmd_dispatch(session_dir: Path, node_ids: list[str]):
    """Mark specific nodes as dispatched (running) in the current wave."""
    state = read_state(session_dir)
    if not state:
        print("No execution state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    marked = []
    for ws in state["waves"]:
        for ns in ws["nodes"]:
            if ns["id"] in node_ids:
                if ns["status"] == "pending":
                    ns["status"] = "dispatched"
                    marked.append(ns["id"])

    # Mark wave as in_progress if any node dispatched
    if marked:
        for ws in state["waves"]:
            dispatched_here = any(
                ns["id"] in node_ids and ns["status"] == "dispatched"
                for ns in ws["nodes"]
            )
            if dispatched_here and ws["status"] == "pending":
                ws["status"] = "in_progress"

    write_state(session_dir, state)
    print(json.dumps({"dispatched": marked, "status": "ok"}, ensure_ascii=False))


# ── Rollback ──

def cmd_rollback(session_dir: Path, target_wave: int):
    state = read_state(session_dir)
    if not state:
        print("No execution state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    waves = state["waves"]
    if target_wave < 0 or target_wave >= len(waves):
        print(f"Invalid wave index {target_wave}. Valid: 0-{len(waves) - 1}", file=sys.stderr)
        sys.exit(1)

    affected = []
    for ws in waves:
        if ws["wave"] >= target_wave:
            # Reset wave status
            original_status = ws["status"]
            ws["status"] = "pending" if ws["wave"] == target_wave else "pending"

            for ns in ws["nodes"]:
                if ns["status"] == "completed" or ns["status"] == "dispatched":
                    ns["status"] = "pending"
                    affected.append(ns["id"])

    write_state(session_dir, state)

    output = {
        "action": "rollback",
        "target_wave": target_wave,
        "affected_count": len(affected),
        "affected_nodes": affected,
        "next_action": f"re-dispatch wave {target_wave}: {', '.join(affected)}" if affected else f"nothing to re-run at wave {target_wave}",
    }
    print(json.dumps(output, ensure_ascii=False))


# ── Main ──

def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    session_dir = Path(sys.argv[1]).resolve()
    action = sys.argv[2]

    if not session_dir.exists():
        print(f"Session directory not found: {session_dir}", file=sys.stderr)
        sys.exit(1)

    if action == "init":
        cmd_init(session_dir)
    elif action == "status":
        cmd_status(session_dir)
    elif action == "wave-complete":
        cmd_wave_complete(session_dir)
    elif action == "dispatch":
        cmd_dispatch(session_dir, sys.argv[3:])
    elif action == "rollback":
        if len(sys.argv) < 4:
            print("Usage: execution_state.py <session_dir> rollback <wave_index>", file=sys.stderr)
            sys.exit(1)
        cmd_rollback(session_dir, int(sys.argv[3]))
    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
