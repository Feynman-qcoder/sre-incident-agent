"""Anti-hallucination grounding verifier.

Checks each EvidenceItem.query_or_id in an InvestigationReport against
the tool_calls_log captured during the investigation.

grounding_score = fraction of evidence items whose query_or_id matches
                  an actual tool call in tool_calls_log.

This is computed by the harness, NOT self-reported by the agent.
A scenario with grounding_score < 0.8 is flagged [HALLUCINATION WARNING].
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.schemas import EvidenceItem, InvestigationReport


@dataclass
class GroundingResult:
    grounding_score: float           # fraction of evidence items verified
    verified_count: int
    total_count: int
    failed_items: list[dict[str, str]]   # [{rank, signal_type, query_or_id, reason}]
    has_hallucination_warning: bool  # grounding_score < 0.8


def verify(
    report: InvestigationReport,
    tool_calls_log: list[dict[str, object]],
    threshold: float = 0.8,
) -> GroundingResult:
    """Verify every EvidenceItem against the tool_calls_log.

    Matching strategy:
    - metric: query_or_id must be a substring of any tool_calls_log[].query_or_id string
    - trace: query_or_id must appear in any trace search or get_trace call args
    - log: query_or_id must be a substring of any loki call's logql arg
    - k8s_event: query_or_id must be a substring of any pod_events call args or result
    """
    # Build set of all query strings from tool_calls_log
    all_executed: list[str] = []
    for entry in tool_calls_log:
        # query_or_id field in tool call log
        qids: list[str] = entry.get("query_or_id", [])  # type: ignore[assignment]
        if isinstance(qids, str):
            qids = [qids]
        all_executed.extend(qids)

        # Also index args directly
        args: dict = entry.get("args", {})  # type: ignore[assignment]
        for v in args.values():
            if isinstance(v, str) and len(v) > 4:
                all_executed.append(v)

        # And result preview (for K8s event matching)
        preview = str(entry.get("result_preview", ""))
        if preview:
            all_executed.append(preview)

    all_executed_set = [s.lower() for s in all_executed if s]

    verified = 0
    total = 0
    failed_items: list[dict[str, str]] = []

    for hypothesis in report.root_causes:
        for ev in hypothesis.evidence:
            total += 1
            matched = _check_evidence(ev, all_executed_set)
            if matched:
                verified += 1
            else:
                failed_items.append({
                    "rank": str(hypothesis.rank),
                    "service": hypothesis.service,
                    "signal_type": ev.signal_type,
                    "query_or_id": ev.query_or_id[:120],
                    "reason": "no matching tool call found",
                })

    if total == 0:
        # No evidence items — neither verified nor hallucinated
        score = 1.0
    else:
        score = verified / total

    return GroundingResult(
        grounding_score=round(score, 4),
        verified_count=verified,
        total_count=total,
        failed_items=failed_items,
        has_hallucination_warning=score < threshold,
    )


def _check_evidence(ev: EvidenceItem, executed_lower: list[str]) -> bool:
    """Return True if the evidence item can be grounded in the tool_calls_log."""
    qid = ev.query_or_id.lower().strip()
    if not qid:
        return False

    # For metrics: check if the PromQL query was executed (substring match tolerates
    # minor whitespace differences)
    if ev.signal_type == "metric":
        # Normalize: strip extra spaces
        qid_norm = " ".join(qid.split())
        for executed in executed_lower:
            executed_norm = " ".join(executed.split())
            if qid_norm in executed_norm or executed_norm in qid_norm:
                return True
        return False

    if ev.signal_type == "trace":
        # Match trace_id or search_traces service name
        for executed in executed_lower:
            if qid in executed or (len(qid) > 8 and qid[:8] in executed):
                return True
        return False

    if ev.signal_type == "log":
        # Match LogQL string
        for executed in executed_lower:
            # At least the service_name portion should match
            if qid[:40] in executed or executed[:40] in qid:
                return True
        return False

    if ev.signal_type == "k8s_event":
        # Match against event result preview or pod_events args
        for executed in executed_lower:
            if qid[:30] in executed:
                return True
        return False

    return False
