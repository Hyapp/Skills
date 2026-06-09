#!/usr/bin/env python3
"""
State index — unified state management for workflow execution.

Read: auto-discovers wave progress, node results, and artifacts from session dir.
Write: supports dispatch, wave-complete, rollback for state transitions.

Output format: YAML (more compact than JSON, fewer tokens).

Usage:
    python state_index.py <session_dir>                   # Full snapshot
    python state_index.py <session_dir> status            # Compact status
    python state_index.py <session_dir> --node <id>       # Node detail
    python state_index.py <session_dir> --wave <n>        # Wave detail
    python state_index.py <session_dir> --status <s>      # Filter by status
    python state_index.py <session_dir> dispatch <ids>    # Mark nodes dispatched
    python state_index.py <session_dir> dispatch-wave <n>  # Mark all nodes in wave N dispatched
    python state_index.py <session_dir> wave-complete     # Advance to next wave
    python state_index.py <session_dir> rollback <wave>   # Roll back to specific wave
    python state_index.py <session_dir> rollback          # Default: one wave back
"""
import glob
import json
import os
import sys
from pathlib import Path

import yaml

STATE_FILE = "execution_state.yaml"
OUTPUT_DIRS = ["./output", "."]
LATEST_SESSION_FILE = "latest.session"


# ── Helpers ──

def read_build_plan(session_dir: Path) -> dict:
    path = session_dir / "build_plan.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def read_state(session_dir: Path) -> dict | None:
    path = session_dir / STATE_FILE
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_state(session_dir: Path, state: dict):
    path = session_dir / STATE_FILE
    path.write_text(
        yaml.dump(state, allow_unicode=True, default_flow_style=None, sort_keys=False),
        encoding="utf-8",
    )


def find_session_dir(raw: str) -> Path:
    p = Path(raw)
    if p.exists() and p.is_dir():
        return p.resolve()
    for base in [Path("./output"), Path(".")]:
        candidate = base / raw
        if candidate.exists():
            return candidate.resolve()
    print(f"Session directory not found: {raw}", file=sys.stderr)
    sys.exit(1)


def read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def out(data: dict):
    """Print as YAML to stdout."""
    print(yaml.dump(data, allow_unicode=True, default_flow_style=None, sort_keys=False).rstrip())


# ── Index (read) ──

def index_session(session_dir: Path) -> dict:
    plan = read_build_plan(session_dir)
    state = read_state(session_dir)

    if not plan:
        return {"error": "build_plan.json not found"}

    wf = plan.get("workflow", {})
    node_results = plan.get("nodes", {})
    execution_order = plan.get("execution_order", [])
    waves = plan.get("waves", [])
    failed = plan.get("failed_nodes", [])
    skipped = plan.get("skipped_nodes", [])

    nodes_index = {}
    for entry in execution_order:
        nid = entry["id"]
        nr = node_results.get(nid, {})
        nodes_index[nid] = {
            "id": nid,
            "type": entry.get("type", "unknown"),
            "status": nr.get("status", "unknown"),
            "wave": entry.get("wave", -1),
            "has_result": (session_dir / "nodes" / nid / "result").exists(),
            "has_agent_dir": (session_dir / "agents" / nid).exists(),
        }

    wave_index = []
    for i, w in enumerate(waves):
        wave_nodes = [nodes_index.get(nid, {"id": nid, "status": "unknown"}) for nid in w]
        all_completed = all(ns["status"] == "completed" for ns in wave_nodes)

        wave_status = "completed" if all_completed else "in_progress"
        if state and i < len(state.get("waves", [])):
            wave_status = state["waves"][i].get("status", wave_status)

        wave_index.append({
            "wave": i,
            "status": wave_status,
            "node_count": len(w),
            "nodes": wave_nodes,
        })

    artifacts = {}
    ir_path = session_dir / "_ir.yaml"
    if ir_path.exists():
        artifacts["ir"] = str(ir_path.resolve())

    agents_dir = session_dir / "agents"
    if agents_dir.exists():
        agent_outputs = {}
        for ad in sorted(agents_dir.iterdir()):
            if ad.is_dir():
                rf = ad / "result.md"
                if rf.exists():
                    agent_outputs[ad.name] = str(rf.resolve())
        if agent_outputs:
            artifacts["agent_outputs"] = agent_outputs

    current_wave = None
    pending_nodes = []
    completed_count = 0
    total_count = 0
    for ws in wave_index:
        for ns in ws["nodes"]:
            total_count += 1
            if ns["status"] == "completed":
                completed_count += 1
            elif ns["status"] in ("pending", "unknown"):
                if current_wave is None:
                    current_wave = ws["wave"]
                if ws["wave"] == current_wave:
                    pending_nodes.append(ns["id"])

    overall_status = "completed" if current_wave is None else "in_progress"

    summary = {
        "session": session_dir.name,
        "workflow": wf.get("name", "unknown"),
        "mode": wf.get("mode", "static"),
        "status": overall_status,
        "wave_count": len(wave_index),
        "current_wave": current_wave,
        "completed": completed_count,
        "total": total_count,
        "pending_nodes": pending_nodes,
    }
    if failed:
        summary["failed_nodes"] = [{"id": f["id"], "error": f.get("error", "")} for f in failed]
    if skipped:
        summary["skipped_nodes"] = skipped

    return {"summary": summary, "waves": wave_index, "artifacts": artifacts}


# ── Mutations ──

def cmd_init(session_dir: Path):
    """Create execution_state.yaml from build_plan.json."""
    plan = read_build_plan(session_dir)
    if not plan:
        print("build_plan.json not found or empty", file=sys.stderr)
        sys.exit(1)

    waves = plan.get("waves", [])
    execution_order = plan.get("execution_order", [])
    node_index = {e["id"]: e for e in execution_order}
    node_results = plan.get("nodes", {})

    wave_states = []
    for w in waves:
        node_states = []
        for nid in w:
            nr = node_results.get(nid, {})
            ns = nr.get("status", "pending")
            if ns not in ("completed", "failed"):
                ns = "pending"
            node_states.append({
                "id": nid,
                "type": node_index.get(nid, {}).get("type", "unknown"),
                "status": ns,
            })
        ws_status = "completed" if all(ns["status"] == "completed" for ns in node_states) else "pending"
        wave_states.append({
            "wave": len(wave_states),
            "status": ws_status,
            "nodes": node_states,
        })

    state = {
        "workflow": plan.get("workflow", {}).get("name", "unknown"),
        "mode": plan.get("workflow", {}).get("mode", "static"),
        "failed_nodes": plan.get("failed_nodes", []),
        "skipped_nodes": plan.get("skipped_nodes", []),
        "waves": wave_states,
    }
    write_state(session_dir, state)
    out({"action": "init", "status": "ok"})


def cmd_status(session_dir: Path):
    """Print compact execution status."""
    index = index_session(session_dir)
    s = index.get("summary", {})
    pending = s.get("pending_nodes", [])
    cw = s.get("current_wave")

    if cw is None:
        next_action = "all-complete"
    elif pending:
        next_action = f"dispatch: {', '.join(pending)} (wave {cw})"
    else:
        next_action = f"await: wave {cw} in progress"

    output = {
        "session": s.get("session"),
        "workflow": s.get("workflow"),
        "status": s.get("status"),
        "current_wave": cw,
        "completed": s.get("completed"),
        "total": s.get("total"),
        "pending_nodes": pending,
        "next_action": next_action,
    }
    for field in ("failed_nodes", "skipped_nodes"):
        if s.get(field):
            output[field] = s[field]

    out(output)


def show_node(session_dir: Path, node_id: str):
    """Show detailed info for a single node."""
    info = {"id": node_id}
    result_file = session_dir / "nodes" / node_id / "result"
    if result_file.exists():
        content = result_file.read_text(encoding="utf-8")
        plan = read_json(session_dir / "build_plan.json")
        status = "unknown"
        if plan:
            status = plan.get("nodes", {}).get(node_id, {}).get("status", "unknown")
        info["status"] = status
        info["result_preview"] = content[:2000]
        info["result_length"] = len(content)
    else:
        info["status"] = "not_found"

    for name in ("exit_code", "stderr"):
        pf = session_dir / "nodes" / node_id / name
        if pf.exists():
            info[name] = pf.read_text(encoding="utf-8")[:1000]

    out(info)


def cmd_dispatch(session_dir: Path, node_ids: list[str]):
    """Mark nodes as dispatched (running)."""
    state = read_state(session_dir)
    if not state:
        print("No state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    marked = []
    for ws in state["waves"]:
        for ns in ws["nodes"]:
            if ns["id"] in node_ids and ns["status"] == "pending":
                ns["status"] = "dispatched"
                marked.append(ns["id"])
        if any(ns["id"] in node_ids and ns["status"] == "dispatched" for ns in ws["nodes"]):
            if ws["status"] == "pending":
                ws["status"] = "in_progress"

    write_state(session_dir, state)
    out({"action": "dispatch", "dispatched": marked})


def cmd_dispatch_wave(session_dir: Path, wave_num: int):
    """Mark all pending nodes in wave N as dispatched.
    This is the wave-level atomic operation: enter a wave by dispatching
    all its nodes at once. Individual nodes are executed by the main Agent
    (respecting parallel_n), and wave-complete is called when all finish.
    """
    state = read_state(session_dir)
    if not state:
        print("No state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    if wave_num < 0 or wave_num >= len(state["waves"]):
        print(f"Invalid wave index {wave_num}. Valid: 0-{len(state['waves']) - 1}", file=sys.stderr)
        sys.exit(1)

    target = state["waves"][wave_num]
    marked = []
    for ns in target["nodes"]:
        if ns["status"] == "pending":
            ns["status"] = "dispatched"
            marked.append(ns["id"])
    if marked and target["status"] == "pending":
        target["status"] = "in_progress"

    write_state(session_dir, state)

    total = len(target["nodes"])
    output = {
        "action": "dispatch-wave",
        "wave": wave_num,
        "dispatched": marked,
        "total_in_wave": total,
        "status": target["status"],
    }
    out(output)


def cmd_wave_complete(session_dir: Path):
    """Mark current wave as complete and advance."""
    state = read_state(session_dir)
    if not state:
        print("No state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    # Find first wave that is in_progress or has dispatched nodes
    found = False
    for ws in state["waves"]:
        statuses = {ns["status"] for ns in ws["nodes"]}
        if ws["status"] == "in_progress" or "dispatched" in statuses or "running" in statuses:
            for ns in ws["nodes"]:
                if ns["status"] in ("dispatched", "running", "in_progress"):
                    ns["status"] = "completed"
            ws["status"] = "completed"
            found = True
            break

    if not found:
        for ws in state["waves"]:
            if ws["status"] == "pending":
                for ns in ws["nodes"]:
                    ns["status"] = "completed"
                ws["status"] = "completed"
                found = True
                break

    if not found:
        all_done = all(ws["status"] == "completed" for ws in state["waves"])
        out({
            "action": "wave-complete",
            "status": "all-complete" if all_done else "nothing-to-advance",
        })
        sys.exit(0 if all_done else 1)

    for ws in state["waves"]:
        if ws["status"] == "completed":
            for ns in ws["nodes"]:
                if ns["status"] == "pending":
                    ns["status"] = "completed"

    write_state(session_dir, state)

    index = index_session(session_dir)
    s = index.get("summary", {})
    pending = s.get("pending_nodes", [])
    cw = s.get("current_wave")

    output = {
        "action": "wave-complete",
        "status": "in_progress",
        "current_wave": cw,
        "pending_nodes": pending,
        "next_action": f"dispatch: {', '.join(pending)} (wave {cw})" if pending else "await completed",
    }
    out(output)


def cmd_rollback(session_dir: Path, target_wave: int):
    """Roll back to target wave, resetting all later waves.
    Idempotent nodes (idempotent=true in DSL) keep their completed status.
    target_wave=-1 auto-computes current_wave - 1 (Markov: only need one layer back)."""
    state = read_state(session_dir)
    if not state:
        print("No state found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)

    # Read idempotent flag from build_plan execution_order
    plan = read_build_plan(session_dir)
    idempotent_nodes = set()
    for entry in plan.get("execution_order", []):
        if entry.get("idempotent"):
            idempotent_nodes.add(entry["id"])

    waves = state["waves"]

    # Auto: one wave back from current
    if target_wave < 0:
        index = index_session(session_dir)
        cw = index.get("summary", {}).get("current_wave")
        target_wave = max(0, cw - 1) if cw is not None else 0

    if target_wave < 0 or target_wave >= len(waves):
        print(f"Invalid wave index {target_wave}. Valid: 0-{len(waves) - 1}", file=sys.stderr)
        sys.exit(1)

    affected = []
    skipped = []
    for ws in waves:
        if ws["wave"] >= target_wave:
            ws["status"] = "pending"
            for ns in ws["nodes"]:
                if ns["status"] in ("completed", "dispatched", "running", "in_progress"):
                    if ns["status"] == "completed" and ns["id"] in idempotent_nodes:
                        skipped.append(ns["id"])
                    else:
                        ns["status"] = "pending"
                        affected.append(ns["id"])

    write_state(session_dir, state)

    output = {
        "action": "rollback",
        "target_wave": target_wave,
        "affected_nodes": affected,
        "skipped_idempotent": skipped,
        "next_action": (
            f"re-dispatch wave {target_wave}: {', '.join(affected)}" if affected
            else f"no nodes to re-run at wave {target_wave}"
        ),
    }
    if skipped:
        output["note"] = f"{len(skipped)} idempotent node(s) skipped: {', '.join(skipped)}"

    out(output)


# ── Recovery ──

def cmd_recover(output_base: Path | None = None):
    """Find all in-progress sessions and report recoverable state.

    Scans output directories for execution_state.yaml with status=in_progress.
    Returns YAML with recoverable sessions, each containing current_wave,
    pending_nodes, and next_action for immediate resume.

    When no session is in_progress, checks latest.session for a completed
    session and reports it as the most recent execution.
    """
    scan_dirs = []
    if output_base:
        scan_dirs.append(output_base.resolve())
    else:
        for d in OUTPUT_DIRS:
            p = Path(d)
            if p.exists():
                scan_dirs.append(p.resolve())

    recoverable = []
    latest = None
    latest_path = None

    for base in scan_dirs:
        for state_file in sorted(glob.glob(str(base / "**" / STATE_FILE), recursive=True)):
            sp = Path(state_file)
            try:
                st = yaml.safe_load(sp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(st, dict):
                continue

            session_dir = sp.parent
            status = st.get("status", "unknown")

            if status == "in_progress":
                idx = index_session(session_dir)
                s = idx.get("summary", {})
                pending = s.get("pending_nodes", [])
                cw = s.get("current_wave")
                recoverable.append({
                    "session": session_dir.name,
                    "path": str(session_dir.resolve()),
                    "workflow": st.get("workflow", "unknown"),
                    "current_wave": cw,
                    "completed": s.get("completed"),
                    "total": s.get("total"),
                    "pending_nodes": pending,
                    "next_action": (
                        f"dispatch: {', '.join(pending)} (wave {cw})" if pending and cw is not None
                        else "wave-complete" if cw is not None
                        else "all-complete"
                    ),
                    "failed_nodes": s.get("failed_nodes", []),
                })
            elif status == "completed":
                # Track latest completed session for reference
                if latest is None or session_dir.stat().st_mtime > latest_path.stat().st_mtime if latest_path else True:
                    latest = {
                        "session": session_dir.name,
                        "path": str(session_dir.resolve()),
                        "workflow": st.get("workflow", "unknown"),
                        "status": "completed",
                    }
                    latest_path = session_dir

    result = {"recoverable_sessions": recoverable}
    if latest:
        result["latest_completed"] = latest

    # Also check latest.session file
    for base in scan_dirs:
        lsf = base / LATEST_SESSION_FILE
        if lsf.exists():
            try:
                last_name = lsf.read_text(encoding="utf-8").strip()
                if last_name:
                    result["latest_session_file"] = str(lsf.resolve())
                    # Check if the latest session is already in recoverable
                    if not any(s["session"] == last_name for s in recoverable):
                        last_dir = base / last_name
                        if last_dir.exists():
                            last_state = last_dir / STATE_FILE
                            if last_state.exists():
                                try:
                                    lst = yaml.safe_load(last_state.read_text(encoding="utf-8"))
                                    if isinstance(lst, dict):
                                        result["latest_session_state"] = lst.get("status", "unknown")
                                except Exception:
                                    pass
            except Exception:
                pass
            break

    out(result)


def auto_recover(session_dir: Path) -> dict | None:
    """Try to auto-recover an in-progress session.
    Returns the recovery action dict, or None if not recoverable.
    """
    state_file = session_dir / STATE_FILE
    if not state_file.exists():
        return None

    try:
        st = yaml.safe_load(state_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(st, dict) or st.get("status") != "in_progress":
        return None

    # Read build_plan to verify it still exists
    plan_file = session_dir / "build_plan.json"
    if not plan_file.exists():
        return None

    return cmd_recover_inner(session_dir, st)


def cmd_recover_inner(session_dir: Path, st: dict) -> dict:
    """Inner recovery logic - produce resume action."""
    idx = index_session(session_dir)
    s = idx.get("summary", {})
    pending = s.get("pending_nodes", [])
    cw = s.get("current_wave")

    return {
        "action": "recover",
        "session": session_dir.name,
        "workflow": st.get("workflow", "unknown"),
        "current_wave": cw,
        "completed": s.get("completed"),
        "total": s.get("total"),
        "pending_nodes": pending,
        "next_action": (
            f"dispatch: {', '.join(pending)} (wave {cw})" if pending and cw is not None
            else "wave-complete" if cw is not None
            else "all-complete"
        ),
        "failed_nodes": s.get("failed_nodes", []),
        "skipped_nodes": s.get("skipped_nodes", []),
        "session_dir": str(session_dir.resolve()),
    }


# ── Main ──

def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    # Special case: recover scans all sessions, doesn't take a session dir
    if sys.argv[1] == "recover":
        output_base = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
        cmd_recover(Path(output_base) if output_base else None)
        return

    session_dir = Path(sys.argv[1]).resolve()
    if not session_dir.exists():
        session_dir = find_session_dir(sys.argv[1])

    action = None
    action_args = []
    show_node_id = None
    filter_wave = None
    filter_status = None

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--node" and i + 1 < len(args):
            show_node_id = args[i + 1]
            i += 2
        elif args[i] == "--wave" and i + 1 < len(args):
            filter_wave = int(args[i + 1])
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            filter_status = args[i + 1]
            i += 2
        elif args[i] in ("init", "status", "wave-complete"):
            action = args[i]
            i += 1
        elif args[i] == "dispatch-wave" and i + 1 < len(args):
            action = "dispatch-wave"
            action_args = [int(args[i + 1])]
            i += 2
        elif args[i] == "rollback":
            action = "rollback"
            if i + 1 < len(args) and args[i + 1].lstrip("-").isdigit():
                action_args = [args[i + 1]]
                i += 2
            else:
                action_args = []
                i += 1
        elif args[i] == "dispatch":
            action = "dispatch"
            action_args = args[i + 1:]
            break
        else:
            i += 1

    if show_node_id:
        show_node(session_dir, show_node_id)
        return

    if filter_wave is not None:
        index = index_session(session_dir)
        for ws in index.get("waves", []):
            if ws["wave"] == filter_wave:
                out(ws)
                return
        out({"error": f"wave {filter_wave} not found"})
        return

    if filter_status:
        index = index_session(session_dir)
        matching = [ns for ws in index.get("waves", []) for ns in ws["nodes"] if ns["status"] == filter_status]
        out({"nodes": matching})
        return

    if action == "init":
        cmd_init(session_dir)
    elif action == "status":
        cmd_status(session_dir)
    elif action == "dispatch":
        cmd_dispatch(session_dir, action_args)
    elif action == "dispatch-wave":
        cmd_dispatch_wave(session_dir, action_args[0])
    elif action == "wave-complete":
        cmd_wave_complete(session_dir)
    elif action == "rollback":
        target = int(action_args[0]) if action_args else -1  # -1 = auto (one wave back)
        cmd_rollback(session_dir, target)
    else:
        out(index_session(session_dir))


if __name__ == "__main__":
    main()
