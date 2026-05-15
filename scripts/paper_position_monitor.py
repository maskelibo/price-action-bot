"""Paper Position Monitor — açık pozisyonları takip + SL/TP hit detect + close.

Pozisyon yaşam döngüsü engine.py'daki multi-target logic'i ile aynı:
- TP1 (1R) hit: partial close %30
- TP2 (1.5R) hit: partial close %30
- Stage >= 2: trailing aktif (1.5 ATR), force-exit 30 bar sonra
- SL hit: tüm kapat (BE'ye çekilmiş ise BE)
- PYRAMID: 1R hit → ek %50 pos, 2R hit → ek %30 pos (BE SL)

Usage:
    python scripts/paper_position_monitor.py          # bir kez çalıştır (cron için)
    python scripts/paper_position_monitor.py --loop   # her 5 dakikada bir döngü
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.paper_state import PaperState

# Multi-bot support (ATLAS / PHOENIX paralel paper test)
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower()
if _BOT_NAME == "atlas":
    JOURNAL = ROOT / "data" / "paper_journal_atlas.duckdb"
    STATE_PATH = ROOT / "logs" / "execution" / "paper_state_atlas.json"
elif _BOT_NAME == "phoenix":
    JOURNAL = ROOT / "data" / "paper_journal_phoenix.duckdb"
    STATE_PATH = ROOT / "logs" / "execution" / "paper_state_phoenix.json"
else:
    JOURNAL = ROOT / "data" / "paper_journal.duckdb"
    STATE_PATH = ROOT / "logs" / "execution" / "paper_state.json"

# v2.0.3 production config
TP1_R = 1.0
TP2_R = 1.5
TP1_CLOSE_PCT = 0.30
TP2_CLOSE_PCT = 0.30
RUNNER_TRAIL_MULT = 1.5
RUNNER_FORCE_EXIT_BARS = 30
PYRAMID_TRIGGERS = [1.0, 2.0]
PYRAMID_SIZES = [0.50, 0.30]
SLIPPAGE_BPS = 5.0


def init_journal_extras():
    """Position lifecycle tabloları."""
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_position_events (
            event_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            position_id VARCHAR,
            symbol VARCHAR,
            event_type VARCHAR,  -- 'tp1_hit', 'tp2_hit', 'sl_hit', 'pyramid_add_1', 'pyramid_add_2', 'trail_force_exit', 'closed'
            price DOUBLE,
            qty_affected DOUBLE,
            realized_R DOUBLE,
            realized_pnl_usdt DOUBLE,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_position_stages (
            position_id VARCHAR PRIMARY KEY,
            stage INTEGER,                   -- 0=fresh, 1=after TP1, 2=after TP2 runner
            initial_qty DOUBLE,
            initial_R_dist DOUBLE,
            atr_for_trail DOUBLE,
            tp1_price DOUBLE,
            tp2_price DOUBLE,
            current_sl DOUBLE,
            peak_price DOUBLE,
            trail_active_bar INTEGER,        -- bar index when trail activated
            pyramid_added_1 BOOLEAN,
            pyramid_added_2 BOOLEAN,
            bars_since_open INTEGER
        )
    """)
    con.commit()
    con.close()


def load_paper_state() -> dict:
    if not STATE_PATH.exists():
        return {"balances": {"USDT": 10000.0}, "positions": [], "realized_pnl_total": 0.0}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_paper_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def fetch_current_bar(symbol: str) -> dict | None:
    """Binance public API son 1d bar (SPOT, futures değil)."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        ohlcv = ex.fetch_ohlcv(symbol, '1d', limit=2)
        if not ohlcv or len(ohlcv) < 1:
            return None
        latest = ohlcv[-1]  # son bar (current ya da bugun)
        return {
            'ts': pd.Timestamp(latest[0], unit='ms', tz='UTC'),
            'open': float(latest[1]),
            'high': float(latest[2]),
            'low': float(latest[3]),
            'close': float(latest[4]),
            'volume': float(latest[5]),
        }
    except Exception as e:
        print(f"  [WARN] {symbol} fetch fail: {e}")
        return None


def get_stage(position_id: str) -> dict:
    """Pozisyon stage state."""
    con = duckdb.connect(str(JOURNAL))
    r = con.execute(
        "SELECT * FROM paper_position_stages WHERE position_id=?",
        [position_id]
    ).fetchone()
    con.close()
    if r is None:
        return None
    cols = ['position_id', 'stage', 'initial_qty', 'initial_R_dist', 'atr_for_trail',
            'tp1_price', 'tp2_price', 'current_sl', 'peak_price', 'trail_active_bar',
            'pyramid_added_1', 'pyramid_added_2', 'bars_since_open']
    return dict(zip(cols, r))


def init_stage(p: dict) -> dict:
    """Yeni pozisyon için stage state init."""
    side = p['side']
    entry = float(p['entry_price'])
    sl = float(p['sl_price'])
    initial_R_dist = abs(entry - sl)
    atr_for_trail = initial_R_dist * 0.5  # approx
    if side == "long":
        tp1 = entry + TP1_R * initial_R_dist
        tp2 = entry + TP2_R * initial_R_dist
        peak = entry
    else:
        tp1 = entry - TP1_R * initial_R_dist
        tp2 = entry - TP2_R * initial_R_dist
        peak = entry

    pos_id = f"{p['symbol']}_{p['opened_at']}"[:64]
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        INSERT OR REPLACE INTO paper_position_stages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pos_id, 0, float(p['quantity']), initial_R_dist, atr_for_trail,
          tp1, tp2, sl, peak, None, False, False, 0))
    con.commit()
    con.close()
    return {
        'position_id': pos_id,
        'stage': 0,
        'initial_qty': float(p['quantity']),
        'initial_R_dist': initial_R_dist,
        'atr_for_trail': atr_for_trail,
        'tp1_price': tp1,
        'tp2_price': tp2,
        'current_sl': sl,
        'peak_price': peak,
        'trail_active_bar': None,
        'pyramid_added_1': False,
        'pyramid_added_2': False,
        'bars_since_open': 0,
    }


def update_stage(stage: dict):
    """Stage state'i journal'a yaz."""
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        UPDATE paper_position_stages SET
            stage=?, current_sl=?, peak_price=?, trail_active_bar=?,
            pyramid_added_1=?, pyramid_added_2=?, bars_since_open=?
        WHERE position_id=?
    """, (stage['stage'], stage['current_sl'], stage['peak_price'], stage['trail_active_bar'],
          stage['pyramid_added_1'], stage['pyramid_added_2'], stage['bars_since_open'],
          stage['position_id']))
    con.commit()
    con.close()


def log_event(position_id: str, symbol: str, event_type: str, price: float,
              qty: float = 0, R: float = 0, pnl: float = 0, notes: str = ""):
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        INSERT INTO paper_position_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), position_id, symbol,
          event_type, price, qty, R, pnl, notes))
    con.commit()
    con.close()


def monitor_position(p: dict, bar: dict, state: dict) -> bool:
    """Tek pozisyon monitor — bar verisinden hit detect.
    Returns True if position closed (caller should remove from state)."""
    side = p['side']
    sym = p['symbol']
    qty = float(p['quantity'])
    entry = float(p['entry_price'])
    sl = float(p['sl_price'])

    pos_id = f"{sym}_{p['opened_at']}"[:64]
    stage = get_stage(pos_id)
    if stage is None:
        stage = init_stage(p)

    hi = bar['high']
    lo = bar['low']
    close = bar['close']
    slip = SLIPPAGE_BPS / 10_000.0

    closed = False
    R_dist = stage['initial_R_dist']

    # Update peak
    if side == "long":
        stage['peak_price'] = max(stage['peak_price'], hi)
    else:
        stage['peak_price'] = min(stage['peak_price'], lo)

    # SL hit?
    if side == "long":
        if lo <= stage['current_sl']:
            close_price = stage['current_sl'] * (1 - slip)
            pnl = (close_price - entry) * qty
            R = (close_price - entry) / R_dist
            print(f"  [SL] {sym} SL HIT @ {close_price:.4f}, PnL ${pnl:+.2f} (R {R:+.2f})")
            log_event(pos_id, sym, 'sl_hit', close_price, qty, R, pnl, f"stage={stage['stage']}")
            state['balances']['USDT'] = state['balances'].get('USDT', 0) + pnl + qty * entry  # margin geri + pnl
            state['realized_pnl_total'] = state.get('realized_pnl_total', 0) + pnl
            closed = True
            return True
    else:
        if hi >= stage['current_sl']:
            close_price = stage['current_sl'] * (1 + slip)
            pnl = (entry - close_price) * qty
            R = (entry - close_price) / R_dist
            print(f"  [SL] {sym} SL HIT @ {close_price:.4f}, PnL ${pnl:+.2f} (R {R:+.2f})")
            log_event(pos_id, sym, 'sl_hit', close_price, qty, R, pnl, f"stage={stage['stage']}")
            state['balances']['USDT'] = state['balances'].get('USDT', 0) + pnl + qty * entry
            state['realized_pnl_total'] = state.get('realized_pnl_total', 0) + pnl
            return True

    # TP1 hit (stage 0 → 1)
    if stage['stage'] == 0:
        tp1 = stage['tp1_price']
        hit = (side == "long" and hi >= tp1) or (side == "short" and lo <= tp1)
        if hit:
            close_price = tp1 * ((1 - slip) if side == "long" else (1 + slip))
            qty1 = qty * TP1_CLOSE_PCT
            pnl1 = ((close_price - entry) if side == "long" else (entry - close_price)) * qty1
            print(f"  [TP1] {sym} TP1 hit @ {close_price:.4f}, partial close {qty1:.4f}, PnL ${pnl1:+.2f} (1R)")
            log_event(pos_id, sym, 'tp1_hit', close_price, qty1, 1.0, pnl1, '')
            state['balances']['USDT'] = state['balances'].get('USDT', 0) + pnl1 + qty1 * entry
            state['realized_pnl_total'] = state.get('realized_pnl_total', 0) + pnl1
            # Pozisyon qty'i güncelle
            p['quantity'] = qty - qty1
            stage['stage'] = 1
            stage['current_sl'] = entry  # break-even
            # PYRAMID ADD
            if not stage['pyramid_added_1']:
                ek_qty = stage['initial_qty'] * PYRAMID_SIZES[0]
                ek_entry = tp1 * ((1 + slip) if side == "long" else (1 - slip))
                ek_margin = ek_qty * ek_entry / 3.0  # leverage 3x
                if state['balances'].get('USDT', 0) >= ek_margin:
                    state['balances']['USDT'] -= ek_margin
                    p['quantity'] = float(p['quantity']) + ek_qty
                    print(f"  [PYRA1] {sym} PYRAMID ADD #1: +{ek_qty:.4f} @ {ek_entry:.4f}")
                    log_event(pos_id, sym, 'pyramid_add_1', ek_entry, ek_qty, 0, 0, f"new_qty={p['quantity']}")
                    stage['pyramid_added_1'] = True
                else:
                    print(f"  [!] {sym} PYRAMID ADD #1 SKIP: insufficient cash")

    # TP2 hit (stage 1 → 2)
    if stage['stage'] == 1:
        tp2 = stage['tp2_price']
        hit = (side == "long" and hi >= tp2) or (side == "short" and lo <= tp2)
        if hit:
            close_price = tp2 * ((1 - slip) if side == "long" else (1 + slip))
            qty2 = stage['initial_qty'] * TP2_CLOSE_PCT
            pnl2 = ((close_price - entry) if side == "long" else (entry - close_price)) * qty2
            print(f"  [TP2] {sym} TP2 hit @ {close_price:.4f}, partial close {qty2:.4f}, PnL ${pnl2:+.2f} (1.5R)")
            log_event(pos_id, sym, 'tp2_hit', close_price, qty2, 1.5, pnl2, '')
            state['balances']['USDT'] = state['balances'].get('USDT', 0) + pnl2 + qty2 * entry
            state['realized_pnl_total'] = state.get('realized_pnl_total', 0) + pnl2
            p['quantity'] = float(p['quantity']) - qty2
            stage['stage'] = 2
            # Trail activate
            stage['trail_active_bar'] = stage['bars_since_open']
            # Trail SL
            if side == "long":
                trail_sl = stage['peak_price'] - RUNNER_TRAIL_MULT * stage['atr_for_trail']
                stage['current_sl'] = max(stage['current_sl'], tp2, trail_sl)
            else:
                trail_sl = stage['peak_price'] + RUNNER_TRAIL_MULT * stage['atr_for_trail']
                stage['current_sl'] = min(stage['current_sl'], tp2, trail_sl)
            # PYRAMID ADD #2
            if not stage['pyramid_added_2']:
                ek_qty = stage['initial_qty'] * PYRAMID_SIZES[1]
                ek_entry = tp2 * ((1 + slip) if side == "long" else (1 - slip))
                ek_margin = ek_qty * ek_entry / 3.0
                if state['balances'].get('USDT', 0) >= ek_margin:
                    state['balances']['USDT'] -= ek_margin
                    p['quantity'] = float(p['quantity']) + ek_qty
                    print(f"  [PYRA2] {sym} PYRAMID ADD #2: +{ek_qty:.4f} @ {ek_entry:.4f}")
                    log_event(pos_id, sym, 'pyramid_add_2', ek_entry, ek_qty, 0, 0, f"new_qty={p['quantity']}")
                    stage['pyramid_added_2'] = True

    # Stage >= 2: trailing + force-exit
    if stage['stage'] >= 2:
        # Trail update
        if side == "long":
            trail_sl = stage['peak_price'] - RUNNER_TRAIL_MULT * stage['atr_for_trail']
            stage['current_sl'] = max(stage['current_sl'], trail_sl)
        else:
            trail_sl = stage['peak_price'] + RUNNER_TRAIL_MULT * stage['atr_for_trail']
            stage['current_sl'] = min(stage['current_sl'], trail_sl)
        # Force-exit (30 bar sonra trail aktif olduktan)
        if stage['trail_active_bar'] is not None:
            bars_since_trail = stage['bars_since_open'] - stage['trail_active_bar']
            if bars_since_trail >= RUNNER_FORCE_EXIT_BARS:
                close_price = close * ((1 - slip) if side == "long" else (1 + slip))
                qty_remaining = float(p['quantity'])
                pnl = ((close_price - entry) if side == "long" else (entry - close_price)) * qty_remaining
                R = ((close_price - entry) if side == "long" else (entry - close_price)) / R_dist
                print(f"  [FORCE] {sym} FORCE EXIT (30 bars trail) @ {close_price:.4f}, PnL ${pnl:+.2f} (R {R:+.2f})")
                log_event(pos_id, sym, 'trail_force_exit', close_price, qty_remaining, R, pnl, '')
                state['balances']['USDT'] = state['balances'].get('USDT', 0) + pnl + qty_remaining * entry
                state['realized_pnl_total'] = state.get('realized_pnl_total', 0) + pnl
                return True

    stage['bars_since_open'] = stage.get('bars_since_open', 0) + 1
    update_stage(stage)
    return False


def monitor_all_positions(verbose=True):
    init_journal_extras()
    state = load_paper_state()
    positions = state.get('positions', [])
    if not positions:
        if verbose:
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Acik pozisyon yok.")
        return

    if verbose:
        print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Monitor: {len(positions)} acik pozisyon")
        print(f"  Equity: ${state['balances'].get('USDT', 0):.2f}, Realized PnL total: ${state.get('realized_pnl_total', 0):+.2f}")

    # Cache: aynı sym için tek fetch
    bar_cache = {}
    closed_indices = []
    for i, p in enumerate(positions):
        sym = p['symbol']
        if sym not in bar_cache:
            bar_cache[sym] = fetch_current_bar(sym)
        bar = bar_cache[sym]
        if bar is None:
            continue
        if monitor_position(p, bar, state):
            closed_indices.append(i)

    # Closed pozisyonları sil
    for i in reversed(closed_indices):
        del positions[i]
    state['positions'] = positions

    save_paper_state(state)
    if verbose:
        print(f"[RESULT] {len(closed_indices)} pos kapatildi, {len(positions)} hala acik")
        print(f"  Equity: ${state['balances'].get('USDT', 0):.2f}, Realized PnL total: ${state.get('realized_pnl_total', 0):+.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Sürekli döngü (her 5dk)")
    parser.add_argument("--interval", type=int, default=300, help="Loop interval saniye (default 300=5dk)")
    args = parser.parse_args()

    if args.loop:
        print(f"Position monitor LOOP mode, interval={args.interval}s")
        while True:
            try:
                monitor_all_positions(verbose=True)
            except Exception as e:
                print(f"[ERROR] {e}")
            time.sleep(args.interval)
    else:
        monitor_all_positions(verbose=True)
