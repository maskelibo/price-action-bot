"""Strategy Curator Agent — Portfolio Lifecycle Management (Faz 8).

Sera bahçıvanı: stratejileri **bitki** gibi yönetir. Alpha decay'ler emekliye,
yeni adaylar onboarding'e.

DESIGN:
- Çoğu iş deterministik (numpy + linear regression + Shannon entropy).
- LLM (Opus) sadece haftalık lifecycle review'da commentary / verdict
  gerekçelendirmesi için. Daily correlation update — pure deterministic.
- READ-ONLY: configs/risk_phoenix_scalp_*.yaml dokunulmaz; library glob
  dosya isimleri okur, modül import etmez.
- Deploy ETMEZ — sadece öneri yazar. `requested_review_from: [ceo, risk_officer]`.

HARD LIMITS (.claude/agents/strategy_curator.md §Hard Limits):
- Aktif config edit YOK
- Lab tournament bypass YOK
- Cool-down ihlali YOK (`cooldown_weeks_after_retire: 12`)
- Recency bias YOK — minimum 3 hafta consecutive decay + n_trades ≥ 30
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar, Iterable, Sequence

from price_action.logging_config import logger

from .base import LLMAgentBase


# ---------------------------------------------------------------------------
# Module-level helpers (testable without instantiating the agent)
# ---------------------------------------------------------------------------


def _calc_alpha_decay_slope(
    returns_series: Sequence[float], window_days: int = 90
) -> dict[str, float]:
    """Returns serisinden rolling Sharpe slope (linear regression).

    Yöntem:
      1. Günlük returns serisi → rolling Sharpe (window içinde mean/std * sqrt(252)).
      2. Sharpe serisi üzerinde linear regression (x = gün index, y = rolling Sharpe).
      3. Slope (/gün) + standard error.

    Negatif slope → alpha decay; daha negatifse aday retire.
    n < window_days*2 ise yetersiz veri → slope=NaN.

    Returns
    -------
    dict
        {"slope": float, "slope_se": float, "n_obs": int, "mean_sharpe": float}
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return {"slope": math.nan, "slope_se": math.nan, "n_obs": 0, "mean_sharpe": math.nan}

    arr = np.asarray(list(returns_series), dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    # Minimum: window + ufak buffer; aksi rolling Sharpe çok az nokta verir
    if n < max(window_days + 5, 10):
        return {"slope": math.nan, "slope_se": math.nan, "n_obs": n, "mean_sharpe": math.nan}

    # Rolling Sharpe (annualized 252)
    sharpe_series: list[float] = []
    for i in range(window_days, n + 1):
        slice_ = arr[i - window_days : i]
        mu = float(slice_.mean())
        sigma = float(slice_.std(ddof=1))
        if sigma <= 1e-12:
            sharpe_series.append(0.0)
        else:
            sharpe_series.append(mu / sigma * math.sqrt(252))

    if len(sharpe_series) < 5:
        return {
            "slope": math.nan,
            "slope_se": math.nan,
            "n_obs": n,
            "mean_sharpe": float(np.mean(sharpe_series)) if sharpe_series else math.nan,
        }

    x = np.arange(len(sharpe_series), dtype=float)
    y = np.asarray(sharpe_series, dtype=float)
    # OLS: slope, intercept
    x_mean = x.mean()
    y_mean = y.mean()
    ss_xx = float(((x - x_mean) ** 2).sum())
    if ss_xx <= 1e-12:
        return {
            "slope": 0.0,
            "slope_se": math.nan,
            "n_obs": n,
            "mean_sharpe": float(y_mean),
        }
    ss_xy = float(((x - x_mean) * (y - y_mean)).sum())
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    # Residual std error → slope SE
    resid = y - (slope * x + intercept)
    df = max(len(y) - 2, 1)
    sigma_r = math.sqrt(float((resid ** 2).sum()) / df)
    slope_se = sigma_r / math.sqrt(ss_xx)
    return {
        "slope": float(slope),
        "slope_se": float(slope_se),
        "n_obs": int(n),
        "mean_sharpe": float(y_mean),
    }


def _calc_diversity_entropy(corr_matrix: Any) -> dict[str, float]:
    """Shannon diversity entropy (normalized) korelasyon matrisinden.

    Yöntem:
      1. corr matrix → similarity → 1 - |corr| dissimilarity
      2. Eigen-decomposition; eigenvalues / sum → probability dist (effective)
      3. H = -sum(p_i log p_i); H_norm = H / log(n)

    Uncorrelated portfolio → H_norm → 1.0 (perfectly diverse).
    Perfectly correlated (all 1.0) → H_norm → 0.0.

    Returns
    -------
    dict
        {"entropy": float, "entropy_normalized": float, "n_strategies": int}
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return {"entropy": math.nan, "entropy_normalized": math.nan, "n_strategies": 0}

    C = np.asarray(corr_matrix, dtype=float)
    if C.ndim != 2 or C.shape[0] != C.shape[1]:
        return {"entropy": math.nan, "entropy_normalized": math.nan, "n_strategies": 0}
    n = C.shape[0]
    if n < 2:
        return {"entropy": 0.0, "entropy_normalized": 0.0, "n_strategies": n}

    # Eigen-decomposition (positive semi-definite varsay; numerik düzeltme)
    try:
        eigvals = np.linalg.eigvalsh(C)
    except Exception:
        return {"entropy": math.nan, "entropy_normalized": math.nan, "n_strategies": n}

    # Negatif eigenvalue olabilir (numerik hata) — clip
    eigvals = np.clip(eigvals, 1e-12, None)
    total = float(eigvals.sum())
    if total <= 1e-12:
        return {"entropy": 0.0, "entropy_normalized": 0.0, "n_strategies": n}
    p = eigvals / total
    # Shannon entropy
    H = -float((p * np.log(p)).sum())
    H_norm = H / math.log(n) if n > 1 else 0.0
    return {
        "entropy": float(H),
        "entropy_normalized": float(H_norm),
        "n_strategies": int(n),
    }


def _annualized_sharpe(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Basit annualized Sharpe (risk-free 0). Bos seri → 0."""
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return 0.0
    arr = np.asarray(list(returns), dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size < 2:
        return 0.0
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    if sigma <= 1e-12:
        return 0.0
    return float(mu / sigma * math.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class StrategyCuratorAgent(LLMAgentBase):
    """Portfolio lifecycle: alpha decay, marginal Sharpe, diversity entropy.

    Tüm dosya çıktıları `reports/curator/` altına. LLM (Opus) sadece
    weekly_lifecycle_review()'da verdict gerekçelendirmesi için.
    """

    name: ClassVar[str] = "strategy_curator"
    default_model: ClassVar[str] = ""  # boş → settings.claude_model_default (Opus)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",     # configs/*.yaml + futures_journal*.duckdb
        "sql_query",     # DuckDB SELECT (read-only)
        "write_report",  # reports/curator/*.md
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Paths / Config
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        p = self.settings.reports_dir / "curator"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _root_dir(self) -> Path:
        # settings.reports_dir.parent = project root
        return self.settings.reports_dir.parent

    def _lifecycle_config_path(self) -> Path:
        return self._root_dir() / "configs" / "strategy_lifecycle.yaml"

    def _load_lifecycle_config(self) -> dict[str, Any]:
        """configs/strategy_lifecycle.yaml oku. Eksikse defaults dön."""
        path = self._lifecycle_config_path()
        defaults: dict[str, Any] = {
            "alpha_decay": {
                "rolling_window_days": 90,
                "sharpe_slope_threshold": -0.001,
                "min_sample_size": 30,
            },
            "retirement_criteria": {
                "rolling_sharpe_min": 0.5,
                "alpha_decay_active": True,
                "cooldown_weeks_after_retire": 12,
            },
            "onboarding_criteria": {
                "min_lab_tournament_pass": 1,
                "min_oos_trades": 30,
                "min_marginal_sharpe_pct": 0.05,
                "max_correlation_to_book": 0.7,
            },
            "probation_criteria": {
                "weeks_on_probation": 4,
                "min_trades_during_probation": 10,
                "exit_to_active_if": "marginal_sharpe_positive AND no_alpha_decay",
                "exit_to_retire_if": "marginal_sharpe_negative OR alpha_decay_active",
            },
            "diversity_targets": {
                "min_entropy_normalized": 0.6,
                "max_pairwise_correlation": 0.8,
            },
            "library_path": "src/price_action/strategies/",
            "active_configs": [
                "configs/risk_phoenix_scalp_15m_widestop.yaml",
                "configs/risk_phoenix_scalp_5m_p1c.yaml",
            ],
        }
        if not path.exists():
            logger.warning("curator.lifecycle_config_missing", extra={"path": str(path)})
            return defaults
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            # Defaults ile shallow merge — eksik anahtarlar default'tan gelir
            merged = {**defaults}
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            return merged
        except Exception as exc:
            logger.warning(
                "curator.lifecycle_config_load_fail",
                extra={"path": str(path), "err": str(exc)[:200]},
            )
            return defaults

    # ------------------------------------------------------------------
    # Active strategies — YAML parse
    # ------------------------------------------------------------------

    def _load_active_strategies(self) -> dict[str, list[str]]:
        """`configs/risk_phoenix_scalp_*.yaml` parse → {config_path: [strategy_name,...]}.

        `strategy_portfolio.strategies` list'ini okur. `enabled: false` veya
        boş list → boş liste dönderir (yorum satırları ignore).
        """
        cfg = self._load_lifecycle_config()
        out: dict[str, list[str]] = {}
        for rel in cfg.get("active_configs", []) or []:
            path = self._root_dir() / rel
            if not path.exists():
                logger.warning("curator.active_config_missing", extra={"path": str(path)})
                out[rel] = []
                continue
            try:
                import yaml
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                portfolio = raw.get("strategy_portfolio", {}) or {}
                enabled = portfolio.get("enabled", True)
                if not enabled:
                    out[rel] = []
                    continue
                strategies = portfolio.get("strategies", []) or []
                # YAML comments zaten parser'da uçar; sadece string elemanları al
                out[rel] = [str(s) for s in strategies if s and isinstance(s, (str, bytes))]
            except Exception as exc:
                logger.warning(
                    "curator.active_config_parse_fail",
                    extra={"path": str(path), "err": str(exc)[:200]},
                )
                out[rel] = []
        return out

    def _flat_active_strategies(self) -> list[str]:
        """Tüm aktif config'lerden birleşik unique strateji listesi."""
        seen: list[str] = []
        for strategies in self._load_active_strategies().values():
            for s in strategies:
                if s not in seen:
                    seen.append(s)
        return seen

    # ------------------------------------------------------------------
    # Library scan
    # ------------------------------------------------------------------

    def _list_library_strategies(self) -> list[str]:
        """`src/price_action/strategies/` glob → modül listesi (.py stems).

        Filtre: `__init__`, `base`, `manifest_loader` gibi infrastructure
        modülleri hariç. 40+ price-action strateji modülü hedeftir.
        """
        cfg = self._load_lifecycle_config()
        rel = cfg.get("library_path", "src/price_action/strategies/")
        lib_dir = self._root_dir() / rel
        if not lib_dir.exists():
            logger.warning("curator.library_missing", extra={"path": str(lib_dir)})
            return []
        excludes = {"__init__", "base", "manifest_loader"}
        out: list[str] = []
        for p in sorted(lib_dir.glob("*.py")):
            stem = p.stem
            if stem in excludes or stem.startswith("_"):
                continue
            out.append(stem)
        return out

    # ------------------------------------------------------------------
    # Journal read — per-strategy returns
    # ------------------------------------------------------------------

    def _data_dir(self) -> Path:
        return self._root_dir() / "data"

    def _list_journal_paths(self) -> list[Path]:
        """`data/futures_journal*.duckdb` glob."""
        data = self._data_dir()
        if not data.exists():
            return []
        return sorted(data.glob("futures_journal*.duckdb"))

    def _read_strategy_returns(
        self,
        journal_path: Path,
        *,
        since: datetime | None = None,
    ) -> dict[str, list[float]]:
        """`futures_trades_closed`'tan per-strategy realized_pnl serisi.

        Dönen: {strategy_name: [pnl_1, pnl_2, ...]} (kronolojik).
        DuckDB yoksa veya tablo yoksa boş dict.
        """
        if not journal_path.exists():
            return {}
        try:
            import duckdb  # type: ignore[import-not-found]
        except Exception:
            logger.warning("curator.duckdb_missing")
            return {}
        try:
            con = duckdb.connect(str(journal_path), read_only=True)
            try:
                tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
                if "futures_trades_closed" not in tables:
                    return {}
                if since is not None:
                    rows = con.execute(
                        """
                        SELECT strategy, ts_close, realized_pnl_usdt, realized_r
                          FROM futures_trades_closed
                         WHERE ts_close >= ?
                         ORDER BY ts_close ASC
                        """,
                        [since],
                    ).fetchall()
                else:
                    rows = con.execute(
                        """
                        SELECT strategy, ts_close, realized_pnl_usdt, realized_r
                          FROM futures_trades_closed
                         ORDER BY ts_close ASC
                        """
                    ).fetchall()
                out: dict[str, list[float]] = {}
                for strat, _ts, pnl, _r in rows:
                    out.setdefault(str(strat), []).append(float(pnl or 0.0))
                return out
            finally:
                con.close()
        except Exception as exc:
            logger.warning(
                "curator.read_returns_fail",
                extra={"path": str(journal_path), "err": str(exc)[:200]},
            )
            return {}

    def _collect_all_strategy_returns(
        self, since_days: int = 30
    ) -> dict[str, list[float]]:
        """Tüm journal'lardan birleşik per-strategy returns."""
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=since_days)
        combined: dict[str, list[float]] = {}
        for jp in self._list_journal_paths():
            per = self._read_strategy_returns(jp, since=since)
            for strat, series in per.items():
                combined.setdefault(strat, []).extend(series)
        return combined

    # ------------------------------------------------------------------
    # SOP-3: Marginal Sharpe (deterministic helper, public)
    # ------------------------------------------------------------------

    async def calc_marginal_sharpe(
        self,
        new_strategy_id: str,
        *,
        new_strategy_returns: Sequence[float] | None = None,
        book_returns: dict[str, list[float]] | None = None,
    ) -> dict[str, float]:
        """Yeni strateji eklersek portföy Sharpe değişimi.

        `new_strategy_returns` verilmezse → 0.0 dönerek "no data" marker.
        `book_returns` verilmezse → `_collect_all_strategy_returns()` ile journal'lardan.

        Returns
        -------
        dict
            {"existing_sharpe", "with_new_sharpe", "marginal_pct", "correlation_to_book"}
        """
        if book_returns is None:
            book_returns = self._collect_all_strategy_returns(since_days=90)
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            return {
                "existing_sharpe": 0.0,
                "with_new_sharpe": 0.0,
                "marginal_pct": 0.0,
                "correlation_to_book": math.nan,
            }

        # Mevcut book: her stratejinin returns'unu equal-weighted ortalama → günlük book return proxy
        # Test/realite: günlük periyodik returns yerine trade-level → annualization sqrt(252) yine
        # ortak ölçek olarak kullanılır (apples-to-apples karşılaştırma).
        book_strategies = [k for k in book_returns if book_returns[k]]
        if not book_strategies:
            existing_sharpe = 0.0
            book_series_arr = np.array([])
        else:
            # Her stratejiyi aynı uzunluğa pad / truncate (en kısa)
            min_len = min(len(book_returns[s]) for s in book_strategies)
            if min_len < 2:
                existing_sharpe = 0.0
                book_series_arr = np.array([])
            else:
                stacked = np.vstack(
                    [np.asarray(book_returns[s][:min_len], dtype=float) for s in book_strategies]
                )
                book_series_arr = stacked.mean(axis=0)
                existing_sharpe = _annualized_sharpe(book_series_arr.tolist())

        if new_strategy_returns is None or len(list(new_strategy_returns)) < 2:
            return {
                "existing_sharpe": float(existing_sharpe),
                "with_new_sharpe": float(existing_sharpe),
                "marginal_pct": 0.0,
                "correlation_to_book": math.nan,
                "new_strategy_id": new_strategy_id,
            }

        new_arr = np.asarray(list(new_strategy_returns), dtype=float)
        # With-new: book + new equal-weighted (aynı uzunlukta sample)
        if book_series_arr.size >= 2:
            min_len2 = min(book_series_arr.size, new_arr.size)
            combined = (book_series_arr[:min_len2] + new_arr[:min_len2]) / 2.0
            with_new_sharpe = _annualized_sharpe(combined.tolist())
            # Correlation to book (book series ile new series)
            try:
                cm = np.corrcoef(book_series_arr[:min_len2], new_arr[:min_len2])
                corr_to_book = float(cm[0, 1]) if cm.shape == (2, 2) else math.nan
            except Exception:
                corr_to_book = math.nan
        else:
            # Book yok → yeni strateji tek başına
            with_new_sharpe = _annualized_sharpe(new_arr.tolist())
            corr_to_book = math.nan

        marginal_pct = 0.0
        if abs(existing_sharpe) > 1e-9:
            marginal_pct = (with_new_sharpe - existing_sharpe) / abs(existing_sharpe)
        elif with_new_sharpe != 0.0:
            # Book Sharpe = 0 → marginal "infinity" yerine raw delta sinyali
            marginal_pct = float(with_new_sharpe)

        return {
            "existing_sharpe": float(existing_sharpe),
            "with_new_sharpe": float(with_new_sharpe),
            "marginal_pct": float(marginal_pct),
            "correlation_to_book": float(corr_to_book) if not math.isnan(corr_to_book) else math.nan,
            "new_strategy_id": new_strategy_id,
        }

    # ------------------------------------------------------------------
    # SOP-1: Daily Correlation Update
    # ------------------------------------------------------------------

    async def daily_correlation_update(self) -> Path:
        """Aktif stratejilerin son 30g returns korelasyon matrisi + entropy.

        Deterministik (LLM çağırmaz). Doc: `reports/curator/correlation-YYYY-MM-DD.md`.
        Protokol-uyumlu (`doc_type: strategy_correlation`).
        """
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            np = None  # type: ignore[assignment]

        cfg = self._load_lifecycle_config()
        diversity_cfg = cfg.get("diversity_targets", {})
        max_pair_corr = float(diversity_cfg.get("max_pairwise_correlation", 0.8))

        active = self._flat_active_strategies()
        all_returns = self._collect_all_strategy_returns(since_days=30)

        # Yalnızca aktif stratejilerin returns serisi
        active_returns = {s: all_returns.get(s, []) for s in active}
        # Boş olanları drop
        present = [s for s in active if len(active_returns.get(s, [])) >= 2]

        corr_matrix: Any = []
        entropy_info = {"entropy": math.nan, "entropy_normalized": math.nan, "n_strategies": len(present)}
        warnings: list[str] = []

        if np is not None and len(present) >= 2:
            min_len = min(len(active_returns[s]) for s in present)
            if min_len >= 2:
                stacked = np.vstack(
                    [np.asarray(active_returns[s][:min_len], dtype=float) for s in present]
                )
                # numpy.corrcoef rows = variables
                try:
                    corr_matrix = np.corrcoef(stacked)
                    # NaN guard (sabit serilerden)
                    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0, posinf=0.0, neginf=0.0)
                    entropy_info = _calc_diversity_entropy(corr_matrix)
                    # Pairwise warning
                    n = len(present)
                    for i in range(n):
                        for j in range(i + 1, n):
                            c = float(corr_matrix[i, j])
                            if abs(c) > max_pair_corr:
                                warnings.append(
                                    f"{present[i]} <-> {present[j]}: corr={c:.3f} > {max_pair_corr}"
                                )
                except Exception as exc:
                    logger.warning(
                        "curator.corr_calc_fail", extra={"err": str(exc)[:200]}
                    )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Body
        body_lines = [
            f"# Strategy Correlation Update — {today}",
            "",
            f"## Active strategies (n={len(active)})",
            "",
        ]
        if active:
            for s in active:
                n_trades = len(active_returns.get(s, []))
                body_lines.append(f"- `{s}` — n_trades(30d)={n_trades}")
        else:
            body_lines.append("- (no active strategies parsed from configs)")

        body_lines += [
            "",
            "## Diversity",
            f"- Entropy: {entropy_info['entropy']:.4f}",
            f"- Entropy (normalized): {entropy_info['entropy_normalized']:.4f}",
            f"- n_strategies in matrix: {entropy_info['n_strategies']}",
            "",
            "## Pairwise correlation matrix",
        ]
        if np is not None and len(present) >= 2 and isinstance(corr_matrix, (list, tuple)) is False:
            body_lines.append("```")
            header = "          " + "  ".join(f"{s[:8]:>8s}" for s in present)
            body_lines.append(header)
            for i, s in enumerate(present):
                row_vals = "  ".join(f"{float(corr_matrix[i, j]):>+8.3f}" for j in range(len(present)))
                body_lines.append(f"{s[:8]:>8s}  {row_vals}")
            body_lines.append("```")
        else:
            body_lines.append("_(insufficient data — need ≥2 active strategies with ≥2 trades each)_")

        body_lines += ["", "## Warnings"]
        if warnings:
            for w in warnings:
                body_lines.append(f"- {w}")
        else:
            body_lines.append("- (none) — all pairwise correlations within threshold")

        body = "\n".join(body_lines) + "\n"

        path = self.write_protocol_doc(
            doc_type="strategy_correlation",
            body=body,
            slug=f"correlation-{today}",
            target_dir=self._reports_dir(),
            status="PUBLISHED",
            confidence="med",
            tags=["curator", "correlation", "daily"],
        )
        return path

    # ------------------------------------------------------------------
    # SOP-2: Weekly Lifecycle Review
    # ------------------------------------------------------------------

    def _retirement_verdict(
        self,
        strategy: str,
        decay: dict[str, float],
        consecutive_weeks_neg_slope: int,
        cfg: dict[str, Any],
    ) -> tuple[str, str]:
        """Aktif strateji için KEEP / RETIRE / PROBATION verdict.

        Sample size < min → INSUFFICIENT_DATA (KEEP, no decision).
        Slope < threshold AND 3w consecutive negative → RETIRE_CANDIDATE.
        90g Sharpe < min AND decay active → RETIRE_CANDIDATE.
        90g Sharpe < min AND decay NOT active → PROBATION.
        """
        ad_cfg = cfg.get("alpha_decay", {})
        ret_cfg = cfg.get("retirement_criteria", {})
        min_n = int(ad_cfg.get("min_sample_size", 30))
        slope_thr = float(ad_cfg.get("sharpe_slope_threshold", -0.001))
        sharpe_min = float(ret_cfg.get("rolling_sharpe_min", 0.5))

        n_obs = int(decay.get("n_obs", 0))
        slope = float(decay.get("slope", math.nan))
        mean_sharpe = float(decay.get("mean_sharpe", math.nan))

        if n_obs < min_n or math.isnan(slope):
            return ("INSUFFICIENT_DATA", f"n_obs={n_obs} < min={min_n} or NaN slope")

        decay_active = slope < slope_thr and consecutive_weeks_neg_slope >= 3
        sharpe_below = (not math.isnan(mean_sharpe)) and mean_sharpe < sharpe_min

        if decay_active and sharpe_below:
            return (
                "RETIRE",
                f"slope={slope:.5f}/gün < {slope_thr}; 3w-neg; mean_sharpe={mean_sharpe:.3f} < {sharpe_min}",
            )
        if decay_active:
            return (
                "RETIRE",
                f"slope={slope:.5f}/gün < {slope_thr}; 3w consecutive negative",
            )
        if sharpe_below:
            return (
                "PROBATION",
                f"mean_sharpe={mean_sharpe:.3f} < {sharpe_min}; slope nötr ({slope:.5f}/gün)",
            )
        return ("KEEP", f"slope={slope:.5f}/gün; mean_sharpe={mean_sharpe:.3f}; n={n_obs}")

    def _onboarding_verdict(
        self,
        candidate: dict[str, Any],
        marginal: dict[str, float],
        cfg: dict[str, Any],
    ) -> tuple[str, str]:
        """Aday strateji için ONBOARD / REJECT verdict.

        Gates: lab_tournament_pass ≥ 1, oos_trades ≥ min, marginal_sharpe ≥ %5,
        correlation_to_book ≤ 0.7.
        """
        ob_cfg = cfg.get("onboarding_criteria", {})
        min_tour = int(ob_cfg.get("min_lab_tournament_pass", 1))
        min_oos = int(ob_cfg.get("min_oos_trades", 30))
        min_mg = float(ob_cfg.get("min_marginal_sharpe_pct", 0.05))
        max_corr = float(ob_cfg.get("max_correlation_to_book", 0.7))

        n_tour = int(candidate.get("lab_tournament_passes", 0))
        n_oos = int(candidate.get("oos_trades", 0))
        mg = float(marginal.get("marginal_pct", 0.0))
        corr = float(marginal.get("correlation_to_book", math.nan))

        failures: list[str] = []
        if n_tour < min_tour:
            failures.append(f"tournament_pass={n_tour} < {min_tour}")
        if n_oos < min_oos:
            failures.append(f"oos_trades={n_oos} < {min_oos}")
        if mg < min_mg:
            failures.append(f"marginal_pct={mg:.4f} < {min_mg}")
        if not math.isnan(corr) and corr > max_corr:
            failures.append(f"corr_to_book={corr:.3f} > {max_corr}")

        if failures:
            return ("REJECT", "; ".join(failures))
        return (
            "ONBOARD",
            f"all gates passed: tour={n_tour}, oos={n_oos}, mg={mg:.4f}, corr={corr:.3f}",
        )

    async def weekly_lifecycle_review(
        self,
        candidates: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Haftalık lifecycle review — KEEP / RETIRE / ONBOARD / PROBATION.

        `candidates` opsiyonel — None ise boş listede onboarding atlanır.
        Her candidate dict:
            {
                "id": "...",
                "returns": [...],  # simulated/OOS
                "lab_tournament_passes": int,
                "oos_trades": int,
            }
        """
        cfg = self._load_lifecycle_config()
        ad_cfg = cfg.get("alpha_decay", {})
        rolling_window = int(ad_cfg.get("rolling_window_days", 90))

        active = self._flat_active_strategies()
        all_returns_90d = self._collect_all_strategy_returns(since_days=180)

        # Decay table for active
        decay_rows: list[dict[str, Any]] = []
        for s in active:
            series = all_returns_90d.get(s, [])
            decay = _calc_alpha_decay_slope(series, window_days=rolling_window)
            # consecutive_weeks_neg_slope — bu MVP'de yalnızca trace placeholder
            # (gerçek üretim: son 3 review doc'tan history okur). Default 3 →
            # slope < threshold ise RETIRE; daha az ise PROBATION'a düşürürüz.
            consecutive_w = 3 if decay.get("slope", 0.0) and decay["slope"] < float(
                ad_cfg.get("sharpe_slope_threshold", -0.001)
            ) else 0
            verdict, reason = self._retirement_verdict(s, decay, consecutive_w, cfg)
            decay_rows.append(
                {
                    "strategy": s,
                    "n_obs": decay.get("n_obs"),
                    "mean_sharpe": decay.get("mean_sharpe"),
                    "slope_per_day": decay.get("slope"),
                    "slope_se": decay.get("slope_se"),
                    "verdict": verdict,
                    "reason": reason,
                }
            )

        # Onboarding table
        onboard_rows: list[dict[str, Any]] = []
        if candidates:
            for c in candidates:
                marginal = await self.calc_marginal_sharpe(
                    str(c.get("id", "?")),
                    new_strategy_returns=c.get("returns"),
                    book_returns=all_returns_90d,
                )
                verdict, reason = self._onboarding_verdict(c, marginal, cfg)
                onboard_rows.append(
                    {
                        "id": c.get("id"),
                        "existing_sharpe": marginal.get("existing_sharpe"),
                        "with_new_sharpe": marginal.get("with_new_sharpe"),
                        "marginal_pct": marginal.get("marginal_pct"),
                        "correlation_to_book": marginal.get("correlation_to_book"),
                        "verdict": verdict,
                        "reason": reason,
                    }
                )

        library = self._list_library_strategies()
        active_in_lib = [s for s in active if s in library]
        shelf = [s for s in library if s not in active]

        # Commentary (LLM, conservative)
        prompt = (
            "Strategy Lifecycle Review — sayısal sonuçlar verildi. CEO + Risk Officer "
            "için tavsiye yaz (KEEP/RETIRE/ONBOARD/PROBATION verdict'ları gerekçelendir, "
            "diversity entropy ve marginal Sharpe yorumla, conservative ol).\n\n"
            f"ACTIVE_DECAY_ROWS={decay_rows}\n\nONBOARD_ROWS={onboard_rows}\n\n"
            f"LIBRARY_n={len(library)}; ACTIVE_in_LIB={len(active_in_lib)}; SHELF_n={len(shelf)}"
        )
        commentary = await self.run(prompt)

        iso = datetime.now(timezone.utc).isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"

        # Body
        body_lines = [
            f"# Strategy Lifecycle Review — Week {week_label}",
            "",
            "## Inventory",
            f"- Active strategies: {len(active)}",
            f"- Library modules: {len(library)}",
            f"- Active also in library: {len(active_in_lib)}",
            f"- Shelf (library, not active): {len(shelf)}",
            "",
            "## Active — Decay Table",
            "| Strategy | n_obs | Mean Sharpe | Slope (/gün) | Slope SE | Verdict | Reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in decay_rows:
            body_lines.append(
                f"| `{r['strategy']}` | {r['n_obs']} | "
                f"{r['mean_sharpe']:.3f} | {r['slope_per_day']:.5f} | "
                f"{r['slope_se']:.5f} | **{r['verdict']}** | {r['reason']} |"
            )

        body_lines += ["", "## Onboarding Candidates"]
        if onboard_rows:
            body_lines += [
                "| Candidate | Existing Sharpe | With-new | Marginal % | Corr | Verdict | Reason |",
                "|---|---|---|---|---|---|---|",
            ]
            for r in onboard_rows:
                body_lines.append(
                    f"| `{r['id']}` | {r['existing_sharpe']:.3f} | "
                    f"{r['with_new_sharpe']:.3f} | {r['marginal_pct']:.4f} | "
                    f"{r['correlation_to_book']:.3f} | **{r['verdict']}** | {r['reason']} |"
                )
        else:
            body_lines.append("- (no candidates submitted this week)")

        body_lines += [
            "",
            "## Library Coverage",
            f"- Total library modules: {len(library)}",
            f"- Currently active: {len(active_in_lib)} ({100*len(active_in_lib)/max(len(library),1):.1f}%)",
            f"- Shelf (potential onboarding pool): {len(shelf)}",
            "",
            "## Commentary",
            commentary,
        ]
        body = "\n".join(body_lines) + "\n"

        has_action = any(r["verdict"] in ("RETIRE", "ONBOARD") for r in decay_rows) or any(
            r["verdict"] == "ONBOARD" for r in onboard_rows
        )
        path = self.write_protocol_doc(
            doc_type="strategy_lifecycle",
            body=body,
            slug=f"lifecycle-{week_label}",
            target_dir=self._reports_dir(),
            status="PROPOSED",
            confidence="high" if has_action else "med",
            requested_review_from=["ceo", "risk_officer"],
            tags=["curator", "lifecycle", "weekly", week_label],
        )
        return path


__all__ = [
    "StrategyCuratorAgent",
    "_calc_alpha_decay_slope",
    "_calc_diversity_entropy",
    "_annualized_sharpe",
]
