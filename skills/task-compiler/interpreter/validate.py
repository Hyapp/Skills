"""DSL schema validation."""

from collections import deque
from pathlib import Path


VALID_NODE_TYPES = {"program", "text", "agent", "expand", "plugin"}
VALID_ON_FAILURE = {"abort", "skip", "retry", "pause"}

REQUIRED_FIELDS = {
    "workflow": ["name"],
    "node": ["id", "type"],
}

NODE_SPECIFIC_REQUIRED = {
    "program": ["command"],
    "text": ["content"],
    "agent": ["prompt"],
    "expand": ["for_each", "as", "template"],
    "plugin": ["plugin"],
}


# ── Plugin Discovery ──────────────────────────────────────────────────────

def discover_plugins(skill_dir: Path) -> dict:
    """Scan plugins/ for plugin.yaml files.

    Returns dict of {name: {yaml_content, dir_path}}.
    Uses existing structure under task-compiler/plugins/<name>/plugin.yaml.
    """
    plugins_dir = skill_dir / "plugins"
    if not plugins_dir.exists():
        return {}

    discovered = {}
    for entry in sorted(plugins_dir.iterdir()):
        if not entry.is_dir():
            continue
        plugin_yaml = entry / "plugin.yaml"
        if not plugin_yaml.exists():
            continue
        try:
            content = plugin_yaml.read_text(encoding="utf-8")
            # Minimal parse — enough to check name and execute command
            name = entry.name
            discovered[name] = {
                "name": name,
                "dir": str(entry.resolve()),
                "yaml_raw": content,
            }
        except OSError:
            continue

    return discovered


def validate_plugin_node(node: dict, available_plugins: dict) -> list[str]:
    """Validate a plugin node references a known, well-formed plugin.

    Returns list of error messages (empty = valid).
    """
    errors = []
    plugin_name = node.get("plugin", "")

    if not plugin_name:
        errors.append(f"node '{node['id']}': 'plugin' field is required for type=plugin")
        return errors

    if plugin_name not in available_plugins:
        errors.append(f"node '{node['id']}': plugin '{plugin_name}' not found in plugins/")
        return errors

    plugin = available_plugins[plugin_name]
    # Check execute block exists by scanning yaml_raw
    yaml_raw = plugin.get("yaml_raw", "")
    if "execute:" not in yaml_raw:
        errors.append(f"node '{node['id']}': plugin '{plugin_name}' has no 'execute:' section in plugin.yaml")
    if "command:" not in yaml_raw:
        errors.append(f"node '{node['id']}': plugin '{plugin_name}' has no 'execute.command:' in plugin.yaml")

    return errors


def resolve_dag(nodes: list[dict]) -> list[str]:
    """Topological sort (Kahn's algorithm). Returns ordered node IDs.
    Raises ValueError on cycle.

    Dependencies that reference nodes NOT in the input list are treated
    as external (already satisfied) and do not affect in-degree.
    """
    # Filter to only dict nodes (validate() catches non-dict entries)
    dict_nodes = [n for n in nodes if isinstance(n, dict)]
    adj = {}
    in_deg = {}

    node_ids = {n["id"] for n in dict_nodes}

    for n in dict_nodes:
        nid = n["id"]
        in_deg[nid] = 0
        adj[nid] = []

    for n in dict_nodes:
        nid = n["id"]
        for dep in n.get("depends_on", []):
            if dep not in node_ids:
                continue
            adj.setdefault(dep, []).append(nid)
            in_deg[nid] += 1

    queue = deque([nid for nid, d in in_deg.items() if d == 0])
    result = []

    while queue:
        nid = queue.popleft()
        result.append(nid)
        for succ in adj.get(nid, []):
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)

    if len(result) != len(dict_nodes):
        cyclic = [nid for nid, d in in_deg.items() if d > 0]
        raise ValueError(f"Cycle detected involving nodes: {cyclic}")

    return result


def validate(workflow: dict, available_plugins: dict | None = None) -> list[str]:
    """Return list of validation errors (empty = valid).

    If available_plugins is provided, plugin-type nodes are validated
    against the discovered plugin registry.
    """
    errors = []

    if not isinstance(workflow, dict) or "workflow" not in workflow:
        errors.append("Missing root 'workflow' key")
        return errors

    wf = workflow["workflow"]
    for field in REQUIRED_FIELDS["workflow"]:
        if field not in wf:
            errors.append(f"workflow: missing required field '{field}'")

    wf_mode = wf.get("mode", "static")
    if wf_mode not in ("static", "dynamic"):
        errors.append(f"workflow.mode: must be 'static' or 'dynamic' (got '{wf_mode}')")

    wf_of = wf.get("on_failure")
    if wf_of and wf_of not in ("abort", "retry", "pause"):
        errors.append(f"workflow.on_failure: must be 'abort', 'retry', or 'pause' (got '{wf_of}')")

    nodes = wf.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("workflow.nodes must be a list")
        return errors

    if not nodes:
        errors.append("workflow.nodes: at least one node required")
        return errors

    node_ids = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{i}]: must be an object")
            continue

        nid = node.get("id", f"<index {i}>")

        for field in REQUIRED_FIELDS["node"]:
            if field not in node:
                errors.append(f"node '{nid}': missing '{field}'")

        if nid in node_ids:
            errors.append(f"node '{nid}': duplicate id")
        node_ids.add(nid)

        ntype = node.get("type")
        if ntype and ntype not in VALID_NODE_TYPES:
            errors.append(f"node '{nid}': invalid type '{ntype}'")

        if ntype in NODE_SPECIFIC_REQUIRED:
            for field in NODE_SPECIFIC_REQUIRED[ntype]:
                if field not in node:
                    errors.append(f"node '{nid}' (type={ntype}): missing '{field}'")

        of = node.get("on_failure")
        if of and of not in VALID_ON_FAILURE:
            errors.append(f"node '{nid}': invalid on_failure '{of}'")

    # Validate workflow-level parallel
    parallel = wf.get("parallel", 1)
    if not isinstance(parallel, int) or parallel < 1:
        errors.append(f"workflow.parallel: must be a positive integer (got '{parallel}')")

    # Validate node-level recovery and manifest
    for node in nodes:
        if not isinstance(node, dict):
            continue
        recovery = node.get("recovery")
        if recovery and recovery not in ("auto", "manual"):
            errors.append(f"node '{node.get('id', '?')}': recovery must be 'auto' or 'manual' (got '{recovery}')")
        manifest = node.get("manifest")
        if manifest is not None:
            if not isinstance(manifest, list) or not all(isinstance(m, str) for m in manifest):
                errors.append(f"node '{node.get('id', '?')}': manifest must be a list of strings")

    # Validate plugin nodes
    if available_plugins:
        for node in nodes:
            if isinstance(node, dict) and node.get("type") == "plugin":
                errors.extend(validate_plugin_node(node, available_plugins))

    # Validate requires
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node["id"]
        req = node.get("requires")
        if req is not None:
            if not isinstance(req, dict):
                errors.append(f"node '{nid}': 'requires' must be a dict")
            else:
                for key in req:
                    if key not in ("skills", "tools"):
                        errors.append(f"node '{nid}': invalid requires key '{key}'")
                    elif not isinstance(req[key], list) or not all(isinstance(v, str) for v in req[key]):
                        errors.append(f"node '{nid}': requires.{key} must be a list of strings")

    # Validate depends_on references
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node["id"]
        deps = node.get("depends_on", [])
        if isinstance(deps, list):
            for dep in deps:
                if dep not in node_ids:
                    errors.append(f"node '{nid}': depends_on '{dep}' not found")

    # Check for cyclic dependencies
    try:
        resolve_dag(nodes)
    except ValueError as e:
        errors.append(f"cyclic dependency detected: {e}")

    # Validate outputs (dict of key -> path)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        outputs = node.get("outputs")
        if outputs is not None:
            if not isinstance(outputs, dict):
                errors.append(f"node '{node['id']}': 'outputs' must be a dict")
            else:
                for k, v in outputs.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        errors.append(f"node '{node['id']}': outputs key/value must be strings")

    # Validate context.from (dict of node_id -> list of keys)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        from_spec = node.get("context", {}).get("from") if isinstance(node.get("context"), dict) else None
        if from_spec is not None:
            if not isinstance(from_spec, dict):
                errors.append(f"node '{node['id']}': context.from must be a dict")
            else:
                for src_id, keys in from_spec.items():
                    if src_id not in node_ids:
                        errors.append(f"node '{node['id']}': context.from references unknown node '{src_id}'")
                    if not isinstance(keys, list):
                        errors.append(f"node '{node['id']}': context.from.{src_id} must be a list of keys")
                    else:
                        src_node = next((n for n in nodes if n["id"] == src_id), None)
                        if src_node and src_node.get("outputs"):
                            valid_keys = list(src_node["outputs"].keys())
                            for k in keys:
                                if k not in valid_keys:
                                    errors.append(f"node '{node['id']}': context.from.{src_id} references key '{k}' but node '{src_id}' only has outputs: {valid_keys}")

    # Validate expand templates: no recursive expand
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == "expand":
            tmpl_nodes = node.get("template", {}).get("nodes", [])
            for tn in tmpl_nodes:
                if tn.get("type") == "expand":
                    errors.append(f"expand node '{node['id']}': template cannot contain expand nodes")
                if "id" not in tn:
                    errors.append(f"expand node '{node['id']}': template node missing 'id'")
                if "type" not in tn:
                    errors.append(f"expand node '{node['id']}': template node missing 'type'")

    # Validate aggregate blocks in expand nodes
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "expand":
            continue
        agg_nodes = node.get("aggregate", [])
        if not agg_nodes:
            continue
        if not isinstance(agg_nodes, list):
            errors.append(f"expand node '{node['id']}': 'aggregate' must be a list")
            continue
        for ai, agg in enumerate(agg_nodes):
            if not isinstance(agg, dict):
                errors.append(f"expand node '{node['id']}': aggregate[{ai}] must be an object")
                continue
            if agg.get("type") == "expand":
                errors.append(f"expand node '{node['id']}': aggregate node cannot be expand type")
            if "id" not in agg:
                errors.append(f"expand node '{node['id']}': aggregate[{ai}] missing 'id'")
            if "type" not in agg:
                errors.append(f"expand node '{node['id']}': aggregate[{ai}] missing 'type'")
            aid = agg.get("id")
            if aid in node_ids:
                errors.append(f"aggregate node '{aid}': id conflicts with existing node")
            node_ids.add(aid)
            doe = agg.get("depends_on_expand", [])
            if not isinstance(doe, list):
                errors.append(f"aggregate node '{aid}': 'depends_on_expand' must be a list")
            ctx = agg.get("context", {})
            if isinstance(ctx, dict):
                fa = ctx.get("from_all", {})
                if fa is not None and not isinstance(fa, dict):
                    errors.append(f"aggregate node '{aid}': 'context.from_all' must be a dict")

    return errors
