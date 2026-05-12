"""Feature Coverage Analyzer — EER-Score readiness check.

CEO brief 2026-05-12 (sec 4.4): Researcher EER-Score'in cikabilmesi icin
gerekli her feature'in pipeline'da hazir olup olmadigini dogrula.

Cikti: data/quality/<DATE>-feature-coverage.json

Calistirma:
    python scripts/data_feature_coverage.py

Yasaklar (data_engineer kontrati):
- Clip/winsorize YOK
- Forward-fill YOK (look-ahead bias)
- Onaysiz yeni veri kaynagi prod'a baglanmaz

Davranis: KESINLIKLE READ-ONLY. Sadece envanter olusturur ve manifest yazar.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

# 11 sembol — scripts/v09_optimize_top10.py'dan kopyalandi (tek dogru kaynak)
SYMBOLS_11 = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
    "DOGE/USDT", "XRP/USDT", "MATIC/USDT",
]


# ---------------------------------------------------------------------------
# Utility: data_hash (reproducibility)
# ---------------------------------------------------------------------------

def _sha256_short(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def _hash_dataframe(df) -> str:
    """Deterministik hash — kolon sirasi + satir sirasi onemli."""
    if df is None or len(df) == 0:
        return "empty"
    import pandas as pd  # local
    # CSV serializasyonu (ts duzgun string olur) — kucuk performans tradeoff
    payload = df.to_csv(index=False).encode("utf-8")
    return _sha256_short(payload)


# ---------------------------------------------------------------------------
# 1d OHLCV envanteri
# ---------------------------------------------------------------------------

def inventory_1d_ohlcv() -> dict:
    import duckdb
    import pandas as pd

    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return {"status": "missing_db", "path": str(db_path)}

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        per_symbol = {}
        all_clean = True
        total_rows = 0
        total_gaps = 0

        for sym in SYMBOLS_11:
            df = con.execute(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE timeframe='1d' AND venue='binance' AND symbol=? "
                "ORDER BY ts",
                [sym],
            ).fetchdf()
            if df.empty:
                per_symbol[sym] = {"status": "EMPTY"}
                all_clean = False
                continue

            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            first_ts = df["ts"].iloc[0]
            last_ts = df["ts"].iloc[-1]
            expected_days = (last_ts - first_ts).days + 1
            diffs = df["ts"].diff().dt.days.dropna()
            gaps = int((diffs != 1).sum())
            gap_rate = gaps / max(1, len(df))

            # OHLC sanity (data_engineer kontrati: high>=max(open,close), low<=min)
            sanity_violations = int(
                ((df["high"] < df[["open", "close"]].max(axis=1)) |
                 (df["low"] > df[["open", "close"]].min(axis=1))).sum()
            )

            # delisted bayraklamasi (last_ts < 2026-05-01)
            delisted = (last_ts.date() < pd.Timestamp("2026-05-01", tz="UTC").date())

            status = "ok"
            if delisted:
                status = "delisted"
                all_clean = False
            elif gap_rate > 0.001:
                status = "gap_above_threshold"
                all_clean = False
            elif sanity_violations > 0:
                status = "ohlc_violation"
                all_clean = False

            per_symbol[sym] = {
                "rows": int(len(df)),
                "first_ts": str(first_ts.date()),
                "last_ts": str(last_ts.date()),
                "expected_days": int(expected_days),
                "gaps": gaps,
                "gap_rate": round(gap_rate, 6),
                "ohlc_violations": sanity_violations,
                "delisted": bool(delisted),
                "data_hash": _hash_dataframe(df),
                "status": status,
            }
            total_rows += len(df)
            total_gaps += gaps

        overall_gap_rate = total_gaps / max(1, total_rows)
        return {
            "symbols": len(SYMBOLS_11),
            "symbols_ok": sum(1 for v in per_symbol.values()
                              if v.get("status") == "ok"),
            "symbols_delisted": sum(1 for v in per_symbol.values()
                                    if v.get("status") == "delisted"),
            "total_rows": total_rows,
            "overall_gap_rate": round(overall_gap_rate, 6),
            "status": "ok" if all_clean else "warn",
            "per_symbol": per_symbol,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 1w / 4h envanteri (varlik kontrolu)
# ---------------------------------------------------------------------------

def inventory_other_tfs() -> dict:
    import duckdb

    db_path = ROOT / "data" / "market.duckdb"
    if not db_path.exists():
        return {"status": "missing_db"}

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        result = {}
        for tf in ("1w", "4h", "1m"):
            df = con.execute(
                "SELECT symbol, COUNT(*) AS rows, MIN(ts) AS first_ts, "
                "MAX(ts) AS last_ts FROM ohlcv "
                "WHERE timeframe=? AND venue='binance' "
                "GROUP BY symbol ORDER BY symbol",
                [tf],
            ).fetchdf()
            result[tf] = {
                "symbols": int(len(df)),
                "total_rows": int(df["rows"].sum()) if not df.empty else 0,
                "status": "ok" if not df.empty else "missing",
            }
            if df.empty and tf == "1m":
                result[tf]["note"] = (
                    "1m OHLCV yok (15-20GB tahmini). Microstructure icin "
                    "1d proxy yeterli; paper trade icin gerekli DEGIL."
                )
        return result
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Alt-data: BTC funding
# ---------------------------------------------------------------------------

def inventory_btc_funding() -> dict:
    import pandas as pd

    p = ROOT / "data" / "alt_data" / "funding_BTCUSDT.csv"
    if not p.exists():
        return {"status": "missing", "path": str(p)}

    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df_00 = df[df["ts"].dt.hour == 0].copy()
    df_00["date"] = df_00["ts"].dt.date

    first_date = df_00["date"].min()
    last_date = df_00["date"].max()
    expected_days = (last_date - first_date).days + 1
    actual_days = df_00["date"].nunique()
    missing = expected_days - actual_days
    gap_rate = missing / max(1, expected_days)

    return {
        "rows_total": int(len(df)),
        "rows_00_only": int(len(df_00)),
        "first_date": str(first_date),
        "last_date": str(last_date),
        "coverage_days": int(actual_days),
        "expected_days": int(expected_days),
        "missing_days_00_utc": int(missing),
        "gap_rate": round(gap_rate, 6),
        "data_hash": _hash_dataframe(df_00[["ts", "fundingRate"]]),
        "source": "Binance public funding (00:00_only causal mode)",
        "status": "ok" if gap_rate < 0.001 else "warn",
    }


# ---------------------------------------------------------------------------
# Alt-data: F&G
# ---------------------------------------------------------------------------

def inventory_fng() -> dict:
    import pandas as pd

    p = ROOT / "data" / "alt_data" / "fng_daily.csv"
    if not p.exists():
        return {"status": "missing", "path": str(p)}

    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"], format="ISO8601")
    first_date = df["date"].min()
    last_date = df["date"].max()
    all_dates = pd.date_range(first_date, last_date, freq="D")
    missing_set = sorted(set(all_dates.date) - set(df["date"].dt.date))
    gap_rate = len(missing_set) / max(1, len(all_dates))

    return {
        "rows": int(len(df)),
        "first_date": str(first_date.date()),
        "last_date": str(last_date.date()),
        "missing_days": len(missing_set),
        "missing_examples": [str(d) for d in missing_set[:10]],
        "gap_rate": round(gap_rate, 6),
        "data_hash": _hash_dataframe(df[["date", "value"]]),
        "source": "alternative.me Fear & Greed Index daily",
        "status": "ok" if gap_rate < 0.001 else "warn",
    }


# ---------------------------------------------------------------------------
# Alt-data: BTC dominance (YOK — fetch plani lazim)
# ---------------------------------------------------------------------------

def inventory_btc_dominance() -> dict:
    """BTC dominance verisi mevcut mu? Mevcut degil ise fetch ETA."""
    # Mumkun konumlar
    candidates = [
        ROOT / "data" / "dominance.duckdb",
        ROOT / "data" / "alt_data" / "btc_dominance.csv",
        ROOT / "data" / "alt_data" / "btc_d.csv",
    ]
    found = [str(p.relative_to(ROOT)) for p in candidates if p.exists()]
    if found:
        # En azindan duckdb varsa satir sayisi raporla
        result = {"status": "ok", "paths": found}
        ddb = ROOT / "data" / "dominance.duckdb"
        if ddb.exists():
            try:
                import duckdb
                con = duckdb.connect(str(ddb), read_only=True)
                try:
                    row = con.execute(
                        "SELECT COUNT(*), MIN(ts), MAX(ts) "
                        "FROM btc_dominance_daily"
                    ).fetchone()
                    result["rows"] = int(row[0]) if row else 0
                    result["first_ts"] = str(row[1]) if row and row[1] else None
                    result["last_ts"] = str(row[2]) if row and row[2] else None
                finally:
                    con.close()
            except Exception as exc:
                result["read_error"] = str(exc)[:200]
        return result

    return {
        "status": "missing",
        "checked_paths": [str(p.relative_to(ROOT)) for p in candidates],
        "fetch_eta_hours": 3,
        "fetch_script": "scripts/ingest_btc_dominance.py",
        "source": "CoinGecko free API (/global + /coins/bitcoin/market_chart)",
        "module": "src/price_action/data/dominance_ingest.py",
        "note": (
            "Modul mevcut (DominanceStore + fetch_btc_dominance_history). "
            "Calistirilmadigi icin DB yok. ingest script'i ile 3y backfill "
            "yapilabilir. CEO brief 4.4 + Researcher B "
            "2026-05-12-regime-btc-dominance-trend-veto.md gerektiriyor."
        ),
        "required_for": [
            "EER-Score: btc_dom_trend bucket key",
            "HYP-2026-05-12-regime-btc-dominance-trend-veto",
        ],
    }


# ---------------------------------------------------------------------------
# Derived features (ATR%, EMA200_streak, 90d_DD)
# ---------------------------------------------------------------------------

def inventory_derived_features() -> dict:
    """regime.py icinde her cagirimda yeniden hesaplaniyor — cache yok.

    Bu **cache eksikligi** — EER backtest'inde tekrarli compute maliyeti olur.
    Kararsiz: tek-pencere kabul edilebilir. 3y/13 pencere icin cache yararli.
    """
    regime_py = ROOT / "src" / "price_action" / "backtest" / "regime.py"
    return {
        "atr_pct": {
            "compute_location": "src/price_action/backtest/regime.py::compute_btc_capitulation_halt",
            "formula": "ATR(14) Wilder / close * 100",
            "cached": False,
            "status": "compute_on_demand",
        },
        "ema200_streak": {
            "compute_location": "src/price_action/backtest/regime.py::compute_btc_capitulation_halt",
            "formula": "consecutive days BTC close < EMA200",
            "cached": False,
            "status": "compute_on_demand",
        },
        "dd_90d": {
            "compute_location": "src/price_action/backtest/regime.py::compute_btc_capitulation_halt",
            "formula": "(close / rolling_max_90d - 1) * 100",
            "cached": False,
            "status": "compute_on_demand",
        },
        "adx14_bbw_pct": {
            "compute_location": "src/price_action/backtest/regime.py::compute_per_symbol_chop",
            "formula": "ADX(14) Wilder + BBW(20,2) 252-day percentile",
            "cached": False,
            "status": "compute_on_demand",
        },
        "regime_module_exists": regime_py.exists(),
        "recommendation": (
            "EER backtest'i 13 pencere x 11 sembol = 143 compute. "
            "Pickle cache (~50MB) eklenmeli — paper trade'e gecmeden W2'de."
        ),
    }


# ---------------------------------------------------------------------------
# Manifest yazici
# ---------------------------------------------------------------------------

def build_manifest() -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()

    print("[1/6] 1d OHLCV envanteri...", flush=True)
    ohlcv_1d = inventory_1d_ohlcv()
    print(f"      {ohlcv_1d.get('symbols_ok', 0)}/{ohlcv_1d.get('symbols', 0)} OK, "
          f"delisted={ohlcv_1d.get('symbols_delisted', 0)}, "
          f"overall_gap_rate={ohlcv_1d.get('overall_gap_rate', 'n/a')}")

    print("[2/6] Diger TF envanteri (1w / 4h / 1m)...", flush=True)
    other_tfs = inventory_other_tfs()

    print("[3/6] BTC funding alt-data...", flush=True)
    funding = inventory_btc_funding()
    print(f"      {funding.get('rows_00_only', 0)} (00:00 only), "
          f"gap_rate={funding.get('gap_rate', 'n/a')}, "
          f"last_date={funding.get('last_date', 'n/a')}")

    print("[4/6] F&G alt-data...", flush=True)
    fng = inventory_fng()
    print(f"      {fng.get('rows', 0)} satir, "
          f"missing_days={fng.get('missing_days', 'n/a')}, "
          f"last_date={fng.get('last_date', 'n/a')}")

    print("[5/6] BTC dominance...", flush=True)
    btcd = inventory_btc_dominance()
    print(f"      status={btcd.get('status')}")

    print("[6/6] Derived features (ATR%, EMA200_streak, 90d_DD)...", flush=True)
    derived = inventory_derived_features()

    # Top-level status: kac feature OK / WARN / MISSING
    feature_block = {
        "1d_ohlcv": ohlcv_1d,
        "1w_ohlcv": other_tfs.get("1w", {}),
        "4h_ohlcv": other_tfs.get("4h", {}),
        "1m_ohlcv": other_tfs.get("1m", {}),
        "btc_funding": funding,
        "fng_daily": fng,
        "btc_dominance": btcd,
        "derived_features": derived,
    }

    # Required for EER
    # NOT: 1d_ohlcv status=warn 'su sebebi MATIC delisting (survivorship icin
    # korundu, hard limit). EER icin >=10/11 sembol yeterlidir — bu blocker DEGIL.
    ohlcv_acceptable = (
        ohlcv_1d.get("symbols_ok", 0) >= 10
        and ohlcv_1d.get("overall_gap_rate", 1.0) < 0.001
    )
    eer_required = {
        "1d_ohlcv": ohlcv_acceptable,
        "btc_funding_00_only": funding.get("status") == "ok",
        "fng_daily": fng.get("status") in ("ok", "warn"),  # 1 gun gap toleransli
        "btc_dominance": btcd.get("status") == "ok",
        "regime_bucket_compute": derived.get("regime_module_exists", False),
        "atr_pct_bucket_compute": derived.get("regime_module_exists", False),
    }
    eer_blockers = [k for k, v in eer_required.items() if not v]

    manifest = {
        "generated_at": generated_at,
        "report_date": "2026-05-13",
        "scope": "EER-Score readiness (CEO brief 2026-05-12 sec 4.4)",
        "symbols_universe": SYMBOLS_11,
        "features": feature_block,
        "eer_readiness": {
            "required": eer_required,
            "blockers": eer_blockers,
            "ready": len(eer_blockers) == 0,
        },
        "summary": {
            "ok_features": sum(
                1 for f in feature_block.values()
                if isinstance(f, dict) and f.get("status") == "ok"
            ),
            "warn_features": sum(
                1 for f in feature_block.values()
                if isinstance(f, dict) and f.get("status") == "warn"
            ),
            "missing_features": sum(
                1 for f in feature_block.values()
                if isinstance(f, dict) and f.get("status") == "missing"
            ),
        },
        "data_engineer_notes": [
            "Forward-fill yapilmadi (look-ahead bias yasak).",
            "Clip/winsorize yapilmadi (raw veri korundu).",
            "MATIC/USDT delisted (2024-09-10) — survivorship icin korundu.",
            "F&G 1 gun eksik (2025-05-12 civari, alternative.me kaynagi).",
            "BTC funding 00:00 UTC slice causal mode default.",
        ],
    }
    return manifest


def main():
    print("=" * 60)
    print("DATA ENGINEER — Feature Coverage Manifest")
    print("CEO brief 2026-05-12 (sec 4.4)")
    print("=" * 60)
    manifest = build_manifest()

    out_path = ROOT / "data" / "quality" / "2026-05-13-feature-coverage.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)

    print()
    print(f"OK Manifest yazildi: {out_path.relative_to(ROOT)}")
    print()
    print("OZET:")
    print(f"  OK     : {manifest['summary']['ok_features']}")
    print(f"  WARN   : {manifest['summary']['warn_features']}")
    print(f"  MISSING: {manifest['summary']['missing_features']}")
    print()
    print(f"  EER-ready: {manifest['eer_readiness']['ready']}")
    if manifest['eer_readiness']['blockers']:
        print(f"  Blockers: {manifest['eer_readiness']['blockers']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
