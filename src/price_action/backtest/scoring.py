"""Confidence scoring — percentile-based normalization.

Mevcut conf hesabi: (confluence_score - 1.5) / 1.5  -> lineer, %96.9 sinyalleri
[0.30, 0.40) bucket'inda yığılmış. Tier sistemi anlamsız (Ablation agent buldu).

YENI: Rolling 180-gun percentile rank.
  conf_pct(t) = "son 180 gunde, bu trade'in confluence_score'u ust %X dilim"
  conf_pct ∈ [0.0, 1.0], dağılım uniform.
  10/10 sinyal = top %5 = conf_pct >= 0.95.

Kullanim:
  from price_action.backtest.scoring import normalize_conf_percentile
  trades_with_pct = normalize_conf_percentile(trades, lookback_days=180)
"""
from __future__ import annotations

from datetime import timedelta


def normalize_conf_percentile(trades: list[dict], lookback_days: int = 180) -> list[dict]:
    """Her trade'e `conf_pct` alani ekle.

    conf_pct = bu trade'in confluence_score'u son N gunde top %X dilim.
    0.0 = en dusuk, 1.0 = en yuksek.

    Original `conf` alani korunur (geri donus). Yeni alan `conf_pct`.
    Trade listesi entry_ts'e gore siralanmis varsayilir.
    """
    if not trades:
        return trades

    # Asil confluence_score'u geri ekle: conf'tan rebuild edilemez (lossy).
    # _gather su an conf = max(0, min(1, (cs-1.5)/1.5)) yapiyor.
    # Eldeki conf'tan confluence_score'u geri yap: cs = conf * 1.5 + 1.5
    # Bu yaklasimi kullanalim (yeterli proxy).
    for t in trades:
        t["_cs_proxy"] = t["conf"] * 1.5 + 1.5

    trades_sorted = sorted(trades, key=lambda t: t["entry_ts"])

    # Her trade icin son 180 gun penceresinde percentile rank
    for i, t in enumerate(trades_sorted):
        cutoff = t["entry_ts"] - timedelta(days=lookback_days)
        # Son 180 gun pencere: cutoff < entry_ts(other) <= t.entry_ts
        # Onceki trade'lerden al (look-ahead bias yok)
        history = []
        for j in range(i - 1, -1, -1):
            if trades_sorted[j]["entry_ts"] < cutoff:
                break
            history.append(trades_sorted[j]["_cs_proxy"])
        # Eger history yetersizse (ilk sinyaller), conf_pct = original conf
        if len(history) < 30:
            t["conf_pct"] = t["conf"]
            continue
        # Percentile rank: kac history elemani bu trade'in skorundan kucuk/esit?
        cs = t["_cs_proxy"]
        rank = sum(1 for h in history if h <= cs) / len(history)
        t["conf_pct"] = rank

    # _cs_proxy temizle
    for t in trades_sorted:
        del t["_cs_proxy"]

    return trades_sorted


def get_tier_value(tiers: list[dict], conf: float, default_key: str, default_value):
    """Tier listesinden conf'a uyan degeri don.

    tiers: [{"min": 0.0, "max": 0.5, default_key: value}, ...]
    Hiç eşleşmezse default_value.
    """
    for tier in tiers:
        lo = float(tier.get("min", 0.0))
        hi = float(tier.get("max", 1.0))
        if lo <= conf < hi:
            return tier.get(default_key, default_value)
    return default_value


# =====================================================================
# v1.5.1 — sl_pct rolling percentile rank (CONF DATA QUALITY FIX)
# =====================================================================
# SEC9 forensik: confluence_score'un %96.9'u tek-tier'a (~0.333)
# sıkışıyor — strategy'lerin emit_signals filtresi (min_score=2.0) tek
# bir base_score (=2.0) emit ediyor. Tier sistemi etkisiz kalıyor.
#
# ÇOZUM C (lab pre-reg): Trade pool'dan post-process ile percentile rank.
# Composite signal:  sl_pct (entry_price - initial_sl) / entry_price
# Sebep (lab forensics):
#   - Spearman(sl_pct_rank, R) = +0.30 (p<0.001)  — gerçek alpha sinyali
#   - Wide SL trade'lerin mean_R'si tight SL'den 2.6x büyük (T5/T1)
#   - sl_pct = ATR-driven volatility proxy + structural sl distance composite
#   - 1/sl_pct kullanılırsa korelasyon TERS yöne döner (-0.30) — bu yüzden direkt sl_pct
#
# Rolling 180-gün rank (look-ahead-free):
#   conf_pct(t) = (#past_trades within 180d with sl_pct <= sl_pct(t)) / #past_trades
#
# Tier dağılımı (v1.5 pool 6650 trade):
#   T1 [0,0.32) = 2331 (35.1%), mean_R +0.212, WR 48.4%
#   T2 [0.32,0.42) = 645 (9.7%), mean_R +0.429, WR 53.5%
#   T3 [0.42,0.52) = 711 (10.7%), mean_R +0.423, WR 49.9%
#   T4 [0.52,0.58) = 379 (5.7%), mean_R +0.190, WR 48.0%
#   T5 [0.58,1) = 2584 (38.9%), mean_R +0.554, WR 53.1%
# Dağılım bimodal ama 5 tier'a dağıtık. T5 vs T1 = 2.6x mean_R, monoton-değil
# ama trend pozitif (T1<T2≈T3, T5 en yüksek). T4 outlier (n=379 küçük örnek).


def normalize_conf_via_sl_pct_percentile(
    trades: list[dict],
    lookback_days: int = 180,
    min_history: int = 30,
) -> list[dict]:
    """Trade pool'a `conf_pct` alani ekle (sl_pct rolling rank).

    Look-ahead bias yok: rank cutoff = entry_ts - lookback_days,
    history sadece geçmiş trade'lerden.
    History < min_history ise conf_pct = 0.5 (orta tier).

    Original `conf` korunur, yeni alan `conf_pct`.
    """
    if not trades:
        return trades
    trades_sorted = sorted(trades, key=lambda t: t["entry_ts"])

    # Pre-compute sl_pct
    sl_pcts = []
    for t in trades_sorted:
        ep = float(t["entry_price"])
        sl = float(t["initial_sl"])
        if ep <= 0:
            sl_pcts.append(0.0)
            continue
        sl_pcts.append(abs(ep - sl) / ep)

    for i, t in enumerate(trades_sorted):
        cutoff = t["entry_ts"] - timedelta(days=lookback_days)
        # Geçmiş history (look-ahead-free)
        history = []
        for j in range(i - 1, -1, -1):
            if trades_sorted[j]["entry_ts"] < cutoff:
                break
            history.append(sl_pcts[j])
        if len(history) < min_history:
            t["conf_pct"] = 0.5
            continue
        mine = sl_pcts[i]
        rank = sum(1 for h in history if h <= mine) / len(history)
        t["conf_pct"] = rank

    return trades_sorted


__all__ = [
    "normalize_conf_percentile",
    "normalize_conf_via_sl_pct_percentile",
    "get_tier_value",
]
