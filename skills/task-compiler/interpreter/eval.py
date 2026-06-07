"""Node evaluation — program, text, agent, expand, aggregation, cache."""

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import glob as fnmatch_glob
from pathlib import Path


# ── Expression Expansion ───────────────────────────────────────────────────

def expand_expr(template: str, context: dict) -> str:
    """Replace {{ path.to.key }} with values from context dict."""
    def _resolve(path: str):
        parts = path.strip().split(".")
        val = context
        for p in parts:
            if isinstance(val, dict):
                val = val.get(p)
            else:
                return f"{{{{ {path} }}}}"
            if val is None:
                return f"{{{{ {path} }}}}"
        if isinstance(val, (list, dict)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    pattern = re.compile(r"\{\{\s*([^}]+)\s*\}\}")

    def _replacer(m):
        return _resolve(m.group(1))

    return pattern.sub(_replacer, template)


# ── Node Evaluation ────────────────────────────────────────────────────────

def eval_program(node: dict, output_dir: Path) -> dict:
    """Execute a shell command, capture output."""
    cmd = node["command"]
    nid = node["id"]

    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        result = {
            "result": r.stdout,
            "exit_code": r.returncode,
            "stderr": r.stderr,
            "status": "completed" if r.returncode == 0 else "failed",
        }

        node_dir = output_dir / "nodes" / nid
        node_dir.mkdir(parents=True, exist_ok=True)
        (node_dir / "result").write_text(r.stdout, encoding="utf-8")
        (node_dir / "exit_code").write_text(str(r.returncode), encoding="utf-8")
        if r.stderr:
            (node_dir / "stderr").write_text(r.stderr, encoding="utf-8")

        write_node_hashes(nid, node, output_dir)

        return result

    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "timeout (300s)", "result": "", "exit_code": -1}
    except Exception as e:
        return {"status": "failed", "error": str(e), "result": "", "exit_code": -1}


def eval_text(node: dict, context: dict, output_dir: Path) -> dict:
    """Expand template and produce text."""
    content = expand_expr(node["content"], context)
    nid = node["id"]
    node_dir = output_dir / "nodes" / nid
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "result").write_text(content, encoding="utf-8")
    write_node_hashes(nid, node, output_dir)
    result = {"result": content, "status": "completed"}
    return result


def prepare_agent(node: dict, context: dict, output_dir: Path, id_map_local: dict,
                  output_validate: bool = False, workflow_mode: str = "static") -> dict:
    """Generate prompt file, context file, and file list for an agent node.
    Does NOT execute the agent — that's the main Agent's job.

    If output_validate is True, appends validation instructions to the prompt
    so the SubAgent self-validates after generating output.
    """
    nid = node["id"]
    agent_dir = output_dir / "agents" / nid
    agent_dir.mkdir(parents=True, exist_ok=True)
    files_dir = agent_dir / "files"
    files_dir.mkdir(exist_ok=True)

    prompt = expand_expr(node["prompt"], context)

    agent_params = {
        "prompt_file": str(agent_dir / "prompt.md"),
        "context_file": str(agent_dir / "context.json"),
        "files_dir": str(files_dir),
    }

    # ── Output validation ──
    output_config = node.get("output", {})
    output_files = output_config.get("files", []) if isinstance(output_config, dict) else []
    if output_validate:
        interpreter_dir = Path(__file__).resolve().parent
        validate_script = str(interpreter_dir / "validate_output.py")

        # Resolve output files relative to agent_dir
        output_paths = [str((agent_dir / f).resolve()) for f in output_files] if output_files else []

        # Build validate block — files list + validate command
        validate_block = "\n\n---\n## 输出文件\n\n任务完成后，将结果写入：\n"
        if output_paths:
            for p in output_paths:
                validate_block += f"- `{p}`\n"
        else:
            default_path = agent_dir / "result.md"
            output_paths = [str(default_path.resolve())]
            validate_block += f"- `{default_path}`\n"

        validate_block += (
            "\n然后运行校验：\n\n"
            "```bash\n"
        )
        validate_block += f"python {validate_script} " + " ".join(output_paths) + "\n"
        validate_block += (
            "```\n\n"
            "如果校验失败（exit code ≠ 0），根据 stdout 中的错误信息修复输出，重新校验。\n"
            "通过后再返回。\n"
        )
        prompt += validate_block
        (agent_dir / "prompt.md").write_text(prompt, encoding="utf-8")

        agent_params["output"] = {
            "files": output_paths,
            "validate_script": validate_script,
        }
    else:
        (agent_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    resolved_files = []
    context_spec = node.get("context", {})
    for pattern in context_spec.get("files", []):
        expanded = expand_expr(pattern, context)
        matched = fnmatch_glob.glob(expanded, recursive=True)
        matched = [p for p in matched if os.path.isfile(p)]
        resolved_files.extend(matched)

    input_sources = {}

    from_outputs = copy_from_outputs(node, context, id_map_local, agent_dir)

    from_all_outputs = {}
    from_all_data = context_spec.get("_from_all", {})
    for logical_name, data in from_all_data.items():
        entries = []
        for gen_id in data.get("node_ids", []):
            gen_node = id_map_local.get(gen_id, {})
            gen_outputs = gen_node.get("outputs", {})
            for key in data.get("keys", []):
                path_str = gen_outputs.get(key)
                if path_str:
                    src_path = Path(path_str)
                    if src_path.exists():
                        dst_name = f"{gen_id}-{key}-{src_path.name}"
                        dst_path = files_dir / "from_all" / dst_name
                        dst_path.parent.mkdir(parents=True, exist_ok=True)
                        dst_path.write_bytes(src_path.read_bytes())
                        entries.append({
                            "node_id": gen_id,
                            "key": key,
                            "file": str(dst_path.resolve()),
                        })
        if entries:
            from_all_outputs[logical_name] = entries

    context_data = {
        "agent_id": nid,
        "files": resolved_files,
        "input_sources": input_sources,
        "from_outputs": from_outputs,
    }
    if from_all_outputs:
        context_data["from_all_outputs"] = from_all_outputs
    (agent_dir / "context.json").write_text(
        json.dumps(context_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    file_manifest = []
    for fpath in resolved_files:
        src = Path(fpath)
        if src.exists():
            dst = files_dir / src.name
            dst.write_bytes(src.read_bytes())
            file_manifest.append(fpath)

    (agent_dir / "manifest.txt").write_text(
        "\n".join(file_manifest), encoding="utf-8"
    )

    result = {
        "status": "pending",
        "agent_params": agent_params,
        "from_outputs": from_outputs,
    }
    if from_all_outputs:
        result["from_all_outputs"] = from_all_outputs
    return result


# ── Expand Node Evaluation ─────────────────────────────────────────────

def resolve_for_each(raw, context):
    """Evaluate a for_each expression to a list of strings."""
    if isinstance(raw, list):
        return [str(x) for x in raw]

    if isinstance(raw, (int, float)):
        return [str(raw)]

    expanded = expand_expr(str(raw), context)

    if expanded.strip().startswith("["):
        try:
            val = json.loads(expanded)
            if isinstance(val, list):
                return [str(x) for x in val]
        except json.JSONDecodeError:
            pass

    if "\n" in expanded:
        return [line.strip() for line in expanded.split("\n") if line.strip()]

    if "," in expanded:
        return [x.strip() for x in expanded.split(",") if x.strip()]

    return [expanded.strip()]


def deep_expand_node(node: dict, as_var: str, item_value: str) -> dict:
    """Deep-clone a template node, expanding ONLY the iteration variable."""
    pattern = re.compile(r"\{\{\s*" + re.escape(as_var) + r"\s*\}\}")

    def _walk(val):
        if isinstance(val, str):
            return pattern.sub(item_value, val)
        elif isinstance(val, list):
            return [_walk(item) for item in val]
        elif isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    return _walk(copy.deepcopy(node))


def eval_expand(node: dict, nodes_list: list, context: dict, output_dir: Path) -> tuple[list[dict], dict]:
    """Evaluate an expand node: resolve for_each, generate template nodes."""
    items = resolve_for_each(node["for_each"], context)
    as_var = node["as"]
    template_nodes = node.get("template", {}).get("nodes", [])

    if not items:
        return [], {}

    new_nodes = []
    template_id_map = {}
    for item in items:
        for tmpl in template_nodes:
            expanded = deep_expand_node(tmpl, as_var, item)
            new_nodes.append(expanded)
            tmpl_full_id = tmpl["id"]
            if tmpl_full_id not in template_id_map:
                template_id_map[tmpl_full_id] = []
            template_id_map[tmpl_full_id].append(expanded["id"])

    existing_ids = {n["id"] for n in nodes_list}
    for nn in new_nodes:
        if nn["id"] in existing_ids:
            print(f"Error: expand produced duplicate node id '{nn['id']}'", file=sys.stderr)
            sys.exit(1)
        existing_ids.add(nn["id"])

    return new_nodes, template_id_map


# ── Aggregate Node Resolution ─────────────────────────────────────────

def resolve_aggregate(expand_node: dict, template_id_map: dict, id_map: dict) -> list[dict]:
    """Resolve aggregate blocks from an expand node into concrete node definitions."""
    aggregates = expand_node.get("aggregate", [])
    if not aggregates:
        return []

    as_var = expand_node["as"]

    logical_to_ids = {}
    for tmpl_full_id, gen_ids in template_id_map.items():
        logical = re.sub(
            r"[-_.]?" + r"\{\{\s*" + re.escape(as_var) + r"\s*\}\}" + r"[-_.]?",
            "", tmpl_full_id
        ).strip("-")
        logical_to_ids[logical] = gen_ids

    result_nodes = []
    for agg in aggregates:
        node = copy.deepcopy(agg)

        expand_deps = node.pop("depends_on_expand", [])
        resolved = []
        for ref in expand_deps:
            resolved.extend(logical_to_ids.get(ref, []))

        existing = node.get("depends_on", [])
        merged = existing + [d for d in resolved if d not in existing]
        if merged:
            node["depends_on"] = merged
        elif "depends_on" in node:
            del node["depends_on"]

        ctx = node.get("context", {})
        if isinstance(ctx, dict) and "from_all" in ctx:
            from_all = ctx.pop("from_all")
            from_all_data = {}
            for logical_name, keys in from_all.items():
                gen_ids = logical_to_ids.get(logical_name, [])
                from_all_data[logical_name] = {
                    "node_ids": gen_ids,
                    "keys": keys,
                }
            ctx["_from_all"] = from_all_data

        result_nodes.append(node)

    return result_nodes


# ── Outputs / From Resolution ──────────────────────────────────────────

def infer_depends_from_from(nodes: list[dict]):
    """Auto-inject depends_on from context.from references."""
    id_map_local = {n["id"]: n for n in nodes}
    for node in nodes:
        ctx = node.get("context", {})
        if not isinstance(ctx, dict):
            continue
        from_spec = ctx.get("from")
        if not isinstance(from_spec, dict):
            continue
        deps = node.get("depends_on", [])
        modified = False
        for src_id in from_spec:
            if src_id not in deps:
                deps.append(src_id)
                modified = True
        if modified:
            node["depends_on"] = deps


def infer_depends_from_captures(nodes: list[dict]):
    """Auto-inject depends_on from {{ nodes.X.xxx }} references in command/prompt/content."""
    node_map = {n["id"]: n for n in nodes}
    pattern = re.compile(r'\{\{\s*nodes\.([^.\s]+)\.')

    for node in nodes:
        deps = node.get("depends_on", [])
        modified = False
        for field in ["command", "content", "prompt"]:
            val = node.get(field, "")
            if isinstance(val, str):
                for m in pattern.finditer(val):
                    ref_id = m.group(1)
                    if ref_id in node_map and ref_id != node["id"] and ref_id not in deps:
                        deps.append(ref_id)
                        modified = True
        if modified:
            node["depends_on"] = deps


def verify_outputs(node: dict) -> list[str]:
    """After executing a node, verify all declared outputs exist."""
    outputs = node.get("outputs")
    if not outputs:
        return []
    missing = []
    for key, path in outputs.items():
        if not Path(path).exists():
            missing.append(f"'{key}': {path}")
    return missing


def copy_from_outputs(node: dict, context: dict, id_map_local: dict, agent_dir: Path) -> dict:
    """Copy files from referenced nodes' declared outputs into agent's context."""
    ctx = node.get("context", {})
    if not isinstance(ctx, dict):
        return {}
    from_spec = ctx.get("from")
    if not isinstance(from_spec, dict):
        return {}

    from_dir = agent_dir / "files" / "from"
    from_dir.mkdir(parents=True, exist_ok=True)

    result = {}
    for src_id, keys in from_spec.items():
        src_node = id_map_local.get(src_id, {})
        src_outputs = src_node.get("outputs", {})
        result[src_id] = {}
        for key in keys:
            output_path = src_outputs.get(key)
            if not output_path:
                continue
            src_path = Path(output_path)
            if not src_path.exists():
                continue
            dst_name = f"{src_id}-{key}-{src_path.name}"
            dst_path = from_dir / dst_name
            dst_path.write_bytes(src_path.read_bytes())
            result[src_id][key] = str(dst_path.resolve())
    return result


# ── Content Hash / Cache ──────────────────────────────────────────────

HASH_ALGO = "sha256"


def file_hash(path: str) -> str:
    """Compute hash of a file's content."""
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def write_output_hash(output_dir: Path, nid: str, key: str, filepath: str):
    """Compute and store hash for a node output file."""
    hash_dir = output_dir / "nodes" / nid / "hashes"
    hash_dir.mkdir(parents=True, exist_ok=True)
    (hash_dir / f"{key}.{HASH_ALGO}").write_text(file_hash(filepath), encoding="utf-8")


def check_node_cache(nid: str, node: dict, output_dir: Path, debug: bool) -> dict | None:
    """Check if a node has valid cached results.
    Returns cached result dict if valid, None if needs re-execution.
    """
    node_dir = output_dir / "nodes" / nid
    if not node_dir.exists():
        return None

    result_file = node_dir / "result"
    if not result_file.exists():
        return None

    exit_file = node_dir / "exit_code"
    exit_code = 0
    if exit_file.exists():
        exit_code = int(exit_file.read_text().strip())

    cached = {
        "result": result_file.read_text(encoding="utf-8"),
        "exit_code": exit_code,
        "status": "completed",
    }
    if (node_dir / "stderr").exists():
        cached["stderr"] = (node_dir / "stderr").read_text(encoding="utf-8")

    outputs = node.get("outputs", {})
    hash_dir = node_dir / "hashes"
    for key, path in outputs.items():
        hash_file = hash_dir / f"{key}.{HASH_ALGO}"
        if not hash_file.exists():
            return None
        if not Path(path).exists():
            return None
        if not debug:
            expected = hash_file.read_text().strip()
            if file_hash(path) != expected:
                return None

    result_hash = hash_dir / f"result.{HASH_ALGO}"
    if result_hash.exists() and not debug:
        expected = result_hash.read_text().strip()
        if file_hash(str(result_file)) != expected:
            return None

    cached["_cached"] = True
    return cached


def write_node_hashes(nid: str, node: dict, output_dir: Path):
    """Write hash files for all outputs of a node."""
    result_file = output_dir / "nodes" / nid / "result"
    if result_file.exists():
        write_output_hash(output_dir, nid, "result", str(result_file))

    outputs = node.get("outputs", {})
    for key, path in outputs.items():
        if Path(path).exists():
            write_output_hash(output_dir, nid, key, path)


def load_session_state(output_dir: Path) -> dict:
    """Load existing node results from a session directory into context."""
    nodes = {}
    node_dir = output_dir / "nodes"
    if not node_dir.exists():
        return nodes

    for nid_dir in sorted(node_dir.iterdir()):
        if not nid_dir.is_dir():
            continue
        nid = nid_dir.name
        result_file = nid_dir / "result"
        if not result_file.exists():
            continue

        entry = {
            "result": result_file.read_text(encoding="utf-8"),
            "status": "completed",
        }
        exit_file = nid_dir / "exit_code"
        if exit_file.exists():
            entry["exit_code"] = int(exit_file.read_text().strip())
        stderr_file = nid_dir / "stderr"
        if stderr_file.exists():
            entry["stderr"] = stderr_file.read_text(encoding="utf-8")

        nodes[nid] = entry
    return nodes
