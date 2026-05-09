"""Unit testler -- CrowsBuyingClimaxStrategy (HYP-NEW-6).

Test senaryolari (11 test):
  1.  BC detector: klasik BC bar => True
  2.  BC detector: dusuk hacim BC degil => False
  3.  BC detector: close ust yarisinda => False (uzun ust fitil yok)
  4.  BC detector: 5-bar new high degil => False
  5.  3 Crows strict: 3 gecerli crow => True
  6.  3 Crows strict: bar-to-bar volume eskalasyonu yok => False (strict mod)
  7.  CBC confluence: BC + 3 Crows islenmis sinyal => True
  8.  CBC confluence: BC var ama 3 Crows yok => False
  9.  CBC confluence: 3 Crows var ama BC yok (3 bar once) => False
  10. End-to-end: Synthetic confluece => short sinyal (SL > close > TP, 3R)
  11. Sadece short sinyal, exception yok (smoke)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.crows_buying_climax import (
    CrowsBuyingClimaxStrategy,
    _buying_climax,
    _three_black_crows_strict,
    _crows_buying_climax_signal,
    _bc_sl_price,
    _default_manifest,
)


# =====================================================================
# Test yardimcilari
# =====================================================================

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 6, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}


def _df(bars: list[dict], symbol: str = "TEST/USDT") -> pd.DataFrame:
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    df["ts"] = ts
    df["venue"] = "binance"
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def _flat_bar(price: float = 100.0, vol: float = 500_000.0) -> dict:
    """Nötr/flat bar (pattern triggerlamamali)."""
    return _bar(price, price * 1.005, price * 0.995, price * 0.998, vol)


def _bc_bar(
    price: float = 100.0,
    spread_mult: float = 2.0,
    vol: float = 5_000_000.0,
    close_pos_frac: float = 0.30,  # close barin alt %30'unda — uzun ust fitil
) -> dict:
    """Buying Climax bar fabrikasi.

    spread = spread_mult * ~range (sembolize genis bar),
    close = low + close_pos_frac * range (alt yarisinda kapanis).
    """
    atr_proxy = price * 0.02  # ~%2 fiyat
    spread = spread_mult * atr_proxy  # genis bar
    high = price + spread * 0.5
    low = price - spread * 0.5
    close = low + close_pos_frac * spread  # alt yarisinda
    open_ = price  # acilis ortada (up bar: close > open ise ayarla)
    # BC'nin bir up bar olmasi icin: close > open
    if close > open_:
        pass
    else:
        # Duzelt: open'i daha asagi al
        open_ = low + close_pos_frac * spread * 0.8
    return _bar(open_, high, low, close, vol)


def _crow_bar(
    open_: float,
    size: float = 10.0,
    vol: float = 1_200_000.0,
) -> dict:
    """Iyi bir Three Black Crows bar fabrikasi.

    body = 80% range, alt shadow = 10%, minimal ust shadow.
    """
    close = open_ - size * 0.80
    high = open_ + size * 0.05
    low = close - size * 0.10
    return _bar(open_, high, low, close, vol)


def _make_strategy(require_ema200: bool = False) -> CrowsBuyingClimaxStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "crows_buying_climax",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": require_ema200},
        "signals": {
            "patterns": [
                {
                    "id": "crows_buying_climax",
                    "enabled": True,
                    "weight": 3.0,
                    "params": {
                        "bc_spread_atr_mult": 1.5,
                        "bc_vol_sma_mult": 2.5,
                        "bc_close_pos_max": 0.50,
                        "bc_new_high_bars": 5,
                        "bc_vol_sma_window": 5,  # kisa pencere testler icin
                        "bc_require_up_bar": False,  # test kolayligi icin kapatildi
                        "crow_body_min": 0.50,
                        "crow_shadow_max": 0.20,
                        "crow_proximity": 0.80,  # gevsetilmis test icin
                        "crow_vol_strict": False,  # net escalation
                        "require_ema200_above": require_ema200,
                        "sl_atr_buffer": 0.5,
                    },
                }
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
            },
            "confluence": {"method": "weighted_sum", "min_score": 3.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "bc_high_atr", "atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
        },
    }
    return CrowsBuyingClimaxStrategy(StrategyManifest.model_validate(raw))


# =====================================================================
# Test 1-4: Buying Climax detector
# =====================================================================

class TestBuyingClimaxDetector:

    def _warmup(self, n: int = 20, price: float = 100.0, vol: float = 500_000.0) -> list[dict]:
        """Kücük volume ile duzen barlar (vol_sma ve ATR hesabinin stabil olmasi icin, n>=20)."""
        return [_flat_bar(price, vol) for _ in range(n)]

    def test_classic_bc_detected(self):
        """Klasik BC bar (genis spread + yuksek hacim + alt kapanis + 5-bar new high) => True.

        Not: ATR hesabi icin min 14 warmup bar gerekli.
        vol_sma(5) warmup vol 500K ile 500K civarinda.
        BC vol = 3_000_000 => 2.5 * 500K = 1.25M < 3M => OK.
        spread = h-l = 8.0, warmup range ~1.0 => ATR ~1.0 => 1.5*ATR ~1.5 < 8 => OK.
        """
        warmup = self._warmup(20, price=100.0, vol=500_000)
        # flat warmup bars: high~100.5, low~99.5, range~1.0
        # BC bar: h=105 (> warmup max 100.5 => 5-bar new high), l=97, spread=8
        bc = _bar(
            o=100.0,
            h=105.0,   # 5-bar yeni high (warmup high ~100.5)
            l=97.0,
            c=98.5,    # close < low + 0.5*range = 97 + 4 = 101 => OK (alt yarisinda)
            v=3_000_000,  # > 2.5 * vol_sma(500K) = 1.25M
        )
        bars = warmup + [bc]
        df = _df(bars)
        flags = _buying_climax(
            df,
            spread_atr_mult=1.5,
            vol_sma_mult=2.5,
            close_pos_max=0.50,
            new_high_bars=5,
            vol_sma_window=5,
            require_up_bar=False,
        )
        assert bool(flags.iloc[-1]), "Klasik BC bar son barda True olmali"

    def test_low_volume_not_bc(self):
        """Dusuk hacimli bar BC degil."""
        warmup = self._warmup(20)
        bc_low_vol = _bar(100.0, 105.0, 97.0, 98.5, v=600_000)  # dusuk hacim
        bars = warmup + [bc_low_vol]
        df = _df(bars)
        flags = _buying_climax(
            df,
            spread_atr_mult=1.5,
            vol_sma_mult=2.5,
            close_pos_max=0.50,
            new_high_bars=5,
            vol_sma_window=5,
            require_up_bar=False,
        )
        assert not bool(flags.iloc[-1]), "Dusuk hacimle BC olmamali"

    def test_close_in_upper_half_not_bc(self):
        """Close barın ust yarısında ise BC degil (uzun ust fitil yok)."""
        warmup = self._warmup(20)
        # close = 103.5 > low + 0.5 * range = 97 + 0.5 * 8 = 101 => NOT BC
        no_bc = _bar(100.0, 105.0, 97.0, 103.5, v=3_000_000)
        bars = warmup + [no_bc]
        df = _df(bars)
        flags = _buying_climax(
            df,
            spread_atr_mult=1.5,
            vol_sma_mult=2.5,
            close_pos_max=0.50,
            new_high_bars=5,
            vol_sma_window=5,
            require_up_bar=False,
        )
        assert not bool(flags.iloc[-1]), "Close ust yarisinda BC olmamali"

    def test_not_new_5bar_high_not_bc(self):
        """5-bar new high degil ise BC degil."""
        # Onceki barlarda daha yuksek high yaparak rolling_max'i yuksel
        warmup = [_bar(100.0, 110.0, 99.0, 100.5, 500_000) for _ in range(20)]  # high=110
        # Bu bar high=107 => 110 kadar degil => 5-bar max = 110 > 107
        no_new_high = _bar(100.0, 107.0, 97.0, 98.5, 3_000_000)
        bars = warmup + [no_new_high]
        df = _df(bars)
        flags = _buying_climax(
            df,
            spread_atr_mult=1.5,
            vol_sma_mult=2.5,
            close_pos_max=0.50,
            new_high_bars=5,
            vol_sma_window=5,
            require_up_bar=False,
        )
        assert not bool(flags.iloc[-1]), "5-bar new high yoksa BC olmamali"


# =====================================================================
# Test 5-6: Three Black Crows (strict)
# =====================================================================

class TestThreeBlackCrowsStrict:

    def test_three_valid_crows_detected(self):
        """3 gecerli crow bar => son barda True."""
        warmup = [_flat_bar(100.0, 500_000) for _ in range(12)]
        crow1 = _crow_bar(100.0, size=8.0, vol=1_000_000)
        crow2 = _crow_bar(93.0, size=8.0, vol=1_300_000)  # c1~93, open2 near c1
        crow3 = _crow_bar(86.0, size=8.0, vol=1_700_000)
        bars = warmup + [crow1, crow2, crow3]
        df = _df(bars)
        flags = _three_black_crows_strict(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.80,
            vol_escalation_strict=False,
        )
        assert bool(flags.iloc[-1]), "3 gecerli crow bar => son barda True"
        assert not bool(flags.iloc[-2]), "Ikinci barda henuz uc crow yok"

    def test_no_volume_escalation_rejected_strict(self):
        """Strict mod: bar-to-bar eskalasyon yok => False."""
        warmup = [_flat_bar(100.0, 500_000) for _ in range(12)]
        # v1=2M, v2=1.5M, v3=1M — azalan
        crow1 = _crow_bar(100.0, size=8.0, vol=2_000_000)
        crow2 = _crow_bar(93.0, size=8.0, vol=1_500_000)
        crow3 = _crow_bar(86.0, size=8.0, vol=1_000_000)
        bars = warmup + [crow1, crow2, crow3]
        df = _df(bars)
        flags = _three_black_crows_strict(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.80,
            vol_escalation_strict=True,  # strict: v2>v1 AND v3>v2
        )
        assert not bool(flags.iloc[-1]), "Azalan volume strict modda reddedilmeli"


# =====================================================================
# Test 7-9: CBC confluence sinyali
# =====================================================================

class TestCBCConfluenceSignal:

    def _make_bc_plus_crows_df(self, bc_vol_high: bool = True) -> pd.DataFrame:
        """
        BC at t-3, 3 crows at [t-2, t-1, t].
        bc_vol_high: BC hackimi gercekten yuksek mi?

        Not: warmup 20 bar, kucuk hacim (500K) => vol_sma ~500K.
        BC vol = 3M => 2.5 * 500K = 1.25M < 3M => OK.
        Spread = 9 (106-97), warmup range ~1 => ATR ~1 => 1.5*ATR ~1.5 < 9 => OK.
        """
        # Warmup: 20 flat bars, kucuk hacim
        warmup = [_flat_bar(100.0, 500_000) for _ in range(20)]

        # BC bar at t-3: high degerini warmup max'dan (100.5) buyuk yap => new 5-bar high
        bc_vol = 3_000_000 if bc_vol_high else 400_000
        bc = _bar(
            o=100.0, h=106.0, l=97.0,
            c=98.5,   # alt yarisinda (97 + 0.5*9 = 101.5 > 98.5 => OK)
            v=bc_vol,
        )

        # 3 crows
        c1 = _crow_bar(104.0, size=8.0, vol=1_200_000)
        c2 = _crow_bar(97.0, size=8.0, vol=1_500_000)
        c3 = _crow_bar(90.0, size=8.0, vol=2_000_000)

        bars = warmup + [bc, c1, c2, c3]
        return _df(bars)

    def test_bc_plus_crows_confluence_true(self):
        """BC 3 bar once + 3 crows => confluence True."""
        df = self._make_bc_plus_crows_df(bc_vol_high=True)
        flags = _crows_buying_climax_signal(
            df,
            bc_spread_atr_mult=1.5,
            bc_vol_sma_mult=2.5,
            bc_close_pos_max=0.50,
            bc_new_high_bars=5,
            bc_vol_sma_window=5,
            bc_require_up_bar=False,
            crow_body_min=0.50,
            crow_shadow_max=0.20,
            crow_proximity=0.80,
            crow_vol_strict=False,
            require_ema200_above=False,
        )
        assert bool(flags.iloc[-1]), "BC + 3 Crows confluence olmali"

    def test_bc_present_but_no_crows_false(self):
        """BC var ama ardindan 3 crows yok => False."""
        warmup = [_flat_bar(100.0, 500_000) for _ in range(20)]
        bc = _bar(100.0, 106.0, 97.0, 98.5, 3_000_000)
        # BC'den sonra neutral barlar
        n1 = _flat_bar(103.0, 700_000)
        n2 = _flat_bar(104.0, 600_000)
        n3 = _flat_bar(103.5, 650_000)
        bars = warmup + [bc, n1, n2, n3]
        df = _df(bars)
        flags = _crows_buying_climax_signal(
            df,
            bc_spread_atr_mult=1.5,
            bc_vol_sma_mult=2.5,
            bc_close_pos_max=0.50,
            bc_new_high_bars=5,
            bc_vol_sma_window=5,
            bc_require_up_bar=False,
            crow_body_min=0.50,
            crow_shadow_max=0.20,
            crow_proximity=0.80,
            crow_vol_strict=False,
            require_ema200_above=False,
        )
        assert not bool(flags.iloc[-1]), "BC var ama crows yok => False"

    def test_crows_present_but_no_bc_3bars_ago_false(self):
        """3 Crows var ama BC (klimaktik hacim+genis spread) 3 bar once yok => False."""
        warmup = [_flat_bar(100.0, 500_000) for _ in range(20)]
        # BC olmayan normal bir bar 3 bar once (kucuk hacim, dar spread)
        normal_3ago = _flat_bar(105.0, 600_000)  # dusuk hacim, dar
        c1 = _crow_bar(104.0, size=8.0, vol=1_200_000)
        c2 = _crow_bar(97.0, size=8.0, vol=1_500_000)
        c3 = _crow_bar(90.0, size=8.0, vol=2_000_000)
        bars = warmup + [normal_3ago, c1, c2, c3]
        df = _df(bars)
        flags = _crows_buying_climax_signal(
            df,
            bc_spread_atr_mult=1.5,
            bc_vol_sma_mult=2.5,
            bc_close_pos_max=0.50,
            bc_new_high_bars=5,
            bc_vol_sma_window=5,
            bc_require_up_bar=False,
            crow_body_min=0.50,
            crow_shadow_max=0.20,
            crow_proximity=0.80,
            crow_vol_strict=False,
            require_ema200_above=False,
        )
        assert not bool(flags.iloc[-1]), "BC olmadan crow sinyali False olmali"


# =====================================================================
# Test 10: End-to-end: short sinyal, SL/TP kontrolu, 3R
# =====================================================================

class TestEndToEnd:

    def test_synthetic_pattern_produces_short_signal(self):
        """Synthetic CBC pattern => en az 1 short sinyal, SL > close > TP, 3R.

        Yaklaşım: features doğrudan inject edilir (cbc_signal + cbc_sl) — böylece
        BC vol_sma / spread / ATR hesaplamalarından bağımsız, saf signal-to-trade
        pipeline test edilir.
        """
        strat = _make_strategy(require_ema200=False)

        n = 60
        rng = np.random.default_rng(42)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.010, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1.005 + np.abs(rng.normal(0, 0.003, n)))
        low = np.minimum(open_, close) * (0.995 - np.abs(rng.normal(0, 0.003, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = _base_ts(n)
        vol = rng.uniform(8e5, 2e6, n)
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": vol,
            "venue": "binance", "symbol": "SYNTH/USDT", "timeframe": "1d",
        })
        df_feats = strat.prepare_features(df)

        # Directly inject the confluence signal at bar 50 and required SL
        inject_idx = 50
        inject_close = float(df_feats.loc[inject_idx, "close"])
        inject_atr = float(df_feats.loc[inject_idx, "atr14"])

        df_feats.loc[inject_idx, "cbc_signal"] = True
        # SL = close + 2.5 * ATR (well above entry — valid short SL)
        df_feats.loc[inject_idx, "cbc_sl"] = inject_close + 2.5 * inject_atr

        signals = strat.generate_signals(df_feats)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Inject edilmis CBC signal => en az 1 short sinyal"

        sig = short_sigs[0]
        assert sig.pattern_id == "crows_buying_climax"
        assert sig.direction == "short"
        assert sig.sl_price > sig.tp_price, "Short: SL > entry > TP"
        assert sig.confluence_score >= 3.0
        # 3R: TP = close - 3 * (sl - close)
        risk = sig.sl_price - inject_close
        assert risk > 0, "Risk pozitif olmali (SL > entry)"
        expected_tp = inject_close - 3.0 * risk
        assert abs(sig.tp_price - expected_tp) < 1e-4 * inject_close, "TP ~= entry - 3R"


# =====================================================================
# Test 11: Smoke test
# =====================================================================

def test_smoke_no_exception_only_short():
    """Rastgele veri: exception yok, sadece short sinyaller."""
    strat = _make_strategy(require_ema200=False)
    rng = np.random.default_rng(77)
    n = 300
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    ts = _base_ts(n)
    df = pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": rng.uniform(5e5, 5e6, n),
        "venue": "binance", "symbol": "SMOKE/USDT", "timeframe": "1d",
    })
    df_feats = strat.prepare_features(df)
    signals = strat.generate_signals(df_feats)

    assert isinstance(signals, list)
    for sig in signals:
        assert sig.direction == "short", "Sadece short sinyal olmali"
        assert sig.sl_price > sig.tp_price, "Short: SL > TP"
        assert sig.confluence_score >= 3.0


# =====================================================================
# Default manifest test
# =====================================================================

def test_default_manifest_valid():
    """_default_manifest() gecerli StrategyManifest dondurmeli."""
    m = _default_manifest()
    assert m.name == "crows_buying_climax"
    assert m.trend_filter.period == 200
    assert m.trend_filter.required is True
    assert len(m.signals.patterns) == 1
    assert m.signals.patterns[0].id == "crows_buying_climax"
    # TP 3R
    primary_r = m.risk.get("take_profit", {}).get("primary_R", 0)
    assert primary_r == 3.0, "TP 3R olmali"


def test_default_manifest_instantiation():
    """Default manifest ile strateji olusturulabilmeli."""
    m = _default_manifest()
    strat = CrowsBuyingClimaxStrategy(m)
    assert strat.name == "crows_buying_climax"
