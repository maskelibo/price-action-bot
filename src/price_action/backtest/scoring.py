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


__all__ = ["normalize_conf_percentile", "get_tier_value"]
