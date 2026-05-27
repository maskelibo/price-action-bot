"""Researcher hipotezini → çalıştırılabilir backtest specifikasyonuna çevir
ve mümkünse otomatik koştur.

Faz 14.15 (2026-05-27): Researcher 36 saatte 1.8M token yakıp 14 hipotez
yazdı ama hiçbirinin BACKTEST sonucu yoktu → Lab tournament'a
`oos_returns=[], oos_sharpe=0` ile girip otomatik reject ediliyordu.
Bu modül o eksik halkayı kapatır:

    hipotez.md  ──Opus extract──▶  spec.json
                                       │
                                       ├─ type=param_sweep    ──▶ apply_cell sweep
                                       ├─ type=analysis       ──▶ correlation runner
                                       ├─ type=new_strategy   ──▶ DEFERRED
                                       └─ type=unknown        ──▶ NOT_AUTOMATED

Sonuçlar `memory/researcher/backtest_results/<hyp_id>.json` altında
tournament-friendly formatta yazılır (oos_returns sample, oos_sharpe
annualized, monthly_roi_pct_mean, max_dd_pct).
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from price_action.logging_config import logger

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HYP_DIR = REPO_ROOT / "memory" / "researcher" / "hypotheses"
DEFAULT_RESULTS_DIR = REPO_ROOT / "memory" / "researcher" / "backtest_results"
DEFAULT_POOL_MAP = {
    # bot_id → (pool_path, default_risk_pct, sl_pct_base)
    "vsa_climax_test": ("data/sec53_5m_pool_v11_vm20.pkl", 0.005, 0.030),
    "brooks_failed_breakout": ("data/sec53_15m_pool_v11.pkl", 0.005, 0.025),
    "anchored_vwap_reversal": ("data/sec53_5m_pool_v11_vm20.pkl", 0.005, 0.025),
    "engulfing_continuation": ("data/sec53_15m_pool_v11.pkl", 0.005, 0.025),
}


@dataclass
class HypothesisSpec:
    """LLM tarafından extract edilen yapılandırılmış hipotez."""
    hypothesis_id: str
    source_path: str
    hypothesis_type: str  # "param_sweep" | "analysis" | "new_strategy" | "unknown"
    base_strategy: str | None
    param_grid: dict[str, list[Any]] | None
    accept_gates: list[str]
    executable: bool
    reason_if_not: str
    raw_llm_response: str = ""


_EXTRACT_PROMPT = """Aşağıdaki hipotez dokümanını oku ve JSON formatında yapılandırılmış spec üret.
SADECE JSON döndür, açıklama yazma. Format:

{
  "hypothesis_id": "<dosya adı .md uzantısız>",
  "hypothesis_type": "param_sweep" | "analysis" | "new_strategy" | "unknown",
  "base_strategy": "<vsa_climax_test|brooks_failed_breakout|anchored_vwap_reversal|engulfing_continuation> veya null",
  "param_grid": {
    "<param_adı>": [<değer1>, <değer2>, ...],
    ...
  } veya null,
  "accept_gates": ["<gate1>", "<gate2>", ...],
  "executable": true|false,
  "reason_if_not": "<executable=false ise sebep, yoksa boş string>"
}

Tip sınıflandırma kuralları:
- "param_sweep": belirgin parametre grid var (sl_pct, risk_pct, tp_r, vol_target gibi). Mevcut sweep runner'ı koşturabilir.
- "analysis": korelasyon, ρ, distribution, statistical test. Yeni strateji değil — analiz.
- "new_strategy": yepyeni bir strateji tanımı (yeni signal logic, yeni indikatör kombinasyonu).
- "unknown": net değil veya yapılandırılamıyor.

base_strategy mevcut 4 strateji'den biri olmalı (varsa). Hipotez yeni bir strateji öneriyorsa "new_strategy" tipi olur, base_strategy null kalır.

ÖNEMLI base_strategy fallback kuralları:
- Hipotez "widestop", "15m wide-stop", "phoenix scalp 15m" yazıyorsa → base_strategy="vsa_climax_test" (mevcut canlı widestop bot'un çekirdek stratejisi)
- Hipotez "vsa", "vsa_climax", "Volume Spread Analysis" yazıyorsa → base_strategy="vsa_climax_test"
- Hipotez "brooks", "failed breakout" yazıyorsa → base_strategy="brooks_failed_breakout"
- Hipotez "anchored vwap", "avwap" yazıyorsa → base_strategy="anchored_vwap_reversal"
- Hipotez "engulfing" yazıyorsa → base_strategy="engulfing_continuation"
- Hipotez 5m bot için ise: base_strategy yine vsa_climax_test (5m bot da onu kullanıyor)

param_grid extract: hipotez metinindeki "## Bağımsız değişkenler" benzeri bölümden grid'i çıkar.
Param adlarını TAM hipotez metnindeki ŞEKİLDE bırak (örn sl_pct, risk_pct, tp_r, vol_target_atr_pct).
Listelerdeki sayıları float'a parse et.

executable=false durumları:
- new_strategy: backtest motorumuz henüz hipotezi koşturamaz (DEFERRED)
- unknown: yapı çıkarılamadı
- analysis ama veri yok: skip

HİPOTEZ:
---
"""


class HypothesisRunner:
    """Hipotez extract + backtest + result writer."""

    def __init__(
        self,
        *,
        hyp_dir: Path | None = None,
        results_dir: Path | None = None,
    ):
        self.hyp_dir = hyp_dir or DEFAULT_HYP_DIR
        self.results_dir = results_dir or DEFAULT_RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1) LLM Extract
    # ------------------------------------------------------------------

    async def extract_spec(self, hyp_path: Path) -> HypothesisSpec:
        """Hipotez MD → structured spec (Opus extract)."""
        text = hyp_path.read_text(encoding="utf-8", errors="ignore")
        # Hipotez büyük olabilir (5K+ kelime) — ilk 8000 karakter yeterli
        # (acceptance criteria, bağımsız değişkenler ilk yarıda yer alır)
        text_trunc = text[:8000]

        # Lab Scientist agent'ı kullan (CLI subscription auth zaten ayarlı)
        from price_action.agents import LabScientistAgent
        lab = LabScientistAgent()
        prompt = _EXTRACT_PROMPT + f"\n{text_trunc}\n---\n\nSADECE JSON döndür."
        try:
            response = await lab.run(prompt)
        except Exception as exc:
            logger.warning(
                "hyp_runner.extract_llm_fail",
                extra={"hyp": hyp_path.name, "err": str(exc)[:200]},
            )
            return HypothesisSpec(
                hypothesis_id=hyp_path.stem,
                source_path=str(hyp_path),
                hypothesis_type="unknown",
                base_strategy=None,
                param_grid=None,
                accept_gates=[],
                executable=False,
                reason_if_not=f"LLM extract failed: {str(exc)[:100]}",
            )

        # JSON parse — LLM bazen markdown ```json``` wrap eder
        cleaned = response.strip()
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        # İlk { ile son } arasını yakala (LLM önsöz ekleyebilir)
        m2 = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m2:
            cleaned = m2.group(0)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "hyp_runner.extract_json_fail",
                extra={"hyp": hyp_path.name, "err": str(exc)[:200], "raw": cleaned[:300]},
            )
            return HypothesisSpec(
                hypothesis_id=hyp_path.stem,
                source_path=str(hyp_path),
                hypothesis_type="unknown",
                base_strategy=None,
                param_grid=None,
                accept_gates=[],
                executable=False,
                reason_if_not=f"JSON parse failed: {str(exc)[:100]}",
                raw_llm_response=response[:500],
            )

        return HypothesisSpec(
            hypothesis_id=data.get("hypothesis_id", hyp_path.stem),
            source_path=str(hyp_path),
            hypothesis_type=str(data.get("hypothesis_type", "unknown")),
            base_strategy=data.get("base_strategy"),
            param_grid=data.get("param_grid"),
            accept_gates=list(data.get("accept_gates", [])),
            executable=bool(data.get("executable", False)),
            reason_if_not=str(data.get("reason_if_not", "")),
            raw_llm_response=response[:500],
        )

    # ------------------------------------------------------------------
    # 2) Type-specific runners
    # ------------------------------------------------------------------

    def run_param_sweep(self, spec: HypothesisSpec) -> dict[str, Any]:
        """Hipotez grid'i ile param_sweep_runner çağır.

        Mevcut altyapı (param_sweep_runner.apply_cell) sl_multiplier,
        tp_r, risk_pct grid'ini bekler. Hipotez farklı isimler kullanabilir
        (sl_pct, sl_pct_min, vs.) → mapping yap.
        """
        if not spec.base_strategy:
            return {"status": "ERROR", "reason": "base_strategy yok"}
        if spec.base_strategy not in DEFAULT_POOL_MAP:
            return {"status": "ERROR", "reason": f"strateji bilinmiyor: {spec.base_strategy}"}
        if not spec.param_grid:
            return {"status": "ERROR", "reason": "param_grid yok"}

        pool_path, default_risk, sl_pct_base = DEFAULT_POOL_MAP[spec.base_strategy]
        full_pool_path = REPO_ROOT / pool_path
        if not full_pool_path.exists():
            return {"status": "ERROR", "reason": f"pool yok: {pool_path}"}

        # Param mapping (hipotez naming → sweep naming)
        grid = spec.param_grid
        # sl_pct (mutlak) → sl_multiplier (sl_pct / sl_pct_base)
        sl_multipliers: list[float]
        if "sl_pct" in grid:
            sl_multipliers = [float(x) / sl_pct_base for x in grid["sl_pct"]]
        elif "sl_multiplier" in grid:
            sl_multipliers = [float(x) for x in grid["sl_multiplier"]]
        else:
            sl_multipliers = [1.0]  # default

        # FIX 2026-05-27 06:10 TR (Faz 14.16b): hipotez tp_r belirtmediyse
        # 1.5 default override BÜYÜK KAZANÇLARI CAP'LİYOR — vsa wide-stop
        # trade'lerinin peak_R'leri çoğunlukla 1.5'u aşıyor, realized +3R
        # kazançlar +1.5R'ye çekiliyor → mean_R negatife dönüyor.
        # 999 default = "override yapma, pool'un realized R'sini kullan".
        # Bu, hipotezin sadece sl_pct + risk_pct'i test ettiği durum için
        # canlı bot davranışına çok daha yakın sonuç verir.
        tp_rs = [float(x) for x in grid.get("tp_r", [999.0])]
        risk_pcts = [float(x) for x in grid.get("risk_pct", [default_risk])]

        # Sweep'i koş — sadece ilk N=20 cell (test için, full grid yorucu)
        import itertools
        import pickle
        import sys
        scripts_dir = REPO_ROOT / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from param_sweep_runner import apply_cell, load_pool

        try:
            df = load_pool(full_pool_path)
        except Exception as exc:
            return {"status": "ERROR", "reason": f"pool load fail: {str(exc)[:100]}"}

        # FIX 2026-05-27 06:00 TR (Faz 14.16): KRİTİK BUG —
        # Pool 4 stratejiyi karıştırıyor (brooks 220K + anchored 104K + vsa 75K
        # + engulfing 9K = 409K trade). apply_cell strategy filtresi
        # yapmıyor → "vsa_climax_test widestop" hipotezini test ederken
        # brooks'un kötü trade'leri de dahil olup ortalama negatife düşüyor.
        # Doğru: vsa_climax_test sadece + wide-stop → mean R = +1.077.
        # Yanlış (önceki): 4-strateji karışık → mean R = -0.0556.
        if "strategy" in df.columns:
            df_strategy = df[df["strategy"] == spec.base_strategy].copy()
            n_before, n_after = len(df), len(df_strategy)
            logger.info(
                "hyp_runner.pool_strategy_filtered",
                extra={
                    "strategy": spec.base_strategy,
                    "n_before": n_before,
                    "n_after": n_after,
                    "pct_kept": round(n_after / max(n_before, 1) * 100, 1),
                },
            )
            if n_after == 0:
                return {
                    "status": "ERROR",
                    "reason": f"pool'da {spec.base_strategy} trade yok",
                }
            df = df_strategy

        cells: list[dict[str, Any]] = []
        max_cells = 20
        for sl, tp, rk in itertools.product(sl_multipliers, tp_rs, risk_pcts):
            if len(cells) >= max_cells:
                break
            try:
                metric = apply_cell(
                    df, sl_multiplier=sl, tp_r=tp, risk_pct=rk,
                    sl_pct_base=sl_pct_base, regime_series=None,
                )
                row = metric.to_row()
                row["strategy"] = spec.base_strategy
                cells.append(row)
            except Exception as exc:
                logger.warning(
                    "hyp_runner.cell_fail",
                    extra={"sl": sl, "tp": tp, "rk": rk, "err": str(exc)[:200]},
                )

        if not cells:
            return {"status": "ERROR", "reason": "hiç cell başarılı değil"}

        # En iyi cell'i seç (mean_R_after_fees'e göre, n_trades min 100)
        viable = [c for c in cells if c["n_trades"] >= 100]
        if not viable:
            best = max(cells, key=lambda c: c["mean_R_after_fees"])
        else:
            best = max(viable, key=lambda c: c["mean_R_after_fees"])

        return {
            "status": "OK",
            "type": "param_sweep",
            "n_cells_evaluated": len(cells),
            "best_cell": best,
            "all_cells_top5": sorted(
                cells, key=lambda c: c["mean_R_after_fees"], reverse=True
            )[:5],
        }

    def run_correlation_analysis(self, spec: HypothesisSpec) -> dict[str, Any]:
        """Cross-strategy correlation analizi.

        Sweep cells'in returns_R_sample'larını al, pairwise Pearson ρ matrix
        hesap, hipotez kabul kriterine göre değerlendir.
        """
        try:
            import numpy as np
            from price_action.lab.sweep_aggregator import top_cells_as_challengers
        except ImportError as exc:
            return {"status": "ERROR", "reason": f"import fail: {exc}"}

        # Tüm strategy top cells'i al (3 strateji × top3)
        challengers = top_cells_as_challengers(top_n_per_strategy=3)
        if len(challengers) < 2:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason": f"sadece {len(challengers)} challenger var, korelasyon hesabı için min 2",
            }

        # Returns matrix (her cell için sample boyutu eşit olmayabilir)
        min_len = min(len(c["oos_returns"]) for c in challengers if c["oos_returns"])
        if min_len < 50:
            return {
                "status": "INSUFFICIENT_DATA",
                "reason": f"min returns sample {min_len} < 50",
            }
        # Eşit boyuta truncate
        names = [c["id"] for c in challengers]
        arr = np.array([c["oos_returns"][:min_len] for c in challengers], dtype=float)
        # Pearson correlation matrix
        corr = np.corrcoef(arr)
        # Pairs with abs(ρ) < 0.20 (low correlation companions)
        n = len(names)
        low_corr_pairs: list[dict[str, Any]] = []
        for i in range(n):
            for j in range(i + 1, n):
                rho = float(corr[i][j])
                if abs(rho) < 0.20:
                    low_corr_pairs.append({
                        "a": names[i],
                        "b": names[j],
                        "rho": round(rho, 4),
                    })
        return {
            "status": "OK",
            "type": "analysis",
            "n_strategies_compared": n,
            "min_sample_size": min_len,
            "correlation_matrix": {
                names[i]: {names[j]: round(float(corr[i][j]), 4) for j in range(n)}
                for i in range(n)
            },
            "low_correlation_pairs": low_corr_pairs,
            "n_low_corr_pairs": len(low_corr_pairs),
        }

    # ------------------------------------------------------------------
    # 3) Orchestrate
    # ------------------------------------------------------------------

    async def run(self, hyp_path: Path, *, skip_if_exists: bool = True) -> dict[str, Any]:
        """End-to-end: extract → run → write result JSON."""
        result_path = self.results_dir / f"{hyp_path.stem}.json"
        if skip_if_exists and result_path.exists():
            try:
                existing = json.loads(result_path.read_text())
                logger.info(
                    "hyp_runner.skip_existing",
                    extra={"hyp": hyp_path.name, "existing_status": existing.get("status")},
                )
                return existing
            except json.JSONDecodeError:
                pass  # corrupted, re-run

        spec = await self.extract_spec(hyp_path)
        logger.info(
            "hyp_runner.spec_extracted",
            extra={
                "hyp": hyp_path.name,
                "type": spec.hypothesis_type,
                "base": spec.base_strategy,
                "executable": spec.executable,
            },
        )

        # FIX: analysis tipi için executable=false olsa bile basit Pearson koş
        # (full conditional/tail correlation MVP'de yok ama unconditional
        # ρ matrix yine yararlı partial result verir).
        if spec.hypothesis_type == "analysis":
            run_result = await asyncio.to_thread(self.run_correlation_analysis, spec)
            if not spec.executable:
                # LLM'in "tam executable değil" notunu sonuca ekle
                run_result["partial_note"] = (
                    f"PARTIAL — sadece unconditional Pearson hesaplandı. "
                    f"Hipotez tam koşum için ekstra pipeline ister: {spec.reason_if_not}"
                )
        elif not spec.executable:
            run_result = {
                "status": "NOT_EXECUTABLE",
                "reason": spec.reason_if_not or "executable=false",
            }
        elif spec.hypothesis_type == "param_sweep":
            run_result = await asyncio.to_thread(self.run_param_sweep, spec)
        elif spec.hypothesis_type == "new_strategy":
            run_result = {
                "status": "DEFERRED",
                "reason": "new_strategy runner henüz yok — manuel pa-backtest gerek",
            }
        else:
            run_result = {
                "status": "NOT_AUTOMATED",
                "reason": f"unknown type: {spec.hypothesis_type}",
            }

        out = {
            "hypothesis_id": spec.hypothesis_id,
            "source_path": spec.source_path,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "spec": {
                "type": spec.hypothesis_type,
                "base_strategy": spec.base_strategy,
                "param_grid": spec.param_grid,
                "accept_gates": spec.accept_gates,
                "executable": spec.executable,
                "reason_if_not": spec.reason_if_not,
            },
            "result": run_result,
        }
        result_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        logger.info(
            "hyp_runner.result_written",
            extra={
                "hyp": hyp_path.name,
                "path": str(result_path),
                "status": run_result.get("status"),
            },
        )
        return out

    async def run_all_pending(self, *, since_days: int = 30, max_runs: int = 5) -> list[dict]:
        """Backtest_results'ta result'ı olmayan hipotezleri sırayla koştur.

        max_runs: token tüketimini kontrol için cap (LLM extract her hipotez
        için ~5K token).
        """
        cutoff_dt = datetime.now(timezone.utc).timestamp() - since_days * 86400
        pending: list[Path] = []
        for hyp_path in sorted(self.hyp_dir.glob("*.md"), reverse=True):
            # Skip README/TEMPLATE
            if hyp_path.name.startswith(("README", "TEMPLATE", "_")):
                continue
            try:
                if hyp_path.stat().st_mtime < cutoff_dt:
                    continue
            except Exception:
                continue
            result_path = self.results_dir / f"{hyp_path.stem}.json"
            if result_path.exists():
                continue
            pending.append(hyp_path)
            if len(pending) >= max_runs:
                break
        logger.info(
            "hyp_runner.batch_start",
            extra={"n_pending": len(pending), "max_runs": max_runs},
        )
        results = []
        for hyp_path in pending:
            try:
                r = await self.run(hyp_path)
                results.append(r)
            except Exception as exc:
                logger.warning(
                    "hyp_runner.run_fail",
                    extra={"hyp": hyp_path.name, "err": str(exc)[:200]},
                )
                results.append({"hypothesis_id": hyp_path.stem, "error": str(exc)[:200]})
        return results


if __name__ == "__main__":
    import sys
    runner = HypothesisRunner()
    if len(sys.argv) > 1:
        # Tek hipotez
        hp = Path(sys.argv[1])
        if not hp.is_absolute():
            hp = DEFAULT_HYP_DIR / hp.name
        result = asyncio.run(runner.run(hp, skip_if_exists=False))
        print(json.dumps(result, indent=2, default=str))
    else:
        # Batch
        results = asyncio.run(runner.run_all_pending(max_runs=3))
        print(f"Toplam koşulan: {len(results)}")
        for r in results:
            print(f"  {r.get('hypothesis_id', '?'):60} → {r.get('result', {}).get('status', '?')}")
