#!/bin/sh
# scripts/pull-models.sh
# Pre-pulls all Ollama models needed by the 10 agents.
# Run inside the Ollama container on first start.

set -e

echo "=== TIMPS Swarm: Pulling Ollama models ==="
echo "This may take 20-60 minutes on first run."
echo ""

MODELS="
qwen2.5:14b
qwen2.5:7b
qwen2.5-coder:7b
qwen2.5:3b
"

for model in $MODELS; do
    echo ">>> Pulling $model ..."
    ollama pull "$model" && echo "  ✅ $model" || echo "  ⚠️  Failed: $model (will use fallback)"
done

echo ""
echo "=== Models ready ==="
