#!/usr/bin/env bash
# TIMPS-Swarm Universal Installer
# ──────────────────────────────────────────────────────────────
# Usage: curl -fsSL https://raw.githubusercontent.com/Sandeeprdy1729/timps-swarm/main/install.sh | sh
# Local:  bash install.sh
#
# What it does:
#  1. Detects OS/arch (macOS Intel/Apple Silicon, Linux x86_64/ARM64, WSL)
#  2. Installs Python ≥3.10 via uv (if missing)
#  3. Installs TIMPS-Swarm from source with uv pip
#  4. Checks for Ollama, optionally installs it and pulls required models
#  5. Auto-registers MCP config for every detected IDE
#  6. Runs `timps doctor` to validate everything
#  7. Prints a ready message with quick-start examples

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
info() { echo -e "${CYAN}ℹ   $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠   $*${RESET}"; }
fail() { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}==> $*${RESET}"; }

# ── Detect OS + arch ─────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
IS_WSL=false
if grep -qEi "(microsoft|wsl)" /proc/version 2>/dev/null; then IS_WSL=true; fi

case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *)      fail "Unsupported OS: $OS. TIMPS runs on macOS and Linux." ;;
esac

case "$ARCH" in
  arm64|aarch64) ARCH_LABEL="arm64" ;;
  x86_64)        ARCH_LABEL="x86_64" ;;
  *)             fail "Unsupported architecture: $ARCH" ;;
esac

echo ""
echo -e "${BOLD}"
echo "  ████████╗██╗███╗   ███╗██████╗ ███████╗"
echo "     ██╔══╝██║████╗ ████║██╔══██╗██╔════╝"
echo "     ██║   ██║██╔████╔██║██████╔╝███████╗"
echo "     ██║   ██║██║╚██╔╝██║██╔═══╝ ╚════██║"
echo "     ██║   ██║██║ ╚═╝ ██║██║     ███████║"
echo "     ╚═╝   ╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝"
echo "              Swarm Installer v1.0"
echo -e "${RESET}"
echo -e "  Platform: ${BOLD}$PLATFORM / $ARCH_LABEL${RESET}$([ "$IS_WSL" = "true" ] && echo " (WSL)" || echo "")"
echo ""

INSTALL_DIR="${TIMPS_INSTALL_DIR:-$HOME/.timps}"
BIN_DIR="$INSTALL_DIR/bin"
MEMORY_DIR="$INSTALL_DIR/memory"
AGENTS_DIR="$INSTALL_DIR/agents"
REPO_DIR="${TIMPS_REPO:-$INSTALL_DIR/repo}"

mkdir -p "$BIN_DIR" "$MEMORY_DIR" "$AGENTS_DIR" "$INSTALL_DIR/logs"

# ── Step 1: Python ≥3.10 via uv ──────────────────────────────────────────────
step "Checking Python environment"

install_uv() {
  info "Installing uv (fast Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Add uv to PATH for this session
  export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
}

if ! command -v uv &>/dev/null; then
  install_uv
else
  ok "uv already installed: $(uv --version)"
fi

# Make sure we have Python 3.10+
PYTHON_OK=false
for pyver in python3.12 python3.11 python3.10 python3; do
  if command -v "$pyver" &>/dev/null; then
    PYVER_NUM=$("$pyver" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || echo "(0, 0)")
    if "$pyver" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
      PYTHON_BIN="$pyver"
      PYTHON_OK=true
      ok "Found $pyver: $($pyver --version)"
      break
    fi
  fi
done

if [ "$PYTHON_OK" = "false" ]; then
  info "Installing Python 3.11 via uv…"
  uv python install 3.11
  PYTHON_BIN="python3.11"
  ok "Python 3.11 installed"
fi

# ── Step 2: Clone / update repo ──────────────────────────────────────────────
step "Setting up TIMPS-Swarm source"

CLONE_URL="https://github.com/Sandeeprdy1729/timps-swarm.git"

if [ -d "$REPO_DIR/.git" ]; then
  info "Updating existing repo at $REPO_DIR…"
  git -C "$REPO_DIR" pull --quiet --ff-only || warn "Could not pull latest — using existing version"
elif [ -f "$(pwd)/mcp_server/server.py" ] && [ -f "$(pwd)/src/agents.py" ]; then
  # Running inside the repo already
  REPO_DIR="$(pwd)"
  info "Using current directory as repo: $REPO_DIR"
else
  info "Cloning TIMPS-Swarm into $REPO_DIR…"
  git clone --depth 1 "$CLONE_URL" "$REPO_DIR"
  ok "Cloned"
fi

# ── Step 3: Install Python dependencies ──────────────────────────────────────
step "Installing Python dependencies"

cd "$REPO_DIR"

# Use uv for fast dependency resolution
if command -v uv &>/dev/null; then
  uv pip install --system -e . --quiet && ok "Dependencies installed via uv" || \
    { warn "uv install failed, falling back to pip"; $PYTHON_BIN -m pip install -e . -q; }
else
  $PYTHON_BIN -m pip install -e . -q
  ok "Dependencies installed via pip"
fi

# Install playwright browsers (needed for BrowserTool)
info "Installing Playwright browser…"
$PYTHON_BIN -m playwright install chromium --quiet 2>/dev/null || \
  warn "Playwright chromium not installed (browser tools will be limited)"

# ── Step 4: Ollama + models ───────────────────────────────────────────────────
step "Checking Ollama"

install_ollama() {
  if [ "$PLATFORM" = "macos" ]; then
    if command -v brew &>/dev/null; then
      info "Installing Ollama via Homebrew…"
      brew install --cask ollama --quiet
    else
      info "Downloading Ollama for macOS…"
      curl -fsSL "https://ollama.ai/download/Ollama-darwin.zip" -o /tmp/ollama.zip
      unzip -q /tmp/ollama.zip -d /tmp/ollama-pkg
      mv /tmp/ollama-pkg/Ollama.app /Applications/ 2>/dev/null || true
    fi
  else
    info "Installing Ollama via official script…"
    curl -fsSL https://ollama.ai/install.sh | sh
  fi
}

if command -v ollama &>/dev/null; then
  ok "Ollama found: $(ollama --version 2>/dev/null || echo 'installed')"
else
  echo ""
  echo -e "${YELLOW}Ollama is not installed. TIMPS-Swarm uses Ollama to run local LLMs.${RESET}"
  read -rp "Install Ollama automatically? [Y/n] " INSTALL_OLLAMA
  INSTALL_OLLAMA="${INSTALL_OLLAMA:-Y}"
  if [[ "$INSTALL_OLLAMA" =~ ^[Yy]$ ]]; then
    install_ollama && ok "Ollama installed"
  else
    warn "Skipping Ollama. Agents will run in data-only mode (no LLM analysis)."
  fi
fi

# Pull models in background if Ollama is available
if command -v ollama &>/dev/null; then
  # Start Ollama if not running
  if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
    info "Starting Ollama in background…"
    ollama serve &>/dev/null &
    sleep 2
  fi

  MODELS_NEEDED=("qwen2.5:14b" "qwen2.5:7b" "qwen2.5-coder:7b" "qwen2.5:3b")
  MODELS_PRESENT=$(ollama list 2>/dev/null | awk 'NR>1{print $1}' || echo "")

  MISSING_MODELS=()
  for m in "${MODELS_NEEDED[@]}"; do
    if ! echo "$MODELS_PRESENT" | grep -q "^${m}"; then
      MISSING_MODELS+=("$m")
    fi
  done

  if [ ${#MISSING_MODELS[@]} -eq 0 ]; then
    ok "All required Ollama models present"
  else
    echo ""
    echo -e "${YELLOW}Missing Ollama models: ${MISSING_MODELS[*]}${RESET}"
    echo -e "  Required: ~15GB disk space total"

    # ── Disk space pre-flight check ──────────────────────────────────────────
    AVAILABLE_GB=0
    if command -v df &>/dev/null; then
      if [ "$PLATFORM" = "macos" ]; then
        AVAILABLE_GB=$(df -g "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
      else
        AVAILABLE_GB=$(df -BG "$HOME" 2>/dev/null | awk 'NR==2 {gsub(/G/,"",$4); print $4}' || echo 0)
      fi
    fi
    REQUIRED_GB=16
    if [ "${AVAILABLE_GB:-0}" -lt "$REQUIRED_GB" ] 2>/dev/null; then
      warn "Only ${AVAILABLE_GB}GB free on disk — models need ~${REQUIRED_GB}GB."
      warn "Free up space first, then re-run: bash install.sh"
      warn "Skipping model pull."
    else
      ok "Disk space OK: ${AVAILABLE_GB}GB free (need ${REQUIRED_GB}GB)"
      read -rp "Pull models in background now? [Y/n] " PULL_MODELS
      PULL_MODELS="${PULL_MODELS:-Y}"
      if [[ "$PULL_MODELS" =~ ^[Yy]$ ]]; then
        PULL_LOG="$INSTALL_DIR/logs/model_pull.log"
        for m in "${MISSING_MODELS[@]}"; do
          info "Pulling $m in background → $PULL_LOG"
          ollama pull "$m" >>"$PULL_LOG" 2>&1 &
        done
        ok "Model pulls started in background. Check $PULL_LOG for progress."
      else
        warn "Skipping model pull. Run: ollama pull qwen2.5:7b (minimum)"
      fi
    fi
  fi
fi

# ── Step 5: Create CLI shims ──────────────────────────────────────────────────
step "Creating CLI commands"

# timps-mcp shim
cat >"$BIN_DIR/timps-mcp" <<SHIM
#!/usr/bin/env bash
exec $PYTHON_BIN -m mcp_server.server "\$@"
SHIM
chmod +x "$BIN_DIR/timps-mcp"

# timps-swarm shim
cat >"$BIN_DIR/timps-swarm" <<SHIM
#!/usr/bin/env bash
exec $PYTHON_BIN "$REPO_DIR/give_work.py" "\$@"
SHIM
chmod +x "$BIN_DIR/timps-swarm"

# timps doctor shim
cat >"$BIN_DIR/timps" <<SHIM
#!/usr/bin/env bash
case "\$1" in
  doctor)  exec $PYTHON_BIN "$REPO_DIR/timps_doctor.py" ;;
  mcp)     exec $PYTHON_BIN -m mcp_server.server ;;
  work)    shift; exec $PYTHON_BIN "$REPO_DIR/give_work.py" "\$@" ;;
  daemon)  exec $PYTHON_BIN "$REPO_DIR/timps_daemon.py" ;;
  memory)  exec $PYTHON_BIN "$REPO_DIR/timps_doctor.py" --memory ;;  keygen)  shift; exec $PYTHON_BIN "$REPO_DIR/give_work.py" --keygen "\$@" ;;
  keys)    exec $PYTHON_BIN "$REPO_DIR/give_work.py" --keys ;;
  revoke)  shift; exec $PYTHON_BIN "$REPO_DIR/give_work.py" --revoke "\$@" ;;  *)       exec $PYTHON_BIN "$REPO_DIR/give_work.py" "\$@" ;;
esac
SHIM
chmod +x "$BIN_DIR/timps"

ok "CLI shims created in $BIN_DIR"

# Add to PATH in shell config
add_to_path() {
  local shell_cfg="$1"
  local path_line="export PATH=\"\$PATH:$BIN_DIR\""
  if [ -f "$shell_cfg" ] && ! grep -qF "$BIN_DIR" "$shell_cfg"; then
    echo "" >> "$shell_cfg"
    echo "# TIMPS-Swarm" >> "$shell_cfg"
    echo "$path_line" >> "$shell_cfg"
    ok "Added $BIN_DIR to PATH in $shell_cfg"
  fi
}

[ -f "$HOME/.zshrc" ]     && add_to_path "$HOME/.zshrc"
[ -f "$HOME/.bashrc" ]    && add_to_path "$HOME/.bashrc"
[ -f "$HOME/.bash_profile" ] && add_to_path "$HOME/.bash_profile"
export PATH="$PATH:$BIN_DIR"

# ── Step 6: Auto-register MCP config for detected IDEs ───────────────────────
step "Registering MCP server with installed IDEs"

MCP_SERVER_CMD="$BIN_DIR/timps-mcp"
MCP_ENTRY_CLAUDE=$(cat <<JSON
{
  "mcpServers": {
    "timps-swarm": {
      "command": "$MCP_SERVER_CMD",
      "env": { "OLLAMA_HOST": "http://localhost:11434" }
    }
  }
}
JSON
)

inject_mcp_config() {
  local config_file="$1"
  local style="$2"   # "claude" | "cursor" | "vscode"
  local dir
  dir="$(dirname "$config_file")"
  mkdir -p "$dir"

  if [ -f "$config_file" ]; then
    # File exists — check if timps-swarm already registered
    if grep -q "timps-swarm" "$config_file" 2>/dev/null; then
      ok "MCP already registered in $config_file"
      return
    fi
    # Back up and merge (simple approach: if it has mcpServers, add our entry)
    cp "$config_file" "${config_file}.bak"
    info "Backed up existing config to ${config_file}.bak"
    # Use Python to merge JSON properly
    $PYTHON_BIN - <<PYEOF
import json, sys
path = "$config_file"
try:
    data = json.loads(open(path).read())
except Exception:
    data = {}

entry = {"command": "$MCP_SERVER_CMD", "env": {"OLLAMA_HOST": "http://localhost:11434"}}
if "$style" == "vscode":
    data.setdefault("mcp", {}).setdefault("servers", {})["timps-swarm"] = {
        "type": "stdio", "command": "$MCP_SERVER_CMD",
        "env": {"OLLAMA_HOST": "http://localhost:11434"}
    }
else:
    data.setdefault("mcpServers", {})["timps-swarm"] = entry

open(path, "w").write(json.dumps(data, indent=2))
print("Merged")
PYEOF
    ok "MCP registered in $config_file"
  else
    # New file
    case "$style" in
      vscode)
        cat >"$config_file" <<JSON
{
  "mcp": {
    "servers": {
      "timps-swarm": {
        "type": "stdio",
        "command": "$MCP_SERVER_CMD",
        "env": { "OLLAMA_HOST": "http://localhost:11434" }
      }
    }
  }
}
JSON
        ;;
      *)
        echo "$MCP_ENTRY_CLAUDE" > "$config_file"
        ;;
    esac
    ok "Created MCP config: $config_file"
  fi
}

# Claude Desktop / Claude Code
[ -d "$HOME/.claude" ] || [ -f "$HOME/.claude/mcp.json" ] && \
  inject_mcp_config "$HOME/.claude/mcp.json" "claude" || \
  inject_mcp_config "$HOME/.claude/mcp.json" "claude"

# Cursor
[ -d "$HOME/.cursor" ] && inject_mcp_config "$HOME/.cursor/mcp.json" "cursor" || true

# VS Code / GitHub Copilot (global user settings)
VSCODE_CONFIG="$HOME/Library/Application Support/Code/User/mcp.json"
[ "$PLATFORM" = "linux" ] && VSCODE_CONFIG="$HOME/.config/Code/User/mcp.json"
inject_mcp_config "$VSCODE_CONFIG" "vscode"

# Windsurf
[ -d "$HOME/.config/windsurf" ] && inject_mcp_config "$HOME/.config/windsurf/mcp.json" "cursor" || true

# Continue.dev
if [ -d "$HOME/.continue" ]; then
  CONTINUE_CFG="$HOME/.continue/config.json"
  if [ -f "$CONTINUE_CFG" ] && ! grep -q "timps-swarm" "$CONTINUE_CFG"; then
    cp "$CONTINUE_CFG" "${CONTINUE_CFG}.bak"
    $PYTHON_BIN - <<PYEOF
import json
path = "$CONTINUE_CFG"
try:
    data = json.loads(open(path).read())
except Exception:
    data = {}
data.setdefault("mcpServers", [])
if not any(s.get("name") == "timps-swarm" for s in data["mcpServers"]):
    data["mcpServers"].append({
        "name": "timps-swarm",
        "command": "$MCP_SERVER_CMD",
        "env": {"OLLAMA_HOST": "http://localhost:11434"}
    })
open(path, "w").write(json.dumps(data, indent=2))
PYEOF
    ok "MCP registered in Continue.dev config"
  fi
fi

# Repo-local VS Code config
if [ -f "$REPO_DIR/.vscode/mcp.json" ]; then
  ok "Repo-local .vscode/mcp.json already present"
else
  mkdir -p "$REPO_DIR/.vscode"
  inject_mcp_config "$REPO_DIR/.vscode/mcp.json" "vscode"
fi

# ── Step 7: Universal Coding Agent Integration (Phase 3) ─────────────────━━━━
step "Integrating with coding agents"

NODE_BIN=""
for candidate in node nodejs; do
  if command -v "$candidate" &>/dev/null; then
    NODE_BIN="$candidate"
    break
  fi
done

if [ -n "$NODE_BIN" ]; then
  if [ -f "$REPO_DIR/cli/lib/claude-code-integration.js" ]; then
    info "Writing Claude Code agent definitions…"
    "$NODE_BIN" "$REPO_DIR/cli/lib/claude-code-integration.js" --agents-only && \
      ok "Claude Code agents written" || \
      warn "Claude Code agent integration failed (non-fatal)"
  fi

  if [ -f "$REPO_DIR/cli/lib/cursor-integration.js" ]; then
    info "Generating Cursor rules…"
    "$NODE_BIN" "$REPO_DIR/cli/lib/cursor-integration.js" && \
      ok "Cursor rules generated" || \
      warn "Cursor integration failed (non-fatal)"
  fi

  if [ -f "$REPO_DIR/cli/lib/codex-adapter.js" ]; then
    info "Writing Codex CLI config…"
    "$NODE_BIN" "$REPO_DIR/cli/lib/codex-adapter.js" && \
      ok "Codex config written" || \
      warn "Codex integration failed (non-fatal)"
  fi
else
  warn "Node.js not found — skipping Claude Code, Cursor, and Codex integrations"
  warn "Install Node.js and re-run: bash install.sh"
fi

if [ -f "$REPO_DIR/cli/lib/aider-bridge.sh" ]; then
  chmod +x "$REPO_DIR/cli/lib/aider-bridge.sh"
  AIDER_BRIDGE_LINK="$BIN_DIR/aider-bridge"
  if [ ! -f "$AIDER_BRIDGE_LINK" ]; then
    ln -sf "$REPO_DIR/cli/lib/aider-bridge.sh" "$AIDER_BRIDGE_LINK" && \
      ok "Aider bridge linked: $AIDER_BRIDGE_LINK"
  fi
fi

# Python-side universal config generator
info "Generating tool connector configs…"
$PYTHON_BIN -c "
from src.tool_connectors import generate_all_configs, connect_all
results = generate_all_configs()
connected = sum(1 for files in results.values() if files)
print(f'Configs generated for {len(results)} tools')
" 2>/dev/null && ok "Tool connector configs generated" || \
  warn "Tool connector generation skipped (non-fatal)"

# ── Step 8: Run timps doctor ──────────────────────────────────────────────────
step "Running TIMPS Doctor (validation)"

cd "$REPO_DIR"
$PYTHON_BIN timps_doctor.py --quick 2>/dev/null && ok "All checks passed" || \
  warn "Some checks failed — run: timps doctor  for details"

# ── Step 9: Start TIMPS daemon ────────────────────────────────────────────────
step "Starting TIMPS background daemon"

DAEMON_LOG="$INSTALL_DIR/logs/daemon.log"
# Check if already running
if pgrep -f "timps_daemon.py" >/dev/null 2>&1; then
  ok "TIMPS daemon already running"
else
  $PYTHON_BIN "$REPO_DIR/timps_daemon.py" --daemon >>"$DAEMON_LOG" 2>&1 &
  DAEMON_PID=$!
  sleep 1
  if kill -0 "$DAEMON_PID" 2>/dev/null; then
    ok "TIMPS daemon started (PID $DAEMON_PID) — logs: $DAEMON_LOG"
  else
    warn "Daemon did not stay running — start manually: timps daemon"
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}  TIMPS-Swarm is ready! 🚀${RESET}"
echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${CYAN}Restart your terminal, then try:${RESET}"
echo ""
echo -e "  ${BOLD}# Ask a health question${RESET}"
echo -e "  timps work \"why is my laptop slow\""
echo ""
echo -e "  ${BOLD}# Full system checkup${RESET}"
echo -e "  timps work --health"
echo ""
echo -e "  ${BOLD}# Run a coding task${RESET}"
echo -e "  timps work \"write a REST API for user auth in Python\""
echo ""
echo -e "  ${BOLD}# Validate everything${RESET}"
echo -e "  timps doctor"
echo ""
echo -e "  ${BOLD}# Use in Claude Code / Cursor / Copilot${RESET}"
echo -e "  → Just ask: \"timps_dispatch: why is my wifi dropping?\""
echo ""
echo -e "  ${CYAN}MCP configs written to:${RESET}"
echo -e "  - Claude Desktop: ~/.claude/mcp.json"
echo -e "  - Cursor:         ~/.cursor/mcp.json"
echo -e "  - VS Code:        ~/Library/Application Support/Code/User/mcp.json"
echo ""
if [ ${#MISSING_MODELS[@]} -gt 0 ] 2>/dev/null; then
  echo -e "  ${YELLOW}Note: Model pulls are running in background.${RESET}"
  echo -e "  Check progress: tail -f $INSTALL_DIR/logs/model_pull.log"
  echo ""
fi
