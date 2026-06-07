"""
Database Migration Pilot — produce safe, reversible schema migrations
with backfills, rollback scripts, duration estimates, and a destructive-
operation gate.

Compares current vs. desired schemas (or interprets a plain-English
change), classifies operations by risk (additive, in-place rewrite,
destructive), and emits Alembic/Flyway/Liquibase scripts plus a
data-backfill plan and a production runbook.

Input:  db_engine (str), current_schema (str), desired_schema (str),
        change_description (str), migration_tool (str), env (str)
Output: migration_up_sql, migration_down_sql, backfill_script,
        risk_classification, destructive_ops, runbook, report_path
"""
from __future__ import annotations

from typing import Any, Dict

from src._helpers import _ts, _llm, _save, _parse_json, _record


_TOOL_FILE_EXT = {"alembic": "py", "flyway": "sql", "liquibase": "xml",
                  "raw_sql": "sql", "knex": "js", "prisma": "prisma"}


def db_migration_pilot(args: Dict[str, Any]) -> Dict[str, Any]:
    engine          = (args.get("db_engine") or "postgresql").lower()
    current_schema  = args.get("current_schema", "")
    desired_schema  = args.get("desired_schema", "")
    change_desc     = args.get("change_description", "")
    tool            = (args.get("migration_tool") or "alembic").lower()
    env             = args.get("env", "production")
    table_row_hints = args.get("table_row_hints", {})  # e.g. {"users": 5_000_000}

    system = (
        f"You are a database reliability engineer specialising in {engine} schema "
        "migrations. Your job is to keep production online. For every change you "
        "must: classify risk (additive / in_place_rewrite / destructive), choose a "
        "ZERO-DOWNTIME pattern (expand-and-contract, online DDL with pt-osc or "
        "gh-ost, batched backfill, dual-write), and ALWAYS emit a working "
        "rollback. Destructive ops (DROP, NOT NULL on populated col, type change "
        "with data loss) MUST be flagged with `requires_explicit_approval=true`. "
        "Output ONLY JSON: "
        f"{{db_engine:str, migration_tool:'{tool}', revision_id:str, "
        "operations:[{op,table,column,type,risk:'additive'|'in_place_rewrite'"
        "|'destructive',pattern,estimated_duration_seconds,locks_acquired:[str],"
        "requires_explicit_approval:bool}], "
        "migration_up:{filename,language,content}, "
        "migration_down:{filename,language,content}, "
        "backfill_script:{language,content,batch_size,estimated_runtime_minutes}, "
        "destructive_ops_requiring_approval:[str], "
        "preflight_checks:[str], "
        "production_runbook:[{step,command,verification,abort_if}], "
        "rollback_runbook:[{step,command,verification}], "
        "monitoring_to_add:[str], "
        "go_no_go_recommendation:{go:bool,reasoning}}."
    )
    prompt = (
        f"DB engine: {engine}\nMigration tool: {tool}\nEnv: {env}\n"
        f"Table row hints: {table_row_hints}\n\n"
        f"CURRENT SCHEMA:\n```sql\n{current_schema[:3500]}\n```\n\n"
        f"DESIRED SCHEMA:\n```sql\n{desired_schema[:3500]}\n```\n\n"
        f"PLAIN-ENGLISH CHANGE:\n{change_desc or '(use schema diff above)'}\n\n"
        "Prefer expand-and-contract. NEVER use ALTER TABLE that takes a long "
        "exclusive lock on large tables without an online DDL note."
    )

    data = _parse_json(_llm(prompt, system, "db_migration_pilot"), {
        "operations": [], "migration_up": {}, "migration_down": {},
        "backfill_script": {}, "production_runbook": [], "rollback_runbook": [],
    })

    ts = _ts()
    ext_up = _TOOL_FILE_EXT.get(tool, "sql")
    rev = (data.get("revision_id") or ts.replace("_", "")[:12])

    up_path   = _save("migrations", f"{rev}_up.{ext_up}",
                      data.get("migration_up", {}).get("content", "") or "")
    down_path = _save("migrations", f"{rev}_down.{ext_up}",
                      data.get("migration_down", {}).get("content", "") or "")
    backfill_path = ""
    bf = data.get("backfill_script", {})
    if bf.get("content"):
        bf_ext = "py" if bf.get("language", "python") == "python" else "sh"
        backfill_path = _save("migrations", f"{rev}_backfill.{bf_ext}", bf["content"])

    destructive = data.get("destructive_ops_requiring_approval", [])
    go = data.get("go_no_go_recommendation", {})

    report = (
        f"# DB Migration Pilot — {engine} / {tool} — {ts}\n\n"
        f"**Revision:** `{rev}`  **Env:** {env}  "
        f"**Operations:** {len(data.get('operations',[]))}  "
        f"**Destructive (approval required):** {len(destructive)}\n\n"
        f"## Go / No-Go: **{'GO' if go.get('go') else 'NO-GO'}**\n"
        f"{go.get('reasoning','')}\n\n"
        "## Operations\n"
        + "\n".join(
            f"- [{o.get('risk','?').upper()}] `{o.get('op','?')}` on "
            f"`{o.get('table','?')}` ({o.get('column','')}) "
            f"~{o.get('estimated_duration_seconds','?')}s "
            f"pattern: {o.get('pattern','?')}"
            + (" **APPROVAL REQUIRED**" if o.get("requires_explicit_approval") else "")
            for o in data.get("operations", [])
        )
        + "\n\n## Preflight checks\n"
        + "\n".join(f"- {c}" for c in data.get("preflight_checks", []))
        + "\n\n## Production runbook\n"
        + "\n".join(
            f"{i+1}. **{s.get('step','?')}**\n   `{s.get('command','')}`\n"
            f"   _Verify_: {s.get('verification','')}  "
            f"_Abort if_: {s.get('abort_if','')}"
            for i, s in enumerate(data.get("production_runbook", []))
        )
        + "\n\n## Rollback runbook\n"
        + "\n".join(
            f"{i+1}. {s.get('step','?')} — `{s.get('command','')}`"
            for i, s in enumerate(data.get("rollback_runbook", []))
        )
        + "\n\n## Monitoring to add\n"
        + "\n".join(f"- {m}" for m in data.get("monitoring_to_add", []))
        + f"\n\n## Files\n- Up: `{up_path}`\n- Down: `{down_path}`"
        + (f"\n- Backfill: `{backfill_path}`" if backfill_path else "")
    )
    report_path = _save("reports", f"db_migration_pilot_{ts}.md", report)

    _record("db_migration_pilot", f"{engine}/{tool}",
            f"rev={rev} destr={len(destructive)} go={go.get('go')}")

    return {
        "db_engine":              engine,
        "migration_tool":         tool,
        "revision_id":            rev,
        "operations":             data.get("operations", []),
        "migration_up_path":      up_path,
        "migration_down_path":    down_path,
        "backfill_script_path":   backfill_path,
        "destructive_ops":        destructive,
        "preflight_checks":       data.get("preflight_checks", []),
        "production_runbook":     data.get("production_runbook", []),
        "rollback_runbook":       data.get("rollback_runbook", []),
        "monitoring_to_add":      data.get("monitoring_to_add", []),
        "go_no_go":               go,
        "report_path":            report_path,
        "summary": (
            f"DB migration `{rev}` for {engine}/{tool}: "
            f"{len(data.get('operations',[]))} ops, "
            f"{len(destructive)} destructive. "
            f"Go={go.get('go')}. → {report_path}."
        ),
    }
