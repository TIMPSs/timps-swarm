"""
API Performance Profiler — static + symbolic analysis for slow APIs.

Looks for N+1 queries, missing indexes, blocking I/O on hot paths,
serialization overhead, request fan-out, missing pagination, cache
misses, and synchronous third-party calls in critical paths. Generates
a benchmarking script (k6 or Locust) and a ranked optimisation backlog
with projected latency/QPS gains.

Input:  code (str), path (str), framework (str), endpoint (str),
        slo_p99_ms (int), traffic_estimate_qps (int)
Output: hotspots, n_plus_one_findings, blocking_calls, missing_cache,
        recommendations, benchmark_script, projected_gains, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record


def _collect(path_str: str, code: str) -> str:
    if code:
        return code[:7500]
    if not path_str:
        return ""
    p = Path(path_str)
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")[:7500]
    if p.is_dir():
        chunks: List[str] = []
        for ext in ("*.py", "*.ts", "*.js", "*.go", "*.rb", "*.java"):
            for f in list(p.rglob(ext))[:4]:
                chunks.append(f"### {f}\n" +
                              f.read_text(encoding="utf-8", errors="ignore")[:900])
            if sum(len(c) for c in chunks) > 7000:
                break
        return "\n\n".join(chunks)[:7500]
    return ""


def api_perf_profiler(args: Dict[str, Any]) -> Dict[str, Any]:
    code         = args.get("code", "")
    path_str     = args.get("path", "")
    framework    = args.get("framework", "auto")
    endpoint     = args.get("endpoint", "/api/*")
    slo_p99_ms   = int(args.get("slo_p99_ms", 200))
    traffic_qps  = int(args.get("traffic_estimate_qps", 100))
    db_engine    = args.get("db_engine", "postgresql")

    source = _collect(path_str, code)

    system = (
        "You are an API performance engineer. Statically analyse the source for "
        "common latency killers: N+1 ORM queries, missing eager loading, blocking "
        "I/O in async paths, sync HTTP calls in hot loops, missing pagination, "
        "unbounded result sets, missing caching/HTTP cache headers, missing or "
        "wrong DB indexes, expensive serialisation (Pydantic .dict() on huge "
        "objects), and request fan-out. For each finding, estimate the impact "
        "(ms saved) and provide a SPECIFIC fix. Then generate a load-test script. "
        "Output ONLY valid JSON: "
        "{framework_detected:str, endpoint:str, slo_p99_ms:int, "
        "estimated_current_p99_ms:int, "
        "hotspots:[{location,kind,evidence,severity:'critical'|'high'|'medium'"
        "|'low',estimated_ms_saved,fix}], "
        "n_plus_one_findings:[{location,model,suggested_eager_load_or_join}], "
        "blocking_calls_in_async:[{location,call,async_alternative}], "
        "missing_cache_opportunities:[{location,key_strategy,ttl_seconds}], "
        "missing_indexes:[{table,columns,kind,create_sql}], "
        "recommendations:[{title,priority:'p0'|'p1'|'p2',effort_hours,"
        "impact_summary}], "
        "benchmark_tool:'k6'|'locust'|'wrk', "
        "benchmark_script:{filename,content}, "
        "projected_after_fixes:{p99_ms,qps,error_rate}, "
        "instrumentation_to_add:[str]}."
    )
    prompt = (
        f"Framework: {framework}\nEndpoint: {endpoint}\nDB: {db_engine}\n"
        f"SLO p99: {slo_p99_ms}ms  Traffic: {traffic_qps} qps\n\n"
        f"SOURCE:\n```\n{source}\n```\n\n"
        "Be specific. Cite exact line ranges where possible. "
        "Generate a runnable benchmark script."
    )

    data = _parse_json(_llm(prompt, system, "api_perf_profiler"), {
        "hotspots": [], "recommendations": [], "benchmark_script": {},
        "projected_after_fixes": {},
    })

    ts = _ts()
    bench = data.get("benchmark_script", {}) or {}
    bench_path = ""
    if bench.get("content"):
        ext = {"k6": "js", "locust": "py", "wrk": "lua"}.get(
            data.get("benchmark_tool", "k6"), "js")
        fname = bench.get("filename") or f"bench_{ts}.{ext}"
        bench_path = _save("perf", fname, bench["content"])

    indexes_path = ""
    if data.get("missing_indexes"):
        sql = "\n".join(i.get("create_sql", "") for i in data["missing_indexes"]
                        if i.get("create_sql"))
        if sql:
            indexes_path = _save("perf", f"recommended_indexes_{ts}.sql", sql)

    proj = data.get("projected_after_fixes", {})
    hotspots = data.get("hotspots", [])
    critical = [h for h in hotspots if h.get("severity") in ("critical", "high")]

    report = (
        f"# API Performance Profiler — {endpoint} — {ts}\n\n"
        f"**SLO p99:** {slo_p99_ms}ms  "
        f"**Estimated current p99:** {data.get('estimated_current_p99_ms','?')}ms  "
        f"**Projected after fixes:** {proj.get('p99_ms','?')}ms\n\n"
        f"**Hotspots:** {len(hotspots)} ({len(critical)} critical/high)  "
        f"**N+1 findings:** {len(data.get('n_plus_one_findings',[]))}  "
        f"**Missing indexes:** {len(data.get('missing_indexes',[]))}\n\n"
        "## Hotspots\n"
        + "\n".join(
            f"- [{h.get('severity','?').upper()}] `{h.get('location','?')}` "
            f"({h.get('kind','?')}) — saves ~{h.get('estimated_ms_saved','?')}ms — "
            f"{h.get('fix','')}"
            for h in hotspots
        )
        + "\n\n## N+1 query findings\n"
        + "\n".join(
            f"- `{n.get('location','?')}` model `{n.get('model','?')}` → "
            f"`{n.get('suggested_eager_load_or_join','')}`"
            for n in data.get("n_plus_one_findings", [])
        )
        + "\n\n## Blocking calls in async paths\n"
        + "\n".join(
            f"- `{b.get('location','?')}` call `{b.get('call','?')}` → "
            f"`{b.get('async_alternative','')}`"
            for b in data.get("blocking_calls_in_async", [])
        )
        + "\n\n## Recommendations (ranked)\n"
        + "\n".join(
            f"- [{r.get('priority','?').upper()}] {r.get('title','?')} "
            f"(~{r.get('effort_hours','?')}h) — {r.get('impact_summary','')}"
            for r in data.get("recommendations", [])
        )
        + f"\n\n## Artifacts\n- Benchmark: `{bench_path or '(not generated)'}`\n"
        + (f"- Indexes: `{indexes_path}`\n" if indexes_path else "")
    )
    report_path = _save("reports", f"api_perf_profiler_{ts}.md", report)

    _record("api_perf_profiler", endpoint,
            f"hotspots={len(hotspots)} critical={len(critical)} "
            f"p99={data.get('estimated_current_p99_ms')}→{proj.get('p99_ms')}")

    return {
        "framework_detected":     data.get("framework_detected", framework),
        "endpoint":               endpoint,
        "slo_p99_ms":             slo_p99_ms,
        "estimated_current_p99_ms": data.get("estimated_current_p99_ms"),
        "hotspots":               hotspots,
        "n_plus_one_findings":    data.get("n_plus_one_findings", []),
        "blocking_calls_in_async": data.get("blocking_calls_in_async", []),
        "missing_cache_opportunities": data.get("missing_cache_opportunities", []),
        "missing_indexes":        data.get("missing_indexes", []),
        "recommendations":        data.get("recommendations", []),
        "benchmark_tool":         data.get("benchmark_tool", "k6"),
        "benchmark_script_path":  bench_path,
        "indexes_sql_path":       indexes_path,
        "projected_after_fixes":  proj,
        "instrumentation_to_add": data.get("instrumentation_to_add", []),
        "report_path":            report_path,
        "summary": (
            f"{len(hotspots)} hotspots ({len(critical)} crit/high). "
            f"p99: ~{data.get('estimated_current_p99_ms','?')}ms → "
            f"~{proj.get('p99_ms','?')}ms. → {report_path}."
        ),
    }
