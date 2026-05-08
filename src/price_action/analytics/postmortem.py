"""Trade post-mortem — kayıplı işlemler için kural bazlı sınıflandırma.

LLM doğrulaması Analyst agent'in işidir; bu modül sadece deterministik
sınıflandırıcı sağlar. Kategoriler `analyst.md` SOP-2'den birebir alınmıştır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from price_action.contracts import TradeRecord
from price_action.logging_config import logger

LossClassification = Literal[
    "wrong_pattern",
    "wrong_timing",
    "wrong_size",
    "regime_change",
    "data_glitch",
    "unlucky",
]


@dataclass(frozen=True)
class PostmortemResult:
    classification: LossClassification
    rationale: str
    confidence: Literal["low", "med", "high"]


def classify_loss(
    trade: TradeRecord,
    market_context: dict[str, Any] | None = None,
) -> LossClassification:
    """Tek kayıplı trade için kural bazlı kategori döner.

    `market_context` opsiyonel; örn:
        {
            "regime_at_entry": "bull"|"bear"|"range",
            "regime_at_exit": ...,
            "abnormal_volume": bool,
            "anomaly_zscore": float,
            "expected_slippage_bps": float,
        }

    Kurallar (öncelik sırasıyla):
    1. data_glitch — slippage_bps anormal yüksek (> 50) veya kontekste anomaly_zscore > 8
    2. regime_change — entry/exit rejimi farklı
    3. wrong_size — realized_r_multiple < -1.5 (SL'in çok ötesinde kapanış / fazla kaldıraç)
    4. wrong_pattern — confluence_score düşük (< 1.5) ve mfe_pct < 0.5%
    5. wrong_timing — mfe_pct >= 1.0% ama exit kayıplı (girdi/çıkış kötü)
    6. unlucky — yukarıdakilerin hiçbiri tetiklenmediyse
    """
    ctx = market_context or {}

    # 1. data glitch
    expected_slip = float(ctx.get("expected_slippage_bps", 25.0))
    if trade.slippage_bps > max(50.0, 2.0 * expected_slip):
        return _log_and_return("data_glitch", trade, "slippage anormal yüksek")
    if abs(float(ctx.get("anomaly_zscore", 0.0))) > 8.0:
        return _log_and_return("data_glitch", trade, "z-score anomaly")

    # 2. regime change
    r_in = ctx.get("regime_at_entry")
    r_out = ctx.get("regime_at_exit")
    if r_in and r_out and r_in != r_out:
        return _log_and_return("regime_change", trade, f"{r_in}→{r_out}")

    # 3. wrong size — risk planı -1R idi ama kayıp -1.5R üstü
    if trade.realized_r_multiple < -1.5:
        return _log_and_return("wrong_size", trade, f"R={trade.realized_r_multiple:.2f}")

    # 4. wrong pattern — düşük güvenli sinyal hiç yürümedi
    if trade.confluence_score < 1.5 and trade.mfe_pct < 0.005:
        return _log_and_return("wrong_pattern", trade, f"score={trade.confluence_score:.2f}")

    # 5. wrong timing — sinyal yürümüş ama biz çıkamamışız
    if trade.mfe_pct >= 0.01 and trade.realized_r_multiple < 0:
        return _log_and_return("wrong_timing", trade, f"mfe={trade.mfe_pct:.3f}")

    # 6. unlucky
    return _log_and_return("unlucky", trade, "hiçbir kural tetiklenmedi")


def classify_loss_detailed(
    trade: TradeRecord,
    market_context: dict[str, Any] | None = None,
) -> PostmortemResult:
    """Sınıflandırma + gerekçe + güven seviyesi."""
    label = classify_loss(trade, market_context)
    confidence: Literal["low", "med", "high"] = "med"
    rationale = ""

    if label == "data_glitch":
        rationale = f"slippage_bps={trade.slippage_bps:.1f} eşik üstü"
        confidence = "high"
    elif label == "regime_change":
        ctx = market_context or {}
        rationale = f"entry={ctx.get('regime_at_entry')}, exit={ctx.get('regime_at_exit')}"
        confidence = "high"
    elif label == "wrong_size":
        rationale = f"R={trade.realized_r_multiple:.2f} (< -1.5)"
        confidence = "med"
    elif label == "wrong_pattern":
        rationale = f"confluence={trade.confluence_score:.2f}, mfe={trade.mfe_pct:.3f}"
        confidence = "med"
    elif label == "wrong_timing":
        rationale = f"mfe={trade.mfe_pct:.3f} >= 1% ama trade kayıplı"
        confidence = "med"
    else:
        rationale = "kural tetiklenmedi — istatistiksel kayıp"
        confidence = "low"

    return PostmortemResult(classification=label, rationale=rationale, confidence=confidence)


def _log_and_return(label: LossClassification, trade: TradeRecord, why: str) -> LossClassification:
    logger.info(
        "postmortem.classified",
        extra={"trade_id": trade.trade_id, "label": label, "why": why},
    )
    return label
