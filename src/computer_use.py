"""
TIMPS Swarm — Real Computer Use Tools

Each agent can invoke these tools to actually operate a computer:
  - BrowserTool   : open URLs, click, type, screenshot, extract text (Playwright)
  - TerminalTool  : run shell commands in a sandboxed subprocess
  - SearchTool    : search the web via DuckDuckGo (no API key needed)
  - FileTool      : read / write / list files in the agent's working dir
  - CodeRunTool   : execute Python snippets and capture stdout/stderr

AgentComputer wraps all tools and provides a single interface agents use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"[ERROR] {self.error}\n{self.output}"


# ---------------------------------------------------------------------------
# BrowserTool — real Playwright automation
# ---------------------------------------------------------------------------

class BrowserTool:
    """
    Real browser automation via Playwright async API.
    Falls back to urllib-based fetching if Playwright is not installed.
    """

    def __init__(self, headless: bool = True, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._browser = None
        self._page = None
        self._playwright_available = self._check_playwright()

    def _check_playwright(self) -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            logger.warning("Playwright not installed — browser tool falls back to urllib")
            return False

    # --- internal helpers ---

    async def _ensure_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()
            await self._page.set_default_timeout(self.timeout_ms)

    async def _fallback_fetch(self, url: str) -> str:
        """Simple urllib fetch when Playwright unavailable."""
        req = urllib.request.Request(url, headers={"User-Agent": "TIMPS-Swarm/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = str(raw[:2000])
        # strip HTML tags naively
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000]

    # --- public API ---

    async def navigate(self, url: str) -> ToolResult:
        """Navigate to a URL and return the visible page text."""
        if not self._playwright_available:
            try:
                text = await self._fallback_fetch(url)
                return ToolResult(success=True, output=text, metadata={"url": url, "method": "urllib"})
            except Exception as exc:
                return ToolResult(success=False, output="", error=str(exc))
        try:
            await self._ensure_browser()
            response = await self._page.goto(url, wait_until="domcontentloaded")
            text = await self._page.inner_text("body")
            return ToolResult(
                success=True,
                output=text[:6000],
                metadata={"url": url, "status": response.status if response else None},
            )
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def click(self, selector: str) -> ToolResult:
        if not self._playwright_available:
            return ToolResult(success=False, output="", error="Playwright not available")
        try:
            await self._ensure_browser()
            await self._page.click(selector)
            return ToolResult(success=True, output=f"Clicked: {selector}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def type_text(self, selector: str, text: str) -> ToolResult:
        if not self._playwright_available:
            return ToolResult(success=False, output="", error="Playwright not available")
        try:
            await self._ensure_browser()
            await self._page.fill(selector, text)
            return ToolResult(success=True, output=f"Typed into {selector}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def screenshot(self, save_path: Optional[str] = None) -> ToolResult:
        if not self._playwright_available:
            return ToolResult(success=False, output="", error="Playwright not available")
        try:
            await self._ensure_browser()
            path = save_path or tempfile.mktemp(suffix=".png")
            await self._page.screenshot(path=path, full_page=True)
            return ToolResult(success=True, output=path, metadata={"screenshot_path": path})
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def extract_links(self) -> ToolResult:
        if not self._playwright_available:
            return ToolResult(success=False, output="", error="Playwright not available")
        try:
            await self._ensure_browser()
            links = await self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
            return ToolResult(success=True, output=json.dumps(links[:50]), metadata={"count": len(links)})
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def get_text(self, selector: str = "body") -> ToolResult:
        if not self._playwright_available:
            return ToolResult(success=False, output="", error="Playwright not available")
        try:
            await self._ensure_browser()
            text = await self._page.inner_text(selector)
            return ToolResult(success=True, output=text[:4000])
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None


# ---------------------------------------------------------------------------
# SearchTool — DuckDuckGo (no API key)
# ---------------------------------------------------------------------------

class SearchTool:
    """
    Web search using DuckDuckGo Instant Answer API + HTML scraping.
    No API key required.
    """

    DDG_API = "https://api.duckduckgo.com/"
    DDG_HTML = "https://html.duckduckgo.com/html/"

    def search(self, query: str, max_results: int = 5) -> ToolResult:
        """Return top search results as JSON list of {title, url, snippet}."""
        try:
            params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
            url = f"{self.DDG_API}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "TIMPS-Swarm/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            results: List[Dict] = []

            # Abstract (best answer)
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", "DuckDuckGo Abstract"),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data["AbstractText"][:500],
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if "Text" in topic and "FirstURL" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:80],
                        "url": topic["FirstURL"],
                        "snippet": topic["Text"][:300],
                    })
                # sub-topics
                for sub in topic.get("Topics", []):
                    if "Text" in sub and "FirstURL" in sub:
                        results.append({
                            "title": sub.get("Text", "")[:80],
                            "url": sub["FirstURL"],
                            "snippet": sub["Text"][:300],
                        })

            results = results[:max_results]
            if not results:
                return ToolResult(success=True, output=f"No results found for: {query}", metadata={"query": query})

            return ToolResult(
                success=True,
                output=json.dumps(results, indent=2),
                metadata={"query": query, "count": len(results)},
            )
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def search_code(self, query: str) -> ToolResult:
        """Search GitHub code via DuckDuckGo with site:github.com."""
        return self.search(f"site:github.com {query}")

    def search_docs(self, query: str, library: str = "") -> ToolResult:
        """Search documentation."""
        q = f"{library} {query} documentation" if library else f"{query} documentation"
        return self.search(q)


# ---------------------------------------------------------------------------
# TerminalTool — real subprocess execution (sandboxed)
# ---------------------------------------------------------------------------

# Commands that are never allowed regardless of context
_BLOCKED_COMMANDS = {
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=/dev/zero",
    ":(){ :|:& };:", "chmod -R 777 /", "> /etc/passwd",
    "curl | sh", "wget | sh", "wget -O- | bash",
}

_BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r">\s*/etc/(passwd|shadow|sudoers)",
    r"curl\s+.*\|\s*(ba)?sh",
    r"wget\s+.*\|\s*(ba)?sh",
]


def _is_safe_command(cmd: str) -> bool:
    cmd_lower = cmd.lower().strip()
    if cmd_lower in _BLOCKED_COMMANDS:
        return False
    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, cmd_lower):
            return False
    return True


class TerminalTool:
    """
    Run shell commands in a sandboxed subprocess with timeout and working-dir isolation.
    Dangerous commands are rejected before execution.
    """

    def __init__(self, working_dir: Optional[str] = None, timeout: int = 60):
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout

    def run(self, command: str, env_extra: Optional[Dict[str, str]] = None) -> ToolResult:
        """Execute a shell command and return combined stdout+stderr."""
        if not _is_safe_command(command):
            return ToolResult(success=False, output="", error=f"Command blocked by safety policy: {command}")

        env = {**os.environ, **(env_extra or {})}
        # Strip any inherited virtualenv to avoid conflicts
        env.pop("VIRTUAL_ENV", None)

        try:
            args = shlex.split(command)
            result = subprocess.run(
                args,
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
            combined = (result.stdout + result.stderr).strip()
            return ToolResult(
                success=result.returncode == 0,
                output=combined[:8000],
                error="" if result.returncode == 0 else f"exit code {result.returncode}",
                metadata={"returncode": result.returncode, "cmd": command},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Command timed out after {self.timeout}s")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def run_python(self, code: str) -> ToolResult:
        """Run a Python snippet in the current interpreter."""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            return self.run(f"{sys.executable} {shlex.quote(tmp)}")
        finally:
            os.unlink(tmp)

    def install_package(self, package: str) -> ToolResult:
        """pip install a package into the current environment."""
        # Only allow simple package names (no shell injection)
        if not re.fullmatch(r"[a-zA-Z0-9_\-\.\[\]>=<!,]+", package):
            return ToolResult(success=False, output="", error=f"Invalid package name: {package}")
        return self.run(f"{sys.executable} -m pip install {shlex.quote(package)} -q")


# ---------------------------------------------------------------------------
# FileTool — scoped file operations
# ---------------------------------------------------------------------------

class FileTool:
    """
    Read/write/list files scoped to the agent's working directory.
    Prevents path traversal outside the root.
    """

    def __init__(self, root_dir: str):
        self.root = Path(root_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str) -> Optional[Path]:
        resolved = (self.root / relative).resolve()
        if not str(resolved).startswith(str(self.root)):
            return None  # path traversal attempt
        return resolved

    def read(self, path: str) -> ToolResult:
        p = self._safe_path(path)
        if p is None:
            return ToolResult(success=False, output="", error="Path traversal denied")
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            return ToolResult(success=True, output=content, metadata={"path": str(p), "size": len(content)})
        except FileNotFoundError:
            return ToolResult(success=False, output="", error=f"File not found: {path}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def write(self, path: str, content: str) -> ToolResult:
        p = self._safe_path(path)
        if p is None:
            return ToolResult(success=False, output="", error="Path traversal denied")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Written {len(content)} chars to {path}", metadata={"path": str(p)})
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def append(self, path: str, content: str) -> ToolResult:
        p = self._safe_path(path)
        if p is None:
            return ToolResult(success=False, output="", error="Path traversal denied")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output=f"Appended {len(content)} chars to {path}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def list_dir(self, path: str = ".") -> ToolResult:
        p = self._safe_path(path)
        if p is None:
            return ToolResult(success=False, output="", error="Path traversal denied")
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = [f"{'[DIR] ' if e.is_dir() else '      '}{e.name}" for e in entries]
            return ToolResult(success=True, output="\n".join(lines), metadata={"count": len(lines)})
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))

    def delete(self, path: str) -> ToolResult:
        p = self._safe_path(path)
        if p is None:
            return ToolResult(success=False, output="", error="Path traversal denied")
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                import shutil
                shutil.rmtree(p)
            return ToolResult(success=True, output=f"Deleted: {path}")
        except Exception as exc:
            return ToolResult(success=False, output="", error=str(exc))


# ---------------------------------------------------------------------------
# CodeRunTool — run & test code with real output capture
# ---------------------------------------------------------------------------

class CodeRunTool:
    """Execute Python code and capture full output. Wraps TerminalTool."""

    def __init__(self, working_dir: str, timeout: int = 30):
        self._terminal = TerminalTool(working_dir=working_dir, timeout=timeout)

    def run_snippet(self, code: str, setup: str = "") -> ToolResult:
        """Run a Python code snippet with optional setup lines."""
        full = textwrap.dedent(setup) + "\n" + textwrap.dedent(code) if setup else textwrap.dedent(code)
        return self._terminal.run_python(full)

    def run_file(self, filepath: str, args: str = "") -> ToolResult:
        return self._terminal.run(f"{sys.executable} {shlex.quote(filepath)} {args}")

    def run_pytest(self, test_path: str = ".", extra_flags: str = "-v --tb=short") -> ToolResult:
        return self._terminal.run(f"{sys.executable} -m pytest {shlex.quote(test_path)} {extra_flags}")

    def run_bandit(self, target_path: str = ".") -> ToolResult:
        return self._terminal.run(f"{sys.executable} -m bandit -r {shlex.quote(target_path)} -f txt -ll")


# ---------------------------------------------------------------------------
# AgentComputer — single interface agents use
# ---------------------------------------------------------------------------

class AgentComputer:
    """
    A real computer for one agent.  Provides:
      - self.browser   : BrowserTool
      - self.terminal  : TerminalTool
      - self.search    : SearchTool
      - self.files     : FileTool
      - self.code      : CodeRunTool

    Usage in an agent node:
        computer = AgentComputer(agent_id="code_gen", working_dir="/tmp/timps/code_gen")
        result = computer.search.search("Python async best practices")
        page = await computer.browser.navigate("https://docs.python.org")
        run = computer.terminal.run("python -m pytest tests/")
        computer.files.write("output.py", generated_code)
    """

    def __init__(self, agent_id: str, working_dir: Optional[str] = None, headless: bool = True):
        self.agent_id = agent_id
        self.working_dir = working_dir or os.path.expanduser(f"~/.timps/agents/{agent_id}/workspace")
        os.makedirs(self.working_dir, exist_ok=True)

        self.browser = BrowserTool(headless=headless)
        self.terminal = TerminalTool(working_dir=self.working_dir)
        self.search = SearchTool()
        self.files = FileTool(root_dir=self.working_dir)
        self.code = CodeRunTool(working_dir=self.working_dir)

        self._action_log: List[Dict] = []

    # --- convenience: log every action ---

    def _log(self, tool: str, action: str, result: ToolResult):
        self._action_log.append({
            "ts": time.time(),
            "tool": tool,
            "action": action,
            "success": result.success,
            "output_len": len(result.output),
        })

    def get_action_log(self) -> List[Dict]:
        return list(self._action_log)

    # --- high-level helpers used by agents ---

    async def research(self, topic: str, follow_links: int = 0) -> str:
        """
        Search the web for a topic, optionally follow the top links and extract text.
        Returns a combined research summary string.
        """
        result = self.search.search(topic, max_results=5)
        self._log("search", topic, result)
        if not result.success:
            return f"Search failed: {result.error}"

        summary = f"=== Search Results for: {topic} ===\n{result.output}\n"

        if follow_links > 0:
            try:
                links_data = json.loads(result.output)
                for item in links_data[:follow_links]:
                    url = item.get("url", "")
                    if url:
                        page_result = await self.browser.navigate(url)
                        self._log("browser", f"navigate:{url}", page_result)
                        if page_result.success:
                            summary += f"\n--- {url} ---\n{page_result.output[:1500]}\n"
            except (json.JSONDecodeError, TypeError):
                pass

        return summary

    def run_and_test(self, code: str, test_code: str) -> Dict[str, ToolResult]:
        """Write code + tests to disk, run tests, return results."""
        self.files.write("solution.py", code)
        self.files.write("test_solution.py", test_code)
        test_result = self.code.run_pytest("test_solution.py")
        self._log("code", "run_pytest", test_result)
        return {"tests": test_result}

    def research_sync(self, topic: str, follow_links: int = 0) -> str:
        """
        Sync wrapper for research() — safe to call from non-async agent nodes.
        Runs the async coroutine in a new thread to avoid event-loop conflicts.
        """
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self.research(topic, follow_links=follow_links))
            try:
                return future.result(timeout=60)
            except Exception as exc:
                logger.warning("research_sync failed: %s", exc)
                # Fallback: sync search only (no browser follow-through)
                result = self.search.search(topic)
                return result.output if result.success else f"Search failed: {result.error}"

    async def close(self):
        await self.browser.close()


# ---------------------------------------------------------------------------
# Module-level singleton registry (one computer per agent_id)
# ---------------------------------------------------------------------------

_computers: Dict[str, AgentComputer] = {}


def get_agent_computer(agent_id: str, working_dir: Optional[str] = None) -> AgentComputer:
    """Return (or create) the AgentComputer for the given agent_id."""
    if agent_id not in _computers:
        _computers[agent_id] = AgentComputer(agent_id=agent_id, working_dir=working_dir)
    return _computers[agent_id]


async def close_all_computers():
    for c in _computers.values():
        await c.close()
    _computers.clear()
