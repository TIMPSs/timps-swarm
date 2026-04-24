"""
TIMPS Swarm Integration Layer 2: Swarm Bridge

Bridges timps-code CLI to timps-swarm multi-agent system.
Connects the 10 specialized agents from timps-swarm into timps-code's command system.
"""
import os
import asyncio
import logging
import time
import json
import uuid
from typing import Dict, Optional, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from src.layer1_computer_manager import get_computer_manager, ComputeResources, AgentComputer
except ImportError:
    from layer1_computer_manager import get_computer_manager, ComputeResources, AgentComputer

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """All 10 swarm agent roles."""
    ORCHESTRATOR = "orchestrator"
    PRODUCT_MANAGER = "product_manager"
    ARCHITECT = "architect"
    CODE_GENERATOR = "code_generator"
    CODE_REVIEWER = "code_reviewer"
    QA_TESTER = "qa_tester"
    SECURITY_AUDITOR = "security_auditor"
    PERFORMANCE_OPTIMIZER = "performance_optimizer"
    DOCUMENTATION_WRITER = "documentation_writer"
    DEVOPS = "devops"


# Default resources per agent role
ROLE_RESOURCES: Dict[AgentRole, ComputeResources] = {
    AgentRole.ORCHESTRATOR: ComputeResources(cpu_percent=30.0, memory_mb=1024, disk_mb=2048, timeout_seconds=600),
    AgentRole.PRODUCT_MANAGER: ComputeResources(cpu_percent=15.0, memory_mb=512, disk_mb=512, timeout_seconds=180),
    AgentRole.ARCHITECT: ComputeResources(cpu_percent=20.0, memory_mb=768, disk_mb=1024, timeout_seconds=300),
    AgentRole.CODE_GENERATOR: ComputeResources(cpu_percent=40.0, memory_mb=2048, disk_mb=4096, timeout_seconds=600),
    AgentRole.CODE_REVIEWER: ComputeResources(cpu_percent=20.0, memory_mb=1024, disk_mb=1024, timeout_seconds=300),
    AgentRole.QA_TESTER: ComputeResources(cpu_percent=25.0, memory_mb=1536, disk_mb=2048, timeout_seconds=300),
    AgentRole.SECURITY_AUDITOR: ComputeResources(cpu_percent=20.0, memory_mb=1024, disk_mb=1024, timeout_seconds=300),
    AgentRole.PERFORMANCE_OPTIMIZER: ComputeResources(cpu_percent=20.0, memory_mb=1024, disk_mb=1024, timeout_seconds=300),
    AgentRole.DOCUMENTATION_WRITER: ComputeResources(cpu_percent=10.0, memory_mb=256, disk_mb=512, timeout_seconds=180),
    AgentRole.DEVOPS: ComputeResources(cpu_percent=15.0, memory_mb=512, disk_mb=1024, timeout_seconds=300),
}


@dataclass
class SubAgent:
    """A spawned sub-agent with its own computer."""
    id: str
    role: AgentRole
    computer: AgentComputer
    status: str = "idle"  # idle | running | completed | failed
    current_task: str = ""
    output: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


@dataclass 
class SwarmTask:
    """A task submitted to the swarm."""
    id: str
    request: str
    language: Optional[str] = None
    max_iterations: int = 10
    status: str = "pending"  # pending | running | completed | failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    error: Optional[str] = None


class SwarmBridge:
    """
    Layer 2: Bridges timps-code to timps-swarm.
    
    Provides:
    - spawn_sub_agent(role): Create sub-agent with dedicated compute
    - run_swarm_task(request): Execute full 10-agent pipeline
    - get_agent_status(id): Check sub-agent state
    - orchestrate(agents): Coordinate multiple sub-agents
    """
    
    def __init__(self, swarm_api_url: str = "http://localhost:8000"):
        self.computer_manager = get_computer_manager()
        self.swarm_api_url = swarm_api_url
        self.sub_agents: Dict[str, SubAgent] = {}
        self.swarm_tasks: Dict[str, SwarmTask] = {}
        self._local_mode = True  # Set to False to use API
        
    async def spawn_sub_agent(
        self, 
        role: AgentRole, 
        resources: Optional[ComputeResources] = None,
        initial_task: Optional[str] = None
    ) -> SubAgent:
        """Spawn a new sub-agent with its own computer."""
        resources = resources or ROLE_RESOURCES.get(role, ComputeResources())
        
        computer = self.computer_manager.allocate_computer(
            agent_type=role.value,
            resources=resources
        )
        
        agent = SubAgent(
            id=computer.agent_id,
            role=role,
            computer=computer,
            status="running" if initial_task else "idle",
            current_task=initial_task or "",
            started_at=datetime.utcnow().isoformat() if initial_task else None,
        )
        
        self.sub_agents[agent.id] = agent
        logger.info(f"[SwarmBridge] Spawned {role.value} sub-agent: {agent.id}")
        
        return agent
    
    async def spawn_agent_team(self, roles: List[AgentRole]) -> List[SubAgent]:
        """Spawn a team of sub-agents."""
        agents = []
        for role in roles:
            agent = await self.spawn_sub_agent(role)
            agents.append(agent)
        return agents
    
    def kill_sub_agent(self, agent_id: str) -> bool:
        """Kill a sub-agent and free its resources."""
        if agent_id not in self.sub_agents:
            return False
        
        del self.sub_agents[agent_id]
        self.computer_manager.release_computer(agent_id)
        logger.info(f"[SwarmBridge] Killed sub-agent: {agent_id}")
        return True
    
    def get_sub_agent(self, agent_id: str) -> Optional[SubAgent]:
        """Get sub-agent details."""
        return self.sub_agents.get(agent_id)
    
    def list_sub_agents(self) -> List[Dict[str, Any]]:
        """List all active sub-agents."""
        return [
            {
                "id": a.id,
                "role": a.role.value,
                "status": a.status,
                "current_task": a.current_task,
                "computer": {
                    "working_dir": a.computer.working_dir,
                    "resources": {
                        "cpu_percent": a.computer.resources.cpu_percent,
                        "memory_mb": a.computer.resources.memory_mb,
                    },
                },
            }
            for a in self.sub_agents.values()
        ]
    
    async def run_swarm_task(
        self, 
        request: str,
        language: str = "python",
        max_iterations: int = 10,
        wait_for_completion: bool = True,
    ) -> SwarmTask:
        """Execute a task through the full 10-agent swarm pipeline."""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        
        task = SwarmTask(
            id=task_id,
            request=request,
            language=language,
            max_iterations=max_iterations,
            status="running",
            started_at=datetime.utcnow().isoformat(),
        )
        
        self.swarm_tasks[task_id] = task
        
        try:
            if self._local_mode:
                result = await self._run_local_swarm(request, language, max_iterations)
            else:
                result = await self._run_api_swarm(request, language, max_iterations)
            
            task.status = "completed"
            task.results = result.get("results", {})
            task.artifacts = result.get("artifacts", [])
            task.completed_at = datetime.utcnow().isoformat()
            
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.completed_at = datetime.utcnow().isoformat()
            logger.error(f"[SwarmBridge] Task {task_id} failed: {e}")
        
        return task
    
    async def _run_local_swarm(self, request: str, language: str, max_iterations: int) -> Dict[str, Any]:
        """Run swarm locally using Python imports."""
        results = {}
        artifacts = []
        
        try:
            from src.graph import build_graph
            from src.state import SwarmState
            
            graph = build_graph()
            
            initial_state: SwarmState = {
                "user_request": request,
                "language": language,
                "requirements": "",
                "architecture_plan": "",
                "tasks": [],
                "code_artifacts": [],
                "review_comments": [],
                "test_results": "",
                "security_report": "",
                "performance_report": "",
                "documentation": "",
                "final_deliverable": "",
                "iteration_count": 0,
                "max_iterations": max_iterations,
                "errors": [],
                "completed": False,
            }
            
            final_state = await graph.ainvoke(initial_state)
            
            results = {
                "requirements": final_state.get("requirements", ""),
                "architecture_plan": final_state.get("architecture_plan", ""),
                "code_artifacts": final_state.get("code_artifacts", []),
                "test_results": final_state.get("test_results", ""),
                "security_report": final_state.get("security_report", ""),
                "performance_report": final_state.get("performance_report", ""),
                "documentation": final_state.get("documentation", ""),
                "final_deliverable": final_state.get("final_deliverable", ""),
            }
            
            artifacts = final_state.get("code_artifacts", [])
            
        except ImportError:
            results = {"error": "timps-swarm not in PYTHONPATH"}
        
        return {"results": results, "artifacts": artifacts}
    
    async def _run_api_swarm(self, request: str, language: str, max_iterations: int) -> Dict[str, Any]:
        """Run swarm via API."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.swarm_api_url}/swarm/run",
                json={
                    "request": request,
                    "language": language,
                    "max_iterations": max_iterations,
                },
                timeout=aiohttp.ClientTimeout(total=600)
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"API error: {resp.status}")
                return await resp.json()
    
    def get_task_status(self, task_id: str) -> Optional[SwarmTask]:
        """Get task status."""
        return self.swarm_tasks.get(task_id)
    
    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all tasks."""
        return [
            {
                "id": t.id,
                "request": t.request[:100] + "..." if len(t.request) > 100 else t.request,
                "status": t.status,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
                "artifacts_count": len(t.artifacts),
            }
            for t in self.swarm_tasks.values()
        ]
    
    async def orchestrate(self, agent_ids: List[str], task: str) -> Dict[str, str]:
        """Coordinate multiple sub-agents on a single task."""
        outputs = {}
        
        for agent_id in agent_ids:
            agent = self.sub_agents.get(agent_id)
            if not agent:
                outputs[agent_id] = f"Agent {agent_id} not found"
                continue
            
            agent.current_task = task
            agent.status = "running"
            outputs[agent_id] = f"Spawned {agent.role.value} for task"
        
        return outputs
    
    def get_swarm_status(self) -> Dict[str, Any]:
        """Get overall swarm status."""
        resources = self.computer_manager.check_resources()
        
        return {
            "active_agents": len(self.sub_agents),
            "total_tasks": len(self.swarm_tasks),
            "completed_tasks": len([t for t in self.swarm_tasks.values() if t.status == "completed"]),
            "failed_tasks": len([t for t in self.swarm_tasks.values() if t.status == "failed"]),
            "system_resources": resources,
            "sub_agents": self.list_sub_agents(),
        }


_swarm_bridge: Optional[SwarmBridge] = None

def get_swarm_bridge() -> SwarmBridge:
    """Get singleton instance."""
    global _swarm_bridge
    if _swarm_bridge is None:
        _swarm_bridge = SwarmBridge()
    return _swarm_bridge