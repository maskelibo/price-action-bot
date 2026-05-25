"""Lab Scientist Agent — Self-Improvement Lab.

Tournament, drift detection, RAG refresh, departman toplantısı.
İstatistik: ``scipy.stats``.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Sequence

from price_action.logging_config import logger
from price_action.rag import summarize_recent_additions
from price_action.settings import get_settings

from .base import LLMAgentBase


class LabScientistAgent(LLMAgentBase):
    name: ClassVar[str] = "lab_scientist"
    default_model: ClassVar[str] = ""
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "rag_ingest",
        "walk_forward_run",
        "stat_test",
        "read_file",
        "write_report",
        "agent_message",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        p = self.settings.reports_dir / "lab"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _import_scipy() -> Any:
        try:
            from scipy import stats  # type: ignore[import-not-found]

            return stats
        except Exception as exc:  # pragma: no cover
            logger.warning("lab.scipy_missing", extra={"err": str(exc)})
            return None

    # ------------------------------------------------------------------
    # İstatistiksel testler
    # ------------------------------------------------------------------

    def welch_ttest(
        self, a: Sequence[float], b: Sequence[float]
    ) -> dict[str, float]:
        """İki returns serisi arasında Welch's t-test."""
        stats = self._import_scipy()
        if stats is None or len(a) < 2 or len(b) < 2:
            return {"t": math.nan, "p": math.nan}
        result = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        return {"t": float(result.statistic), "p": float(result.pvalue)}

    def ks_test(
        self, a: Sequence[float], b: Sequence[float]
    ) -> dict[str, float]:
        """Kolmogorov-Smirnov dağılım eşitliği testi."""
        stats = self._import_scipy()
        if stats is None or not a or not b:
            return {"d": math.nan, "p": math.nan}
        result = stats.ks_2samp(a, b)
        return {"d": float(result.statistic), "p": float(result.pvalue)}

    def deflated_sharpe(
        self,
        sharpe: float,
        n_trials: int,
        n_obs: int,
        skew: float = 0.0,
        kurt: float = 3.0,
    ) -> dict[str, float]:
        """DSR (Deflated Sharpe Ratio) — Bailey & López de Prado.

        Çoklu test sayısına ve örnek istatistiklere göre düzeltilmiş p-value.
        """
        stats = self._import_scipy()
        if stats is None or n_obs < 30 or n_trials < 1:
            return {"dsr": math.nan, "p": math.nan}
        # Beklenen maksimum Sharpe (n_trials denemesi içinde)
        # E[max(Z)] ≈ (1 - γ) * Φ⁻¹(1 - 1/n) + γ * Φ⁻¹(1 - 1/(n*e))
        gamma = 0.5772156649  # Euler-Mascheroni
        try:
            inv1 = stats.norm.ppf(1 - 1.0 / max(n_trials, 2))
            inv2 = stats.norm.ppf(1 - 1.0 / (max(n_trials, 2) * math.e))
            sharpe0 = (1 - gamma) * inv1 + gamma * inv2
            # PSR (Probabilistic Sharpe Ratio) ile deflated p-value
            denom = math.sqrt(
                max(
                    1e-9,
                    1
                    - skew * sharpe
                    + ((kurt - 1) / 4.0) * sharpe**2,
                )
            )
            z = (sharpe - sharpe0) * math.sqrt(n_obs - 1) / denom
            p = 1.0 - float(stats.norm.cdf(z))
            return {"dsr": float(z), "p": p, "expected_max_sharpe": float(sharpe0)}
        except Exception as exc:
            logger.warning("lab.dsr_calc_fail", extra={"err": str(exc)})
            return {"dsr": math.nan, "p": math.nan}

    # ------------------------------------------------------------------
    # SOP-1: Tournament
    # ------------------------------------------------------------------

    def _collect_active_challengers(self, since_days: int = 7) -> list[dict[str, Any]]:
        """Faz 3.2: Researcher'in son N gündeki hypothesis dokümanlarını topla.

        `respond_to_drift()` ile üretilen drift_response hipotezleri dahil.
        Backtest sonucu olmadan tournament'a girmez — sadece "var" işareti.
        """
        from price_action.memory.store import MemoryStore

        store = MemoryStore()
        hyp_docs = store.list_recent_docs(
            agent="researcher",
            doc_type="hypothesis",
            since_days=since_days,
        )
        # Researcher hypotheses memory/researcher/hypotheses/ altında olabilir,
        # ya da reports/researcher/ altında (write_protocol_doc default).
        # Her ikisini de tara.
        from pathlib import Path as _P
        hyp_dir_memory = self.settings.memory_dir / "researcher" / "hypotheses"
        if hyp_dir_memory.exists():
            extra = sorted(hyp_dir_memory.glob("*.md"), reverse=True)[:20]
            hyp_docs = list(hyp_docs) + list(extra)

        # Map → challenger dict; backtest sonucu yoksa "pending"
        challengers: list[dict[str, Any]] = []
        for doc in hyp_docs[:10]:  # son 10 hipotez
            challengers.append({
                "id": doc.stem,
                "source_doc": str(doc),
                "oos_returns": [],
                "oos_sharpe": 0.0,
                "oos_maxdd": 0.0,
                "n_trials": 0,
                "status": "PENDING_BACKTEST",
            })
        logger.info("lab.auto_collected_challengers", extra={"n": len(challengers)})
        return challengers

    async def weekly_tournament(
        self,
        champion: dict[str, Any] | None = None,
        challengers: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Champion vs challenger karşılaştırması.

        Faz 3.2: ``challengers=None`` ise `_collect_active_challengers()` ile
        otomatik toplanır (son 7g Researcher hipotezleri).

        ``champion`` ve ``challengers``:
            {
              "id": "...",
              "oos_returns": [...],
              "oos_sharpe": 1.23,
              "oos_maxdd": 0.18,
              "n_trials": 80,
            }
        """
        # Faz 3.2: auto-collect
        if challengers is None:
            challengers = self._collect_active_challengers(since_days=7)
        if champion is None:
            champion = {
                "id": "noop_placeholder",
                "oos_returns": [],
                "oos_sharpe": 0.0,
                "oos_maxdd": 0.0,
                "n_trials": 0,
            }
        rows: list[dict[str, Any]] = []
        c_returns = list(champion.get("oos_returns", []) or [])
        c_sharpe = float(champion.get("oos_sharpe", 0))

        for ch in challengers:
            ch_returns = list(ch.get("oos_returns", []) or [])
            tt = self.welch_ttest(ch_returns, c_returns)
            dsr = self.deflated_sharpe(
                float(ch.get("oos_sharpe", 0)),
                int(ch.get("n_trials", 1)),
                len(ch_returns) or 30,
            )
            effect = (
                (float(ch.get("oos_sharpe", 0)) - c_sharpe) / max(abs(c_sharpe), 1e-9)
            )
            promote = (
                effect >= 0.15
                and dsr.get("p", 1.0) < 0.05
                and float(ch.get("oos_maxdd", 1)) <= float(champion.get("oos_maxdd", 1)) + 0.05
            )
            rows.append(
                {
                    "id": ch.get("id"),
                    "oos_sharpe": ch.get("oos_sharpe"),
                    "oos_maxdd": ch.get("oos_maxdd"),
                    "effect_vs_champion": round(effect, 4),
                    "welch_p": tt["p"],
                    "dsr_p": dsr.get("p"),
                    "decision": "promote_candidate" if promote else "reject",
                }
            )

        prompt = (
            "Tournament Report — sayısal sonuçlar verildi. CEO için tavsiye yaz "
            "(SOP-1 formatında). Conservative ol; effect size + DSR p < 0.05 "
            "olmadan terfi önerme.\n\n"
            f"CHAMPION: {champion.get('id')}\nROWS: {rows}"
        )
        commentary = await self.run(prompt)
        iso = datetime.now(timezone.utc).isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"

        body = (
            f"# Tournament Report — Week {week_label}\n\n"
            f"## Setup\n"
            f"- Champion: {champion.get('id', 'noop')}\n"
            f"- Challengers (n={len(challengers)}): {[ch.get('id') for ch in challengers]}\n"
            f"- Total trials: {sum(int(ch.get('n_trials', 0)) for ch in challengers)}\n\n"
            f"## Rows\n```json\n{rows}\n```\n\n"
            f"## Commentary\n{commentary}\n"
        )

        # Faz 3.3 — tournament otomatik risk officer review için yazılır
        report_path = self.write_protocol_doc(
            doc_type="tournament",
            body=body,
            slug=f"tournament-{week_label}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="high" if rows and any(r.get("decision") == "promote_candidate" for r in rows) else "med",
            depends_on=[ch.get("source_doc", "") for ch in challengers if ch.get("source_doc")],
            requested_review_from=["risk_officer", "ceo"],
            tags=["tournament", "weekly", week_label],
        )
        return report_path

    # ------------------------------------------------------------------
    # SOP-2: Drift detection
    # ------------------------------------------------------------------

    def drift_detect(
        self,
        live_returns: Sequence[float],
        backtest_returns: Sequence[float],
        *,
        alpha: float = 0.01,
        symbol: str | None = None,
        strategy: str | None = None,
        emit_doc: bool = True,
    ) -> dict[str, Any]:
        """KS + Welch + Levene; herhangi p < alpha → drift uyarısı.

        Faz 3.1: ``alert=True`` ve ``emit_doc=True`` ise protokol-uyumlu
        drift_alert doc yazılır (``requested_review_from=[researcher]``);
        bu Researcher'ı `respond_to_drift()` ile tetikler.
        """
        stats = self._import_scipy()
        result: dict[str, Any] = {"alert": False, "tests": {}}
        if stats is None or len(live_returns) < 5 or len(backtest_returns) < 5:
            result["tests"]["status"] = "insufficient_data"
            return result
        ks = self.ks_test(live_returns, backtest_returns)
        tt = self.welch_ttest(live_returns, backtest_returns)
        try:
            lev = stats.levene(live_returns, backtest_returns, center="median")
            lev_p = float(lev.pvalue)
        except Exception:
            lev_p = math.nan
        result["tests"] = {
            "ks_p": ks["p"],
            "welch_p": tt["p"],
            "levene_p": lev_p,
        }
        ps = [v for v in (ks["p"], tt["p"], lev_p) if not math.isnan(v)]
        if any(p < alpha for p in ps):
            result["alert"] = True

        # Faz 3.1 — drift_alert doc emit
        if result["alert"] and emit_doc:
            try:
                doc_path = self._emit_drift_alert_doc(
                    result=result,
                    live_returns=live_returns,
                    backtest_returns=backtest_returns,
                    symbol=symbol or "unknown",
                    strategy=strategy or "unknown",
                )
                result["doc_path"] = str(doc_path)
            except Exception as exc:
                logger.warning("lab.drift_doc_fail", extra={"err": str(exc)[:200]})

        return result

    def _emit_drift_alert_doc(
        self,
        *,
        result: dict[str, Any],
        live_returns: Sequence[float],
        backtest_returns: Sequence[float],
        symbol: str,
        strategy: str,
    ) -> Path:
        """drift_alert.md.tmpl format'ında doc yaz.

        Researcher'ı `requested_review_from=[researcher]` ile tetikler.
        """
        import numpy as np

        live_arr = np.asarray(live_returns, dtype=float)
        bt_arr = np.asarray(backtest_returns, dtype=float)
        live_mean = float(live_arr.mean()) if live_arr.size else 0.0
        bt_mean = float(bt_arr.mean()) if bt_arr.size else 0.0
        live_std = float(live_arr.std(ddof=1)) if live_arr.size > 1 else 0.0
        bt_std = float(bt_arr.std(ddof=1)) if bt_arr.size > 1 else 0.0
        pooled_std = math.sqrt((live_std**2 + bt_std**2) / 2.0) if (live_std + bt_std) > 0 else 1e-9
        cohens_d = (live_mean - bt_mean) / pooled_std

        tests = result.get("tests", {})
        ks_p = tests.get("ks_p", math.nan)
        welch_p = tests.get("welch_p", math.nan)
        levene_p = tests.get("levene_p", math.nan)

        body = (
            f"# Drift Alert — {strategy} on {symbol}\n\n"
            "## Detection\n"
            f"- Detected at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"- Test window: live n={len(live_returns)} vs backtest n={len(backtest_returns)}\n"
            f"- Strategy: {strategy}\n"
            f"- Symbol scope: {symbol}\n\n"
            "## Statistical Tests\n"
            "| Test | p-value | Threshold | Status |\n"
            "|---|---|---|---|\n"
            f"| Kolmogorov-Smirnov | {ks_p:.4f} | < 0.01 | "
            f"{'FAIL' if not math.isnan(ks_p) and ks_p < 0.01 else 'PASS'} |\n"
            f"| Welch's t-test (returns) | {welch_p:.4f} | < 0.01 | "
            f"{'FAIL' if not math.isnan(welch_p) and welch_p < 0.01 else 'PASS'} |\n"
            f"| Levene (variance) | {levene_p:.4f} | < 0.01 | "
            f"{'FAIL' if not math.isnan(levene_p) and levene_p < 0.01 else 'PASS'} |\n\n"
            "## Effect Size\n"
            f"- Live mean return: {live_mean*100:.4f}%\n"
            f"- Backtest mean return: {bt_mean*100:.4f}%\n"
            f"- Delta: {(live_mean-bt_mean)*100:.4f}%\n"
            f"- Cohen's d: {cohens_d:.3f}\n\n"
            "## Sebep Hipotezleri (Researcher'a teslim)\n"
            "1. **Veri kalitesi:** data_engineer audit gerekli mi?\n"
            "2. **Slippage erosion:** execution_chief slippage report kontrol et\n"
            "3. **Regime change:** hangi rejim modelinde ne diyor?\n"
            "4. **Edge erosion:** strategy maturity / arbitrage decay?\n"
            "5. **Sample variance:** n<30 ise true alarm olmayabilir\n\n"
            "## Aksiyon Önerisi\n"
            "- Researcher: `respond_to_drift()` ile yeni hipotez kartı (Faz 3 cron `scan_drift_alerts`)\n"
            "- Risk Officer: position size geçici azaltma değerlendirmesi\n"
            "- CEO: brief'te değin\n\n"
            "## Cooldown\n"
            "- Bu drift_alert için max **3 hipotez yanıtı** (researcher cool-down)\n"
            "- Lab tournament reddi sonrası **7 gün** aynı strateji için yeni hipotez yok\n"
        )

        return self.write_protocol_doc(
            doc_type="drift_alert",
            body=body,
            slug=f"drift-{symbol}-{strategy}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="high",
            requested_review_from=["researcher"],
            tags=["drift", strategy, symbol],
        )

    # ------------------------------------------------------------------
    # SOP-3: RAG refresh
    # ------------------------------------------------------------------

    async def rag_refresh(self, since_days: int = 7) -> Path:
        """Son N günde eklenen RAG belgelerini özetler."""
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        hits = summarize_recent_additions(since)
        prompt = (
            "RAG Refresh özeti. Aşağıdaki yeni belgelerden 5-10 maddelik "
            '"what\'s new in PA literature" listesi üret.\n\n'
            f"NEW DOCS ({len(hits)}): "
            + "\n\n".join(
                f"- [{h.metadata.get('source_id', '?')}] {h.metadata.get('title', '')}"
                f"\n{h.text[:300]}"
                for h in hits[:30]
            )
        )
        text = await self.run(prompt)
        iso = datetime.now(timezone.utc).isocalendar()
        path = self._reports_dir() / f"rag-refresh-{iso.year}-W{iso.week:02d}.md"
        path.write_text(text, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # SOP-4: Departman toplantısı
    # ------------------------------------------------------------------

    async def hold_meeting(self, agent_summaries: dict[str, str]) -> Path:
        """Tüm agent özetlerini sentezleyip toplantı raporu üret."""
        joined = "\n\n".join(f"### {k}\n{v}" for k, v in agent_summaries.items())
        prompt = (
            "SOP-4 Departman Toplantısı. Aşağıdaki agent özetlerini sentezle: "
            "ortak bulgular, çelişkiler, açık sorular, atanmış görevler.\n\n"
            f"--- SUMMARIES ---\n{joined}"
        )
        text = await self.run(prompt)
        iso = datetime.now(timezone.utc).isocalendar()
        path = self._reports_dir() / f"meeting-{iso.year}-W{iso.week:02d}.md"
        path.write_text(text, encoding="utf-8")
        return path
