"""RiskOfficer canlı entegrasyon smoke testi (emir GÖNDERMEZ).

Gerçek futures testnet hesap state + gerçek market data + sahte sinyaller →
RiskOfficer.evaluate() kararlarını logla. Reject reason'ları görmek için.

Kullanım:
    python scripts/test_risk_integration.py
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from scripts.futures_trade_daily import get_futures_exchange, fetch_futures_state
from scripts.lib.risk_integration import (
    build_futures_account_state,
    build_returns_df,
    build_signal_from_scan,
    load_risk_officer,
)


def _build_mock_signal(symbol: str, side: str, sl_pct: float = 0.03, tp_pct: float = 0.045) -> dict:
    """Bir test sinyali üret."""
    return {
        "ts": datetime.now(timezone.utc) - timedelta(days=1),
        "symbol": symbol,
        "strategy": "smoke_test",
        "side": side,
        "entry_price": 0,
        "sl_price": 100.0,  # geçersiz; market_price ile gerçek hesaplama scripte göre
        "tp_price": 100.0,
        "confluence": 0.55,
        "signal_obj": None,
    }


def main():
    print("=" * 70)
    print("RISK OFFICER LIVE INTEGRATION SMOKE TEST")
    print("=" * 70)

    risk_yaml = ROOT / "configs" / "risk_balanced.yaml"
    breaker_path = ROOT / "logs" / "risk" / "smoke_breaker_state.json"
    breaker_path.parent.mkdir(parents=True, exist_ok=True)
    if breaker_path.exists():
        breaker_path.unlink()  # temiz başla

    print(f"\n[1/4] Loading RiskOfficer from {risk_yaml.name}...")
    ro = load_risk_officer(yaml_path=risk_yaml, breaker_state_path=breaker_path)
    print(f"  ✓ max_open={ro.config.concentration_limits.get('max_open_positions')}, "
          f"max_per_sym={ro.config.concentration_limits.get('max_per_symbol_pct')}, "
          f"daily_dd={ro.config.drawdown_breakers.get('daily_loss_pct')}, "
          f"risk_per_trade={ro.config.position_sizing.get('risk_per_trade')}")

    print(f"\n[2/4] Fetching live futures account state...")
    try:
        ex = get_futures_exchange()
        state = fetch_futures_state(ex)
        print(f"  ✓ wallet=${state['wallet_balance']:.2f}, "
              f"available=${state['available_balance']:.2f}, "
              f"pos={state['n_positions']}, orders={state['n_open_orders']}")
    except Exception as e:
        print(f"  ✗ FAIL: {type(e).__name__}: {e}")
        return 1

    print(f"\n[3/4] Building AccountState + returns_df...")
    journal = ROOT / "data" / "futures_journal.duckdb"
    account = build_futures_account_state(state, journal_path=journal)
    syms = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT",
            "AVAX/USDT","LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
    open_syms = [p.symbol for p in account.open_positions]
    print(f"  ✓ equity=${account.equity_usdt:.2f}, "
          f"free=${account.free_margin_usdt:.2f}, "
          f"open_pos={len(account.open_positions)} ({open_syms}), "
          f"pnl_today=${account.realized_pnl_today:+.2f}")
    rets = build_returns_df(syms, days=90)
    print(f"  ✓ returns_df: shape={rets.shape}, last_date={rets.index[-1] if not rets.empty else None}")

    print(f"\n[4/4] Test signals through RiskOfficer.evaluate()...")
    test_cases = [
        ("BTC/USDT", "long",  0.30, "BTC long — normal"),
        ("BTC/USDT", "short", 0.30, "BTC short — F&G fear günü olabilir"),
        ("ETH/USDT", "long",  0.30, "ETH long — normal"),
        ("DOGE/USDT", "short", 0.30, "DOGE short — extreme fear günleri"),
        ("XRP/USDT", "long",  0.05, "XRP long — VERY tight SL (%5 of price)"),
        ("BTC/USDT", "long",  10.0, "BTC long — absurd wide SL (%1000)"),
    ]

    n_pass = 0
    n_reject = 0
    for sym, side, sl_pct_of_px, label in test_cases:
        try:
            ticker = ex.fetch_ticker(sym)
            cur_px = float(ticker["last"])
        except Exception as e:
            print(f"  [{sym}] ticker fail: {e}")
            continue

        if side == "long":
            sl = cur_px * (1 - sl_pct_of_px)
            tp = cur_px * (1 + sl_pct_of_px * 1.5)
        else:
            sl = cur_px * (1 + sl_pct_of_px)
            tp = cur_px * (1 - sl_pct_of_px * 1.5)

        s = {
            "ts": datetime.now(timezone.utc) - timedelta(days=1),
            "symbol": sym,
            "strategy": "smoke_test",
            "side": side,
            "entry_price": 0,
            "sl_price": sl,
            "tp_price": tp,
            "confluence": 0.55,
            "signal_obj": None,
        }
        sig = build_signal_from_scan(s, venue="binance")
        decision = ro.evaluate(sig, account, market_price=cur_px, returns_df=rets)

        if hasattr(decision, "quantity"):
            n_pass += 1
            print(f"  [✓ ACCEPT] {sym:<10} {side:<5} px=${cur_px:.2f} sl=${sl:.2f} → "
                  f"qty={decision.quantity:.6f} notional=${decision.notional_usdt:.2f} "
                  f"lev={decision.leverage:.1f}x corr={decision.correlation_factor:.2f}  ({label})")
        else:
            n_reject += 1
            reason = getattr(decision, "reason", "?")
            detail = getattr(decision, "detail", {}) or {}
            print(f"  [✗ REJECT] {sym:<10} {side:<5} sl_pct={sl_pct_of_px*100:.1f}% → "
                  f"{reason} {detail}  ({label})")

    print(f"\n{'=' * 70}")
    print(f"RESULT: {n_pass} accept, {n_reject} reject (out of {len(test_cases)} tests)")
    print(f"NOT: hiçbir emir gönderilmedi — sadece RiskOfficer kararları test edildi.")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
