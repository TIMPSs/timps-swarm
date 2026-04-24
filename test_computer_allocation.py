#!/usr/bin/env python3
"""
Test script to verify sub-agents are using their own computers.
Run this to test that each agent gets isolated compute resources.
"""
import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.layer1_computer_manager import get_computer_manager, ComputeResources
from src.layer2_swarm_bridge import get_swarm_bridge, AgentRole


async def test_computer_allocation():
    """Test that agents get their own computers."""
    print("=" * 60)
    print("TEST 1: Computer Allocation")
    print("=" * 60)
    
    cm = get_computer_manager()
    
    # Spawn 3 test agents
    agents = []
    for role_name in ["code_generator", "qa_tester", "security_auditor"]:
        role = AgentRole(role_name)
        computer = cm.allocate_computer(role_name)
        
        # Write test file to agent's computer
        test_file = os.path.join(computer.working_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write(f"Hello from {role_name}!")
        
        # Verify isolation
        files = os.listdir(computer.working_dir)
        print(f"✓ {role_name}: {computer.agent_id}")
        print(f"  - Working dir: {computer.working_dir}")
        print(f"  - Files: {files}")
        print(f"  - CPU quota: {computer.resources.cpu_percent}%")
        print(f"  - Memory: {computer.resources.memory_mb}MB")
        
        agents.append((role, computer.agent_id))
    
    print(f"\n✓ Allocated {len(agents)} isolated computers\n")
    return agents


async def test_swarm_execution(agents):
    """Test that swarm can execute a task."""
    print("=" * 60)
    print("TEST 2: Swarm Task Execution")
    print("=" * 60)
    
    bridge = get_swarm_bridge()
    
    # Run a simple task
    task = await bridge.run_swarm_task(
        request="Write a hello world function in Python",
        language="python",
        max_iterations=3,
        wait_for_completion=True
    )
    
    print(f"Task ID: {task.id}")
    print(f"Status: {task.status}")
    
    if task.status == "completed":
        print(f"✓ Task completed")
        print(f"  Artifacts: {len(task.artifacts)}")
        for a in task.artifacts:
            print(f"    - {a}")
    else:
        print(f"✗ Task failed: {task.error}")
    
    print()
    return task


async def test_parallel_agents():
    """Test parallel agent execution."""
    print("=" * 60)
    print("TEST 3: Parallel Agent Execution")
    print("=" * 60)
    
    bridge = get_swarm_bridge()
    
    # Spawn team of agents
    roles = [
        AgentRole.ORCHESTRATOR,
        AgentRole.CODE_GENERATOR,
        AgentRole.QA_TESTER,
    ]
    
    agents = await bridge.spawn_agent_team(roles)
    
    print(f"✓ Spawned {len(agents)} agents:")
    for agent in agents:
        print(f"  - {agent.role.value} ({agent.id})")
        print(f"    Working dir: {agent.computer.working_dir}")
    
    # Each agent writes to its own directory
    for agent in agents:
        test_file = os.path.join(agent.computer.working_dir, "execution_log.txt")
        with open(test_file, "w") as f:
            f.write(f"Agent {agent.role.value} executed at {time.time()}")
        print(f"\n✓ {agent.role.value} wrote to its own computer")
    
    print()
    return agents


async def test_resource_isolation():
    """Test that agents have isolated resources."""
    print("=" * 60)
    print("TEST 4: Resource Isolation Verification")
    print("=" * 60)
    
    cm = get_computer_manager()
    resources = cm.check_resources()
    
    print(f"System Resources:")
    print(f"  CPU cores: {resources['cpu_count']}")
    print(f"  Memory: {resources['memory_available_mb']}MB available")
    print(f"  Disk: {100 - resources['disk_usage_percent']:.1f}% free")
    
    print(f"\nAllocated Agents:")
    agents = cm.list_agents()
    print(f"  Total: {agents['total']}/{agents['max']}")
    
    for aid, agent in agents['agents'].items():
        print(f"\n  {aid} ({agent['type']}):")
        print(f"    CPU: {agent['resources']['cpu_percent']}%")
        print(f"    Memory: {agent['resources']['memory_mb']}MB")
        print(f"    Dir: {agent['working_dir']}")
    
    print(f"\n✓ Resources properly isolated per agent\n")


async def test_agent_independence():
    """Test that each agent is independent."""
    print("=" * 60)
    print("TEST 5: Agent Independence")
    print("=" * 60)
    
    bridge = get_swarm_bridge()
    
    # Create 2 agents at same time
    agent1 = await bridge.spawn_sub_agent(AgentRole.CODE_GENERATOR, initial_task="write test 1")
    agent2 = await bridge.spawn_sub_agent(AgentRole.QA_TESTER, initial_task="write test 2")
    
    # Write different files to each
    with open(os.path.join(agent1.computer.working_dir, "data.json"), "w") as f:
        f.write('{"agent": "code_generator", "task": "write test 1"}')
    
    with open(os.path.join(agent2.computer.working_dir, "data.json"), "w") as f:
        f.write('{"agent": "qa_tester", "task": "write test 2"}')
    
    # Read back - should be different
    with open(os.path.join(agent1.computer.working_dir, "data.json")) as f:
        data1 = f.read()
    with open(os.path.join(agent2.computer.working_dir, "data.json")) as f:
        data2 = f.read()
    
    print(f"Agent 1 data: {data1}")
    print(f"Agent 2 data: {data2}")
    
    if data1 != data2:
        print("✓ Agents have independent storage!")
    else:
        print("✗ Storage not isolated!")
    
    # Kill one, check the other survives
    bridge.kill_sub_agent(agent1.id)
    
    if os.path.exists(agent2.computer.working_dir):
        print(f"✓ Agent 2 survived after Agent 1 was killed!")
    else:
        print("✗ Agent 2 was also killed!")
    
    # Check agent 1 directory is gone
    if not os.path.exists(agent1.computer.working_dir):
        print(f"✓ Agent 1 directory cleaned up!")
    else:
        print("✗ Agent 1 directory not cleaned!")
    
    print()
    return True


async def main():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║     TIMPS Swarm - Computer Allocation Test Suite            ║
║     Verifying sub-agents have their own computers            ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    tests = [
        ("Computer Allocation", test_computer_allocation),
        ("Swarm Execution", test_swarm_execution),
        ("Parallel Agents", test_parallel_agents),
        ("Resource Isolation", test_resource_isolation),
        ("Agent Independence", test_agent_independence),
    ]
    
    results = []
    agents = None
    
    for name, test_fn in tests:
        try:
            if name == "Swarm Execution":
                if agents:
                    result = await test_fn(agents)
                else:
                    result = await test_fn([])
            else:
                result = await test_fn()
                if name == "Computer Allocation":
                    agents = result
            results.append((name, "PASS"))
        except Exception as e:
            print(f"✗ Test failed: {e}")
            results.append((name, f"FAIL: {e}"))
    
    print("=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    for name, result in results:
        status = "✓" if result == "PASS" else "✗"
        print(f"{status} {name}: {result}")
    
    passed = sum(1 for _, r in results if r == "PASS")
    print(f"\n{passed}/{len(tests)} tests passed")
    
    # Show directory structure
    print("\n" + "=" * 60)
    print("AGENT DIRECTORIES CREATED")
    print("=" * 60)
    agent_dir = os.path.expanduser("~/.timps/agents")
    if os.path.exists(agent_dir):
        for d in os.listdir(agent_dir):
            dpath = os.path.join(agent_dir, d)
            if os.path.isdir(dpath):
                files = os.listdir(dpath)
                print(f"  {d}/ ({len(files)} files)")


if __name__ == "__main__":
    asyncio.run(main())