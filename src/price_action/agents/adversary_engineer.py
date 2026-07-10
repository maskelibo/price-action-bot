"""Adversary Engineer Agent — Internal Red Team + Crash Specialist.

Faz 9: Renaissance "red team" + Tower crash specialist disiplini.
Aktif bot'lara günlük stress test uygular, haftalık Black Swan Readiness
raporu üretir, lab tournament terfi adaylarına / CEO deploy önerilerine
pre-deploy "kill probe" uygular (overfit / cherry-pick detection).

HARD LIMIT (`agents/adversary_engineer.md` §Hard Limits):
- AYNI risk_officer.py gibi — sadece dosya yazar, configs/*.yaml editlemez,
  canlı emir vermez. Tüm çıktı `reports/adversary/` altında critique/endorse doc'lar.

İlham: lab_scientist.py'ın weekly_tournament + tour gate pattern'i,
risk_officer.py'ın critique/endorse review pattern'i.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger

from .base import LLMAgentBase


class AdversaryEngineerAgent(LLMAgentBase):
    name: ClassVar[str] = "adversary_engineer"
    default_model: ClassVar[str] = ""  # boşsa settings.claude_model_default (Opus)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",  # config + bot YAML + replay pool okuma
        "write_report",  # critique/endorse + stress raporu yazma
        "backtest_run",  # replay engine çağrısı (orchestrator MCP)
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        p = self.settings.reports_dir / "adversary"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _configs_dir(self) -> Path:
        return self.settings.configs_dir

    def _load_periods_config(self) -> dict[str, Any]:
        """`configs/adversarial_periods.yaml` oku.

        Eksikse {} döner (hardcoded fallback YOK — config zorunlu).
        """
        try:
            import yaml

            cfg_path = self._configs_dir() / "adversarial_periods.yaml"
            if not cfg_path.exists():
                logger.warning("adversary.periods_config_missing", extra={"path": str(cfg_path)})
                return {}
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return data
        except Exception as exc:
            logger.warning("adversary.periods_config_fail", extra={"err": str(exc)[:200]})
            return {}

    def _load_bot_config(self, bot_id: str) -> dict[str, Any]:
        """`configs/risk_phoenix_scalp_<bot_id>.yaml` veya `configs/<bot_id>.yaml` oku."""
        try:
            import yaml

            candidates = [
                self._configs_dir() / f"risk_phoenix_scalp_{bot_id}.yaml",
                self._configs_dir() / f"risk_{bot_id}.yaml",
                self._configs_dir() / f"{bot_id}.yaml",
            ]
            for cfg_path in candidates:
                if cfg_path.exists():
                    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    data["_config_path"] = str(cfg_path)
                    return data
            logger.warning("adversary.bot_config_missing", extra={"bot": bot_id})
            return {}
        except Exception as exc:
            logger.warning(
                "adversary.bot_config_fail", extra={"bot": bot_id, "err": str(exc)[:200]}
            )
            return {}

    # ------------------------------------------------------------------
    # SOP-1: Daily stress test
    # ------------------------------------------------------------------

    def _replay_stress_period(
        self,
        strategy: str,
        period_dates: tuple[str, str],
        params: dict[str, Any],
        *,
        pool: Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Bir stress periodda strateji replay'i.

        Args:
            strategy: strategy id (ör. "phoenix_scalp_5m").
            period_dates: (start_iso, end_iso) — "2022-05-07", "2022-05-15".
            params: bot config (risk_pct, sl_pct, vs.) — yalnızca metrics
                rapor edilirken referans için saklanır.
            pool: opsiyonel replay pool subset. Production'da
                ``data/sec53_*.pkl`` benzeri pool subset filtrelenir;
                test'te dict listesi enjekte edilir.

        Returns:
            {"period": (start, end), "n_trades": int, "win_rate": float,
             "worst_dd_pct": float, "recovery_days": int|None,
             "final_return_pct": float, "concave": bool}
        """
        # Production: pool yoksa store.read() ile OHLCV çek + strategy run.
        # Bu helper paranoid bir minimal hesap yapar — tam backtest engine'i
        # `tools/backtest_run` üzerinden çağırmak orchestrator'ın işi; biz
        # statistical aggregator + verdict generator'ız.
        if pool is None or len(pool) == 0:
            return {
                "period": period_dates,
                "n_trades": 0,
                "win_rate": math.nan,
                "worst_dd_pct": math.nan,
                "recovery_days": None,
                "final_return_pct": math.nan,
                "concave": False,
                "status": "no_pool_data",
            }

        # Pool: list of trade dicts with keys: ts (iso str), pnl_pct (float).
        start_iso, end_iso = period_dates
        try:
            start_dt = datetime.fromisoformat(start_iso).replace(tzinfo=UTC)
            end_dt = datetime.fromisoformat(end_iso).replace(tzinfo=UTC)
        except ValueError:
            start_dt = end_dt = datetime.now(UTC)

        in_window: list[dict[str, Any]] = []
        for tr in pool:
            ts_raw = tr.get("ts") or tr.get("exit_ts") or tr.get("entry_ts")
            if not ts_raw:
                continue
            try:
                if isinstance(ts_raw, datetime):
                    ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
                else:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    if not ts.tzinfo:
                        ts = ts.replace(tzinfo=UTC)
            except ValueError:
                continue
            if start_dt <= ts <= end_dt:
                in_window.append(tr)

        n = len(in_window)
        if n == 0:
            return {
                "period": period_dates,
                "n_trades": 0,
                "win_rate": math.nan,
                "worst_dd_pct": math.nan,
                "recovery_days": None,
                "final_return_pct": math.nan,
                "concave": False,
                "status": "no_trades_in_window",
            }

        # Equity curve hesabı (additive % — compound overflow paranoyası, V14 lesson)
        # FIX 2026-05-28 (Faz 14.27 C8): Liquidation modeli eklendi.
        # Önceki bug: equity -%100 altına düşebiliyordu (LUNA test -%147 raporu →
        # impossible without leverage cap). Şimdi: -100% floor + liquidation flag.
        # Stress test'in pratik anlamı için: -%100'e ulaşırsa testi DUR + liquidated=True.
        LIQUIDATION_FLOOR = -100.0  # %100 sermaye kaybı = total liquidation
        pnls = [float(tr.get("pnl_pct", 0.0)) for tr in in_window]
        equity = [0.0]
        liquidated = False
        liquidation_idx: int | None = None
        for i, p in enumerate(pnls):
            new_eq = equity[-1] + p
            if new_eq <= LIQUIDATION_FLOOR:
                # Liquidation — sermayeyi sıfırla, trade'leri bitir
                equity.append(LIQUIDATION_FLOOR)
                liquidated = True
                liquidation_idx = i + 1  # equity index (entry 0 + i+1 trade)
                break
            equity.append(new_eq)

        peak = equity[0]
        worst_dd = 0.0
        worst_idx = 0
        for i, eq in enumerate(equity):
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > worst_dd:
                worst_dd = dd
                worst_idx = i

        # Recovery: worst_idx'ten sonra peak'i geri alana kadar trade sayısı.
        # gün cinsinden tahmin: trade arası ortalama süre.
        recovery_days: int | None = None
        if worst_idx < len(equity) - 1 and worst_dd > 0:
            target = peak
            recovered_at = None
            for j in range(worst_idx + 1, len(equity)):
                if equity[j] >= target:
                    recovered_at = j
                    break
            if recovered_at is not None and recovered_at > 0:
                # in_window[recovered_at-1] sona kadar olan trade
                if recovered_at - 1 < len(in_window):
                    total_span = (end_dt - start_dt).days or 1
                    recovery_days = max(
                        1, int(round((recovered_at - worst_idx) / max(1, n) * total_span))
                    )

        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n
        final_ret = equity[-1]

        # Concave check: equity curve son yarısı ilk yarısından daha kötü mü?
        mid = len(equity) // 2
        first_half_delta = equity[mid] - equity[0]
        second_half_delta = equity[-1] - equity[mid]
        concave = second_half_delta < first_half_delta and second_half_delta < 0

        return {
            "period": period_dates,
            "n_trades": n,
            "win_rate": round(wr, 4),
            "worst_dd_pct": round(worst_dd, 4),
            "recovery_days": recovery_days,
            "final_return_pct": round(final_ret, 4),
            "concave": concave,
            # FIX 2026-05-28 (Faz 14.27 C8): liquidation reporting
            "liquidated": liquidated,
            "liquidation_at_trade": liquidation_idx,
            "status": "liquidated" if liquidated else "ok",
        }

    async def daily_stress_test(
        self,
        bot_id: str,
        *,
        pool: Sequence[dict[str, Any]] | None = None,
    ) -> Path | None:
        """Bot için günlük stress test — 5 adversarial period'da replay.

        Args:
            bot_id: ör. "5m_p1c", "15m_widestop_vsa2".
            pool: opsiyonel replay pool (test'te enjekte; production'da None →
                gerçek pool yüklenir orchestrator tarafından).

        Returns:
            Stress test doc path (`reports/adversary/stress-YYYY-MM-DD-<bot>.md`)
            veya None (config yoksa).
        """
        cfg = self._load_periods_config()
        bot_cfg = self._load_bot_config(bot_id)
        periods = cfg.get("stress_periods", {})
        thresholds = cfg.get("adversarial_thresholds", {})

        if not periods:
            logger.warning("adversary.no_periods_loaded", extra={"bot": bot_id})
            return None

        results: list[dict[str, Any]] = []
        for pid, pdata in periods.items():
            res = self._replay_stress_period(
                strategy=f"phoenix_scalp_{bot_id}",
                period_dates=(pdata.get("start", ""), pdata.get("end", "")),
                params=bot_cfg,
                pool=pool,
            )
            res["period_id"] = pid
            res["period_name"] = pdata.get("name", pid)
            res["severity"] = pdata.get("severity", "unknown")
            res["passes_dd_gate"] = (
                not math.isnan(res.get("worst_dd_pct", math.nan))
                # FIX 2026-07-07 (denetim HIGH-2): birim uyumsuzluğu ~100× —
                # worst_dd_pct YÜZDE-PUAN (5.0 = %5), eşik ORAN (0.20 = %20).
                # Eski kıyas %0.2 gerçek DD'de fail edip kronik sahte CRIT üretiyordu.
                and res["worst_dd_pct"]
                <= thresholds.get("max_drawdown_pct_per_period", 0.20) * 100.0
                # FIX 2026-05-28 (Faz 14.27 C8): liquidated period = otomatik FAIL
                and not res.get("liquidated", False)
            )
            res["passes_recovery_gate"] = res.get("recovery_days") is None or res[
                "recovery_days"
            ] <= thresholds.get("min_recovery_days_acceptable", 30)
            results.append(res)

        n_pass = sum(1 for r in results if r["passes_dd_gate"] and r["passes_recovery_gate"])
        n_total = len(results)
        verdict_label = (
            "PASS" if n_pass == n_total else ("CRIT" if n_pass < n_total // 2 else "MED")
        )

        # LLM verdict üret
        prompt = (
            "Sen Adversary Engineer'sın. Aşağıdaki stress test sonuçlarına bakarak "
            "3-5 paragraf 'red team verdict' yaz. Tarz: acımasız, nümerik, kanlı tarihsel "
            "kaskad referansı (LUNA 2022-05, FTX 2022-11, Flash Crash 2010 vb). 'Bu sefer "
            "farklı' deme. Pozitif görüş üretme — şüphen varsa yaz.\n\n"
            f"BOT: {bot_id}\n"
            f"CONFIG PATH: {bot_cfg.get('_config_path', '(missing)')}\n"
            f"PASS COUNT: {n_pass}/{n_total}\n"
            f"VERDICT LABEL: {verdict_label}\n\n"
            f"PERIOD RESULTS:\n{results}\n\n"
            f"THRESHOLDS:\n{thresholds}\n\n"
            "Çıktı 5 alanlı critique formatı: ## Claim ## Disagreement ## Evidence "
            "## Alternative ## What would change my mind"
        )
        commentary = await self.run(prompt)

        ts_iso = datetime.now(UTC).strftime("%Y-%m-%d")
        body = (
            f"# Stress Test — {bot_id} — {ts_iso}\n\n"
            f"## Setup\n"
            f"- Bot: {bot_id}\n"
            f"- Config: {bot_cfg.get('_config_path', '(not found)')}\n"
            f"- Periods tested: {n_total}\n"
            f"- Verdict label: **{verdict_label}** ({n_pass}/{n_total} pass)\n\n"
            f"## Per-Period Results\n"
            f"| Period | Sev | n | WR | Worst DD% | Recov d | Final% | Concave | DD Gate | Recov Gate |\n"
            f"|---|---|---|---|---|---|---|---|---|---|\n"
            + "\n".join(
                f"| {r['period_id']} | {r['severity']} | {r['n_trades']} | "
                f"{r['win_rate']} | {r['worst_dd_pct']} | "
                f"{r['recovery_days']} | {r['final_return_pct']} | "
                f"{r['concave']} | {r['passes_dd_gate']} | {r['passes_recovery_gate']} |"
                for r in results
            )
            + "\n\n"
            f"## Thresholds Applied\n```yaml\n{thresholds}\n```\n\n"
            f"## Red Team Verdict\n{commentary}\n"
        )

        doc_path = self.write_protocol_doc(
            doc_type="adversarial_test",
            body=body,
            slug=f"stress-{ts_iso}-{bot_id}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="high" if verdict_label != "PASS" else "med",
            requested_review_from=["ceo", "risk_officer"],
            tags=["adversarial", "stress_test", bot_id, verdict_label.lower()],
        )
        logger.info(
            "adversary.daily_stress_done",
            extra={
                "bot": bot_id,
                "verdict": verdict_label,
                "n_pass": n_pass,
                "n_total": n_total,
                "doc": str(doc_path),
            },
        )
        return doc_path

    # ------------------------------------------------------------------
    # SOP-2: Weekly red team report
    # ------------------------------------------------------------------

    def _compute_readiness_score(
        self,
        period_results: list[dict[str, Any]],
        *,
        kill_probe_passed: bool = False,
        scoring: dict[str, Any] | None = None,
    ) -> int:
        """Black Swan Readiness Score (0-100)."""
        scoring = scoring or {}
        per_period = float(scoring.get("per_period_pass_points", 20))
        fast_rec_bonus = float(scoring.get("fast_recovery_bonus", 5))
        baseline = float(scoring.get("kill_probe_baseline", 10))
        concave_pen = float(scoring.get("concave_curve_penalty", -10))

        score = 0.0
        if kill_probe_passed:
            score += baseline
        for r in period_results:
            if r.get("passes_dd_gate") and r.get("passes_recovery_gate"):
                score += per_period
            if r.get("recovery_days") is not None and r["recovery_days"] <= 30:
                score += fast_rec_bonus
            if r.get("concave"):
                score += concave_pen
        return max(0, min(100, int(round(score))))

    async def weekly_red_team_report(
        self,
        bot_ids: Sequence[str] | None = None,
        *,
        pool_by_bot: dict[str, Sequence[dict[str, Any]]] | None = None,
    ) -> Path:
        """Aktif bot'lar için haftalık red team raporu + readiness skoru."""
        cfg = self._load_periods_config()
        scoring = cfg.get("readiness_scoring", {})
        crit_thr = float(scoring.get("critical_threshold", 60))
        med_thr = float(scoring.get("medium_threshold", 80))

        bot_ids = list(bot_ids or ["5m_p1c", "15m_widestop_vsa2"])
        pool_by_bot = pool_by_bot or {}

        per_bot: list[dict[str, Any]] = []
        for bot in bot_ids:
            pool = pool_by_bot.get(bot)
            bot_cfg = self._load_bot_config(bot)
            periods = cfg.get("stress_periods", {})
            results: list[dict[str, Any]] = []
            for pid, pdata in periods.items():
                r = self._replay_stress_period(
                    strategy=f"phoenix_scalp_{bot}",
                    period_dates=(pdata.get("start", ""), pdata.get("end", "")),
                    params=bot_cfg,
                    pool=pool,
                )
                r["period_id"] = pid
                r["passes_dd_gate"] = not math.isnan(r.get("worst_dd_pct", math.nan)) and r[
                    "worst_dd_pct"
                ] <= cfg.get("adversarial_thresholds", {}).get("max_drawdown_pct_per_period", 0.20)
                r["passes_recovery_gate"] = r.get("recovery_days") is None or r[
                    "recovery_days"
                ] <= cfg.get("adversarial_thresholds", {}).get("min_recovery_days_acceptable", 30)
                results.append(r)
            score = self._compute_readiness_score(results, scoring=scoring)
            label = "CRIT" if score < crit_thr else ("MED" if score < med_thr else "OK")
            per_bot.append(
                {
                    "bot": bot,
                    "readiness": score,
                    "label": label,
                    "results": results,
                }
            )

        prompt = (
            "Sen Adversary Engineer'sın. Aşağıdaki tüm aktif bot'lar için "
            "haftalık 'red team report' yaz. Her bot için Readiness Score "
            "(0-100), gerekçesi, hangi period en zayıf, hangi tarihsel kaskad "
            "tekrarı varsa hangi bot nasıl çöker.\n\n"
            "CRIT (< 60) bot'lar için **acil critique gerekçesi**, MED (60-80) "
            "için CEO uyarısı, OK (> 80) için sessiz onay.\n\n"
            f"PER-BOT DATA:\n{per_bot}\n"
        )
        commentary = await self.run(prompt)

        iso = datetime.now(UTC).isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"

        body = (
            f"# Weekly Red Team Report — {week_label}\n\n"
            f"## Bot Summary\n"
            f"| Bot | Readiness | Label |\n"
            f"|---|---|---|\n"
            + "\n".join(f"| {b['bot']} | {b['readiness']} | **{b['label']}** |" for b in per_bot)
            + "\n\n"
            "## Per-Bot Details\n"
            + "\n\n".join(
                f"### {b['bot']} — readiness {b['readiness']} ({b['label']})\n"
                + "\n".join(
                    f"- {r['period_id']}: DD={r['worst_dd_pct']}, "
                    f"recov={r['recovery_days']}d, concave={r['concave']}, "
                    f"n={r['n_trades']}, dd_gate={r['passes_dd_gate']}, "
                    f"recov_gate={r['passes_recovery_gate']}"
                    for r in b["results"]
                )
                for b in per_bot
            )
            + "\n\n"
            f"## Verdict\n{commentary}\n"
        )

        # Risk Officer'a critique olarak gönder
        doc_path = self.write_protocol_doc(
            doc_type="red_team_weekly",
            body=body,
            slug=f"weekly-{week_label}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="high" if any(b["label"] == "CRIT" for b in per_bot) else "med",
            requested_review_from=["risk_officer", "ceo"],
            tags=["adversarial", "weekly", week_label],
        )
        logger.info(
            "adversary.weekly_done",
            extra={
                "week": week_label,
                "n_bots": len(per_bot),
                "n_crit": sum(1 for b in per_bot if b["label"] == "CRIT"),
                "doc": str(doc_path),
            },
        )
        return doc_path

    # ------------------------------------------------------------------
    # SOP-3: Pre-deploy kill probe
    # ------------------------------------------------------------------

    _NUMERIC_RE = re.compile(r"[-+]?\d*\.?\d+")

    def _extract_metrics_from_doc(self, body: str) -> dict[str, float]:
        """Aday doc body'sinden IS/OOS Sharpe, n_trades, param extremeness çek.

        Defansif regex parser — eksik alan math.nan döner; LLM evaluate edebilir
        ama kill probe deterministic kabul/red veremez.
        """
        out: dict[str, float] = {
            "is_sharpe": math.nan,
            "oos_sharpe": math.nan,
            "n_unique_trades": math.nan,
            "param_extremeness_pct": math.nan,
            "n_regimes_passed": math.nan,
            "n_params": math.nan,
        }
        body_l = body.lower()

        # IS Sharpe
        m = re.search(r"(?:in.?sample|is)\s*sharpe[:\s=]+([\-+]?\d+\.?\d*)", body_l)
        if m:
            try:
                out["is_sharpe"] = float(m.group(1))
            except ValueError:
                pass

        # OOS Sharpe
        m = re.search(r"(?:out.?of.?sample|oos)\s*sharpe[:\s=]+([\-+]?\d+\.?\d*)", body_l)
        if m:
            try:
                out["oos_sharpe"] = float(m.group(1))
            except ValueError:
                pass

        # Unique trades
        m = re.search(r"(?:unique\s+trades|n_trades|n_unique_trades)[:\s=]+(\d+)", body_l)
        if m:
            try:
                out["n_unique_trades"] = float(m.group(1))
            except ValueError:
                pass

        # Param extremeness
        m = re.search(r"param[_\s]*extremeness[_\s]*(?:pct)?[:\s=]+([\-+]?\d+\.?\d*)", body_l)
        if m:
            try:
                out["param_extremeness_pct"] = float(m.group(1))
            except ValueError:
                pass

        # Regimes passed
        m = re.search(r"regime[s]?[_\s]*passed?[:\s=]+(\d+)", body_l)
        if m:
            try:
                out["n_regimes_passed"] = float(m.group(1))
            except ValueError:
                pass

        # Param count
        m = re.search(r"(?:n_params|param[s]?\s*count)[:\s=]+(\d+)", body_l)
        if m:
            try:
                out["n_params"] = float(m.group(1))
            except ValueError:
                pass

        return out

    def kill_probe(
        self,
        metrics: dict[str, float] | None = None,
        *,
        candidate_doc_body: str | None = None,
    ) -> dict[str, Any]:
        """Pre-deploy kill probe — overfit / cherry-pick / sample-size detection.

        Eğer ``metrics`` verilmezse ``candidate_doc_body``'den regex ile çıkarır.
        Herhangi bir gate FAIL → overall fail.

        Returns:
            {"passed": bool, "fails": [reason, ...], "checks": {gate: bool|None}}
        """
        cfg = self._load_periods_config()
        gates = cfg.get("pre_deploy_kill_probes", {})

        if metrics is None and candidate_doc_body is not None:
            metrics = self._extract_metrics_from_doc(candidate_doc_body)
        metrics = metrics or {}

        fails: list[str] = []
        checks: dict[str, Any] = {}

        # 1. IS/OOS Sharpe spread
        is_s = float(metrics.get("is_sharpe", math.nan))
        oos_s = float(metrics.get("oos_sharpe", math.nan))
        max_spread = float(gates.get("in_oos_sharpe_spread_max_pct", 0.30))
        if not (math.isnan(is_s) or math.isnan(oos_s)) and abs(is_s) > 1e-9:
            spread = (is_s - oos_s) / abs(is_s)
            ok = spread <= max_spread
            checks["in_oos_sharpe_spread"] = ok
            if not ok:
                fails.append(
                    f"overfit_is_oos_spread {spread:.3f} > {max_spread} " f"(IS={is_s} OOS={oos_s})"
                )
        else:
            checks["in_oos_sharpe_spread"] = None  # unknown

        # 2. Min unique trades
        n_tr = float(metrics.get("n_unique_trades", math.nan))
        min_tr = float(gates.get("min_unique_trades", 100))
        if not math.isnan(n_tr):
            ok = n_tr >= min_tr
            checks["min_unique_trades"] = ok
            if not ok:
                fails.append(f"sample_too_small n={int(n_tr)} < {int(min_tr)}")
        else:
            checks["min_unique_trades"] = None

        # 3. Param extremeness — value > max_extremeness_pct → grid ucunda
        ext = float(metrics.get("param_extremeness_pct", math.nan))
        max_ext = float(gates.get("max_param_extremeness_pct", 0.20))
        if not math.isnan(ext):
            ok = ext <= max_ext
            checks["param_extremeness"] = ok
            if not ok:
                fails.append(f"cherry_pick_grid_edge ext={ext:.3f} > {max_ext}")
        else:
            checks["param_extremeness"] = None

        # 4. Regime coverage
        n_reg = float(metrics.get("n_regimes_passed", math.nan))
        min_reg = float(gates.get("min_regime_pass_count", 2))
        if not math.isnan(n_reg):
            ok = n_reg >= min_reg
            checks["regime_coverage"] = ok
            if not ok:
                fails.append(f"insufficient_regime_coverage {int(n_reg)} < {int(min_reg)}")
        else:
            checks["regime_coverage"] = None

        # 5. k/n parameter overfitting rule
        np_count = float(metrics.get("n_params", math.nan))
        max_pct = float(gates.get("max_param_count_per_trade", 0.10))
        if not (math.isnan(np_count) or math.isnan(n_tr)) and n_tr > 0:
            ratio = np_count / n_tr
            ok = ratio <= max_pct
            checks["param_per_trade_ratio"] = ok
            if not ok:
                fails.append(
                    f"k_over_n_overfit {ratio:.3f} > {max_pct} "
                    f"(params={int(np_count)} trades={int(n_tr)})"
                )
        else:
            checks["param_per_trade_ratio"] = None

        # FIX 2026-07-07 (denetim HIGH-3): fail-open kapatıldı — hiçbir metrik
        # parse edilemediyse (checks tümü None) eski kod passed=True verip
        # kırmızı takımın OKUYAMADIĞI dokümanı ENDORSE etmesine yol açıyordu.
        if not any(v is not None for v in checks.values()):
            fails.append("no_metrics_parsed — kill-probe fail-closed (doc formatı okunamadı)")

        return {
            "passed": len(fails) == 0,
            "fails": fails,
            "checks": checks,
            "metrics": metrics,
        }

    async def evaluate_promotion_candidate(self, candidate_doc: Path | str) -> Path | None:
        """Lab tournament terfi adayı veya CEO deploy önerisini değerlendir.

        Akış:
            1. Doc'u oku, body'den metrics çek.
            2. Kill probe çalıştır.
            3. PASS → endorse doc (sadece "kill probe geçti", deploy izni DEĞİL).
               FAIL → critique doc, status BLOCKED, `requested_review_from: [ceo]`.

        Returns:
            Üretilen critique/endorse doc path.
        """
        path = Path(candidate_doc)
        if not path.exists():
            logger.warning("adversary.candidate_missing", extra={"path": str(path)})
            return None

        body = path.read_text(encoding="utf-8")
        original_id = path.stem
        probe = self.kill_probe(candidate_doc_body=body)

        is_fail = not probe["passed"]
        doc_type = "critique" if is_fail else "endorse"

        prompt = (
            "Sen Adversary Engineer'sın. Lab tournament terfi adayı (ya da CEO "
            "deploy önerisi) için kill probe sonucu aşağıda. "
            f"{'FAIL' if is_fail else 'PASS'} verdict'i için 5 alanlı "
            "(Claim/Disagreement|Why I Endorse/Evidence/Alternative/What would change "
            "my mind) format yaz.\n\n"
            f"ORIGINAL DOC ID: {original_id}\n"
            f"PROBE RESULT: {probe}\n\n"
            "PASS durumunda BİLE 'sadece kill probe geçti, deploy için Risk Officer + "
            "CEO + Principal onayı şart' uyarısını ekle. Kanlı tarihsel kaskad "
            "referansı (LUNA, FTX, Flash Crash 2010) ekle."
        )
        commentary = await self.run(prompt)

        body_out = (
            f"# Kill Probe — {original_id}\n\n"
            f"## Probe Result\n"
            f"- Passed: **{probe['passed']}**\n"
            f"- Fails: {probe['fails']}\n"
            f"- Checks: {probe['checks']}\n"
            f"- Metrics extracted: {probe['metrics']}\n\n"
            f"## Verdict\n{commentary}\n"
        )

        doc_path = self.write_protocol_doc(
            doc_type=doc_type,
            body=body_out,
            slug=f"probe-{original_id[:50]}",
            target_dir=self._reports_dir(),
            status="BLOCKED" if is_fail else "PROPOSED",
            confidence="high",
            depends_on=[original_id],
            requested_review_from=["ceo"] if is_fail else ["ceo", "risk_officer"],
            tags=[doc_type, "kill_probe", "adversarial", "fail" if is_fail else "pass"],
        )
        logger.info(
            "adversary.candidate_evaluated",
            extra={
                "original": original_id,
                "passed": probe["passed"],
                "n_fails": len(probe["fails"]),
                "doc": str(doc_path),
            },
        )
        return doc_path

    # ------------------------------------------------------------------
    # Faz 14.3 — Quiet Failure Hunter (proactive bug detection)
    # ------------------------------------------------------------------

    async def quiet_failure_audit(self) -> Path | None:
        """Sistemde sessizce başarısız olan komponentleri ara.

        Promise/Reality detector eksiklikleri yakaladığı için bu metod
        DAHA DERIN sorular sorar:
        1. Hangi config dosyası son commit'ten farklı (drift)?
        2. Hangi agent dry-run dışında hiç çağrı yapmadı?
        3. Hangi `promised file` hiç oluşturulmamış (config'te referans
           var ama disk'te yok)?
        4. Hangi cron job 7 gün boyunca 0 success raporladı?
        5. Hangi DuckDB tablo 30 gün+ değişmedi (atrofi)?

        Çıktı: reports/adversary/quiet_audit-YYYY-MM-DD.md + push_critical
        eğer CRIT bulgu varsa.
        """
        import subprocess
        from datetime import datetime, timedelta
        from pathlib import Path

        now = datetime.now(UTC)
        findings: list[dict[str, Any]] = []
        repo = Path("/Users/peyman/price-action-bot")

        # ── Kontrol 1: Config drift (git status) ─────────────────────
        try:
            git_status = subprocess.run(
                ["git", "diff", "--name-only", "HEAD", "--", "configs/"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if git_status.returncode == 0 and git_status.stdout.strip():
                changed = git_status.stdout.strip().splitlines()
                findings.append(
                    {
                        "severity": "warn",
                        "kind": "config_drift",
                        "summary": f"{len(changed)} config dosyası git HEAD'den sapmış",
                        "details": changed[:10],
                    }
                )
        except Exception as exc:
            logger.warning("adversary.git_check_fail", extra={"err": str(exc)[:200]})

        # ── Kontrol 2: Agent dry-run dışı çağrı yok ──────────────────
        # data/llm_calls.jsonl'i tara — son 7g hangi agent hiç çağrı yapmamış
        try:
            import json as _json

            audit = repo / "data" / "llm_calls.jsonl"
            if audit.exists():
                cutoff = now - timedelta(days=7)
                agent_counts: dict[str, int] = {}
                with audit.open("r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = _json.loads(line)
                            ts = datetime.fromisoformat(rec["ts"])
                            if ts < cutoff:
                                continue
                            agent_counts[rec["agent"]] = agent_counts.get(rec["agent"], 0) + 1
                        except Exception:
                            continue
                expected_agents = [
                    "ceo",
                    "researcher",
                    "lab_scientist",
                    "analyst",
                    "risk_officer",
                    "bot_monitor",
                    "adversary_engineer",
                    "strategy_curator",
                ]
                missing = [a for a in expected_agents if agent_counts.get(a, 0) == 0]
                if missing:
                    findings.append(
                        {
                            "severity": "crit",
                            "kind": "silent_agent",
                            "summary": f"{len(missing)} agent son 7g HİÇ LLM çağrısı yapmadı",
                            "details": missing,
                        }
                    )
        except Exception as exc:
            logger.warning("adversary.silent_check_fail", extra={"err": str(exc)[:200]})

        # ── Kontrol 3: Promised file hiç oluşmamış ───────────────────
        try:
            promises_yaml = repo / "configs" / "promises.yaml"
            if promises_yaml.exists():
                import yaml as _yaml

                promises = _yaml.safe_load(promises_yaml.read_text(encoding="utf-8")) or {}
                never_written: list[str] = []
                for comp_name, comp_cfg in (promises.get("components") or {}).items():
                    for check in comp_cfg.get("checks") or []:
                        if check.get("kind") != "file_pattern":
                            continue
                        pattern = check.get("pattern", "")
                        if not pattern:
                            continue
                        matches = list(repo.glob(pattern))
                        if not matches:
                            never_written.append(f"{comp_name}: {pattern}")
                if never_written:
                    findings.append(
                        {
                            "severity": "warn",
                            "kind": "never_written",
                            "summary": f"{len(never_written)} promised file pattern hiç oluşmamış",
                            "details": never_written[:10],
                        }
                    )
        except Exception as exc:
            logger.warning("adversary.promises_check_fail", extra={"err": str(exc)[:200]})

        # ── Kontrol 4: Eski log dosyaları (atrofi) ────────────────────
        try:
            cutoff_old = now - timedelta(days=7)
            stale_dirs = []
            for sub in ["param_sweep", "tf_exploration", "market_scout"]:
                d = repo / "reports" / sub
                if not d.exists():
                    continue
                newest = max(
                    (
                        datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
                        for f in d.rglob("*")
                        if f.is_file()
                    ),
                    default=None,
                )
                if newest is None or newest < cutoff_old:
                    stale_dirs.append(f"reports/{sub}/ (newest: {newest})")
            if stale_dirs:
                findings.append(
                    {
                        "severity": "warn",
                        "kind": "atrophied_output",
                        "summary": f"{len(stale_dirs)} report dizini 7g+ yazılmıyor",
                        "details": stale_dirs,
                    }
                )
        except Exception as exc:
            logger.warning("adversary.atrophy_check_fail", extra={"err": str(exc)[:200]})

        # ── Rapor üret ───────────────────────────────────────────────
        lines = [
            f"# Quiet Failure Audit — {now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            f"**Toplam bulgu:** {len(findings)} ({sum(1 for f in findings if f['severity']=='crit')} CRIT)",
            "",
        ]
        if not findings:
            lines.append("✅ Sessiz başarısızlık tespit edilmedi. Sistem alarmları doğrulanmış.")
        else:
            for f in findings:
                icon = "🚨" if f["severity"] == "crit" else "⚠️"
                lines.append(f"## {icon} [{f['severity'].upper()}] {f['kind']}")
                lines.append(f"- {f['summary']}")
                for d in f.get("details", []):
                    lines.append(f"  - `{d}`")
                lines.append("")

        body = "\n".join(lines)
        path = self.write_protocol_doc(
            doc_type="quiet_failure_audit",
            body=body,
            slug=f"quiet-audit-{now.strftime('%Y-%m-%d-%H')}",
            target_dir=self._reports_dir(),
            status="FINAL",
            confidence="high",
            requested_review_from=["ceo"],
            tags=["adversary", "quiet_audit", "proactive"],
        )

        # CRIT bulgu varsa Telegram
        crits = [f for f in findings if f["severity"] == "crit"]
        if crits:
            try:
                from price_action.orchestrator.notifications import push_critical

                msg = f"QUIET AUDIT — {len(crits)} CRIT bulgu:\n" + "\n".join(
                    f"- {c['summary']}" for c in crits
                )
                push_critical(msg, source="adversary_quiet_audit")
            except Exception:
                pass

        logger.info(
            "adversary.quiet_audit_done",
            extra={"n_findings": len(findings), "n_crit": len(crits), "path": str(path)},
        )
        return path
