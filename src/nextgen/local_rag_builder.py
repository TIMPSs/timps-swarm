"""Local RAG Builder — builds a fully-local Retrieval-Augmented Generation
pipeline (Ollama embeddings + LlamaIndex / LangChain retriever + reranker +
CLI chat) from a description of the corpus and intended question types.

The agent is LLM-driven: the LLM designs the chunking strategy, the embedding
model, the retriever, the reranker, the prompt template, and the eval set.
Everything is generated as importable code under `generated/rag/<name>/` —
no real network calls, no downloads.  A Dockerfile and a Makefile are also
emitted so the user can spin it up on CPU/GPU.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "nextgen"


def local_rag_builder(args: Dict[str, Any]) -> Dict[str, Any]:
    description = (args.get("description") or args.get("corpus") or "").strip()
    project_name = (args.get("name") or "local_rag").strip().lower()
    project_name = re.sub(r"[^a-z0-9_]+", "_", project_name).strip("_") or "local_rag"
    corpus_path = args.get("corpus_path") or "."
    llm_backend = (args.get("llm_backend") or "ollama").lower()
    embed_model = args.get("embed_model") or "nomic-embed-text"
    llm_model = args.get("llm_model") or "llama3.1:8b"
    target_dir = Path(args.get("target_dir") or f"generated/rag/{project_name}")

    if not description:
        return {
            "summary": "No corpus description provided — describe the documents, question types, and domain.",
            "error": "description is required",
        }

    # --------------------------------------------------------------- gather
    extra: List[str] = []
    p = Path(corpus_path)
    if p.is_dir():
        sample = [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in
                  {".md", ".txt", ".rst", ".adoc", ".json", ".yaml", ".yml", ".py"}][:5]
        for s in sample:
            try:
                extra.append(
                    f"--- SAMPLE {s.name} ---\n"
                    + s.read_text(encoding="utf-8", errors="ignore")[:4_000]
                )
            except Exception:
                pass
    elif p.is_file():
        try:
            extra.append("--- CORPUS FILE ---\n" + p.read_text(encoding="utf-8", errors="ignore")[:6_000])
        except Exception:
            pass

    # --------------------------------------------------------------- prompt
    system = (
        "You are a senior applied-ML engineer designing a fully-local RAG "
        "pipeline.  You return ONLY a single JSON object — no prose, no "
        "markdown fences.\n\n"
        "Schema:\n"
        "{\n"
        '  "chunking":       { "strategy": "fixed"|"semantic"|"markdown"|"code", '
        '"chunk_size": int, "chunk_overlap": int },\n'
        '  "embedding":      { "provider": "ollama"|"sentence_transformers", '
        '"model": str, "dim": int },\n'
        '  "vector_store":   { "kind": "chroma"|"faiss"|"lancedb"|"pgvector", '
        '"path": str },\n'
        '  "retriever":      { "kind": "vector"|"hybrid"|"bm25", "top_k": int },\n'
        '  "reranker":       { "enabled": bool, "model": str|null, "top_n": int },\n'
        '  "prompt":         { "system": str, "template": str },\n'
        '  "llm":            { "provider": "ollama"|"llamacpp"|"vllm", "model": str, '
        '"temperature": float, "max_tokens": int },\n'
        '  "eval_set":       [ { "question": str, "expected_keywords": [str] } ],\n'
        '  "safety":         [str],   // PII redaction, prompt-injection guards, etc.\n'
        '  "performance":    { "expected_p50_ms": int, "expected_p95_ms": int }\n'
        "}\n\n"
        "Rules:\n"
        "- All models must be open-weights and run locally — no cloud APIs.\n"
        "- `prompt.template` MUST contain the literal placeholders {context} and "
        "{question}.\n"
        "- Provide at least 5 diverse eval-set questions relevant to the corpus."
    )

    user = (
        f"Project: {project_name}\nLLM backend: {llm_backend} ({llm_model})\n"
        f"Embedder: {embed_model}\nCorpus path: {corpus_path}\n\n"
        f"Description:\n{description}\n\n"
        + ("\n".join(extra))
    )

    raw = _llm(user, system, "local_rag_builder")
    parsed = _parse_json(
        raw,
        fallback={
            "chunking": {"strategy": "fixed", "chunk_size": 800, "chunk_overlap": 100},
            "embedding": {"provider": "ollama", "model": embed_model, "dim": 768},
            "vector_store": {"kind": "chroma", "path": "./.chroma"},
            "retriever": {"kind": "vector", "top_k": 5},
            "reranker": {"enabled": False, "model": None, "top_n": 3},
            "prompt": {
                "system": "You are a careful assistant. Answer using only the provided context.",
                "template": "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:",
            },
            "llm": {"provider": "ollama", "model": llm_model, "temperature": 0.2, "max_tokens": 512},
            "eval_set": [],
            "safety": [],
            "performance": {"expected_p50_ms": 1500, "expected_p95_ms": 5000},
        },
    )

    chunking = parsed.get("chunking") or {}
    embedding = parsed.get("embedding") or {}
    vector_store = parsed.get("vector_store") or {}
    retriever = parsed.get("retriever") or {}
    reranker = parsed.get("reranker") or {}
    prompt = parsed.get("prompt") or {}
    llm = parsed.get("llm") or {}
    eval_set = parsed.get("eval_set") or []
    safety = parsed.get("safety") or []
    perf = parsed.get("performance") or {}

    # --------------------------------------------------------------- emit
    target_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[str] = []

    files = {
        "config.json":      json.dumps(parsed, indent=2),
        "ingest.py":        _render_ingest(project_name, chunking, embedding, vector_store),
        "retrieve.py":      _render_retrieve(project_name, retriever, reranker),
        "generate.py":      _render_generate(project_name, prompt, llm),
        "chat.py":          _render_chat(project_name),
        "evaluate.py":      _render_evaluate(project_name, eval_set, prompt, llm),
        "requirements.txt": _render_requirements(embedding, llm, vector_store, reranker),
        "Dockerfile":       _render_dockerfile(llm_model, embed_model),
        "Makefile":         _render_makefile(project_name),
        "README.md":        _render_readme(project_name, parsed, perf),
    }
    for name, content in files.items():
        p = target_dir / name
        p.write_text(content, encoding="utf-8")
        out_paths.append(str(p))

    smoke = _run(
        f"cd {target_dir} && python -c \"import ast; "
        f"[ast.parse(open(f).read()) for f in ['ingest.py','retrieve.py','generate.py','chat.py','evaluate.py']]; "
        f"print('ok')\"",
        timeout=20,
    )

    summary = (
        f"Built local RAG '{project_name}': {retriever.get('kind','vector')} retriever, "
        f"{vector_store.get('kind','chroma')} store, reranker={reranker.get('enabled', False)}, "
        f"eval_set={len(eval_set)} questions, expected p50={perf.get('expected_p50_ms','?')}ms."
    )

    payload = {
        "summary": summary,
        "project_name": project_name,
        "llm_backend": llm_backend,
        "config": parsed,
        "files": out_paths,
        "smoke_check": smoke[:600],
        "generated_at": _ts(),
    }
    _save("rag", f"{project_name}_summary.json", json.dumps(payload, indent=2))
    _record("local_rag_builder", project_name, f"chunks={chunking.get('chunk_size')} retriever={retriever.get('kind')} eval={len(eval_set)}")
    return payload


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_ingest(name, chunking, embedding, vector_store) -> str:
    return (
        f'"""{name} ingestion — walks a corpus and indexes chunks into the vector store."""\n'
        f"from __future__ import annotations\n"
        f"import hashlib, os, sys\n"
        f"from pathlib import Path\n\n"
        f"CHUNK_SIZE    = {chunking.get('chunk_size', 800)}\n"
        f"CHUNK_OVERLAP = {chunking.get('chunk_overlap', 100)}\n"
        f"STRATEGY      = {json.dumps(chunking.get('strategy', 'fixed'))}\n"
        f"EMBED_MODEL   = {json.dumps(embedding.get('model', 'nomic-embed-text'))}\n"
        f"STORE_KIND    = {json.dumps(vector_store.get('kind', 'chroma'))}\n"
        f"STORE_PATH    = {json.dumps(vector_store.get('path', './.chroma'))}\n\n"
        f"def chunk(text: str) -> list[str]:\n"
        f"    if STRATEGY == 'fixed':\n"
        f"        return [text[i:i + CHUNK_SIZE] for i in range(0, max(1, len(text)), CHUNK_SIZE - CHUNK_OVERLAP)]\n"
        f"    return text.split('\\n\\n')\n\n"
        f"def embed(texts: list[str]) -> list[list[float]]:\n"
        f"    # Replace with ollama/sentence-transformers call in production.\n"
        f"    return [[0.0] * {embedding.get('dim', 768)} for _ in texts]\n\n"
        f"def ingest(root: str = '.') -> int:\n"
        f"    n = 0\n"
        f"    for path in Path(root).rglob('*'):\n"
        f"        if not path.is_file() or path.suffix.lower() not in {{'.md','.txt','.rst','.py'}}:\n"
        f"            continue\n"
        f"        for c in chunk(path.read_text(encoding='utf-8', errors='ignore')):\n"
        f"            embed([c])  # real call would persist\n"
        f"            n += 1\n"
        f"    return n\n\n"
        f"if __name__ == '__main__':\n"
        f"    print('indexed', ingest(sys.argv[1] if len(sys.argv) > 1 else '.'), 'chunks')\n"
    )


def _render_retrieve(name, retriever, reranker) -> str:
    return (
        f'"""{name} retriever."""\n'
        f"from __future__ import annotations\n"
        f"TOP_K   = {retriever.get('top_k', 5)}\n"
        f"KIND    = {json.dumps(retriever.get('kind', 'vector'))}\n"
        f"RERANK  = {bool(reranker.get('enabled'))}\n"
        f"RERANK_N = {reranker.get('top_n', 3) if reranker.get('enabled') else 0}\n\n"
        f"def retrieve(query: str) -> list[str]:\n"
        f"    # Replace with real vector-store query.\n"
        f"    hits = [f'passage for {{query}}'] * TOP_K\n"
        f"    return hits[:RERANK_N] if RERANK else hits\n"
    )


def _render_generate(name, prompt, llm) -> str:
    return (
        f'"""{name} generator — formats the prompt and calls the local LLM."""\n'
        f"from __future__ import annotations\n"
        f"SYSTEM = {json.dumps(prompt.get('system',''))}\n"
        f"TEMPLATE = {json.dumps(prompt.get('template', 'Context:\\n{context}\\n\\nQ: {question}\\nA:'))}\n"
        f"LLM_MODEL = {json.dumps(llm.get('model', 'llama3.1:8b'))}\n"
        f"TEMPERATURE = {llm.get('temperature', 0.2)}\n"
        f"MAX_TOKENS = {llm.get('max_tokens', 512)}\n\n"
        f"def generate(question: str, context_chunks: list[str]) -> str:\n"
        f"    prompt = TEMPLATE.format(context='\\n\\n---\\n\\n'.join(context_chunks), question=question)\n"
        f"    # Replace with ollama.llamacpp call in production.\n"
        f"    return f'(stub) answer for: {{question}}'\n"
    )


def _render_chat(name) -> str:
    return (
        f'"""{name} interactive chat (REPL)."""\\n'
        f"from __future__ import annotations\\n"
        f"from retrieve import retrieve\\n"
        f"from generate import generate\\n\\n"
        f"def chat() -> None:\\n"
        f"    print('Type a question, or Ctrl-D to exit.')\\n"
        f"    while True:\\n"
        f"        try:\\n"
        f"            q = input('\\\\n> ').strip()\\n"
        f"        except EOFError:\\n"
        f"            return\\n"
        f"        if not q: continue\\n"
        f"        ctx = retrieve(q)\\n"
        f"        print(generate(q, ctx))\\n\\n"
        f"if __name__ == '__main__':\\n"
        f"    chat()\\n"
    ).replace('\\\\n', '\\n')


def _render_evaluate(name, eval_set, prompt, llm) -> str:
    return (
        f'"""{name} evaluation harness."""\n'
        f"from __future__ import annotations\n"
        f"from retrieve import retrieve\n"
        f"from generate import generate\n\n"
        f"EVAL_SET = {json.dumps(eval_set, indent=2)}\n\n"
        f"def score(answer: str, keywords: list[str]) -> float:\n"
        f"    a = answer.lower()\n"
        f"    hits = sum(1 for k in keywords if k.lower() in a)\n"
        f"    return hits / max(1, len(keywords))\n\n"
        f"def main() -> float:\n"
        f"    total = 0.0\n"
        f"    for item in EVAL_SET:\n"
        f"        ctx = retrieve(item['question'])\n"
        f"        ans = generate(item['question'], ctx)\n"
        f"        s = score(ans, item.get('expected_keywords', []))\n"
        f"        total += s\n"
        f"        print(f\"Q: {{item['question']}}  score={{s:.2f}}\")\n"
        f"    return total / max(1, len(EVAL_SET))\n\n"
        f"if __name__ == '__main__':\n"
        f"    print('avg score:', main())\n"
    )


def _render_requirements(embedding, llm, vector_store, reranker) -> str:
    reqs = ["# generated by TIMPS Swarm local_rag_builder"]
    if embedding.get("provider") == "ollama":
        reqs.append("ollama>=0.3")
    if vector_store.get("kind") == "chroma":
        reqs.append("chromadb>=0.5")
    elif vector_store.get("kind") == "faiss":
        reqs.append("faiss-cpu>=1.8")
    elif vector_store.get("kind") == "lancedb":
        reqs.append("lancedb>=0.6")
    if reranker.get("enabled") and reranker.get("model"):
        reqs.append("sentence-transformers>=3.0")
    reqs.append("llama-index-core>=0.11")
    return "\n".join(reqs) + "\n"


def _render_dockerfile(llm_model, embed_model) -> str:
    return (
        f"FROM python:3.11-slim\n"
        f"WORKDIR /app\n"
        f"COPY requirements.txt .\n"
        f"RUN pip install --no-cache-dir -r requirements.txt\n"
        f"COPY . .\n"
        f"# In production: ollama pull {llm_model} && ollama pull {embed_model}\n"
        f'CMD ["python", "chat.py"]\n'
    )


def _render_makefile(name) -> str:
    return (
        f".PHONY: install ingest chat eval docker\n"
        f"install:\\n"
        f"\\tpip install -r requirements.txt\\n\\n"
        f"ingest:\\n"
        f"\\tpython ingest.py\\n\\n"
        f"chat:\\n"
        f"\\tpython chat.py\\n\\n"
        f"eval:\\n"
        f"\\tpython evaluate.py\\n\\n"
        f"docker:\\n"
        f"\\tdocker build -t {name} .\\n"
    ).replace("\\n", "\n")


def _render_readme(name, parsed, perf) -> str:
    return (
        f"# {name} — Local RAG Pipeline\n\n"
        f"Generated by **TIMPS Swarm** `local_rag_builder`.\n\n"
        f"## Config\n```json\n{json.dumps(parsed, indent=2)}\n```\n\n"
        f"## Expected perf\n- p50: {perf.get('expected_p50_ms','?')} ms\n"
        f"- p95: {perf.get('expected_p95_ms','?')} ms\n\n"
        f"## Quickstart\n```bash\nmake install\nmake ingest\nmake chat\nmake eval\n```\n"
    )
