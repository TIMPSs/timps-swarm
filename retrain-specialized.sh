#!/bin/bash
# retrain-specialized.sh
# Trains 20 specialized TIMPS-Coder LoRA adapters
# Requires: pip install mlx-lm datasets huggingface-hub
# Usage: bash retrain-specialized.sh [--iters 1500] [--base-model Qwen/Qwen2.5-Coder-0.5B-Instruct]

set -e

BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-Coder-0.5B-Instruct}"
ITERS="${ITERS:-1500}"
DATA_DIR="data/processed"
ADAPTER_DIR="adapters"
BATCH_SIZE="${BATCH_SIZE:-2}"
LORA_RANK="${LORA_RANK:-16}"

mkdir -p "$ADAPTER_DIR"

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --iters)    ITERS="$2";      shift 2 ;;
        --base-model) BASE_MODEL="$2"; shift 2 ;;
        --batch-size) BATCH_SIZE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          TIMPS-Coder Specialized Adapter Training        ║"
echo "║  Base model : $BASE_MODEL"
echo "║  Iterations : $ITERS"
echo "║  Adapters   : 20"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Build base dataset if not exists ───────────────────────────────────────
if [ ! -f "$DATA_DIR/train.jsonl" ]; then
    echo ">>> Building base dataset..."
    python3 build_clean_dataset.py
    python3 fix_fences.py
fi

BASE_COUNT=$(wc -l < "$DATA_DIR/train.jsonl")
echo ">>> Base dataset: $BASE_COUNT samples"

# ── 20 Specialisations ─────────────────────────────────────────────────────
declare -a SPECIALIZATIONS=(
    "java_npe:NullPointerException:Java NullPointerException and null dereference specialist"
    "java_ioob:IndexOutOfBoundsException:Java array index out of bounds specialist"
    "java_concurrent:ConcurrentModification:Java concurrency and threading specialist"
    "python_keyerror:KeyError:Python dictionary KeyError and missing key specialist"
    "python_typeerror:TypeError:Python type mismatch and AttributeError specialist"
    "python_recursion:RecursionError:Python recursion depth and stack overflow specialist"
    "python_async:asyncio:Python asyncio event loop and coroutine specialist"
    "python_logic:LogicError:Python algorithmic logic and incorrect output specialist"
    "javascript_null:undefined:JavaScript null undefined and TypeError specialist"
    "javascript_scope:ScopeError:JavaScript closure variable scope and hoisting specialist"
    "javascript_async:Promise:JavaScript async await Promise rejection specialist"
    "cpp_memory:Segmentation:Cpp memory management pointer and heap corruption specialist"
    "cpp_bounds:OutOfBounds:Cpp buffer overflow array bounds and stack smashing specialist"
    "go_routine:goroutine:Go concurrency goroutine channel deadlock specialist"
    "rust_borrow:borrow:Rust ownership borrow checker lifetime specialist"
    "sql_injection:SQL injection:SQL injection parameterised query security specialist"
    "xss_vuln:XSS:Cross-site scripting HTML sanitisation security specialist"
    "auth_bypass:authentication:Authentication session JWT token security specialist"
    "performance_slow:performance:Algorithm complexity N+1 query caching optimisation specialist"
    "api_design:API design:REST API endpoint contract versioning design specialist"
)

TRAINED=0
FAILED=0

for spec in "${SPECIALIZATIONS[@]}"; do
    IFS=':' read -r NAME FILTER SYSTEM_SUFFIX <<< "$spec"

    ADAPTER_PATH="$ADAPTER_DIR/timps-$NAME"
    DATA_FILE="$DATA_DIR/train_${NAME}.jsonl"
    mkdir -p "$ADAPTER_PATH"

    echo ""
    echo "┌─────────────────────────────────────────────────────────"
    echo "│  Adapter: $NAME  (filter: $FILTER)"
    echo "└─────────────────────────────────────────────────────────"

    # ── Filter dataset ────────────────────────────────────────────
    python3 << PYEOF
import json
import random

name = "${NAME}"
keyword = "${FILTER}".lower()
system = "You are TIMPS-Coder specialising in ${SYSTEM_SUFFIX}. Explain the root cause in plain English, then show the complete corrected code."

count = 0
samples = []

with open("${DATA_DIR}/train.jsonl") as fin:
    for line in fin:
        data = json.loads(line)
        text = json.dumps(data).lower()
        if keyword in text:
            if 'messages' in data and len(data['messages']) > 0:
                data['messages'][0]['content'] = system
            samples.append(data)
            count += 1

# Augment if fewer than 500 specialised samples
if count < 500:
    with open("${DATA_DIR}/train.jsonl") as fin2:
        general = [json.loads(l) for l in fin2 if l.strip()]
        random.shuffle(general)
        needed = 1000 - count
        for item in general[:needed]:
            if 'messages' in item and len(item['messages']) > 0:
                item['messages'][0]['content'] = system
            samples.append(item)

random.shuffle(samples)

with open("${DATA_FILE}", 'w') as fout:
    for s in samples:
        fout.write(json.dumps(s) + '\n')

print(f"  [{name}] Dataset: {len(samples)} samples ({count} specialised)")
PYEOF

    # ── Train LoRA adapter ─────────────────────────────────────────
    if python3 -m mlx_lm.lora \
        --model "$BASE_MODEL" \
        --train \
        --data "$DATA_FILE" \
        --adapter-path "$ADAPTER_PATH" \
        --iters "$ITERS" \
        --batch-size "$BATCH_SIZE" \
        --grad-accum 4 \
        --learning-rate 5e-6 \
        --lora-rank "$LORA_RANK" \
        --lora-alpha 32 \
        --lora-dropout 0.05 \
        --max-seq-length 1024 \
        --save-every 500 \
        --steps-per-report 100; then

        # ── Merge weights ──────────────────────────────────────────
        python3 -m mlx_lm.fuse \
            --model "$BASE_MODEL" \
            --adapter-path "$ADAPTER_PATH" \
            --save-path "${ADAPTER_PATH}-merged" \
            --de-quantize 2>/dev/null || true

        echo "  ✅ $NAME trained → $ADAPTER_PATH"
        TRAINED=$((TRAINED + 1))
    else
        echo "  ❌ $NAME FAILED"
        FAILED=$((FAILED + 1))
    fi

done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Training Complete"
printf  "║  ✅ Trained : %-3d   ❌ Failed: %-3d\n" $TRAINED $FAILED
echo "║  Location  : ./adapters/"
echo "╚══════════════════════════════════════════════════════════╝"
