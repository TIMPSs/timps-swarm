import asyncio
import logging

from src.layer2_swarm_bridge import get_swarm_bridge, AgentRole
from src.context_sharing import ContextSharer

logger = logging.getLogger(__name__)


class AutoSpawner:
    def __init__(self, observer):
        self.observer = observer
        self.bridge = get_swarm_bridge()
        self.context_sharer = ContextSharer()
        self.active_pools: dict[str, list] = {}
        self.max_pool_size = 10
        self.observer.spawn_callbacks.append(self._on_pattern_detected)
        self._working_dir = "."

    def _on_pattern_detected(self, pattern: dict):
        pattern_id = f"{pattern['tool']}:{pattern['sample_args']['args_hash']}"
        if pattern_id in self.active_pools:
            pool = self.active_pools[pattern_id]
            if len(pool) >= self.max_pool_size:
                return
        if pattern.get("suggested_action") == "spawn_sub_agents" and pattern["count"] >= 3:
            asyncio.ensure_future(self._spawn_batch(pattern, pattern_id))

    async def _spawn_batch(self, pattern: dict, pattern_id: str):
        tool_name = pattern["tool"]
        role = self._map_tool_to_role(tool_name)
        batch_size = min(pattern["count"], self.max_pool_size)
        _ = self.context_sharer.get_context(self._working_dir)
        spawned = []
        for i in range(batch_size):
            try:
                agent = await self.bridge.spawn_sub_agent(
                    role=role,
                    initial_task=f"{tool_name} batch #{i + 1}/{batch_size}",
                )
                agent_id = agent.id
                spawned.append(agent_id)
            except Exception as exc:
                logger.warning("AutoSpawner: failed to spawn sub-agent: %s", exc)
        if spawned:
            self.active_pools[pattern_id] = spawned
            logger.info(
                "AutoSpawner: spawned %d sub-agents for pattern %s (tool=%s)",
                len(spawned), pattern_id, tool_name,
            )

    def _map_tool_to_role(self, tool_name: str) -> AgentRole:
        mapping = {
            "timps_unit_test_writer": AgentRole.QA_TESTER,
            "timps_docstring_generator": AgentRole.DOCUMENTATION_WRITER,
            "timps_run_task": AgentRole.ORCHESTRATOR,
            "timps_dependency_sentinel": AgentRole.DEPENDENCY_REBEL,
            "timps_pr_reviewer": AgentRole.CODE_REVIEWER,
            "timps_log_detective": AgentRole.LOG_INTERPRETER,
            "timps_sql_optimizer": AgentRole.DATABASE_ADMIN if hasattr(AgentRole, "DATABASE_ADMIN") else AgentRole.PERFORMANCE_OPTIMIZER,
            "timps_api_contract_auditor": AgentRole.ARCHITECT,
            "timps_content_multiplier": AgentRole.DOCUMENTATION_WRITER,
            "timps_boilerplate_architect": AgentRole.CODE_GENERATOR,
            "timps_research_scout": AgentRole.CONTEXT_KEEPER,
            "timps_data_wrangler": AgentRole.CODE_GENERATOR,
            "timps_refactoring_agent": AgentRole.CODE_REVIEWER,
            "timps_monitoring_agent": AgentRole.DEVOPS,
            "timps_ui_ux_agent": AgentRole.ARCHITECT,
        }
        return mapping.get(tool_name, AgentRole.CODE_GENERATOR)

    def pool_status(self) -> dict:
        return {k: {"count": len(v), "agent_ids": v} for k, v in self.active_pools.items()}


_spawner: AutoSpawner | None = None


def get_auto_spawner(observer=None) -> AutoSpawner:
    global _spawner
    if _spawner is None and observer is not None:
        _spawner = AutoSpawner(observer)
    return _spawner
