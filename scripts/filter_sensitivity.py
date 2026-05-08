"""Aşama B filter sensitivity testi.

Tek tek filterları aç/kapat, ROI etkisini ölç. Sweet spot bul.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


def _build_manifest(filters_overrides: dict, max_score: float = 0.0):
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "classic_pa_test",
        "version": "1.0",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_pin_bar", "enabled": True, "weight": 1.5, "params": {"body_to_range_max": 0.33, "lower_wick_to_range_min": 0.6, "upper_wick_to_range_max": 0.15}},
                {"id": "bearish_pin_bar", "enabled": True, "weight": 1.5, "params": {"body_to_range_max": 0.33, "upper_wick_to_range_min": 0.6, "lower_wick_to_range_max": 0.15}},
                {"id": "bullish_engulfing", "enabled": True, "weight": 1.5, "params": {"prev_body_min_range_pct": 0.15}},
                {"id": "bearish_engulfing", "enabled": True, "weight": 1.5, "params": {"prev_body_min_range_pct": 0.15}},
                {"id": "inside_bar_breakout", "enabled": True, "weight": 0.8, "params": {"confirm_with_close": True}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 120, "cluster_atr_multiplier": 0.5, "min_touches": 2, "max_age_bars": 120},
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {"atr_min_pct": 0.005, "volume_zscore_min": 0.0, **filters_overrides},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5, "max_score": max_score},
        },
        "risk": {
            "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 2.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


def run_one(label: str, filters_overrides: dict, max_score: float = 0.0):
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.classic_pa import ClassicPriceActionStrategy
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = _build_manifest(filters_overrides, max_score=max_score)
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]
    total_trades = 0
    total_wins = 0
    total_pnl_pct = 0.0
    sharpes = []
    dds = []
    for sym in symbols:
        df = _load_symbol_ohlcv(sym, tf="1d")
        s = ClassicPriceActionStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        n = int(r.kpis.get("n_trades", 0))
        win_rate = float(r.kpis.get("win_rate", 0.0))
        sharpe = float(r.kpis.get("sharpe", 0.0))
        dd = float(r.kpis.get("max_drawdown", 0.0))
        end_eq = float(r.equity_curve.iloc[-1])
        total_trades += n
        total_wins += int(round(n * win_rate))
        total_pnl_pct += (end_eq / 10000 - 1)
        sharpes.append(sharpe)
        dds.append(dd)
    avg_sharpe = sum(sharpes) / len(sharpes)
    avg_dd = sum(dds) / len(dds)
    avg_win = total_wins / max(1, total_trades)
    avg_return_3y = total_pnl_pct / len(symbols)
    annual = ((1 + avg_return_3y) ** (1/3) - 1) * 100
    print(f"  {label:<40} trades={total_trades:>4} win={avg_win*100:>5.1f}% Sharpe={avg_sharpe:>5.2f} DD={avg_dd*100:>5.1f}% 3yReturn={avg_return_3y*100:>+6.1f}% yıllık={annual:>+5.2f}%")


def main():
    print("=== Aşama B Filter Sensitivity (10 sembol, 3y, equal-weight) ===\n")
    print(f"  {'senaryo':<40} {'trades':>6} {'winrt':>6} {'Sharpe':>6} {'DD':>6} {'3yReturn':>8} {'yıllık':>6}")
    print("-" * 100)

    # Baseline — no Phase B filters
    run_one("BASELINE (no Phase B)", {})

    # Each filter alone
    run_one("ER >= 0.20 only", {"kaufman_er_min": 0.20, "kaufman_er_period": 14})
    run_one("ER >= 0.30 only", {"kaufman_er_min": 0.30, "kaufman_er_period": 14})
    run_one("Always-in only", {"always_in_required": True, "always_in_n_confirm": 3})
    run_one("Rolling Sharpe>=0 only", {"rolling_sharpe_min": 0.0, "rolling_sharpe_period": 60})
    run_one("Bear regime (200-EMA) only", {"bear_regime_size_factor": 0.5})
    run_one("Confluence cap=2.5 only", {}, max_score=2.5)
    run_one("Confluence cap=2.0 only", {}, max_score=2.0)

    # Combinations
    print("--- Kombinasyonlar ---")
    run_one("ER>=0.20 + Bear200", {"kaufman_er_min": 0.20, "bear_regime_size_factor": 0.5})
    run_one("ER>=0.20 + Confluence cap 2.5", {"kaufman_er_min": 0.20}, max_score=2.5)
    run_one("ER>=0.20 + RolSharpe + Conf cap 2.5", {"kaufman_er_min": 0.20, "rolling_sharpe_min": 0.0, "rolling_sharpe_period": 60}, max_score=2.5)
    run_one("FULL (all on, conf cap 2.5)", {
        "kaufman_er_min": 0.30, "always_in_required": True,
        "rolling_sharpe_min": 0.0, "bear_regime_size_factor": 0.5,
    }, max_score=2.5)


if __name__ == "__main__":
    main()
