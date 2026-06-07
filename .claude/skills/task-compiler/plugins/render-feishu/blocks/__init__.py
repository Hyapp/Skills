"""Block type registry with lazy import.

Each block type is a sibling module exporting `render(block_data) -> str`.
Modules are loaded on first use — only the types actually present in the IR
are imported.
"""

import importlib

_registry = {}  # block_type -> callable | None


def render(block_data):
    block_type = block_data.get('type', '')
    if not block_type:
        return ''

    if block_type not in _registry:
        try:
            mod = importlib.import_module(f'.{block_type}', __package__)
            _registry[block_type] = getattr(mod, 'render', None)
        except ImportError:
            _registry[block_type] = None

    handler = _registry[block_type]
    if handler is None:
        return ''
    return handler(block_data)
