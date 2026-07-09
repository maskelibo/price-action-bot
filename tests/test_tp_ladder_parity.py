"""F2 TP merdiveni paritesi — kapanış sprinti 2026-07-10 (DERIN_DENETIM F2 CRIT).

Canlı merdiven doğrulanmamış TERS kurulumdu: 'TP1' emri sig.tp_price'a (strateji
ham hedefi, 2-2.5R!) %25 qty, 'TP2' 1.5R'ye %25, runner %50. Doğrulanan kanon
(engine.py default'ları + exit_tournament_verdict §6 primary + v15p2'nin 2 Tem
robustness koşusu): TP1=%30@1R, TP2=%30@1.5R, runner=%40. Ters merdiven hiçbir
modelde backtest'lenmedi (turnuvanın 'LIVE' replikası bile tp1_R=1.0 varsaymıştı).

Fix: compute_partial_tp_prices saf fonksiyonu + kaynak-pin sabitler; TP1 artık
entry±1R hesaplanır, sig.tp_price yalnız legacy single-TP modda + observability
(strategy_tp_price) olarak yaşar.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.futures_trade_daily as ftd  # noqa: E402


def test_tp1_price_is_1r_long():
    assert ftd.compute_partial_tp_prices("long", 100.0, 95.0) == (105.0, 107.5)


def test_tp1_price_is_1r_short():
    assert ftd.compute_partial_tp_prices("short", 100.0, 105.0) == (95.0, 92.5)


def test_ladder_never_inverted():
    """F2 regresyon nöbetçisi: TP1 her zaman TP2'den YAKIN olmalı."""
    for side, entry, sl in (("long", 100.0, 97.0), ("short", 50.0, 52.0), ("long", 1.9, 1.8)):
        tp1, tp2 = ftd.compute_partial_tp_prices(side, entry, sl)
        assert abs(tp1 - entry) < abs(tp2 - entry), f"{side}: merdiven ters ({tp1} vs {tp2})"


def test_fractions_match_validated_model():
    assert ftd.TP1_FRAC == 0.30
    assert ftd.TP2_FRAC == 0.30
    assert abs((1 - ftd.TP1_FRAC - ftd.TP2_FRAC) - 0.40) < 1e-9  # runner %40


def test_source_pin_engine_defaults():
    """Kanon kayarsa bu test kırılır: canlı sabitler = engine default'ları."""
    import inspect

    from price_action.backtest.engine import BacktestEngine

    p = inspect.signature(BacktestEngine.__init__).parameters
    assert p["tp1_R"].default == ftd.TP1_R
    assert p["tp2_R"].default == ftd.TP2_R
    assert p["tp1_close_pct"].default == ftd.TP1_FRAC
    assert p["tp2_close_pct"].default == ftd.TP2_FRAC


class _StubExchange:
    """create_order çağrılarını kaydeden minimal borsa."""

    def __init__(self):
        self.orders = []
        self._i = 0

    def amount_to_precision(self, symbol, x):
        return str(x)

    def price_to_precision(self, symbol, x):
        return str(x)

    def create_order(self, symbol, type, side, amount, params):
        self._i += 1
        self.orders.append({"type": type, "side": side, "amount": amount, "params": dict(params)})
        return {"id": f"oid{self._i}"}


def test_place_protection_uses_computed_tp1_not_sig_tp():
    """ÇEKİRDEK VAKA: strateji TP'si 112.5 (2.5R) geçilse bile TP1 emri 1R'ye
    (105.0) konmalı — eski kod 112.5'e koyuyordu (ters merdiven)."""
    ex = _StubExchange()
    res = ftd.place_protection_orders(
        ex, "BTC/USDT:USDT", "long", qty=1.0, tp_price=112.5, sl_price=95.0, entry_price=100.0
    )
    tps = [o for o in ex.orders if o["type"] == "TAKE_PROFIT_MARKET"]
    sls = [o for o in ex.orders if o["type"] == "STOP_MARKET"]
    assert len(tps) == 2 and len(sls) == 1
    assert float(tps[0]["params"]["stopPrice"]) == 105.0  # TP1 = 1R (112.5 DEĞİL)
    assert float(tps[1]["params"]["stopPrice"]) == 107.5  # TP2 = 1.5R
    assert abs(tps[0]["amount"] - 0.30) < 1e-9
    assert abs(tps[1]["amount"] - 0.30) < 1e-9
    assert abs(sls[0]["amount"] - 1.0) < 1e-9  # SL tam qty
    assert res["status"] == "placed"
    assert float(res["tp_price"]) == 105.0
    assert float(res["strategy_tp_price"]) == 112.5  # observability korunur


def test_short_side_orders():
    ex = _StubExchange()
    res = ftd.place_protection_orders(
        ex, "ZEC/USDT:USDT", "short", qty=2.0, tp_price=85.0, sl_price=105.0, entry_price=100.0
    )
    tps = [o for o in ex.orders if o["type"] == "TAKE_PROFIT_MARKET"]
    assert all(o["side"] == "BUY" for o in tps)
    assert float(tps[0]["params"]["stopPrice"]) == 95.0  # 1R aşağı
    assert float(tps[1]["params"]["stopPrice"]) == 92.5  # 1.5R aşağı
    assert res["status"] == "placed"


def test_legacy_single_tp_mode_unchanged():
    """entry_price=None → eski davranış: TEK TP, geçilen tp_price'ta, tam qty."""
    ex = _StubExchange()
    res = ftd.place_protection_orders(
        ex, "BTC/USDT:USDT", "long", qty=1.0, tp_price=112.5, sl_price=95.0
    )
    tps = [o for o in ex.orders if o["type"] == "TAKE_PROFIT_MARKET"]
    assert len(tps) == 1
    assert float(tps[0]["params"]["stopPrice"]) == 112.5  # legacy: strateji TP'si
    assert abs(tps[0]["amount"] - 1.0) < 1e-9
    assert res["status"] == "placed"
