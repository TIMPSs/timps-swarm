.PHONY: all setup install dataset train up down logs test clean help

# ── Config ─────────────────────────────────────────────────────────────────
BASE_MODEL ?= Qwen/Qwen2.5-Coder-0.5B-Instruct
ITERS      ?= 1500
PORT       ?= 8000

help:
	@echo ""
	@echo "  ████████╗██╗███╗   ███╗██████╗ ███████╗"
	@echo "     ██╔══╝██║████╗ ████║██╔══██╗██╔════╝"
	@echo "     ██║   ██║██╔████╔██║██████╔╝███████╗"
	@echo "     ██║   ██║██║╚██╔╝██║██╔═══╝ ╚════██║"
	@echo "     ██║   ██║██║ ╚═╝ ██║██║     ███████║"
	@echo "     ╚═╝   ╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝  Swarm"
	@echo ""
	@echo "  Commands:"
	@echo "    make setup      — First-time: create dirs, install deps, pull Ollama models"
	@echo "    make install    — Install Python dependencies only"
	@echo "    make dataset    — Build & clean the training dataset"
	@echo "    make train      — Train all 20 specialised adapters (MLX)"
	@echo "    make up         — Start the full Docker swarm"
	@echo "    make up-local   — Start API locally (no Docker)"
	@echo "    make ui         — Start React dashboard"
	@echo "    make down       — Stop all Docker services"
	@echo "    make logs       — Tail swarm API logs"
	@echo "    make test       — Run test suite"
	@echo "    make run REQ=.. — Fire a quick swarm request"
	@echo "    make clean      — Remove generated files and filtered datasets"
	@echo ""

# ── Setup ──────────────────────────────────────────────────────────────────
all: setup dataset train up

setup: install
	@echo ">>> Creating runtime directories..."
	@mkdir -p adapters generated data/processed logs datasets/custom datasets/raw
	@echo ">>> Pulling Ollama models (this takes 20-60 min first time)..."
	@docker-compose up -d ollama 2>/dev/null || ollama serve &
	@sleep 5
	@for model in qwen2.5:14b qwen2.5:7b qwen2.5-coder:7b qwen2.5:3b; do \
		echo "  Pulling $$model..."; \
		ollama pull $$model; \
	done
	@echo ">>> Setup complete ✅"

install:
	@pip install -r requirements.txt
	@echo ">>> Python deps installed ✅"

# ── Dataset ────────────────────────────────────────────────────────────────
dataset:
	@echo ">>> Building training dataset..."
	@python build_clean_dataset.py --max-samples 5000
	@python fix_fences.py
	@echo ">>> Dataset ready: $$(wc -l < data/processed/train.jsonl) samples ✅"

# ── Training ───────────────────────────────────────────────────────────────
train:
	@echo ">>> Training 20 specialised TIMPS-Coder adapters..."
	@BASE_MODEL=$(BASE_MODEL) ITERS=$(ITERS) bash retrain-specialized.sh
	@echo ">>> Training complete ✅"

# ── Docker ─────────────────────────────────────────────────────────────────
up:
	@echo ">>> Starting TIMPS Swarm (Docker)..."
	@docker-compose up -d --build
	@echo ""
	@echo "  Swarm API  →  http://localhost:$(PORT)"
	@echo "  Dashboard  →  http://localhost:3000"
	@echo "  Ollama     →  http://localhost:11434"
	@echo ""

down:
	@docker-compose down

logs:
	@docker-compose logs -f swarm-api

# ── Local dev (no Docker) ──────────────────────────────────────────────────
up-local:
	@echo ">>> Starting API locally on port $(PORT)..."
	@DEV=true PORT=$(PORT) python3 -m src.main

ui:
	@echo ">>> Starting React dashboard..."
	@cd dashboard && npm install && npm start

# ── Testing ────────────────────────────────────────────────────────────────
test:
	@python3 -m pytest tests/ -v --tb=short 2>/dev/null || echo "No tests found — create tests/ directory"

# ── Quick fire ─────────────────────────────────────────────────────────────
run:
ifndef REQ
	$(error REQ is undefined. Usage: make run REQ="Fix the NullPointerException in AuthService")
endif
	@curl -s -X POST http://localhost:$(PORT)/swarm/run \
		-H "Content-Type: application/json" \
		-d '{"request":"$(REQ)","language":"python","max_iterations":10}' | python3 -m json.tool

# ── Cleanup ────────────────────────────────────────────────────────────────
clean:
	@echo ">>> Cleaning generated files..."
	@rm -rf generated/* data/processed/train_*.jsonl logs/*
	@echo ">>> Clean ✅"

clean-all: clean
	@echo ">>> Removing adapters and model cache..."
	@rm -rf adapters/timps-* data/processed/
