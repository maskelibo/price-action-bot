"""Token budget monitoring — Faz 4.2.

Prometheus counter `pa_llm_tokens_total{agent, model, type}` zaten
`base.py` `run_full()` içinde inc ediliyor. Bu modül:

- per-agent + per-model günlük/haftalık summarize
- `configs/token_budget.yaml` per-agent limit kontrolü
- Limit aşımı → OpsAgent CRIT alarm
- Haftalık rapor: `reports/ops/token-YYYY-WW.md`

Public API
----------
get_token_stats(window_hours=24) -> dict
    Prometheus registry'den son N saat per-agent/model token kullanımı.

check_budget(stats, budget_config) -> list[dict]
    Limit aşan agent'lar liste (alarm için).

build_weekly_report(stats, budget_config) -> str
    Markdown rapor body (write_protocol_doc'a body olarak verilir).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from price_action.logging_config import logger
from price_action.settings import get_settings


# Model fiyatlandırma (input + output per 1M token, USD) — kabaca
# Faz 4'te güncellenebilir; Max Pro kullanımında bu rakamlar referans amaçlı.
MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Default fallback
    "_default": {"input": 5.0, "output": 25.0},
}


def get_token_stats(window_hours: int = 24) -> dict[str, dict[str, Any]]:
    """Prometheus counter'dan per-agent + per-model token usage.

    Prometheus client_python default registry'i tarar. Counter cumulative
    olduğu için window_hours rate'i yaklaşık olarak hesaplanır
    (ProcessInstanceLifetime metric'i ile).

    Returns
    -------
    dict
        ``{(agent, model): {input: N, output: M, calls: K, cost_usd: X}}``
    """
    stats: dict[tuple[str, str], dict[str, Any]] = {}

    try:
        from prometheus_client import REGISTRY  # type: ignore[import-not-found]

        for collector in REGISTRY._collector_to_names.keys():  # type: ignore[attr-defined]
            try:
                metrics = collector.collect()
            except Exception:
                continue
            for metric in metrics:
                if metric.name != "pa_llm_tokens":
                    continue
                for sample in metric.samples:
                    if sample.name != "pa_llm_tokens_total":
                        continue
                    labels = sample.labels
                    agent = labels.get("agent", "?")
                    model = labels.get("model", "?")
                    tok_type = labels.get("type", "?")
                    key = (agent, model)
                    if key not in stats:
                        stats[key] = {"input": 0, "output": 0, "calls": 0, "cost_usd": 0.0}
                    stats[key][tok_type] = int(sample.value)

                if metric.name == "pa_llm_calls":
                    for sample in metric.samples:
                        if sample.name != "pa_llm_calls_total":
                            continue
                        labels = sample.labels
                        if labels.get("status") != "ok":
                            continue
                        agent = labels.get("agent", "?")
                        model = labels.get("model", "?")
                        key = (agent, model)
                        if key not in stats:
                            stats[key] = {"input": 0, "output": 0, "calls": 0, "cost_usd": 0.0}
                        stats[key]["calls"] = int(sample.value)
    except Exception as exc:
        logger.warning("token_budget.prometheus_unavailable", extra={"err": str(exc)[:200]})

    # Compute cost
    for key, s in stats.items():
        _agent, model = key
        pricing = MODEL_PRICING_USD_PER_1M.get(model, MODEL_PRICING_USD_PER_1M["_default"])
        s["cost_usd"] = round(
            s["input"] / 1_000_000 * pricing["input"]
            + s["output"] / 1_000_000 * pricing["output"],
            4,
        )

    # Convert tuple keys to string for serialization
    return {f"{k[0]}|{k[1]}": v for k, v in stats.items()}


def load_budget_config(path: Path | None = None) -> dict[str, Any]:
    """Load `configs/token_budget.yaml` (yoksa default budget)."""
    if path is None:
        s = get_settings()
        path = s.reports_dir.parent / "configs" / "token_budget.yaml"
    if not path.exists():
        logger.info("token_budget.config_missing", extra={"path": str(path)})
        return _default_budget()
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or _default_budget()
    except Exception as exc:
        logger.warning("token_budget.config_parse_fail", extra={"err": str(exc)[:200]})
        return _default_budget()


def _default_budget() -> dict[str, Any]:
    """Max Pro plan altında makul daily limits (per-agent input+output token)."""
    return {
        "daily_limits": {
            "ceo": 50_000,
            "researcher": 100_000,
            "lab_scientist": 80_000,
            "analyst": 60_000,
            "risk_officer": 40_000,
            "ops_engineer": 20_000,
            "portfolio_manager": 0,  # deterministic — LLM use yok
            "signal_chief": 0,
            "execution_chief": 0,
            "data_engineer": 5_000,
        },
        "weekly_limit_total": 3_000_000,  # 3M token / hafta total
        "alert_threshold_pct": 80,  # %80 reach → WARN
    }


def check_budget(
    stats: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Limit aşan agent'lar listesi.

    Returns
    -------
    list[dict]
        ``[{agent, model, used, limit, pct, level}, ...]``
    """
    alerts: list[dict[str, Any]] = []
    limits = config.get("daily_limits", {})
    alert_pct = config.get("alert_threshold_pct", 80)

    # Per-agent toplam (her model'i topla)
    per_agent: dict[str, int] = {}
    for key, s in stats.items():
        agent = key.split("|", 1)[0]
        per_agent.setdefault(agent, 0)
        per_agent[agent] += s["input"] + s["output"]

    for agent, used in per_agent.items():
        limit = limits.get(agent, 0)
        if limit == 0:
            continue  # Deterministic agent — limit yok
        pct = used / limit * 100
        if pct >= alert_pct:
            level = "CRIT" if pct >= 100 else "WARN"
            alerts.append({
                "agent": agent,
                "used": used,
                "limit": limit,
                "pct": round(pct, 1),
                "level": level,
            })
    return alerts


def build_weekly_report(
    stats: dict[str, dict[str, Any]],
    config: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> str:
    """Markdown body — write_protocol_doc'a verilir."""
    iso = datetime.now(timezone.utc).isocalendar()
    week_label = f"{iso.year}-W{iso.week:02d}"

    total_input = sum(s["input"] for s in stats.values())
    total_output = sum(s["output"] for s in stats.values())
    total_calls = sum(s["calls"] for s in stats.values())
    total_cost = sum(s["cost_usd"] for s in stats.values())

    body = [
        f"# Token Budget Report — Week {week_label}",
        "",
        "## Genel Özet",
        f"- Toplam input token: {total_input:,}",
        f"- Toplam output token: {total_output:,}",
        f"- Toplam LLM çağrı: {total_calls:,}",
        f"- Toplam maliyet (kabaca, USD): ${total_cost:.2f}",
        "",
        "## Per-Agent + Per-Model",
        "",
        "| Agent | Model | Input | Output | Calls | Cost USD |",
        "|---|---|---|---|---|---|",
    ]
    for key in sorted(stats.keys()):
        s = stats[key]
        agent, model = key.split("|", 1)
        body.append(
            f"| {agent} | {model} | {s['input']:,} | {s['output']:,} | {s['calls']:,} | ${s['cost_usd']:.4f} |"
        )
    body.append("")

    body.append("## Bütçe Durumu")
    body.append("")
    if alerts:
        body.append("⚠️ **Limit aşımı tespit edildi:**")
        body.append("")
        body.append("| Agent | Used | Limit | % | Level |")
        body.append("|---|---|---|---|---|")
        for a in alerts:
            body.append(f"| {a['agent']} | {a['used']:,} | {a['limit']:,} | {a['pct']}% | **{a['level']}** |")
    else:
        body.append("✅ Hiçbir agent günlük limitin %80'ini aşmadı.")
    body.append("")

    body.append("## Notlar")
    body.append("")
    body.append(f"- Bütçe config: `configs/token_budget.yaml` (alert eşiği {config.get('alert_threshold_pct', 80)}%)")
    body.append("- Max Pro plan altında bu rakamlar referans amaçlı (gerçek faturalama Anthropic dashboard'unda)")
    body.append("- Prometheus counter cumulative — daily breakdown yapılmadı (process restart'ta sıfırlanır)")

    return "\n".join(body)
