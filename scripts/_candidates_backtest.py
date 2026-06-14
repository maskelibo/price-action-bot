"""Aday sembol backtest screen — BCH/TRX/UNI/AAVE/LTC/ATOM/ICP/ALGO.

ZEC/NEAR/FIL/XLM ekleme metodolojisini (scripts/_expansion_vsa_pool_build.py)
birebir tekrarlar: vsa_climax_test + brooks_failed_breakout, aynı fee/slip,
her sembol KENDİ listing tarihinden (survivorship yok). Ayrı DB'ye yazar,
canlı daemon'lara dokunmaz.

Çıktı: her aday için strateji-bazında n_trade / win% / mean_R / total_R,
mevcut 14'ün baseline'ı ile kıyas → "edge var mı" verdikti.

Usage:
  .venv/bin/python scripts/_candidates_backtest.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging

logging.getLogger("price_action").setLevel(logging.ERROR)

import duckdb
import pandas as pd

from price_action.backtest.engine import BacktestEngine
from price_action.signals.filters import volume_zscore
from price_action.strategies.brooks_failed_breakout import (
    BrooksFailedBreakoutStrategy,
)
from price_action.strategies.brooks_failed_breakout import (
    _default_manifest as brooks_manifest,
)
from price_action.strategies.vsa_climax_test import (
    VSAClimaxTestStrategy,
)
from price_action.strategies.vsa_climax_test import (
    _default_manifest as vsa_manifest,
)

CAND_DB = ROOT / "data" / "market_candidates_15m.duckdb"
MAIN_DB = ROOT / "data" / "market.duckdb"

CANDIDATES = [
    "BCH/USDT",
    "TRX/USDT",
    "UNI/USDT",
    "AAVE/USDT",
    "LTC/USDT",
    "ATOM/USDT",
    "ICP/USDT",
    "ALGO/USDT",
]
# Baseline kıyas: mevcut 14'ten temsilciler (market.duckdb'de var)
BASELINE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "ZEC/USDT"]


def load_ohlcv(db_path: Path, symbol: str, tf: str = "15m", venue: str = "binance") -> pd.DataFrame:
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


def gather(strategy, db_path: Path, sym: str, strat_name: str, tf: str = "15m") -> list[dict]:
    """Replicate expansion gather: run strategy through BacktestEngine, full history."""
    df = load_ohlcv(db_path, sym, tf=tf)
    if df is None or df.empty:
        return []
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = tf
    try:
        df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
    except Exception:
        rolling = df["volume"].rolling(20)
        df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(
        strategy,
        [sym],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe=tf,
        initial_capital=10_000.0,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=prov,
    )
    out = []
    for _, t in r.trades.iterrows():
        try:
            out.append(
                {
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym,
                    "strategy": strat_name,
                }
            )
        except Exception:
            continue
    return out


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "win": 0.0, "mean_R": 0.0, "median_R": 0.0, "total_R": 0.0}
    rs = [t["R"] for t in trades]
    wins = sum(1 for x in rs if x > 0)
    return {
        "n": len(rs),
        "win": wins / len(rs) * 100,
        "mean_R": mean(rs),
        "median_R": median(rs),
        "total_R": sum(rs),
    }


def ensure_data():
    """Adaylar için 15m tam geçmiş çek (yoksa). market_candidates_15m.duckdb."""
    from price_action.data.ingest_ccxt import ingest_symbol
    from price_action.data.store import OHLCVStore

    store = OHLCVStore(path=str(CAND_DB), force_write=True)
    # mevcut barları say
    have = {}
    try:
        con = duckdb.connect(str(CAND_DB), read_only=True)
        for row in con.execute(
            "SELECT symbol, count(*) FROM ohlcv WHERE timeframe='15m' GROUP BY symbol"
        ).fetchall():
            have[row[0]] = row[1]
        con.close()
    except Exception:
        pass
    print("=== VERİ ÇEKME (15m tam geçmiş) ===")
    for sym in CANDIDATES:
        if have.get(sym, 0) > 1000:
            print(f"  {sym:10s} zaten var ({have[sym]} bar) — atla")
            continue
        t0 = time.time()
        try:
            st = ingest_symbol(venue="binance", symbol=sym, timeframe="15m", years=5, store=store)
            print(f"  {sym:10s} çekildi: {st.rows_written} bar ({time.time()-t0:.0f}s)")
        except Exception as exc:
            print(f"  {sym:10s} HATA: {str(exc)[:80]}")
    from price_action.data.store import close_pool_for_path

    close_pool_for_path(str(CAND_DB))


def main():
    ensure_data()
    print("\n=== BACKTEST (vsa_climax_test + brooks_failed_breakout) ===\n")

    results = {}
    for label, syms, db in [
        ("ADAYLAR", CANDIDATES, CAND_DB),
        ("BASELINE (mevcut 14)", BASELINE, MAIN_DB),
    ]:
        print(f"--- {label} ---")
        for sym in syms:
            t0 = time.time()
            vsa = gather(VSAClimaxTestStrategy(vsa_manifest()), db, sym, "vsa")
            brk = gather(BrooksFailedBreakoutStrategy(brooks_manifest()), db, sym, "brooks")
            results[sym] = {"vsa": summarize(vsa), "brooks": summarize(brk)}
            sv, sb = results[sym]["vsa"], results[sym]["brooks"]
            print(
                f"  {sym:10s} vsa[n={sv['n']:>4} win={sv['win']:4.1f}% "
                f"meanR={sv['mean_R']:+.3f} totR={sv['total_R']:+7.0f}]  "
                f"brooks[n={sb['n']:>4} win={sb['win']:4.1f}% "
                f"meanR={sb['mean_R']:+.3f} totR={sb['total_R']:+7.0f}]  ({time.time()-t0:.0f}s)"
            )

    # Baseline ortalama eşiği
    base_vsa_mean = mean(
        [results[s]["vsa"]["mean_R"] for s in BASELINE if results[s]["vsa"]["n"] > 50]
    )
    base_brk_mean = mean(
        [results[s]["brooks"]["mean_R"] for s in BASELINE if results[s]["brooks"]["n"] > 50]
    )
    print(
        f"\n=== BASELINE eşiği: vsa mean_R={base_vsa_mean:+.3f} | brooks mean_R={base_brk_mean:+.3f} ==="
    )

    print("\n=== VERDİKT (aday — fee sonrası edge) ===")
    ranked = []
    for sym in CANDIDATES:
        v, b = results[sym]["vsa"], results[sym]["brooks"]
        # combined: hangi strateji daha iyi, toplam R
        best = max(v["mean_R"], b["mean_R"])
        tot = v["total_R"] + b["total_R"]
        n = v["n"] + b["n"]
        ranked.append((sym, best, tot, n, v, b))
    ranked.sort(key=lambda x: -x[2])
    for sym, best, tot, n, v, b in ranked:
        verdict = (
            "✅ GÜÇLÜ"
            if (best > 0.10 and n > 200 and tot > 0)
            else ("🟡 ZAYIF" if (best > 0 and tot > 0) else "❌ EDGE YOK")
        )
        print(f"  {sym:10s} {verdict:10s} en-iyi mean_R={best:+.3f} toplam_R={tot:+7.0f} n={n}")


if __name__ == "__main__":
    main()
