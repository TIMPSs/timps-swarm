"""Service Mesh Configurator — generates Istio / Linkerd configuration for
a microservice: mTLS, traffic split, fault injection, retries, timeouts,
authorization policies, telemetry.

Outputs:

* A `mesh.yaml` for the chosen mesh (Istio or Linkerd).
* Per-service: VirtualService / DestinationRule / ServiceEntry equivalents.
* An AuthorizationPolicy (Istio) or Server/AuthorizationPolicy (Linkerd).
* A traffic-shift manifest for canary / blue-green.
* A fault-injection manifest for chaos testing.
* A README explaining the configuration.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

MESHES = ("istio", "linkerd")


def service_mesh_configurator(args: Dict[str, Any]) -> Dict[str, Any]:
    service = (args.get("service") or args.get("description") or args.get("request") or "").strip()
    if not service:
        return {"summary": "No service description supplied.", "error": "service is required",
                "configs": []}

    mesh = (args.get("mesh") or "istio").lower()
    if mesh not in MESHES: mesh = "istio"
    namespace = (args.get("namespace") or "default").strip()
    mtls_mode = (args.get("mtls") or "strict").lower()
    canary_pct = int(args.get("canary_pct") or 10)

    design = _design(service, mesh, namespace, mtls_mode, canary_pct)
    yaml = _render_yaml(design, mesh)
    fault = _render_fault_injection(design, mesh)
    traffic = _render_traffic_split(design, mesh, canary_pct)
    authz = _render_authz(design, mesh)
    readme = _render_readme(design, mesh, namespace, mtls_mode, canary_pct)

    payload = {
        "summary": _summary(service, mesh, design),
        "service": service,
        "mesh": mesh,
        "namespace": namespace,
        "mtls": mtls_mode,
        "canary_pct": canary_pct,
        "design": design,
        "configs": [
            {"name": "mesh", "filename": f"{service}_mesh.yaml", "content": yaml},
            {"name": "fault_injection", "filename": f"{service}_fault.yaml", "content": fault},
            {"name": "traffic_split",   "filename": f"{service}_traffic.yaml", "content": traffic},
            {"name": "authz",           "filename": f"{service}_authz.yaml", "content": authz},
        ],
        "readme": readme,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", service.lower()).strip("_")[:40] or "svc"
    for c in payload["configs"]:
        _save("phase7/mesh", c["filename"], c["content"])
    _save("phase7/mesh", f"{slug}_README.md", readme)
    _record("service_mesh_configurator", service[:60], f"mesh={mesh} configs={len(payload['configs'])}")
    return payload


# ---------------------------------------------------------------------------

def _design(service: str, mesh: str, ns: str, mtls: str, canary: int) -> Dict[str, Any]:
    system = (
        f"You design a {mesh} service-mesh configuration for a microservice.  "
        f"Return ONLY a JSON object:\n"
        "{\n"
        '  "service": str, "namespace": str, "ports": [{"name": str, "number": int, "protocol": "HTTP"|"HTTPS"|"gRPC"}],\n'
        '  "mtls": "strict"|"permissive",\n'
        '  "canary_baseline_version": str, "canary_candidate_version": str,\n'
        '  "fault_injection": {"delay_ms": int, "abort_http": int, "pct": int},\n'
        '  "retries": {"attempts": int, "per_try_timeout_ms": int, "retry_on": [str]},\n'
        '  "timeouts": {"request_s": int},\n'
        '  "authz": {\n'
        '    "allow": [{"from": str, "to": str, "methods": [str], "paths": [str]}],\n'
        '    "deny":  [{"from": str, "to": str}]\n'
        '  },\n'
        '  "telemetry": {"access_log": bool, "metrics": [str], "tracing": bool}\n'
        "}"
    )
    user = (
        f"Service: {service}\nMesh: {mesh}\nNamespace: {ns}\n"
        f"mTLS: {mtls}\nCanary: {canary}%\n"
        "Defaults: 2 ports (http:8080, metrics:9090), 3 retries, 5s request timeout, 10% fault."
    )
    raw = _llm(user, system, "service_mesh_configurator")
    parsed = _parse_json(raw, fallback={
        "service": service, "namespace": ns, "ports": [
            {"name": "http", "number": 8080, "protocol": "HTTP"},
            {"name": "metrics", "number": 9090, "protocol": "HTTP"}],
        "mtls": mtls, "canary_baseline_version": "v1", "canary_candidate_version": "v2",
        "fault_injection": {"delay_ms": 200, "abort_http": 503, "pct": 10},
        "retries": {"attempts": 3, "per_try_timeout_ms": 2000, "retry_on": ["5xx", "reset", "connect-failure"]},
        "timeouts": {"request_s": 5}, "authz": {"allow": [], "deny": []},
        "telemetry": {"access_log": True, "metrics": ["request_count", "latency"], "tracing": True}
    })
    parsed.setdefault("service", service)
    parsed.setdefault("namespace", ns)
    return parsed


def _render_yaml(d: Dict[str, Any], mesh: str) -> str:
    if mesh == "istio":
        ports_yaml = "\n    ".join(
            f"- number: {p['number']}\n      name: {p['name']}\n      protocol: {p['protocol']}" for p in d.get("ports", [])
        )
        return (
            f"apiVersion: v1\nkind: Service\nmetadata:\n  name: {d['service']}\n  namespace: {d['namespace']}\nspec:\n  ports:\n    {ports_yaml}\n  selector:\n    app: {d['service']}\n---\n"
            f"apiVersion: security.istio.io/v1beta1\nkind: PeerAuthentication\nmetadata:\n  name: {d['service']}-mtls\n  namespace: {d['namespace']}\nspec:\n  mtls:\n    mode: {d.get('mtls','STRICT').upper()}\n---\n"
            f"apiVersion: networking.istio.io/v1beta1\nkind: DestinationRule\nmetadata:\n  name: {d['service']}-dr\n  namespace: {d['namespace']}\nspec:\n  host: {d['service']}\n  trafficPolicy:\n    connectionPool:\n      http:\n        h2UpgradePolicy: DEFAULT\n        maxRequestsPerConnection: 100\n    outlierDetection:\n      consecutive5xxErrors: 5\n      interval: 30s\n      baseEjectionTime: 30s\n    retries:\n      attempts: {d.get('retries',{}).get('attempts',3)}\n      perTryTimeout: {d.get('retries',{}).get('per_try_timeout_ms',2000)}ms\n      retryOn: '{','.join(d.get('retries',{}).get('retry_on',['5xx']))}'\n    timeout: {d.get('timeouts',{}).get('request_s',5)}s\n"
        )
    # linkerd
    return (
        f"apiVersion: v1\nkind: Service\nmetadata:\n  name: {d['service']}\n  namespace: {d['namespace']}\n  annotations:\n    linkerd.io/inject: enabled\nspec:\n  selector:\n    app: {d['service']}\n---\n"
        f"apiVersion: policy.linkerd.io/v1beta1\nkind: Server\nmetadata:\n  name: {d['service']}\n  namespace: {d['namespace']}\nspec:\n  podSelector:\n    matchLabels:\n      app: {d['service']}\n  port: 8080\n  proxyProtocol: HTTP/1\n"
    )


def _render_fault_injection(d: Dict[str, Any], mesh: str) -> str:
    f = d.get("fault_injection", {})
    if mesh == "istio":
        return (
            f"apiVersion: networking.istio.io/v1beta1\nkind: VirtualService\nmetadata:\n  name: {d['service']}-fault\n  namespace: {d['namespace']}\nspec:\n  hosts: [{d['service']}]\n  http:\n  - fault:\n      delay:\n        percentage:\n          value: {f.get('pct',10)}\n        fixedDelay: {f.get('delay_ms',200)}ms\n      abort:\n        percentage:\n          value: {f.get('pct',10)}\n        httpStatus: {f.get('abort_http',503)}\n    route:\n    - destination:\n        host: {d['service']}\n"
        )
    return (
        f"# Linkerd fault injection via SMI TrafficSplit or service-profile\n"
        f"# Use: linkerd profile --proto http {d['service']}.{d['namespace']}.svc.cluster.local:8080\n"
        f"# Then patch the profile with retryBudget / successRate thresholds."
    )


def _render_traffic_split(d: Dict[str, Any], mesh: str, canary_pct: int) -> str:
    baseline = d.get("canary_baseline_version", "v1")
    cand = d.get("canary_candidate_version", "v2")
    if mesh == "istio":
        return (
            f"apiVersion: networking.istio.io/v1beta1\nkind: VirtualService\nmetadata:\n  name: {d['service']}-canary\n  namespace: {d['namespace']}\nspec:\n  hosts: [{d['service']}]\n  http:\n  - route:\n    - destination:\n        host: {d['service']}\n        subset: {baseline}\n      weight: {100 - canary_pct}\n    - destination:\n        host: {d['service']}\n        subset: {cand}\n      weight: {canary_pct}\n---\n"
            f"apiVersion: networking.istio.io/v1beta1\nkind: DestinationRule\nmetadata:\n  name: {d['service']}-subsets\n  namespace: {d['namespace']}\nspec:\n  host: {d['service']}\n  subsets:\n  - name: {baseline}\n    labels: {{ version: {baseline} }}\n  - name: {cand}\n    labels: {{ version: {cand} }}\n"
        )
    return (
        f"apiVersion: split.smi-spec.io/v1alpha1\nkind: TrafficSplit\nmetadata:\n  name: {d['service']}-canary\n  namespace: {d['namespace']}\nspec:\n  service: {d['service']}\n  backends:\n  - service: {d['service']}-{baseline}\n    weight: {100 - canary_pct}\n  - service: {d['service']}-{cand}\n    weight: {canary_pct}\n"
    )


def _render_authz(d: Dict[str, Any], mesh: str) -> str:
    allows = d.get("authz", {}).get("allow") or [{"from": "gateway", "to": d.get("service", "?"), "methods": ["GET"], "paths": ["/"]}]
    if mesh == "istio":
        rules = []
        for a in allows:
            rules.append(
                f"- from:\n    - source:\n        principals: ['cluster.local/ns/{d['namespace']}/sa/{a.get('from','default')}']\n  to:\n    - operation:\n        methods: {a.get('methods', ['GET'])}\n        paths: {a.get('paths', ['/'])}"
            )
        return (
            f"apiVersion: security.istio.io/v1beta1\nkind: AuthorizationPolicy\nmetadata:\n  name: {d['service']}-authz\n  namespace: {d['namespace']}\nspec:\n  action: ALLOW\n  rules:\n" + "\n".join(rules) + "\n"
        )
    # linkerd
    authz_yaml = []
    for a in allows:
        authz_yaml.append(
            f"apiVersion: policy.linkerd.io/v1beta1\nkind: AuthorizationPolicy\nmetadata:\n  name: {d['service']}-from-{a.get('from','default')}\n  namespace: {d['namespace']}\nspec:\n  targetRef:\n    group: policy.linkerd.io\n    kind: ServiceAccount\n    name: {d['service']}\n  requiredAuthenticationRefs:\n  - group: policy.linkerd.io\n    kind: MeshTLSAuthentication\n    name: {a.get('from','default')}\n"
        )
    return "---\n".join(authz_yaml)


def _render_readme(d: Dict[str, Any], mesh: str, ns: str, mtls: str, canary: int) -> str:
    return (
        f"# {d['service']} — {mesh} configuration\n\n"
        f"- Namespace: `{ns}`\n- mTLS: `{mtls}`\n- Canary: `{canary}%` to version `{d.get('canary_candidate_version','v2')}`\n\n"
        f"## Apply\n```bash\nkubectl apply -f {d['service']}_mesh.yaml\nkubectl apply -f {d['service']}_authz.yaml\nkubectl apply -f {d['service']}_traffic.yaml\n```\n\n"
        f"## Validate\n```bash\nlinkerd check   # if Linkerd\nistioctl analyze  # if Istio\n```\n"
    )


def _summary(service: str, mesh: str, d: Dict[str, Any]) -> str:
    return f"Mesh config ({mesh}) for {service}: {len(d.get('ports',[]))} ports, canary to {d.get('canary_candidate_version','v2')}."
