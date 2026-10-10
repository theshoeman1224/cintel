"""Markdown report renderer.

Each report family renders in its own module so layout changes stay local.
The JSON siblings live in ``cintel.adapters.reports.json_renderer``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cintel.adapters.reports.markdown import (
    build_selection,
    call_graph,
    capability_index,
    compilation_units,
    diagnostics_index,
    function_index,
    global_usage,
    include_index,
    repository_inventory,
    symbol_index,
)


class MarkdownReportRenderer:
    """Dispatch each report family to its Markdown module."""
    def render(self, report_name: str, data: Any) -> str:
        handler = _MARKDOWN_HANDLERS.get(report_name)
        if handler is None:
            raise ValueError(f"Unsupported report: {report_name}")
        return handler(data)


_MARKDOWN_HANDLERS: dict[str, Callable[[Any], str]] = {
    "repository_inventory": repository_inventory.render,
    "build_selection": build_selection.render,
    "compilation_units": compilation_units.render,
    "function_index": function_index.render,
    "call_graph": call_graph.render,
    "include_index": include_index.render,
    "symbol_index": symbol_index.render,
    "global_usage": global_usage.render,
    "diagnostics_index": diagnostics_index.render,
    "capability_index": capability_index.render,
}
