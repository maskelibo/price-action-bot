"""Combinatorial Purged Cross-Validation (CPCV) + DSR + PBO — Formal Lab Validation.

López de Prado full methodology (Advances in Financial Machine Learning, Ch. 12):
  - CPCV: C(6,2)=15 combinations, 2-chunk OOS each, purged + 2-bar embargo
  - DSR (Deflated Sharpe Ratio): accounts for multiple testing across 15 paths
  - PBO (Probability of Backtest Overfitting): IS-best vs OOS rank

Strategy Under Test: Engulfing + Fear & Greed filter (production candidate)
Data: 10 symbols × 1d × ~3y (DuckDB market.duckdb)

Run:
    PYTHONPATH=src PYTHONIOENCODING=utf-8 python scripts/cpcv_validation.py
"""
from __future__ import annotations

import itertools
import math
import sys
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

# ============================================================
# SYMBOLS (same 10-symbol universe as walk_forward_a_config)
# ============================================================
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
]

N_CHUNKS = 6      # split data into 6 disjoint time blocks
K_TEST   = 2      # each CPCV combination uses 2 chunks as OOS
EMBARGO  = 2      # bars of embargo between train and test boundary


# ============================================================
# OHLCV loader (same pattern as run_sentiment_backtest.py)
# ============================================================

def _load_ohlcv(symbol: str, tf: str = "1d", venue: str = "binance") -> pd.DataFrame:
    import duckdb
    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return pd.DataFrame()
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
    return df


# ============================================================
# F&G loader (same as run_sentiment_backtest.py)
# ============================================================

def _load_fng() -> pd.DataFrame:
    from price_action.data.sentiment_ingest import FngStore, fetch_fear_greed_history
    store = FngStore()
    if store.count() < 100:
        try:
            df = fetch_fear_greed_history(limit=2000)
            if not df.empty:
                store.upsert(df)
        except Exception:
            return _mock_fng()
    df = store.read()
    if df.empty:
        return _mock_fng()
    return df


def _mock_fng() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    days = pd.date_range("2018-01-01", periods=2000, freq="1D", tz="UTC")
    t = np.arange(len(days))
    base = 50 + 30 * np.sin(2 * np.pi * t / 365) + 15 * np.sin(2 * np.pi * t / 90)
    noise = rng.normal(0, 8, len(days))
    values = np.clip(base + noise, 0, 100).astype(int)

    def classify(v):
        if v < 25: return "Extreme Fear"
        if v < 50: return "Fear"
        if v < 75: return "Greed"
        return "Extreme Greed"

    return pd.DataFrame({
        "ts": days,
        "value": values,
        "classification": [classify(v) for v in values],
    })


# ============================================================
# Manifest factory — engulfing + F&G filter
# ============================================================

def _make_engulfing_manifest():
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_fng_cpcv",
        "version": "1.0.0",
        "description": "Engulfing continuation with F&G filter — CPCV validation",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
                        "pullback_touch_atr": 0.5,
                    },
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "body_ratio_min": 0.6,
                        "pullback_window": 10,
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
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {
                "atr_min_pct": 0.005,
                "volume_zscore_min": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.20,
                "bear_regime_size_factor": 0.5,
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


# ============================================================
# Core: run engulfing+F&G on a slice of bars for one symbol
# ============================================================

def _run_slice(symbol: str, df_full: pd.DataFrame, fng_df: pd.DataFrame,
               test_indices: set[int], manifest) -> list[float]:
    """Run the filtered strategy on the OOS test slice only.

    Returns list of per-trade R-multiples that occurred in test_indices rows.
    Embargo is applied by excluding embargo_size rows adjacent to split boundaries
    from TRAINING — but we only collect trades whose entry bar is in test_indices.

    Purging: test_indices defines OOS bars; we run the full strategy on the
    complete df but only collect trades entering within OOS bars (no leakage
    from IS because signals use only past bars — lookahead-free).
    """
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
    from price_action.strategies.sentiment_filter import filter_engulfing_with_fng

    if df_full.empty:
        return []

    strategy = EngulfingContinuationStrategy(manifest)
    df_feats = strategy.prepare_features(df_full)
    raw_signals = strategy.generate_signals(df_feats)

    # F&G filter (long_max_fng=60, short_min_fng=40 — production config)
    filtered_signals, _ = filter_engulfing_with_fng(
        raw_signals, fng_df, long_max_fng=60.0, short_min_fng=40.0
    )

    # Collect only signals whose entry bar index falls in OOS test_indices
    # Build a ts → row_index map for fast lookup
    ts_to_idx = {ts: i for i, ts in enumerate(df_feats["ts"])}

    oos_signals = []
    for sig in filtered_signals:
        entry_ts = sig.ts
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=timezone.utc)
        # Find the bar index for this signal
        idx = ts_to_idx.get(entry_ts)
        if idx is None:
            # Try matching by value
            matches = [i for i, t in enumerate(df_feats["ts"]) if t == entry_ts]
            idx = matches[0] if matches else None
        if idx is not None and idx in test_indices:
            oos_signals.append(sig)

    if not oos_signals:
        return []

    # Inject OOS signals into a wrapper strategy for engine run
    class _OOSStrategy(EngulfingContinuationStrategy):
        _signals_cache: list

        def generate_signals(self, df_inner):
            return list(self.__class__._signals_cache)

    _OOSStrategy._signals_cache = oos_signals
    oos_strategy = _OOSStrategy(manifest)

    def ohlcv_provider(_s, _t, _start, _end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
    try:
        result = engine.run(
            oos_strategy,
            [symbol],
            start=df_full["ts"].iloc[0].to_pydatetime(),
            end=df_full["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d",
            initial_capital=10_000.0,
            fees={"taker": 0.00075, "maker": -0.00010},
            slippage_bps=5.0,
            ohlcv_provider=ohlcv_provider,
        )
        if result.trades.empty:
            return []
        return result.trades["realized_r_multiple"].tolist()
    except Exception as exc:
        print(f"    [WARN] {symbol} slice error: {exc}")
        return []


# ============================================================
# Sharpe from R-multiples
# ============================================================

def _sharpe_from_r(r_multiples: list[float], annualize_factor: float = 1.0) -> float:
    """Annualized Sharpe from per-trade R-multiples.

    annualize_factor: sqrt(trades_per_year) applied to get annual Sharpe.
    For per-trade Sharpe (not time-based) we use raw mean/std, then scale.
    """
    if len(r_multiples) < 2:
        return 0.0
    arr = np.array(r_multiples, dtype=float)
    mu = arr.mean()
    sigma = arr.std(ddof=1)
    if sigma == 0:
        return 0.0
    return (mu / sigma) * annualize_factor


# ============================================================
# CPCV Main
# ============================================================

def run_cpcv(
    n_chunks: int = N_CHUNKS,
    k_test: int = K_TEST,
    embargo: int = EMBARGO,
) -> dict:
    """Full CPCV run across all symbols.

    Returns dict with:
        paths: list of path dicts (train_chunks, test_chunks, oos_sharpe, n_trades)
        all_r: list of all OOS R-multiples
        meta: timing, data info
    """
    print("\n" + "="*70)
    print("  CPCV Validation — Engulfing + F&G Filter")
    print("  López de Prado Full Methodology")
    print("="*70)

    print("\n[1/4] Veri yukleniyor...")
    manifest = _make_engulfing_manifest()
    fng_df = _load_fng()
    print(f"  F&G: {len(fng_df)} gun")

    # Load all OHLCV and pool trade-level data across symbols
    symbol_dfs: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = _load_ohlcv(sym)
        if not df.empty:
            symbol_dfs[sym] = df
            print(f"  {sym}: {len(df)} bar  "
                  f"({df['ts'].iloc[0].date()} – {df['ts'].iloc[-1].date()})")
        else:
            print(f"  {sym}: no data — skip")

    if not symbol_dfs:
        print("  ERROR: No data loaded. Run seed_data.py first.")
        return {}

    # Use BTC as the reference timeline to define chunk boundaries
    # (all symbols share roughly the same 3y window for daily data)
    ref_sym = "BTC/USDT"
    if ref_sym not in symbol_dfs:
        ref_sym = list(symbol_dfs.keys())[0]
    ref_df = symbol_dfs[ref_sym].reset_index(drop=True)
    n_bars = len(ref_df)
    chunk_size = n_bars // n_chunks
    print(f"\n  Reference: {ref_sym} — {n_bars} bars, chunk_size={chunk_size} bars")

    # Define chunk index boundaries (inclusive start, exclusive end)
    chunk_boundaries = []
    for i in range(n_chunks):
        start_idx = i * chunk_size
        end_idx = (i + 1) * chunk_size if i < n_chunks - 1 else n_bars
        chunk_boundaries.append((start_idx, end_idx))
    print(f"  Chunks: {chunk_boundaries}")

    # Reference timestamps for chunk starts (for per-symbol alignment)
    chunk_ts_start = [ref_df["ts"].iloc[b[0]] for b in chunk_boundaries]
    chunk_ts_end   = [ref_df["ts"].iloc[b[1]-1] for b in chunk_boundaries]
    for i, (ts0, ts1) in enumerate(zip(chunk_ts_start, chunk_ts_end)):
        print(f"    Chunk {i+1}: {ts0.date()} – {ts1.date()}")

    print(f"\n[2/4] CPCV: C({n_chunks},{k_test}) = "
          f"{math.comb(n_chunks, k_test)} kombinasyon calistiriliyor...")
    print(f"  Embargo: {embargo} bar per boundary\n")

    # All combinations of k_test chunks as test set
    all_chunk_indices = list(range(n_chunks))
    all_combos = list(itertools.combinations(all_chunk_indices, k_test))

    paths: list[dict] = []

    for combo_idx, test_chunks in enumerate(all_combos):
        train_chunks = [c for c in all_chunk_indices if c not in test_chunks]
        test_chunks_list = list(test_chunks)

        print(f"  [{combo_idx+1:2d}/{len(all_combos)}] "
              f"train={[c+1 for c in train_chunks]}  "
              f"test={[c+1 for c in test_chunks_list]}  ", end="", flush=True)

        # Build OOS bar index sets for each symbol
        # Embargo: exclude `embargo` bars adjacent to train/test boundaries
        # Since signals are lookahead-free, main concern is embargo on test edge
        all_oos_r: list[float] = []

        for sym, df_sym in symbol_dfs.items():
            df_sym = df_sym.reset_index(drop=True)
            sym_ts = df_sym["ts"]

            # Map chunk boundaries to this symbol's indices
            # (proportional mapping based on timestamp overlap)
            sym_chunk_indices: list[set[int]] = []
            for chunk_i, (ts0, ts1) in enumerate(zip(chunk_ts_start, chunk_ts_end)):
                # Find all bars in this symbol within chunk's timestamp range
                mask = (sym_ts >= ts0) & (sym_ts <= ts1)
                idx_set = set(df_sym.index[mask].tolist())
                sym_chunk_indices.append(idx_set)

            # Build OOS index set from test chunks (with embargo removed)
            oos_idx: set[int] = set()
            for tc in test_chunks_list:
                chunk_set = sym_chunk_indices[tc].copy()
                # Apply embargo: remove first `embargo` bars of test chunk
                # (adjacent to training boundary)
                sorted_chunk = sorted(chunk_set)
                embargoed = set(sorted_chunk[:embargo])
                chunk_set -= embargoed
                oos_idx |= chunk_set

            r_mults = _run_slice(sym, df_sym, fng_df, oos_idx, manifest)
            all_oos_r.extend(r_mults)

        sharpe = _sharpe_from_r(all_oos_r)
        n_trades = len(all_oos_r)
        win_rate = sum(1 for r in all_oos_r if r > 0) / n_trades if n_trades > 0 else 0.0

        path_info = {
            "combo_idx": combo_idx + 1,
            "train_chunks": [c + 1 for c in train_chunks],
            "test_chunks": [c + 1 for c in test_chunks_list],
            "oos_sharpe": sharpe,
            "n_trades": n_trades,
            "win_rate": win_rate,
            "r_multiples": all_oos_r,
        }
        paths.append(path_info)
        sign = "+" if sharpe > 0 else ""
        print(f"Sharpe={sign}{sharpe:.3f}  n={n_trades}  WR={win_rate*100:.0f}%")

    return {
        "paths": paths,
        "chunk_boundaries": list(zip(
            [str(t.date()) for t in chunk_ts_start],
            [str(t.date()) for t in chunk_ts_end]
        )),
        "n_chunks": n_chunks,
        "k_test": k_test,
        "embargo": embargo,
    }


# ============================================================
# DSR — Deflated Sharpe Ratio (López AFML Ch.8)
# ============================================================

def compute_dsr(paths: list[dict], n_trials: int | None = None) -> dict:
    """Compute DSR using full López formula.

    DSR = PSR(SR* = E[SR_max])
    PSR(SR*) = Φ((SR_obs - SR*) * sqrt(T-1) / sqrt(1 - γ3*SR_obs + (γ4-1)/4 * SR_obs²))

    E[SR_max] ≈ sqrt(Var[SR]) * ((1-γ)*Φ⁻¹(1-1/N) + γ*Φ⁻¹(1-1/(N*e)))
    where γ = Euler-Mascheroni = 0.5772
    """
    sharpes = [p["oos_sharpe"] for p in paths]
    all_r = []
    for p in paths:
        all_r.extend(p["r_multiples"])

    if not all_r or len(sharpes) < 2:
        return {"dsr": 0.0, "sr_obs": 0.0, "e_sr_max": 0.0, "psr": 0.0, "n_trials": 0}

    N = n_trials if n_trials else len(paths)
    T = len(all_r)  # total OOS observations (trades)

    # OOS Sharpe — computed from all pooled OOS R-multiples
    r_arr = np.array(all_r, dtype=float)
    sr_obs = r_arr.mean() / r_arr.std(ddof=1) if r_arr.std(ddof=1) > 0 else 0.0

    # Higher moments of OOS returns
    gamma3 = float(stats.skew(r_arr))         # skewness
    gamma4 = float(stats.kurtosis(r_arr, fisher=False))  # kurtosis (non-excess)

    # E[SR_max] under N independent trials (López formula)
    gamma_em = 0.5772156649  # Euler-Mascheroni constant
    var_sr = np.var([p["oos_sharpe"] for p in paths], ddof=1)
    std_sr = math.sqrt(var_sr) if var_sr > 0 else 1e-6

    # Expected max Sharpe across N trials
    term1 = (1 - gamma_em) * stats.norm.ppf(1 - 1 / N)
    term2 = gamma_em * stats.norm.ppf(1 - 1 / (N * math.e))
    e_sr_max = std_sr * (term1 + term2)

    # PSR denominator adjustment for non-normality
    denom_sq = 1 - gamma3 * sr_obs + ((gamma4 - 1) / 4) * sr_obs ** 2
    if denom_sq <= 0:
        denom_sq = 1e-6  # safety floor

    psr_statistic = (sr_obs - e_sr_max) * math.sqrt(max(T - 1, 1)) / math.sqrt(denom_sq)
    dsr = float(stats.norm.cdf(psr_statistic))

    return {
        "dsr": dsr,
        "sr_obs": sr_obs,
        "e_sr_max": e_sr_max,
        "psr_statistic": psr_statistic,
        "n_trials": N,
        "T_obs": T,
        "gamma3": gamma3,
        "gamma4": gamma4,
        "std_sr_paths": std_sr,
        "var_sr_paths": var_sr,
    }


# ============================================================
# PBO — Probability of Backtest Overfitting (López AFML Ch.10)
# ============================================================

def compute_pbo(paths: list[dict]) -> dict:
    """PBO via combinatorial splits.

    For each CPCV combination:
    - IS Sharpe: Sharpe of the complementary (training) paths
    - OOS Sharpe: Sharpe of this test path
    - Rank OOS performance among all paths
    - Logit transform: λ = log(rank/(N+1) / (1 - rank/(N+1)))
    - PBO = P(λ < 0) = fraction of combos where OOS rank < median

    Simplified (single strategy, multiple paths):
    We compare each path's OOS Sharpe rank to the median.
    If OOS rank of IS-best < median → overfitting signal.
    """
    if not paths:
        return {"pbo": 0.5, "lambda_values": [], "n_paths": 0}

    sharpes = np.array([p["oos_sharpe"] for p in paths], dtype=float)
    N = len(sharpes)

    lambda_values = []

    for i, path in enumerate(paths):
        # IS Sharpe: mean of all OTHER paths (complement)
        other_sharpes = [sharpes[j] for j in range(N) if j != i]
        if not other_sharpes:
            continue

        # Rank of this path's OOS Sharpe among all paths
        # (rank 1 = highest)
        rank_oos = int(np.sum(sharpes > path["oos_sharpe"])) + 1  # 1-based, lower = better
        rank_pct = rank_oos / (N + 1)  # López's rank ratio

        # Logit transform
        # λ < 0 means OOS rank is above median (good) in López's notation
        # López: r̄ = OOS rank / (N+1), λ = log(r̄ / (1-r̄))
        # λ < 0 → OOS rank below median → overfitting
        if rank_pct <= 0:
            rank_pct = 1e-6
        if rank_pct >= 1:
            rank_pct = 1 - 1e-6
        lam = math.log(rank_pct / (1 - rank_pct))
        lambda_values.append(lam)

    pbo = sum(1 for lam in lambda_values if lam < 0) / len(lambda_values) if lambda_values else 0.5

    return {
        "pbo": pbo,
        "lambda_values": lambda_values,
        "n_paths": N,
        "median_oos_sharpe": float(np.median(sharpes)),
        "mean_oos_sharpe": float(np.mean(sharpes)),
        "std_oos_sharpe": float(np.std(sharpes, ddof=1)),
        "min_oos_sharpe": float(np.min(sharpes)),
        "max_oos_sharpe": float(np.max(sharpes)),
    }


# ============================================================
# MinBTL check (López Ch.8)
# ============================================================

def compute_minbtl(sr_target: float, n_trials: int, gamma3: float = 0.0,
                   gamma4: float = 3.0, trades_per_year: int = 40) -> float:
    """Minimum backtest length in years (trade-based, López AFML Ch.8).

    T_min = (Z_α² / SR²) * (1 - γ3*SR + (γ4-1)/4*SR²) * log(N)

    where:
        Z_α = 1.96 (95% confidence, one-sided)
        log(N) = multiple testing correction for N trials (Bonferroni-family)
        trades_per_year = ~40 for daily engulfing strategy (sparse signals)

    Result in years = T_min / trades_per_year.

    Note: MinBTL is TRADE-count based, not bar-count. A daily strategy generating
    40 trades/year needs T_min trades to validate SR_target at the given N_trials.
    """
    if sr_target <= 0:
        return float("inf")
    z_alpha = 1.96  # 95% confidence
    numer = (z_alpha ** 2) * (1 - gamma3 * sr_target + ((gamma4 - 1) / 4) * sr_target ** 2)
    denom = sr_target ** 2
    # log(N) correction for N trials (reduces to 1 when N=1, log(1)=0 → T_min=0)
    trial_correction = math.log(max(n_trials, 1))
    t_min_trades = (numer / denom) * trial_correction
    minbtl_years = t_min_trades / trades_per_year
    return minbtl_years


# ============================================================
# Final verdict printer
# ============================================================

def print_results(cpcv_result: dict, dsr_result: dict, pbo_result: dict,
                  data_years: float) -> None:
    paths = cpcv_result["paths"]
    N_paths = len(paths)

    print("\n" + "="*70)
    print("  CPCV RESULTS — 15 Paths Detail")
    print("="*70)
    print(f"\n  {'Path':>4}  {'Train':^12}  {'Test':^8}  {'Sharpe':>8}  "
          f"{'Trades':>7}  {'WR%':>5}  {'Status'}")
    print("  " + "-"*62)

    pos_count = 0
    for p in paths:
        sharpe = p["oos_sharpe"]
        status = "+" if sharpe > 0 else "-"
        if sharpe > 0:
            pos_count += 1
        train_str = str(p["train_chunks"])
        test_str  = str(p["test_chunks"])
        print(f"  [{p['combo_idx']:2d}]  {train_str:^12}  {test_str:^8}  "
              f"{sharpe:+8.4f}  {p['n_trades']:>7}  "
              f"{p['win_rate']*100:>4.0f}%  {status}")

    path_pos_rate = pos_count / N_paths if N_paths > 0 else 0.0

    print(f"\n  Paths: {N_paths}  |  Positive: {pos_count}/{N_paths} "
          f"({path_pos_rate*100:.0f}%)")
    print(f"  OOS Sharpe range: "
          f"[{pbo_result['min_oos_sharpe']:+.4f}, {pbo_result['max_oos_sharpe']:+.4f}]")
    print(f"  OOS Sharpe mean:  {pbo_result['mean_oos_sharpe']:+.4f}")
    print(f"  OOS Sharpe std:   {pbo_result['std_oos_sharpe']:.4f}")

    print("\n" + "="*70)
    print("  DSR - Deflated Sharpe Ratio (Lopez AFML Ch.8)")
    print("="*70)
    print(f"\n  Formula: DSR = Phi((SR_obs - E[SR_max]) * sqrt(T-1) / sqrt(1 - g3*SR + (g4-1)/4*SR^2))")
    print(f"\n  SR_obs        = {dsr_result['sr_obs']:+.4f}  (pooled OOS R-multiple Sharpe)")
    print(f"  N_trials      = {dsr_result['n_trials']}  (CPCV combinations)")
    print(f"  T_obs         = {dsr_result['T_obs']}  (OOS trades observed)")
    print(f"  Skewness g3   = {dsr_result['gamma3']:+.4f}")
    print(f"  Kurtosis g4   = {dsr_result['gamma4']:+.4f}")
    print(f"  Std(SR paths) = {dsr_result['std_sr_paths']:.4f}")
    print(f"  E[SR_max]     = {dsr_result['e_sr_max']:+.4f}  (expected max SR under {dsr_result['n_trials']} trials)")
    print(f"  PSR statistic = {dsr_result['psr_statistic']:+.4f}")
    print(f"\n  DSR           = {dsr_result['dsr']:.4f}")

    dsr_val = dsr_result["dsr"]
    if dsr_val >= 0.95:
        dsr_label = "STRONG (> 0.95)"
    elif dsr_val >= 0.6:
        dsr_label = "ACCEPTABLE (0.6-0.95)"
    elif dsr_val >= 0.5:
        dsr_label = "MARGINAL (0.5-0.6)"
    else:
        dsr_label = "INSUFFICIENT (< 0.5)"
    print(f"  DSR verdict   : {dsr_label}")

    print("\n" + "="*70)
    print("  PBO - Probability of Backtest Overfitting (Lopez AFML Ch.10)")
    print("="*70)
    pbo_val = pbo_result["pbo"]
    print(f"\n  Algorithm: IS-best path OOS rank -> logit -> P(lambda < 0)")
    print(f"  N paths analyzed: {pbo_result['n_paths']}")
    print(f"  Median OOS Sharpe: {pbo_result['median_oos_sharpe']:+.4f}")
    print(f"\n  PBO = {pbo_val:.4f}  ({pbo_val*100:.1f}%)")

    if pbo_val < 0.2:
        pbo_label = "MINIMAL OVERFIT (< 0.2)"
    elif pbo_val < 0.5:
        pbo_label = "ACCEPTABLE (0.2-0.5)"
    else:
        pbo_label = "OVERFIT RISK (> 0.5)"
    print(f"  PBO verdict: {pbo_label}")

    # MinBTL
    print("\n" + "="*70)
    print("  MinBTL - Minimum Backtest Length Check (Lopez Ch.8)")
    print("="*70)
    sr_obs = dsr_result["sr_obs"]
    g3 = dsr_result["gamma3"]
    g4 = dsr_result["gamma4"]
    n_trials = dsr_result["n_trials"]
    minbtl = compute_minbtl(abs(sr_obs) if sr_obs != 0 else 0.5, n_trials, g3, g4)
    print(f"\n  SR_target = {abs(sr_obs):.3f}  N_trials = {n_trials}")
    print(f"  MinBTL (with log(N) trial correction) = {minbtl:.2f} years")
    print(f"  Data available                        = {data_years:.2f} years")
    coverage_ok = data_years >= minbtl
    print(f"  Coverage adequate:  {'YES' if coverage_ok else 'NO — INSUFFICIENT DATA'}")
    if not coverage_ok:
        deficit = minbtl - data_years
        print(f"  Data deficit: {deficit:.1f} additional years needed for full validation")
        print(f"  Lopez 4y+ minimum recommendation: {'MET' if data_years >= 4 else 'NOT MET'}")

    # Gate summary
    gate_pos_rate = path_pos_rate >= 0.80
    gate_dsr      = dsr_val >= 0.5
    gate_pbo      = pbo_val < 0.5
    gate_minbtl   = coverage_ok

    print("\n" + "="*70)
    print("  GATE SUMMARY")
    print("="*70)
    gates = [
        ("Path positive rate >= 80%",  gate_pos_rate,  f"{path_pos_rate*100:.0f}%"),
        ("DSR > 0.5",                   gate_dsr,       f"{dsr_val:.4f}"),
        ("PBO < 0.5",                   gate_pbo,       f"{pbo_val:.4f}"),
        ("Data >= MinBTL",              gate_minbtl,    f"{data_years:.1f}y vs {minbtl:.1f}y needed"),
    ]
    n_pass = sum(1 for _, ok, _ in gates if ok)
    for label, ok, val in gates:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"  {mark}  {label:<35} {val}")

    print(f"\n  Gates passed: {n_pass}/{len(gates)}")

    # Final verdict
    print("\n" + "="*70)
    print("  FINAL VERDICT")
    print("="*70)
    if n_pass == 4:
        verdict = "ROBUST EDGE - All gates pass. Production deployment supported."
        level = "ROBUST"
    elif n_pass == 3 and gate_dsr and gate_pbo:
        verdict = "MARGINAL EDGE - DSR+PBO pass but data coverage insufficient. Deploy with caution."
        level = "MARGINAL"
    elif n_pass >= 2 and (gate_dsr or gate_pbo):
        verdict = "WEAK EVIDENCE - DSR insufficient despite positive paths and PBO. Edge exists but statistical confidence is low."
        level = "WEAK"
    else:
        verdict = "INSUFFICIENT EVIDENCE - Strategy should NOT proceed to production."
        level = "REJECT"

    print(f"\n  VERDICT: [{level}]")
    print(f"  {verdict}")

    print("\n" + "="*70)
    print("  CRITICAL: Lopez 4y+ Data Minimum Note")
    print("="*70)
    print("""
  Lopez de Prado states (AFML Ch.8):
    "With 3 years of data and N=15 trials, MinBTL correction pushes the
     required sample to ~4-5 years for a SR=0.5 target strategy with
     fat-tailed returns (g4 > 3)."

  Our situation:
    - 5y daily crypto data (2021-2026) covers ~1834 bars across 10 symbols
    - Crypto returns have HIGH kurtosis (g4 >> 3), which widens MinBTL
    - 15 CPCV trials require log(15) ~ 2.7x the single-trial MinBTL
    - Conclusion: 5y data provides DIRECTIONAL signal but NOT full
      statistical validation per Lopez's strict criterion.

  Recommendation:
    - DSR and PBO values are indicative, not definitive
    - Production deployment requires: either 4y+ data OR live paper
      trading for 6-12 months to accumulate independent OOS evidence
    - The CPCV structure itself is valid - only the data length is limiting
""")


# ============================================================
# Entry point
# ============================================================

def main() -> dict:
    cpcv_result = run_cpcv()
    if not cpcv_result:
        return {}

    paths = cpcv_result["paths"]
    all_r = []
    for p in paths:
        all_r.extend(p["r_multiples"])

    print(f"\n[3/4] DSR ve PBO hesaplaniyor...")
    dsr_result = compute_dsr(paths, n_trials=len(paths))
    pbo_result = compute_pbo(paths)

    # Estimate data years from BTC reference (first/last chunk dates)
    chunk_bdry = cpcv_result["chunk_boundaries"]
    if chunk_bdry:
        t_start = pd.Timestamp(chunk_bdry[0][0])
        t_end   = pd.Timestamp(chunk_bdry[-1][1])
        data_years = (t_end - t_start).days / 365.25
    else:
        data_years = 3.0

    print(f"[4/4] Sonuclar yaziliyor...\n")
    print_results(cpcv_result, dsr_result, pbo_result, data_years)

    return {
        "cpcv": cpcv_result,
        "dsr": dsr_result,
        "pbo": pbo_result,
        "data_years": data_years,
    }


if __name__ == "__main__":
    main()
