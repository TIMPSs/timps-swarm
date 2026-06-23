import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ContextSharer:
    def get_context(self, working_dir: str = ".") -> dict:
        context = {}
        try:
            git_status = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, cwd=working_dir, timeout=5,
            )
            context["git_status"] = git_status.stdout[:2000]
        except Exception:
            context["git_status"] = ""
        try:
            git_diff = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, cwd=working_dir, timeout=5,
            )
            context["recent_diff"] = git_diff.stdout[:2000]
        except Exception:
            context["recent_diff"] = ""
        try:
            file_tree = subprocess.run(
                ["find", ".", "-maxdepth", "3", "-type", "f",
                 "-not", "-path", "*/node_modules/*",
                 "-not", "-path", "*/.git/*",
                 "-not", "-path", "*/__pycache__/*",
                 "-not", "-path", "*.pyc"],
                capture_output=True, text=True, cwd=working_dir, timeout=5,
            )
            context["file_tree"] = file_tree.stdout[:3000]
        except Exception:
            context["file_tree"] = ""
        context["framework"] = self._detect_framework(working_dir)
        context["test_examples"] = self._find_test_examples(working_dir)
        context["style_config"] = self._read_style_config(working_dir)
        context["open_files"] = self._detect_open_files(working_dir)
        return context

    def _detect_framework(self, working_dir: str) -> str:
        wd = Path(working_dir)
        indicators = []
        if (wd / "pyproject.toml").exists():
            indicators.append("python")
            content = (wd / "pyproject.toml").read_text()
            if "django" in content:
                indicators.append("django")
            if "fastapi" in content or "flask" in content:
                indicators.append("fastapi")
            if "pytest" in content:
                indicators.append("pytest")
        if (wd / "package.json").exists():
            indicators.append("node")
            content = (wd / "package.json").read_text()
            if "react" in content or "next" in content:
                indicators.append("react")
            if "express" in content:
                indicators.append("express")
            if "jest" in content or "vitest" in content:
                indicators.append("jest")
        if (wd / "Cargo.toml").exists():
            indicators.append("rust")
        if (wd / "go.mod").exists():
            indicators.append("go")
        return ", ".join(indicators) or "unknown"

    def _find_test_examples(self, working_dir: str, max_examples: int = 3) -> list[str]:
        wd = Path(working_dir)
        test_files = []
        for pattern in ["tests/test_*.py", "*_test.py", "*.test.ts", "*.spec.ts", "test_*.py"]:
            matches = list(wd.glob(f"**/{pattern}"))
            for m in matches:
                if "node_modules" not in str(m) and ".git" not in str(m):
                    try:
                        content = m.read_text()[:1500]
                        test_files.append(f"# {m}\n{content}")
                        if len(test_files) >= max_examples:
                            break
                    except Exception:
                        pass
            if len(test_files) >= max_examples:
                break
        return test_files

    def _read_style_config(self, working_dir: str) -> str:
        wd = Path(working_dir)
        configs = ["pyproject.toml", ".editorconfig", ".eslintrc.json",
                    ".prettierrc", "rustfmt.toml", "go.mod"]
        for name in configs:
            path = wd / name
            if path.exists():
                try:
                    return f"# {name}\n{path.read_text()[:1000]}"
                except Exception:
                    pass
        return ""

    def _detect_open_files(self, working_dir: str) -> list[str]:
        open_files = []
        for storage_file in [".vscode/storage.json", ".cursor/storage.json"]:
            path = Path(working_dir) / storage_file
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    entries = (
                        data.get("openedPathsList", {}).get("entries", [])
                        or data.get("lastOpenedPaths", [])
                    )
                    for e in entries:
                        if isinstance(e, str) and not e.startswith("vscode-remote"):
                            open_files.append(e)
                except (json.JSONDecodeError, KeyError, AttributeError):
                    pass
        return open_files[:20]

    def inject_context(self, task_args: dict, context: dict | None = None) -> dict:
        if context is None:
            context = self.get_context()
        enriched = dict(task_args)
        enriched["_repo_context"] = context
        return enriched


_sharer: ContextSharer | None = None


def get_context_sharer() -> ContextSharer:
    global _sharer
    if _sharer is None:
        _sharer = ContextSharer()
    return _sharer
