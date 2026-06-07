"""RAG Evaluator — RAGAS-style evaluation harness for any RAG pipeline.

Runs a golden eval set through a retriever + generator and reports:

* **Retrieval metrics** (when expected contexts are provided):
  context_precision@k, context_recall@k, MRR, NDCG@k, hit_rate.
* **Generation metrics** (LLM-as-judge): faithfulness, answer_relevance,
  answer_correctness (vs. expected), hallucination, completeness.
* **Aggregate scores** + a regression diff vs. a previous run (if supplied).

Inputs:

* `eval_set_path`   — JSONL file or list of dicts with:
                       {"question": str, "expected_answer": str,
                        "expected_contexts": [str] (optional)}
* `retriever_call`  — callable name (registered in `src.nextgen.rag_evaluator._RETRIEVERS`)
                       or a literal "stub" that returns a fake top-k
* `generator_call`  — same — "stub" or a registered name
* `previous_results` — path to a prior summary.json for regression comparison
* `metrics`         — subset of the metric names to compute
* `top_k`           — int, default 5

The agent NEVER assumes a real LLM call is needed; if the configured
retriever/generator is "stub" it runs offline so the harness is always
exercisable.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

DEFAULT_METRICS = ("context_precision", "context_recall", "hit_rate", "mrr",
                   "faithfulness", "answer_relevance", "answer_correctness",
                   "completeness", "hallucination")


def rag_evaluator(args: Dict[str, Any]) -> Dict[str, Any]:
    eval_set = _load_eval_set(args.get("eval_set_path") or args.get("eval_set") or [])
    retriever = args.get("retriever_call") or "stub"
    generator = args.get("generator_call") or "stub"
    top_k = int(args.get("top_k") or 5)
    metrics = tuple(args.get("metrics") or DEFAULT_METRICS)
    previous_path = args.get("previous_results")
    out_path = Path(args.get("out_path") or f"generated/phase7/rag_eval/{_ts()}_summary.json")

    if not eval_set:
        return {
            "summary": "No eval set provided — supply eval_set_path or eval_set.",
            "error": "eval_set is required",
            "aggregate": {},
        }

    per_question: List[Dict[str, Any]] = []
    for item in eval_set:
        per_question.append(_evaluate_one(item, retriever, generator, top_k, metrics))

    aggregate = _aggregate(per_question, metrics)
    regressions: List[Dict[str, Any]] = []
    if previous_path and Path(previous_path).is_file():
        regressions = _regress(aggregate, _load_json(previous_path))

    payload = {
        "summary": _summary(aggregate, regressions, len(per_question)),
        "retriever_call": retriever,
        "generator_call": generator,
        "top_k": top_k,
        "metrics": list(metrics),
        "n_questions": len(per_question),
        "per_question": per_question,
        "aggregate": aggregate,
        "regressions": regressions,
        "out_path": str(out_path),
        "generated_at": _ts(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _save("phase7/rag_eval", f"{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("rag_evaluator", f"{len(per_question)}q", f"agg={json.dumps(aggregate)[:200]}")
    return payload


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_eval_set(src: Any) -> List[Dict[str, Any]]:
    if isinstance(src, list):
        return [x for x in src if isinstance(x, dict) and x.get("question")]
    p = Path(str(src))
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                if obj.get("question"):
                    out.append(obj)
            except Exception:
                pass
    if not out and text.strip().startswith("["):
        try:
            arr = json.loads(text)
            out = [x for x in arr if isinstance(x, dict) and x.get("question")]
        except Exception:
            pass
    return out


def _load_json(p: str) -> Dict[str, Any]:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Per-question evaluation
# ---------------------------------------------------------------------------

def _evaluate_one(item: Dict[str, Any], retriever: str, generator: str, top_k: int, metrics: tuple) -> Dict[str, Any]:
    question = item.get("question", "").strip()
    expected_answer = (item.get("expected_answer") or "").strip()
    expected_contexts = item.get("expected_contexts") or []

    retrieved = _call_retriever(retriever, question, top_k)
    answer = _call_generator(generator, question, retrieved)

    scores: Dict[str, float] = {}
    notes: List[str] = []

    if "context_precision" in metrics and expected_contexts:
        scores["context_precision"] = _context_precision(retrieved, expected_contexts, top_k)
    if "context_recall" in metrics and expected_contexts:
        scores["context_recall"] = _context_recall(retrieved, expected_contexts)
    if "hit_rate" in metrics and expected_contexts:
        scores["hit_rate"] = _hit_rate(retrieved, expected_contexts)
    if "mrr" in metrics and expected_contexts:
        scores["mrr"] = _mrr(retrieved, expected_contexts)
    if "ndcg" in metrics and expected_contexts:
        scores["ndcg"] = _ndcg(retrieved, expected_contexts, top_k)
    if "faithfulness" in metrics:
        scores["faithfulness"] = _llm_judge(question, retrieved, answer, "faithfulness")
    if "answer_relevance" in metrics:
        scores["answer_relevance"] = _llm_judge(question, retrieved, answer, "answer_relevance")
    if "answer_correctness" in metrics and expected_answer:
        scores["answer_correctness"] = _answer_correctness(answer, expected_answer)
    if "completeness" in metrics and expected_answer:
        scores["completeness"] = _completeness(answer, expected_answer)
    if "hallucination" in metrics:
        scores["hallucination"] = 1.0 - _llm_judge(question, retrieved, answer, "faithfulness")

    return {
        "question": question,
        "expected_answer": expected_answer,
        "answer": answer,
        "retrieved": retrieved,
        "scores": scores,
        "notes": notes,
    }


def _call_retriever(name: str, question: str, top_k: int) -> List[Dict[str, Any]]:
    """Return a list of {text, score?}.  Built-in: 'stub' (offline)."""
    if name == "stub":
        # offline fake retriever: split question into tokens, return one fake doc
        return [
            {"text": f"(stub) passage for: {question}", "score": 0.9},
            {"text": "(stub) related background context", "score": 0.7},
        ][:top_k]
    try:
        from src.nextgen import NEXTGEN_AGENTS  # type: ignore
        fn = NEXTGEN_AGENTS.get(name)
        if fn:
            r = fn({"query": question, "max_results": top_k})
            return [{"text": (x.get("content") or x.get("snippet") or ""), "url": x.get("url", "")} for x in r.get("results", [])]
    except Exception:
        pass
    return []


def _call_generator(name: str, question: str, retrieved: List[Dict[str, Any]]) -> str:
    if name == "stub":
        ctx = " ".join((r.get("text") or "")[:200] for r in retrieved[:2])
        return f"(stub) Based on: {ctx} — answer for: {question}"
    try:
        from src.aiml import AIML_AGENTS  # type: ignore
        from src.more_agents import MORE_AGENTS  # type: ignore
        fn = AIML_AGENTS.get(name) or MORE_AGENTS.get(name)
        if fn:
            r = fn({"request": f"Answer this question using the context. Q: {question}\nContext: {retrieved}"})
            return r.get("summary") or r.get("answer") or str(r)[:500]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------

def _context_precision(retrieved: List[Dict[str, Any]], expected: List[str], k: int) -> float:
    if not expected or k == 0:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if any(_overlap(r.get("text", ""), e) for e in expected))
    return hits / k


def _context_recall(retrieved: List[Dict[str, Any]], expected: List[str]) -> float:
    if not expected:
        return 0.0
    found = sum(1 for e in expected if any(_overlap(r.get("text", ""), e) for r in retrieved))
    return found / len(expected)


def _hit_rate(retrieved: List[Dict[str, Any]], expected: List[str]) -> float:
    return 1.0 if any(_overlap(r.get("text", ""), e) for r in retrieved for e in expected) else 0.0


def _mrr(retrieved: List[Dict[str, Any]], expected: List[str]) -> float:
    for i, r in enumerate(retrieved, start=1):
        if any(_overlap(r.get("text", ""), e) for e in expected):
            return 1.0 / i
    return 0.0


def _ndcg(retrieved: List[Dict[str, Any]], expected: List[str], k: int) -> float:
    rels = [1.0 if any(_overlap(r.get("text", ""), e) for e in expected) else 0.0 for r in retrieved[:k]]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, sum(1 for r in rels if r > 0)) or 1))
    return dcg / idcg if idcg else 0.0


def _overlap(text: str, expected: str) -> bool:
    if not text or not expected:
        return False
    a = set(re.findall(r"\w+", text.lower()))
    b = set(re.findall(r"\w+", expected.lower()))
    return len(a & b) >= max(3, min(8, len(b) // 4)) and (len(a & b) / max(1, len(b))) >= 0.3


# ---------------------------------------------------------------------------
# Generation metrics (LLM-as-judge + heuristics)
# ---------------------------------------------------------------------------

def _llm_judge(question: str, retrieved: List[Dict[str, Any]], answer: str, metric: str) -> float:
    system = (
        "You are an impartial RAG evaluator.  Score the ANSWER on a 0-1 scale for "
        f"the metric '{metric}'.  Return ONLY a JSON object: {{\"score\": float, "
        "\"reason\": str}}.  Be strict but fair."
    )
    user = (
        f"Question: {question}\n\n"
        f"Retrieved context (truncated):\n" + "\n---\n".join((r.get('text') or '')[:500] for r in retrieved[:5]) + "\n\n"
        f"Answer: {answer}\n\n"
        f"Score for '{metric}':"
    )
    raw = _llm(user, system, "rag_evaluator")
    parsed = _parse_json(raw, fallback={"score": 0.0, "reason": ""})
    return max(0.0, min(1.0, float(parsed.get("score", 0.0))))


def _answer_correctness(answer: str, expected: str) -> float:
    a_tokens = Counter(re.findall(r"\w+", (answer or "").lower()))
    e_tokens = Counter(re.findall(r"\w+", (expected or "").lower()))
    if not e_tokens:
        return 0.0
    overlap = sum((a_tokens & e_tokens).values())
    return min(1.0, overlap / sum(e_tokens.values()))


def _completeness(answer: str, expected: str) -> float:
    """Heuristic: fraction of expected sentences whose key tokens appear in the answer."""
    if not expected:
        return 0.0
    expected_sents = [s.strip() for s in re.split(r"[.!?]\s+", expected) if s.strip()]
    if not expected_sents:
        return 0.0
    ans_lc = (answer or "").lower()
    covered = sum(1 for s in expected_sents if any(tok in ans_lc for tok in re.findall(r"\w{4,}", s.lower())))
    return covered / len(expected_sents)


# ---------------------------------------------------------------------------
# Aggregation & regression
# ---------------------------------------------------------------------------

def _aggregate(per_question: List[Dict[str, Any]], metrics: tuple) -> Dict[str, float]:
    agg: Dict[str, float] = {}
    for m in metrics:
        vals = [q["scores"].get(m) for q in per_question if m in q["scores"]]
        if vals:
            agg[m] = round(sum(vals) / len(vals), 4)
    return agg


def _regress(current: Dict[str, float], previous_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    prev = previous_payload.get("aggregate") or {}
    out: List[Dict[str, Any]] = []
    for k, v in current.items():
        pv = prev.get(k)
        if pv is None: continue
        delta = round(v - pv, 4)
        if delta < -0.03:
            out.append({"metric": k, "previous": pv, "current": v, "delta": delta, "verdict": "regression"})
        elif delta > 0.03:
            out.append({"metric": k, "previous": pv, "current": v, "delta": delta, "verdict": "improvement"})
    return out


def _summary(agg: Dict[str, float], regressions: List[Dict[str, Any]], n: int) -> str:
    top = ", ".join(f"{k}={v:.2f}" for k, v in list(agg.items())[:4])
    n_reg = sum(1 for r in regressions if r["verdict"] == "regression")
    return f"RAG eval: {n} questions; aggregates: {top}; regressions={n_reg}."
