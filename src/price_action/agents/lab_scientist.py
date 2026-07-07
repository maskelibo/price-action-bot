"""Lab Scientist Agent — Self-Improvement Lab.

Tournament, drift detection, RAG refresh, departman toplantısı.
İstatistik: ``scipy.stats``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from price_action.logging_config import logger
from price_action.rag import summarize_recent_additions

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

    def _load_gates_config(self) -> dict[str, Any]:
        """Cleanup 5: configs/lab_gates.yaml → promotion_gates section.

        Eksikse default değerler döner (hardcoded backwards compat).
        """
        try:
            import yaml

            cfg_path = self.settings.reports_dir.parent / "configs" / "lab_gates.yaml"
            if not cfg_path.exists():
                return {}
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return data.get("promotion_gates", {})
        except Exception as exc:
            logger.warning("lab.gates_config_fail", extra={"err": str(exc)[:200]})
            return {}

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

    def welch_ttest(self, a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
        """İki returns serisi arasında Welch's t-test."""
        stats = self._import_scipy()
        if stats is None or len(a) < 2 or len(b) < 2:
            return {"t": math.nan, "p": math.nan}
        result = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        return {"t": float(result.statistic), "p": float(result.pvalue)}

    def ks_test(self, a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
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
        returns: Sequence[float] | None = None,
    ) -> dict[str, float]:
        """DSR (Deflated Sharpe Ratio) — Bailey & López de Prado.

        Çoklu test sayısına ve örnek istatistiklere göre düzeltilmiş p-value.

        FIX 2026-07-02 (fabrika RW P0-2): ``returns`` verilirse istatistik
        DOĞRU birimde hesaplanır — per-obs SR örneklemden türetilir ve
        z = SR_obs·√(n−1)/denom − E[maxZ(n_trials)] karşılaştırması yapılır.
        Eski yol (annualized sharpe'ı Z-birimiyle karıştıran) yalnız returns
        yokken fallback olarak kalır. Eski yolda ayrıca n_trials'a yanlışlıkla
        TRADE sayısı besleniyordu (kaynak fix: sweep_aggregator) — ikisi
        birlikte dsr_p'yi kalıcı ~1.0'a çiviliyordu → 0 terfi.
        """
        stats = self._import_scipy()
        if stats is None or n_trials < 1:
            return {"dsr": math.nan, "p": math.nan}
        # Beklenen maksimum Z (n_trials bağımsız deneme içinde)
        # E[max(Z)] ≈ (1 - γ) * Φ⁻¹(1 - 1/n) + γ * Φ⁻¹(1 - 1/(n*e))
        gamma = 0.5772156649  # Euler-Mascheroni
        try:
            inv1 = stats.norm.ppf(1 - 1.0 / max(n_trials, 2))
            inv2 = stats.norm.ppf(1 - 1.0 / (max(n_trials, 2) * math.e))
            e_max_z = (1 - gamma) * inv1 + gamma * inv2

            if returns is not None and len(returns) >= 30:
                # --- Doğru yol: per-obs SR, skew/kurt örneklemden ---
                import numpy as _np

                r = _np.asarray(list(returns), dtype=float)
                r = r[_np.isfinite(r)]
                n = int(r.size)
                if n < 30:
                    return {"dsr": math.nan, "p": math.nan}
                sd = float(r.std(ddof=1))
                if sd <= 1e-12:
                    return {"dsr": math.nan, "p": math.nan}
                sr_obs = float(r.mean()) / sd
                skew_s = float(stats.skew(r))
                kurt_s = float(stats.kurtosis(r, fisher=False))  # Pearson (normal=3)
                denom = math.sqrt(max(1e-9, 1 - skew_s * sr_obs + ((kurt_s - 1) / 4.0) * sr_obs**2))
                z = sr_obs * math.sqrt(n - 1) / denom - float(e_max_z)
                p = 1.0 - float(stats.norm.cdf(z))
                return {
                    "dsr": float(z),
                    "p": p,
                    "sr_obs": sr_obs,
                    "expected_max_z": float(e_max_z),
                    "n_obs_used": float(n),
                }

            # --- Legacy fallback (returns yok): eski davranış korunur ---
            if n_obs < 30:
                return {"dsr": math.nan, "p": math.nan}
            sharpe0 = e_max_z
            denom = math.sqrt(
                max(
                    1e-9,
                    1 - skew * sharpe + ((kurt - 1) / 4.0) * sharpe**2,
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
        """Tournament için aday strateji konfig'leri topla — iki kaynak.

        Kaynak 1 (FAZ 14.10, 2026-05-27 birincil): **Param sweep chunks**
            `reports/param_sweep/chunks/*.jsonl` — `param_sweep_runner` her
            saat 5 cell işliyor (vsa_climax_test, brooks_failed_breakout,
            anchored_vwap_reversal rotasyonu). Çıktı per-cell:
            `{sl_multiplier, tp_r, risk_pct, n_trades, sharpe_like,
            mean_R_after_fees, sum_R, regime breakdowns}`.
            `top_cells_as_challengers()` strateji başına top-N dedupe'lu
            (sl, tp) cell döner — bunlar GERÇEK sayısal challenger.

        Kaynak 2 (geçici, deprecated bekçi): **Researcher hipotez dosyaları**
            `memory/researcher/hypotheses/*.md` — backtest sonucu YOKSA
            (`PENDING_BACKTEST`), `_collect_pending_hypotheses()` ile
            sadece METADATA olarak eklenir. Bu hipotezler tournament'a
            sayısal yarışmacı olarak ALINMAZ (oos_sharpe=0 → reject), ama
            CEO raporda "Researcher şu hipotezleri yazdı, henüz backtest
            yok" bilgisi geçsin diye listede tutulur.

        Eskisi (boş hipotezleri sweep'e koymak): tournament `rows: []`
        üretiyordu → CEO yeni bot adayı GÖREMİYORDU. Bu yenisi sweep
        chunk'larından gerçek tournament girdisi sağlıyor.
        """
        challengers: list[dict[str, Any]] = []

        # Kaynak 1 — gerçek sayısal challenger (param sweep cells)
        try:
            from price_action.lab.sweep_aggregator import top_cells_as_challengers

            sweep_challengers = top_cells_as_challengers(
                since_days=since_days,
                top_n_per_strategy=3,
                min_trades=500,
                min_mean_R_after_fees=0.0,  # fee sonrası kayıp = aday değil
            )
            challengers.extend(sweep_challengers)
            logger.info(
                "lab.sweep_challengers_collected",
                extra={"n": len(sweep_challengers)},
            )
        except Exception as exc:
            logger.warning(
                "lab.sweep_challengers_fail",
                extra={"err": str(exc)[:200]},
            )

        # Kaynak 2 — hipotez "place-holder" listesi (metadata only, oos=0)
        try:
            from price_action.memory.store import MemoryStore

            store = MemoryStore()
            hyp_docs = store.list_recent_docs(
                agent="researcher",
                doc_type="hypothesis",
                since_days=since_days,
            )
            hyp_dir_memory = self.settings.memory_dir / "researcher" / "hypotheses"
            if hyp_dir_memory.exists():
                extra = sorted(hyp_dir_memory.glob("*.md"), reverse=True)[:20]
                hyp_docs = list(hyp_docs) + list(extra)
            # FIX 2026-05-27 (Lab Scientist tournament feedback): README,
            # TEMPLATE, .tmpl gibi gerçek hipotez olmayan dosyaları ele.
            HYP_SKIP_PREFIXES = ("README", "TEMPLATE", "_template")
            HYP_SKIP_SUFFIXES = (".tmpl", "_template.md")
            # FIX 2026-05-27 (Faz 14.15): hipotez backtest_results/ varsa
            # PENDING_BACKTEST placeholder yerine GERÇEK sonuçları kullan.
            results_dir = self.settings.memory_dir / "researcher" / "backtest_results"
            for doc in hyp_docs[:15]:
                name = doc.name
                if any(name.startswith(p) for p in HYP_SKIP_PREFIXES):
                    continue
                if any(name.endswith(s) for s in HYP_SKIP_SUFFIXES):
                    continue
                # backtest result var mı?
                result_path = results_dir / f"{doc.stem}.json"
                if result_path.exists():
                    try:
                        import json as _json

                        rdata = _json.loads(result_path.read_text())
                        rstatus = rdata.get("result", {}).get("status", "")
                        rtype = rdata.get("spec", {}).get("type", "")
                        if rstatus == "OK" and rtype == "param_sweep":
                            best = rdata["result"].get("best_cell", {})
                            challengers.append(
                                {
                                    "id": doc.stem,
                                    "source_doc": str(doc),
                                    "oos_returns": list(best.get("returns_R_sample", [])),
                                    "oos_sharpe": float(best.get("sharpe_annualized", 0.0)),
                                    "oos_maxdd": float(best.get("max_drawdown_R", 0.0))
                                    * float(best.get("risk_pct", 0.005)),
                                    # FIX 2026-07-07 (denetim H3): n_trials =
                                    # DENENEN HÜCRE sayısı (çoklu-test düzeltmesi
                                    # bunu bekler) — eski n_trades (binlerce)
                                    # E[maxZ]≈3.5 → dsr_p≈1 → otomatik reject
                                    # üretiyordu (2 Tem fix'i bu yolu atlamıştı).
                                    "n_trials": max(
                                        int(rdata["result"].get("n_cells_evaluated") or 0),
                                        1,
                                    ),
                                    "mean_R_after_fees": float(best.get("mean_R_after_fees", 0.0)),
                                    "hypothesis_spec": rdata.get("spec"),
                                    "status": "BACKTESTED_FROM_HYP",
                                }
                            )
                            continue
                        elif rstatus == "OK" and rtype == "analysis":
                            # Analysis sonucu — sayısal challenger değil ama
                            # findings olarak ekle (informational)
                            challengers.append(
                                {
                                    "id": doc.stem,
                                    "source_doc": str(doc),
                                    "oos_returns": [],
                                    "oos_sharpe": 0.0,
                                    "oos_maxdd": 0.0,
                                    "n_trials": 0,
                                    "analysis_findings": rdata["result"],
                                    "status": "ANALYSIS_RESULT",
                                }
                            )
                            continue
                        # NOT_EXECUTABLE / DEFERRED / ERROR — fall through to placeholder
                    except Exception:
                        pass
                # FIX 2026-06-22 (turnuva hijyeni): seed-abort hipotezleri seed
                # eleme aşamasında iptal edildi — backtest'leri OLMAYACAK, yani
                # "pending" değil ölü. Bunları PENDING_BACKTEST placeholder olarak
                # turnuvaya sokmak 0-row sahte "challenger" tortusu üretiyordu
                # (W24/W25'te 21 adayın ~14'ü bu tortuydu, raporu yanıltıyordu).
                # Gerçek sonucu olan dosyalar yukarıda zaten BACKTESTED_FROM_HYP /
                # ANALYSIS_RESULT ile `continue` edildi; buraya yalnızca placeholder
                # düşer — seed-abort placeholder'ı ele (gerçek challenger asla düşmez).
                if "seed-abort" in name:
                    continue
                # Default: PENDING_BACKTEST placeholder (sweep_aggregator dolduracak)
                challengers.append(
                    {
                        "id": doc.stem,
                        "source_doc": str(doc),
                        "oos_returns": [],
                        "oos_sharpe": 0.0,
                        "oos_maxdd": 0.0,
                        "n_trials": 0,
                        "status": "PENDING_BACKTEST",
                    }
                )
        except Exception as exc:
            logger.warning(
                "lab.hyp_collect_fail",
                extra={"err": str(exc)[:200]},
            )

        logger.info(
            "lab.auto_collected_challengers",
            extra={"n_total": len(challengers)},
        )
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
        # Cleanup 5: gates config'den oku (hardcoded → configs/lab_gates.yaml)
        gates = self._load_gates_config()
        effect_min = float(gates.get("effect_size_min_pct", 0.15))
        dsr_max = float(gates.get("dsr_p_value_max", 0.05))
        maxdd_excess = float(gates.get("maxdd_excess_max", 0.05))

        rows: list[dict[str, Any]] = []
        c_returns = list(champion.get("oos_returns", []) or [])
        c_sharpe = float(champion.get("oos_sharpe", 0))

        for ch in challengers:
            ch_returns = list(ch.get("oos_returns", []) or [])
            tt = self.welch_ttest(ch_returns, c_returns)
            # FIX 2026-07-02 (P0-2): returns örneklemini DSR'ye geçir — per-obs
            # SR + doğru çoklu-test düzeltmesi. n_trials artık kaynak tarafında
            # (sweep_aggregator) denenen-konfig sayısı olarak geliyor.
            dsr = self.deflated_sharpe(
                float(ch.get("oos_sharpe", 0)),
                int(ch.get("n_trials", 1)),
                len(ch_returns) or 30,
                returns=ch_returns or None,
            )
            effect = (float(ch.get("oos_sharpe", 0)) - c_sharpe) / max(abs(c_sharpe), 1e-9)
            promote = (
                effect >= effect_min
                and dsr.get("p", 1.0) < dsr_max
                and float(ch.get("oos_maxdd", 1))
                <= float(champion.get("oos_maxdd", 1)) + maxdd_excess
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
        iso = datetime.now(UTC).isocalendar()
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
            confidence="high"
            if rows and any(r.get("decision") == "promote_candidate" for r in rows)
            else "med",
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
            f"- Detected at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
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
        since = datetime.now(UTC) - timedelta(days=since_days)
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
        iso = datetime.now(UTC).isocalendar()
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
        iso = datetime.now(UTC).isocalendar()
        path = self._reports_dir() / f"meeting-{iso.year}-W{iso.week:02d}.md"
        path.write_text(text, encoding="utf-8")
        return path
