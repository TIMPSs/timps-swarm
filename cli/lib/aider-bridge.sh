#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Aider Bridge — Shell bridge for Aider AI
# ==========================================
# Translates Aider CLI calls into TIMPS Swarm REST API calls via timps_batch.
#
# Aider (https://aider.chat) is an AI pair-programmer in the terminal.
# This bridge lets Aider delegate work to the TIMPS Swarm's specialist agents
# instead of doing everything with its built-in model.
#
# Two use modes:
#   1. MCP mode — Aider calls TIMPS as an MCP server (preferred)
#   2. API mode — This script translates aider-style args into REST API calls
#
# Usage:
#   # Configure Aider to use TIMPS for code review:
#   aider --mcp-servers timps-swarm=http://localhost:8000/mcp
#
#   # Or use this bridge as a subprocess wrapper:
#   export AIDER_BRIDGE=$(which aider-bridge.sh)
#   aider --no-auto-lint --no-auto-test --subprocess "$AIDER_BRIDGE"
#
#   # Direct API calls:
#   aider-bridge.sh review path/to/file.py
#   aider-bridge.sh test src/handler.py
#   aider-bridge.sh batch "add docstrings to all Python files" /path/to/project
#
# Environment:
#   TIMPS_API_URL    — Base URL for the TIMPS API (default: http://localhost:8000)
#   AIDER_MCP_MODE   — Set to "1" to output MCP-compatible JSON (default: 0)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

TIMPS_API="${TIMPS_API_URL:-http://localhost:8000}"
MCP_MODE="${AIDER_MCP_MODE:-0}"

# ── Help ──────────────────────────────────────────────────────────────────────

show_help() {
  cat <<HELP
Aider Bridge — TIMPS Swarm integration for Aider AI

Usage:
  aider-bridge.sh review <file>         — Review a file or diff
  aider-bridge.sh test <file>           — Generate tests for a file
  aider-bridge.sh docstring <file>      — Add docstrings to a file
  aider-bridge.sh refactor <file>       — Refactor a file
  aider-bridge.sh db <description>      — Design a database schema
  aider-bridge.sh api <description>     — Design an API spec
  aider-bridge.sh health                — Run computer health checkup
  aider-bridge.sh batch <instr> <dir>   — Bulk operation via timps_batch
  aider-bridge.sh list                  — List available TIMPS agents
  aider-bridge.sh help                  — Show this help

Environment:
  TIMPS_API_URL   — Base URL (default: http://localhost:8000)
  AIDER_MCP_MODE  — Output MCP JSON when set to 1 (default: 0)

Examples:
  aider-bridge.sh review src/main.py
  aider-bridge.sh batch "add tests for all handlers" /workspace/project
  AIDER_MCP_MODE=1 aider-bridge.sh list
HELP
}

# ── API helpers ───────────────────────────────────────────────────────────────

call_timps() {
  local tool="$1"
  shift
  local payload="$*"

  if [ "$MCP_MODE" = "1" ]; then
    # Output MCP-compatible JSON-RPC for Aider's MCP client
    cat <<JSON
{"jsonrpc":"2.0","id":"aider-bridge","method":"tools/call","params":{"name":"${tool}","arguments":${payload:-{}}}}
JSON
    return
  fi

  # REST API call to the TIMPS FastAPI server
  curl -sf -X POST "${TIMPS_API}/mcp/tools/call" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${tool}\", \"arguments\": ${payload:-{}}}" 2>/dev/null || {
    echo "{\"error\": \"Failed to call ${tool} at ${TIMPS_API}\"}"
    return 1
  }
}

read_file_as_json() {
  local file="$1"
  if [ ! -f "$file" ]; then
    echo "{\"error\": \"File not found: ${file}\"}"
    exit 1
  fi
  # Read file content and escape for JSON
  local content
  content=$(cat "$file" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || echo "\"\"")
  echo "$content"
}

# ── Command dispatch ──────────────────────────────────────────────────────────

cmd_review() {
  local file="$1"
  local content
  content=$(read_file_as_json "$file")
  call_timps "timps_pr_reviewer" "{\"diff\": ${content}}"
}

cmd_test() {
  local file="$1"
  local content
  content=$(read_file_as_json "$file")
  call_timps "timps_unit_test_writer" "{\"source_code\": ${content}, \"language\": \"${LANGUAGE:-python}\"}"
}

cmd_docstring() {
  local file="$1"
  local content
  content=$(read_file_as_json "$file")
  call_timps "timps_docstring_generator" "{\"source_code\": ${content}, \"language\": \"${LANGUAGE:-python}\", \"doc_style\": \"${DOCSTYLE:-google}\"}"
}

cmd_refactor() {
  local file="$1"
  local content
  content=$(read_file_as_json "$file")
  call_timps "timps_refactoring_agent" "{\"code\": ${content}, \"language\": \"${LANGUAGE:-python}\"}"
}

cmd_db() {
  local desc="$1"
  call_timps "timps_db_agent" "{\"description\": \"${desc}\"}"
}

cmd_api() {
  local desc="$1"
  call_timps "timps_api_design_agent" "{\"description\": \"${desc}\"}"
}

cmd_health() {
  call_timps "timps_full_checkup" "{}"
}

cmd_batch() {
  local instruction="$1"
  local working_dir="${2:-.}"
  call_timps "timps_batch" "{\"instruction\": \"${instruction}\", \"agent_type\": \"${AGENT_TYPE:-docstring_generator}\", \"working_dir\": \"${working_dir}\"}"
}

cmd_list() {
  call_timps "timps_list_agents" "{}"
}

# ── Main ──────────────────────────────────────────────────────────────────────

if [ $# -eq 0 ]; then
  show_help
  exit 0
fi

COMMAND="$1"
shift

case "$COMMAND" in
  review)
    cmd_review "$@"
    ;;
  test)
    cmd_test "$@"
    ;;
  docstring)
    cmd_docstring "$@"
    ;;
  refactor)
    cmd_refactor "$@"
    ;;
  db)
    cmd_db "$@"
    ;;
  api)
    cmd_api "$@"
    ;;
  health)
    cmd_health "$@"
    ;;
  batch)
    cmd_batch "$@"
    ;;
  list)
    cmd_list "$@"
    ;;
  help|--help|-h)
    show_help
    ;;
  *)
    echo "Unknown command: $COMMAND"
    echo "Run 'aider-bridge.sh help' for usage."
    exit 1
    ;;
esac
