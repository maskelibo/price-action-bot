"""Build 1h backtest pool (sec53 schema) from 15m OHLCV via resample.

YOL_HARITASI §5 adım-1 / Faz 10.2 pool-builder TODO
(configs/tf_expansion_targets.yaml: builders.1h = scripts/build_pool_1h.py).
Fizibilite: reports/audit/dalga5/A3_multi_tf_fizibilite.md §5 Aşama-0.

PIPELINE (sec53_15m_pool_v11.pkl üreten hattın 1h portu — bit-uyumlu desen):
  1. data/market.duckdb (saatlik atomik snapshot, READ-ONLY) → 19 sembol 15m OHLCV
  2. 15m → 1h resample: resample("1h", label="left", closed="left"),
     open=first / high=max / low=min / close=last / volume=sum
     (scripts/futures_trade_30m45m.py::_resample_5m_to ile aynı kural).
     INCOMPLETE-BAR DÜŞÜRME: 4'ten az 15m barı içeren 1h kovaları atılır
     (forming/leading partial + orta-seri gap saatleri) — lookahead yok,
     yarım bar yok.
  3. TOP-4 strateji (vsa_climax_test, brooks_failed_breakout,
     anchored_vwap_reversal, engulfing_continuation) × 19 sembol
     BacktestEngine ile koşulur. df["timeframe"]="1h" olduğundan
     apply_tf_manifest() manifests/<strategy>_1h.yaml override'ını
     OTOMATİK uygular (4'ünün de 1h manifesti mevcut).
     Fees/slippage sec53 hattıyla aynı: taker 7.5bps / maker -1bps / slip 5bps.
  4. Trade → pool-dict eşlemesi scripts/sec31_phoenix_scalp_15m_rolling.py::
     _gather_peakR_single ile SATIR-SATIR aynı (entry_ts, exit_ts, entry_price,
     initial_sl, R, peak_R, symbol, side, conf, strategy, vol_z).

Çıktı: data/sec53_1h_pool_v1.pkl  (list[dict], sec53_15m_pool_v11.pkl şeması)

NOT: tf_exploration_runner.py 1h için data/sec53_1h_pool_v11.pkl bekler;
bu builder'ın çıktısı doğrulandıktan sonra o ada kopyalanabilir:
    cp data/sec53_1h_pool_v1.pkl data/sec53_1h_pool_v11.pkl

Usage:
    .venv/bin/python scripts/build_pool_1h.py --symbols BTC/USDT,ETH/USDT,SOL/USDT
    .venv/bin/python scripts/build_pool_1h.py                 # 19 sembol tam koşu
    .venv/bin/python scripts/build_pool_1h.py --mode parity   # parite raporu yaz

Canlı bota / journal'a / mevcut pool dosyalarına DOKUNMAZ. DB read-only.
"""
# ruff: noqa: E402, N806  (script deseni + R-domain adlandırma — 2026-07-10)

from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from pathlib import Path

os.environ.setdefault("PA_LOG_QUIET", "1")
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

# ── Config ───────────────────────────────────────────────────────────────────
DB_PATH = ROOT / "data" / "market.duckdb"  # atomik snapshot — read-only güvenli
OUT_DEFAULT = ROOT / "data" / "sec53_1h_pool_v1.pkl"
PARITY_REPORT = ROOT / "reports" / "research" / "pool_1h_parity.md"

TF_SRC = "15m"
TF_DST = "1h"
TARGET_BARS_PER_BUCKET = {
    "30m": 2,
    "1h": 4,
    "4h": 16,
}
TARGET_PANDAS_FREQ = {
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
}
BARS_PER_BUCKET = TARGET_BARS_PER_BUCKET[TF_DST]

# sec53 pool'unun TOP-4 stratejisi (verify_sec53_pool.py EXPECTED_STRATEGIES)
TOP4_STRATEGIES: list[tuple[str, str]] = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]

# 19-sembol 15m evreni (18 trading + UNI data-only) — DB ile runtime'da doğrulanır
SYMBOLS_19: list[str] = [
    "AAVE/USDT",
    "ADA/USDT",
    "ALGO/USDT",
    "ATOM/USDT",
    "AVAX/USDT",
    "BNB/USDT",
    "BTC/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "ETH/USDT",
    "FIL/USDT",
    "LINK/USDT",
    "NEAR/USDT",
    "SOL/USDT",
    "TRX/USDT",
    "UNI/USDT",
    "XLM/USDT",
    "XRP/USDT",
    "ZEC/USDT",
]

FEES = {"taker": 0.00075, "maker": -0.00010}
SLIPPAGE_BPS = 5.0
INITIAL_CAPITAL = 10_000.0


# ── Data loading + resample ──────────────────────────────────────────────────
def load_15m(symbol: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    """15m OHLCV'yi read-only DuckDB'den çek (run_real_backtest._load_symbol_ohlcv deseni)."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            ["binance", symbol, TF_SRC],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def resample_15m(df_15m: pd.DataFrame, target_tf: str) -> tuple[pd.DataFrame, dict]:
    """15m barları desteklenen daha yüksek bir timeframe'e resample et.

    ``label='left', closed='left'`` ile damga bar-open zamanıdır; karar
    bar kapanmadan görünmez. Hedef kovadaki 15m bar sayısı tam değilse kova
    düşürülür. Bu, forming bar ve veri-gap'lerinin sahte OHLC üretmesini önler.
    """
    if target_tf not in TARGET_BARS_PER_BUCKET:
        raise ValueError(
            f"Desteklenmeyen hedef timeframe: {target_tf!r}; "
            f"beklenen={sorted(TARGET_BARS_PER_BUCKET)}"
        )
    bars_per_bucket = TARGET_BARS_PER_BUCKET[target_tf]
    if df_15m.empty:
        return pd.DataFrame(), {"n_src": 0, "n_buckets": 0, "n_complete": 0, "n_dropped": 0}
    g = df_15m.set_index("ts").resample(
        TARGET_PANDAS_FREQ[target_tf], label="left", closed="left"
    )
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    cnt = g["close"].count()
    n_buckets = int((cnt > 0).sum())
    complete_mask = cnt == bars_per_bucket
    out = out[complete_mask].dropna().reset_index()
    stats = {
        "n_src": len(df_15m),
        "n_buckets": n_buckets,
        "n_complete": len(out),
        "n_dropped": n_buckets - len(out),
    }
    return out, stats


def resample_15m_to_1h(df_15m: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Backward-compatible 1h wrapper used by the parity audit."""
    return resample_15m(df_15m, "1h")


# ── Pool gather (sec31 _gather_peakR_single'ın 1h portu) ─────────────────────
def gather_cell(
    module_name: str,
    class_name: str,
    sym: str,
    df_tf: pd.DataFrame,
    target_tf: str = TF_DST,
) -> list[dict]:
    """Tek (strateji, sembol) hücresi — sec31_phoenix_scalp_15m_rolling ile aynı eşleme."""
    try:
        mod = __import__(
            f"price_action.strategies.{module_name}",
            fromlist=[class_name, "_default_manifest"],
        )
        cls = getattr(mod, class_name, None)
        if cls is None:
            for name in dir(mod):
                if name.endswith("Strategy") and not name.startswith("_"):
                    cls = getattr(mod, name)
                    break
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn or not cls:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [SKIP] {module_name}/{sym}: import ({e})")
        return []

    df = df_tf.copy()
    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = target_tf
    try:
        df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
    except Exception:
        rolling = df["volume"].rolling(20)
        df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

    def prov(*a, **k):
        return df.copy()

    try:
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(
            s,
            [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe=target_tf,
            initial_capital=INITIAL_CAPITAL,
            fees=FEES,
            slippage_bps=SLIPPAGE_BPS,
            ohlcv_provider=prov,
        )
    except Exception as ex:
        print(f"  [ERR] {module_name}/{sym}: run {ex}")
        return []

    out: list[dict] = []
    ts_map = pd.to_datetime(df["ts"], utc=True)
    for _, t in r.trades.iterrows():
        try:
            conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            entry_price = float(t["entry_price"])
            initial_sl = float(t["initial_sl"])
            mfe_pct = float(t.get("mfe_pct", 0))
            risk_pct = abs(initial_sl - entry_price) / entry_price if entry_price > 0 else 0.04
            side = str(t["side"]).lower()
            if side == "long":
                peak_R = mfe_pct / risk_pct if risk_pct > 0 else 0
            else:
                peak_R = -mfe_pct / risk_pct if risk_pct > 0 else 0
            final_R = float(t["realized_r_multiple"])
            peak_R = max(peak_R, final_R)
            # P2-#12 (2026-07-10): mae_R — MTM stress bandının gerçek-MAE işareti.
            # peak_R'nin simetriği (engine mae_pct'yi zaten üretiyor; eski pool'lar
            # taşımıyordu → -1R fallback). Konvansiyon: mae_R <= 0 (aleyhte-en-kötü).
            mae_pct = float(t.get("mae_pct", 0) or 0)
            if side == "long":
                mae_R = mae_pct / risk_pct if risk_pct > 0 else 0.0
            else:
                mae_R = -mae_pct / risk_pct if risk_pct > 0 else 0.0
            mae_R = min(mae_R, 0.0, final_R)  # aleyhte-uç final'den iyi olamaz

            ts_e = pd.Timestamp(t["entry_ts"])
            if ts_e.tzinfo is None:
                ts_e = ts_e.tz_localize("UTC")
            ts_x = pd.Timestamp(t["exit_ts"])
            if ts_x.tzinfo is None:
                ts_x = ts_x.tz_localize("UTC")

            mask = ts_map < ts_e
            vz = 0.0
            if mask.any():
                idx = ts_map[mask].index[-1]
                vz_val = df["vol_z_pre"].iloc[idx]
                vz = float(vz_val) if not pd.isna(vz_val) else 0.0

            out.append(
                {
                    "entry_ts": ts_e,
                    "exit_ts": ts_x,
                    "entry_price": entry_price,
                    "initial_sl": initial_sl,
                    "R": final_R,
                    "peak_R": peak_R,
                    "mae_R": mae_R,  # P2-#12: MTM stress gerçek-MAE (yoksa tüketici -1R'a düşer)
                    "symbol": sym,
                    "side": str(t["side"]),
                    "conf": conf,
                    "strategy": module_name,
                    "vol_z": vz,
                }
            )
        except Exception:
            continue
    return out


# ── Build mode ───────────────────────────────────────────────────────────────
def run_build(symbols: list[str], out_path: Path, target_tf: str = TF_DST) -> int:
    t_start = time.time()
    pool: list[dict] = []
    resample_rows = []

    if target_tf not in TARGET_BARS_PER_BUCKET:
        raise ValueError(f"Desteklenmeyen hedef timeframe: {target_tf!r}")
    print(
        f"=== build_pool_{target_tf} — {len(symbols)} sembol × "
        f"{len(TOP4_STRATEGIES)} strateji ==="
    )
    print(f"DB: {DB_PATH} (read-only)  →  OUT: {out_path}")

    for sym in symbols:
        t_sym = time.time()
        df_15m = load_15m(sym)
        if df_15m.empty:
            print(f"  [WARN] {sym}: 15m verisi yok — atlandı")
            continue
        df_tf, rs = resample_15m(df_15m, target_tf)
        resample_rows.append((sym, rs))
        if df_tf.empty:
            print(f"  [WARN] {sym}: resample sonrası boş — atlandı")
            continue
        sym_trades = 0
        for module_name, class_name in TOP4_STRATEGIES:
            t_cell = time.time()
            trades = gather_cell(module_name, class_name, sym, df_tf, target_tf)
            pool.extend(trades)
            sym_trades += len(trades)
            print(
                f"  {sym:11s} {module_name:24s} {len(trades):>6d} trade "
                f"({time.time()-t_cell:.1f}s)"
            )
        print(
            f"  {sym:11s} TOPLAM {sym_trades:>6d} trade | 15m={rs['n_src']:,} → "
            f"{target_tf}={rs['n_complete']:,} (dropped {rs['n_dropped']}) "
            f"({time.time()-t_sym:.1f}s)"
        )

    if not pool:
        print("[FATAL] pool boş — hiçbir hücre trade üretmedi")
        return 1

    pool.sort(key=lambda t: (t["entry_ts"], t["symbol"], t["strategy"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        pickle.dump(pool, fh)

    # ── Özet ──
    elapsed = time.time() - t_start
    from collections import Counter

    strat_counts = Counter(t["strategy"] for t in pool)
    sym_counts = Counter(t["symbol"] for t in pool)
    ts_all = [t["entry_ts"] for t in pool]
    print(f"\n[OUT] {out_path}  —  {len(pool):,} trade  ({elapsed/60:.1f} dk)")
    print(f"  tarih aralığı: {min(ts_all)} → {max(ts_all)}")
    print("  strateji dağılımı:")
    for k, v in strat_counts.most_common():
        print(f"    {k:26s} {v:>7,}")
    print("  sembol dağılımı:")
    for k in sorted(sym_counts):
        print(f"    {k:12s} {sym_counts[k]:>7,}")
    print(f"  resample özeti (sembol: 15m→{target_tf}, dropped-incomplete):")
    for sym, rs in resample_rows:
        print(
            f"    {sym:12s} {rs['n_src']:>8,} → {rs['n_complete']:>7,}  (dropped {rs['n_dropped']})"
        )
    return 0


# ── Parity mode ──────────────────────────────────────────────────────────────
PARITY_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
PARITY_START = pd.Timestamp("2026-04-01", tz="UTC")
PARITY_END = pd.Timestamp("2026-05-01", tz="UTC")  # 30 gün; DB 1h kapsamı içinde


def _load_db_1h(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Bağımsız kaynak: borsadan ingest edilmiş 1h barlar (DB'de mevcut, 10 major)."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE venue='binance' AND symbol=? AND timeframe='1h' "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            [symbol, start.to_pydatetime(), end.to_pydatetime()],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _sql_agg_1h(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """İkinci bağımsız hesap yolu: pandas'sız, saf SQL saat-kovası agregasyonu.

    time_bucket UTC-epoch bazlı → session timezone'dan bağımsız.
    Yalnız 4-barlı (complete) kovalar döner — builder kuralının SQL ikizi.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT time_bucket(INTERVAL 1 HOUR, ts) AS ts,
                   first(open ORDER BY ts)  AS open,
                   max(high)                AS high,
                   min(low)                 AS low,
                   last(close ORDER BY ts)  AS close,
                   sum(volume)              AS volume,
                   count(*)                 AS n
            FROM ohlcv
            WHERE venue='binance' AND symbol=? AND timeframe='15m'
              AND ts >= ? AND ts < ?
            GROUP BY 1 HAVING count(*)=4 ORDER BY 1
            """,
            [symbol, start.to_pydatetime(), end.to_pydatetime()],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.drop(columns=["n"])


def run_parity(report_path: Path = PARITY_REPORT) -> int:
    """3 sembol × 30 gün: resample'lı 1h barları iki bağımsız kaynakla karşılaştır.

    A) DB'deki borsa-ingest 1h barları (tam bağımsız veri yolu)
    B) Saf-SQL saat-kovası agregasyonu (pandas resample'ın bağımsız ikizi)
    PASS eşiği (B1 blocker disipliniyle aynı): max close diff < 0.1%.
    """
    lines: list[str] = []
    w = lines.append
    w("# 1h Pool Resample Parite Raporu")
    w("")
    w(f"- **Tarih:** {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}")
    w("- **Üretici:** `scripts/build_pool_1h.py --mode parity`")
    w(
        f"- **Pencere:** {PARITY_START.date()} → {PARITY_END.date()} (30 gün) × {len(PARITY_SYMBOLS)} sembol"
    )
    w(
        f"- **Kural:** `resample('1h', label='left', closed='left')`, open=first/high=max/low=min/close=last/volume=sum, "
        f"kovada <{BARS_PER_BUCKET} × 15m bar varsa DÜŞ (incomplete-bar kuralı)"
    )
    w("- **PASS eşiği:** max |close diff| < 0.1% (B1 resample-parity blocker disiplini)")
    w("")

    all_pass = True

    # ── A) borsa-ingest 1h vs resample ──
    w("## A) Resample(15m→1h) vs borsa-ingest 1h (DB `timeframe='1h'` — bağımsız veri yolu)")
    w("")
    w(
        "| sembol | n_resample | n_db_1h | n_ortak | max\\|Δopen\\|% | max\\|Δhigh\\|% | max\\|Δlow\\|% | max\\|Δclose\\|% | max\\|Δvol\\|% | sonuç |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|")
    for sym in PARITY_SYMBOLS:
        df_15m = load_15m(sym)
        df_15m = df_15m[(df_15m["ts"] >= PARITY_START) & (df_15m["ts"] < PARITY_END)]
        df_rs, _ = resample_15m_to_1h(df_15m)
        df_db = _load_db_1h(sym, PARITY_START, PARITY_END)
        if df_db.empty or df_rs.empty:
            w(f"| {sym} | {len(df_rs)} | {len(df_db)} | — | — | — | — | — | — | NO_DATA |")
            all_pass = False
            continue
        m = df_rs.merge(df_db, on="ts", suffixes=("_rs", "_db"))
        diffs = {}
        for col in ["open", "high", "low", "close", "volume"]:
            denom = m[f"{col}_db"].replace(0, pd.NA).astype(float)
            d = ((m[f"{col}_rs"] - m[f"{col}_db"]).abs() / denom * 100).fillna(0.0)
            diffs[col] = float(d.max()) if len(d) else float("nan")
        ok = diffs["close"] < 0.1
        all_pass &= ok
        w(
            f"| {sym} | {len(df_rs)} | {len(df_db)} | {len(m)} | {diffs['open']:.6f} | "
            f"{diffs['high']:.6f} | {diffs['low']:.6f} | {diffs['close']:.6f} | "
            f"{diffs['volume']:.6f} | {'PASS' if ok else 'FAIL'} |"
        )
    w("")

    # ── B) saf-SQL agregasyon vs pandas resample ──
    # OHLC = eleman seçimi (first/max/min/last) → BIT-IDENTICAL olmalı.
    # volume = float toplam; pandas ile SQL toplama SIRASI farklı olabilir →
    # 1e-9 göreli tolerans (saf float-associativity gürültüsü).
    w("## B) pandas resample vs saf-SQL saat-kovası (bağımsız hesap yolu, aynı 15m veri)")
    w("")
    w(
        "| sembol | n_pandas | n_sql | n_ortak | max\\|Δohlc\\| (mutlak) | max\\|Δvol\\| (göreli) | sonuç |"
    )
    w("|---|---|---|---|---|---|---|")
    for sym in PARITY_SYMBOLS:
        df_15m = load_15m(sym)
        df_15m = df_15m[(df_15m["ts"] >= PARITY_START) & (df_15m["ts"] < PARITY_END)]
        df_rs, _ = resample_15m_to_1h(df_15m)
        df_sql = _sql_agg_1h(sym, PARITY_START, PARITY_END)
        m = df_rs.merge(df_sql, on="ts", suffixes=("_p", "_s"))
        max_ohlc = 0.0
        for col in ["open", "high", "low", "close"]:
            if len(m):
                max_ohlc = max(max_ohlc, float((m[f"{col}_p"] - m[f"{col}_s"]).abs().max()))
        max_vol_rel = 0.0
        if len(m):
            denom = m["volume_s"].astype(float).abs().clip(lower=1e-12)
            max_vol_rel = float(((m["volume_p"] - m["volume_s"]).abs() / denom).max())
        ok = len(m) == len(df_rs) == len(df_sql) and max_ohlc == 0.0 and max_vol_rel < 1e-9
        all_pass &= ok
        w(
            f"| {sym} | {len(df_rs)} | {len(df_sql)} | {len(m)} | {max_ohlc:.10f} | "
            f"{max_vol_rel:.2e} | {'PASS (ohlc bit-identical)' if ok else 'FAIL'} |"
        )
    w("")

    # ── C) elle doğrulanabilir örnek barlar ──
    w("## C) Elle doğrulanabilir örnek (BTC/USDT, ilk 3 saat)")
    w("")
    sym = "BTC/USDT"
    df_15m = load_15m(sym)
    df_15m = df_15m[
        (df_15m["ts"] >= PARITY_START) & (df_15m["ts"] < PARITY_START + pd.Timedelta(hours=3))
    ]
    df_rs, _ = resample_15m_to_1h(df_15m)
    w("15m ham barlar:")
    w("")
    w("| ts (UTC) | open | high | low | close | volume |")
    w("|---|---|---|---|---|---|")
    for _, r in df_15m.iterrows():
        w(f"| {r['ts']} | {r['open']} | {r['high']} | {r['low']} | {r['close']} | {r['volume']} |")
    w("")
    w(
        "Resample çıktısı 1h barlar (open=ilk 15m open, high=max, low=min, close=son 15m close, volume=Σ):"
    )
    w("")
    w("| ts (UTC) | open | high | low | close | volume |")
    w("|---|---|---|---|---|---|")
    for _, r in df_rs.iterrows():
        w(f"| {r['ts']} | {r['open']} | {r['high']} | {r['low']} | {r['close']} | {r['volume']} |")
    w("")

    w("## Sonuç")
    w("")
    w(
        f"**{'PASS' if all_pass else 'FAIL'}** — "
        + (
            "resample hattı hem borsa-ingest 1h ile (<0.1%) hem saf-SQL agregasyonla (bit-identical) uyumlu; "
            "1h pool inşasında kullanım ONAYLI."
            if all_pass
            else "en az bir karşılaştırma eşiği aştı — pool'u kullanmadan önce incele."
        )
    )
    w("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OUT] parite raporu: {report_path}  —  {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="1h backtest pool builder (sec53 şeması)")
    p.add_argument("--mode", choices=["build", "parity"], default="build")
    p.add_argument(
        "--timeframe",
        choices=sorted(TARGET_BARS_PER_BUCKET),
        default="1h",
        help="15m kaynaktan üretilecek hedef timeframe.",
    )
    p.add_argument(
        "--symbols", default="", help="Virgüllü alt-küme (örn: BTC/USDT,ETH/USDT). Boş = 19 sembol."
    )
    p.add_argument(
        "--out", type=Path, default=None, help="Pool çıktı yolu (verilmezse timeframe'e göre seçilir)."
    )
    args = p.parse_args()

    if args.mode == "parity":
        if args.timeframe != "1h":
            p.error("parity modu yalnız bağımsız DB 1h barları bulunduğu için --timeframe 1h destekler")
        return run_parity()

    out_path = args.out
    if out_path is None:
        out_path = OUT_DEFAULT if args.timeframe == "1h" else ROOT / "data" / f"sec53_{args.timeframe}_pool_v11.pkl"

    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else SYMBOLS_19
    )
    unknown = [s for s in symbols if s not in SYMBOLS_19]
    if unknown:
        print(f"[WARN] 19-sembol evreninde olmayan semboller: {unknown}")
    return run_build(symbols, out_path, args.timeframe)


if __name__ == "__main__":
    sys.exit(main())
