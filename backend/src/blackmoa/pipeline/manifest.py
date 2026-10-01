"""Build the single black-moa manifest for an agent × audience (plan/07)."""
from __future__ import annotations

from typing import Any

from geny_executor import EnvironmentManifest

from blackmoa.models import Agent, ModelCatalog
from blackmoa.services.catalog import PROVIDER_TO_EXECUTOR

CLI_PROVIDERS = {"claude_code"}


def build_manifest(agent: Agent, cat: ModelCatalog, *, audience: str, tool_names: list[str],
                   core_overrides: dict[str, bool], turn_cost_cap_usd: float) -> EnvironmentManifest:
    m = EnvironmentManifest.blank_manifest(f"blackmoa-{agent.id}-{audience}", description="black-moa secretary pipeline")
    m.metadata.tags = ["blackmoa", audience]
    exec_provider = PROVIDER_TO_EXECUTOR.get(agent.provider, agent.provider)
    is_cli = agent.provider in CLI_PROVIDERS
    thinking = bool(agent.thinking_enabled and cat.supports_thinking)
    temperature = 0.3 + 0.5 * float((agent.persona or {}).get("humor", 0.2) or 0)
    m.model = {
        "model": cat.cli_alias if (is_cli and cat.cli_alias) else cat.model_id,
        "max_tokens": min(int(cat.max_output or 8192), 8192 if audience == "owner" else 4096),
        "temperature": round(min(1.0, max(0.0, temperature)), 2),
        "thinking_enabled": thinking,
        "thinking_budget_tokens": 4096 if thinking else 0,
        "thinking_display": "summarized",
    }
    m.pipeline = {"max_iterations": 6, "cost_budget_usd": float(turn_cost_cap_usd), "context_window_budget": int(cat.context_window or 200_000),
                  "stream": True}
    by_order: dict[int, dict[str, Any]] = {s["order"]: s for s in m.stages}

    def stage(order: int, *, active: bool = True, strategies: dict | None = None, strategy_configs: dict | None = None,
              config: dict | None = None, chain_order: dict | None = None) -> None:
        s = by_order[order]
        s["active"] = active
        if strategies:
            s["strategies"].update(strategies)
        if strategy_configs:
            s["strategy_configs"].update(strategy_configs)
        if config:
            s["config"].update(config)
        if chain_order:
            s["chain_order"] = chain_order

    stage(1, strategies={"validator": "default", "normalizer": "multimodal"})
    stage(2, strategies={"strategy": "simple_load", "compactor": "truncate", "retriever": "null"},
          strategy_configs={"compactor": {"keep_last": 60}}, config={"retrieval_timeout_s": 6.0})
    stage(3, strategies={"builder": "composable"}, config={"volatile_placement": "turn_context"})
    stage(4)
    stage(5, strategies={"strategy": "system_cache"})
    stage(6, strategies={"retry": "rate_limit_aware", "router": "passthrough", "tool_loop": "internal"},
          strategy_configs={"tool_loop": {"max_inner_turns": 12, "parallel_tools": True}},
          config={"provider": exec_provider, "stream": True})
    stage(7, strategies={"tracker": "detailed", "calculator": "unified_pricing"})
    stage(8, active=thinking, strategies={"processor": "extract_and_store", "budget_planner": "static"})
    stage(9, strategies={"parser": "default", "signal_detector": "hybrid"})
    stage(10, strategies={"executor": "parallel", "router": "registry"}, config={"max_concurrency": 6})
    stage(11)
    for order in (12, 13, 14, 15, 17, 18, 19, 20):
        stage(order, active=False)
    stage(16, strategies={"controller": "budget_aware"}, config={"max_turns": 6})
    stage(21, strategies={"formatter": "default"})

    m.tools.built_in = []
    m.tools.external = list(tool_names)
    m.tools.core_overrides = dict(core_overrides)
    m.tools.mcp_servers = []
    m.memory = {}
    return m
