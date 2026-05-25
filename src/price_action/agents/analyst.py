"""Analyst Agent — Head of Performance Analytics.

KPI brief, post-mortem, weekly pack, anomaly check, what-if counterfactual.
Postgres journal'ı (varsa) okur — defansif: yoksa boş veriyle çalışır.

Faz 2.1: `whatif_analysis()` yeni metod — son N gün rejected sinyallerinin
"filtre olmasaydı" PnL'ini hesaplar. Postgres signals tablosu yoksa
`logs/futures_daemon.log`'dan parse eder. Çıktı protokol-uyumlu doc.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
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

    # ------------------------------------------------------------------
    # Faz 2.1 — what-if counterfactual analysis
    # ------------------------------------------------------------------

    _WIDESTOP_RE = re.compile(
        r"^\[(\d{2}):(\d{2}):(\d{2})\]\s+15M_REJECT_WIDESTOP:\s+(\S+)\s+sl_pct=([\d.]+)"
    )

    def _parse_widestop_rejections(
        self, log_path: Path, hours: int = 168
    ) -> list[dict[str, Any]]:
        """Daemon log'undan WIDESTOP rejection'larını parse et.

        Log timestamp'leri UTC; entry'leri kronolojik artar varsayımıyla
        gün geçişi sezilir.

        Returns
        -------
        list[dict]
            ``{ts_utc, symbol, sl_pct}`` dict'leri (son ``hours`` saatlik pencere).
        """
        if not log_path.exists():
            return []

        try:
            lines = log_path.read_text(encoding="utf-8").split("\n")
        except Exception as exc:
            logger.warning("analyst.log_read_fail", extra={"err": str(exc)[:200]})
            return []

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)
        # Heuristic: log'un başlangıç gününü bilmiyoruz; daemon uptime'dan tahmin
        # En basit: log dosyasının mtime'dan geriye gidip TS'lerden gün ata
        import os
        log_mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=timezone.utc)
        # Log mtime'a denk gelen son entry'yi bul, oradan başlayıp geriye sürkle gün
        last_hour = log_mtime.hour
        cur_day = log_mtime.date()
        # Önce dosyayı son satırdan başa doğru oku, gün geçişi sezdir
        prev_h = last_hour
        entries: list[tuple[datetime, str, float]] = []
        for line in reversed(lines):
            m = self._WIDESTOP_RE.match(line.strip())
            if not m:
                continue
            h, mi, _s, sym, sl = m.groups()
            h_int = int(h)
            # Geriye doğru ilerlerken saat artıyorsa gün geri at
            if h_int > prev_h + 1:
                cur_day -= timedelta(days=1)
            prev_h = h_int
            ts = datetime(cur_day.year, cur_day.month, cur_day.day, h_int, int(mi), 0, tzinfo=timezone.utc)
            entries.append((ts, sym, float(sl)))

        # Cutoff filtre + sıralı (kronolojik)
        entries.sort(key=lambda e: e[0])
        filtered = [(t, s, p) for t, s, p in entries if t >= cutoff]
        return [{"ts_utc": t, "symbol": s, "sl_pct": p} for t, s, p in filtered]

    def _simulate_counterfactual_pnl(
        self,
        rejections: list[dict[str, Any]],
        *,
        capital: float = 5000.0,
        risk_pct: float = 0.005,
        tp_r: float = 1.2,
        hold_bars: int = 8,
    ) -> dict[str, Any]:
        """Reddedilen sinyaller için forward-fill PnL tahmin (ccxt OHLCV).

        Side bilinmediği için LONG + SHORT iki ayrı simülasyon, 50/50 ortalama.

        Returns
        -------
        dict
            ``{long: {realized, unrealized, total, ...}, short: {...}, mix: {...}}``
        """
        if not rejections:
            return {"n": 0, "long": {}, "short": {}, "mix": {}}

        risk_usd = capital * risk_pct

        # ccxt fetch — son 60 saat OHLCV
        try:
            import ccxt  # type: ignore[import-not-found]
            ex = ccxt.binance({
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
                "timeout": 20000,
            })
        except Exception as exc:
            logger.warning("analyst.ccxt_unavailable", extra={"err": str(exc)[:200]})
            return {"n": len(rejections), "error": "ccxt unavailable", "long": {}, "short": {}, "mix": {}}

        symbols = sorted({r["symbol"] for r in rejections})
        ohlcv: dict[str, list[list[float]]] = {}
        # Fetch window: rejections min ts → now + 2h forward
        earliest = min(r["ts_utc"] for r in rejections)
        since_ms = int((earliest - timedelta(hours=2)).timestamp() * 1000)
        for sym in symbols:
            try:
                bars = ex.fetch_ohlcv(sym, "15m", since=since_ms, limit=500)
                ohlcv[sym] = bars
            except Exception as exc:
                logger.warning("analyst.ohlcv_fail", extra={"sym": sym, "err": str(exc)[:200]})
                ohlcv[sym] = []

        # Per-rejection simulation
        results_long: list[tuple[str, float, str]] = []  # (status, R, ts)
        results_short: list[tuple[str, float, str]] = []

        for rej in rejections:
            sym = rej["symbol"]
            ts = rej["ts_utc"]
            sl_pct = rej["sl_pct"]
            bars = ohlcv.get(sym, [])
            if not bars:
                continue
            # Find bar at signal_ts; entry = next bar's open
            ts_ms = int(ts.timestamp() * 1000)
            after = [b for b in bars if b[0] > ts_ms][:hold_bars + 1]
            if len(after) < 2:
                continue
            entry_price = after[0][1]  # open of next bar
            sl_dist = entry_price * sl_pct
            forward = after[1:hold_bars + 1]

            for direction, results in (("long", results_long), ("short", results_short)):
                if direction == "long":
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + tp_r * sl_dist
                else:
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - tp_r * sl_dist

                status = "OPEN"
                r_mult = 0.0
                out_ts = ""
                for b in forward:
                    ts_ms_b, _o, hi, lo, cl, _v = b
                    if direction == "long":
                        if lo <= sl_price:
                            status, r_mult = "SL", -1.0
                            out_ts = datetime.fromtimestamp(ts_ms_b / 1000, tz=timezone.utc).isoformat()
                            break
                        if hi >= tp_price:
                            status, r_mult = "TP", tp_r
                            out_ts = datetime.fromtimestamp(ts_ms_b / 1000, tz=timezone.utc).isoformat()
                            break
                    else:
                        if hi >= sl_price:
                            status, r_mult = "SL", -1.0
                            out_ts = datetime.fromtimestamp(ts_ms_b / 1000, tz=timezone.utc).isoformat()
                            break
                        if lo <= tp_price:
                            status, r_mult = "TP", tp_r
                            out_ts = datetime.fromtimestamp(ts_ms_b / 1000, tz=timezone.utc).isoformat()
                            break
                if status == "OPEN":
                    # Mark-to-market last close
                    last_close = forward[-1][4]
                    if direction == "long":
                        r_mult = (last_close - entry_price) / sl_dist if sl_dist > 0 else 0.0
                    else:
                        r_mult = (entry_price - last_close) / sl_dist if sl_dist > 0 else 0.0
                    out_ts = datetime.fromtimestamp(forward[-1][0] / 1000, tz=timezone.utc).isoformat()
                results.append((status, r_mult, out_ts))

        def _summarize(results: list[tuple[str, float, str]]) -> dict[str, Any]:
            if not results:
                return {"n": 0}
            closed = [r for r in results if r[0] in ("SL", "TP")]
            open_ = [r for r in results if r[0] == "OPEN"]
            realized_r = sum(r[1] for r in closed)
            unrealized_r = sum(r[1] for r in open_)
            realized_usd = realized_r * risk_usd
            unrealized_usd = unrealized_r * risk_usd
            return {
                "n_total": len(results),
                "n_closed": len(closed),
                "n_open": len(open_),
                "n_tp": sum(1 for r in closed if r[0] == "TP"),
                "n_sl": sum(1 for r in closed if r[0] == "SL"),
                "realized_usd": round(realized_usd, 2),
                "unrealized_usd": round(unrealized_usd, 2),
                "total_usd": round(realized_usd + unrealized_usd, 2),
                "realized_pct": round(realized_usd / capital * 100, 2),
                "unrealized_pct": round(unrealized_usd / capital * 100, 2),
                "total_pct": round((realized_usd + unrealized_usd) / capital * 100, 2),
            }

        long_summary = _summarize(results_long)
        short_summary = _summarize(results_short)
        mix_realized = (long_summary.get("realized_usd", 0) + short_summary.get("realized_usd", 0)) / 2
        mix_unrealized = (long_summary.get("unrealized_usd", 0) + short_summary.get("unrealized_usd", 0)) / 2

        return {
            "n_rejected": len(rejections),
            "n_simulated": long_summary.get("n_total", 0),
            "capital": capital,
            "risk_pct": risk_pct,
            "risk_usd": risk_usd,
            "tp_r": tp_r,
            "hold_bars": hold_bars,
            "long": long_summary,
            "short": short_summary,
            "mix": {
                "realized_usd": round(mix_realized, 2),
                "unrealized_usd": round(mix_unrealized, 2),
                "total_usd": round(mix_realized + mix_unrealized, 2),
                "realized_pct": round(mix_realized / capital * 100, 2),
                "unrealized_pct": round(mix_unrealized / capital * 100, 2),
                "total_pct": round((mix_realized + mix_unrealized) / capital * 100, 2),
            },
        }

    async def whatif_analysis(
        self,
        window_days: int = 7,
        *,
        capital: float = 5000.0,
        risk_pct: float = 0.005,
        tp_r: float = 1.2,
        write_doc: bool = True,
    ) -> Path | dict[str, Any]:
        """Son ``window_days`` rejection'lar için "filtre olmasaydı" PnL.

        İki kaynak denenir:
        1. Postgres `signals` tablo (Faz 3+ canlı olduğunda)
        2. `logs/futures_daemon.log` WIDESTOP parse (mevcut Faz 1)

        Çıktı: `reports/analytics/whatif-YYYY-WW.md` (frontmatter:
        ``doc_type: whatif``, ``requested_review_from: [risk_officer, researcher]``)

        Returns
        -------
        Path | dict
            ``write_doc=True`` → doc path, False → raw stats dict.
        """
        # 1) Veri çek
        s = get_settings()
        log_path = s.reports_dir.parent / "logs" / "futures_daemon.log"
        rejections = self._parse_widestop_rejections(log_path, hours=window_days * 24)

        if not rejections:
            logger.info("analyst.whatif_no_data", extra={"window_days": window_days})
            stats = {"n_rejected": 0, "error": "No WIDESTOP rejections found in window"}
        else:
            # 2) Simulate
            stats = self._simulate_counterfactual_pnl(
                rejections,
                capital=capital,
                risk_pct=risk_pct,
                tp_r=tp_r,
            )

        if not write_doc:
            return stats

        # 3) LLM narrative + frontmatter doc
        iso = datetime.now(timezone.utc).isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"

        # Top rejected symbols
        from collections import Counter
        sym_counter = Counter(r["symbol"] for r in rejections)
        top_syms = sym_counter.most_common(10)

        prompt = (
            f"What-if counterfactual analysis. Son {window_days} gündeki WIDESTOP "
            "filtrelerinden geçemeyen sinyaller için 'filtre olmasaydı' tahmini PnL.\n\n"
            "STATS:\n"
            f"{stats}\n\n"
            f"TOP REJECTED SYMBOLS: {top_syms}\n\n"
            "Görevin: Frontmatter (template: memory/shared/templates/whatif.md.tmpl) "
            "+ markdown body üret. Body yapısı:\n"
            "1. Setup (window, capital, risk, TP rule, hold cap)\n"
            "2. Filter / Halt Stats (toplam reject, sembol bazında)\n"
            "3. Counterfactual PnL tablosu (LONG/SHORT/50-50, USD + %)\n"
            "4. Filter cost ranking\n"
            "5. Pattern (önceki haftalarla karşılaştırma — şu hafta yorum yap)\n"
            "6. Aksiyon önerisi (Researcher'a/Risk Officer'a directed)\n"
            "7. Caveats (sample size, side unknown, slippage exclusion, OHLCV penceresi)\n\n"
            "DİKKAT: Honest caveat'leri MUTLAKA dahil et — LONG/SHORT mean ± uncertainty "
            "ile birlikte. 50/50 ortalama yanıltıcı olabilir; gerçek strateji tipi reversal "
            "ise SHORT'a daha yakın sonuç."
        )
        body = await self.run(prompt)

        # write_protocol_doc kullan (frontmatter otomatik)
        doc_path = self.write_protocol_doc(
            doc_type="whatif",
            body=body,
            slug=f"whatif-{week_label}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="med",
            requested_review_from=["risk_officer", "researcher"],
            tags=["whatif", "counterfactual", "weekly"],
        )
        return doc_path
