"""SEC54.7: Paper Trading Gate — K2 (first 30d neg months) + K3 (30d ROI <%15).

Paper trade açılışı gating (SEC54.9). K1, K4, K5, K6 mevcut implementations'dan
delegate edilir; K2, K3 bu modülde implement.

Gate YAML config:
  paper_trading:
    enabled: true
    cap_usdt: 1000.0
    start_date: "2026-05-25"  # ISO format
    k2_max_neg_months_first_30d: 1
    k3_min_monthly_roi_pct: 15.0

Public API:
  gate = PaperGate(config, trade_journal, telegram_throttle)
  results = gate.evaluate_all(now=datetime.utcnow())
  for r in results:
      if r.action == "HALT":
          # Kill switch tetikle
          activate_kill_switch(reason=f"{r.switch}: {r.reason}")
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from price_action.logging_config import logger
from price_action.settings import get_settings

if False:  # TYPE_CHECKING
    from price_action.execution.trade_journal import TradeJournal
    from price_action.ops.telegram_throttle import TelegramThrottle


@dataclass
class PaperGateConfig:
    """Paper trading gate configuration.

    Attributes
    ----------
    paper_start_date : datetime
        Paper trading başlangıç tarihi (UTC).
    cap_usd : float
        Paper hesap başlangıç kapital (K3 ROI yüzde hesaplamada kullanılır).
        Default: 1000.0 (SEC54.9).
    k2_max_neg_months_first_30d : int
        K2 eşik: ilk 30 gün içinde bu kadar 'den fazla negatif ay → HARD KILL.
        Default: 1 (1 neg ay = OK; 2+ = HALT).
    k3_min_monthly_roi_pct : float
        K3 eşik: rolling 30g ROI bu yüzdenin altındaysa ALERT (warning, manual review).
        Default: 15.0 (% 15 aylık hedef).
    """

    paper_start_date: datetime
    cap_usd: float = 1000.0
    k2_max_neg_months_first_30d: int = 1
    k3_min_monthly_roi_pct: float = 15.0


@dataclass
class GateResult:
    """Gate evaluasyon sonucu.

    Attributes
    ----------
    action : Literal["PASS", "ALERT", "HALT"]
        Triggerlenme aksiyonu.
        - "PASS": threshold altında, normal işlem
        - "ALERT": warning seviyesi, manual review gerekli (daemon devam)
        - "HALT": critical, kill switch tetikle (daemon durdur)
    switch : str
        K1, K2, K3, K4, K5, K6, ...
    reason : str
        Human-readable tetiklenme sebebi.
    metric_value : float
        Ölçülen değer.
    threshold : float
        Eşik değeri.
    """

    action: Literal["PASS", "ALERT", "HALT"]
    switch: str
    reason: str
    metric_value: float
    threshold: float


class PaperGate:
    """Paper trading gate evaluation engine — K1-K6 checks.

    K1: monthly_loss_pct > 8% → DDBreaker (mevcut)
    K2: first 30d >1 neg month → HARD KILL (bu sprint)
    K3: rolling 30d ROI < 15% → ALERT (bu sprint)
    K4: slippage > 25bps → SEC26.B-5 (mevcut)
    K5: DD breaker → SEC26.B-1 (mevcut)
    K6: consecutive ≥7 → SEC26.B-3 (mevcut)

    Notes:
      - K2 sadece ilk 30 gün active; sonra no-op
      - K3 rolling 30g pencere (30g dolmadıysa no-op)
      - All Telegram alerts throttle'da gider (max 1 per 600s per alert_type)
      - Backward-compat: trade_journal boşsa (no trades yet) → no trigger
    """

    def __init__(
        self,
        config: PaperGateConfig,
        trade_journal: TradeJournal,
        telegram_throttle: TelegramThrottle,
    ) -> None:
        """Initialize PaperGate.

        Parameters
        ----------
        config : PaperGateConfig
            Gate thresholds + paper start date.
        trade_journal : TradeJournal
            Trade Journal instance (futures_trades_closed tablo okur).
        telegram_throttle : TelegramThrottle
            Telegram alert dispatcher (throttled).
        """
        self.config = config
        self.journal = trade_journal
        self.telegram = telegram_throttle
        self._log = logger.bind(component="paper_gate")

    def evaluate_k2(self, current_date: datetime) -> Optional[GateResult]:
        """K2: First 30 days, max 1 negative month before HARD KILL.

        İlk 30 gün içerisinde 2+ negatif ay tamamlandıysa (>1) HALT.
        Pratikte: ilk ay negatif + 2. ay başlar başlamaz negatif → HARD KILL.

        Returns
        -------
        Optional[GateResult]
            GateResult(action="HALT") if K2 triggered, else None.
        """
        days_since_start = (current_date - self.config.paper_start_date).days

        # K2 only applies within first 30 days
        if days_since_start > 30:
            return None

        # If less than 24 hours passed, nothing to evaluate yet
        if days_since_start < 1:
            return None

        # Monthly aggregation: trading period'u monthly bins'e ayır
        # Paper başlangıcından current_date'e kadar each calendar month'un ROI'ı hesapla.
        monthly_roi = self._aggregate_by_month(
            start=self.config.paper_start_date,
            end=current_date,
        )

        # Count negative months
        neg_count = sum(1 for m in monthly_roi if m["roi_pct"] < 0)

        # K2 trigger: >max_neg_months_first_30d
        if neg_count > self.config.k2_max_neg_months_first_30d:
            self.telegram.send_throttled(
                "K2_HARD_KILL",
                f"K2 HALT: {neg_count} negative months in first 30 days "
                f"(threshold: {self.config.k2_max_neg_months_first_30d})",
                level="CRITICAL",
            )
            self._log.bind(
                switch="K2",
                neg_count=neg_count,
                threshold=self.config.k2_max_neg_months_first_30d,
                days_since_start=days_since_start,
            ).critical("paper_gate.k2_triggered")

            return GateResult(
                action="HALT",
                switch="K2",
                reason=(
                    f"{neg_count} negative months in first 30 days "
                    f"(threshold: {self.config.k2_max_neg_months_first_30d})"
                ),
                metric_value=float(neg_count),
                threshold=float(self.config.k2_max_neg_months_first_30d),
            )

        return None

    def evaluate_k3(self, current_date: datetime) -> Optional[GateResult]:
        """K3: Rolling 30-day ROI < 15% → ALERT (not HALT).

        30 gün öncesine kadar olan trade'lerin ROI'ı (başlangıç kapitaline göre
        yüzde cinsinden) threshold'un altındaysa ALERT gönderi (daemon devam eder,
        manual review gerekli).

        Returns
        -------
        Optional[GateResult]
            GateResult(action="ALERT") if K3 triggered, else None.
        """
        # 30 gün geriye pencere aç
        window_start = current_date - timedelta(days=30)

        # 30 gün dolmadıysa (paper başlangıcından 30g geçmediyse) no-op
        if window_start < self.config.paper_start_date:
            return None

        # [window_start, current_date] aralığındaki trades al
        trades_30d = self._get_trades_window(window_start, current_date)

        # ROI yüzde hesapla: total_pnl / cap_usdt * 100
        total_pnl = sum(t["realized_pnl_usdt"] for t in trades_30d)
        roi_30d_pct = (total_pnl / self.config.cap_usd * 100) if self.config.cap_usd > 0 else 0.0

        # K3 trigger: roi_30d_pct < k3_min_monthly_roi_pct
        if roi_30d_pct < self.config.k3_min_monthly_roi_pct:
            self.telegram.send_throttled(
                "K3_ALERT",
                f"K3 ALERT: 30-day ROI {roi_30d_pct:.2f}% < threshold {self.config.k3_min_monthly_roi_pct}%",
                level="WARNING",
            )
            self._log.bind(
                switch="K3",
                roi_30d_pct=roi_30d_pct,
                threshold=self.config.k3_min_monthly_roi_pct,
                trade_count=len(trades_30d),
            ).warning("paper_gate.k3_triggered")

            return GateResult(
                action="ALERT",
                switch="K3",
                reason=(
                    f"Rolling 30-day ROI {roi_30d_pct:.2f}% under threshold "
                    f"{self.config.k3_min_monthly_roi_pct}%"
                ),
                metric_value=roi_30d_pct,
                threshold=self.config.k3_min_monthly_roi_pct,
            )

        return None

    def evaluate_all(self, current_date: Optional[datetime] = None) -> list[GateResult]:
        """Evaluate all K2 + K3 gates (K1, K4, K5, K6 from other modules).

        Future: K1-K6 full evaluation chain (currently K2+K3 only).

        Parameters
        ----------
        current_date : Optional[datetime]
            Evaluation timestamp (default: now UTC).

        Returns
        -------
        list[GateResult]
            List of triggered gates (empty if all PASS).
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)
        elif current_date.tzinfo is None:
            current_date = current_date.replace(tzinfo=timezone.utc)

        results = []

        # K2: First 30d neg months check
        k2 = self.evaluate_k2(current_date)
        if k2:
            results.append(k2)

        # K3: Rolling 30d ROI check
        k3 = self.evaluate_k3(current_date)
        if k3:
            results.append(k3)

        # Future: K1, K4, K5, K6 from DDBreaker, SlippageTracker, etc.
        # For now, those modules are separate and called from RiskOfficer/daemon.

        return results

    # ----- Internal Helpers -----

    def _aggregate_by_month(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, float]]:
        """Aggregate realized PnL by calendar month.

        Returns list of dicts: [{"month": "2026-05", "roi_pct": 1.5}, ...]
        Each month: sum of realized_pnl_usdt / cap_usdt * 100.

        Empty calendar months = skip (no trades).
        """
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        try:
            con = self.journal._TradeJournal__dict__.get("db_path")  # hack: access private attr
        except Exception:
            con = None

        if con is None:
            con = self.journal.db_path

        try:
            import duckdb

            connection = duckdb.connect(str(con), read_only=True)
            try:
                rows = connection.execute(
                    """
                    SELECT
                        strftime(ts_close, '%Y-%m') as month,
                        COALESCE(SUM(realized_pnl_usdt), 0.0) as total_pnl
                    FROM futures_trades_closed
                    WHERE ts_close >= ? AND ts_close <= ?
                    GROUP BY month
                    ORDER BY month
                    """,
                    [start, end],
                ).fetchall()

                result = []
                for month_str, total_pnl in rows:
                    roi_pct = (total_pnl / self.config.cap_usd * 100) if self.config.cap_usd > 0 else 0.0
                    result.append({"month": month_str, "total_pnl": total_pnl, "roi_pct": roi_pct})
                return result
            finally:
                connection.close()
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("paper_gate._aggregate_by_month_fail")
            return []

    def _get_trades_window(
        self,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Get all trades closed in [start, end] window.

        Returns list of dicts: [{"realized_pnl_usdt": 10.5, "ts_close": ..., ...}, ...]
        """
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        try:
            con = self.journal.db_path
        except Exception:
            return []

        try:
            import duckdb

            connection = duckdb.connect(str(con), read_only=True)
            try:
                rows = connection.execute(
                    """
                    SELECT
                        trade_id, ts_open, ts_close, sym, side, strategy,
                        entry_price, exit_price, qty,
                        realized_pnl_usdt, realized_r, win, close_reason
                    FROM futures_trades_closed
                    WHERE ts_close >= ? AND ts_close <= ?
                    ORDER BY ts_close
                    """,
                    [start, end],
                ).fetchall()

                result = []
                for row in rows:
                    result.append(
                        {
                            "trade_id": row[0],
                            "ts_open": row[1],
                            "ts_close": row[2],
                            "sym": row[3],
                            "side": row[4],
                            "strategy": row[5],
                            "entry_price": row[6],
                            "exit_price": row[7],
                            "qty": row[8],
                            "realized_pnl_usdt": float(row[9]),
                            "realized_r": row[10],
                            "win": row[11],
                            "close_reason": row[12],
                        }
                    )
                return result
            finally:
                connection.close()
        except Exception as exc:
            self._log.bind(err=str(exc)).warning("paper_gate._get_trades_window_fail")
            return []


__all__ = [
    "PaperGate",
    "PaperGateConfig",
    "GateResult",
]
