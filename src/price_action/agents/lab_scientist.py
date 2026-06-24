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

    async def weekly_tournament(
        self,
        champion: dict[str, Any],
        challengers: list[dict[str, Any]],
    ) -> Path:
        """Champion vs challenger karşılaştırması.

        ``champion`` ve ``challengers``:
            {
              "id": "...",
              "oos_returns": [...],
              "oos_sharpe": 1.23,
              "oos_maxdd": 0.18,
              "n_trials": 80,
            }
        """
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
        report_path = self._reports_dir() / f"tournament-{iso.year}-W{iso.week:02d}.md"
        report_path.write_text(
            f"# Tournament Report — Week {iso.week:02d}\n\n"
            f"## Rows\n```json\n{rows}\n```\n\n## Commentary\n{commentary}\n",
            encoding="utf-8",
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
    ) -> dict[str, Any]:
        """KS + Welch + Levene; herhangi p < alpha → drift uyarısı."""
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
        return result

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
