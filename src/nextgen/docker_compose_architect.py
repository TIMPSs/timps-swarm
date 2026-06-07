"""
Docker Compose Architect — design a complete, runnable multi-service
development environment from a plain-English description.

Generates: docker-compose.yml with proper networks, named volumes,
healthchecks, dependency ordering, env files, per-service Dockerfiles for
custom apps, .env templates, a Makefile target list, and a validation
runbook (compose config → up → smoke-test).

Input:  services_description (str), project_name (str), include_db (bool),
        include_cache (bool), include_observability (bool), env_target (str)
Output: compose_yaml, dockerfiles, env_template, makefile_snippet,
        validation_runbook, mermaid_diagram, report_path
"""
from __future__ import annotations

from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record


def docker_compose_architect(args: Dict[str, Any]) -> Dict[str, Any]:
    desc                  = args.get("services_description") or args.get("request") or \
                            "FastAPI + Postgres + Redis + Nginx reverse proxy"
    project_name          = args.get("project_name", "app")
    include_db            = bool(args.get("include_db", True))
    include_cache         = bool(args.get("include_cache", False))
    include_observability = bool(args.get("include_observability", False))
    env_target            = args.get("env_target", "dev")  # dev|prod|ci

    system = (
        "You are a senior platform engineer. Produce a production-quality "
        "docker-compose stack (Compose Spec 3.x compliant). Requirements: "
        "1) Every service has restart policy, healthcheck, resource limits, "
        "explicit user UID (non-root) where possible. "
        "2) Use named networks (not host) and named volumes (not bind-mounts) by default. "
        "3) Order dependencies with `depends_on: condition: service_healthy`. "
        "4) Centralise secrets via `.env` and `${VAR}` interpolation — never inline. "
        "5) For each custom app service, emit a multi-stage Dockerfile. "
        "6) Add a smoke-test runbook that proves end-to-end connectivity. "
        "Output ONLY valid JSON: "
        "{project_name:str, env_target:str, "
        "compose_yaml:str, "
        "service_inventory:[{name,image_or_build,role,exposes:[int],"
        "depends_on:[str],volumes:[str],env_keys:[str],healthcheck:str}], "
        "dockerfiles:[{filename,content,base_image,multi_stage:bool}], "
        "env_template:str, "
        "makefile_snippet:str, "
        "validation_runbook:[{step,command,expected,timeout_seconds}], "
        "mermaid_diagram:str, "
        "security_notes:[str], "
        "scale_up_path:str}."
    )
    prompt = (
        f"Project name: {project_name}\nEnv target: {env_target}\n"
        f"Include DB: {include_db}  Cache: {include_cache}  "
        f"Observability: {include_observability}\n\n"
        f"Description:\n{desc}\n\n"
        "Produce a stack that runs end-to-end with `docker compose up`. "
        "Be opinionated about image versions (pin tags, NEVER `:latest` in prod)."
    )

    data = _parse_json(_llm(prompt, system, "docker_compose_architect"), {
        "project_name": project_name, "env_target": env_target,
        "compose_yaml": "", "dockerfiles": [], "env_template": "",
    })

    ts = _ts()
    compose_path = _save("compose", f"{project_name}_docker-compose_{ts}.yml",
                         data.get("compose_yaml", "") or "")
    env_path     = _save("compose", f"{project_name}.env.template_{ts}",
                         data.get("env_template", "") or "")
    makefile_path = _save("compose", f"{project_name}_Makefile_{ts}",
                          data.get("makefile_snippet", "") or "")

    dockerfile_paths: List[str] = []
    for df in data.get("dockerfiles", []):
        fname = (df.get("filename") or f"Dockerfile_{ts}").replace("/", "_")
        dockerfile_paths.append(_save("compose", f"{project_name}_{fname}",
                                       df.get("content", "") or ""))

    diagram_path = _save("diagrams", f"{project_name}_compose_{ts}.mmd",
                         data.get("mermaid_diagram", "") or "graph LR\n  app[App]")

    runbook = data.get("validation_runbook", [])
    runbook_md = (
        f"# {project_name} — Compose Validation Runbook\n\n"
        + "\n".join(
            f"## Step {i+1}: {s.get('step','?')}\n"
            f"```bash\n{s.get('command','')}\n```\n"
            f"_Expected_: {s.get('expected','')}  "
            f"_Timeout_: {s.get('timeout_seconds','?')}s\n"
            for i, s in enumerate(runbook)
        )
    )
    runbook_path = _save("compose", f"{project_name}_runbook_{ts}.md", runbook_md)

    report = (
        f"# Docker Compose Architect — {project_name} ({env_target}) — {ts}\n\n"
        f"**Services:** {len(data.get('service_inventory',[]))}  "
        f"**Dockerfiles emitted:** {len(dockerfile_paths)}\n\n"
        "## Service Inventory\n"
        + "\n".join(
            f"- **`{s.get('name','?')}`** ({s.get('role','?')}) — "
            f"exposes {s.get('exposes',[])}, depends on {s.get('depends_on',[])}, "
            f"volumes {s.get('volumes',[])}"
            for s in data.get("service_inventory", [])
        )
        + "\n\n## Scale-up path\n" + (data.get("scale_up_path", "") or "")
        + "\n\n## Security notes\n"
        + "\n".join(f"- {n}" for n in data.get("security_notes", []))
        + f"\n\n## Artifacts\n- Compose: `{compose_path}`\n"
        f"- Env template: `{env_path}`\n"
        f"- Makefile: `{makefile_path}`\n"
        f"- Mermaid diagram: `{diagram_path}`\n"
        f"- Runbook: `{runbook_path}`"
    )
    report_path = _save("reports", f"docker_compose_architect_{ts}.md", report)

    _record("docker_compose_architect", project_name,
            f"services={len(data.get('service_inventory',[]))} env={env_target}")

    return {
        "project_name":        project_name,
        "env_target":          env_target,
        "compose_path":        compose_path,
        "compose_yaml":        data.get("compose_yaml", ""),
        "service_inventory":   data.get("service_inventory", []),
        "dockerfile_paths":    dockerfile_paths,
        "env_template_path":   env_path,
        "makefile_path":       makefile_path,
        "diagram_path":        diagram_path,
        "runbook_path":        runbook_path,
        "validation_runbook":  runbook,
        "security_notes":      data.get("security_notes", []),
        "scale_up_path":       data.get("scale_up_path", ""),
        "report_path":         report_path,
        "summary": (
            f"Compose stack `{project_name}` ({env_target}): "
            f"{len(data.get('service_inventory',[]))} services, "
            f"{len(dockerfile_paths)} Dockerfiles. → {compose_path}."
        ),
    }
