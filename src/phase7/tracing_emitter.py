"""Tracing Emitter — OpenTelemetry/OTLP emitter for any agent or Python
service.  Produces a ready-to-paste instrumented module (and the
collector/agent config) that emits traces, metrics, and logs to a
backend of choice (Jaeger, Tempo, Honeycomb, Datadog, New Relic, OTLP).

The agent is LLM-driven: the LLM designs the resource attributes,
custom span names, metric names + units, and a sampling strategy based
on the user's service description.  The output is a complete,
drop-in `tracing.py` and a `collector.yaml`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

BACKENDS = ("jaeger", "tempo", "honeycomb", "datadog", "newrelic", "otlp")


def tracing_emitter(args: Dict[str, Any]) -> Dict[str, Any]:
    service = (args.get("service") or args.get("description") or "").strip()
    backend = (args.get("backend") or "otlp").lower()
    if backend not in BACKENDS:
        backend = "otlp"
    endpoint = args.get("endpoint") or _default_endpoint(backend)
    sample_ratio = float(args.get("sample_ratio") or 1.0)
    extra_packages: List[str] = args.get("extra_packages") or []

    if not service:
        return {"summary": "No service description supplied.", "error": "service is required",
                "tracing_py": "", "collector_yaml": ""}

    design = _design(service, backend, endpoint, sample_ratio, extra_packages)
    tracing_py = _render_tracing_py(design, backend, endpoint, sample_ratio)
    collector_yaml = _render_collector(design, backend, endpoint)
    otel_requirements = "opentelemetry-api>=1.27\nopentelemetry-sdk>=1.27\n"
    otel_requirements += f"opentelemetry-exporter-otlp-proto-{ 'grpc' if backend != 'jaeger' else 'http' }>=1.27\n"
    if backend in {"jaeger", "tempo"}:
        otel_requirements += "opentelemetry-exporter-jaeger>=1.27\n"
    for pkg in extra_packages:
        otel_requirements += f"{pkg}\n"

    payload = {
        "summary": _summary(service, backend, design),
        "service": service,
        "backend": backend,
        "endpoint": endpoint,
        "sample_ratio": sample_ratio,
        "design": design,
        "tracing_py": tracing_py,
        "collector_yaml": collector_yaml,
        "requirements": otel_requirements,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", service.lower()).strip("_")[:40] or "svc"
    _save("phase7/tracing", f"{slug}_{backend}_tracing.py", tracing_py)
    _save("phase7/tracing", f"{slug}_{backend}_collector.yaml", collector_yaml)
    _save("phase7/tracing", f"{slug}_requirements.txt", otel_requirements)
    _save("phase7/tracing", f"{slug}_summary.json", json.dumps(payload, indent=2))
    _record("tracing_emitter", service[:60], f"backend={backend} spans={len(design.get('spans', []))}")
    return payload


# ---------------------------------------------------------------------------

def _default_endpoint(backend: str) -> str:
    return {
        "jaeger":   "http://localhost:14268/api/traces",
        "tempo":    "http://localhost:4318/v1/traces",
        "honeycomb":"https://api.honeycomb.io",
        "datadog":  "https://trace.agent.datadoghq.com",
        "newrelic": "https://otlp.nr-data.net:4318/v1/traces",
        "otlp":     "http://localhost:4318/v1/traces",
    }.get(backend, "http://localhost:4318/v1/traces")


def _design(service: str, backend: str, endpoint: str, sample: float, extras: List[str]) -> Dict[str, Any]:
    system = (
        "You are an observability architect.  Design an OpenTelemetry "
        "instrumentation for the service.  Return ONLY a JSON object:\n"
        "{\n"
        '  "resource_attributes": [str],   // service.name, deployment.environment, etc.\n'
        '  "spans": [\n'
        '    {"name": str, "kind": "internal"|"server"|"client"|"producer"|"consumer", '
        '    "attributes": [str], "events": [str]}\n'
        '  ],\n'
        '  "metrics": [\n'
        '    {"name": str, "type": "counter"|"histogram"|"gauge", "unit": str, '
        '    "description": str, "labels": [str]}\n'
        '  ],\n'
        '  "logs": [str],                  // structured-log fields\n'
        '  "sampling": {"strategy": "always_on"|"probabilistic"|"parent_based", '
        '  "ratio": float, "rationale": str}\n'
        "}\n\n"
        "Rules:\n"
        "- Span names should be lower_snake_case and stable (used for dashboards).\n"
        "- Metric names should follow Otel semantic conventions where possible.\n"
        "- Counter units: '{request}', '{error}', '{item}'.\n"
        "- Histogram units: 's' for latency, 'By' for sizes."
    )
    user = (
        f"Service: {service}\n"
        f"Backend: {backend}\nEndpoint: {endpoint}\n"
        f"Sample ratio: {sample}\nExtra packages: {json.dumps(extras)}"
    )
    raw = _llm(user, system, "tracing_emitter")
    parsed = _parse_json(raw, fallback={"resource_attributes": [], "spans": [], "metrics": [], "logs": [], "sampling": {}})
    parsed.setdefault("resource_attributes", [f"service.name={service}", "deployment.environment=prod"])
    parsed.setdefault("sampling", {"strategy": "probabilistic", "ratio": sample, "rationale": "default"})
    return parsed


def _render_tracing_py(d: Dict[str, Any], backend: str, endpoint: str, sample: float) -> str:
    attrs = "\n    ".join(f'"{a}",' for a in d.get("resource_attributes", []))
    spans = "\n".join(
        f'    @tracer.start_as_current_span({json.dumps(s["name"])}, kind=SpanKind.{s.get("kind","INTERNAL").upper()})\n'
        f'    def {s["name"].replace(".", "_")}(*a, **kw):\n'
        f'        yield\n'
        for s in d.get("spans", [])
    )
    metrics = "\n".join(
        f'    {m["name"]} = meter.create_{m["type"]}("{m["name"]}", unit="{m.get("unit","1")}", description={json.dumps(m.get("description",""))})'
        for m in d.get("metrics", [])
    )
    return (
        '"""tracing.py — generated by TIMPS Swarm tracing_emitter."""\n'
        'from __future__ import annotations\n'
        'import os\n'
        'from contextlib import contextmanager\n'
        'from opentelemetry import trace, metrics\n'
        'from opentelemetry.sdk.resources import Resource\n'
        'from opentelemetry.sdk.trace import TracerProvider\n'
        'from opentelemetry.sdk.trace.export import BatchSpanProcessor\n'
        'from opentelemetry.sdk.trace.sampling import TraceIdRatioBased\n'
        'from opentelemetry.sdk.metrics import MeterProvider\n'
        'from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader\n'
        'from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\n'
        'from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter\n'
        'from opentelemetry.trace import SpanKind\n\n'
        f'ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "{endpoint}")\n'
        f'SAMPLE    = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "{sample}"))\n\n'
        '_resource = Resource.create({\n'
        f'    {attrs}\n'
        '})\n'
        '_provider = TracerProvider(resource=_resource, sampler=TraceIdRatioBased(SAMPLE))\n'
        '_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT + "/v1/traces")))\n'
        'trace.set_tracer_provider(_provider)\n'
        '_meter = MeterProvider(resource=_resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=ENDPOINT + "/v1/metrics"))])\n'
        'metrics.set_meter_provider(_meter)\n'
        'tracer = trace.get_tracer(__name__)\n'
        'meter  = metrics.get_meter(__name__)\n\n'
        f'{metrics}\n\n'
        f'{spans}\n'
    )


def _render_collector(d: Dict[str, Any], backend: str, endpoint: str) -> str:
    return (
        f"# OpenTelemetry Collector — generated by TIMPS Swarm tracing_emitter\n"
        f"receivers:\n"
        f"  otlp:\n"
        f"    protocols:\n"
        f"      grpc: {{}}\n"
        f"      http: {{}}\n\n"
        f"processors:\n"
        f"  batch: {{}}\n"
        f"  memory_limiter:\n"
        f"    limit_mib: 512\n\n"
        f"exporters:\n"
        f"  {backend}:\n"
        f"    endpoint: {endpoint}\n\n"
        f"service:\n"
        f"  pipelines:\n"
        f"    traces:\n"
        f"      receivers: [otlp]\n"
        f"      processors: [memory_limiter, batch]\n"
        f"      exporters: [{backend}]\n"
        f"    metrics:\n"
        f"      receivers: [otlp]\n"
        f"      processors: [memory_limiter, batch]\n"
        f"      exporters: [{backend}]\n"
    )


def _summary(service: str, backend: str, design: Dict[str, Any]) -> str:
    n_s = len(design.get("spans", []))
    n_m = len(design.get("metrics", []))
    return f"Tracing design for '{service}' → {backend}: {n_s} spans, {n_m} metrics."
