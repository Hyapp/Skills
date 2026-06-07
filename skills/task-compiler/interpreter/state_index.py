#!/usr/bin/env python3
"""
State index — read-only index of current execution state.

Auto-discovers wave progress, node results, and artifacts from a session
directory. Main Agent uses this after context compression to restore position.

Usage:
    python state_index.py <session_dir> [--node <id>] [--wave <n>] [--status <s>]

Without flags: full state snapshot.
  --node <id>   Show details for a specific node (stdout result, exit code)
  --wave <n>    Show all nodes in a specific wave
  --status <s>  Filter nodes by status (completed/pending/failed)
"""
import json
import os
import sys
from pathlib import Path


def find_session_dir(raw: str) -> Path:
    """Resolve session dir from name or path."""
    p = Path(raw)
    if p.exists() and p.is_dir():
        return p.resolve()
    # Try under ./output/
    candidate = Path("./output") / raw
    if candidate.exists():
        return candidate.resolve()
    candidate = Path(".") / raw
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


def index_session(session_dir: Path) -> dict:
    plan = read_json(session_dir / "build_plan.json")
    state = None
    try:
        import yaml
        state = yaml.safe_load((session_dir / "execution_state.yaml").read_text(encoding="utf-8"))
    except Exception:
        pass

    if not plan:
        return {"error": "build_plan.json not found"}

    wf = plan.get("workflow", {})
    node_results = plan.get("nodes", {})
    execution_order = plan.get("execution_order", [])
    waves = plan.get("waves", [])
    failed = plan.get("failed_nodes", [])
    skipped = plan.get("skipped_nodes", [])

    # Build per-node index
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

    # Wave index
    wave_index = []
    for i, w in enumerate(waves):
        wave_nodes = []
        all_completed = True
        for nid in w:
            info = nodes_index.get(nid, {"id": nid, "status": "unknown"})
            wave_nodes.append(info)
            if info["status"] != "completed":
                all_completed = False
        wave_status = "completed" if all_completed else "in_progress"
        if state and i < len(state.get("waves", [])):
            wave_status = state["waves"][i].get("status", wave_status)
        wave_index.append({
            "wave": i,
            "status": wave_status,
            "node_count": len(w),
            "nodes": wave_nodes,
        })

    # Artifact index
    artifacts = {}
    ir_path = session_dir / "_ir.yaml"
    if ir_path.exists():
        artifacts["ir"] = str(ir_path.resolve())

    agent_results = {}
    agents_dir = session_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            if agent_dir.is_dir():
                result_file = agent_dir / "result.md"
                if result_file.exists():
                    agent_results[agent_dir.name] = str(result_file.resolve())

    if agent_results:
        artifacts["agent_outputs"] = agent_results

    # Determine current position
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
        summary["failed_nodes"] = [
            {"id": f["id"], "error": f.get("error", "")} for f in failed
        ]
    if skipped:
        summary["skipped_nodes"] = skipped

    result = {
        "summary": summary,
        "waves": wave_index,
        "artifacts": artifacts,
    }

    return result


def show_node(session_dir: Path, node_id: str):
    """Show detailed info for a single node: result, exit code, stderr."""
    info = {"id": node_id}

    result_file = session_dir / "nodes" / node_id / "result"
    if result_file.exists():
        content = result_file.read_text(encoding="utf-8")
        plan = read_json(session_dir / "build_plan.json")
        status = "unknown"
        if plan:
            nr = plan.get("nodes", {}).get(node_id, {})
            status = nr.get("status", "unknown")
        info["status"] = status
        info["result"] = content[:2000]  # Cap display size
        info["result_length"] = len(content)
    else:
        info["status"] = "not_found"

    exit_file = session_dir / "nodes" / node_id / "exit_code"
    if exit_file.exists():
        info["exit_code"] = int(exit_file.read_text().strip())

    stderr_file = session_dir / "nodes" / node_id / "stderr"
    if stderr_file.exists():
        info["stderr"] = stderr_file.read_text(encoding="utf-8")[:1000]

    print(json.dumps(info, indent=2, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    session_dir = Path(sys.argv[1]).resolve()
    if not session_dir.exists():
        session_dir = find_session_dir(sys.argv[1])

    # Parse optional flags
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
        else:
            i += 1

    if show_node_id:
        show_node(session_dir, show_node_id)
        return

    index = index_session(session_dir)

    if filter_wave is not None:
        for ws in index.get("waves", []):
            if ws["wave"] == filter_wave:
                print(json.dumps(ws, indent=2, ensure_ascii=False))
                return
        print(json.dumps({"error": f"wave {filter_wave} not found"}), ensure_ascii=False)
        return

    if filter_status:
        matching = [
            ns for ws in index.get("waves", [])
            for ns in ws["nodes"]
            if ns["status"] == filter_status
        ]
        print(json.dumps(matching, indent=2, ensure_ascii=False))
        return

    print(json.dumps(index, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
