"""DAG resolution and wave computation."""


def compute_waves(nodes: list[dict], order: list[str]) -> tuple[dict, list[list[str]]]:
    """Assign wave levels and group nodes by topological depth.
    Returns (wave_map: node_id->wave, waves: [[wave0_ids], [wave1_ids], ...]).
    """
    node_map = {n["id"]: n for n in nodes}

    wave_of = {}
    for nid in order:
        node = node_map[nid]
        deps = [d for d in node.get("depends_on", []) if d in node_map]
        if not deps:
            wave_of[nid] = 0
        else:
            wave_of[nid] = max(wave_of[d] for d in deps) + 1

    groups = {}
    for nid in order:
        groups.setdefault(wave_of[nid], []).append(nid)
    waves = [groups[w] for w in sorted(groups)]
    return wave_of, waves
