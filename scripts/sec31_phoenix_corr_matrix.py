"""SEC31: Phoenix 1d × Scalper Trade-Series Correlation Harness.

PURPOSE
-------
Phoenix 1d swing botu vs scalper bot'ları (15m/5m/1m) **trade-series korelasyon
matrisi** + **drawdown overlap heatmap** üret. Portfolio integration gate (Phase 5)
sayısal kararı verecek:
  - Korelasyon < 0.30 (her TF için) → portfolio diversification fayda var
  - Korelasyon > 0.50 → hedge faydası sıfır, scalper standalone değerlendir

TARGET METRICS (her TF için ayrı)
----------------------------------
1. Pearson correlation (90g rolling) — pa.daily_pnl_phoenix vs pa.daily_pnl_scalper
2. Spearman rank correlation (90g rolling) — non-linear ilişki
3. Drawdown overlap matrix — Phoenix DD pencerelerinde scalper performans

INPUT FORMAT (esnek loader)
---------------------------
Phoenix 1d trade series (canonical):
  futures_trades_closed table (SEC26.B-4 schema) OR
  CSV: ts, sym, side, strategy, entry_price, exit_price, qty, realized_pnl_usdt, realized_r

Scalper trade series (3 TF, scalper backtest sonucu — Phase 4 çıktısı):
  reports/lab/sec3X_phoenix_scalp_{15m,5m,1m}_trades.csv  (henüz YOK, Phase 4 üretecek)

DAILY PNL AGGREGATION
---------------------
Trade-level → daily P&L serisi:
  daily_pnl_USDT[D] = sum(realized_pnl_usdt) FOR trades WITH exit_ts.date() == D
  daily_pnl_R[D]    = sum(realized_r) FOR aynı subset
Korelasyon **R-bazlı** yapılır (size-invariant); $$-bazlı versiyon ek.

ROLLING CORRELATION
-------------------
window = 90 gün (Phoenix 1d için 1 quarter yeterli sample), step = 1 gün.
Tek pencere değil rolling — regime shift'lerde korelasyon NASIL DEĞİŞTİĞİNİ gör.

DRAWDOWN OVERLAP HEATMAP
------------------------
1. Phoenix 1d equity curve → DD pencereleri tespit (peak-to-trough >= -%10 olanlar)
2. Her DD penceresi içinde scalper cumulative R / DD nedir?
3. Matrix: rows = DD events (örn. 2022-Q2 LUNA / 2024-Q1 ETH ETF), cols = TF (15m/5m/1m)
   Cell = (scalper_R, scalper_DD) within Phoenix DD window

GATING (Phase 5 hard gate)
--------------------------
- Median 90d corr < 0.30 + max corr < 0.50  → PORTFOLIO PASS
- Drawdown overlap: scalper performs >= -%5 R within Phoenix DD windows
  (true diversification = scalper aktif kazanç sağlamasa bile zarar etmemeli)

USAGE
-----
    python scripts/sec31_phoenix_corr_matrix.py --demo            # 1d-only demo
    python scripts/sec31_phoenix_corr_matrix.py \\
        --phoenix-csv reports/lab/phoenix_1d_trades.csv \\
        --scalp-15m   reports/lab/sec31_15m_trades.csv \\
        --scalp-5m    reports/lab/sec32_5m_trades.csv \\
        --scalp-1m    reports/lab/sec33_1m_trades.csv

NOT
---
Bu sprint (Phase 5 prep) **harness skeleton** + 1d self-correlation demo.
Scalper trade CSV'leri Phase 4 sonunda gelir → plug-and-play çalışır.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

# Windows console UTF-8 fix
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# ------------------- Trade Loader (esnek) --------------------------------

CANONICAL_COLUMNS = {
    "ts": ["ts", "exit_ts", "close_ts", "timestamp"],
    "sym": ["sym", "symbol"],
    "side": ["side", "direction"],
    "strategy": ["strategy", "strat"],
    "realized_pnl_usdt": ["realized_pnl_usdt", "pnl_usdt", "pnl"],
    "realized_r": ["realized_r", "R", "r_multiple"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Loose column name → canonical names map."""
    rename: dict[str, str] = {}
    cols_lower = {c.lower(): c for c in df.columns}
    for canon, candidates in CANONICAL_COLUMNS.items():
        for cand in candidates:
            if cand.lower() in cols_lower:
                rename[cols_lower[cand.lower()]] = canon
                break
    return df.rename(columns=rename)


def load_trades_csv(path: Path) -> pd.DataFrame:
    """Load trade-level CSV; conform to canonical columns."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = _normalize_columns(df)
    if "ts" not in df.columns:
        raise ValueError(f"{path.name}: missing ts/exit_ts column")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    # Ensure numeric realized_r (fallback: pnl/risk if missing — accept either)
    if "realized_r" not in df.columns and "realized_pnl_usdt" in df.columns:
        df["realized_r"] = df["realized_pnl_usdt"]  # raw fallback
    if "realized_pnl_usdt" not in df.columns:
        df["realized_pnl_usdt"] = df.get("realized_r", 0.0)
    return df.sort_values("ts").reset_index(drop=True)


def load_phoenix_demo() -> pd.DataFrame:
    """Demo: Phoenix 1d production_replay'in son rolling window'unun trade-serisi
    yerine, SEC11e'nin lab CSV'sini kullan (canonical schema parity yok ama dummy).

    Phase 4'te `reports/lab/phoenix_1d_canonical_trades.csv` üretilecek.
    """
    # Try sec11e CSV (best-effort)
    candidate = ROOT / "reports" / "lab" / "sec11e_new_signals_trades.csv"
    if candidate.exists():
        df = pd.read_csv(candidate)
        df = _normalize_columns(df)
        if "ts" not in df.columns and "exit_ts" in df.columns:
            df["ts"] = df["exit_ts"]
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
            df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)
            return df
    # Last resort: synthetic
    rng = pd.date_range("2023-01-01", "2026-05-01", freq="3D", tz="UTC")
    rs = np.random.default_rng(42)
    return pd.DataFrame({
        "ts": rng,
        "sym": "BTC/USDT",
        "side": rs.choice(["long", "short"], len(rng)),
        "strategy": "synthetic_phoenix",
        "realized_pnl_usdt": rs.normal(50, 200, len(rng)),
        "realized_r": rs.normal(0.5, 1.2, len(rng)),
    })


# ------------------- Daily Aggregation -----------------------------------

def daily_series(trades: pd.DataFrame, value_col: str = "realized_r") -> pd.Series:
    """Trade-level → daily sum series (UTC date index)."""
    if trades.empty:
        return pd.Series(dtype=float)
    df = trades.copy()
    if value_col not in df.columns:
        # Fallback: if value_col missing, use realized_r if present, else 0.0
        if "realized_r" in df.columns:
            value_col = "realized_r"
        else:
            df[value_col] = 0.0
    df["date"] = df["ts"].dt.date
    return df.groupby("date")[value_col].sum().sort_index()


def align_daily(*series: pd.Series) -> pd.DataFrame:
    """Outer-join multiple daily series → fill NA with 0 (no trade = 0 PnL)."""
    if not series:
        return pd.DataFrame()
    out = pd.concat(series, axis=1).sort_index().fillna(0.0)
    return out


# ------------------- Correlation Engine ----------------------------------

@dataclass(frozen=True)
class CorrResult:
    pair: str
    n_obs: int
    pearson_full: float
    spearman_full: float
    pearson_90d_median: float
    pearson_90d_min: float
    pearson_90d_max: float
    spearman_90d_median: float
    pct_windows_above_03: float   # % of 90d windows where pearson > 0.30 (target FAIL)


def rolling_corr(a: pd.Series, b: pd.Series, window: int = 90, method: str = "pearson") -> pd.Series:
    """Rolling correlation (NaN-tolerant). spearman = rank-based fallback."""
    df = pd.concat([a, b], axis=1).fillna(0.0)
    df.columns = ["a", "b"]
    if method == "spearman":
        return _rolling_spearman(df["a"], df["b"], window)
    return df["a"].rolling(window).corr(df["b"])


def _rolling_spearman(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """Rolling Spearman via rank-then-Pearson per window (compute heavier, OK for daily)."""
    arr_a = a.values
    arr_b = b.values
    out = np.full(len(a), np.nan)
    for i in range(window - 1, len(a)):
        sa = pd.Series(arr_a[i - window + 1:i + 1]).rank()
        sb = pd.Series(arr_b[i - window + 1:i + 1]).rank()
        c = sa.corr(sb)
        out[i] = c if c is not None else np.nan
    return pd.Series(out, index=a.index)


def compute_corr_matrix(daily_panel: pd.DataFrame, base_col: str = "phoenix_1d") -> list[CorrResult]:
    """Compute Phoenix 1d × {scalp_TF} correlations."""
    if base_col not in daily_panel.columns:
        raise ValueError(f"base column {base_col} not in panel ({list(daily_panel.columns)})")
    base = daily_panel[base_col]
    results: list[CorrResult] = []
    for col in daily_panel.columns:
        if col == base_col:
            continue
        other = daily_panel[col]
        # full-period pearson + spearman
        full_p = base.corr(other) if base.std() > 0 and other.std() > 0 else np.nan
        full_s = base.corr(other, method="spearman") if base.std() > 0 and other.std() > 0 else np.nan
        # rolling 90d
        roll_p = rolling_corr(base, other, window=90, method="pearson").dropna()
        roll_s = rolling_corr(base, other, window=90, method="spearman").dropna()
        n_above = (roll_p.abs() > 0.30).sum()
        pct_above = float(n_above) / max(len(roll_p), 1) * 100
        results.append(CorrResult(
            pair=f"{base_col} × {col}",
            n_obs=len(daily_panel),
            pearson_full=round(float(full_p), 4) if not pd.isna(full_p) else float("nan"),
            spearman_full=round(float(full_s), 4) if not pd.isna(full_s) else float("nan"),
            pearson_90d_median=round(float(roll_p.median()), 4) if not roll_p.empty else float("nan"),
            pearson_90d_min=round(float(roll_p.min()), 4) if not roll_p.empty else float("nan"),
            pearson_90d_max=round(float(roll_p.max()), 4) if not roll_p.empty else float("nan"),
            spearman_90d_median=round(float(roll_s.median()), 4) if not roll_s.empty else float("nan"),
            pct_windows_above_03=round(pct_above, 1),
        ))
    return results


# ------------------- Drawdown Overlap ------------------------------------

def equity_curve(daily_pnl_usdt: pd.Series, initial: float = 10000.0) -> pd.Series:
    return initial + daily_pnl_usdt.cumsum()


def find_drawdown_windows(equity: pd.Series, min_dd_pct: float = 10.0) -> list[tuple]:
    """Detect peak-to-trough DD windows >= min_dd_pct.

    Returns list of (peak_date, trough_date, dd_pct).
    """
    if equity.empty:
        return []
    cummax = equity.cummax()
    dd = (equity / cummax - 1.0) * 100.0
    windows: list[tuple] = []
    in_dd = False
    peak_idx = equity.index[0]
    for i, (idx, v) in enumerate(dd.items()):
        if v < -1.0 and not in_dd:
            in_dd = True
            peak_idx = cummax[:idx].idxmax() if i > 0 else idx
        elif v >= -0.5 and in_dd:
            # recovered — finalize window
            window_dd = dd[peak_idx:idx].min()
            if window_dd <= -min_dd_pct:
                trough_idx = dd[peak_idx:idx].idxmin()
                windows.append((peak_idx, trough_idx, round(float(window_dd), 2)))
            in_dd = False
    # Tail DD (no recovery)
    if in_dd:
        window_dd = dd[peak_idx:].min()
        if window_dd <= -min_dd_pct:
            trough_idx = dd[peak_idx:].idxmin()
            windows.append((peak_idx, trough_idx, round(float(window_dd), 2)))
    return windows


def scalper_perf_in_window(scalp_daily: pd.Series, peak: pd.Timestamp, trough: pd.Timestamp) -> dict:
    """Within Phoenix DD window: scalper cum R + its own DD."""
    sub = scalp_daily.loc[peak:trough]
    if sub.empty:
        return {"cum_r": 0.0, "max_dd": 0.0, "n_days": 0}
    cum = sub.cumsum()
    cummax = cum.cummax()
    dd = (cum - cummax).min()
    return {
        "cum_r": round(float(sub.sum()), 3),
        "max_dd": round(float(dd), 3),
        "n_days": int(len(sub)),
    }


# ------------------- Main ------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Phoenix 1d × Scalper correlation harness")
    ap.add_argument("--phoenix-csv", default=None, help="Phoenix 1d trades CSV (canonical)")
    ap.add_argument("--scalp-15m", default=None, help="Scalper 15m trades CSV")
    ap.add_argument("--scalp-5m", default=None, help="Scalper 5m trades CSV")
    ap.add_argument("--scalp-1m", default=None, help="Scalper 1m trades CSV")
    ap.add_argument("--demo", action="store_true", help="Run demo with available local CSV")
    args = ap.parse_args()

    print("SEC31: Phoenix 1d × Scalper Correlation Matrix")
    print("=" * 78)

    phoenix = (load_trades_csv(Path(args.phoenix_csv)) if args.phoenix_csv else load_phoenix_demo())
    if phoenix.empty:
        print("  [ERR] no Phoenix trades available (demo OR --phoenix-csv)")
        sys.exit(1)
    print(f"  Phoenix  : n={len(phoenix):>5} trades  range={phoenix['ts'].min().date()} - {phoenix['ts'].max().date()}")

    scalp_loaders = {
        "scalp_15m": args.scalp_15m,
        "scalp_5m": args.scalp_5m,
        "scalp_1m": args.scalp_1m,
    }
    scalp_dfs: dict[str, pd.DataFrame] = {}
    for label, path in scalp_loaders.items():
        if path:
            df = load_trades_csv(Path(path))
            if not df.empty:
                scalp_dfs[label] = df
                print(f"  {label:<9}: n={len(df):>5} trades  range={df['ts'].min().date()} - {df['ts'].max().date()}")
            else:
                print(f"  {label:<9}: [SKIP] CSV empty/missing ({path})")

    if not scalp_dfs and args.demo:
        # Demo: bootstrap synthetic scalp series from phoenix (uncorrelated)
        print()
        print("  [DEMO] no scalp CSV — generating UNCORRELATED synthetic scalp_15m for harness check")
        rng = pd.date_range(phoenix["ts"].min().date(), phoenix["ts"].max().date(), freq="D", tz="UTC")
        rs = np.random.default_rng(7)
        scalp_dfs["scalp_15m_demo"] = pd.DataFrame({
            "ts": rng,
            "realized_r": rs.normal(0.05, 0.4, len(rng)),
            "realized_pnl_usdt": rs.normal(20, 80, len(rng)),
        })

    # Daily aggregation
    print()
    print("  Daily aggregation (R-based + USDT-based)...")
    phoenix_daily_r = daily_series(phoenix, "realized_r").rename("phoenix_1d")
    phoenix_daily_usd = daily_series(phoenix, "realized_pnl_usdt").rename("phoenix_1d")

    panel_cols: dict[str, pd.Series] = {"phoenix_1d": phoenix_daily_r}
    panel_usd_cols: dict[str, pd.Series] = {"phoenix_1d": phoenix_daily_usd}
    for label, df in scalp_dfs.items():
        panel_cols[label] = daily_series(df, "realized_r").rename(label)
        panel_usd_cols[label] = daily_series(df, "realized_pnl_usdt").rename(label)

    panel = align_daily(*panel_cols.values())
    panel.columns = list(panel_cols.keys())

    # Correlation matrix
    if len(panel.columns) > 1:
        print()
        print("CORRELATION RESULTS (R-based daily series, 90d rolling)")
        print("-" * 78)
        results = compute_corr_matrix(panel, base_col="phoenix_1d")
        header = f"{'pair':<32}{'n':>6}{'pearson':>10}{'spearman':>10}{'r90dmed':>10}{'%>0.30':>10}"
        print(header)
        print("-" * 78)
        for r in results:
            print(
                f"{r.pair:<32}{r.n_obs:>6}{r.pearson_full:>10.3f}{r.spearman_full:>10.3f}"
                f"{r.pearson_90d_median:>10.3f}{r.pct_windows_above_03:>9.1f}%"
            )
        print()
        print("  GATE: pearson_full < 0.30 + r90dmed < 0.30 + %above0.30 < %20  → PORTFOLIO PASS")

    # Drawdown overlap
    if len(panel.columns) > 1:
        print()
        print("PHOENIX DRAWDOWN OVERLAP (scalper performance within Phoenix DD windows)")
        print("-" * 78)
        phoenix_eq = equity_curve(panel_usd_cols["phoenix_1d"])
        dd_windows = find_drawdown_windows(phoenix_eq, min_dd_pct=10.0)
        if not dd_windows:
            print("  [INFO] no Phoenix DD windows >= -%10 in this series (demo data clean)")
        else:
            print(f"  {len(dd_windows)} DD window(s) detected (>= -%10):")
            print(f"  {'peak':<12}{'trough':<12}{'phoenix_dd%':>14}", end="")
            for label in scalp_dfs:
                print(f"{label + '_R':>18}", end="")
            print()
            for peak, trough, dd in dd_windows[:10]:
                line = f"  {str(peak)[:10]:<12}{str(trough)[:10]:<12}{dd:>14.2f}"
                for label in scalp_dfs:
                    scalp_d = daily_series(scalp_dfs[label], "realized_r")
                    perf = scalper_perf_in_window(scalp_d, peak, trough)
                    line += f"{perf['cum_r']:>14.2f}({perf['n_days']:>2}d)"
                print(line)

    print()
    print("=" * 78)
    print("DONE — bu harness scalper CSV'leri Phase 4 sonunda gelince plug-and-play çalışır")


if __name__ == "__main__":
    main()
