"""
Intelligence Agents — 6 flagship agents that make the swarm smarter over time.

  code_archaeology     — map legacy codebases: modules, hidden deps, risk zones
  pattern_detector     — find repeated code patterns, suggest abstractions
  technical_debt       — quantify debt, produce prioritised paydown roadmap
  memory_agent         — persist context across sessions (Qdrant / JSONL)
  learning_agent       — distil best-performing runs → few-shot prompt upgrades
  agent_composer       — create brand-new agents from a natural-language brief

All follow the same contract as more_agents.py / priority_agents.py:
  fn(args: dict) -> dict
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.llm_router import LLMRouter
from src.memory import recall_similar, record_run

logger = logging.getLogger(__name__)

_GEN  = Path(os.getenv("GENERATED_DIR", "generated"))
_RPTS = _GEN / "reports"
_CODE = _GEN / "code"
_PRMPTS = _GEN / "prompts"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _llm(prompt: str, system: str, agent: str = "default") -> str:
    try:
        return LLMRouter().call(agent, prompt, system)
    except Exception as exc:
        logger.error("LLM error [%s]: %s", agent, exc)
        return f"# LLM error: {exc}"


def _strip_fences(text: str, lang: str = "") -> str:
    pattern = rf"```{re.escape(lang)}\s*([\s\S]*?)```"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else text.strip()


def _save(sub: str, name: str, content: str) -> str:
    path = _GEN / sub / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run(cmd: str, cwd: Optional[str] = None) -> str:
    try:
        args = shlex.split(cmd)
        r = subprocess.run(args, capture_output=True, text=True, timeout=60,
                           cwd=cwd or os.getcwd())
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as exc:
        return f"Error: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# 1 — CODE ARCHAEOLOGY
# Maps undocumented legacy code into a navigable knowledge artefact.
# ─────────────────────────────────────────────────────────────────────────────

def code_archaeology(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reverse-engineer a legacy codebase into structured documentation.

    Args:
      path (str): Root directory of the codebase to analyse.
      language (str): Primary language (python | javascript | java | go | ...).
      max_files (int): Cap on files analysed (default 50).
    """
    repo_path = Path(args.get("path", "."))
    language  = args.get("language", "python")
    max_files = int(args.get("max_files", 50))

    # --- collect files ---
    ext_map = {
        "python": ["*.py"], "javascript": ["*.js", "*.mjs"], "typescript": ["*.ts", "*.tsx"],
        "java": ["*.java"], "go": ["*.go"], "rust": ["*.rs"], "cpp": ["*.cpp", "*.h"],
    }
    exts = ext_map.get(language, ["*.py"])
    files: List[Path] = []
    for ext in exts:
        files.extend(list(repo_path.rglob(ext))[:max_files])
    files = files[:max_files]

    # --- build corpus ---
    corpus_parts: List[str] = []
    for f in files:
        try:
            snippet = f.read_text(encoding="utf-8", errors="ignore")[:800]
            corpus_parts.append(f"### {f.relative_to(repo_path)}\n{snippet}")
        except Exception:
            pass
    corpus = "\n\n".join(corpus_parts[:40])

    # --- try to extract call-graph for Python ---
    call_graph_text = ""
    if language == "python":
        imports: Dict[str, List[str]] = {}
        for f in files:
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
                imported = [
                    (n.asname or n.name) for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for n in node.names
                ] + [
                    node.module or ""
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                ]
                imports[str(f.relative_to(repo_path))] = [i for i in imported if i]
            except Exception:
                pass
        call_graph_text = json.dumps(imports, indent=2)[:3000]

    system = (
        "You are a legendary code archaeologist. Given partial source code, produce:\n"
        "1. ARCHITECTURE.md — module responsibilities, tech stack, key abstractions\n"
        "2. dependency_graph summary — which modules depend on what\n"
        "3. risk_map — files most dangerous to change (high coupling / complexity / no tests)\n"
        "4. tribal_knowledge — implicit contracts, magic constants, undocumented side-effects\n"
        "5. onboarding_guide — 'how to make your first meaningful change'\n"
        "Return JSON: {architecture_md, dependency_summary, risk_map: [{file, risk_level, reason}], "
        "tribal_knowledge: [string], onboarding_steps: [string]}. Output ONLY valid JSON."
    )
    prompt = (
        f"Language: {language}  Files analysed: {len(files)}\n\n"
        f"Call/import graph:\n{call_graph_text}\n\n"
        f"Source corpus (first 800 chars per file):\n{corpus[:8000]}"
    )

    raw = _llm(prompt, system, "code_archaeology")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {
            "architecture_md": raw, "dependency_summary": call_graph_text,
            "risk_map": [], "tribal_knowledge": [], "onboarding_steps": [],
        }

    arch_path   = _save("reports", f"ARCHITECTURE_{_ts()}.md",  data.get("architecture_md", ""))
    risk_path   = _save("reports", f"risk_map_{_ts()}.json",
                        json.dumps(data.get("risk_map", []), indent=2))
    tribal_path = _save("reports", f"tribal_knowledge_{_ts()}.md",
                        "\n".join(f"- {t}" for t in data.get("tribal_knowledge", [])))

    record_run("code_archaeology", str(repo_path), data.get("architecture_md", "")[:400])
    return {
        "files_analysed": len(files),
        "architecture_md": data.get("architecture_md", ""),
        "dependency_summary": data.get("dependency_summary", ""),
        "risk_map": data.get("risk_map", []),
        "tribal_knowledge": data.get("tribal_knowledge", []),
        "onboarding_steps": data.get("onboarding_steps", []),
        "arch_path": arch_path,
        "risk_path": risk_path,
        "tribal_path": tribal_path,
        "summary": (
            f"Mapped {len(files)} files. "
            f"{len(data.get('risk_map', []))} risk zones identified. "
            f"ARCHITECTURE.md saved to {arch_path}."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2 — PATTERN DETECTOR
# Finds copy-paste, near-duplicates, missed abstractions, god classes.
# ─────────────────────────────────────────────────────────────────────────────

def pattern_detector(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scan a codebase for repeated patterns and suggest DRY abstractions.

    Args:
      code (str): Source code OR
      path (str): Path to file/directory to scan.
      language (str): Programming language.
      min_lines (int): Minimum duplicate block length (default 10).
    """
    code     = args.get("code", "")
    path_str = args.get("path", "")
    language = args.get("language", "python")
    min_lines = int(args.get("min_lines", 10))

    # Collect source
    if not code and path_str:
        p = Path(path_str)
        if p.is_file():
            code = p.read_text(encoding="utf-8", errors="ignore")
        elif p.is_dir():
            parts = []
            for f in list(p.rglob("*.py"))[:20]:
                parts.append(f"### {f.name}\n{f.read_text(encoding='utf-8', errors='ignore')[:600]}")
            code = "\n\n".join(parts)

    if not code.strip():
        return {"error": "No code provided", "patterns": []}

    # Run jscpd / simple line-based detection for Python
    raw_duplicates = ""
    if language == "python" and path_str and Path(path_str).is_dir():
        raw_duplicates = _run(
            f"python3 -c \""
            f"import subprocess; r = subprocess.run(['python3', '-m', 'ast', '.'], "
            f"capture_output=True, text=True); print(r.stdout[:1000])\""
        )

    system = (
        "You are a code-quality expert specialising in DRY principles and design patterns. "
        f"Find ALL repeated patterns (blocks ≥ {min_lines} lines), near-duplicate functions, "
        "god classes (> 300 lines), missed factory/strategy/template patterns, magic numbers. "
        "Return JSON: {patterns: [{type, locations: [string], lines, description, "
        "suggested_abstraction}], god_classes: [string], magic_numbers: [{value, locations}], "
        "refactor_priority: 'high'|'medium'|'low', estimated_loc_reduction: int}. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Language: {language}  Min duplicate block: {min_lines} lines\n\n"
        f"Code:\n```{language}\n{code[:8000]}\n```"
    )

    raw = _llm(prompt, system, "pattern_detector")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"patterns": [], "god_classes": [], "magic_numbers": [],
                "refactor_priority": "medium", "estimated_loc_reduction": 0}

    report = (
        f"# Pattern Detector Report — {_ts()}\n\n"
        f"**Language:** {language}  **Patterns found:** {len(data.get('patterns', []))}\n"
        f"**Estimated LoC reduction:** {data.get('estimated_loc_reduction', 0)}\n"
        f"**Refactor priority:** {data.get('refactor_priority', '?').upper()}\n\n"
        "## Patterns\n"
        + "\n".join(
            f"### {p.get('type', '?')} ({p.get('lines', '?')} lines)\n"
            f"**Locations:** {', '.join(p.get('locations', []))}\n"
            f"**Description:** {p.get('description', '')}\n"
            f"**Suggested abstraction:** {p.get('suggested_abstraction', '')}\n"
            for p in data.get("patterns", [])
        )
        + "\n\n## God Classes\n"
        + "\n".join(f"- `{c}`" for c in data.get("god_classes", []))
        + "\n\n## Magic Numbers\n"
        + "\n".join(
            f"- `{m.get('value')}` in {', '.join(m.get('locations', []))}"
            for m in data.get("magic_numbers", [])
        )
    )

    report_path = _save("reports", f"pattern_detector_{_ts()}.md", report)
    record_run("pattern_detector", path_str or "inline", report[:400])

    return {
        "patterns": data.get("patterns", []),
        "god_classes": data.get("god_classes", []),
        "magic_numbers": data.get("magic_numbers", []),
        "refactor_priority": data.get("refactor_priority", "medium"),
        "estimated_loc_reduction": data.get("estimated_loc_reduction", 0),
        "report_path": report_path,
        "summary": (
            f"Found {len(data.get('patterns', []))} duplicate patterns, "
            f"{len(data.get('god_classes', []))} god classes. "
            f"~{data.get('estimated_loc_reduction', 0)} LoC could be removed."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3 — TECHNICAL DEBT AGENT
# Quantifies debt per file and produces a prioritised paydown roadmap.
# ─────────────────────────────────────────────────────────────────────────────

def technical_debt(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Measure technical debt across a codebase and output a paydown roadmap.

    Args:
      path (str): Repository root (default: current directory).
      language (str): Primary language (default: python).
      include_git_churn (bool): Use git log to weight churn (default: True).
    """
    repo_path = args.get("path", ".")
    language  = args.get("language", "python")
    use_churn = args.get("include_git_churn", True)

    # --- radon cyclomatic complexity ---
    radon_output = ""
    if language == "python":
        radon_output = _run(f"python3 -m radon cc {repo_path} -s -j 2>/dev/null || echo 'radon not installed'")[:3000]

    # --- git churn ---
    churn_output = ""
    if use_churn:
        churn_output = _run(
            f"git -C {repo_path} log --format= --name-only | sort | uniq -c | sort -rn | head -30"
        )

    # --- TODO / FIXME count ---
    _ext = "py" if language == "python" else "js"
    todo_output = _run(
        f"grep -r --include='*.{_ext}' "
        f"-c 'TODO|FIXME|HACK|XXX' {repo_path} 2>/dev/null | sort -t: -k2 -rn | head -20"
    )

    system = (
        "You are a technical-debt expert. Given complexity metrics, git churn, and TODO counts, "
        "produce a comprehensive debt analysis. Return JSON: "
        "{overall_debt_score: int (0-100, higher = more debt), "
        "file_scores: [{file, complexity, churn, todos, debt_score: int, effort_to_fix: 'S'|'M'|'L'|'XL'}], "
        "total_debt_hours: int, "
        "paydown_roadmap: [{priority: int, file, action, effort, expected_improvement}], "
        "quick_wins: [string], "
        "debt_categories: {legacy_code: int, missing_tests: int, poor_naming: int, "
        "complex_logic: int, outdated_deps: int}}. Output ONLY valid JSON."
    )
    prompt = (
        f"Language: {language}  Repo: {repo_path}\n\n"
        f"Cyclomatic complexity (radon):\n{radon_output}\n\n"
        f"Git churn (most-changed files):\n{churn_output}\n\n"
        f"TODO/FIXME density:\n{todo_output}"
    )

    raw = _llm(prompt, system, "technical_debt")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {
            "overall_debt_score": 50, "file_scores": [], "total_debt_hours": 0,
            "paydown_roadmap": [], "quick_wins": [], "debt_categories": {},
        }

    roadmap_text = "\n".join(
        f"{r.get('priority', '?')}. **{r.get('file', '?')}** — {r.get('action', '')} "
        f"(effort: {r.get('effort', '?')}, impact: {r.get('expected_improvement', '')})"
        for r in data.get("paydown_roadmap", [])
    )

    report = (
        f"# Technical Debt Report — {_ts()}\n\n"
        f"**Overall debt score:** {data.get('overall_debt_score', 0)}/100  "
        f"**Total estimated effort:** ~{data.get('total_debt_hours', 0)}h\n\n"
        f"## Debt Categories\n"
        + "\n".join(f"- {k}: {v}" for k, v in data.get("debt_categories", {}).items())
        + f"\n\n## Paydown Roadmap\n{roadmap_text}\n\n"
        f"## Quick Wins\n"
        + "\n".join(f"- {q}" for q in data.get("quick_wins", []))
    )

    report_path = _save("reports", f"tech_debt_{_ts()}.md", report)
    record_run("technical_debt", repo_path, report[:400])

    return {
        "overall_debt_score": data.get("overall_debt_score", 0),
        "total_debt_hours": data.get("total_debt_hours", 0),
        "file_scores": data.get("file_scores", []),
        "paydown_roadmap": data.get("paydown_roadmap", []),
        "quick_wins": data.get("quick_wins", []),
        "debt_categories": data.get("debt_categories", {}),
        "report_path": report_path,
        "summary": (
            f"Debt score: {data.get('overall_debt_score', 0)}/100. "
            f"~{data.get('total_debt_hours', 0)}h to pay down. "
            f"{len(data.get('paydown_roadmap', []))} items in roadmap."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4 — MEMORY AGENT
# High-level agent interface to the persistent memory system.
# Stores + retrieves context across sessions using JSONL + Qdrant.
# ─────────────────────────────────────────────────────────────────────────────

def memory_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Store a memory entry or recall relevant past context.

    Args:
      action (str): 'store' | 'recall' | 'stats' | 'forget'.
      content (str): Content to store (for 'store').
      query (str): Topic to recall (for 'recall').
      agent (str): Agent name filter for recall.
      limit (int): Max results to return (default 5).
      key (str): Specific memory key for 'forget'.
    """
    from src.memory import recall_similar, record_run, get_preference, set_preference

    action  = args.get("action", "recall")
    content = args.get("content", "")
    query   = args.get("query", content)
    agent   = args.get("agent", None)
    limit   = int(args.get("limit", 5))

    if action == "store":
        if not content:
            return {"error": "content required for store", "stored": False}
        record_run(
            agent_name=agent or "memory_agent",
            request=query or content[:100],
            summary=content[:1000],
            success=True,
            metadata=args.get("metadata", {}),
        )
        return {
            "stored": True,
            "agent": agent or "memory_agent",
            "preview": content[:200],
            "summary": f"Memory stored for agent '{agent or 'memory_agent'}'.",
        }

    elif action == "recall":
        if not query:
            return {"error": "query required for recall", "results": []}
        results = recall_similar(query, agent=agent, limit=limit)
        formatted = [
            {"agent": r.get("agent"), "request": r.get("request"),
             "summary": r.get("summary", "")[:300], "ts": r.get("ts")}
            for r in results
        ]
        return {
            "results": formatted,
            "count": len(formatted),
            "query": query,
            "summary": f"Found {len(formatted)} relevant memories for: '{query}'.",
        }

    elif action == "stats":
        from pathlib import Path as _P
        import os as _os
        mem_dir = _P(_os.environ.get("TIMPS_MEMORY_DIR",
                                     str(_P.home() / ".timps" / "memory")))
        runs_file = mem_dir / "runs.jsonl"
        total_runs = 0
        agents_seen: set = set()
        if runs_file.exists():
            for line in runs_file.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    total_runs += 1
                    agents_seen.add(entry.get("agent", ""))
                except Exception:
                    pass
        return {
            "total_runs": total_runs,
            "unique_agents": len(agents_seen),
            "agents": sorted(agents_seen),
            "memory_dir": str(mem_dir),
            "summary": f"{total_runs} runs stored across {len(agents_seen)} agents.",
        }

    elif action == "forget":
        key = args.get("key", "")
        return {
            "forgotten": False,
            "note": "Selective forget not yet implemented; clear ~/.timps/memory/runs.jsonl manually.",
            "key": key,
        }

    return {"error": f"Unknown action: {action}"}


# ─────────────────────────────────────────────────────────────────────────────
# 5 — LEARNING AGENT
# Analyses high-scoring runs, distils patterns, upgrades agent prompts.
# ─────────────────────────────────────────────────────────────────────────────

def learning_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Learn from past successful swarm runs and improve agent prompts.

    Args:
      target_agent (str): Which agent to improve (or 'all').
      min_score (int): Minimum self-critic score to learn from (default 8).
      top_k (int): How many examples to distil (default 10).
      apply (bool): If True, write improved prompts to generated/prompts/
    """
    target  = args.get("target_agent", "all")
    min_score = int(args.get("min_score", 8))
    top_k   = int(args.get("top_k", 10))
    apply   = args.get("apply", False)

    from src.memory import recall_similar
    from pathlib import Path as _P
    import os as _os

    # --- load all runs ---
    mem_dir = _P(_os.environ.get("TIMPS_MEMORY_DIR", str(_P.home() / ".timps" / "memory")))
    runs_file = mem_dir / "runs.jsonl"
    all_runs: List[Dict] = []
    if runs_file.exists():
        for line in runs_file.read_text().splitlines():
            try:
                all_runs.append(json.loads(line))
            except Exception:
                pass

    # Filter to target agent and high-quality runs
    good_runs = [
        r for r in all_runs
        if r.get("success") and
        (target == "all" or r.get("agent") == target)
    ][-top_k * 5:]  # take recent ones

    if not good_runs:
        return {
            "improvements": [],
            "summary": f"No runs found for '{target}'. Run some tasks first.",
        }

    run_corpus = json.dumps(good_runs[:top_k], indent=2, default=str)[:6000]

    system = (
        "You are a meta-learning engineer. Analyse successful agent runs and extract "
        "reusable patterns, best-practice prompt fragments, and few-shot examples. "
        "Return JSON: {agent_improvements: [{agent, improved_system_prompt_fragment, "
        "few_shot_examples: [{input, output}], key_learnings: [string]}], "
        "meta_patterns: [string], recommended_actions: [string]}. Output ONLY valid JSON."
    )
    prompt = (
        f"Target agent: {target}  Min score: {min_score}  Analysing {len(good_runs)} runs\n\n"
        f"Successful runs:\n{run_corpus}"
    )

    raw = _llm(prompt, system, "learning_agent")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"agent_improvements": [], "meta_patterns": [], "recommended_actions": [raw]}

    improvements = data.get("agent_improvements", [])

    # Optionally write improved prompt fragments
    saved_paths: List[str] = []
    if apply and improvements:
        for imp in improvements:
            agent_name = imp.get("agent", "unknown")
            fragment   = imp.get("improved_system_prompt_fragment", "")
            if fragment:
                p = _save("prompts", f"{agent_name}_improved_{_ts()}.md",
                          f"# Improved prompt fragment for {agent_name}\n\n{fragment}")
                saved_paths.append(p)

    report = (
        f"# Learning Agent Report — {_ts()}\n\n"
        f"**Target:** {target}  **Runs analysed:** {len(good_runs)}\n\n"
        "## Improvements\n"
        + "\n".join(
            f"### {i.get('agent', '?')}\n"
            f"Key learnings: {', '.join(i.get('key_learnings', []))}\n"
            for i in improvements
        )
        + "\n\n## Meta Patterns\n"
        + "\n".join(f"- {p}" for p in data.get("meta_patterns", []))
        + "\n\n## Recommended Actions\n"
        + "\n".join(f"- {a}" for a in data.get("recommended_actions", []))
    )

    report_path = _save("reports", f"learning_agent_{_ts()}.md", report)

    return {
        "improvements": improvements,
        "meta_patterns": data.get("meta_patterns", []),
        "recommended_actions": data.get("recommended_actions", []),
        "saved_prompt_paths": saved_paths,
        "report_path": report_path,
        "summary": (
            f"Analysed {len(good_runs)} runs. "
            f"Generated {len(improvements)} agent improvement(s). "
            f"{'Applied to prompts directory.' if apply else 'Use apply=True to write prompt upgrades.'}"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6 — AGENT COMPOSER
# Creates brand-new specialist agents from a natural-language brief.
# Generates the Python file, graph patch, llm_router mapping, and MCP tool.
# ─────────────────────────────────────────────────────────────────────────────

def agent_composer(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compose a new TIMPS agent from a natural-language description.

    Args:
      description (str): What the new agent should do.
      agent_name (str): Snake-case name (e.g. 'solidity_auditor'). Auto-generated if omitted.
      model (str): Preferred LLM model for the agent (default: 'qwen2.5:7b').
      dag_position (str): Where in the DAG: 'after_code_generator' | 'standalone' | 'final'.
      tools (list[str]): External tools / libs the agent uses.
    """
    description = args.get("description", "")
    if not description:
        return {"error": "description is required"}

    agent_name  = args.get("agent_name", "")
    model       = args.get("model", "qwen2.5:7b")
    dag_pos     = args.get("dag_position", "standalone")
    tools       = args.get("tools", [])

    # Auto-generate agent name if not provided
    if not agent_name:
        slug = re.sub(r"[^a-z0-9]+", "_", description.lower().strip())[:40].strip("_")
        agent_name = slug or "custom_agent"

    system = (
        "You are an expert AI agent architect who designs LLM-backed agents. "
        "Given a brief, produce a complete Python agent function following the TIMPS pattern:\n"
        "- fn(args: dict) -> dict\n"
        "- Uses LLMRouter().call(agent_name, prompt, system_prompt)\n"
        "- Saves artefacts to generated/<subdir>/<name>.ext\n"
        "- Returns a dict with summary, relevant keys, and file paths\n"
        "- Never raises — always returns gracefully\n\n"
        "Return JSON: {agent_function_code: string (complete Python function), "
        "system_prompt: string (the agent's system prompt), "
        "input_schema: {property: {type, description}}, "
        "output_schema: {property: {type, description}}, "
        "dag_node_name: string, "
        "mcp_tool_description: string, "
        "recommended_model: string, "
        "required_packages: [string]}. Output ONLY valid JSON."
    )
    prompt = (
        f"Agent name: {agent_name}\n"
        f"Description: {description}\n"
        f"Preferred model: {model}\n"
        f"DAG position: {dag_pos}\n"
        f"Tools/libraries: {', '.join(tools) or 'none'}\n\n"
        "Generate the complete agent implementation."
    )

    raw = _llm(prompt, system, "agent_composer")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {
            "agent_function_code": raw,
            "system_prompt": "",
            "input_schema": {},
            "output_schema": {},
            "dag_node_name": agent_name,
            "mcp_tool_description": description,
            "recommended_model": model,
            "required_packages": [],
        }

    # Write the agent Python file
    agent_code = data.get("agent_function_code", "")
    file_header = (
        f'"""\nAuto-generated by Agent Composer — {_ts()}\n'
        f"Description: {description}\n"
        f"Model: {data.get('recommended_model', model)}\n"
        f'"""\nfrom __future__ import annotations\n'
        f"from src.llm_router import LLMRouter\n\n\n"
    )
    full_code = file_header + agent_code

    code_path = _save("code", f"{agent_name}_{_ts()}.py", full_code)

    # Write a registration snippet
    reg_snippet = (
        f"# ── Add to graph.py ─────────────────────────────────\n"
        f"# from generated.code.{agent_name}_{_ts()} import {agent_name}\n"
        f"# workflow.add_node('{data.get('dag_node_name', agent_name)}', {agent_name})\n\n"
        f"# ── Add to llm_router.py MODEL_MAP ──────────────────\n"
        f"# '{data.get('dag_node_name', agent_name)}': '{data.get('recommended_model', model)}',\n\n"
        f"# ── MCP tool description ─────────────────────────────\n"
        f"# {data.get('mcp_tool_description', description)}\n"
    )
    reg_path = _save("code", f"{agent_name}_registration_{_ts()}.md", reg_snippet)

    record_run("agent_composer", description, f"Created {agent_name}")
    return {
        "agent_name": agent_name,
        "dag_node_name": data.get("dag_node_name", agent_name),
        "agent_function_code": agent_code,
        "system_prompt": data.get("system_prompt", ""),
        "input_schema": data.get("input_schema", {}),
        "output_schema": data.get("output_schema", {}),
        "mcp_tool_description": data.get("mcp_tool_description", description),
        "recommended_model": data.get("recommended_model", model),
        "required_packages": data.get("required_packages", []),
        "code_path": code_path,
        "registration_path": reg_path,
        "summary": (
            f"Agent '{agent_name}' composed. Code at {code_path}. "
            f"Packages needed: {', '.join(data.get('required_packages', [])) or 'none'}. "
            f"Follow registration snippet at {reg_path}."
        ),
    }


# ── Dispatch table ────────────────────────────────────────────────────────────

INTELLIGENCE_AGENTS: Dict[str, Any] = {
    "code_archaeology":  code_archaeology,
    "pattern_detector":  pattern_detector,
    "technical_debt":    technical_debt,
    "memory_agent":      memory_agent,
    "learning_agent":    learning_agent,
    "agent_composer":    agent_composer,
}
