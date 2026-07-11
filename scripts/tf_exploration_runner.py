"""TF Exploration Pipeline — Faz 10.

Verilen strateji için tüm TF'lerde pool'dan subset alır, per-TF metrik
hesaplar (n_trades/yr, mean_R, Sharpe-like, MaxDD, recovery), composite
score'a göre rank eder ve best TF + deploy önerisi çıkarır.

Pool dosyası bulunamayan TF'ler "NO_POOL_DATA" olarak işaretlenir
(Faz 10.2 backlog).

Usage:
    .venv/bin/python scripts/tf_exploration_runner.py \\
        --strategy vsa_climax_test \\
        --output reports/tf_exploration/vsa-2026-05-25.md

Spec (Faz 10):
    - Pool subset (drop_strategies hariç)
    - Per-TF metrics: n_trades/yr, mean_R, sum_R, Sharpe-like, MaxDD, WR, recovery
    - Composite score (configs/tf_expansion_targets.yaml ağırlıkları)
    - Ortak sembol + ortak tarih penceresinde adil TF karşılaştırması
    - Best TF + research recommendation (CANDIDATE / STAY / NEEDS_MORE_DATA)
"""
from __future__ import annotations

import argparse
import math
import pickle
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


# Default TF expansion config — eğer dosya yoksa fallback olarak kullanılır.
_DEFAULT_TF_CONFIG = ROOT / "configs" / "tf_expansion_targets.yaml"

# Default candidate pool path map. Sadece var olan dosyalar yüklenir;
# diğerleri NO_POOL_DATA olur.
_DEFAULT_POOL_MAP = {
    "1m": ROOT / "data" / "sec53_1m_pool_v11.pkl",
    "5m": ROOT / "data" / "sec53_5m_pool_v11_vm20.pkl",
    "15m": ROOT / "data" / "sec53_15m_pool_v11.pkl",
    "30m": ROOT / "data" / "sec53_30m_pool_v11.pkl",
    "1h": ROOT / "data" / "sec53_1h_pool_v11.pkl",
    "4h": ROOT / "data" / "sec53_4h_pool_v11.pkl",
    "1d": ROOT / "data" / "sec53_1d_pool_v11.pkl",
}


# ---------------------------------------------------------------------------
# Pool helpers
# ---------------------------------------------------------------------------
def _to_utc(ts) -> datetime:
    """UTC-aware datetime'a normalize et."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    # pandas.Timestamp gibi nesneler
    if hasattr(ts, "to_pydatetime"):
        return _to_utc(ts.to_pydatetime())
    raise TypeError(f"Cannot normalize ts: {type(ts)}")


def load_pool(path: Path) -> list[dict]:
    """sec53_<tf>_pool_v11_*.pkl yükle."""
    with path.open("rb") as f:
        pool = pickle.load(f)
    if not isinstance(pool, list):
        raise TypeError(f"Pool must be list, got {type(pool)}")
    return pool


def filter_strategy_subset(
    pool: list[dict],
    strategy: str,
    drop_strategies: Iterable[str] = (),
) -> list[dict]:
    """drop_strategies hariç tutarak strategy match'leyen trade'leri döner."""
    drop = set(drop_strategies)
    return [
        t for t in pool
        if t.get("strategy") == strategy and t.get("strategy") not in drop
    ]


def align_common_comparison_sample(
    subsets: dict[str, list[dict]],
) -> tuple[dict[str, list[dict]], dict]:
    """Align TF samples to one symbol universe and entry-time window.

    Pool builders are not guaranteed to cover the same symbols or dates.  A
    rank across unmatched pools rewards the larger/newer pool rather than the
    timeframe.  Every comparable TF is therefore restricted to the symbol
    intersection and the overlapping entry-time interval.  Malformed research
    rows fail closed instead of being converted to zero-return observations.
    """
    if not subsets:
        raise ValueError("no strategy samples available for comparison")

    prepared: dict[str, list[tuple[dict, str, datetime]]] = {}
    symbol_sets: list[set[str]] = []
    for tf, trades in subsets.items():
        if not trades:
            raise ValueError(f"{tf}: empty strategy sample")
        rows: list[tuple[dict, str, datetime]] = []
        symbols: set[str] = set()
        for index, trade in enumerate(trades):
            if not isinstance(trade, dict):
                raise ValueError(f"{tf}: non-dict trade at index {index}")
            symbol = trade.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError(f"{tf}: invalid symbol at index {index}")
            if "entry_ts" not in trade:
                raise ValueError(f"{tf}: missing entry_ts at index {index}")
            try:
                entry_ts = _to_utc(trade["entry_ts"])
                r_value = float(trade["R"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{tf}: malformed trade at index {index}: {exc}") from exc
            if not math.isfinite(r_value):
                raise ValueError(f"{tf}: non-finite R at index {index}")
            clean_symbol = symbol.strip()
            rows.append((trade, clean_symbol, entry_ts))
            symbols.add(clean_symbol)
        prepared[tf] = rows
        symbol_sets.append(symbols)

    common_symbols = set.intersection(*symbol_sets)
    if not common_symbols:
        raise ValueError("TF samples have no common symbols")

    common_rows: dict[str, list[tuple[dict, str, datetime]]] = {
        tf: [row for row in rows if row[1] in common_symbols]
        for tf, rows in prepared.items()
    }
    if any(not rows for rows in common_rows.values()):
        raise ValueError("at least one TF has no rows in the common symbol universe")

    comparison_start = max(min(row[2] for row in rows) for rows in common_rows.values())
    comparison_end = min(max(row[2] for row in rows) for rows in common_rows.values())
    if comparison_start > comparison_end:
        raise ValueError("TF samples have no overlapping entry-time window")

    aligned: dict[str, list[dict]] = {}
    counts: dict[str, dict[str, int]] = {}
    for tf, rows in common_rows.items():
        selected = [row[0] for row in rows if comparison_start <= row[2] <= comparison_end]
        if not selected:
            raise ValueError(f"{tf}: no trades remain after common-sample alignment")
        aligned[tf] = selected
        counts[tf] = {
            "raw_strategy_trades": len(subsets[tf]),
            "common_symbol_trades": len(rows),
            "aligned_trades": len(selected),
        }

    provenance = {
        "method": "symbol_intersection_and_overlapping_entry_window",
        "common_symbols": sorted(common_symbols),
        "n_common_symbols": len(common_symbols),
        "entry_start": comparison_start.isoformat(),
        "entry_end": comparison_end.isoformat(),
        "counts": counts,
    }
    return aligned, provenance


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def calc_tf_metrics(trades: list[dict]) -> dict:
    """Trade listesinden per-TF özet metrikler.

    Returns:
        dict with keys:
            n_trades, n_trades_per_year, mean_R, sum_R, sharpe,
            maxdd_R, recovery_factor, win_rate, span_days
    """
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "n_trades_per_year": 0.0,
            "mean_R": 0.0,
            "sum_R": 0.0,
            "sharpe": 0.0,
            "maxdd_R": 0.0,
            "recovery_factor": 0.0,
            "win_rate": 0.0,
            "span_days": 0.0,
        }

    rs = [float(t.get("R", 0.0)) for t in trades]
    sum_r = sum(rs)
    mean_r = sum_r / n
    # std (sample, ddof=1) — küçük n'de NaN olabilir, guard et.
    if n > 1:
        var = sum((r - mean_r) ** 2 for r in rs) / (n - 1)
        std_r = math.sqrt(var)
    else:
        std_r = 0.0
    # Trade-based "Sharpe-like": mean / std × sqrt(n_trades). Annualize
    # için ayrı n/yr metriği var. Burada birim trade-based ratio.
    sharpe = (mean_r / std_r * math.sqrt(n)) if std_r > 0 else 0.0

    # MaxDD R cinsinden — kümülatif R serisindeki en büyük peak-to-trough.
    sorted_trades = sorted(trades, key=lambda t: _to_utc(t["entry_ts"]))
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for t in sorted_trades:
        eq += float(t.get("R", 0.0))
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > maxdd:
            maxdd = dd

    # Recovery factor = sum_R / maxdd (Calmar-like, R cinsinden).
    recovery = (sum_r / maxdd) if maxdd > 0 else (sum_r if sum_r > 0 else 0.0)

    # Win rate
    n_win = sum(1 for r in rs if r > 0)
    win_rate = n_win / n

    # n/yr — span'den hesapla.
    t0 = _to_utc(sorted_trades[0]["entry_ts"])
    t1 = _to_utc(sorted_trades[-1]["entry_ts"])
    span_days = max((t1 - t0).total_seconds() / 86400.0, 1.0)
    span_years = span_days / 365.25
    n_per_year = n / span_years if span_years > 0 else 0.0

    return {
        "n_trades": n,
        "n_trades_per_year": n_per_year,
        "mean_R": mean_r,
        "sum_R": sum_r,
        "sharpe": sharpe,
        "maxdd_R": maxdd,
        "recovery_factor": recovery,
        "win_rate": win_rate,
        "span_days": span_days,
    }


def _normalize_for_score(metrics_list: list[dict]) -> list[dict]:
    """Composite score için her metriği 0-1 normalize et."""
    # Sadece METRICS_VALID olan kayıtlar normalize edilir.
    valid = [m for m in metrics_list if m.get("status") == "OK"]
    if not valid:
        return metrics_list

    def _maxabs(key: str) -> float:
        vals = [abs(m["metrics"].get(key, 0.0)) for m in valid]
        return max(vals) if vals else 1.0

    sharpe_max = _maxabs("sharpe") or 1.0
    nyr_max = _maxabs("n_trades_per_year") or 1.0
    rec_max = _maxabs("recovery_factor") or 1.0
    # maxdd için inverse — küçük DD iyi.
    dd_max = _maxabs("maxdd_R") or 1.0

    for m in metrics_list:
        if m.get("status") != "OK":
            m["normalized"] = None
            continue
        met = m["metrics"]
        m["normalized"] = {
            "sharpe": max(0.0, met["sharpe"] / sharpe_max) if sharpe_max > 0 else 0.0,
            "n_trades_per_year": (met["n_trades_per_year"] / nyr_max) if nyr_max > 0 else 0.0,
            "recovery_factor": max(0.0, met["recovery_factor"] / rec_max) if rec_max > 0 else 0.0,
            # inverse: 1 - (dd / max_dd) → küçük dd → büyük puan
            "maxdd_inverse": max(0.0, 1.0 - (met["maxdd_R"] / dd_max)) if dd_max > 0 else 1.0,
        }
    return metrics_list


def composite_score(normalized: dict, weights: dict) -> float:
    """Ağırlıklı normalize skor → 0..1 ölçek."""
    if normalized is None:
        return 0.0
    return (
        weights.get("sharpe", 0.40) * normalized.get("sharpe", 0.0)
        + weights.get("n_trades_per_year", 0.20) * normalized.get("n_trades_per_year", 0.0)
        + weights.get("recovery_factor", 0.20) * normalized.get("recovery_factor", 0.0)
        + weights.get("maxdd_inverse", 0.20) * normalized.get("maxdd_inverse", 0.0)
    )


# ---------------------------------------------------------------------------
# Main exploration entry
# ---------------------------------------------------------------------------
def explore_tf(
    strategy: str,
    tf_list: list[str],
    pool_paths: dict[str, Path],
    *,
    drop_strategies: Iterable[str] = (),
    config_path: Path | None = None,
) -> dict:
    """Strateji için verilen TF'lerde fizibilite analizi.

    Args:
        strategy: 'vsa_climax_test' vb.
        tf_list: ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
        pool_paths: {'5m': Path(...), '15m': Path(...), ...}
        drop_strategies: Pool'dan çıkarılacak strateji listesi.
        config_path: configs/tf_expansion_targets.yaml — composite weights +
            deploy thresholds. None ise default lokasyona bakar.

    Returns:
        {
            'strategy': str,
            'tf_results': {tf: {status, metrics, normalized, composite, rank}},
            'best_tf': str | None,
            'recommendation': str,  # CANDIDATE <tf> | STAY | NEEDS_MORE_DATA
        }
    """
    config = _load_config(config_path)
    weights = config.get("composite_score", {}).get("weights", {})
    thresholds = config.get("deploy_thresholds", {})

    tf_results: dict[str, dict] = {}
    raw_subsets: dict[str, list[dict]] = {}
    for tf in tf_list:
        path = pool_paths.get(tf)
        if path is None or not Path(path).exists():
            tf_results[tf] = {
                "status": "NO_POOL_DATA",
                "metrics": None,
                "normalized": None,
                "composite": 0.0,
                "rank": None,
                "pool_path": str(path) if path else None,
            }
            continue

        try:
            pool = load_pool(Path(path))
            subset = filter_strategy_subset(pool, strategy, drop_strategies)
            if not subset:
                tf_results[tf] = {
                    "status": "NO_TRADES_FOR_STRATEGY",
                    "metrics": None,
                    "normalized": None,
                    "composite": 0.0,
                    "rank": None,
                    "pool_path": str(path),
                }
                continue
            raw_subsets[tf] = subset
            tf_results[tf] = {
                "status": "OK",
                "metrics": None,
                "normalized": None,  # _normalize_for_score doldurur
                "composite": 0.0,
                "rank": None,
                "pool_path": str(path),
            }
        except Exception as e:
            tf_results[tf] = {
                "status": f"ERROR: {e!s}",
                "metrics": None,
                "normalized": None,
                "composite": 0.0,
                "rank": None,
                "pool_path": str(path),
            }

    comparison: dict | None = None
    if raw_subsets:
        try:
            aligned_subsets, comparison = align_common_comparison_sample(raw_subsets)
        except (TypeError, ValueError) as exc:
            error = f"ERROR: unsafe comparison sample: {exc}"
            for tf in raw_subsets:
                tf_results[tf]["status"] = error
        else:
            for tf, subset in aligned_subsets.items():
                tf_results[tf]["metrics"] = calc_tf_metrics(subset)
                tf_results[tf]["sample"] = comparison["counts"][tf]

    # Composite + rank
    flat = [{"tf": tf, **info} for tf, info in tf_results.items()]
    _normalize_for_score(flat)
    for entry in flat:
        if entry["status"] == "OK":
            entry["composite"] = composite_score(entry.get("normalized"), weights)
        tf_results[entry["tf"]] = {k: v for k, v in entry.items() if k != "tf"}

    # Rank by composite (yüksek → iyi). Sadece OK olanlar rank alır.
    ok_entries = [
        (tf, info) for tf, info in tf_results.items() if info["status"] == "OK"
    ]
    ok_entries.sort(key=lambda kv: kv[1]["composite"], reverse=True)
    for idx, (tf, _info) in enumerate(ok_entries, start=1):
        tf_results[tf]["rank"] = idx

    # Recommendation
    best_tf = ok_entries[0][0] if ok_entries else None
    recommendation = _build_recommendation(
        best_tf,
        tf_results,
        thresholds,
    )

    return {
        "strategy": strategy,
        "tf_results": tf_results,
        "best_tf": best_tf,
        "recommendation": recommendation,
        "weights": weights,
        "thresholds": thresholds,
        "comparison_sample": comparison,
    }


def _build_recommendation(
    best_tf: str | None,
    tf_results: dict,
    thresholds: dict,
) -> str:
    """Ham TF ekranından güvenli aday önerisi üret.

    Bu katman IS/OOS, walk-forward, shuffle, symbol-out veya adversarial
    kapıları çalıştırmaz. Bu nedenle hiçbir sonuç doğrudan ``DEPLOY`` olamaz;
    eşikleri geçen yeni TF yalnızca robustness hattına ``CANDIDATE`` olur.
    """
    if best_tf is None:
        return "NEEDS_MORE_DATA: hiçbir TF için pool yok ya da geçerli trade bulunamadı."

    best_score = tf_results[best_tf]["composite"]
    composite_min = float(thresholds.get("composite_min", 0.70))
    baseline_tf = str(thresholds.get("baseline_tf", "15m"))
    min_gain = float(thresholds.get("vs_baseline_min_gain_pct", 0.10))
    baseline = tf_results.get(baseline_tf, {})

    if best_tf != baseline_tf and baseline.get("status") != "OK":
        return (
            f"NEEDS_MORE_DATA: güvenli aday karşılaştırması için {baseline_tf} "
            "baseline pool'u ve ortak örneklem gerekli."
        )

    if best_score < composite_min:
        return (
            f"STAY: best TF '{best_tf}' composite {best_score:.3f} < "
            f"threshold {composite_min:.2f}. Mevcut TF'leri koru."
        )

    if best_tf == baseline_tf:
        return (
            f"STAY {best_tf}: best TF zaten aktif (composite {best_score:.3f})."
        )

    baseline_score = float(baseline.get("composite", 0.0))
    if baseline_score > 0:
        gain = (best_score - baseline_score) / baseline_score
        if gain < min_gain:
            return (
                f"STAY {baseline_tf}: '{best_tf}' composite kazancı {gain:.1%} < "
                f"gerekli {min_gain:.1%}."
            )
    else:
        gain = float("inf")

    comparison = (
        f"; {baseline_tf} baseline'a göre kazanç {gain:.1%}"
        if gain is not None and math.isfinite(gain)
        else "; baseline karşılaştırması yok"
    )
    return (
        f"CANDIDATE {best_tf}: ham composite {best_score:.3f} >= "
        f"{composite_min:.2f}{comparison}. IS/OOS + walk-forward + shuffle + "
        "symbol-out + adversarial kapıları geçmeden deploy ETME."
    )


def _load_config(config_path: Path | None) -> dict:
    path = config_path or _DEFAULT_TF_CONFIG
    if not path.exists():
        # Fallback defaults
        return {
            "composite_score": {
                "weights": {
                    "sharpe": 0.40,
                    "maxdd_inverse": 0.20,
                    "n_trades_per_year": 0.20,
                    "recovery_factor": 0.20,
                }
            },
            "deploy_thresholds": {
                "composite_min": 0.70,
                "baseline_tf": "15m",
                "vs_baseline_min_gain_pct": 0.10,
            },
        }
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def render_markdown(result: dict) -> str:
    lines: list[str] = []
    w = lines.append
    strategy = result["strategy"]
    weights = result.get("weights", {})
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    w(f"# TF Exploration Report — `{strategy}`")
    w("")
    w(f"**Date:** {today}")
    w(f"**Best TF:** {result.get('best_tf') or 'N/A'}")
    w(f"**Recommendation:** {result['recommendation']}")
    w("")

    comparison = result.get("comparison_sample")
    if comparison:
        w("## Fair Comparison Sample")
        w("")
        w(
            f"- Common universe: {comparison['n_common_symbols']} symbols "
            f"(`{', '.join(comparison['common_symbols'])}`)"
        )
        w(f"- Entry window: `{comparison['entry_start']}` → `{comparison['entry_end']}`")
        w("- Method: symbol intersection + overlapping entry-time window (fail closed).")
        w("")

    w("## Composite Score Weights")
    w("")
    w("| Metric | Weight |")
    w("|---|---|")
    for k, v in (weights or {}).items():
        w(f"| {k} | {v:.2f} |")
    w("")
    w("Composite = ağırlıklı normalize skor (0..1). Her metrik kendi en büyük")
    w("değerine bölünerek 0..1 ölçeğine indirgenir, MaxDD ters (küçük iyi).")
    w("")

    w("## TF Rank Table")
    w("")
    w("| Rank | TF | Status | n_trades | n/yr | mean_R | Sharpe-like | MaxDD (R) | Recovery | WR | Composite |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")

    tf_order_by_rank = sorted(
        result["tf_results"].items(),
        key=lambda kv: (kv[1]["rank"] is None, kv[1]["rank"] or 999),
    )
    for tf, info in tf_order_by_rank:
        if info["status"] == "OK":
            m = info["metrics"]
            w(
                f"| {info['rank']} | {tf} | OK | {m['n_trades']:,} | "
                f"{m['n_trades_per_year']:.0f} | {m['mean_R']:+.3f} | "
                f"{m['sharpe']:.2f} | {m['maxdd_R']:.1f} | "
                f"{m['recovery_factor']:.2f} | {m['win_rate']*100:.1f}% | "
                f"{info['composite']:.3f} |"
            )
        else:
            w(f"| - | {tf} | {info['status']} | - | - | - | - | - | - | - | - |")

    w("")
    w("## Notes")
    w("")
    w("- `NO_POOL_DATA` TF'leri config'deki uygun pool builder ile doldurulacak.")
    w("- Rank tablosundaki bütün OK TF'ler aynı sembol kesişimi ve aynı giriş")
    w("  tarih penceresiyle hesaplanır; ham pool büyüklüğü skoru şişiremez.")
    w("- `Sharpe-like` = mean_R / std_R × sqrt(n_trades). Annual değil — trade")
    w("  ölçekli karşılaştırma için. Annualize için n/yr ayrı kolonda.")
    w("- `Recovery` = sum_R / maxdd_R. Calmar benzeri, R cinsinden.")
    w("- Composite skor `composite_min` ve baseline-gain eşiklerini aşarsa")
    w("  yalnızca `CANDIDATE <tf>` çıkar; robustness kapıları olmadan deploy edilmez.")
    w("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TF Exploration Pipeline (Faz 10)")
    p.add_argument("--strategy", required=True, help="Örn: vsa_climax_test")
    p.add_argument(
        "--tfs",
        default="1m,5m,15m,30m,1h,4h,1d",
        help="Virgüllü TF listesi (default: tüm hedef TF'ler).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown çıktı yolu. Verilmezse stdout'a basar.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="tf_expansion_targets.yaml — opsiyonel (default lokasyon kullanılır).",
    )
    p.add_argument(
        "--drop",
        default="",
        help="Virgüllü drop_strategies listesi (örn: engulfing_continuation).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    tf_list = [t.strip() for t in args.tfs.split(",") if t.strip()]
    drop = [d.strip() for d in args.drop.split(",") if d.strip()]

    # Pool path map: config'den oku, yoksa default kullan.
    config = _load_config(args.config)
    target_tfs = config.get("target_tfs", [])
    pool_paths: dict[str, Path] = {}
    for entry in target_tfs:
        tf = entry.get("tf")
        pool_rel = entry.get("pool")
        if tf and pool_rel:
            p = Path(pool_rel)
            if not p.is_absolute():
                p = ROOT / p
            pool_paths[tf] = p
    # Eksik TF'leri default'tan tamamla.
    for tf, p in _DEFAULT_POOL_MAP.items():
        pool_paths.setdefault(tf, p)

    result = explore_tf(
        strategy=args.strategy,
        tf_list=tf_list,
        pool_paths=pool_paths,
        drop_strategies=drop,
        config_path=args.config,
    )

    md = render_markdown(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding="utf-8")
        print(f"[OK] Report yazıldı: {args.output}")
    else:
        sys.stdout.write(md)

    print(f"[SUMMARY] strategy={args.strategy} best_tf={result['best_tf']}")
    print(f"[SUMMARY] recommendation={result['recommendation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
