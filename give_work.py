#!/usr/bin/env python3
"""
Give work to TIMPS Swarm agents.
Usage: python3 give_work.py "<your task>"
"""
import asyncio
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.layer2_swarm_bridge import get_swarm_bridge, AgentRole


async def give_work(request: str, language: str = "python", wait: bool = True):
    """Give a task to the swarm."""
    bridge = get_swarm_bridge()
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║                    GIVING WORK TO SWARM                       ║
╚══════════════════════════════════════════════════════════════════╝

Task: {request}
Language: {language}
""")
    
    # Show available agents
    agents = bridge.computer_manager.list_agents()
    print(f"Available agents: {agents['total']}/{agents['max']}")
    
    print("\n⚡ Running swarm...\n")
    
    task = await bridge.run_swarm_task(
        request=request,
        language=language,
        max_iterations=10,
        wait_for_completion=wait
    )
    
    print(f"Status: {task.status}")
    
    if task.status == "completed":
        print("\n✅ RESULTS:")
        if task.results.get("requirements"):
            print(f"\n📋 Requirements:\n{task.results['requirements'][:500]}")
        if task.results.get("architecture_plan"):
            print(f"\n🏗️ Architecture:\n{task.results['architecture_plan'][:500]}")
        if task.results.get("code_artifacts"):
            print(f"\n💻 Generated {len(task.results['code_artifacts'])} files:")
            for f in task.results['code_artifacts']:
                print(f"   - {f}")
        if task.results.get("test_results"):
            print(f"\n🧪 Tests:\n{task.results['test_results'][:500]}")
        if task.results.get("security_report"):
            print(f"\n🔒 Security:\n{task.results['security_report'][:500]}")
        if task.results.get("documentation"):
            print(f"\n📝 Docs:\n{task.results['documentation'][:500]}")
    else:
        print(f"\n❌ Error: {task.error}")
    
    return task


async def spawn_and_work(roles: list, task: str):
    """Spawn specific agents then give them work."""
    bridge = get_swarm_bridge()
    
    print(f"🚀 Spawning {len(roles)} agents...")
    agents = await bridge.spawn_agent_team(roles)
    
    for a in agents:
        print(f"  - {a.role.value} ({a.id})")
    
    print(f"\n💼 Giving task: {task}")
    
    for agent in agents:
        print(f"\n📤 {agent.role.value}: {task}")
        # Agent does its work in its own directory
        with open(os.path.join(agent.computer.working_dir, "task.txt"), "w") as f:
            f.write(task)
        print(f"   ✅ Written to {agent.computer.working_dir}")
    
    return agents


def main():
    parser = argparse.ArgumentParser(description="Give work to TIMPS Swarm")
    parser.add_argument("task", nargs="?", help="Task to give to swarm")
    parser.add_argument("-l", "--language", default="python", help="Language")
    parser.add_argument("--spawn", nargs="+", help="Spawn specific agents (e.g. code_generator qa_tester)")
    args = parser.parse_args()
    
    if args.spawn:
        roles = [AgentRole(r.replace("-", "_")) for r in args.spawn]
        task = args.task or "do your work"
        asyncio.run(spawn_and_work(roles, task))
    elif args.task:
        asyncio.run(give_work(args.task, args.language))
    else:
        print("Usage:")
        print("  python3 give_work.py \"Write a hello function\"")
        print("  python3 give_work.py \"Fix the bug\" -l javascript")
        print("  python3 give_work.py --spawn code_generator qa_tester \"Write code and test it\"")


if __name__ == "__main__":
    main()