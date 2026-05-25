"""Bot Monitor Agent — per-bot equity/health watcher.

Faz 6: hybrid agent. Çoğu iş deterministik (DuckDB query + threshold check);
LLM (Haiku) sadece günlük report card'da bot başına 3-satır özet için kullanılır.

HARD LIMIT (`agents/bot_monitor.md` §Hard Limits):
- Bot daemon'a doğrudan müdahale YOK — sadece dosya yazar.
- `configs/bot_kill_criteria.yaml` READ-ONLY.
- Otomatik PAUSE YOK — WARN → 24h hold → PAUSE öneri (manuel onay şart).
- Bu modül scheduler.py'a kendisini register etmez; orchestrator entegre eder.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger

from .base import LLMAgentBase


# ---------------------------------------------------------------------------
# Module-level helpers (testable without instantiating the agent)
# ---------------------------------------------------------------------------

def _calc_drawdown(equity_series: list[float]) -> float:
    """Equity serisinden max drawdown (kesir, pozitif sayı).

    DD = max((peak - trough) / peak) running peak üzerinden.
    Boş/tek-elemanlı seri → 0.0. Negatif equity desteklenir (peak monoton artar,
    trough peak'in altındaki en derin nokta).
    """
    if not equity_series or len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for v in equity_series:
        if v > peak:
            peak = v
        if peak <= 0:
            # Equity sıfır/negatif olduysa drawdown tanımsız — 0 dön (defensive).
            continue
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return float(max_dd)


def _calc_attribution(trades: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    """Trade listesinden (strategy, symbol) bazında PnL + trade sayısı + win rate.

    Trade dict şeması (futures_trades_closed):
        strategy, sym, realized_pnl_usdt, win (bool)

    Dönen dict: { (strategy, sym): {"pnl": X, "n": N, "wins": W, "win_rate": ratio} }
    """
    agg: dict[tuple[str, str], dict[str, float]] = {}
    for t in trades:
        key = (str(t.get("strategy", "?")), str(t.get("sym", "?")))
        bucket = agg.setdefault(key, {"pnl": 0.0, "n": 0.0, "wins": 0.0, "win_rate": 0.0})
        bucket["pnl"] += float(t.get("realized_pnl_usdt", 0.0) or 0.0)
        bucket["n"] += 1
        if t.get("win"):
            bucket["wins"] += 1
    for key, b in agg.items():
        b["win_rate"] = (b["wins"] / b["n"]) if b["n"] > 0 else 0.0
    return agg


def _evaluate_threshold_breach(
    *,
    starting_equity: float,
    current_equity: float,
    equity_series: list[float],
    consecutive_losses: int,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """Eşik aşımlarını değerlendir, breached flag + detay dön.

    thresholds keys: cum_loss_7d_pct (or whichever window caller measured),
    max_drawdown_pct, consecutive_losses
    """
    breached: list[str] = []
    cum_loss_pct = 0.0
    if starting_equity > 0:
        cum_loss_pct = max(0.0, (starting_equity - current_equity) / starting_equity)
    dd_pct = _calc_drawdown(equity_series)

    if "cum_loss_pct" in thresholds and cum_loss_pct > thresholds["cum_loss_pct"]:
        breached.append(f"cum_loss_pct={cum_loss_pct:.4f}>thr={thresholds['cum_loss_pct']:.4f}")
    if "max_drawdown_pct" in thresholds and dd_pct > thresholds["max_drawdown_pct"]:
        breached.append(f"max_drawdown_pct={dd_pct:.4f}>thr={thresholds['max_drawdown_pct']:.4f}")
    if (
        "consecutive_losses" in thresholds
        and consecutive_losses >= int(thresholds["consecutive_losses"])
    ):
        breached.append(
            f"consecutive_losses={consecutive_losses}>=thr={int(thresholds['consecutive_losses'])}"
        )
    return {
        "breached": breached,
        "cum_loss_pct": cum_loss_pct,
        "max_drawdown_pct": dd_pct,
        "consecutive_losses": consecutive_losses,
    }


def _count_consecutive_losses(trades_chrono: list[dict[str, Any]]) -> int:
    """En son trade'den geriye doğru ardışık loss sayısı."""
    count = 0
    for t in reversed(trades_chrono):
        if t.get("win"):
            break
        # `win` False veya None ise loss say (defensive — net pnl<0)
        if float(t.get("realized_pnl_usdt", 0.0) or 0.0) <= 0:
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class BotMonitorAgent(LLMAgentBase):
    """Saatlik snapshot + günlük report card + kill-criteria evaluator.

    Tüm dosya çıktıları `reports/bot_monitor/` altına. LLM (Haiku) sadece
    daily_report_cards()'da bot başına 3-satır özet için. Diğer iki SOP
    deterministik.
    """

    name: ClassVar[str] = "bot_monitor"
    default_model: ClassVar[str] = "claude-haiku-4-5-20251001"
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",   # journal DuckDB + config yaml
        "sql_query",   # DuckDB SELECT (read-only)
        "write_report",  # snapshot / card / alert md
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = "claude-haiku-4-5-20251001"

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _reports_root(self) -> Path:
        d = self.settings.reports_dir / "bot_monitor"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _config_path(self) -> Path:
        # ROOT_DIR / configs / bot_kill_criteria.yaml
        return self.settings.reports_dir.parent / "configs" / "bot_kill_criteria.yaml"

    def _resolve_journal_path(self, journal: str | Path) -> Path:
        """Config'teki journal path göreceliyse ROOT_DIR'a göre çöz."""
        p = Path(journal)
        if p.is_absolute():
            return p
        return self.settings.reports_dir.parent / p

    def _warn_state_path(self) -> Path:
        # WARN→PAUSE hold için durum (per-bot ilk warn timestamp)
        d = self._reports_root() / "_state"
        d.mkdir(parents=True, exist_ok=True)
        return d / "warn_state.json"

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> dict[str, Any]:
        path = self._config_path()
        if not path.exists():
            logger.warning("bot_monitor.config_missing", extra={"path": str(path)})
            return {"bots": {}, "defaults": {}}
        try:
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(
                "bot_monitor.config_load_fail",
                extra={"path": str(path), "err": str(exc)[:200]},
            )
            return {"bots": {}, "defaults": {}}

    # ------------------------------------------------------------------
    # Journal read
    # ------------------------------------------------------------------

    def _check_postgres_journal(self, path: str | Path) -> bool:
        """Journal DuckDB var mı + futures_trades_closed tablosu açılıyor mu?

        Naming legacy: "postgres" kelimesi tarihten kalma; aslında DuckDB.
        DuckDB yoksa False dön (test ortamı için).
        """
        p = Path(path)
        if not p.exists():
            return False
        try:
            import duckdb  # type: ignore[import-not-found]
        except Exception:
            logger.warning("bot_monitor.duckdb_missing")
            return False
        try:
            con = duckdb.connect(str(p), read_only=True)
            try:
                tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                return "futures_trades_closed" in tables
            finally:
                con.close()
        except Exception as exc:
            logger.warning(
                "bot_monitor.journal_check_fail",
                extra={"path": str(p), "err": str(exc)[:200]},
            )
            return False

    def _read_trades(
        self,
        journal_path: str | Path,
        *,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """`futures_trades_closed`'tan kapanmış trade'leri çek (kronolojik).

        Test ortamında DuckDB yoksa boş liste döner (deterministik no-op).
        """
        if not self._check_postgres_journal(journal_path):
            return []
        try:
            import duckdb  # type: ignore[import-not-found]
        except Exception:
            return []
        try:
            con = duckdb.connect(str(journal_path), read_only=True)
            try:
                if since is not None:
                    rows = con.execute(
                        """
                        SELECT trade_id, ts_open, ts_close, sym, side, strategy,
                               entry_price, exit_price, qty,
                               realized_pnl_usdt, realized_r, win, close_reason
                          FROM futures_trades_closed
                         WHERE ts_close >= ?
                         ORDER BY ts_close ASC
                        """,
                        [since],
                    ).fetchall()
                else:
                    rows = con.execute(
                        """
                        SELECT trade_id, ts_open, ts_close, sym, side, strategy,
                               entry_price, exit_price, qty,
                               realized_pnl_usdt, realized_r, win, close_reason
                          FROM futures_trades_closed
                         ORDER BY ts_close ASC
                        """
                    ).fetchall()
                cols = [
                    "trade_id", "ts_open", "ts_close", "sym", "side", "strategy",
                    "entry_price", "exit_price", "qty",
                    "realized_pnl_usdt", "realized_r", "win", "close_reason",
                ]
                return [dict(zip(cols, r)) for r in rows]
            finally:
                con.close()
        except Exception as exc:
            logger.warning(
                "bot_monitor.read_trades_fail",
                extra={"path": str(journal_path), "err": str(exc)[:200]},
            )
            return []

    @staticmethod
    def _calc_drawdown(equity_series: list[float]) -> float:
        """Public wrapper — testlerde de çağrılabilir."""
        return _calc_drawdown(equity_series)

    @staticmethod
    def _calc_attribution(trades: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
        return _calc_attribution(trades)

    @staticmethod
    def _equity_curve(trades_chrono: list[dict[str, Any]], starting_equity: float = 0.0) -> list[float]:
        """cum_sum realized_pnl_usdt — equity curve."""
        eq = starting_equity
        out: list[float] = []
        for t in trades_chrono:
            eq += float(t.get("realized_pnl_usdt", 0.0) or 0.0)
            out.append(eq)
        return out

    # ------------------------------------------------------------------
    # Blind-spot detector (FIX 2026-05-25)
    # ------------------------------------------------------------------
    # Problem: previous hourly_snapshot only reported equity/DD/last_trade
    # as informational. It did NOT flag "bot has 0 trades in N days" or
    # "all rejects are the same technical reason" — so the Principal had
    # to manually notice 3 days of zero activity.
    #
    # detect_blind_spots() returns a list of alert dicts. hourly_snapshot
    # calls it and pushes CRITICAL Telegram if any alert is high-severity.
    # Alerts have shape:
    #   {bot, severity, kind, message, evidence}
    # severity ∈ "info" | "warn" | "crit"
    # kind ∈ "stale_no_trades" | "uniform_tech_reject" | "heartbeat_dead"
    # ------------------------------------------------------------------

    def detect_blind_spots(
        self,
        bot_name: str,
        *,
        trades: list[dict[str, Any]],
        last_trade: dict[str, Any] | None,
        now: datetime,
        no_trade_warn_hours: int = 24,
        no_trade_crit_hours: int = 72,
        log_path: Path | None = None,
        reject_window_minutes: int = 60,
        uniform_reject_threshold: float = 0.90,
    ) -> list[dict[str, Any]]:
        """Bot için kör nokta tespiti.

        İki kontrol:
        1. Stale no-trade: son trade kapanışı > N saat önce ise WARN/CRIT.
        2. Uniform tech reject: son N dakikadaki reject'lerin %X'i aynı
           TEKNİK sebep ise (widestop hariç — o tasarım gereği) → CRIT.

        Returns:
            Tespit edilen alert listesi (boş ise sorun yok).
        """
        alerts: list[dict[str, Any]] = []

        # ---- Check 1: stale no-trade ---------------------------------
        if last_trade is None:
            # 30 günde 0 trade
            alerts.append({
                "bot": bot_name,
                "severity": "warn",
                "kind": "stale_no_trades",
                "message": f"{bot_name}: son 30 günde HİÇ trade yok.",
                "evidence": {"n_trades_30d": 0},
            })
        else:
            ts_close = last_trade.get("ts_close")
            if ts_close:
                try:
                    last_close = self._to_utc(ts_close)
                    hours_since = (now - last_close).total_seconds() / 3600.0
                    if hours_since >= no_trade_crit_hours:
                        alerts.append({
                            "bot": bot_name,
                            "severity": "crit",
                            "kind": "stale_no_trades",
                            "message": (
                                f"{bot_name}: {hours_since:.1f} saattir hiç trade yok "
                                f"(eşik CRIT={no_trade_crit_hours}h). "
                                f"Reject pattern'ı kontrol et."
                            ),
                            "evidence": {"hours_since_last_trade": round(hours_since, 1)},
                        })
                    elif hours_since >= no_trade_warn_hours:
                        alerts.append({
                            "bot": bot_name,
                            "severity": "warn",
                            "kind": "stale_no_trades",
                            "message": (
                                f"{bot_name}: {hours_since:.1f} saattir trade yok "
                                f"(eşik WARN={no_trade_warn_hours}h)."
                            ),
                            "evidence": {"hours_since_last_trade": round(hours_since, 1)},
                        })
                except Exception:
                    pass  # ts parse hatası — sessiz geç

        # ---- Check 2: uniform tech reject ----------------------------
        # Daemon log'unu (varsa) tarayıp son N dakikadaki REJECT pattern'ını
        # analiz et. "WIDESTOP" tasarım gereği — sayılmaz. Diğer her şey
        # (regime_cache_stale, import_fail, vb.) TEKNİK bug indikatörü.
        if log_path and log_path.exists():
            try:
                cutoff_clock = (now - timedelta(minutes=reject_window_minutes)).strftime("%H:%M")
                # Log format: [HH:MM:SS] 15M_REJECT_RISK: SYM strat reason=X
                rejects: dict[str, int] = {}
                total_rejects = 0
                widestop_count = 0
                # Read tail efficiently
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-2000:]
                for line in lines:
                    if "REJECT" not in line:
                        continue
                    # Time gate (HH:MM string compare — yeterince doğru)
                    m = re.match(r"^\[(\d{2}:\d{2}):\d{2}\]", line)
                    if not m or m.group(1) < cutoff_clock:
                        continue
                    if "REJECT_WIDESTOP" in line:
                        widestop_count += 1
                        continue  # tasarım gereği, atla
                    # reason=X parse
                    rm = re.search(r"reason=(\S+)", line)
                    reason = rm.group(1) if rm else "unknown"
                    rejects[reason] = rejects.get(reason, 0) + 1
                    total_rejects += 1

                if total_rejects >= 3:  # anlamlı örneklem
                    top_reason, top_count = max(rejects.items(), key=lambda x: x[1])
                    ratio = top_count / total_rejects
                    if ratio >= uniform_reject_threshold:
                        alerts.append({
                            "bot": bot_name,
                            "severity": "crit",
                            "kind": "uniform_tech_reject",
                            "message": (
                                f"{bot_name}: son {reject_window_minutes}dk içinde "
                                f"{total_rejects} non-widestop reject'in %{ratio*100:.0f}'i "
                                f"`{top_reason}` (teknik bug muhtemel)."
                            ),
                            "evidence": {
                                "reason": top_reason,
                                "count": top_count,
                                "total_non_widestop_rejects": total_rejects,
                                "widestop_rejects": widestop_count,
                            },
                        })
            except Exception as exc:
                logger.warning(
                    "bot_monitor.blind_spot_log_parse_fail",
                    extra={"bot": bot_name, "err": str(exc)[:200]},
                )

        return alerts

    @staticmethod
    def _resolve_log_path(bot_name: str) -> Path | None:
        """Bot adından launchd stderr log path'i türet."""
        try:
            from price_action.settings import get_settings
            s = get_settings()
            candidates = [
                s.reports_dir.parent / "logs" / "launchd" / f"{bot_name}.stderr.log",
                s.reports_dir.parent / "logs" / "launchd" / f"{bot_name}.stdout.log",
                s.reports_dir.parent / "logs" / f"futures_daemon{'_5m' if '5m' in bot_name else ''}.log",
            ]
            for p in candidates:
                if p.exists():
                    return p
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # SOP-1: Hourly Snapshot
    # ------------------------------------------------------------------

    async def hourly_snapshot(self) -> Path | None:
        """Per-bot equity / last-trade / DD30 / halt status snapshot.

        Deterministik — LLM çağırmaz. Dosya: snapshot-YYYY-MM-DD-HH.md.
        Doc'u protokol-uyumlu olarak yazar (write_protocol_doc).
        """
        cfg = self._load_config()
        bots = cfg.get("bots") or {}
        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=30)

        lines: list[str] = [f"# Bot Snapshot — {now.strftime('%Y-%m-%d %H:00 UTC')}", ""]
        active_bots: list[str] = []
        all_alerts: list[dict[str, Any]] = []  # FIX 2026-05-25 blind-spot

        for bot_name, bot_cfg in bots.items():
            journal = self._resolve_journal_path(bot_cfg.get("journal", ""))
            ok = self._check_postgres_journal(journal)
            trades = self._read_trades(journal, since=since_30d) if ok else []
            equity = self._equity_curve(trades)
            current_equity = equity[-1] if equity else 0.0
            dd30 = self._calc_drawdown(equity)
            # Son 24h P&L
            cutoff_24h = now - timedelta(hours=24)
            pnl_24h = sum(
                float(t.get("realized_pnl_usdt", 0.0) or 0.0)
                for t in trades
                if t.get("ts_close") and self._to_utc(t["ts_close"]) >= cutoff_24h
            )
            last_trade = trades[-1] if trades else None
            heartbeat_ok = self._heartbeat_check(bot_name)

            # FIX 2026-05-25: blind-spot detection
            log_path = self._resolve_log_path(bot_name)
            bot_alerts = self.detect_blind_spots(
                bot_name,
                trades=trades,
                last_trade=last_trade,
                now=now,
                log_path=log_path,
            )
            all_alerts.extend(bot_alerts)

            lines.append(f"## {bot_name}")
            lines.append(f"- Journal: `{journal}` — {'OK' if ok else 'MISSING'}")
            lines.append(f"- Trades (30d): {len(trades)}")
            lines.append(f"- Equity (cum realized): ${current_equity:.2f}")
            lines.append(f"- P&L 24h: ${pnl_24h:.2f}")
            lines.append(f"- Rolling 30d MaxDD: %{dd30 * 100:.2f}")
            if last_trade:
                lines.append(
                    f"- Last trade: {last_trade.get('ts_close')} / "
                    f"{last_trade.get('sym')} / {last_trade.get('side')} / "
                    f"R={float(last_trade.get('realized_r', 0.0) or 0.0):.2f}"
                )
            else:
                lines.append("- Last trade: (none in 30d)")
            lines.append(f"- Heartbeat: {'OK' if heartbeat_ok else 'STALE/MISSING'}")
            if bot_alerts:
                lines.append(f"- ⚠️ Blind-spot alerts: {len(bot_alerts)}")
                for a in bot_alerts:
                    lines.append(f"  - [{a['severity'].upper()}] {a['kind']}: {a['message']}")
            lines.append("")
            active_bots.append(bot_name)

        # FIX 2026-05-25: CRIT alerts'i Telegram'a push'la (parse_mode=None artık güvenli)
        crit_alerts = [a for a in all_alerts if a["severity"] == "crit"]
        if crit_alerts:
            try:
                from price_action.orchestrator.notifications import push_critical
                msg = f"BOT BLIND-SPOT — {len(crit_alerts)} CRIT alert(s):\n" + "\n".join(
                    f"- {a['message']}" for a in crit_alerts
                )
                push_critical(msg, source="bot_monitor")
            except Exception as exc:
                logger.warning(
                    "bot_monitor.blind_spot_push_fail",
                    extra={"err": str(exc)[:200], "n_crit": len(crit_alerts)},
                )

        body = "\n".join(lines)
        slug = f"snapshot-{now.strftime('%Y-%m-%d-%H')}"
        path = self.write_protocol_doc(
            doc_type="bot_health_report",
            body=body,
            slug=slug,
            target_dir=self._reports_root(),
            status="FINAL",
            confidence="high",
            tags=["snapshot", "deterministic"] + active_bots,
        )
        logger.info(
            "bot_monitor.snapshot_done",
            extra={"path": str(path), "bots": active_bots},
        )
        return path

    @staticmethod
    def _to_utc(ts: Any) -> datetime:
        """DuckDB rows tz-naive UTC TIMESTAMP döner; aware'a yükselt."""
        if isinstance(ts, datetime):
            return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        try:
            return datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    def _heartbeat_check(self, bot_name: str) -> bool:
        """`data/dms_heartbeat_*{bot_name}*.txt` son 1h içinde update mı?"""
        data_dir = self.settings.reports_dir.parent / "data"
        if not data_dir.exists():
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        for hb in data_dir.glob(f"dms_heartbeat_*{bot_name}*.txt"):
            try:
                mtime = datetime.fromtimestamp(hb.stat().st_mtime, tz=timezone.utc)
                if mtime >= cutoff:
                    return True
            except OSError:
                continue
        # Bot adı eşleşmesi yoksa heuristic — daemon adı farklı olabilir.
        return False

    # ------------------------------------------------------------------
    # SOP-2: Daily Report Cards
    # ------------------------------------------------------------------

    async def daily_report_cards(self) -> Path | None:
        """Günlük per-bot card. Haiku ile bot başına 3-satır özet.

        Telegram chunked output: her bot ayrı section, ilk satır 280-char özet.
        """
        cfg = self._load_config()
        bots = cfg.get("bots") or {}
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        since_7d = now - timedelta(days=7)

        sections: list[str] = [f"# Bot Daily Cards — {now.strftime('%Y-%m-%d')}", ""]
        per_bot_summary_inputs: list[dict[str, Any]] = []

        for bot_name, bot_cfg in bots.items():
            journal = self._resolve_journal_path(bot_cfg.get("journal", ""))
            trades_24h = self._read_trades(journal, since=since_24h)
            trades_7d = self._read_trades(journal, since=since_7d)

            pnl_24h = sum(float(t.get("realized_pnl_usdt", 0) or 0) for t in trades_24h)
            n_24h = len(trades_24h)
            wins_24h = sum(1 for t in trades_24h if t.get("win"))
            wr_24h = (wins_24h / n_24h) if n_24h > 0 else 0.0
            avg_r_24h = (
                sum(float(t.get("realized_r", 0) or 0) for t in trades_24h) / n_24h
                if n_24h > 0
                else 0.0
            )
            pnl_7d = sum(float(t.get("realized_pnl_usdt", 0) or 0) for t in trades_7d)
            equity_7d = self._equity_curve(trades_7d)
            dd_7d = self._calc_drawdown(equity_7d)

            # Top winner / loser
            top_winner = max(
                trades_24h,
                key=lambda t: float(t.get("realized_pnl_usdt", 0) or 0),
                default=None,
            )
            top_loser = min(
                trades_24h,
                key=lambda t: float(t.get("realized_pnl_usdt", 0) or 0),
                default=None,
            )

            # Attribution
            attribution = self._calc_attribution(trades_7d)
            attr_lines = [
                f"  - {strategy}/{sym}: pnl=${v['pnl']:.2f} n={int(v['n'])} wr={v['win_rate']*100:.0f}%"
                for (strategy, sym), v in sorted(
                    attribution.items(), key=lambda kv: kv[1]["pnl"], reverse=True
                )[:10]
            ]

            sections.append(f"## {bot_name}")
            sections.append(
                f"- 24h: trades={n_24h}, P&L=${pnl_24h:.2f}, win={wr_24h*100:.1f}%, avg_R={avg_r_24h:.2f}"
            )
            sections.append(f"- 7g rolling: P&L=${pnl_7d:.2f}, MaxDD=%{dd_7d*100:.2f}, n_trades={len(trades_7d)}")
            if top_winner:
                sections.append(
                    f"- Top winner (24h): {top_winner.get('sym')} / "
                    f"{top_winner.get('strategy')} / ${float(top_winner.get('realized_pnl_usdt',0) or 0):.2f}"
                )
            if top_loser:
                sections.append(
                    f"- Top loser (24h): {top_loser.get('sym')} / "
                    f"{top_loser.get('strategy')} / ${float(top_loser.get('realized_pnl_usdt',0) or 0):.2f}"
                )
            if attr_lines:
                sections.append("- Attribution (7g, top-10):")
                sections.extend(attr_lines)
            else:
                sections.append("- Attribution: (no trades in 7d)")

            per_bot_summary_inputs.append({
                "bot": bot_name,
                "pnl_24h": pnl_24h,
                "pnl_7d": pnl_7d,
                "wr_24h": wr_24h,
                "n_24h": n_24h,
                "dd_7d": dd_7d,
            })
            sections.append("")

        # Haiku özet: bot başına 3 satır
        if per_bot_summary_inputs:
            prompt = (
                "Sen Bot Monitor'sın. Her bot için tam 3 satır özet üret. "
                "Format: '<bot>: 24h <±%>, 7g <±%>, win <%>, <comment>'. "
                "Comment kısa (5-8 kelime). Sayılar verilen input'tan. "
                "Hiçbir hipotez/anlatı yok, sadece sayı + 1 nitel etiket "
                "(örn. 'no halt', 'in drawdown', 'low activity').\n\n"
                f"INPUT:\n{json.dumps(per_bot_summary_inputs, indent=2)}"
            )
            try:
                summary_text = await self.run(prompt, max_tokens=512, temperature=0.1)
            except Exception as exc:
                logger.warning("bot_monitor.summary_fail", extra={"err": str(exc)[:200]})
                summary_text = "(LLM summary unavailable)"
            sections.append("## LLM özet (Haiku)\n")
            sections.append(summary_text)
            sections.append("")

        body = "\n".join(sections)
        slug = f"cards-{now.strftime('%Y-%m-%d')}"
        path = self.write_protocol_doc(
            doc_type="bot_daily_card",
            body=body,
            slug=slug,
            target_dir=self._reports_root(),
            status="FINAL",
            confidence="high",
            requested_review_from=["ceo"],
            tags=["daily_card", "telegram_push"],
        )
        logger.info("bot_monitor.daily_card_done", extra={"path": str(path)})
        return path

    # ------------------------------------------------------------------
    # SOP-3: Kill Criteria Evaluation
    # ------------------------------------------------------------------

    def _load_warn_state(self) -> dict[str, Any]:
        p = self._warn_state_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_warn_state(self, state: dict[str, Any]) -> None:
        p = self._warn_state_path()
        p.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    async def evaluate_kill_criteria(self) -> Path | None:
        """Tüm bot'lar için kill criteria check. WARN ya da PAUSE öneri.

        Akış:
        - Eşik altı → WARN state varsa CLEAR doc, yoksa no-op.
        - Eşik üstü + WARN state YOK → WARN doc + state'e timestamp.
        - Eşik üstü + WARN state VAR + warn_hold_hours geçmiş → PAUSE öneri.
        - Eşik üstü + WARN state VAR + henüz hold süresinde → no-op (silent).
        """
        cfg = self._load_config()
        bots = cfg.get("bots") or {}
        defaults = cfg.get("defaults") or {}
        warn_hold_hours = int(defaults.get("warn_hold_hours", 24))
        warn_first = bool(defaults.get("warn_first", True))

        now = datetime.now(timezone.utc)
        warn_state = self._load_warn_state()
        alert_paths: list[Path] = []
        alerts_summary: list[str] = []

        for bot_name, bot_cfg in bots.items():
            journal = self._resolve_journal_path(bot_cfg.get("journal", ""))
            thresholds = bot_cfg.get("kill_thresholds") or {}

            # 7g window default kill metric — yaml'da cum_loss_7d_pct ana eşik
            since_7d = now - timedelta(days=7)
            trades_7d = self._read_trades(journal, since=since_7d)
            since_14d = now - timedelta(days=14)
            trades_14d = self._read_trades(journal, since=since_14d)

            equity_7d = self._equity_curve(trades_7d)
            # cum loss 7d / 14d (basit: realized PnL toplamı negatif mi)
            cum_pnl_7d = sum(float(t.get("realized_pnl_usdt", 0) or 0) for t in trades_7d)
            cum_pnl_14d = sum(float(t.get("realized_pnl_usdt", 0) or 0) for t in trades_14d)
            # Approx starting equity = current equity - cum_pnl (relative loss pct)
            current_equity = equity_7d[-1] if equity_7d else 0.0
            # Test/empty journal'da bot equity baseline yok → mutlak loss pct
            # için 1.0 baseline kullanırız (cum_pnl negatifse pct = -pnl);
            # threshold pct < 1 olduğundan büyük loss'larda doğru tetikler.
            baseline = max(abs(current_equity - cum_pnl_7d), 1.0)
            cum_loss_7d_pct = max(0.0, -cum_pnl_7d / baseline)
            baseline_14d = max(abs((equity_7d[-1] if equity_7d else 0.0) - cum_pnl_14d), 1.0)
            cum_loss_14d_pct = max(0.0, -cum_pnl_14d / baseline_14d)

            dd30 = self._calc_drawdown(self._equity_curve(self._read_trades(journal, since=now - timedelta(days=30))))
            consec = _count_consecutive_losses(trades_14d)

            # Eşik komparasyon
            breaches: list[str] = []
            if "cum_loss_7d_pct" in thresholds and cum_loss_7d_pct > float(thresholds["cum_loss_7d_pct"]):
                breaches.append(
                    f"cum_loss_7d_pct={cum_loss_7d_pct:.4f} > thr={float(thresholds['cum_loss_7d_pct']):.4f}"
                )
            if "cum_loss_14d_pct" in thresholds and cum_loss_14d_pct > float(thresholds["cum_loss_14d_pct"]):
                breaches.append(
                    f"cum_loss_14d_pct={cum_loss_14d_pct:.4f} > thr={float(thresholds['cum_loss_14d_pct']):.4f}"
                )
            if "max_drawdown_pct" in thresholds and dd30 > float(thresholds["max_drawdown_pct"]):
                breaches.append(
                    f"max_drawdown_pct={dd30:.4f} > thr={float(thresholds['max_drawdown_pct']):.4f}"
                )
            if "consecutive_losses" in thresholds and consec >= int(thresholds["consecutive_losses"]):
                breaches.append(
                    f"consecutive_losses={consec} >= thr={int(thresholds['consecutive_losses'])}"
                )

            bot_state = warn_state.get(bot_name) or {}
            first_warn_at = bot_state.get("first_warn_at")

            if not breaches:
                # Clear varsa
                if first_warn_at:
                    body = self._build_alert_body(
                        bot_name, "CLEAR",
                        breaches=[],
                        cum_loss_7d_pct=cum_loss_7d_pct,
                        cum_loss_14d_pct=cum_loss_14d_pct,
                        dd30=dd30,
                        consec=consec,
                        recommendation="No action — thresholds back to safe range.",
                    )
                    p = self.write_protocol_doc(
                        doc_type="kill_criteria_alert",
                        body=body,
                        slug=f"clear-{bot_name}-{now.strftime('%Y%m%dT%H%M%S')}",
                        target_dir=self._reports_root(),
                        status="FINAL",
                        confidence="high",
                        tags=["kill_alert", "clear", bot_name],
                    )
                    alert_paths.append(p)
                    alerts_summary.append(f"{bot_name}: CLEAR")
                    warn_state.pop(bot_name, None)
                continue

            # Breaches var
            if not first_warn_at and warn_first:
                # İlk WARN
                body = self._build_alert_body(
                    bot_name, "WARN",
                    breaches=breaches,
                    cum_loss_7d_pct=cum_loss_7d_pct,
                    cum_loss_14d_pct=cum_loss_14d_pct,
                    dd30=dd30,
                    consec=consec,
                    recommendation=(
                        f"WARN — threshold breach detected. "
                        f"Re-evaluating in {warn_hold_hours}h. "
                        f"If still breached, PAUSE recommendation will be issued."
                    ),
                )
                p = self.write_protocol_doc(
                    doc_type="kill_criteria_alert",
                    body=body,
                    slug=f"warn-{bot_name}-{now.strftime('%Y%m%dT%H%M%S')}",
                    target_dir=self._reports_root(),
                    status="PROPOSED",
                    confidence="high",
                    requested_review_from=["ceo", "risk_officer"],
                    tags=["kill_alert", "warn_first", bot_name],
                )
                alert_paths.append(p)
                alerts_summary.append(f"{bot_name}: WARN ({len(breaches)} breach(es))")
                warn_state[bot_name] = {
                    "first_warn_at": now.isoformat(),
                    "breaches": breaches,
                }
            else:
                # WARN state var — hold süresi doldu mu?
                first_dt = self._parse_iso(first_warn_at) if first_warn_at else now
                elapsed_h = (now - first_dt).total_seconds() / 3600.0
                if elapsed_h >= warn_hold_hours:
                    body = self._build_alert_body(
                        bot_name, "PAUSE",
                        breaches=breaches,
                        cum_loss_7d_pct=cum_loss_7d_pct,
                        cum_loss_14d_pct=cum_loss_14d_pct,
                        dd30=dd30,
                        consec=consec,
                        recommendation=(
                            f"PAUSE RECOMMENDATION — threshold still breached after "
                            f"{elapsed_h:.1f}h hold (first WARN: {first_warn_at}). "
                            f"Recommend PAUSE for 48h; investigate slippage + regime. "
                            f"Bot Monitor does NOT pause autonomously. "
                            f"Principal must manually stop the daemon."
                        ),
                    )
                    p = self.write_protocol_doc(
                        doc_type="kill_criteria_alert",
                        body=body,
                        slug=f"pause-{bot_name}-{now.strftime('%Y%m%dT%H%M%S')}",
                        target_dir=self._reports_root(),
                        status="PROPOSED",
                        confidence="high",
                        requested_review_from=["ceo", "risk_officer"],
                        tags=["kill_alert", "pause_recommendation", bot_name],
                    )
                    alert_paths.append(p)
                    alerts_summary.append(f"{bot_name}: PAUSE recommended")
                    # State'i koru — manual clear edilene kadar tekrar PAUSE çıkmasın
                    warn_state[bot_name]["last_pause_rec_at"] = now.isoformat()
                else:
                    alerts_summary.append(
                        f"{bot_name}: WARN held ({elapsed_h:.1f}h / {warn_hold_hours}h)"
                    )

        self._save_warn_state(warn_state)

        # Tek kill-alerts.md indeks dosyası
        if alerts_summary:
            self._append_alerts_index(alerts_summary, now, alert_paths)
        else:
            logger.info("bot_monitor.kill_eval_no_breach")

        return alert_paths[-1] if alert_paths else None

    @staticmethod
    def _parse_iso(s: str) -> datetime:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    def _build_alert_body(
        self,
        bot_name: str,
        severity: str,
        *,
        breaches: list[str],
        cum_loss_7d_pct: float,
        cum_loss_14d_pct: float,
        dd30: float,
        consec: int,
        recommendation: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        # Source query hash for reproducibility
        h = hashlib.sha256(
            f"{bot_name}|{cum_loss_7d_pct}|{cum_loss_14d_pct}|{dd30}|{consec}|{now.isoformat()}".encode()
        ).hexdigest()[:12]
        lines = [
            f"# Kill Criteria Alert — {bot_name} — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Severity: {severity}",
            "",
            "## Metrics",
            f"- cum_loss_7d_pct: %{cum_loss_7d_pct*100:.2f}",
            f"- cum_loss_14d_pct: %{cum_loss_14d_pct*100:.2f}",
            f"- max_drawdown_30d: %{dd30*100:.2f}",
            f"- consecutive_losses: {consec}",
            "",
            "## Breaches",
        ]
        if breaches:
            for b in breaches:
                lines.append(f"- {b}")
        else:
            lines.append("- (none — thresholds cleared)")
        lines += [
            "",
            "## Recommendation",
            recommendation,
            "",
            "## Provenance",
            f"- Query hash: {h}",
            f"- Run TS: {now.isoformat()}",
            "",
            "## Hard Limit Reminder",
            "Bot Monitor does NOT pause bots autonomously. This is a recommendation",
            "for CEO + Risk Officer review and Principal manual decision.",
        ]
        return "\n".join(lines)

    def _append_alerts_index(
        self,
        alerts_summary: list[str],
        ts: datetime,
        paths: list[Path],
    ) -> None:
        idx = self._reports_root() / "kill-alerts.md"
        existing = idx.read_text(encoding="utf-8") if idx.exists() else "# Kill Alerts Log\n\n"
        line = f"\n## {ts.strftime('%Y-%m-%d %H:%M UTC')}\n"
        for s in alerts_summary:
            line += f"- {s}\n"
        for p in paths:
            line += f"  - doc: `{p}`\n"
        idx.write_text(existing + line, encoding="utf-8")
