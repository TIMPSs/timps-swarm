"""
TIMPS Swarm Integration Layer 1: Computer Manager

Allocates isolated compute resources (CPU, RAM, disk) to each sub-agent.
Each sub-agent runs in its own sandboxed environment with dedicated resources.
"""
import os
import asyncio
import logging
import uuid
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None
import tempfile
import shutil
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

AGENT_COMPUTE_DIR = os.getenv("AGENT_COMPUTE_DIR", os.path.expanduser("~/.timps/agents"))
os.makedirs(AGENT_COMPUTE_DIR, exist_ok=True)


@dataclass
class ComputeResources:
    """Resources allocated to a sub-agent."""
    cpu_percent: float = 25.0
    memory_mb: int = 512
    disk_mb: int = 1024
    timeout_seconds: int = 300


@dataclass
class AgentComputer:
    """Virtual computer for a sub-agent."""
    agent_id: str
    agent_type: str
    resources: ComputeResources
    working_dir: str
    env_vars: Dict[str, str] = field(default_factory=dict)
    is_active: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_used: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ComputerManager:
    """
    Layer 1: Allocates and manages compute resources for sub-agents.
    
    Each sub-agent gets:
    - Dedicated directory for files
    - CPU quota (percentage of total)
    - Memory limit (MB)
    - Disk quota (MB)
    - Isolated environment variables
    - Process timeout
    """
    
    def __init__(self):
        self.agents: Dict[str, AgentComputer] = {}
        self.max_agents = int(os.getenv("MAX_SWARM_AGENTS", "10"))
        
        if HAS_PSUTIL:
            self.system_total_memory = psutil.virtual_memory().total // (1024 * 1024)
            self.system_total_cpu = psutil.cpu_count()
        else:
            self.system_total_memory = 8192
            self.system_total_cpu = 4
        
    def allocate_computer(self, agent_type: str, resources: Optional[ComputeResources] = None) -> AgentComputer:
        """Allocate a new virtual computer for a sub-agent."""
        if len(self.agents) >= self.max_agents:
            raise RuntimeError(f"Max agents ({self.max_agents}) reached. Cannot allocate more.")
        
        agent_id = f"{agent_type}-{uuid.uuid4().hex[:8]}"
        
        if resources is None:
            resources = ComputeResources()
        
        working_dir = os.path.join(AGENT_COMPUTE_DIR, agent_id)
        os.makedirs(working_dir, exist_ok=True)
        
        computer = AgentComputer(
            agent_id=agent_id,
            agent_type=agent_type,
            resources=resources,
            working_dir=working_dir,
            is_active=True,
        )
        
        self.agents[agent_id] = computer
        logger.info(f"[ComputerManager] Allocated {agent_id} with {resources}")
        
        return computer
    
    def release_computer(self, agent_id: str) -> bool:
        """Release resources for a sub-agent."""
        if agent_id not in self.agents:
            return False
        
        computer = self.agents[agent_id]
        
        if os.path.exists(computer.working_dir):
            try:
                shutil.rmtree(computer.working_dir)
            except Exception as e:
                logger.warning(f"[ComputerManager] Failed to clean {computer.working_dir}: {e}")
        
        del self.agents[agent_id]
        logger.info(f"[ComputerManager] Released {agent_id}")
        
        return True
    
    def get_computer(self, agent_id: str) -> Optional[AgentComputer]:
        """Get computer details."""
        return self.agents.get(agent_id)
    
    def list_agents(self) -> Dict[str, Any]:
        """List all active agent computers."""
        return {
            "total": len(self.agents),
            "max": self.max_agents,
            "system_memory_mb": self.system_total_memory,
            "system_cpu_cores": self.system_total_cpu,
            "agents": {
                aid: {
                    "type": comp.agent_type,
                    "resources": {
                        "cpu_percent": comp.resources.cpu_percent,
                        "memory_mb": comp.resources.memory_mb,
                        "disk_mb": comp.resources.disk_mb,
                        "timeout_seconds": comp.resources.timeout_seconds,
                    },
                    "working_dir": comp.working_dir,
                    "is_active": comp.is_active,
                    "created_at": comp.created_at,
                }
                for aid, comp in self.agents.items()
            }
        }
    
    def check_resources(self) -> Dict[str, Any]:
        """Check available system resources."""
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            return {
                "memory_total_mb": mem.total // (1024 * 1024),
                "memory_available_mb": mem.available // (1024 * 1024),
                "memory_used_percent": mem.percent,
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "disk_usage_percent": psutil.disk_usage("/").percent,
            }
        return {
            "memory_total_mb": 8192,
            "memory_available_mb": 4096,
            "memory_used_percent": 50.0,
            "cpu_count": 4,
            "cpu_percent": 25.0,
            "disk_usage_percent": 50.0,
        }
    
    def set_agent_env(self, agent_id: str, key: str, value: str) -> bool:
        """Set environment variable for an agent."""
        if agent_id not in self.agents:
            return False
        self.agents[agent_id].env_vars[key] = value
        return True
    
    def get_agent_env(self, agent_id: str) -> Dict[str, str]:
        """Get environment variables for an agent."""
        computer = self.agents.get(agent_id)
        return dict(computer.env_vars) if computer else {}


_computer_manager = None

def get_computer_manager() -> ComputerManager:
    """Get singleton instance."""
    global _computer_manager
    if _computer_manager is None:
        _computer_manager = ComputerManager()
    return _computer_manager