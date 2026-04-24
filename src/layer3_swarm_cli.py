"""
TIMPS Swarm Integration Layer 3: CLI Commands

CLI commands for timps-code to control the swarm.
Adds /swarm slash commands to timps-code.
"""
import os
import asyncio
import logging
import json
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from src.layer2_swarm_bridge import SwarmBridge, AgentRole, SubAgent, SwarmTask, get_swarm_bridge
    from src.layer1_computer_manager import get_computer_manager, ComputeResources
except ImportError:
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from layer2_swarm_bridge import SwarmBridge, AgentRole, SubAgent, SwarmTask, get_swarm_bridge
        from layer1_computer_manager import get_computer_manager, ComputeResources
    except ImportError:
        pass


@dataclass
class SwarmCommand:
    """A swarm command result."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class SwarmCLI:
    """
    Layer 3: CLI commands for swarm control.
    
    Commands:
    - /swarm spawn <role>     Spawn a sub-agent
    - /swarm task <request>   Run a swarm task
    - /swarm status         Show swarm status
    - /swarm agents         List active agents
    - /swarm kill <id>      Kill an agent
    - /swarm team <roles>    Spawn a team
    - /swarm resources      Show resource usage
    """
    
    def __init__(self):
        self.bridge: Optional[SwarmBridge] = None
        
    def _get_bridge(self) -> SwarmBridge:
        if self.bridge is None:
            try:
                self.bridge = get_swarm_bridge()
            except Exception:
                from layer2_swarm_bridge import SwarmBridge
                self.bridge = SwarmBridge()
        return self.bridge
    
    async def spawn_agent(self, role: str, task: Optional[str] = None) -> SwarmCommand:
        """Spawn a new sub-agent."""
        try:
            role_enum = AgentRole(role.lower())
        except ValueError:
            valid_roles = [r.value for r in AgentRole]
            return SwarmCommand(
                success=False,
                message=f"Invalid role. Valid: {', '.join(valid_roles)}"
            )
        
        bridge = self._get_bridge()
        agent = await bridge.spawn_sub_agent(role_enum, initial_task=task)
        
        return SwarmCommand(
            success=True,
            message=f"Spawned {role} agent: {agent.id}",
            data={
                "agent_id": agent.id,
                "role": role,
                "working_dir": agent.computer.working_dir,
            }
        )
    
    async def run_task(self, request: str, language: str = "python", wait: bool = True) -> SwarmCommand:
        """Run a task through the swarm."""
        bridge = self._get_bridge()
        task = await bridge.run_swarm_task(request, language, wait_for_completion=wait)
        
        if task.status == "completed":
            return SwarmCommand(
                success=True,
                message=f"Task {task.id} completed successfully",
                data={
                    "task_id": task.id,
                    "artifacts": task.artifacts,
                    "summary": task.results.get("final_deliverable", "")[:500],
                }
            )
        elif task.status == "failed":
            return SwarmCommand(
                success=False,
                message=f"Task {task.id} failed: {task.error}",
            )
        else:
            return SwarmCommand(
                success=True,
                message=f"Task {task.id} started",
                data={"task_id": task.id, "status": "running"}
            )
    
    async def spawn_team(self, roles: List[str]) -> SwarmCommand:
        """Spawn a team of agents."""
        bridge = self._get_bridge()
        
        role_enums = []
        for role in roles:
            try:
                role_enums.append(AgentRole(role.lower()))
            except ValueError:
                return SwarmCommand(
                    success=False,
                    message=f"Invalid role: {role}"
                )
        
        agents = await bridge.spawn_agent_team(role_enums)
        
        return SwarmCommand(
            success=True,
            message=f"Spawned team of {len(agents)} agents",
            data={
                "agents": [{"id": a.id, "role": a.role.value} for a in agents]
            }
        )
    
    async def kill_agent(self, agent_id: str) -> SwarmCommand:
        """Kill an agent."""
        bridge = self._get_bridge()
        success = bridge.kill_sub_agent(agent_id)
        
        return SwarmCommand(
            success=success,
            message=f"Killed agent {agent_id}" if success else f"Agent {agent_id} not found"
        )
    
    async def list_agents(self) -> SwarmCommand:
        """List active agents."""
        bridge = self._get_bridge()
        agents = bridge.list_sub_agents()
        
        return SwarmCommand(
            success=True,
            message=f"Active agents: {len(agents)}",
            data={"agents": agents}
        )
    
    async def show_status(self) -> SwarmCommand:
        """Show swarm status."""
        bridge = self._get_bridge()
        status = bridge.get_swarm_status()
        
        return SwarmCommand(
            success=True,
            message=f"Swarm status",
            data=status
        )
    
    async def show_resources(self) -> SwarmCommand:
        """Show resource usage."""
        cm = get_computer_manager()
        resources = cm.check_resources()
        agents = cm.list_agents()
        
        return SwarmCommand(
            success=True,
            message="System resources",
            data={
                "system": resources,
                "agents": agents
            }
        )
    
    def parse_command(self, command: str) -> tuple[str, Dict[str, Any]]:
        """Parse command string into action and args."""
        parts = command.strip().split()
        action = parts[0] if parts else ""
        args = {" ".join(parts[1:])}
        
        if action == "spawn" and len(parts) >= 2:
            return "spawn", {"role": parts[1], "task": parts[2:] if len(parts) > 2 else None
        elif action == "task":
            return "task", {"request": " ".join(parts[1:])}
        elif action == "team":
            return "team", {"roles": parts[1:]}
        elif action == "kill" and len(parts) >= 2:
            return "kill", {"agent_id": parts[1]}
        elif action == "agents":
            return "list_agents", {}
        elif action == "status":
            return "show_status", {}
        elif action == "resources":
            return "show_resources", {}
        else:
            return "help", {}


async def run_swarm_command(command: str) -> SwarmCommand:
    """Run a swarm CLI command."""
    cli = SwarmCLI()
    
    action, args = cli.parse_command(command)
    
    if action == "spawn":
        return await cli.spawn_agent(args.get("role"), args.get("task"))
    elif action == "task":
        return await cli.run_task(args.get("request"))
    elif action == "team":
        return await cli.spawn_team(args.get("roles", []))
    elif action == "kill":
        return await cli.kill_agent(args.get("agent_id"))
    elif action == "list_agents":
        return await cli.list_agents()
    elif action == "show_status":
        return await cli.show_status()
    elif action == "show_resources":
        return await cli.show_resources()
    else:
        return SwarmCommand(
            success=True,
            message="""
Swarm Commands:
  /swarm spawn <role> [task]  - Spawn a sub-agent
  /swarm task <request>       - Run task through swarm
  /swarm team <roles>     - Spawn a team of agents
  /swarm agents          - List active agents
  /swarm status         - Show swarm status
  /swarm resources      - Show resource usage
  /swarm kill <id>       - Kill an agent

Roles: orchestrator, product_manager, architect, code_generator, 
       code_reviewer, qa_tester, security_auditor, 
       performance_optimizer, documentation_writer, devops
"""
        )


def get_swarm_help() -> str:
    """Get help text for swarm commands."""
    return """
/swarm — TIMPS Swarm Multi-Agent Control

Spawn sub-agents with dedicated compute resources to work in parallel.

Examples:
  /swarm spawn code_generator "write a REST API"
  /swarm task "Fix the NullPointerException in AuthService"
  /swarm team orchestrator code_generator qa_tester
  /swarm status
  /swarm resources
"""