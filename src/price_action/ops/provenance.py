"""Provenance banner — her daemon/agent ne yüklediğini açıkça beyan eder.

FIX 2026-05-26 (Faz 14.1): Önceden config dosyası adı + içerik gizli
kalıyordu (sadece kod biliyordu). Daemon yanlış config ile başlatılırsa
fark edilmesi günler alıyordu (örn. c2v5 yerine widestop_vsa2 olması
gerekirken c2v5 çalıştı).

Bu modül:
- config dosyası SHA256 + key params parse + format
- Daemon startup'ta log'a + Telegram'a (opsiyonel) yazılır
- Daily Truth Report bu provenance'a bakar
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml


def _sha256(path: Path) -> str:
    """Dosyanın SHA256 hash'i (kısa form, ilk 16 char)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return "UNREADABLE"


def config_provenance(config_path: Path | str) -> dict[str, Any]:
    """Config dosyasını parse et + key risk params + hash döndür.

    Returns dict:
        path, name, sha256_short, exists, risk_per_trade, sl_pct_min,
        leverage_max, pyramid_enabled, expected_monthly_pct, header_summary
    """
    p = Path(config_path)
    out: dict[str, Any] = {
        "path": str(p),
        "name": p.name,
        "exists": p.exists(),
    }
    if not p.exists():
        out["sha256_short"] = "MISSING"
        return out

    out["sha256_short"] = _sha256(p)

    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        out["parse_error"] = str(exc)[:200]
        return out

    # Key risk params (path'ler değişebilir, defansif get)
    pos_sizing = cfg.get("position_sizing", {}) or {}
    exec_cfg = cfg.get("execution", {}) or {}
    portfolio = cfg.get("strategy_portfolio", {}) or {}
    leverage_cfg = cfg.get("leverage", {}) or {}
    breakers = cfg.get("drawdown_breakers", {}) or {}

    out.update({
        "risk_per_trade": pos_sizing.get("risk_per_trade"),
        "backtest_risk_pct": pos_sizing.get("backtest_risk_pct"),
        "sl_pct_min": exec_cfg.get("sl_pct_min", 0.0),
        "leverage_max": leverage_cfg.get("max_leverage_per_symbol"),
        "pyramid_enabled": portfolio.get("pyramid_enabled", False),
        "daily_loss_pct": breakers.get("daily_loss_pct"),
        "weekly_loss_pct": breakers.get("weekly_loss_pct"),
        "expected_annual_return": cfg.get("expected_annual_return"),
        "preset_name": exec_cfg.get("preset_name") or pos_sizing.get("preset_name"),
    })

    # Header yorumundan backtest özeti çıkar (ilk 80 satır)
    try:
        head = p.read_text(encoding="utf-8").splitlines()[:80]
        summary_lines = []
        for line in head:
            stripped = line.strip("# ").rstrip()
            # Backtest sonuçlarını yakala (Annual, Mean, Negatif gibi anahtarlar)
            for kw in ("Annual:", "annual ", "Aylık", "aylik", "Negatif",
                       "Negative", "Mean M:", "DD ", "negative months"):
                if kw in stripped and len(summary_lines) < 5:
                    summary_lines.append(stripped[:120])
                    break
        out["backtest_summary"] = summary_lines
    except Exception:
        out["backtest_summary"] = []

    return out


def format_banner(provenance: dict[str, Any], *, component: str) -> str:
    """Provenance dict'ini insan-okunur banner string'e dönüştürür."""
    lines = [
        "============================================================",
        f"  {component} CONFIG PROVENANCE",
        "============================================================",
        f"  Config:           {provenance.get('name', '?')}",
        f"  SHA256 (short):   {provenance.get('sha256_short', '?')}",
        f"  Path:             {provenance.get('path', '?')}",
    ]
    if not provenance.get("exists"):
        lines.append("  ⚠️  DOSYA YOK — daemon SAFE mode'a düşer!")
        lines.append("============================================================")
        return "\n".join(lines)

    if provenance.get("parse_error"):
        lines.append(f"  ⚠️  PARSE ERROR: {provenance['parse_error']}")

    if provenance.get("preset_name"):
        lines.append(f"  Preset:           {provenance['preset_name']}")
    if provenance.get("risk_per_trade") is not None:
        lines.append(f"  risk_per_trade:   {provenance['risk_per_trade']}")
    if provenance.get("sl_pct_min") is not None:
        # FIX 2026-05-28 (audit-Y2): banner threshold _thresholds.py'den.
        from price_action._thresholds import WIDESTOP_SL_PCT_DEFAULT
        wide = (
            "✅ WIDESTOP AKTİF"
            if float(provenance["sl_pct_min"] or 0) >= WIDESTOP_SL_PCT_DEFAULT
            else "❌ widestop yok"
        )
        lines.append(f"  sl_pct_min:       {provenance['sl_pct_min']}  ({wide})")
    if provenance.get("leverage_max") is not None:
        lines.append(f"  leverage_max:     {provenance['leverage_max']}x")
    if provenance.get("pyramid_enabled") is not None:
        lines.append(f"  pyramid:          {'AÇIK' if provenance['pyramid_enabled'] else 'KAPALI'}")
    if provenance.get("daily_loss_pct") is not None:
        lines.append(f"  daily_breaker:    %{float(provenance['daily_loss_pct']) * 100:.2f}")
    if provenance.get("expected_annual_return") is not None:
        lines.append(f"  expected_annual:  %{float(provenance['expected_annual_return']) * 100:.1f}")
    if provenance.get("backtest_summary"):
        lines.append("  --- Backtest header summary ---")
        for s in provenance["backtest_summary"]:
            lines.append(f"    | {s[:80]}")
    lines.append("============================================================")
    return "\n".join(lines)


def env_config_for_15m() -> Path:
    """15m daemon hangi config'i yükleyecek (env override veya default)."""
    override = os.environ.get("PA_15M_CONFIG", "").strip()
    base = Path("/Users/peyman/price-action-bot")
    if override:
        p = Path(override)
        return p if p.is_absolute() else (base / p)
    return base / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"


def env_config_for_5m() -> Path:
    """5m daemon hangi config'i yükleyecek."""
    override = os.environ.get("PA_5M_CONFIG", "").strip()
    base = Path("/Users/peyman/price-action-bot")
    if override:
        p = Path(override)
        return p if p.is_absolute() else (base / p)
    return base / "configs" / "risk_phoenix_scalp_5m_p1c.yaml"
