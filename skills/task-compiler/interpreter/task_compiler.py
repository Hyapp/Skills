#!/usr/bin/env python3
"""
vDSL Interpreter -- deterministic DSL evaluator for Vibe Workflows.

Usage:
    python task_compiler.py workflow.json [--output-dir ./output]

Input:  JSON file (Agent converts YAML -> JSON before calling this)
Output: build_plan.json + per-node result files + per-agent parameter files
Flags:
    --agent-runtime <runtime>  Mark build_plan.json with the target agent platform.
                               Supported: codex, trae, claude.
                               The interpreter does NOT execute agent nodes;
                               this field tells the main Agent which SubAgent
                               dispatch instructions to follow in Phase 3.

    --output-validate          Force enable output validation for agent nodes
                               (dynamic mode defaults to on, static to off).
    --no-output-validate       Force disable output validation.

Dependencies: Python 3 stdlib only (json, subprocess, glob, pathlib, os, sys)
"""

import datetime
import json
import os
import shutil
import sys
from pathlib import Path

from validate import validate, resolve_dag as _resolve_dag, discover_plugins
from dag import compute_waves
from eval import (
    expand_expr, eval_program, eval_text, prepare_agent,
    eval_expand, resolve_aggregate,
    infer_depends_from_from, infer_depends_from_captures,
    verify_outputs, check_node_cache, load_session_state,
)

# ── Build Plan Size Limits ───────────────────────────────────────────────

MAX_RESULT_DISPLAY_SIZE = 100 * 1024  # 100KB -- truncate node results in build_plan
RESULT_FILE_REF = "result_file"        # key for the file path to the full result


def _truncate_for_plan(nid: str, output_dir: Path, result: dict) -> dict:
    """Return a build_plan-safe copy of a node result dict.

    If the 'result' field exceeds MAX_RESULT_DISPLAY_SIZE, replace it
    with a truncated preview and add a 'result_file' reference pointing
    to the full result on disk.
    """
    out = dict(result)
    body = out.get("result", "")
    if isinstance(body, str) and len(body) > MAX_RESULT_DISPLAY_SIZE:
        half = MAX_RESULT_DISPLAY_SIZE // 2
        out["result"] = body[:half] + f"\n... [truncated {len(body)} chars at {MAX_RESULT_DISPLAY_SIZE}B]\n" + body[-half:]
        result_path = output_dir / "nodes" / nid / "result"
        out[RESULT_FILE_REF] = str(result_path.resolve())
    return out


def prepare_plugin(node: dict, output_dir: Path, available_plugins: dict) -> dict:
    """Validate plugin reference and prepare execution parameters.

    Returns:
        dict with status="pending" and plugin_params for the main Agent.
    """
    plugin_name = node["plugin"]
    plugin = available_plugins.get(plugin_name)
    if not plugin:
        return {"status": "failed", "error": f"plugin '{plugin_name}' not found"}

    # Read plugin.yaml for execute section
    plugin_dir = Path(plugin["dir"])
    plugin_yaml = plugin_dir / "plugin.yaml"
    try:
        raw = plugin_yaml.read_text(encoding="utf-8")
    except OSError as e:
        return {"status": "failed", "error": f"cannot read plugin.yaml: {e}"}

    # Minimal parsing of execute.command
    execute_cmd = None
    in_execute = False
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped == "execute:":
            in_execute = True
            continue
        if in_execute:
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("- ") and not line.startswith(" "):
                in_execute = False
                continue
            if stripped.startswith("command:"):
                execute_cmd = stripped[len("command:"):].strip().strip("\"'")
                break

    if not execute_cmd:
        return {"status": "failed", "error": f"plugin '{plugin_name}': no execute.command in plugin.yaml"}

    # plugin input IR path resolved from depends_on upstream via Phase 3 SubAgent
    input_ir = ""

    # Build final command (expand template vars)
    final_cmd = execute_cmd.replace("{plugin_dir}", str(plugin_dir.resolve()))
    final_cmd = final_cmd.replace("{input_ir}", input_ir if input_ir else "{input_ir}")

    result = {
        "status": "pending",
        "plugin_params": {
            "plugin": plugin_name,
            "command": final_cmd,
            "plugin_dir": str(plugin_dir.resolve()),
            "input_ir": input_ir,
        },
    }
    return result


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} workflow.json [--output-dir ./output] [--session name] [--debug] [--clean] [--on-failure abort|retry|pause] [--max-retries N] [--agent-runtime codex|trae|claude] [--output-validate|--no-output-validate]", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    base_dir = Path("./output")
    session_name = None
    debug = False
    clean = False
    cli_on_failure = None
    cli_max_retries = 3
    agent_runtime = None
    output_validate = None  # None=auto(dynamic=on,static=off), True=force, False=off
    for i, arg in enumerate(sys.argv):
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            base_dir = Path(sys.argv[i + 1])
        if arg == "--session" and i + 1 < len(sys.argv):
            session_name = sys.argv[i + 1]
        if arg == "--debug":
            debug = True
        if arg == "--clean":
            clean = True
        if arg == "--on-failure" and i + 1 < len(sys.argv):
            cli_on_failure = sys.argv[i + 1]
        if arg == "--max-retries" and i + 1 < len(sys.argv):
            cli_max_retries = int(sys.argv[i + 1])
        if arg == "--agent-runtime" and i + 1 < len(sys.argv):
            agent_runtime = sys.argv[i + 1]
        if arg == "--output-validate":
            output_validate = True
        if arg == "--no-output-validate":
            output_validate = False

    # Validate agent_runtime
    VALID_AGENT_RUNTIMES = {"codex", "trae", "claude"}
    if agent_runtime and agent_runtime not in VALID_AGENT_RUNTIMES:
        print(f"Error: invalid agent_runtime '{agent_runtime}'. Valid options: {', '.join(sorted(VALID_AGENT_RUNTIMES))}", file=sys.stderr)
        sys.exit(1)

    base_dir.mkdir(parents=True, exist_ok=True)

    # ── Plugin discovery ──
    skill_dir = Path(__file__).resolve().parent.parent
    available_plugins = discover_plugins(skill_dir)
    if available_plugins:
        print(f"  [plugins] found: {', '.join(available_plugins.keys())}")

    if session_name:
        output_dir = base_dir / session_name
        reuse = output_dir.exists()
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rand = os.urandom(2).hex()
        output_dir = base_dir / f"{ts}_{rand}"
        reuse = False

    output_dir.mkdir(parents=True, exist_ok=True)

    (base_dir / "latest.session").write_text(output_dir.name, encoding="utf-8")

    if reuse:
        print(f"  [session] {output_dir.name} (reused)")
    else:
        print(f"  [session] {output_dir.name}")

    # Read input (YAML preferred, JSON fallback)
    try:
        raw = input_path.read_text(encoding="utf-8")
        if input_path.suffix in (".yaml", ".yml"):
            import yaml as _yaml
            workflow = _yaml.safe_load(raw)
        else:
            workflow = json.loads(raw)
    except Exception as e:
        print(f"Error reading input: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate
    errors = validate(workflow, available_plugins if available_plugins else None)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    wf = workflow["workflow"]
    nodes = wf["nodes"]
    variables = wf.get("variables", {})

    if debug:
        print("  [debug mode] - hash verification disabled, modified intermediates accepted")

    # Resolve on_failure priority: node > workflow > CLI > default(abort)
    wf_on_failure = wf.get("on_failure") or cli_on_failure or "abort"
    wf_max_retries = wf.get("max_retries", cli_max_retries)
    if wf_on_failure not in ("abort", "retry", "pause"):
        print(f"Error: invalid on_failure '{wf_on_failure}'", file=sys.stderr)
        sys.exit(1)

    # Auto-inject depends_on
    infer_depends_from_from(nodes)
    infer_depends_from_captures(nodes)

    # Build context
    context = {
        "workflow": {
            "name": wf["name"],
            "version": wf.get("version", ""),
            "description": wf.get("description", ""),
        },
        "variables": variables,
        "nodes": {},
    }

    # Preload existing session state
    if session_name:
        existing = load_session_state(output_dir)
        if existing:
            context["nodes"].update(existing)
            print(f"  [session state] loaded {len(existing)} existing node(s)")

    # ── Main Execution Loop ──

    expand_ids = {n["id"] for n in nodes if n["type"] == "expand"}
    executable = [n for n in nodes if n["type"] != "expand"]
    if not executable and not expand_ids:
        print("No executable nodes found", file=sys.stderr)
        sys.exit(1)

    try:
        order = _resolve_dag(executable) if executable else []
    except ValueError as e:
        print(f"DAG error: {e}", file=sys.stderr)
        sys.exit(1)

    id_map = {n["id"]: n for n in nodes}
    node_results = {}
    failed_nodes = []
    skipped_nodes = []  # Fix #1: track skipped nodes separately
    executed = set()
    consumed_expands = set()
    expand_template_maps = {}
    total_nodes_injected = 0

    def resolve_on_failure(node: dict) -> tuple:
        nf = node.get("on_failure") or wf_on_failure
        nr = node.get("max_retries", wf_max_retries)
        return nf, nr

    def process_node(nid: str):
        """Execute or prepare a single node, with cache, retry, and failure handling."""
        nonlocal failed_nodes, skipped_nodes
        node = id_map[nid]
        ntype = node["type"]
        on_failure, max_retries = resolve_on_failure(node)

        # Check cache first
        cached = check_node_cache(nid, node, output_dir, debug)
        if cached is not None:
            node_results[nid] = cached
            context["nodes"][nid] = cached
            executed.add(nid)
            tag = "cached:debug" if debug else "cached"
            print(f"  [{tag}] {nid}")
            if cached.get("status") == "completed":
                c_capture = node.get("capture")
                if c_capture and "result" in cached:
                    context["variables"][c_capture] = cached["result"]
                    cached["capture"] = c_capture
            return

        node_dir = output_dir / "nodes" / nid
        if node_dir.exists():
            print(f"  [cache-miss] {nid} - re-executing (hash mismatch)", file=sys.stderr)

        # Execute
        result = {}
        if ntype == "program":
            node["command"] = expand_expr(node["command"], context)
            last_error = None
            for attempt in range(1, max_retries + 1):
                result = eval_program(node, output_dir)
                if result.get("status") == "completed":
                    missing = verify_outputs(node)
                    if missing:
                        result["status"] = "failed"
                        result["error"] = f"Missing outputs: {'; '.join(missing)}"
                if result.get("status") != "failed":
                    break
                last_error = result.get("error", "unknown")
                if on_failure == "retry" and attempt < max_retries:
                    print(f"  [retry] {nid} attempt {attempt}/{max_retries} failed, retrying...")
                else:
                    break
            if result.get("status") == "failed" and last_error:
                result["error"] = last_error

        elif ntype == "text":
            result = eval_text(node, context, output_dir)

        elif ntype == "agent":
            # Resolve output validation: explicit flag > node config > mode default
            ov = output_validate
            if ov is None:
                node_output = node.get("output", {})
                if isinstance(node_output, dict) and node_output.get("files"):
                    ov = True
                else:
                    ov = (wf.get("mode", "static") == "dynamic")
            result = prepare_agent(node, context, output_dir, id_map,
                                   output_validate=ov, workflow_mode=wf.get("mode", "static"))

        elif ntype == "plugin":
            result = prepare_plugin(node, output_dir, available_plugins)

        node_results[nid] = result
        context["nodes"][nid] = result
        executed.add(nid)
        if "_cached" not in result:
            print(f"  [exec] {nid}")

        # ── Failure handling (BEFORE capture) ──
        # Fix #2: handle failure before capturing, so skip/abort doesn't poison context
        if result.get("status") == "failed":
            if on_failure == "abort":
                print(f"Node '{nid}' failed (on_failure=abort). Aborting.", file=sys.stderr)
                sys.exit(1)
            elif on_failure == "retry":
                failed_nodes.append({"id": nid, "error": result.get("error", "unknown"),
                                     "retries_exhausted": True})
                print(f"Node '{nid}' failed after {max_retries} retries.", file=sys.stderr)
            elif on_failure == "pause":
                result["status"] = "paused"
                result["on_failure"] = "pause"
                print(f"Node '{nid}' paused (on_failure=pause).", file=sys.stderr)
            elif on_failure == "skip":
                skipped_nodes.append(nid)
                print(f"Node '{nid}' failed (on_failure=skip). Skipping.")
            else:
                failed_nodes.append({"id": nid, "error": result.get("error", "unknown")})

        # Fix #2: capture only on success (failure handlers above may have changed status)
        if result.get("status") == "completed":
            capture = node.get("capture")
            if capture and "result" in result:
                context["variables"][capture] = result["result"]
                result["capture"] = capture

    # ── Phase 1: Execute static nodes ──
    i = 0
    while i < len(order):
        nid = order[i]

        if nid in executed:
            i += 1
            continue

        node = id_map.get(nid)
        if node is None:
            i += 1
            continue

        if node["type"] == "expand":
            i += 1
            continue

        process_node(nid)
        i += 1

    # ── Phase 2: Resolve expand nodes ──
    while consumed_expands != expand_ids:
        expanded_this_round = False
        for n in list(nodes):
            if n["type"] != "expand" or n["id"] in consumed_expands:
                continue

            # Fix #3: check both key existence AND success status
            deps = n.get("depends_on", [])
            if not all(
                dep in context["nodes"] and context["nodes"][dep].get("status") == "completed"
                for dep in deps
            ):
                continue

            new_nodes, tmpl_map = eval_expand(n, nodes, context, output_dir)
            expand_template_maps[n["id"]] = tmpl_map
            consumed_expands.add(n["id"])
            if new_nodes:
                total_nodes_injected += len(new_nodes)
                nodes.extend(new_nodes)
                id_map.update({nn["id"]: nn for nn in new_nodes})
                expanded_this_round = True
                print(f"  Expand '{n['id']}': generated {len(new_nodes)} nodes")

        if not expanded_this_round:
            unexpanded = expand_ids - consumed_expands
            if unexpanded:
                unexp_detail = []
                for eid in sorted(unexpanded):
                    en = id_map[eid]
                    missing = [d for d in en.get("depends_on", []) if d not in context["nodes"]]
                    unexp_detail.append(f"'{eid}' (missing deps: {missing})")
                print(f"Warning: {len(unexpanded)} expand node(s) not resolved: {', '.join(unexp_detail)}", file=sys.stderr)
            break

    # Execute all injected non-expand nodes
    injected = [n for n in nodes if n["id"] not in executed and n["type"] != "expand"]
    if injected:
        try:
            new_order = _resolve_dag(injected)
        except ValueError as e:
            print(f"DAG error after expand: {e}", file=sys.stderr)
            sys.exit(1)

        for nid in new_order:
            if nid not in executed:
                process_node(nid)

    # ── Phase 3: Resolve aggregate nodes ──
    aggregate_nodes = []
    if consumed_expands:
        for n in list(nodes):
            if n["type"] != "expand":
                continue
            tmpl_map = expand_template_maps.get(n["id"])
            if tmpl_map is None:
                continue
            agg = resolve_aggregate(n, tmpl_map, id_map)
            aggregate_nodes.extend(agg)

    if aggregate_nodes:
        for agg in aggregate_nodes:
            id_map[agg["id"]] = agg
        nodes.extend(aggregate_nodes)

        try:
            agg_order = _resolve_dag(aggregate_nodes)
        except ValueError as e:
            print(f"DAG error (aggregate): {e}", file=sys.stderr)
            sys.exit(1)

        for nid in agg_order:
            if nid not in executed:
                process_node(nid)
        print(f"  Aggregate: {len(aggregate_nodes)} aggregate nodes executed")

    # ── Wave computation ──
    all_node_ids = [n["id"] for n in nodes if n["id"] in node_results and n["type"] != "expand"]
    wave_of, waves = compute_waves(nodes, all_node_ids)

    # ── Build Plan ──
    execution_order = []
    for nid in node_results:
        node = id_map[nid]
        entry = {
            "id": nid,
            "type": node["type"],
            "status": node_results[nid].get("status", "unknown"),
            "wave": wave_of.get(nid, -1),
        }
        recovery = node.get("recovery", "auto")
        if recovery != "auto":
            entry["recovery"] = recovery
        manifest = node.get("manifest")
        if manifest:
            entry["manifest"] = manifest
        # Fix #5: use "is not None" so empty dict {} is preserved
        requires = node.get("requires")
        if requires is not None:
            entry["requires"] = requires
        if node["type"] == "agent":
            entry["agent_params"] = node_results[nid].get("agent_params")
            fo = node_results[nid].get("from_outputs")
            if fo:
                entry["from_outputs"] = fo
            fa = node_results[nid].get("from_all_outputs")
            if fa:
                entry["from_all_outputs"] = fa

        if node["type"] == "plugin":
            pp = node_results[nid].get("plugin_params")
            if pp:
                entry["plugin_params"] = pp
        if node.get("outputs"):
            entry["outputs"] = node["outputs"]
        of_val, _ = resolve_on_failure(node)
        if of_val != "abort":
            entry["on_failure"] = of_val
        execution_order.append(entry)

    # Fix #6: truncate large results in build_plan, full data is on disk
    truncated_node_results = {
        nid: _truncate_for_plan(nid, output_dir, node_results[nid])
        for nid in node_results
    }

    wf_agent_runtime = wf.get("agent_runtime")
    if wf_agent_runtime and wf_agent_runtime not in VALID_AGENT_RUNTIMES:
        print(f"Error: workflow.agent_runtime '{wf_agent_runtime}' is not valid. Valid options: {', '.join(sorted(VALID_AGENT_RUNTIMES))}", file=sys.stderr)
        sys.exit(1)

    final_agent_runtime = wf_agent_runtime or agent_runtime or "codex"

    plan = {
        "workflow": {
            "name": wf["name"],
            "variables": variables,
            "mode": wf.get("mode", "static"),
            "parallel_n": wf.get("parallel", 1),
            "agent_runtime": final_agent_runtime,
        },
        "nodes": truncated_node_results,
        "waves": waves,
        "execution_order": execution_order,
        "failed_nodes": failed_nodes,
        "skipped_nodes": skipped_nodes,
    }

    plan_path = output_dir / "build_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Plan written to {plan_path}")
    print(f"  Nodes total: {len(node_results)}")
    agent_count = sum(1 for nid in node_results if id_map[nid]["type"] == "agent")
    print(f"  Agent nodes: {agent_count}")
    plugin_count = sum(1 for nid in node_results if id_map[nid]["type"] == "plugin")
    if plugin_count:
        print(f"  Plugin nodes: {plugin_count} (pending)")
    print(f"  Expanded from: {total_nodes_injected} nodes injected by expand")
    print(f"  Failed: {len(failed_nodes)}")
    if skipped_nodes:
        print(f"  Skipped: {len(skipped_nodes)} - {skipped_nodes}")

    has_pending = any(
        node_results.get(nid, {}).get("status") in ("pending", "paused")
        for nid in node_results
    )

    # Fix #1: also guard clean against skipped nodes
    if clean and not failed_nodes and not skipped_nodes and not has_pending:
        shutil.rmtree(output_dir)
        print(f"  [clean] removed {output_dir}")

    if failed_nodes:
        sys.exit(1)


if __name__ == "__main__":
    main()
