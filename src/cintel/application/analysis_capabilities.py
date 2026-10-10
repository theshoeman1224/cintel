"""Capability records for one source-analysis run.

Statuses derive from run counts, so the CLI and reports can state what the
analysis could and could not claim without re-reading parser output.
"""

from __future__ import annotations

from cintel.domain.models import AnalysisCapability, CapabilityStatus


def analysis_capabilities(
    *,
    target_count: int,
    reused: int,
    stored: int,
    failed: int,
    resolved_calls: int,
    unresolved_calls: int,
    resolved_includes: int,
    unresolved_includes: int,
    entry_points: int,
    unreachable: int,
    recursive_count: int,
) -> tuple[AnalysisCapability, ...]:
    """Build the capability records reported by one analysis run."""
    analysis_status = _analysis_status(target_count, failed)
    call_status = _call_status(resolved_calls, unresolved_calls)
    graph_status = (
        CapabilityStatus.AVAILABLE
        if definition_graph_exists(entry_points, unreachable, recursive_count)
        else CapabilityStatus.UNAVAILABLE
    )
    return (
        AnalysisCapability(
            name="source_analysis",
            status=analysis_status,
            reason=(
                "Conservative source analysis completed."
                if analysis_status is CapabilityStatus.AVAILABLE
                else "Some analyzed targets could not be parsed."
            ),
            evidence=(
                f"{target_count} targets selected",
                f"{reused} reused",
                f"{stored} parsed",
            ),
        ),
        AnalysisCapability(
            name="call_resolution",
            status=call_status,
            reason="Direct-call candidates resolve to unique definitions.",
            evidence=(
                f"{resolved_calls} resolved",
                f"{unresolved_calls} unresolved",
                f"{resolved_includes} include directives resolved",
                f"{unresolved_includes} include directives unresolved",
            ),
        ),
        AnalysisCapability(
            name="entry_point_reachability",
            status=graph_status,
            reason="Reachability and direct-recursion cycles come from resolved calls.",
            evidence=(
                f"{entry_points} entry points",
                f"{unreachable} unreachable definitions",
                f"{recursive_count} directly recursive functions",
            ),
        ),
    )


def _analysis_status(target_count: int, failed: int) -> CapabilityStatus:
    if target_count == 0:
        return CapabilityStatus.UNAVAILABLE
    if failed:
        return CapabilityStatus.DEGRADED
    return CapabilityStatus.AVAILABLE


def _call_status(resolved_calls: int, unresolved_calls: int) -> CapabilityStatus:
    if resolved_calls == 0 and unresolved_calls == 0:
        return CapabilityStatus.UNAVAILABLE
    if unresolved_calls == 0:
        return CapabilityStatus.AVAILABLE
    return CapabilityStatus.DEGRADED


def definition_graph_exists(entry_points: int, unreachable: int, recursive: int) -> bool:
    """True when the call graph has any node worth reporting."""
    return bool(entry_points or unreachable or recursive)
