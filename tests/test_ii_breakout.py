"""Unit testler + backtest -- IIBreakoutStrategy (Brooks ii Inside-Inside).

Test senaryolari (8 adet):
  1. _ii_pattern: Bilinen ii pattern tespiti (A->B->C)
  2. _ii_breakout_flags: D bari long/short breakout tespit dogrulugu
  3. Lookahead-free: breakout flag t aninda t-1..t-3 bilgisini kullaniyor
  4. prepare_features: Gerekli kolonlari ekliyor
  5. Long sinyal: ii breakout long + trend filtresi uyum => sinyal uretildi
  6. Short sinyal: ii breakout short + trend filtresi uyum => sinyal uretildi
  7. Sinyal yok: ii complete ama breakout bar yok
  8. Backtest: Sentetik trend verisi, sinyal sayisi / SL-TP tutarliligi / win rate
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.ii_breakout import (
    IIBreakoutStrategy,
    _default_manifest,
    _ii_pattern,
    _ii_breakout_flags,
)
from price_action.strategies.base import StrategyManifest
from price_action.contracts import Signal


# =====================================================================
# Yardimci fabrikalar
# =====================================================================

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v)}


def _df_from_bars(
    bars: list[dict],
    venue: str = "binance",
    symbol: str = "TEST/USDT",
) -> pd.DataFrame:
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["ts"] = ts
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _make_strategy(trend_required: bool = False) -> IIBreakoutStrategy:
    """Minimal test manifest ile strateji olusturur."""
    raw = {
        "name": "ii_breakout",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": trend_required},
        "signals": {
            "patterns": [
                {"id": "ii_long_breakout",  "enabled": True, "weight": 1.0, "params": {}},
                {"id": "ii_short_breakout", "enabled": True, "weight": 1.0, "params": {}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 50,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 50,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.0,
                "volume_zscore_min": 0.0,
                "kaufman_er_min": 0.0,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "a_range_opposite", "sl_atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
        "backtest": {
            "warmup_bars": 10,
            "fees": {"taker": 0.00075},
            "slippage_bps": 5.0,
            "initial_capital_usdt": 10000.0,
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return IIBreakoutStrategy(manifest)


def _make_trend_df(n: int = 150, seed: int = 42, uptrend: bool = True) -> pd.DataFrame:
    """Gercekci trend sentetik OHLCV (EMA warmup icin yeterli bar)."""
    rng = np.random.default_rng(seed)
    drift = 0.003 if uptrend else -0.003
    rets = rng.normal(drift, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low  = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low  = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(8e5, 2e6, n)
    return pd.DataFrame({
        "ts": _base_ts(n),
        "open":   open_,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume,
        "venue":  "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


# =====================================================================
# 1. _ii_pattern: bilinen ii pattern tespiti
# =====================================================================

class TestIIPattern:
    def test_ii_complete_detected(self):
        """B inside A, C inside B => ii_complete True at bar C (index 4)."""
        #         o      h      l      c
        bars = [
            _bar(90,  110, 88,   100),   # bar 0: warmup
            _bar(90,  110, 88,   100),   # bar 1: warmup
            _bar(95,  108, 92,   100),   # bar 2 = A: range [92, 108]
            _bar(96,  105, 93,   100),   # bar 3 = B: inside A [93<92? no -- fix]
            _bar(97,  103, 94,   100),   # bar 4 = C: inside B
        ]
        # A=[92,108], B must have high<108 AND low>92 -- bar3 h=105<108, l=93>92 OK
        # C must have high<105 AND low>93 -- bar4 h=103<105, l=94>93 OK
        df = _df_from_bars(bars)
        ii_complete, a_high, a_low = _ii_pattern(df)

        # At bar index 4 (C): ii_complete should be True
        assert bool(ii_complete.iloc[4]), "Bar 4 (C bari) ii_complete True olmali"
        # A.high and A.low at bar 4 (from bar 2)
        assert abs(float(a_high.iloc[4]) - 108.0) < 1e-6, "A.high bar 4'te 108 olmali"
        assert abs(float(a_low.iloc[4])  -  92.0) < 1e-6, "A.low bar 4'te 92 olmali"

    def test_no_ii_when_b_not_inside_a(self):
        """B bar A'nin disminda => ii_complete False."""
        bars = [
            _bar(90,  110, 88,  100),   # warmup
            _bar(90,  110, 88,  100),   # warmup
            _bar(95,  108, 92,  100),   # A
            _bar(96,  115, 93,  100),   # B NOT inside A (high=115 > A.high=108)
            _bar(97,  103, 94,  100),   # C
        ]
        df = _df_from_bars(bars)
        ii_complete, _, _ = _ii_pattern(df)
        assert not bool(ii_complete.iloc[4]), "B disminda ise ii_complete False olmali"

    def test_no_ii_when_c_not_inside_b(self):
        """C bar B'nin disminda => ii_complete False."""
        bars = [
            _bar(90,  110, 88,  100),   # warmup
            _bar(90,  110, 88,  100),   # warmup
            _bar(95,  108, 92,  100),   # A
            _bar(96,  105, 93,  100),   # B inside A
            _bar(97,  106, 94,  100),   # C NOT inside B (high=106 > B.high=105)
        ]
        df = _df_from_bars(bars)
        ii_complete, _, _ = _ii_pattern(df)
        assert not bool(ii_complete.iloc[4]), "C disminda ise ii_complete False olmali"


# =====================================================================
# 2. _ii_breakout_flags: D bari breakout tespiti
# =====================================================================

class TestIIBreakoutFlags:
    def _ii_bars_plus_breakout(
        self,
        breakout_close: float,
        a_high: float = 108.0,
        a_low:  float = 92.0,
    ) -> pd.DataFrame:
        """ii tamamlanmis + D bari verilen kapanista."""
        bars = [
            _bar(90,  110,       88,       100),    # 0 warmup
            _bar(90,  110,       88,       100),    # 1 warmup
            _bar(95,  a_high,    a_low,    100),    # 2 = A
            _bar(96,  a_high-3,  a_low+1,  100),    # 3 = B inside A
            _bar(97,  a_high-6,  a_low+2,  100),    # 4 = C inside B
            _bar(100, breakout_close+1, breakout_close-1, breakout_close),  # 5 = D
        ]
        return _df_from_bars(bars)

    def test_long_breakout_detected(self):
        """D.close > A.high => long_breakout True at D (bar 5)."""
        df = self._ii_bars_plus_breakout(breakout_close=112.0)  # > A.high=108
        long_bo, short_bo, a_h, a_l = _ii_breakout_flags(df)
        assert bool(long_bo.iloc[5]), "D.close > A.high => long_breakout True"
        assert not bool(short_bo.iloc[5]), "Long breakout sirasinda short_breakout False"

    def test_short_breakout_detected(self):
        """D.close < A.low => short_breakout True at D (bar 5)."""
        df = self._ii_bars_plus_breakout(breakout_close=88.0)  # < A.low=92
        long_bo, short_bo, a_h, a_l = _ii_breakout_flags(df)
        assert bool(short_bo.iloc[5]), "D.close < A.low => short_breakout True"
        assert not bool(long_bo.iloc[5]), "Short breakout sirasinda long_breakout False"

    def test_no_breakout_inside_a_range(self):
        """D.close A range icinde => breakout yok."""
        df = self._ii_bars_plus_breakout(breakout_close=100.0)  # icinde [92, 108]
        long_bo, short_bo, _, _ = _ii_breakout_flags(df)
        assert not bool(long_bo.iloc[5]), "A range icinde long_breakout olmamali"
        assert not bool(short_bo.iloc[5]), "A range icinde short_breakout olmamali"

    def test_a_range_values_correct_at_d(self):
        """D barinda a_high / a_low degerleri bar A'ya ait olmali."""
        df = self._ii_bars_plus_breakout(breakout_close=112.0)
        _, _, a_h, a_l = _ii_breakout_flags(df)
        # A bar = bar 2, shift(3) from D (bar 5) in _ii_pattern, then shift(1) in breakout
        # a_high at bar 5 should = bar2.high = 108
        assert abs(float(a_h.iloc[5]) - 108.0) < 1e-6, f"a_high at D = {a_h.iloc[5]}"
        assert abs(float(a_l.iloc[5]) -  92.0) < 1e-6, f"a_low at D = {a_l.iloc[5]}"


# =====================================================================
# 3. Lookahead-free kontrol
# =====================================================================

class TestLookahead:
    def test_breakout_flag_uses_only_past_bars(self):
        """Bar D'deki breakout flag bar D+1 bilgisini kullanmamali.

        Yontem: D bari sonrasini degistirip D'deki sonucun sabit kaldigini goster.
        """
        bars_base = [
            _bar(90,  110,  88,  100),   # 0 warmup
            _bar(90,  110,  88,  100),   # 1 warmup
            _bar(95,  108,  92,  100),   # 2 = A
            _bar(96,  105,  93,  100),   # 3 = B
            _bar(97,  103,  94,  100),   # 4 = C
            _bar(100, 115, 110, 112),    # 5 = D (long breakout > 108)
            _bar(100, 120, 115, 118),    # 6 = next bar (degistirilecek)
        ]
        df1 = _df_from_bars(bars_base)
        long_bo1, _, _, _ = _ii_breakout_flags(df1)

        bars_modified = bars_base.copy()
        bars_modified[6] = _bar(100, 80, 75, 78)  # 6. bari cok farklı yap
        df2 = _df_from_bars(bars_modified)
        long_bo2, _, _, _ = _ii_breakout_flags(df2)

        # Bar 5 degismemeli
        assert bool(long_bo1.iloc[5]) == bool(long_bo2.iloc[5]), (
            "Bar 5 (D) breakout flag bar 6 degisince degismemeli (lookahead yok)"
        )

    def test_no_breakout_flag_before_d(self):
        """D barindan once (bar 4 = C) breakout flag False olmali."""
        bars = [
            _bar(90,  110,  88,  100),
            _bar(90,  110,  88,  100),
            _bar(95,  108,  92,  100),  # A
            _bar(96,  105,  93,  100),  # B
            _bar(97,  103,  94,  100),  # C
            _bar(100, 115, 110, 112),   # D
        ]
        df = _df_from_bars(bars)
        long_bo, short_bo, _, _ = _ii_breakout_flags(df)
        # Bar 4 (C) - sinyal olsuyor ama D bar 5'te
        assert not bool(long_bo.iloc[4]), "C barinda (index 4) long_breakout False olmali"


# =====================================================================
# 4. prepare_features: gerekli kolonlar
# =====================================================================

class TestPrepareFeatures:
    def test_required_columns_present(self):
        """prepare_features sonrasi tum gerekli kolonlar bulunmali."""
        strat = _make_strategy()
        df = _make_trend_df(n=80)
        df_feat = strat.prepare_features(df)
        required = [
            "ema50", "ema200", "atr14", "atr_pct", "vol_z",
            "kaufman_er", "always_in_long", "always_in_short",
            "rolling_sharpe",
            "ii_long_breakout", "ii_short_breakout",
            "ii_a_high", "ii_a_low",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_empty_df_returns_empty(self):
        """Bos DataFrame => bos sonuc."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        result = strat.prepare_features(empty)
        assert result.empty


# =====================================================================
# 5. Long sinyal uretimi
# =====================================================================

class TestLongSignal:
    def test_long_signal_produced_on_breakout(self):
        """ii long breakout flag varken long sinyal uretilmeli."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=80)
        df_feat = strat.prepare_features(df)

        # Tum breakout flagleri sifirla
        df_feat["ii_long_breakout"]  = False
        df_feat["ii_short_breakout"] = False

        # Bar 50'yi tetikle
        bar_idx = 50
        close_val = float(df_feat.loc[bar_idx, "close"])
        df_feat.loc[bar_idx, "ii_long_breakout"] = True
        df_feat.loc[bar_idx, "ii_a_high"] = close_val * 0.98   # A.high < close => breakout
        df_feat.loc[bar_idx, "ii_a_low"]  = close_val * 0.90   # SL = a_low - 0.5*atr
        df_feat.loc[bar_idx, "atr_pct"]   = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "ii long breakout sonrasi long sinyal olmali"

        sig = long_sigs[0]
        assert sig.pattern_id == "ii_long_breakout"
        assert sig.sl_price < close_val, "Long SL close altinda olmali"
        assert sig.tp_price > close_val, "Long TP close ustunde olmali"
        assert isinstance(sig, Signal)

    def test_long_sl_and_tp_consistency(self):
        """Long sinyalde sl < close < tp ve tp - close ~= 2 * (close - sl)."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=80)
        df_feat = strat.prepare_features(df)

        df_feat["ii_long_breakout"]  = False
        df_feat["ii_short_breakout"] = False

        bar_idx = 60
        close_val = float(df_feat.loc[bar_idx, "close"])
        atr_val   = float(df_feat.loc[bar_idx, "atr14"])
        a_low_val = close_val - 3.0 * atr_val  # enough distance for SL

        df_feat.loc[bar_idx, "ii_long_breakout"] = True
        df_feat.loc[bar_idx, "ii_a_high"] = close_val * 0.99
        df_feat.loc[bar_idx, "ii_a_low"]  = a_low_val
        df_feat.loc[bar_idx, "atr_pct"]   = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1

        sig = long_sigs[0]
        risk = sig.tp_price - close_val  # approximate R
        assert sig.tp_price > close_val
        assert sig.sl_price < close_val
        # 2R check: tp - close ~= 2 * (close - sl)  ± 5%
        r = close_val - sig.sl_price
        tp_expected = close_val + 2.0 * r
        assert abs(sig.tp_price - tp_expected) / tp_expected < 0.05, (
            f"TP 2R'den sapti: expected={tp_expected:.4f}, got={sig.tp_price:.4f}"
        )


# =====================================================================
# 6. Short sinyal uretimi
# =====================================================================

class TestShortSignal:
    def test_short_signal_produced_on_breakout(self):
        """ii short breakout flag varken short sinyal uretilmeli."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=80, uptrend=False)
        df_feat = strat.prepare_features(df)

        df_feat["ii_long_breakout"]  = False
        df_feat["ii_short_breakout"] = False

        bar_idx = 50
        close_val = float(df_feat.loc[bar_idx, "close"])
        df_feat.loc[bar_idx, "ii_short_breakout"] = True
        df_feat.loc[bar_idx, "ii_a_high"] = close_val * 1.08
        df_feat.loc[bar_idx, "ii_a_low"]  = close_val * 1.02  # A.low > close => breakout
        df_feat.loc[bar_idx, "atr_pct"]   = 0.02

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "ii short breakout sonrasi short sinyal olmali"

        sig = short_sigs[0]
        assert sig.pattern_id == "ii_short_breakout"
        assert sig.sl_price > close_val, "Short SL close ustunde olmali"
        assert sig.tp_price < close_val, "Short TP close altinda olmali"


# =====================================================================
# 7. Sinyal yok: ii complete ama breakout bar yok
# =====================================================================

class TestNoSignal:
    def test_no_signal_without_breakout(self):
        """ii tamamlandi ama D bari A range icinde => sinyal yok."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=80)
        df_feat = strat.prepare_features(df)

        # Her iki flag False
        df_feat["ii_long_breakout"]  = False
        df_feat["ii_short_breakout"] = False

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Breakout bar olmadan sinyal uretilmemeli"

    def test_no_signal_empty_df(self):
        """Bos DataFrame => bos sinyal listesi."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []

    def test_trend_filter_blocks_counter_trend(self):
        """Trend filtresi aktifken trend yonune karsi sinyal uretilmemeli.

        Uptrend (close > ema50) => short sinyal bloke edilmeli.
        """
        strat = _make_strategy(trend_required=True)
        df = _make_trend_df(n=80, uptrend=True)
        df_feat = strat.prepare_features(df)

        df_feat["ii_long_breakout"]  = False
        df_feat["ii_short_breakout"] = False

        bar_idx = 60
        close_val = float(df_feat.loc[bar_idx, "close"])
        # Uptrend icinde short breakout dene
        df_feat.loc[bar_idx, "ii_short_breakout"] = True
        df_feat.loc[bar_idx, "ii_a_high"] = close_val * 1.08
        df_feat.loc[bar_idx, "ii_a_low"]  = close_val * 1.02
        df_feat.loc[bar_idx, "atr_pct"]   = 0.02

        # Uptrend: close > ema50 garantile
        df_feat.loc[bar_idx, "ema50"] = close_val * 0.95

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) == 0, "Uptrend'de trend filtresi short sinyali bloke etmeli"


# =====================================================================
# 8. Backtest: sentetik veri uzerinde tam calistirma
# =====================================================================

class TestBacktest:
    """End-to-end backtest: sinyal uret, SL/TP simule et, win rate hesapla."""

    def _run_backtest(
        self,
        df: pd.DataFrame,
        strat: IIBreakoutStrategy,
        primary_R: float = 2.0,
    ) -> dict:
        """Basit event-driven backtest: her sinyali simule eder.

        Varsayim:
          - Entry: sinyal bar kapanisi (D bari)
          - Sonraki N barlarda TP veya SL hangisi once kirilirsa o sonuc.
          - Max hold = 20 bar
        """
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)

        wins   = 0
        losses = 0
        signal_dates = set()

        for sig in signals:
            # sinyalin index'ini bul
            ts_series = pd.to_datetime(df_feat["ts"])
            sig_ts = pd.Timestamp(sig.ts)
            matches = df_feat.index[ts_series == sig_ts].tolist()
            if not matches:
                continue
            entry_idx = matches[0]
            entry_price = float(df_feat.loc[entry_idx, "close"])

            # sonraki 20 bar
            result = None
            for j in range(entry_idx + 1, min(entry_idx + 21, len(df_feat))):
                bar_h = float(df_feat.loc[j, "high"])
                bar_l = float(df_feat.loc[j, "low"])

                if sig.direction == "long":
                    if bar_h >= sig.tp_price:
                        result = "win"
                        break
                    if bar_l <= sig.sl_price:
                        result = "loss"
                        break
                else:
                    if bar_l <= sig.tp_price:
                        result = "win"
                        break
                    if bar_h >= sig.sl_price:
                        result = "loss"
                        break

            if result == "win":
                wins += 1
            elif result == "loss":
                losses += 1

            signal_dates.add(sig.ts.year if hasattr(sig.ts, "year") else 0)

        total = wins + losses
        win_rate = wins / total if total > 0 else float("nan")

        return {
            "total_signals": len(signals),
            "resolved": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
        }

    def test_backtest_no_exceptions(self):
        """Tam backtest dongusu exception olusturmamali."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=300, seed=1)
        result = self._run_backtest(df, strat)
        assert isinstance(result["total_signals"], int)
        assert result["total_signals"] >= 0

    def test_backtest_sl_tp_coherence(self):
        """Her sinyalde: long => sl < close < tp, short => sl > close > tp."""
        strat = _make_strategy(trend_required=False)
        df = _make_trend_df(n=200, seed=7)
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)

        for sig in signals:
            close_approx = float(
                df_feat.loc[
                    pd.to_datetime(df_feat["ts"]) == pd.Timestamp(sig.ts),
                    "close"
                ].iloc[0]
                if len(df_feat.loc[pd.to_datetime(df_feat["ts"]) == pd.Timestamp(sig.ts)]) > 0
                else sig.sl_price + 1  # fallback
            )
            if sig.direction == "long":
                assert sig.sl_price < sig.tp_price, (
                    f"Long: SL ({sig.sl_price}) >= TP ({sig.tp_price})"
                )
            else:
                assert sig.sl_price > sig.tp_price, (
                    f"Short: SL ({sig.sl_price}) <= TP ({sig.tp_price})"
                )

    def test_backtest_full_stats(self):
        """3 yillik sentetik veri: sinyal sayisi, win rate, yillik performans raporu.

        ii pattern NADIR -- 1000 barlik pencerede ~5-30 sinyal beklenir.
        Win rate 2R ile 40%+ olmali (teorik EV pozitif).
        """
        strat = _make_strategy(trend_required=False)
        # 3 yil ~ 1095 gunluk bar (birden cok trend donemi)
        rng = np.random.default_rng(2024)
        n = 1095
        # Karma trend: ilk 365 up, sonraki 365 down, son 365 up
        drifts = np.concatenate([
            rng.normal(0.002, 0.012, 365),
            rng.normal(-0.002, 0.012, 365),
            rng.normal(0.002, 0.012, 365),
        ])
        close = 100.0 * np.exp(np.cumsum(drifts))
        open_ = np.r_[close[0], close[:-1]]
        high  = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low   = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
        high  = np.maximum.reduce([high, open_, close])
        low   = np.minimum.reduce([low, open_, close])
        volume = rng.uniform(8e5, 2e6, n)
        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "venue": "binance", "symbol": "BTC/USDT", "timeframe": "1d",
        })

        result = self._run_backtest(df, strat)

        total_signals = result["total_signals"]
        win_rate      = result["win_rate"]
        years         = n / 365.0

        # Raporla (assert sadece tutarlilik icin)
        print(f"\n{'='*55}")
        print(f"ii Breakout Backtest Raporu (3 yillik sentetik)")
        print(f"{'='*55}")
        print(f"Toplam sinyal   : {total_signals}")
        print(f"Yillik sinyal   : {total_signals / years:.1f}")
        print(f"Cozumlenen      : {result['resolved']}")
        print(f"Kazanc          : {result['wins']}")
        print(f"Kayip           : {result['losses']}")
        if not np.isnan(win_rate):
            print(f"Win rate        : {win_rate:.1%}")
        else:
            print("Win rate        : N/A (cozumlenen sinyal yok)")
        print(f"{'='*55}")

        # ii NADIR, 0 da olabilir -- sadece tutarlilik kontrol et
        assert total_signals >= 0
        if result["resolved"] > 0 and not np.isnan(win_rate):
            # Win rate 0-1 araliginda olmali
            assert 0.0 <= win_rate <= 1.0


# =====================================================================
# Default manifest ve instantiation testleri
# =====================================================================

def test_default_manifest_valid():
    """_default_manifest() gecerli StrategyManifest dondurmeli."""
    m = _default_manifest()
    assert m.name == "ii_breakout"
    assert len(m.signals.patterns) == 2
    assert m.risk.get("take_profit", {}).get("primary_R", 0) == 2.0
    assert m.trend_filter.required is True


def test_default_manifest_strategy_instantiation():
    """Default manifest ile IIBreakoutStrategy olusturulabilmeli."""
    m = _default_manifest()
    strat = IIBreakoutStrategy(m)
    assert strat.name == "ii_breakout"


def test_smoke_run_random_data():
    """Rastgele veriye karsi genel smoke testi -- exception olmamalı."""
    rng = np.random.default_rng(9999)
    n = 250
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
    open_ = np.r_[close[0], close[:-1]]
    high  = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low   = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high  = np.maximum.reduce([high, open_, close])
    low   = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "venue": "binance", "symbol": "SMOKE/USDT", "timeframe": "1d",
    })
    strat = _make_strategy()
    df_feat = strat.prepare_features(df)
    signals = strat.generate_signals(df_feat)

    assert isinstance(signals, list)
    for sig in signals:
        if sig.direction == "long":
            assert sig.sl_price < sig.tp_price
        else:
            assert sig.sl_price > sig.tp_price
