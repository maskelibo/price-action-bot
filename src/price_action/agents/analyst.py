"""Analyst Agent — Head of Performance Analytics.

KPI brief, post-mortem, weekly pack, anomaly check.
Postgres journal'ı (varsa) okur — defansif: yoksa boş veriyle çalışır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from price_action.logging_config import logger
from price_action.settings import get_settings

from .base import LLMAgentBase


class AnalystAgent(LLMAgentBase):
    name: ClassVar[str] = "analyst"
    default_model: ClassVar[str] = ""
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "sql_query",  # postgres journal
        "read_file",
        "write_report",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        s = get_settings()
        p = s.reports_dir / "analytics"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _query_trades(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Postgres journal'dan trade çek — bağlantı yoksa boş döner."""
        try:
            import psycopg  # type: ignore[import-not-found]

            with psycopg.connect(self.settings.postgres_dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT trade_id, symbol, side, entry_ts, exit_ts, "
                        "realized_pnl_usdt, realized_r_multiple, strategy_id, "
                        "pattern_id FROM trades WHERE exit_ts BETWEEN %s AND %s",
                        (start, end),
                    )
                    cols = [c.name for c in cur.description] if cur.description else []
                    rows = cur.fetchall()
                    return [dict(zip(cols, r)) for r in rows]
        except Exception as exc:
            logger.warning(
                "analyst.pg_unavailable",
                extra={"err": str(exc)[:200]},
            )
            return []

    # ------------------------------------------------------------------
    # SOP
    # ------------------------------------------------------------------

    async def daily_kpi_brief(self, when: date | None = None) -> Path:
        when = when or date.today()
        start = datetime.combine(when, datetime.min.time())
        end = datetime.combine(when, datetime.max.time())
        trades = self._query_trades(start, end)
        prompt = (
            "SOP-1 Günlük KPI Brief. Aşağıdaki trade listesini kullanarak "
            "günlük rapor üret: KPI snapshot, trade tablosu, regime split notu, "
            "bias/anomaly notları, CEO brief'ine 2 cümlelik özet.\n\n"
            f"TRADES: {trades}\n"
            f"DATE: {when.isoformat()}"
        )
        text = await self.run(prompt)
        path = self._reports_dir() / f"{when.isoformat()}.md"
        path.write_text(text, encoding="utf-8")
        return path

    async def postmortem(self, trade: dict[str, Any]) -> Path:
        """Tek bir kayıplı trade için post-mortem raporu."""
        prompt = (
            "SOP-2 Trade Post-Mortem. Aşağıdaki trade'i kategori ile sınıflandır "
            "(wrong_pattern / wrong_timing / wrong_size / regime_change / "
            "data_glitch / unlucky). Sayısal gerekçe ve aksiyon önerisi (varsa) "
            "belirt.\n\n"
            f"TRADE: {trade}"
        )
        text = await self.run(prompt)
        s = get_settings()
        out_dir = s.reports_dir / "postmortems"
        out_dir.mkdir(parents=True, exist_ok=True)
        trade_id = str(trade.get("trade_id", "unknown"))
        path = out_dir / f"{trade_id}.md"
        path.write_text(text, encoding="utf-8")
        return path

    async def weekly_pack(self, week_label: str | None = None) -> Path:
        if week_label is None:
            iso = datetime.now(timezone.utc).isocalendar()
            week_label = f"{iso.year}-W{iso.week:02d}"
        prompt = (
            "SOP-3 Haftalık Executive Pack. Net P&L + benchmark karşılaştırma "
            "(BTC HODL, ETH HODL), risk-adjusted metrics, strategy attribution, "
            "top winners/losers, outlier'lar, 3 watch-item."
        )
        text = await self.run(prompt)
        out = self._reports_dir() / "weekly" / f"{week_label}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return out

    def anomaly_check(self, returns: list[float]) -> dict[str, Any]:
        """Deterministik 3σ anomali tespiti — LLM çağırmaz.

        Returns: ``{"is_anomaly": bool, "z_max": float, "n": int}``.
        """
        if not returns:
            return {"is_anomaly": False, "z_max": 0.0, "n": 0}
        arr = np.asarray(returns, dtype=float)
        mu = float(arr.mean())
        sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
        if sd == 0:
            return {"is_anomaly": False, "z_max": 0.0, "n": int(arr.size), "mean": mu, "std": sd}
        z = float(np.max(np.abs((arr - mu) / sd)))
        return {
            "is_anomaly": bool(z > 3.0),
            "z_max": z,
            "n": int(arr.size),
            "mean": mu,
            "std": sd,
        }
