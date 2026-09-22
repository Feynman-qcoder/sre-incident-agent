"""LangGraph StateGraph for the SRE-Copilot investigation agent.

Graph structure:
  START → tool_call_loop → [conditional: more tools?] → generate_report → END
                ↑___________________________________|
  (loops while LLM requests tool calls AND iteration < MAX_ITER)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.agent.context_manager import ContextBudget
from src.agent.prompts import build_system_prompt
from src.agent.schemas import InvestigationReport
from src.agent.tools import make_tools
from src.utils.cost import estimate_cost

if TYPE_CHECKING:
    from src.datasources.protocol import DataSource


class GraphState(TypedDict, total=False):
    """LangGraph state — TypedDict so all keys are preserved across nodes."""
    incident_id: str
    incident_start_ts: str
    incident_end_ts: str
    affected_namespace: str
    _investigation_start_ts: str
    # add-incident-memory D5：可选 Hint 块（历史调查参考；空 = 行为与变更前一致）
    memory_hint: str
    messages: list[Any]
    tool_calls_log: list[dict[str, Any]]
    metrics_context: str
    traces_context: str
    logs_context: str
    hypotheses: list[dict[str, Any]]
    iteration_count: int
    final_report: InvestigationReport | None

log = structlog.get_logger()

MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))
# Force at least this many tool iterations, and at least one Prometheus metric sweep, before
# the agent is allowed to write a report. Without this the LLM tends to call get_service_topology
# once and then fabricate evidence (grounding_score=0.0).
MIN_TOOL_ITERATIONS = int(os.getenv("MIN_TOOL_ITERATIONS", "3"))


def build_graph(ds: DataSource, audit_path: str | Path | None = None) -> StateGraph:
    """Build and compile the investigation StateGraph for the given DataSource.

    ``audit_path``（add-tool-gateway）：tool_audit.jsonl 落盘路径（None → 系统 tmp）。
    """

    budget = ContextBudget()
    tools = make_tools(ds, budget)

    # LLM: OpenAI 兼容端点（默认 DeepSeek；NIM_* 环境变量可指向任意兼容端点）
    llm = ChatOpenAI(
        model=os.getenv("NIM_MODEL", "deepseek-flash"),
        openai_api_key=os.getenv("NIM_API_KEY", ""),
        openai_api_base=os.getenv("NIM_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
        # 2026-09-16 调整：4096 -> 50000 -> 131072。
        # 目的：让完成预算**不再构成约束**（准确性优先，不能因为截断产出错误答案）。
        # 关键认知：max_tokens **无法真正"关闭"** —— 服务端永远有模型自身的最大输出长度；
        #   而**完全省略 max_tokens 会回落到服务商默认值（DeepSeek 默认 4096），反而更小**，
        #   所以必须显式设成一个"实际不可能被触及"的大值。
        # 已实测（api.deepseek.com，deepseek-flash）：131072 与 200000 均被接受，
        #   且在约 2k token 的 prompt 下不会因"prompt+max_tokens 超出上下文"而报错。
        max_tokens=131072,
    )
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    # add-tool-gateway D1：分发层单点收口——所有工具调用经 SafeToolGateway 判定
    # （allowlist / namespace / window clamp / budget+timeout 四类钳制 + 审计）
    from src.agent.gateway import SafeToolGateway
    gateway = SafeToolGateway(tool_map, audit_path=audit_path)

    # ── Node: tool_call_loop ───────────────────────────────────────────────
    def tool_call_loop(state: GraphState) -> GraphState:
        iteration = state.get("iteration_count", 0)
        tool_calls_log: list[dict] = list(state.get("tool_calls_log", []))
        messages: list = list(state.get("messages", []))

        # First iteration: inject system + human messages
        if iteration == 0:
            system_msg = SystemMessage(content=build_system_prompt(
                start=state["incident_start_ts"],
                end=state["incident_end_ts"],
                namespace=state["affected_namespace"],
                max_iterations=MAX_TOOL_ITERATIONS,
            ))
            human_msg = HumanMessage(
                content=f"Investigate incident {state['incident_id']} "
                        f"in namespace {state['affected_namespace']}. "
                        f"Window: {state['incident_start_ts']} → {state['incident_end_ts']}. "
                        "Identify the root cause and produce an InvestigationReport JSON."
            )
            # add-incident-memory D2 结构隔离：Hint 块为独立 HumanMessage，
            # 位于 system 与任务消息之间；不进 tool_calls_log（grounding 零交集）。
            messages = [system_msg, human_msg]
            hint = str(state.get("memory_hint", "") or "")
            if hint:
                messages = [system_msg, HumanMessage(content=hint), human_msg]

        # If the LLM tried to stop early (last msg is an AIMessage with no tool calls) but we
        # are forcing more investigation, nudge it to actually sweep metrics before concluding.
        elif messages and isinstance(messages[-1], AIMessage) and not getattr(
            messages[-1], "tool_calls", None
        ):
            messages = messages + [HumanMessage(content=(
                "You have not gathered enough grounded evidence yet. Before concluding, call "
                "query_prometheus_range to sweep error_rate, cpu_usage, memory_usage and "
                "pod_restarts across the main services, then inspect the top anomalies with "
                "search_traces / query_loki / get_pod_events. Do not fabricate evidence."
            ))]

        # Call LLM
        response: AIMessage = llm_with_tools.invoke(messages)  # type: ignore[assignment]
        messages = messages + [response]

        # Execute any tool calls
        new_tool_messages: list[ToolMessage] = []
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", f"call_{iteration}_{tool_name}")

                log.info("tool_call", name=tool_name, iteration=iteration)

                # add-tool-gateway：分发经 gateway（DENY/CLAMP/timeout 全走这里）。
                # executed=False（DENY/超时）→ 不进 tool_calls_log（D4：grounding
                # 只校验实际执行；被拒调用绝不作为证据）。原 [UNKNOWN TOOL] 软提示
                # 升级为 Allowlist DENY（同样入审计）。
                result_str, executed = gateway.check_and_invoke(tool_name, tool_args, {
                    "incident_id": state.get("incident_id", ""),
                    "incident_start_ts": state.get("incident_start_ts", ""),
                    "incident_end_ts": state.get("incident_end_ts", ""),
                })

                if executed:
                    # Record tool call for grounding verification
                    tool_calls_log.append({
                        "iteration": iteration,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "result_preview": str(result_str)[:200],
                        # Store exact query/id strings for grounding check
                        "query_or_id": _extract_query_or_id(tool_name, tool_args),
                    })

                new_tool_messages.append(ToolMessage(
                    content=str(result_str),
                    tool_call_id=tool_id,
                    name=tool_name,
                ))

        return {
            "messages": messages + new_tool_messages,
            "tool_calls_log": tool_calls_log,
            "iteration_count": iteration + 1,
        }

    # ── Node: generate_report ──────────────────────────────────────────────
    def generate_report(state: GraphState) -> GraphState:
        messages: list = list(state.get("messages", []))
        inv_start = state.get("_investigation_start_ts", datetime.now(UTC).isoformat())

        # Ask LLM to produce the final structured report
        finalize_msg = HumanMessage(
            content=(
                "Based on all evidence gathered above, produce the final InvestigationReport JSON. "
                "Output ONLY the JSON object, no other text. "
                "Remember: every query_or_id in evidence must be an exact tool call you made."
            )
        )
        messages_for_report = messages + [finalize_msg]

        report_llm = ChatOpenAI(
            model=os.getenv("NIM_MODEL", "deepseek-flash"),
            openai_api_key=os.getenv("NIM_API_KEY", ""),
            openai_api_base=os.getenv("NIM_BASE_URL", "https://api.deepseek.com"),
            temperature=0,
            # 2026-09-16 调整：2048 -> 8192 -> 50000 -> 131072。
            # 目的：完成预算**不再构成约束**（报告被截断 = 直接产出错误答案，准确性优先）。
            # 实测轨迹（推理型模型 glm-5.3 会吃满预算）：
            #   max_tokens=2048 -> reasoning=2046（99.9%）截断，3/7 场景失败；
            #   max_tokens=8192 -> reasoning=7321（89%）截断，1/7 场景失败。
            # 关键认知：max_tokens **无法真正"关闭"**（服务端总有模型最大输出长度），
            #   且**省略它会回落到服务商默认值（更小）** → 必须显式设大值。
            # 已实测（api.deepseek.com）：131072 与 200000 均被接受，且约 2k token 的
            #   prompt 下不会触发上下文超限报错。
            # 注意：reasoning tokens 出现在响应的 usage 里，**不可设置**。
            max_tokens=131072,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

        response: AIMessage = report_llm.invoke(messages_for_report)  # type: ignore[assignment]
        inv_end = datetime.now(UTC).isoformat()

        # Parse and validate
        content = response.content if isinstance(response.content, str) else str(response.content)

        # Inject timing and token metadata
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = usage.get("input_tokens", 0) if usage else 0
        completion_tokens = usage.get("output_tokens", 0) if usage else 0
        latency_s = (
            datetime.fromisoformat(inv_end) - datetime.fromisoformat(inv_start)
        ).total_seconds()

        try:
            raw = json.loads(content)
            raw.update({
                "incident_id": state["incident_id"],
                "investigation_start_ts": inv_start,
                "investigation_end_ts": inv_end,
                "latency_s": latency_s,
                "total_prompt_tokens": prompt_tokens,
                "total_completion_tokens": completion_tokens,
                "cost_usd": estimate_cost(prompt_tokens, completion_tokens),
                "llm_model": os.getenv("NIM_MODEL", "deepseek-flash"),
                "agent_version": "0.1.0",
                "fault_type_classification": (
                    raw.get("root_causes", [{}])[0].get("fault_type", "unknown")
                    if raw.get("root_causes") else "unknown"
                ),
            })
            report = InvestigationReport.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, IndexError) as e:
            log.error("report_parse_failed", error=str(e), content_preview=content[:300])
            # Return a minimal valid report rather than crashing
            report = InvestigationReport(
                incident_id=state["incident_id"],
                investigation_start_ts=inv_start,
                investigation_end_ts=inv_end,
                root_causes=[],
                fault_type_classification="unknown",
                latency_s=latency_s,
            )

        return {"final_report": report}

    # ── Conditional edge ───────────────────────────────────────────────────
    def should_continue(state: GraphState) -> str:
        messages: list = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        if iteration >= MAX_TOOL_ITERATIONS:
            log.info("iteration_limit_reached", iteration=iteration)
            return "generate_report"

        # Find last AIMessage — if it had tool_calls, they were just executed → keep looping.
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                if getattr(msg, "tool_calls", None):
                    return "tool_call_loop"
                break

        # LLM wants to stop. Force more investigation if it hasn't met the minimum: at least
        # MIN_TOOL_ITERATIONS iterations AND at least one Prometheus metric query.
        metric_calls = sum(
            1 for e in state.get("tool_calls_log", [])
            if str(e.get("tool_name", "")).startswith("query_prometheus")
        )
        if iteration < MIN_TOOL_ITERATIONS or metric_calls < 1:
            log.info("forcing_more_investigation", iteration=iteration, metric_calls=metric_calls)
            return "tool_call_loop"
        return "generate_report"

    # ── Build graph ────────────────────────────────────────────────────────
    graph = StateGraph(GraphState)
    graph.add_node("tool_call_loop", tool_call_loop)
    graph.add_node("generate_report", generate_report)

    graph.add_edge(START, "tool_call_loop")
    graph.add_conditional_edges(
        "tool_call_loop",
        should_continue,
        {"tool_call_loop": "tool_call_loop", "generate_report": "generate_report"},
    )
    graph.add_edge("generate_report", END)

    return graph.compile()


def _extract_query_or_id(tool_name: str, args: dict) -> list[str]:  # type: ignore[type-arg]
    """Extract the query strings or IDs from tool args for grounding verification."""
    if tool_name in ("query_prometheus_range", "query_prometheus_instant"):
        return [args.get("query", "")]
    if tool_name in ("search_traces",):
        return [f"search_traces:{args.get('service_name','')}" ]
    if tool_name == "get_trace":
        return [args.get("trace_id", "")]
    if tool_name == "query_loki":
        return [args.get("logql", "")]
    if tool_name == "get_pod_events":
        return [f"k8s_events:{args.get('namespace','')}/{args.get('pod_name_prefix','')}"]
    return []
