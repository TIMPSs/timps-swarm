# TIMPS Swarm 🤖

A production-ready multi-agent coding system built around [TIMPS-Coder](https://github.com/Sandeeprdy1729/timps-coder) — a fine-tuned 0.5B bug-fixing model. 10 specialised AI agents collaborate to handle the full software development lifecycle, while 20 LoRA adapters give TIMPS-Coder deep expertise in specific bug patterns.

**New: Each sub-agent now runs on its own computer with dedicated compute resources!**

---

## Architecture

```
╔════════════════════════════════════════════════════════════════════════════════════════╗
║                    TIMPS SWARM 3-LAYER ARCHITECTURE                 ║
╠════════════════════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  Layer 3: CLI Commands (swarm control)                                 ║
║     /swarm spawn <role> /swarm task <request> /swarm status           ║
║                         │                                           ║
║  Layer 2: Swarm Bridge (agent orchestration)                        ║
║     spawn_sub_agent() → run_swarm_task() → orchestrate()             ║
║                         │                                           ║
║  Layer 1: Computer Manager (compute allocation)                  ║
║     Each agent gets: ~/agents/<agent_id>/ with CPU/RAM/disk quotas   ║
║                         │                                           ║
║                    timps-swarm LangGraph DAG (10 agents)            ║
╚════════════════════════════════════════════════════════════════════════════════════════╝

User Request
     │
     ▼
┌────────────┐     ┌─────────────────────────────────────────────────┐
│Orchestrator│────▶│  Product Manager → Architect → Code Generator   │
│  (qwen:14b)│◀────│  Code Reviewer → QA Tester → Security Auditor   │
└────────────┘     │  Performance Optimizer → Docs Writer → DevOps   │
                   └─────────────────────────────────────────────────┘
                              All coordinated via LangGraph DAG
```

### Each Sub-Agent Has Its Own Computer

```python
# Layer 1: Computer Manager
computer = cm.allocate_computer("code_generator")
# → Creates: ~/.timps/agents/code_generator-a1b2c3d4/
# → CPU quota: 40%
# → Memory: 2048MB
# → Each agent is isolated!

# Layer 2: Swarm Bridge
bridge.spawn_sub_agent(AgentRole.CODE_GENERATOR)
# → Spawns agent with its own computer
# → Agent writes to its own directory only

# Layer 3: CLI
timps swarm run "fix this bug"
# → Whole swarm works on task
# → Each agent uses its own compute
```

### The 10 Agents

| # | Agent | Model | Role |
|---|-------|-------|------|
| 1 | **Orchestrator** | qwen2.5:14b | Plans task DAG, routes work, handles retries |
| 2 | **Product Manager** | qwen2.5:7b | Writes PRDs and acceptance criteria |
| 3 | **Architect** | qwen2.5:14b | Designs system structure and API contracts |
| 4 | **Code Generator** | TIMPS-Coder + qwen2.5-coder:7b | Implements code; uses TIMPS for bug fixes |
| 5 | **Code Reviewer** | qwen2.5:7b | Reviews PRs for bugs and anti-patterns |
| 6 | **QA Tester** | qwen2.5-coder:7b | Writes pytest suites, runs tests in sandbox |
| 7 | **Security Auditor** | qwen2.5:7b | OWASP scanning, runs bandit, CVE detection |
| 8 | **Performance Optimizer** | qwen2.5:7b | Big-O analysis, N+1 detection, caching |
| 9 | **Docs Writer** | qwen2.5:3b | README, API docs, deployment guides |
| 10 | **DevOps** | qwen2.5:7b | Dockerfile, GitHub Actions, Terraform |

### The 20 TIMPS-Coder Adapters

Each adapter is a specialised LoRA fine-tune for a specific bug class:

`java_npe` · `java_ioob` · `java_concurrent` · `python_keyerror` · `python_typeerror` · `python_recursion` · `python_async` · `python_logic` · `javascript_null` · `javascript_scope` · `javascript_async` · `cpp_memory` · `cpp_bounds` · `go_routine` · `rust_borrow` · `sql_injection` · `xss_vuln` · `auth_bypass` · `performance_slow` · `api_design`

---

## Quick Start

### Option A: Docker (Recommended)

```bash
# 1. Clone
git clone https://github.com/Sandeeprdy1729/timps-coder
cd timps-swarm

# 2. Configure
cp .env.example .env
# Edit .env with your HF_TOKEN if you want to push adapters

# 3. One-command setup + launch
make all

# 4. Open dashboard
open http://localhost:3000

# 5. Fire a task
make run REQ="Fix the NullPointerException in my Spring Boot AuthService and write tests"
```

### Option B: Local (No Docker)

```bash
# Install Python deps
make install

# Start Ollama and pull models (one time)
ollama serve &
ollama pull qwen2.5:14b
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5:3b

# Run the API
make up-local

# In a separate terminal, run the dashboard
make ui
```

---

## Adding New Training Data & Auto-Training

This is how you push new bug-fix data and have GitHub Actions train adapters automatically.

### Step 1: Create a dataset file

Create a `.jsonl` file in `datasets/custom/` with your bug-fix pairs:

```jsonl
{"messages":[
  {"role":"system","content":"You are TIMPS-Coder..."},
  {"role":"user","content":"Fix this buggy code:\n```python\n# buggy code here\n```"},
  {"role":"assistant","content":"**Root cause:** ...\n\n**Fixed code:**\n```python\n# fixed code\n```"}
]}
```

**Shortcut format** (auto-converted by `build_clean_dataset.py`):
```jsonl
{"buggy_code": "...", "fixed_code": "...", "explanation": "The bug was..."}
{"instruction": "Fix the NullPointerException in...", "output": "Root cause: ...\nFixed:\n```java\n...```"}
```

### Step 2: Push to GitHub

```bash
# Add your dataset file
cp my_java_bugs.jsonl datasets/custom/

git add datasets/custom/my_java_bugs.jsonl
git commit -m "feat: add 50 new Java NPE training samples"
git push origin main
```

### Step 3: GitHub Actions trains automatically

Pushing to `main` with changes in `datasets/` triggers the CI pipeline:

1. **build-dataset** — Merges all your custom files + HuggingFace data
2. **train-adapter** — 20 parallel jobs train specialised LoRA adapters (macOS runners with MLX)
3. **benchmark** — Evaluates each adapter against test cases
4. **release** — Publishes adapter bundle to GitHub Releases + HuggingFace Hub

Monitor at: `github.com/YOUR_REPO/actions`

### Step 4: Set GitHub Secrets

In your repo → **Settings → Secrets → Actions**, add:

| Secret | Value |
|--------|-------|
| `HF_TOKEN` | Your HuggingFace token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `HF_REPO_ID` | e.g. `sandeeprdy1729/timps-coder-adapters` |

---

## Manual Training (Local)

```bash
# Build dataset from your custom files
make dataset

# Train all 20 adapters (requires MLX on Apple Silicon)
make train

# Or train a single adapter
BASE_MODEL=Qwen/Qwen2.5-Coder-0.5B-Instruct \
ITERS=1000 \
bash retrain-specialized.sh
```

---

## API Reference

```bash
# Health check
curl http://localhost:8000/health

# Launch a swarm task
curl -X POST http://localhost:8000/swarm/run \
  -H "Content-Type: application/json" \
  -d '{
    "request": "Fix SQL injection in my FastAPI user endpoint",
    "language": "python",
    "max_iterations": 10
  }'

# Poll status
curl http://localhost:8000/swarm/status?run_id=abc12345

# List all runs
curl http://localhost:8000/swarm/runs

# Real-time WebSocket
wscat -c ws://localhost:8000/ws
```

---

## Python API (New 3-Layer System)

### Layer 1: Computer Manager

```python
from src.layer1_computer_manager import get_computer_manager, ComputeResources

cm = get_computer_manager()

# Allocate a computer for an agent
computer = cm.allocate_computer("code_generator")
# → AgentComputer(agent_id="code_generator-abc123", working_dir="~/.timps/agents/code_generator-abc123/")

# Check system resources
resources = cm.check_resources()
# → {cpu_count: 8, memory_available_mb: 16384, ...}

# List all agents
agents = cm.list_agents()
# → {total: 5, max: 10, agents: {...}}

# Release an agent
cm.release_computer(agent_id)
```

### Layer 2: Swarm Bridge

```python
from src.layer2_swarm_bridge import get_swarm_bridge, AgentRole

bridge = get_swarm_bridge()

# Spawn a sub-agent with its own computer
agent = await bridge.spawn_sub_agent(AgentRole.CODE_GENERATOR, initial_task="write code")
# → SubAgent(id="code_generator-xyz", role=AgentRole.CODE_GENERATOR, computer=AgentComputer(...))

# Spawn a team
agents = await bridge.spawn_agent_team([
    AgentRole.CODE_GENERATOR,
    AgentRole.QA_TESTER,
])

# Run a full swarm task
task = await bridge.run_swarm_task("Fix the bug in AuthService", language="python")
# → SwarmTask(id="task-123", status="completed", artifacts=[...])

# Get swarm status
status = bridge.get_swarm_status()
```

### Layer 3: CLI

```python
from src.layer3_swarm_cli import run_swarm_command

# Run a command
result = await run_swarm_command("spawn code_generator write hello")
# → SwarmCommand(success=True, message="Spawned code_generator...")

# Available commands:
# - spawn <role> [task]
# - task <request>
# - team <roles>
# - status
# - resources
# - kill <agent_id>
```

---

## Give Work to Swarm

```bash
# Give task to whole swarm
python3 give_work.py "Write a hello world function"

# With specific language
python3 give_work.py "Create a REST API" -l python

# Spawn specific agents only
python3 give_work.py --spawn code_generator qa_tester "Write code and test it"

# Spawn single agent
python3 give_work.py --spawn code_generator "Fix the NullPointerException"
```

---

## Hardware Requirements

| Setup | RAM | What runs |
|-------|-----|-----------|
| Minimum | 8 GB | Swarm API + 1 Ollama model at a time |
| Recommended | 16 GB | All Ollama models loaded simultaneously |
| Training | 8 GB+ (Apple M1/M2) | MLX adapter training |
| 300-agent scale | 64 GB server | Multiple Ollama instances behind a load balancer |

---

## Scaling to 300 Agents

To reach Kimi K2.6-scale parallelism:

```python
# Pattern 1: Shard by file (one agent per source file)
files = glob("src/**/*.py")
tasks = [Task(id=f"fix-{i}", description=f"Fix bugs in {f}") for i, f in enumerate(files)]

# Pattern 2: Ensemble fixes (10 candidates per bug → Critic votes)
candidates = await asyncio.gather(*[
    code_generator_fix(bug, strategy=s)
    for s in ["conservative", "minimal", "refactor", "defensive", "async"]
])
best = await critic_vote(candidates)
```

Edit `MAX_PARALLEL_AGENTS` in `.env` to control concurrency.

---

## License

MIT — see [TIMPS-Coder repo](https://github.com/Sandeeprdy1729/timps-coder) for model license.
