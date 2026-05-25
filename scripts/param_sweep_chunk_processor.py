#!/usr/bin/env python
"""Faz 7 — Saatlik chunk processor.

Cron: `35 * * * *` — her saat `chunk_size` cell'i işler.

State machine:
    {strategy: 'vsa_climax_test', cell_offset: 25, total_cells: 80}

Akış:
1. configs/param_sweep_chunks.yaml + param_sweep_grids.yaml oku.
2. State file'dan (strategy, offset) al — yoksa rotation[0], offset=0.
3. Stratejinin pool'unu yükle, grid'ten [offset : offset+chunk_size] cell al.
4. Her cell için metric hesapla (param_sweep_runner.apply_cell kullan).
5. Sonuçları reports/param_sweep/chunks/<date>-<strategy>-<offset>.jsonl'a append.
6. Offset'i ilerlet; strateji bitince rotation'da sıradakine geç.
7. Haftalık summarize: --summarize flag ile son N gün chunks'tan top-5 derle.

CLI:
    .venv/bin/python scripts/param_sweep_chunk_processor.py            # tek chunk
    .venv/bin/python scripts/param_sweep_chunk_processor.py --summarize
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

# Make sibling import work when invoked as script.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from param_sweep_runner import (  # noqa: E402
    apply_cell,
    build_regime_series,
    iter_grid,
    load_pool,
)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state(state_file: Path) -> dict[str, Any]:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


def advance_state(
    state: dict[str, Any],
    rotation: list[str],
    chunk_size: int,
    total_per_strategy: int,
) -> dict[str, Any]:
    """Move cell_offset forward; rotate strategy if exhausted."""
    cur_strat = state.get("strategy") or rotation[0]
    offset = int(state.get("cell_offset", 0))
    new_offset = offset + chunk_size
    if new_offset >= total_per_strategy:
        # next strategy in rotation
        try:
            idx = rotation.index(cur_strat)
        except ValueError:
            idx = -1
        next_strat = rotation[(idx + 1) % len(rotation)]
        return {
            "strategy": next_strat,
            "cell_offset": 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "previous_strategy": cur_strat,
        }
    return {
        "strategy": cur_strat,
        "cell_offset": new_offset,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Chunk execution
# ---------------------------------------------------------------------------

def process_chunk(
    chunks_cfg: dict[str, Any],
    grids_cfg: dict[str, Any],
    chunks_dir: Path,
) -> dict[str, Any]:
    state_file = Path(chunks_cfg["chunk_state_file"])
    chunk_size = int(chunks_cfg.get("chunk_size", 5))
    rotation = list(chunks_cfg.get("strategies_in_rotation", []))
    if not rotation:
        raise ValueError("strategies_in_rotation is empty in chunks config")

    state = load_state(state_file)
    strategy = state.get("strategy") or rotation[0]
    offset = int(state.get("cell_offset", 0))

    per_strat = (grids_cfg.get("per_strategy") or {}).get(strategy, {}) or {}
    default_grid = dict(grids_cfg.get("default_grid", {}))
    if "grid" in per_strat:
        default_grid.update(per_strat["grid"])
    pool_path = Path(per_strat.get("pool", "data/sec53_5m_pool_v11_vm20.pkl"))
    sl_pct_base = float(per_strat.get("sl_pct_min", 0.025))
    drop_strategies = per_strat.get("drop_strategies") or []

    all_cells = iter_grid(default_grid)
    total = len(all_cells)
    chunk = all_cells[offset : offset + chunk_size]

    df = load_pool(pool_path)
    df_strat = df[df["strategy"] == strategy].copy()
    if drop_strategies:
        df_strat = df_strat[~df_strat["strategy"].isin(drop_strategies)]
    regime_series = None
    if (grids_cfg.get("regime_split") or {}).get("enabled", True):
        regime_series = build_regime_series(df)

    results = []
    for params in chunk:
        m = apply_cell(
            df_strat,
            sl_multiplier=float(params["sl_multiplier"]),
            tp_r=float(params["tp_r"]),
            risk_pct=float(params["risk_pct"]),
            sl_pct_base=sl_pct_base,
            regime_series=regime_series,
        )
        row = m.to_row()
        row["strategy"] = strategy
        row["pool"] = str(pool_path)
        row["processed_at"] = datetime.now(timezone.utc).isoformat()
        results.append(row)

    # Append to JSONL — file naming: <date>-<strategy>-<offset>.jsonl
    chunks_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).date().isoformat()
    out_path = chunks_dir / f"{date_str}-{strategy}-offset{offset:03d}.jsonl"
    with out_path.open("a") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")

    new_state = advance_state(state, rotation, chunk_size, total)
    save_state(state_file, new_state)

    return {
        "strategy": strategy,
        "offset": offset,
        "chunk_size": len(chunk),
        "total_cells": total,
        "output": str(out_path),
        "new_state": new_state,
        "n_results": len(results),
    }


# ---------------------------------------------------------------------------
# Weekly summarize
# ---------------------------------------------------------------------------

def summarize_weekly(
    chunks_cfg: dict[str, Any],
    chunks_dir: Path,
    weekly_dir: Path,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Read chunks from last N days, pick top-5 per strategy by sharpe_like."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    if not chunks_dir.exists():
        return {"n_rows": 0, "output": None}
    for jf in chunks_dir.glob("*.jsonl"):
        # Parse date from filename: YYYY-MM-DD-...
        try:
            date_part = "-".join(jf.stem.split("-")[:3])
            file_date = datetime.fromisoformat(date_part).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            file_date = cutoff  # include if undetermined
        if file_date < cutoff:
            continue
        for line in jf.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not rows:
        return {"n_rows": 0, "output": None}

    # Group by strategy, top 5 by sharpe_like (eligible n>=30).
    weekly_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).date().isoformat()
    out_path = weekly_dir / f"weekly-{date_str}.md"

    by_strat: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        s = r.get("strategy", "unknown")
        by_strat.setdefault(s, []).append(r)

    lines = [f"# Param Sweep — Weekly Summary ({date_str})", ""]
    lines.append(f"_Lookback: {lookback_days} days; rows: {len(rows)}_")
    lines.append("")
    for strategy, items in by_strat.items():
        eligible = [x for x in items if int(x.get("n_trades", 0)) >= 30]
        eligible.sort(key=lambda x: float(x.get("sharpe_like", 0)), reverse=True)
        top = eligible[:5]
        lines.append(f"## {strategy}  ({len(eligible)} eligible / {len(items)} total)")
        lines.append("")
        lines.append("| sl_mult | tp_r | risk_pct | n | win% | mean_R | sharpe_like |")
        lines.append("|---------|------|----------|---|------|--------|-------------|")
        for t in top:
            lines.append(
                f"| {t.get('sl_multiplier')} | {t.get('tp_r')} | "
                f"{t.get('risk_pct')} | {t.get('n_trades')} | "
                f"{float(t.get('win_rate', 0)) * 100:.2f} | "
                f"{float(t.get('mean_R', 0)):.3f} | "
                f"{float(t.get('sharpe_like', 0)):.3f} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines))
    return {"n_rows": len(rows), "output": str(out_path), "strategies": list(by_strat.keys())}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Param sweep chunk processor")
    p.add_argument("--chunks-yaml", type=Path,
                   default=Path("configs/param_sweep_chunks.yaml"))
    p.add_argument("--grids-yaml", type=Path,
                   default=Path("configs/param_sweep_grids.yaml"))
    p.add_argument("--summarize", action="store_true",
                   help="Run weekly summarize instead of a chunk.")
    args = p.parse_args(argv)

    chunks_cfg = yaml.safe_load(args.chunks_yaml.read_text()) or {}
    grids_cfg = yaml.safe_load(args.grids_yaml.read_text()) or {}
    chunks_dir = Path(chunks_cfg.get("chunks_dir", "reports/param_sweep/chunks"))
    weekly_dir = Path(chunks_cfg.get("weekly_summary_dir", "reports/param_sweep/weekly"))

    if args.summarize:
        result = summarize_weekly(
            chunks_cfg, chunks_dir, weekly_dir,
            lookback_days=int(chunks_cfg.get("weekly_lookback_days", 7)),
        )
    else:
        result = process_chunk(chunks_cfg, grids_cfg, chunks_dir)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
