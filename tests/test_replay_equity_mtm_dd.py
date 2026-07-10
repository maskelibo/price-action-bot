"""Replay-equity CRIT — MTM DD bandı (P2 kapanışı, 2026-07-10).

Eski max_drawdown İKİ ZIT kusur taşır:
  (1) Ana-döngü: açık pozisyonlar book-margin'de (0 unrealized) → DD AZ gösterir.
  (2) Wind-down: equity=cash açık marjinleri HARİÇ tutar → yapay dip → DD FAZLA
      gösterir (dead-end deneyi: all-winner havuzda sahte -0.388).
İlk -1R stress-band denemesi ETKİSİZDİ çünkü (2)'yi miras alıyordu
([[replay-equity-stress-band-deadend]]) — bu fix her cash-olayında (entry/close/
wind-down) DOĞRU muhasebe tutar:
  max_drawdown_mtm    = book (cash+Σ açık marjin, wind-down düzeltmeli)
  max_drawdown_stress = book − Σ stres-işaret (mae_R varsa gerçek MAE, yoksa -1R)
ADDITIVE: eski eq_curve/final_equity/max_drawdown BYTE-AYNI (parite + arşiv).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from price_action.backtest.lab import (
    ProductionConfig,
    ReplayResult,
    _stress_risk_mark,
    _update_dd_state,
    production_replay,
)

_BASE = datetime(2024, 1, 1, tzinfo=UTC)
_SYMS = [f"S{i}/USDT" for i in range(10)]


def _cfg(**over) -> ProductionConfig:
    d = dict(
        risk_pct=0.01,
        conf_min=0.0,
        max_concurrent=20,
        same_symbol_side_cooldown_days=0.0,
        initial_capital=10_000.0,
        consecutive_loss_n=None,
        daily_dd=0.99,
        weekly_dd=0.99,
        monthly_dd=0.99,
    )
    d.update(over)
    return ProductionConfig(**d)


def _trade(sym, entry_off_min, exit_off, r_mult, sl_pct=0.02, entry_price=100.0, mae_r=None):
    t = {
        "entry_ts": _BASE + timedelta(minutes=entry_off_min),
        "exit_ts": _BASE + exit_off,
        "symbol": sym,
        "side": "long",
        "strategy": "test_strat",
        "R": r_mult,
        "conf": 0.5,
        "conf_pct": 0.5,
        "entry_price": entry_price,
        "initial_sl": entry_price * (1.0 - sl_pct),
    }
    if mae_r is not None:
        t["mae_R"] = mae_r
    return t


# ---------------------------------------------------------------------------
# Saf helper'lar
# ---------------------------------------------------------------------------


def test_stress_mark_fallback_1r():
    assert _stress_risk_mark({"risk": 100.0}) == 100.0  # mae_R yok → -1R


def test_stress_mark_uses_mae_when_present():
    assert _stress_risk_mark({"risk": 100.0, "mae_R": -0.3}) == 30.0
    assert _stress_risk_mark({"risk": 100.0, "mae_R": 0.5}) == 0.0  # hiç aleyhe gitmemiş
    assert _stress_risk_mark({"risk": 100.0, "mae_R": None}) == 100.0  # None → fallback


def test_update_dd_state_tracks_both_series():
    st = {"peak": 100.0, "dd": 0.0, "speak": 100.0, "sdd": 0.0}
    _update_dd_state(st, 110.0, 105.0)  # yeni peak'ler
    _update_dd_state(st, 99.0, 88.0)  # dipler
    assert abs(st["dd"] - (99.0 - 110.0) / 110.0) < 1e-12
    assert abs(st["sdd"] - (88.0 - 105.0) / 105.0) < 1e-12


# ---------------------------------------------------------------------------
# ÇEKİRDEK: iki kusurun da düzeldiğinin kanıtı
# ---------------------------------------------------------------------------


def test_winddown_artifact_corrected_and_concurrency_revealed():
    """Dead-end deneyinin vakası: 5 eşzamanlı all-winner, hepsi wind-down'da kapanır.
    ESKİ max_drawdown ≈ -0.388 (yapay dip — kusur 2, kıyas için AYNEN durur).
    YENİ max_drawdown_mtm ≈ 0 (all-winner book hiç düşmez — kusur 2 düzeldi).
    YENİ max_drawdown_stress ≤ -0.04 (5×1R eşzamanlı risk — kusur 1 görünür oldu)."""
    pool = [_trade(_SYMS[i], i, timedelta(days=10, hours=i), r_mult=2.0) for i in range(5)]
    r = production_replay(pool, _cfg())
    assert r is not None
    assert r.max_drawdown < -0.30  # eski artefakt korunuyor (byte-parite belgesi)
    assert r.max_drawdown_mtm > -1e-9  # düzeltilmiş book: all-winner → DD yok
    # 5 açık × risk_d=60 (conf=0.5 modifier: 100×0.6) = 300/10000 = -%3 gerçek maruziyet
    assert abs(r.max_drawdown_stress - (-0.03)) < 1e-9


def test_sequential_mtm_matches_realized():
    """Örtüşmesiz sıralı havuz: iki kusur da devrede değil → mtm ≈ eski realized."""
    pool = [
        _trade(
            _SYMS[i % 5], i * 1440, timedelta(days=i, hours=4), r_mult=(2.0 if i % 2 == 0 else -1.0)
        )
        for i in range(10)
    ]
    r = production_replay(pool, _cfg())
    assert r is not None
    assert abs(r.max_drawdown_mtm - r.max_drawdown) < 1e-9


def test_stress_never_above_mtm():
    """Üst-sınır garantisi: stress her zaman book'tan ≤ (daha negatif/eşit)."""
    pool = [
        _trade(_SYMS[i % 6], i * 60.0, timedelta(days=5, hours=i), r_mult=(1.5 if i % 3 else -1.0))
        for i in range(12)
    ]
    r = production_replay(pool, _cfg())
    assert r is not None
    assert r.max_drawdown_stress <= r.max_drawdown_mtm + 1e-12


def test_mae_enriched_pool_gives_milder_stress():
    """mae_R'li havuz: stres işareti gerçek MAE'ye göre (-1R'den ılımlı)."""
    mk = lambda mae: [  # noqa: E731
        _trade(_SYMS[i], i, timedelta(days=10, hours=i), r_mult=2.0, mae_r=mae) for i in range(5)
    ]
    r_mae = production_replay(mk(-0.2), _cfg())
    r_1r = production_replay(mk(None), _cfg())
    assert r_mae is not None and r_1r is not None
    assert r_mae.max_drawdown_stress > r_1r.max_drawdown_stress  # -0.2R işaret < -1R işaret
    assert r_mae.max_drawdown_stress < 0.0  # ama yine görünür


# ---------------------------------------------------------------------------
# Parite kalkanları — eski alanlar DEĞİŞMEDİ
# ---------------------------------------------------------------------------


def test_existing_fields_and_invariants_preserved():
    """realistic_backtest len(eq_curve)==n+1 varsayar; max_drawdown eski formülle
    eq_curve'den yeniden hesaplanabilir olmalı (eski yol dokunulmamış kanıtı)."""
    pool = [
        _trade(
            _SYMS[i % 5], i * 720.0, timedelta(days=3 + i, hours=2), r_mult=(2.0 if i % 2 else -1.0)
        )
        for i in range(8)
    ]
    r = production_replay(pool, _cfg())
    assert r is not None and r.equity_curve is not None
    assert len(r.equity_curve) == r.trades + 1
    assert abs(r.equity_curve[-1] - r.final_equity) < 1e-9
    # eski max_drawdown == eq_curve'den eski formülle hesap (bağımsız re-derive)
    peak, dd = r.equity_curve[0], 0.0
    for v in r.equity_curve:
        peak = max(peak, v)
        dd = min(dd, (v - peak) / peak if peak > 0 else 0.0)
    assert abs(dd - r.max_drawdown) < 1e-12


def test_backward_compat_default_fields():
    rr = ReplayResult(
        final_equity=10_000.0,
        initial_capital=10_000.0,
        trades=0,
        win_rate=0.0,
        max_drawdown=0.0,
        avg_r=0.0,
        sum_r=0.0,
        config_label="x",
    )
    assert rr.max_drawdown_mtm == 0.0 and rr.max_drawdown_stress == 0.0


def test_source_pins():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "src" / "price_action" / "backtest" / "lab.py"
    ).read_text(encoding="utf-8")
    assert "_stress_risk_mark(" in src
    assert "_update_dd_state(" in src
    assert '"mae_R": t.get("mae_R")' in src
    # eski yollar byte-aynı duruyor:
    assert 'equity = cash + sum(q["margin"] for q in still)' in src
    assert "equity = cash\n" in src  # wind-down eski satırı (kasıtlı korunuyor)
