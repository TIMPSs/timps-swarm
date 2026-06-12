# Changelog

## [2.2.1] - 2026-06-12

### Added
- `mcp` command auto-clones Python backend to `~/.timps/repo/` on first use (true one-command install)
- `install-mcp` bootstraps the backend during setup

### Fixed
- `.gitignore` added and tracked junk removed (`cli/node_modules/`, `__pycache__/`, `.DS_Store`)
- MIT LICENSE file added to repo root
- `Dockerfile.swarm` now copies all required directories (`mcp_server/`, `give_work.py`, etc.)
- `Makefile` uses `pip install -e ".[dev]"` instead of missing `requirements.txt`
- `redis>=5.0.0` added to `pyproject.toml` dependencies
- CORS origins restricted from wildcard to configurable list via `TIMPS_CORS_ORIGINS` env var
- Health task routing uses prefix matching to avoid false positives with broad keywords
- npm `postinstall` is now opt-in (shows usage hint instead of silently writing 160 files)
- Duplicate paragraphs removed from `AGENTS.md`
- CLI test script runs real tests via `node --test tests/*.test.js`
- AgentRole docstrings updated from "22" to "35" members
- Unused imports removed across 35+ Python files
- Python 3.10 compatibility fixed in f-strings (`local_rag_builder.py`, `timps_cli.py`)
- `AGENTS.md` stale references updated (64→160 tools, `.gitignore` state, uncommitted-changes note)
- `cli/package.json` stale `*-node_modules/` reference removed
