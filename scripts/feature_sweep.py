"""Feature Sweep Engine — sistematik feature × forward-return korelasyon taraması.

OTONOMI-1 (2026-07-07, Principal direktifi): "piyasayı anlasın, on binlerce
korelasyon denesin, uyumu yakalasın." Bu motor bunu İSTATİSTİKSEL DÜRÜSTLÜKLE
yapar — çıplak korelasyon avı değil:

  - Spearman IC (rank korelasyon; outlier-dirençli)
  - Benjamini-Hochberg FDR düzeltmesi (binlerce test → yanlış-keşif kontrolü)
  - Walk-forward onay: IS (ilk %70) işaret+büyüklük, OOS (son %30) işaret
    tutarlılığı + |IC_OOS| >= 0.5 × |IC_IS| şartı
  - Lookahead YOK: her feature t anında yalnız <= t verisi kullanır (shift
    disiplini); target = t -> t+h forward return.

Veri: market.duckdb (RO, tüketici) 15m -> 1h resample + 1d; funding.duckdb.
Çıktı:
  - reports/research/feature_sweep/YYYY-MM-DD.md  (insan-okur rapor)
  - memory/researcher/sweep_candidates.jsonl      (append-only aday kuyruğu;
    researcher pulse bu dosyayı hipotez hammaddesi olarak okur)

Cron: scheduler `feature_sweep` (deterministik CPU, LLM YOK).
Elle: .venv/bin/python scripts/feature_sweep.py [--tf 1h] [--quick]

Hard limits (repo disiplini): forward-fill YOK, clip/winsorize YOK,
sayı uydurma YOK — geçemeyen aday yazılmaz.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

MARKET_DB = ROOT / "data" / "market.duckdb"
FUNDING_DB = ROOT / "data" / "funding.duckdb"
OUT_DIR = ROOT / "reports" / "research" / "feature_sweep"
CAND_PATH = ROOT / "memory" / "researcher" / "sweep_candidates.jsonl"

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "XLM/USDT",
    "TRX/USDT",
    "ATOM/USDT",
    "AAVE/USDT",
    "ALGO/USDT",
]  # trading evreni (18; UNI data-only oldugu icin sweep disi — KARAR P1-6)

# Kabul eşikleri — gevşetilemez (gevşetme = KARAR-GUNLUGU)
FDR_ALPHA = 0.05
MIN_ABS_IC = 0.02
OOS_RATIO = 0.5
IS_FRAC = 0.7
MIN_OBS = 500  # feature-target çifti başına asgari gözlem


def _load_ohlcv_1h(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame:
    """15m -> 1h resample (left-closed, label=left; bar kapanınca bilinir)."""
    df = con.execute(
        """
        SELECT ts, open, high, low, close, volume FROM ohlcv
        WHERE venue='binance' AND symbol=? AND timeframe='15m'
        ORDER BY ts
        """,
        [symbol],
    ).fetchdf()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    o = df.resample("1h", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return o.dropna(subset=["close"])


def _load_funding(symbol: str) -> pd.Series | None:
    if not FUNDING_DB.exists():
        return None
    # funding.duckdb sembolleri ÇIPLAK saklar ('BTC') — üç varyantı da dene
    sym = symbol.replace("/", "")
    base = symbol.split("/")[0]
    try:
        con = duckdb.connect(str(FUNDING_DB), read_only=True)
        df = con.execute(
            "SELECT ts, funding_rate FROM funding_rates WHERE symbol IN (?, ?, ?) ORDER BY ts",
            [symbol, sym, base],
        ).fetchdf()
        con.close()
    except Exception:
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")["funding_rate"]


def build_features(
    o: pd.DataFrame, funding: pd.Series | None, btc_close: pd.Series | None
) -> pd.DataFrame:
    """1h bar'lardan feature matrisi. HER feature t bar-kapanışında bilinir."""
    f = pd.DataFrame(index=o.index)
    c = o["close"]
    # Geçmiş getiriler (t kapanışında biliniyor)
    for h in (1, 4, 24, 72):
        f[f"ret_{h}h"] = c.pct_change(h)
    # Volatilite / hacim z-skorları (rolling, yalnız geçmiş)
    r1 = c.pct_change()
    f["vol_z"] = (r1.rolling(24).std() - r1.rolling(240).std().shift(24)) / (
        r1.rolling(240).std().shift(24) + 1e-12
    )
    f["volume_z"] = (o["volume"] - o["volume"].rolling(240).mean()) / (
        o["volume"].rolling(240).std() + 1e-12
    )
    # Range pozisyonu: son 24h aralığında kapanış nerede
    hh, ll = o["high"].rolling(24).max(), o["low"].rolling(24).min()
    f["range_pos_24h"] = (c - ll) / (hh - ll + 1e-12)
    # ATR% (14, 1h)
    tr = pd.concat(
        [o["high"] - o["low"], (o["high"] - c.shift()).abs(), (o["low"] - c.shift()).abs()],
        axis=1,
    ).max(axis=1)
    f["atr_pct"] = tr.rolling(14).mean() / c
    # Funding (8h serisi -> asof <= t; z 30g = 90 nokta)
    if funding is not None and len(funding) > 100:
        fu = funding.reindex(
            f.index, method="ffill"
        )  # asof: son bilinen funding (<= t) — forward-fill DEĞİL, event-carry
        f["funding"] = fu
        f["funding_z"] = (fu - fu.rolling(90 * 8).mean()) / (fu.rolling(90 * 8).std() + 1e-12)
        f["funding_chg_24h"] = fu - fu.shift(24)
    # BTC lider getirisi (alt'lar için cross-feature)
    if btc_close is not None:
        b = btc_close.reindex(f.index).ffill()
        f["btc_ret_4h"] = b.pct_change(4)
        f["btc_ret_24h"] = b.pct_change(24)
    return f


def build_targets(o: pd.DataFrame) -> pd.DataFrame:
    """Forward returns: t kapanışından t+h kapanışına. (Yalnız target ileri bakar.)"""
    c = o["close"]
    t = pd.DataFrame(index=o.index)
    for h in (4, 24, 72):
        t[f"fwd_{h}h"] = c.shift(-h) / c - 1.0
    return t


def _target_horizon_bars(target_col: str) -> int:
    """'fwd_24h' → 24 (1h grid: h saat = h bar). Ayrıştırılamazsa 1 (de-overlap yok)."""
    try:
        return max(int("".join(ch for ch in target_col if ch.isdigit())), 1)
    except (ValueError, TypeError):
        return 1


def _deoverlapped_p(ic: float, n_raw: int, h_bars: int) -> float:
    """Örtüşen forward-return için ETKİN-N Spearman iki-yanlı p-değeri.

    FIX 2026-07-10 (P2 feature-sweep p-şişmesi): fwd_4h/24h/72h target'ları ÖRTÜŞEN
    — komşu satırlar h-1/h bar paylaşır; feature'lar da rolling/ffill autokorele.
    scipy'nin i.i.d. p'si ham n≈31k ile deflate → |IC|>0.011 mikroskopik p → %74
    FDR-pass (crypto getiri tahmininde istatistiksel imkânsız). Etkin örneklem
    n_eff = n_raw // h_bars (bağımsız blok sayısı); Spearman t = ic*sqrt((n_eff-2)/
    (1-ic²)), p = 2*t.sf(|t|, n_eff-2). n_eff<=2 veya |ic|>=1 → p=1.0 (güvenli).
    Nokta-tahmin ic'ye DOKUNULMAZ; yalnız p düzelir → daha az ama dürüst aday.
    """
    n_eff = int(n_raw) // max(int(h_bars), 1)
    if n_eff <= 2 or abs(ic) >= 1.0:
        return 1.0
    t = ic * np.sqrt((n_eff - 2) / (1.0 - ic * ic))
    return float(2.0 * stats.t.sf(abs(t), n_eff - 2))


def sweep_symbol(sym: str, feats: pd.DataFrame, tgts: pd.DataFrame) -> list[dict]:
    """Tüm (feature, target) çiftleri için IS/OOS Spearman IC."""
    out = []
    n = len(feats)
    if n < MIN_OBS:
        return out
    for fc in feats.columns:
        for tc in tgts.columns:
            pair = pd.concat([feats[fc], tgts[tc]], axis=1).dropna()
            if len(pair) < MIN_OBS:
                continue
            k = int(len(pair) * IS_FRAC)
            is_df, oos_df = pair.iloc[:k], pair.iloc[k:]
            if len(oos_df) < 100:
                continue
            ic_is, _p_iid = stats.spearmanr(is_df.iloc[:, 0], is_df.iloc[:, 1])
            ic_oos, _ = stats.spearmanr(oos_df.iloc[:, 0], oos_df.iloc[:, 1])
            if np.isnan(ic_is) or np.isnan(ic_oos):
                continue
            # scipy'nin i.i.d. p'si yerine örtüşen-target etkin-N p'si (P2 fix):
            # _p_iid deflate; _deoverlapped_p gerçek anlamlılığı verir.
            p_is = _deoverlapped_p(float(ic_is), len(is_df), _target_horizon_bars(tc))
            out.append(
                {
                    "symbol": sym,
                    "feature": fc,
                    "target": tc,
                    "n_is": len(is_df),
                    "n_oos": len(oos_df),
                    "ic_is": round(float(ic_is), 4),
                    "p_is": float(p_is),
                    "ic_oos": round(float(ic_oos), 4),
                }
            )
    return out


def bh_fdr(results: list[dict], alpha: float = FDR_ALPHA) -> list[dict]:
    """Benjamini-Yekutieli: bağımlı/korele p'ler için FDR; geçenlere fdr_pass=True.

    FIX 2026-07-10 (P2): testler ağır korele (3 iç-içe örtüşen target/feature +
    tüm semboller BTC ile ko-hareket) → düz BH'nin bağımsızlık/PRDS varsayımı
    bozuk. BY, eşiği harmonik sayı H_m ile bölerek bağımlılık altında FDR
    garantisini geri verir. Monoton sıkılaştırma → BH'nin reddettiğini asla kabul
    etmez (güvenli). FDR_ALPHA ve OOS kapısı DEĞİŞMEZ (eşik gevşetme YASAK).
    """
    if not results:
        return results
    ps = sorted((r["p_is"], i) for i, r in enumerate(results))
    m = len(ps)
    h_m = sum(1.0 / k for k in range(1, m + 1))  # BY harmonic düzeltmesi
    thresh_idx = -1
    for rank, (p, _) in enumerate(ps, start=1):
        if p <= alpha * rank / (m * h_m):
            thresh_idx = rank
    passing = (
        {i for _, (p, i) in zip(range(thresh_idx), ps, strict=False)} if thresh_idx > 0 else set()
    )
    for i, r in enumerate(results):
        r["fdr_pass"] = i in passing
    return results


def confirm_oos(r: dict) -> bool:
    return (
        r["fdr_pass"]
        and abs(r["ic_is"]) >= MIN_ABS_IC
        and np.sign(r["ic_oos"]) == np.sign(r["ic_is"])
        and abs(r["ic_oos"]) >= OOS_RATIO * abs(r["ic_is"])
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="ilk 4 sembol (smoke test)")
    args = ap.parse_args()

    syms = SYMBOLS[:4] if args.quick else SYMBOLS
    con = duckdb.connect(str(MARKET_DB), read_only=True)
    btc = _load_ohlcv_1h(con, "BTC/USDT")
    btc_close = btc["close"] if not btc.empty else None

    all_results: list[dict] = []
    for sym in syms:
        o = _load_ohlcv_1h(con, sym)
        if o.empty or len(o) < MIN_OBS:
            print(f"[sweep] {sym}: veri yetersiz ({len(o)}) — atlandı")
            continue
        feats = build_features(o, _load_funding(sym), None if sym == "BTC/USDT" else btc_close)
        tgts = build_targets(o)
        rs = sweep_symbol(sym, feats, tgts)
        all_results.extend(rs)
        print(f"[sweep] {sym}: {len(rs)} test ({len(o)} bar)")
    con.close()

    all_results = bh_fdr(all_results)
    candidates = [r for r in all_results if confirm_oos(r)]
    candidates.sort(key=lambda r: -abs(r["ic_oos"]))

    ts = datetime.now(UTC)
    stamp = ts.strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Aday kuyruğu (dedupe: symbol|feature|target anahtarı)
    seen: set[str] = set()
    if CAND_PATH.exists():
        for line in CAND_PATH.read_text().splitlines():
            try:
                d = json.loads(line)
                seen.add(f"{d['symbol']}|{d['feature']}|{d['target']}")
            except Exception:
                continue
    new_cands = []
    with open(CAND_PATH, "a", encoding="utf-8") as fh:
        for r in candidates:
            key = f"{r['symbol']}|{r['feature']}|{r['target']}"
            if key in seen:
                continue
            rec = {**r, "ts": ts.isoformat(), "status": "CANDIDATE"}
            fh.write(json.dumps(rec) + "\n")
            new_cands.append(rec)

    # İnsan-okur rapor
    lines = [
        f"# Feature Sweep — {stamp}",
        "",
        f"Toplam test: **{len(all_results)}** (semboller: {len(syms)}, 1h TF) · "
        f"FDR(BH, α={FDR_ALPHA}) geçen: **{sum(1 for r in all_results if r['fdr_pass'])}** · "
        f"OOS-onaylı aday: **{len(candidates)}** · YENİ aday: **{len(new_cands)}**",
        "",
        "Kabul: FDR-pass ∧ |IC_IS|≥0.02 ∧ işaret(OOS)==işaret(IS) ∧ |IC_OOS|≥0.5·|IC_IS|",
        "",
        "| symbol | feature | target | IC_is | IC_oos | n |",
        "|---|---|---|---|---|---|",
    ]
    for r in candidates[:40]:
        lines.append(
            f"| {r['symbol']} | {r['feature']} | {r['target']} | "
            f"{r['ic_is']:+.3f} | {r['ic_oos']:+.3f} | {r['n_is'] + r['n_oos']} |"
        )
    if not candidates:
        lines.append("| — | (bu turda aday yok — dürüst sonuç) | | | | |")
    report = OUT_DIR / f"{stamp}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"[sweep] TAMAM: {len(all_results)} test, {len(candidates)} aday "
        f"({len(new_cands)} yeni) → {report}"
    )


if __name__ == "__main__":
    main()
