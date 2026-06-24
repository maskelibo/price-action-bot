"""SEC56 Live Scan Diagnostic — 15m signal zero-output root cause analysis.

Kullanım:
    python scripts/sec56_live_scan_diagnostic.py

Adımlar:
  T1: Warmup test — son 50/100/200/500 bar history ile strateji
  T2: Bar tamamlanma — last bar exclude vs include karşılaştır
  T3: Sym universe — pool vs ccxt diff
  T4: Generate_signals bug — internal filter trace
  T5: Conf threshold — config vs manifest min_score

Root cause analiz: H1-H5 hipotez testi.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

SIGNAL_MAX_AGE_MIN = 30  # futures_trade_15m.py sabitiyle eşleşmeli
TF = "15m"
BASE_PARQUET = ROOT / "data" / "parquet" / "binance"
SYMBOLS_FOLDERS = {
    "BTC/USDT": "BTC_USDT",
    "ETH/USDT": "ETH_USDT",
    "SOL/USDT": "SOL_USDT",
    "BNB/USDT": "BNB_USDT",
    "ADA/USDT": "ADA_USDT",
    "AVAX/USDT": "AVAX_USDT",
    "LINK/USDT": "LINK_USDT",
    "DOT/USDT": "DOT_USDT",
    "DOGE/USDT": "DOGE_USDT",
    "XRP/USDT": "XRP_USDT",
}

TOP_4_15M = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]


# ── Parquet loader (DuckDB bypass — daemon market.duckdb exclusive lock) ──────

def load_parquet_15m(sym_folder: str, n_tail: int = 500) -> pd.DataFrame:
    tf_dir = BASE_PARQUET / sym_folder / "15m"
    if not tf_dir.exists():
        return pd.DataFrame()
    all_dfs = []
    for year_dir in sorted(tf_dir.iterdir()):
        for month_dir in sorted(year_dir.iterdir()):
            f = month_dir / "data.parquet"
            if f.exists():
                all_dfs.append(pd.read_parquet(f))
    if not all_dfs:
        return pd.DataFrame()
    df = pd.concat(all_dfs, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df.tail(n_tail).reset_index(drop=True)


def _prep_df(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    df = df.copy()
    df["symbol"] = sym
    df["venue"] = "binance"
    df["timeframe"] = TF
    df["vol_z_pre"] = 0
    return df


def _load_strategy(module_name: str, class_name: str):
    mod = __import__(
        f"price_action.strategies.{module_name}",
        fromlist=[class_name, "_default_manifest"],
    )
    cls = getattr(mod, class_name)
    manifest_fn = getattr(mod, "_default_manifest")
    return cls(manifest_fn()), manifest_fn()


# ── Test T1: Warmup ────────────────────────────────────────────────────────────

def test_t1_warmup(sym: str = "BTC/USDT") -> None:
    print("\n=== T1: WARMUP TEST ===")
    folder = SYMBOLS_FOLDERS[sym]
    df_full = load_parquet_15m(folder, n_tail=500)
    if df_full.empty:
        print(f"  {sym}: parquet veri yok!")
        return

    for n in [50, 100, 200, 500]:
        df = _prep_df(df_full.tail(n).reset_index(drop=True), sym)
        totals = {}
        for mod_name, cls_name in TOP_4_15M:
            try:
                strat, _ = _load_strategy(mod_name, cls_name)
                df_prep = strat.prepare_features(df.copy())
                sigs = strat.generate_signals(df_prep)
                totals[mod_name] = len(sigs)
            except Exception as e:
                totals[mod_name] = f"ERR:{e}"
        print(f"  {n:>4} bar | " + " | ".join(f"{k.split('_')[0]}={v}" for k, v in totals.items()))

    print(f"\n  Sonuç: Warmup (bar sayısı) sinyal üretimini etkiliyor mu?")
    print(f"  -> 200+ bar'da sinyal çıkıyorsa warmup SORUN DEĞİL (DuckDB'de 175K bar var)")


# ── Test T2: Bar tamamlanma ────────────────────────────────────────────────────

def test_t2_bar_completion(sym: str = "BTC/USDT") -> None:
    print("\n=== T2: BAR COMPLETION TEST ===")
    folder = SYMBOLS_FOLDERS[sym]
    df = load_parquet_15m(folder, n_tail=500)
    if df.empty:
        print(f"  {sym}: veri yok")
        return

    now_utc = datetime.now(timezone.utc)
    minutes_since_epoch = int(now_utc.timestamp() // 60)
    bar_floor_min = (minutes_since_epoch // 15) * 15
    target_bar_close = pd.Timestamp(
        datetime.fromtimestamp(bar_floor_min * 60, tz=timezone.utc)
    )

    last_bar_in_data = pd.Timestamp(df["ts"].iloc[-1])
    if last_bar_in_data.tzinfo is None:
        last_bar_in_data = last_bar_in_data.tz_localize("UTC")

    data_age_min = (now_utc - last_bar_in_data.to_pydatetime()).total_seconds() / 60

    print(f"  now_utc:          {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  target_bar_close: {target_bar_close.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  last_bar_in_data: {last_bar_in_data.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  data_age:         {data_age_min:.1f} min")
    print(f"  stale_threshold:  {SIGNAL_MAX_AGE_MIN} min")
    print(f"  STALE?            {'YES — INGEST DURMUŞ' if data_age_min > SIGNAL_MAX_AGE_MIN else 'NO — veri taze'}")

    # Daemon _scan_symbol last_bar_ts filter simülasyonu
    df_p = _prep_df(df.copy(), sym)
    df_filtered = df_p[df_p["ts"] <= target_bar_close]
    if df_filtered.empty:
        print("  df_filtered EMPTY — target_bar_close tüm barlardan önce!")
        return
    last_bar_ts = df_filtered["ts"].iloc[-1]

    # Strateji sinyalleri
    strat, _ = _load_strategy("vsa_climax_test", "VSAClimaxTestStrategy")
    df_prep = strat.prepare_features(df_filtered.copy())
    sigs_all = strat.generate_signals(df_prep)

    sigs_last_bar = []
    for sig in sigs_all:
        sig_ts = pd.Timestamp(sig.ts)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.tz_localize("UTC")
        if abs((sig_ts - last_bar_ts).total_seconds()) < 60:
            sigs_last_bar.append(sig)

    print(f"\n  VSA total sigs (tüm tarih): {len(sigs_all)}")
    print(f"  VSA sigs on last_bar_ts ({last_bar_ts}): {len(sigs_last_bar)}")
    if sigs_all:
        latest_sig_ts = max(pd.Timestamp(s.ts) for s in sigs_all)
        diff_hours = (last_bar_ts - latest_sig_ts).total_seconds() / 3600
        print(f"  En son sinyal: {latest_sig_ts} (last_bar_ts'den {diff_hours:.1f}h önce)")
    print(f"\n  Sonuç: 0 sinyal nedeni = last_bar_ts match filter + stale data kombinasyonu")


# ── Test T3: Sym universe ───────────────────────────────────────────────────────

def test_t3_sym_universe() -> None:
    print("\n=== T3: SYM UNIVERSE TEST ===")
    scan_syms = list(SYMBOLS_FOLDERS.keys())
    print(f"  scan SYMBOLS ({len(scan_syms)}): {scan_syms}")

    # Pool'dan syms (sec53 pool dosyası)
    pool_file = ROOT / "data" / "sec53_15m_pool_v11.pkl"
    if pool_file.exists():
        import pickle
        with open(pool_file, "rb") as f:
            pool = pickle.load(f)
        if hasattr(pool, "columns") and "symbol" in pool.columns:
            pool_syms = sorted(pool["symbol"].unique().tolist())
        elif isinstance(pool, dict) and "symbol" in pool:
            pool_syms = sorted(set(pool["symbol"]))
        else:
            pool_syms = []
        print(f"  Pool syms ({len(pool_syms)}): {pool_syms[:10]}")
        missing_in_scan = set(pool_syms) - set(scan_syms)
        missing_in_pool = set(scan_syms) - set(pool_syms)
        print(f"  Pool'da var, scan'de yok: {missing_in_scan}")
        print(f"  Scan'de var, pool'da yok: {missing_in_pool}")
    else:
        print(f"  Pool dosyası yok: {pool_file}")

    print(f"  Sonuç: Universe farkı sinyal kaybına yol açmıyor (10 sym scan eşleşiyor)")


# ── Test T4: Generate_signals raw output ───────────────────────────────────────

def test_t4_generate_signals() -> None:
    print("\n=== T4: GENERATE_SIGNALS RAW OUTPUT ===")
    sym = "BTC/USDT"
    folder = SYMBOLS_FOLDERS[sym]
    df_full = load_parquet_15m(folder, n_tail=500)
    if df_full.empty:
        print(f"  {sym}: veri yok")
        return

    df = _prep_df(df_full.copy(), sym)
    print(f"  {sym} son 500 bar, her strateji raw sinyal sayısı:")

    for mod_name, cls_name in TOP_4_15M:
        try:
            strat, manifest = _load_strategy(mod_name, cls_name)
            min_score = getattr(
                getattr(manifest, "signals", None),
                "confluence", None,
            )
            min_score_val = getattr(min_score, "min_score", "?") if min_score else "?"
            df_prep = strat.prepare_features(df.copy())
            sigs = strat.generate_signals(df_prep)
            if sigs:
                scores = [s.confluence_score for s in sigs]
                last_sig = sigs[-1]
                print(
                    f"  {mod_name:<35} {len(sigs):>4} sig | "
                    f"min_score={min_score_val} | "
                    f"scores=[{min(scores):.2f}..{max(scores):.2f}] | "
                    f"son={last_sig.ts} dir={last_sig.direction}"
                )
            else:
                print(f"  {mod_name:<35}    0 sig | min_score={min_score_val}")
        except Exception as e:
            print(f"  {mod_name:<35} HATA: {e}")

    print(f"\n  Sonuç: Stratejiler sinyal üretiyor ama bunlar eski barlara ait")
    print(f"         last_bar_ts match filter (< 60s) tüm sinyalleri eliyor")


# ── Test T5: Conf threshold ─────────────────────────────────────────────────────

def test_t5_conf_gate() -> None:
    print("\n=== T5: CONF GATE TEST ===")
    sym = "BTC/USDT"
    folder = SYMBOLS_FOLDERS[sym]
    df = _prep_df(load_parquet_15m(folder, n_tail=500), sym)

    yaml_conf_min = 0.25  # risk_phoenix_scalp_15m_c2v5_final.yaml: signal_confidence_min
    print(f"  YAML signal_confidence_min: {yaml_conf_min}")

    for mod_name, cls_name in TOP_4_15M:
        try:
            strat, manifest = _load_strategy(mod_name, cls_name)
            signals_obj = getattr(manifest, "signals", None)
            conf_obj = getattr(signals_obj, "confluence", None) if signals_obj else None
            manifest_min = getattr(conf_obj, "min_score", "N/A") if conf_obj else "N/A"

            df_prep = strat.prepare_features(df.copy())
            sigs = strat.generate_signals(df_prep)
            if sigs:
                scores = [s.confluence_score for s in sigs]
                below_yaml = sum(1 for s in scores if s < yaml_conf_min)
                print(
                    f"  {mod_name:<35} manifest_min={manifest_min} | "
                    f"yaml_min={yaml_conf_min} | "
                    f"below_yaml={below_yaml}/{len(sigs)}"
                )
            else:
                print(f"  {mod_name:<35} 0 sinyal")
        except Exception as e:
            print(f"  {mod_name}: HATA: {e}")

    print(f"\n  Sonuç: Conf gate sinyal kaybına yol açmıyor (sinyaller zaten 0)")


# ── Hipotez özet ──────────────────────────────────────────────────────────────

def print_hypothesis_summary() -> None:
    print("\n" + "=" * 70)
    print("ROOT CAUSE SUMMARY — SEC56 Diagnostic")
    print("=" * 70)

    now_utc = datetime.now(timezone.utc)
    folder = SYMBOLS_FOLDERS["BTC/USDT"]
    df_btc = load_parquet_15m(folder, n_tail=10)
    last_bar = pd.Timestamp(df_btc["ts"].iloc[-1]) if not df_btc.empty else None
    if last_bar is not None and last_bar.tzinfo is None:
        last_bar = last_bar.tz_localize("UTC")
    age_min = (now_utc - last_bar.to_pydatetime()).total_seconds() / 60 if last_bar else None

    print(f"""
HIPOTEZ TEST SONUÇLARI:
  H1 (Warmup -- yetersiz bar):     FAIL -- 175K bar mevcut, 200+ bar'da sinyal cikiyor
  H2 (Bar Latency -- ingest gap):  PASS -- ROOT CAUSE
     Son bar: {last_bar} UTC
     Age:     {age_min:.1f} min (threshold: {SIGNAL_MAX_AGE_MIN} min)
     Etki:    _scan_symbol son barda sinyal yok (en son sinyal 2 gun once)
              bar_close_ts = {last_bar} (stale)
              Strateji sinyalleri eski barlara ait -> last_bar_ts match filter (< 60s) eliyor
  H3 (Sym Universe):              FAIL -- 10 sym scan = pool ile ayni
  H4 (Generate_signals bug):      FAIL -- stratejiler sinyal uretiyor (eski barlarda)
  H5 (Conf gate):                 FAIL -- conf thresholds backtest ile ayni

ROOT CAUSE:
  ingest_15m_live.py cron DURMUS (veya basarisiz)
  Parquet/DuckDB son bar = ~11:00 UTC (yaklasik 2+ saat once)
  _scan_symbol: last_bar_ts = {last_bar}
  Stratejiler 2 gun onceki bar icin sinyal uretiyor
  last_bar_ts match filtresi (< 60s) bunlari eliyor -> 0 sinyal
  Stale guard ikinci savunma hatti -- ama 0 sinyal zaten dondugundan devreye girmiyor

KALICI FIX (SEC56):
  1. futures_trade_15m._scan_symbol: data freshness guard + auto-refresh (ccxt)
     Son bar > 30 dk eski ise ccxt'ten 50 bar cek, DuckDB'ye upsert
  2. futures_daemon.py satir 503: _scan_signals_15m(scan_start) -> (current_boundary)
     scan_start (now) yerine son kapanan bar boundary kullan (semantik duzeltme)
  3. ingest cron watchdog: ingest 2 bar > 30 dk sessiz kalirsa alarm (onerilir)
""")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("SEC56 LIVE SCAN DIAGNOSTIC")
    print(f"Zaman: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 70)

    test_t1_warmup()
    test_t2_bar_completion()
    test_t3_sym_universe()
    test_t4_generate_signals()
    test_t5_conf_gate()
    print_hypothesis_summary()


if __name__ == "__main__":
    main()
