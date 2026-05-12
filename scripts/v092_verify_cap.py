"""v0.9.2 sanity: notional cap %30 uygulaniyor mu?

RiskOfficer.evaluate'ı iki kez calistirir:
  1. cap aktif (production risk.yaml) — wide SL trade'de notional/equity = 0.30 olmali
  2. cap pasif (override) — wide SL trade'de notional/equity > 0.30 cikar
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.contracts import Signal
from price_action.risk.sizing import AccountState, RiskOfficer


def make_signal(entry: float, sl: float, side: str = "long"):
    """Wide SL, low conf — notional buyuk olmali (cap olmadan)."""
    import datetime as _dt
    return Signal(
        ts=_dt.datetime.now(_dt.timezone.utc),
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction=side,
        pattern_id="test",
        confluence_score=2.0,
        sl_price=sl,
        tp_price=entry + (entry - sl) * 2 if side == "long" else entry - (sl - entry) * 2,
        suggested_size_atr=1.0,
        metadata={"entry_price": entry},
    )


def main():
    risk_yaml = ROOT / "configs" / "risk.yaml"

    # === Senaryo 1: production config (cap 0.30 aktif) ===
    print("=" * 80)
    print("SENARYO 1 — v0.9.2 production (cap 0.30 aktif)")
    print("=" * 80)
    ro = RiskOfficer.from_yaml(risk_yaml)
    ro.config.position_sizing["method"] = "fixed_fractional"
    ro.config.position_sizing["risk_per_trade"] = 0.030
    # confidence_dynamic conf dusukse %1 oluyor, ben %3 sabit istiyorum testte
    ro.config.position_sizing.pop("confidence_risk_tiers", None)
    print(f"  max_notional_pct_equity: {ro.config.position_sizing.get('max_notional_pct_equity')}")

    state = AccountState(equity_usdt=10_000.0, free_margin_usdt=10_000.0)
    # Wide SL: %15 — cap olmadan notional = 0.03 * 10000 / 0.15 = $2,000 (cap altinda)
    # Tight SL: %1 — cap olmadan notional = 0.03 * 10000 / 0.01 = $30,000 (cap USTUNDE!)
    print("\n  Test A: Wide SL %15 (cap'e takilmamali)")
    sig_a = make_signal(entry=100.0, sl=85.0)
    r = ro.evaluate(sig_a, state, market_price=100.0)
    cls = type(r).__name__
    if cls == "RiskedOrder":
        nr = r.notional_usdt / state.equity_usdt
        print(f"    -> kabul: notional ${r.notional_usdt:,.0f} / eq ${state.equity_usdt:,.0f} = {nr:.2%}")
    else:
        print(f"    -> reject: {r.reason}")

    print("\n  Test B: Tight SL %1 (cap'e takilmali, notional 0.30 olmali)")
    sig_b = make_signal(entry=100.0, sl=99.0)
    r = ro.evaluate(sig_b, state, market_price=100.0)
    cls = type(r).__name__
    if cls == "RiskedOrder":
        nr = r.notional_usdt / state.equity_usdt
        print(f"    -> kabul: notional ${r.notional_usdt:,.0f} / eq ${state.equity_usdt:,.0f} = {nr:.2%}")
        if abs(nr - 0.30) < 0.001:
            print(f"    OK CAP CALISIYOR (notional/equity = {nr:.2%})")
        else:
            print(f"    HATA CAP BEKLENMIYORDU veya yanlis hesap")
    else:
        print(f"    -> reject: {r.reason}")

    # === Senaryo 2: cap kapali (override) ===
    print()
    print("=" * 80)
    print("SENARYO 2 — cap kapali (override max_notional_pct_equity = 0)")
    print("=" * 80)
    ro2 = RiskOfficer.from_yaml(risk_yaml)
    ro2.config.position_sizing["method"] = "fixed_fractional"
    ro2.config.position_sizing["risk_per_trade"] = 0.030
    ro2.config.position_sizing.pop("confidence_risk_tiers", None)
    ro2.config.position_sizing["max_notional_pct_equity"] = 0.0  # cap kapali
    # Leverage gate bunu max 5x x equity = $50,000'ya kadar izin verir.

    print("\n  Test B (cap kapali): Tight SL %1 — notional 3.0x equity beklenir")
    r = ro2.evaluate(sig_b, state, market_price=100.0)
    cls = type(r).__name__
    if cls == "RiskedOrder":
        nr = r.notional_usdt / state.equity_usdt
        print(f"    -> kabul: notional ${r.notional_usdt:,.0f} / eq ${state.equity_usdt:,.0f} = {nr:.2%}")
        if nr > 0.30:
            print(f"    OK CAP YOK (notional/equity = {nr:.2%}, 30%'den buyuk)")
    else:
        print(f"    -> reject: {r.reason}")


if __name__ == "__main__":
    main()
