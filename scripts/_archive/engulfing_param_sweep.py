"""Engulfing Continuation — Parameter Sweep (López AFML yaklaşımı).

Amaç: 50 Halton-sequence örnekli parametre kombinasyonu ile train/test
      split (70/30 kronolojik) üzerinde DSR tabanlı OOS sağlamlık testi.

Sweep parametreleri:
  kaufman_er_min      : [0.15, 0.20, 0.25, 0.30]
  body_engulf_ratio   : [0.5, 0.6, 0.7]
  atr_proximity_to_sr : [0.3, 0.5, 0.7]
  pullback_window     : [10, 15, 20]
  bear_regime_factor  : [0.5, 1.0]

López protokolü:
  - Train: ilk %70 veri
  - Test : son %30 veri (OOS)
  - Metric: Sharpe + DSR (n_trials=50, Bonferroni p < 0.001)
  - Karar: DSR > 0.5 olan tek set varsa PROMOTE, yoksa KEEP DEFAULTS

Çalıştırma:
    PYTHONPATH=src python scripts/engulfing_param_sweep.py

    --symbols BTC/USDT ETH/USDT   (DuckDB veri yoksa sentetik kullanır)
    --n-samples 50                  (Halton örnek sayısı)
    --dsr-threshold 0.5
    --no-db                         (DB olmadan sentetik veri ile çalıştır)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Sabitler & Default parametreler
# =====================================================================

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

INITIAL_CAPITAL = 10_000.0
TRAIN_RATIO = 0.70
N_TRIALS = 50          # Halton örnekleri
DSR_THRESHOLD = 0.5    # López onay eşiği
BONFERRONI_ALPHA = 0.05 / N_TRIALS  # ~0.001

# Production defaults
DEFAULTS = {
    "kaufman_er_min": 0.20,
    "body_engulf_ratio": 0.60,
    "atr_proximity_to_sr": 0.50,
    "pullback_window": 10,
    "bear_regime_factor": 0.50,
}

# Param grid boundaries (low, high, is_discrete)
PARAM_GRID = {
    "kaufman_er_min":      (0.15, 0.30, False),
    "body_engulf_ratio":   (0.50, 0.70, False),
    "atr_proximity_to_sr": (0.30, 0.70, False),
    "pullback_window":     (10,   20,   True),
    "bear_regime_factor":  (0.50, 1.00, False),
}


# =====================================================================
# Halton sequence sampler (quasi-random, daha iyi coverage)
# =====================================================================

def _halton_sequence(n: int, base: int) -> list[float]:
    """n adet Halton sayısı üret (base ile)."""
    seq: list[float] = []
    for i in range(1, n + 1):
        f, r = 1.0, 0.0
        k = i
        while k > 0:
            f /= base
            r += f * (k % base)
            k //= base
        seq.append(r)
    return seq


PRIMES = [2, 3, 5, 7, 11]  # 5 boyut için 5 asal sayı


def halton_samples(n: int, param_grid: dict) -> list[dict]:
    """Halton quasi-random örnekleme — her parametre için ayrı baz."""
    keys = list(param_grid.keys())
    assert len(keys) <= len(PRIMES), "PRIMES listesi yeterli değil"

    seqs = {k: _halton_sequence(n, PRIMES[i]) for i, k in enumerate(keys)}
    samples: list[dict] = []
    for j in range(n):
        combo: dict[str, Any] = {}
        for k in keys:
            lo, hi, discrete = param_grid[k]
            val = lo + seqs[k][j] * (hi - lo)
            if discrete:
                # En yakın integer'a yuvarlama — grid değerleri: 10, 15, 20
                # Basit yaklaşım: grid adımı = (hi-lo)/(n_vals-1)
                n_vals = int((hi - lo) / 5) + 1  # pullback_window için 3 değer
                steps = [lo + s * (hi - lo) / (n_vals - 1) for s in range(n_vals)]
                val = min(steps, key=lambda x: abs(x - val))
                val = int(round(val))
            combo[k] = val
        samples.append(combo)
    return samples


# =====================================================================
# Veri yükleme
# =====================================================================

def _load_from_db(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    """DuckDB'den OHLCV oku."""
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return pd.DataFrame()
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            [venue, symbol, tf],
        ).fetchdf()
        con.close()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["symbol"] = symbol
        df["timeframe"] = tf
        df["venue"] = venue
        return df
    except Exception as exc:
        print(f"  [DB WARN] {symbol}: {exc}")
        return pd.DataFrame()


def _generate_synthetic(
    symbol: str = "SYN/USDT",
    n: int = 800,
    seed: int = 42,
    drift: float = 0.0005,
) -> pd.DataFrame:
    """Sentetik OHLCV — seed ile deterministik."""
    rng = np.random.default_rng(seed)
    from datetime import timedelta
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    ts = [start + timedelta(days=i) for i in range(n)]
    rets = rng.normal(drift, 0.02, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    vol = rng.uniform(500_000, 5_000_000, n)
    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
        "symbol": symbol, "timeframe": "1d", "venue": "binance",
    })


def _load_ohlcv(symbol: str, use_db: bool = True) -> pd.DataFrame:
    """DB'yi dene, yoksa sentetik üret."""
    if use_db:
        df = _load_from_db(symbol)
        if not df.empty and len(df) >= 200:
            return df
    # Fallback: deterministik sentetik
    seed_map = {s: i * 13 + 7 for i, s in enumerate(SYMBOLS)}
    seed = seed_map.get(symbol, 42)
    df = _generate_synthetic(symbol, n=900, seed=seed)
    return df


# =====================================================================
# Manifest fabrikası
# =====================================================================

def _make_manifest(params: dict):
    """Param dict → StrategyManifest."""
    from price_action.strategies.base import StrategyManifest

    er_min = float(params.get("kaufman_er_min", DEFAULTS["kaufman_er_min"]))
    body_ratio = float(params.get("body_engulf_ratio", DEFAULTS["body_engulf_ratio"]))
    proximity = float(params.get("atr_proximity_to_sr", DEFAULTS["atr_proximity_to_sr"]))
    pb_window = int(params.get("pullback_window", DEFAULTS["pullback_window"]))
    bear_factor = float(params.get("bear_regime_factor", DEFAULTS["bear_regime_factor"]))

    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": body_ratio,
                        "pullback_window": pb_window,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": body_ratio,
                        "pullback_window": pb_window,
                        "pullback_touch_atr": 0.5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 120,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 120,
                },
                "require_proximity_to_sr_atr": proximity,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": er_min,
                "bear_regime_size_factor": bear_factor,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.5,
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Tek backtest koşusu
# =====================================================================

def _run_backtest(df: pd.DataFrame, params: dict) -> dict:
    """Hazır df üzerinde EngulfingContinuationStrategy koştur."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

    if df.empty or len(df) < 100:
        return {"sharpe": 0.0, "n_trades": 0, "max_drawdown": 0.0, "n_obs": 0}

    manifest = _make_manifest(params)
    strat = EngulfingContinuationStrategy(manifest)

    df_f = strat.prepare_features(df)
    signals = strat.generate_signals(df_f)

    def prov(*a, **kw):
        return df_f.copy()

    engine = BacktestEngine(risk_officer=None)
    result = engine.run(
        strat,
        [str(df["symbol"].iloc[0])],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe="1d",
        initial_capital=INITIAL_CAPITAL,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=prov,
    )
    k = result.kpis
    return {
        "sharpe": float(k.get("sharpe", 0.0)),
        "sortino": float(k.get("sortino", 0.0)),
        "max_drawdown": float(k.get("max_drawdown", 0.0)),
        "cagr": float(k.get("cagr", 0.0)),
        "profit_factor": float(k.get("profit_factor", 0.0)),
        "win_rate": float(k.get("win_rate", 0.0)),
        "n_trades": int(k.get("n_trades", 0)),
        "n_obs": int(k.get("n_obs", 0)),
        "deflated_sharpe": float(k.get("deflated_sharpe", 0.0)),
        "equity_final": float(result.equity_curve.iloc[-1]) if not result.equity_curve.empty else INITIAL_CAPITAL,
    }


# =====================================================================
# DSR hesabı (López formülü)
# =====================================================================

def _compute_dsr(
    sr_observed: float,
    n_trials: int,
    returns: pd.Series | None = None,
) -> float:
    """López de Prado (2014) Deflated Sharpe Ratio."""
    from price_action.backtest.metrics import deflated_sharpe_ratio

    skew = float(returns.skew()) if returns is not None and not returns.empty else 0.0
    kurt = float(returns.kurt()) + 3.0 if returns is not None and not returns.empty else 3.0
    n_obs = len(returns) if returns is not None and not returns.empty else 252

    return deflated_sharpe_ratio(
        sr_observed,
        n_trials=n_trials,
        skew=skew,
        kurt=kurt,
        n_obs=n_obs,
    )


# =====================================================================
# Aggregate multi-symbol backtest
# =====================================================================

def _aggregate_kpis(results: list[dict]) -> dict:
    """Semboller arası KPI ortalaması — trades-weighted Sharpe."""
    valid = [r for r in results if r.get("n_trades", 0) > 0 and "error" not in r]
    if not valid:
        return {"sharpe": 0.0, "max_drawdown": 0.0, "n_trades": 0, "n_obs": 0,
                "cagr": 0.0, "profit_factor": 0.0, "win_rate": 0.0}
    n_trades_total = sum(r["n_trades"] for r in valid)
    sharpe_avg = float(np.mean([r["sharpe"] for r in valid]))
    dd_avg = float(np.mean([r["max_drawdown"] for r in valid]))
    cagr_avg = float(np.mean([r["cagr"] for r in valid]))
    pf_avg = float(np.mean([r["profit_factor"] for r in valid]))
    wr_avg = float(np.mean([r["win_rate"] for r in valid]))
    n_obs_total = sum(r["n_obs"] for r in valid)
    return {
        "sharpe": sharpe_avg,
        "max_drawdown": dd_avg,
        "n_trades": n_trades_total,
        "n_obs": n_obs_total,
        "cagr": cagr_avg,
        "profit_factor": pf_avg,
        "win_rate": wr_avg,
        "n_valid_symbols": len(valid),
    }


# =====================================================================
# Sweep core
# =====================================================================

def run_sweep(
    symbols: list[str],
    n_samples: int = 50,
    use_db: bool = True,
    train_ratio: float = TRAIN_RATIO,
) -> dict:
    """
    Ana sweep fonksiyonu.

    Returns:
        dict with keys:
          - all_results: list of per-combo dicts
          - train_top5, test_top5
          - dsr_results: {combo_idx: dsr}
          - verdict, default_comparison
    """
    print(f"\nVeri yükleniyor: {len(symbols)} sembol...")
    # Her sembol için full veri + train/test split
    symbol_data: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for sym in symbols:
        df = _load_ohlcv(sym, use_db=use_db)
        if df.empty or len(df) < 150:
            print(f"  {sym}: yetersiz veri, atlandı")
            continue
        df = df.sort_values("ts").reset_index(drop=True)
        split_idx = int(len(df) * train_ratio)
        train_df = df.iloc[:split_idx].copy().reset_index(drop=True)
        test_df = df.iloc[split_idx:].copy().reset_index(drop=True)
        symbol_data[sym] = (train_df, test_df)
        src = "DB" if use_db and not _load_from_db(sym).empty else "SYN"
        print(f"  {sym:<12} total={len(df):>5} train={len(train_df):>4} test={len(test_df):>4} [{src}]")

    if not symbol_data:
        print("HATA: Hiç sembol verisi yüklenemedi.")
        return {}

    # Halton örnekleri üret
    print(f"\nHalton örnekleme: {n_samples} kombinasyon...")
    param_combos = halton_samples(n_samples, PARAM_GRID)

    # Default combo da ekle (referans)
    param_combos.append(DEFAULTS.copy())
    default_combo_idx = len(param_combos) - 1

    all_train_kpis: list[dict] = []
    all_test_kpis: list[dict] = []
    all_params: list[dict] = []

    print(f"\nSweep başlıyor: {len(param_combos)} kombinasyon × {len(symbol_data)} sembol...")
    print("-" * 80)

    for combo_idx, params in enumerate(param_combos):
        is_default = combo_idx == default_combo_idx
        label = "DEFAULT" if is_default else f"#{combo_idx:>3}"

        train_results: list[dict] = []
        test_results: list[dict] = []

        for sym, (train_df, test_df) in symbol_data.items():
            # TRAIN
            try:
                tr = _run_backtest(train_df, params)
            except Exception as exc:
                tr = {"sharpe": 0.0, "n_trades": 0, "max_drawdown": 0.0,
                      "n_obs": 0, "error": str(exc)}
            # TEST
            try:
                te = _run_backtest(test_df, params)
            except Exception as exc:
                te = {"sharpe": 0.0, "n_trades": 0, "max_drawdown": 0.0,
                      "n_obs": 0, "error": str(exc)}
            train_results.append(tr)
            test_results.append(te)

        train_agg = _aggregate_kpis(train_results)
        test_agg = _aggregate_kpis(test_results)
        all_train_kpis.append(train_agg)
        all_test_kpis.append(test_agg)
        all_params.append(params)

        if combo_idx % 10 == 0 or is_default:
            print(
                f"  {label} "
                f"ER={params['kaufman_er_min']:.2f} "
                f"body={params['body_engulf_ratio']:.2f} "
                f"prox={params['atr_proximity_to_sr']:.2f} "
                f"pb_win={params['pullback_window']:>2} "
                f"bear={params['bear_regime_factor']:.2f} "
                f"| TRAIN Sharpe={train_agg['sharpe']:>+6.3f} "
                f"TRADES={train_agg['n_trades']:>4} "
                f"| TEST Sharpe={test_agg['sharpe']:>+6.3f} "
                f"TRADES={test_agg['n_trades']:>3}"
            )

    # ----------------------------------------------------------------
    # Top-5 by train Sharpe → DSR on test
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TOP-5 TRAIN SHARPE → OOS DSR")
    print("=" * 80)

    # Train Sharpe sıralaması (default hariç)
    non_default_idx = [i for i in range(len(all_params)) if i != default_combo_idx]
    train_sharpes = [(all_train_kpis[i]["sharpe"], i) for i in non_default_idx]
    train_sorted = sorted(train_sharpes, reverse=True)
    top5_train_idx = [i for _, i in train_sorted[:5]]

    # Test Sharpe sıralaması
    test_sharpes = [(all_test_kpis[i]["sharpe"], i) for i in non_default_idx]
    test_sorted = sorted(test_sharpes, reverse=True)
    top5_test_idx = [i for _, i in test_sorted[:5]]

    # Train SR varyansı (DSR için) — tüm trial'ların train Sharpe'larından
    all_train_sr_vals = [all_train_kpis[i]["sharpe"] for i in non_default_idx]
    sr_var = float(np.var(all_train_sr_vals)) if len(all_train_sr_vals) > 1 else 1.0

    dsr_results: dict[int, dict] = {}
    print(f"\n{'Rank':<5} {'Combo':>5} {'ER':>5} {'Body':>5} {'Prox':>5} {'PbW':>4} {'Bear':>5} "
          f"{'TrSharpe':>9} {'TeSharpe':>9} {'DSR':>7} {'Bonferr':>8}")
    print("-" * 80)

    for rank, idx in enumerate(top5_train_idx, 1):
        p = all_params[idx]
        tr_kpi = all_train_kpis[idx]
        te_kpi = all_test_kpis[idx]
        te_sharpe = te_kpi["sharpe"]
        te_n_obs = max(te_kpi["n_obs"], 30)

        dsr = _compute_dsr(te_sharpe, n_trials=n_samples, returns=None)
        # Bonferroni p-value yaklaşımı: SR'den t-stat, 1-sided
        import math
        t_stat = te_sharpe * math.sqrt(te_n_obs)
        p_val = 0.5 * (1 - math.erf(t_stat / math.sqrt(2))) if t_stat > 0 else 0.5
        bonf_ok = p_val < BONFERRONI_ALPHA

        dsr_results[idx] = {
            "dsr": dsr,
            "p_value": p_val,
            "bonferroni_pass": bonf_ok,
            "train_sharpe": tr_kpi["sharpe"],
            "test_sharpe": te_sharpe,
            "params": p,
        }
        bonf_str = "PASS" if bonf_ok else "fail"
        print(
            f"  {rank:<4} #{idx:>3} "
            f"{p['kaufman_er_min']:>5.2f} "
            f"{p['body_engulf_ratio']:>5.2f} "
            f"{p['atr_proximity_to_sr']:>5.2f} "
            f"{p['pullback_window']:>4} "
            f"{p['bear_regime_factor']:>5.2f} "
            f"  {tr_kpi['sharpe']:>+8.3f} "
            f"  {te_sharpe:>+8.3f} "
            f"  {dsr:>7.3f} "
            f"  {bonf_str}"
        )

    # ----------------------------------------------------------------
    # Top-5 by test Sharpe (OOS view)
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("TOP-10 TEST (OOS) SHARPE — tüm kombinasyonlar")
    print("=" * 80)
    print(f"\n{'Rank':<5} {'Combo':>5} {'ER':>5} {'Body':>5} {'Prox':>5} {'PbW':>4} {'Bear':>5} "
          f"{'TrSharpe':>9} {'TeSharpe':>9} {'TrTrades':>9} {'TeTrades':>9}")
    print("-" * 80)

    all_test_sorted_full = sorted(
        [(all_test_kpis[i]["sharpe"], i) for i in non_default_idx], reverse=True
    )
    for rank, (te_sh, idx) in enumerate(all_test_sorted_full[:10], 1):
        p = all_params[idx]
        tr_kpi = all_train_kpis[idx]
        te_kpi = all_test_kpis[idx]
        print(
            f"  {rank:<4} #{idx:>3} "
            f"{p['kaufman_er_min']:>5.2f} "
            f"{p['body_engulf_ratio']:>5.2f} "
            f"{p['atr_proximity_to_sr']:>5.2f} "
            f"{p['pullback_window']:>4} "
            f"{p['bear_regime_factor']:>5.2f} "
            f"  {tr_kpi['sharpe']:>+8.3f} "
            f"  {te_sh:>+8.3f} "
            f"  {tr_kpi['n_trades']:>9} "
            f"  {te_kpi['n_trades']:>9}"
        )

    # ----------------------------------------------------------------
    # Default parametreler için ayrıca DSR
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("DEFAULT PARAMETRELERİ DSR KARŞILAŞTIRMASI")
    print("=" * 80)

    def_train = all_train_kpis[default_combo_idx]
    def_test = all_test_kpis[default_combo_idx]
    def_dsr = _compute_dsr(def_test["sharpe"], n_trials=n_samples)
    print(f"\n  Default params: {DEFAULTS}")
    print(f"  Train Sharpe : {def_train['sharpe']:>+.3f}  N_trades={def_train['n_trades']}")
    print(f"  Test Sharpe  : {def_test['sharpe']:>+.3f}  N_trades={def_test['n_trades']}")
    print(f"  Test DSR     : {def_dsr:>+.3f}  (eşik={DSR_THRESHOLD})")

    # ----------------------------------------------------------------
    # Parametre duyarlılık analizi (default'tan sapma vs. Sharpe)
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PARAMETRELİK DUYARLILIK (DEFAULT'TAN SAPMA)")
    print("=" * 80)

    sensitivity: dict[str, dict] = {}
    for param_name in PARAM_GRID.keys():
        default_val = DEFAULTS[param_name]
        diffs: list[tuple[float, float]] = []  # (abs_diff, test_sharpe)
        for i in non_default_idx:
            val = all_params[i][param_name]
            diff = abs(val - default_val) / max(abs(default_val), 1e-6)
            diffs.append((diff, all_test_kpis[i]["sharpe"]))
        # Korelasyon: diff ile test_sharpe
        diffs_arr = np.array(diffs)
        if len(diffs_arr) > 2 and diffs_arr[:, 0].std() > 0:
            corr = float(np.corrcoef(diffs_arr[:, 0], diffs_arr[:, 1])[0, 1])
        else:
            corr = 0.0
        sensitivity[param_name] = {"diff_sharpe_corr": corr}

    print(f"\n  {'Parametre':<25} {'Sapma-Sharpe Korr':>20}  Yorum")
    print("  " + "-" * 60)
    for pname, sv in sensitivity.items():
        c = sv["diff_sharpe_corr"]
        if abs(c) < 0.1:
            comment = "Duyarsız (robüst)"
        elif c > 0.1:
            comment = "Daha farklı => daha iyi (dikkat: overfit riski)"
        else:
            comment = "Default civarı => daha iyi"
        print(f"  {pname:<25} {c:>+20.3f}  {comment}")

    # ----------------------------------------------------------------
    # DSR analizi — kaç tanesi > 0.5?
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"DSR ANALIZI (eşik={DSR_THRESHOLD}, Bonferroni α={BONFERRONI_ALPHA:.4f})")
    print("=" * 80)

    dsr_pass_combos = [
        (idx, info) for idx, info in dsr_results.items()
        if info["dsr"] > DSR_THRESHOLD
    ]
    bonf_pass_combos = [
        (idx, info) for idx, info in dsr_results.items()
        if info["bonferroni_pass"]
    ]

    print(f"\n  Top-5 train sweep'te DSR > {DSR_THRESHOLD}: {len(dsr_pass_combos)}/5")
    print(f"  Bonferroni (p<{BONFERRONI_ALPHA:.4f}) geçen  : {len(bonf_pass_combos)}/5")

    if dsr_pass_combos:
        print("\n  DSR PASS kombinasyonları:")
        for idx, info in sorted(dsr_pass_combos, key=lambda x: -x[1]["dsr"]):
            print(f"    #{idx:<4} DSR={info['dsr']:.3f}  TeSharpe={info['test_sharpe']:+.3f}  "
                  f"params={info['params']}")

    # ----------------------------------------------------------------
    # VERDICT
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    # Promoted set belirleme
    # Kriter: en az 1 DSR > 0.5 VE test Sharpe > default test Sharpe
    default_te_sharpe = def_test["sharpe"]
    promoted_sets = [
        (idx, info) for idx, info in dsr_pass_combos
        if info["test_sharpe"] > default_te_sharpe
    ]

    # Overfit check: train-test sharpe gap
    best_by_test_idx = test_sorted[0][1] if test_sorted else 0
    best_train_sr = all_train_kpis[best_by_test_idx]["sharpe"]
    best_test_sr = all_test_kpis[best_by_test_idx]["sharpe"]
    train_test_gap = abs(best_train_sr - best_test_sr)
    overfit_signal = train_test_gap > 1.5  # büyük gap → overfit

    if promoted_sets and not overfit_signal:
        verdict = "PROMOTE"
        best_promoted_idx, best_promoted_info = max(promoted_sets, key=lambda x: x[1]["dsr"])
        verdict_params = best_promoted_info["params"]
        verdict_reason = (
            f"DSR={best_promoted_info['dsr']:.3f} > {DSR_THRESHOLD}, "
            f"OOS Sharpe={best_promoted_info['test_sharpe']:+.3f} > default({default_te_sharpe:+.3f})"
        )
    elif overfit_signal and promoted_sets:
        verdict = "NEED MORE DATA"
        verdict_params = DEFAULTS
        verdict_reason = (
            f"Train-test gap={train_test_gap:.2f} çok büyük — overfit şüphesi. "
            f"Daha uzun OOS penceresi gerekli."
        )
    elif def_dsr > DSR_THRESHOLD:
        verdict = "KEEP DEFAULTS"
        verdict_params = DEFAULTS
        verdict_reason = (
            f"Hiçbir yeni set default'u DSR açısından geçemedi. "
            f"Default DSR={def_dsr:.3f} zaten {DSR_THRESHOLD}'i geçiyor."
        )
    else:
        verdict = "KEEP DEFAULTS"
        verdict_params = DEFAULTS
        verdict_reason = (
            f"Hiçbir kombinasyon DSR > {DSR_THRESHOLD} ve OOS Sharpe > default sağlayamadı. "
            f"Default parametreler optimal ya da veri yetersiz."
        )

    print(f"\n  VERDICT  : {verdict}")
    print(f"  Gerekçe  : {verdict_reason}")
    print(f"  Seçilen  : {verdict_params}")
    print()
    print(f"  Train-test Sharpe gap (best OOS): {train_test_gap:.3f}  "
          f"({'OVERFIT ALARM' if overfit_signal else 'OK'})")
    print(f"  Default DSR              : {def_dsr:.3f}")
    print(f"  N_trials (sweep)         : {n_samples}")
    print(f"  Bonferroni α             : {BONFERRONI_ALPHA:.5f}")

    # ----------------------------------------------------------------
    # Rapor kaydet
    # ----------------------------------------------------------------
    report = {
        "run_date": datetime.now(timezone.utc).isoformat(),
        "n_samples": n_samples,
        "symbols": symbols,
        "train_ratio": train_ratio,
        "n_param_combos": len(param_combos),
        "dsr_threshold": DSR_THRESHOLD,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "defaults": DEFAULTS,
        "top5_train_dsr": [
            {
                "combo_idx": idx,
                **dsr_results[idx],
            }
            for idx in top5_train_idx
            if idx in dsr_results
        ],
        "top10_test": [
            {
                "rank": r + 1,
                "combo_idx": idx,
                "params": all_params[idx],
                "train_sharpe": all_train_kpis[idx]["sharpe"],
                "test_sharpe": te_sh,
                "train_trades": all_train_kpis[idx]["n_trades"],
                "test_trades": all_test_kpis[idx]["n_trades"],
            }
            for r, (te_sh, idx) in enumerate(all_test_sorted_full[:10])
        ],
        "default_comparison": {
            "train_sharpe": def_train["sharpe"],
            "test_sharpe": def_test["sharpe"],
            "dsr": def_dsr,
            "n_trades_train": def_train["n_trades"],
            "n_trades_test": def_test["n_trades"],
        },
        "sensitivity": sensitivity,
        "overfit_signal": overfit_signal,
        "train_test_gap": train_test_gap,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "verdict_params": verdict_params,
        "dsr_pass_count": len(dsr_pass_combos),
        "bonferroni_pass_count": len(bonf_pass_combos),
    }

    rdir = ROOT / "reports" / "backtests"
    rdir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rpath = rdir / f"engulfing_param_sweep_{ts_str}.json"
    rpath.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    print(f"\n  Detay rapor: {rpath}")

    return report


# =====================================================================
# CLI
# =====================================================================

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Engulfing Continuation parameter sweep (López AFML)",
    )
    p.add_argument(
        "--symbols", nargs="+", default=SYMBOLS[:5],
        help="Backteste katılacak semboller (default: ilk 5)",
    )
    p.add_argument("--n-samples", type=int, default=N_TRIALS,
                   help=f"Halton örnek sayısı (default: {N_TRIALS})")
    p.add_argument("--dsr-threshold", type=float, default=DSR_THRESHOLD,
                   help=f"DSR eşiği (default: {DSR_THRESHOLD})")
    p.add_argument("--train-ratio", type=float, default=TRAIN_RATIO,
                   help=f"Train oranı (default: {TRAIN_RATIO})")
    p.add_argument("--no-db", action="store_true",
                   help="DuckDB kullanma, sentetik veri üret")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    print("=" * 80)
    print("ENGULFING CONTINUATION — PARAMETER SWEEP (López AFML)")
    print(f"Semboller     : {args.symbols}")
    print(f"Halton samples: {args.n_samples}")
    print(f"Train ratio   : {args.train_ratio:.0%}")
    print(f"DSR threshold : {args.dsr_threshold}")
    print(f"Bonferroni a  : {BONFERRONI_ALPHA:.5f}")
    print(f"DB kullan     : {not args.no_db}")
    print("=" * 80)

    report = run_sweep(
        symbols=args.symbols,
        n_samples=args.n_samples,
        use_db=not args.no_db,
        train_ratio=args.train_ratio,
    )

    if not report:
        print("HATA: Sweep başarısız.")
        return 1

    print("\n" + "=" * 80)
    print(f"SONUC: {report.get('verdict', 'UNKNOWN')}")
    print(f"Neden: {report.get('verdict_reason', '')}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
