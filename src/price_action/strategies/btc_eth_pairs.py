"""BTC-ETH Statistical Arbitrage Pairs Trading Strategy.

Chan (Algorithmic Trading, 2013) yöntemi: Engle-Granger cointegration
testi ile spread tespiti, rolling OLS hedge ratio, z-score giriş/çıkış.

Market-neutral: LONG spread = long BTC + short ETH (dollar-neutral)
               SHORT spread = short BTC + long ETH

Sinyal kuralı:
  z < -2.0 AND adf_p < 0.05  -> LONG spread
  z > +2.0 AND adf_p < 0.05  -> SHORT spread
  |z| < 0.5 (ya da ters yön) -> Kapat

Lookahead koruması: tüm hesaplamalar shift(1) ile korunur.
İki sinyal per entry emitlenir: bir BTC, bir ETH bacağı.
Bacaklar pair_signal_id ile linklenmiştir.
"""
from __future__ import annotations

import uuid
import warnings
from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import Signal
from price_action.logging_config import logger
from price_action.strategies.base import Strategy, StrategyManifest

# statsmodels — ADF testi icin
try:
    from statsmodels.tsa.stattools import adfuller

    _STATSMODELS_OK = True
except ImportError:  # pragma: no cover
    _STATSMODELS_OK = False
    warnings.warn(
        "statsmodels bulunamadi; ADF testi icin basit yaklasim kullanilacak. "
        "pip install statsmodels",
        ImportWarning,
        stacklevel=2,
    )


# =====================================================================
# Yardimci fonksiyonlar (modül düzeyi — test edilebilir)
# =====================================================================

def _compute_hedge_ratio(
    btc_log: pd.Series,
    eth_log: pd.Series,
    lookback: int = 60,
) -> pd.Series:
    """Rolling OLS ile hedge ratio beta hesapla.

    Bağımlı: btc_log, bağımsız: eth_log.
    spread = btc_log - beta * eth_log

    Lookahead koruması: t bari icin [t-lookback, t-1] kullanilir.
    Yani OLS verisi shift(1) uygulanmis veri uzerinde rolling yapilir;
    mevcut bar verisi dahil edilmez.

    Returns
    -------
    pd.Series: beta (hedge ratio), same index as input.
    """
    n = len(btc_log)
    betas = np.full(n, np.nan)

    # Shift ederek lookahead kapatiriz: [t-lookback..t-1]
    btc_shifted = btc_log.shift(1).values
    eth_shifted = eth_log.shift(1).values

    for i in range(lookback, n):
        y = btc_shifted[i - lookback + 1 : i + 1]
        x = eth_shifted[i - lookback + 1 : i + 1]
        if np.any(np.isnan(y)) or np.any(np.isnan(x)):
            continue
        # OLS: y = beta*x + alpha  (numpy.linalg.lstsq ile)
        X = np.column_stack([x, np.ones(len(x))])
        result, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        betas[i] = result[0]

    return pd.Series(betas, index=btc_log.index, name="hedge_ratio")


def _compute_spread(
    btc_log: pd.Series,
    eth_log: pd.Series,
    hedge_ratio: pd.Series,
) -> pd.Series:
    """Log spread serisi hesapla: spread = log_BTC - beta * log_ETH.

    hedge_ratio zaten shift(1) ile hesaplanmis (lookahead-free).
    """
    spread = btc_log - hedge_ratio * eth_log
    return spread.rename("spread")


def _zscore_spread(
    spread: pd.Series,
    lookback: int = 20,
) -> pd.Series:
    """Rolling z-score: (spread - rolling_mean) / rolling_std.

    Lookahead koruması: shift(1) ile bir bar geriye kaydirilir;
    yani t bari icin [t-lookback..t-1] kullanilir.
    """
    shifted = spread.shift(1)
    mean = shifted.rolling(lookback, min_periods=lookback // 2).mean()
    std = shifted.rolling(lookback, min_periods=lookback // 2).std(ddof=1)
    z = (spread - mean) / std.replace(0, np.nan)
    return z.rename("spread_z")


def _adf_test(spread: pd.Series) -> float:
    """Augmented Dickey-Fuller testi: p-degeri doner.

    Null: unit root var (non-stationary).
    p < 0.05 -> stationary (spread mean-reverting).

    statsmodels yoksa basit AR(1) yaklasimi kullanilir.
    """
    arr = spread.dropna().values
    if len(arr) < 20:
        return 1.0  # yetersiz veri -> reject sinyal

    if _STATSMODELS_OK:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = adfuller(arr, maxlag=1, autolag=None)
        return float(result[1])  # p-value
    else:
        # Basit yaklasim: AR(1) rezidu OLS t-stat (degil ADF ama proxy)
        y = arr[1:]
        x = arr[:-1]
        if np.std(x) == 0:
            return 1.0
        beta = np.cov(y, x)[0, 1] / np.var(x)
        resid = y - beta * x
        se = np.std(resid) / (np.std(x) * np.sqrt(len(x)))
        t_stat = (beta - 1.0) / (se + 1e-12)
        # Approximate p-value from t distribution
        # p yaklaşık: ADF kritik degerleri %5 seviyesinde -2.86 civarı
        return 0.01 if t_stat < -3.0 else (0.05 if t_stat < -2.86 else 0.10)


def _rolling_adf_p(
    spread: pd.Series,
    adf_window: int = 60,
) -> pd.Series:
    """Her bar icin rolling window ADF p-degeri.

    t bari icin [t-adf_window..t-1] spread verisine ADF uygulanir.
    Lookahead: shift(1) ile spread bir bar geride.
    """
    spread_shifted = spread.shift(1)
    n = len(spread_shifted)
    pvals = np.full(n, np.nan)

    for i in range(adf_window, n):
        window = spread_shifted.iloc[i - adf_window + 1 : i + 1].dropna()
        if len(window) < 20:
            continue
        pvals[i] = _adf_test(window)

    return pd.Series(pvals, index=spread.index, name="adf_p_lag")


def _half_life(spread: pd.Series) -> float:
    """Ornstein-Uhlenbeck half-life hesapla (AR(1) uzerinden).

    delta_spread = lambda * spread_lag + mu + epsilon
    half_life = -log(2) / log(1 + lambda)
    """
    arr = spread.dropna().values
    if len(arr) < 10:
        return np.nan
    delta = np.diff(arr)
    lag = arr[:-1]
    if np.std(lag) == 0:
        return np.nan
    # OLS
    X = np.column_stack([lag, np.ones(len(lag))])
    res, _, _, _ = np.linalg.lstsq(X, delta, rcond=None)
    lam = res[0]
    if lam >= 0:
        return np.nan  # mean-reversion yok
    try:
        hl = -np.log(2) / np.log(1 + lam)
    except Exception:
        return np.nan
    return float(hl)


# =====================================================================
# Default manifest
# =====================================================================

def _default_manifest() -> StrategyManifest:
    raw = {
        "name": "btc_eth_pairs",
        "version": "1.0.0",
        "description": (
            "BTC-ETH statistical arbitrage pairs trading "
            "(Chan-style Engle-Granger cointegration + rolling OLS hedge ratio)"
        ),
        "signals": {
            "patterns": [
                {
                    "id": "pairs_long_spread",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "spread_z_entry": 2.0,
                        "exit_z": 0.5,
                        "stop_z": 3.5,
                        "lookback_window": 60,
                        "adf_window": 60,
                        "adf_threshold": 0.05,
                    },
                },
                {
                    "id": "pairs_short_spread",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "spread_z_entry": 2.0,
                        "exit_z": 0.5,
                        "stop_z": 3.5,
                        "lookback_window": 60,
                        "adf_window": 60,
                        "adf_threshold": 0.05,
                    },
                },
            ],
        },
        "risk": {
            "position_sizing": {"method": "dollar_neutral", "risk_per_trade": 0.02},
        },
    }
    return StrategyManifest.model_validate(raw)


# =====================================================================
# Strategy
# =====================================================================

class BTCETHPairsStrategy(Strategy):
    """BTC-ETH Statistical Arbitrage Pairs Trading.

    Market-neutral: spread = log(BTC) - beta * log(ETH)

    Her entry'de 2 sinyal emitlenir:
      - BTC bacağı  (direction="long"  veya "short")
      - ETH bacağı  (direction="short" veya "long", tersi)
    Pair bağlantısı: metadata['pair_signal_id'] ile.

    Beklenen kullanım:
        strategy = BTCETHPairsStrategy(_default_manifest())
        df_btc = store.read("BTC/USDT", "1d")
        df_eth = store.read("ETH/USDT", "1d")
        df_feats = strategy.prepare_features_pair(df_btc, df_eth)
        signals = strategy.generate_signals_pair(df_feats)
    """

    name = "btc_eth_pairs"

    # Params — manifestten veya default
    @property
    def _params(self) -> dict[str, Any]:
        for p in self.manifest.signals.patterns:
            if p.id in ("pairs_long_spread", "pairs_short_spread"):
                return p.params
        return {}

    @property
    def spread_z_entry(self) -> float:
        return float(self._params.get("spread_z_entry", 2.0))

    @property
    def exit_z(self) -> float:
        return float(self._params.get("exit_z", 0.5))

    @property
    def stop_z(self) -> float:
        return float(self._params.get("stop_z", 3.5))

    @property
    def lookback_window(self) -> int:
        return int(self._params.get("lookback_window", 60))

    @property
    def adf_window(self) -> int:
        return int(self._params.get("adf_window", 60))

    @property
    def adf_threshold(self) -> float:
        return float(self._params.get("adf_threshold", 0.05))

    # ------------------------------------------------------------------
    # Strategy ABC — single-df arayüz (Strategy.generate_signals imzasi)
    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Tek sembollü df için — pairs stratejisinde kullanılmaz.

        ABC gereksinimi; birleşik df bekleniyor (prepare_features_pair kullan).
        df'de 'btc_close' ve 'eth_close' kolonları olmalı.
        """
        return self.prepare_features_pair(df)

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Tek sembollü wrapper — birleşik df bekleniyor."""
        return self.generate_signals_pair(df)

    # ------------------------------------------------------------------
    # Pairs-spesifik arayüz
    # ------------------------------------------------------------------

    def prepare_features_pair(
        self,
        df: pd.DataFrame,
        btc_col: str = "btc_close",
        eth_col: str = "eth_close",
    ) -> pd.DataFrame:
        """Birleşik (btc_close + eth_close kolonlu) df üzerinde özellikler hesapla.

        df'de ts, btc_close, eth_close gereklidir.
        Dışarıdan da farklı kolon isimleri kullanılabilir.
        """
        if df.empty:
            return df.copy()
        df = df.sort_values("ts").reset_index(drop=True).copy()

        # log fiyatlar
        df["log_btc"] = np.log(df[btc_col].clip(lower=1e-12))
        df["log_eth"] = np.log(df[eth_col].clip(lower=1e-12))

        # Rolling OLS hedge ratio (lookahead-free, shift(1) içinde)
        df["hedge_ratio"] = _compute_hedge_ratio(
            df["log_btc"], df["log_eth"], lookback=self.lookback_window
        )

        # Spread
        df["spread"] = _compute_spread(df["log_btc"], df["log_eth"], df["hedge_ratio"])

        # Z-score (shift(1) ile lookahead kapalı)
        df["spread_z"] = _zscore_spread(df["spread"], lookback=self.lookback_window)

        # Rolling ADF p-value (shift(1) içinde)
        df["adf_p_lag"] = _rolling_adf_p(df["spread"], adf_window=self.adf_window)

        return df

    def generate_signals_pair(
        self,
        df: pd.DataFrame,
        venue: str = "binance",
        timeframe: str = "1d",
    ) -> list[Signal]:
        """Pairs stratejisi için sinyal üret.

        Her sinyal entry'de 2 sinyal emitlenir (BTC bacağı + ETH bacağı).
        metadata['pair_signal_id'] ile pair bağlantısı sağlanır.
        metadata['pair_leg'] = 'btc' veya 'eth'.

        Çıkış sinyalleri metadata['pair_action'] = 'exit' ile işaretlenir.
        """
        if df.empty:
            return []

        # Özellikler yoksa hesapla
        if "spread_z" not in df.columns:
            df = self.prepare_features_pair(df)

        out: list[Signal] = []
        z_entry = self.spread_z_entry
        z_exit = self.exit_z
        z_stop = self.stop_z
        adf_thr = self.adf_threshold

        # State tracker (basit vektörel backtest icin sinyaller yeterli;
        # tam durum makinesi engine'de; burada sinyal üretimi)
        # long_spread: long BTC + short ETH (z < -entry)
        # short_spread: short BTC + long ETH (z > +entry)

        in_long_spread = False
        in_short_spread = False

        for i in range(len(df)):
            row = df.iloc[i]
            z = float(row.get("spread_z", np.nan))
            adf_p = float(row.get("adf_p_lag", np.nan))
            hedge = float(row.get("hedge_ratio", np.nan))
            ts = pd.Timestamp(row["ts"]).to_pydatetime()

            if np.isnan(z) or np.isnan(adf_p) or np.isnan(hedge):
                continue

            btc_price = float(row.get("btc_close", 0.0))
            eth_price = float(row.get("eth_close", 0.0))
            if btc_price <= 0 or eth_price <= 0:
                continue

            cointegrated = adf_p < adf_thr
            pair_id = str(uuid.uuid4())[:12]

            # --- EXIT LOGIC FIRST ---
            if in_long_spread:
                # Exit: z rises back above -exit_z  OR  stop_z hit
                if z > -z_exit or z < -z_stop:
                    pair_id_exit = str(uuid.uuid4())[:12]
                    action = "stop" if z < -z_stop else "exit"
                    # Close BTC leg (was long) -> short
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="BTC/USDT", direction="short",
                        pattern_id="pairs_long_spread",
                        pair_signal_id=pair_id_exit,
                        pair_leg="btc", pair_action=action,
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=btc_price,
                    ))
                    # Close ETH leg (was short) -> long
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="ETH/USDT", direction="long",
                        pattern_id="pairs_long_spread",
                        pair_signal_id=pair_id_exit,
                        pair_leg="eth", pair_action=action,
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=eth_price,
                    ))
                    in_long_spread = False
                continue  # after exit, no new entry this bar

            if in_short_spread:
                # Exit: z falls back below +exit_z  OR  stop_z hit
                if z < z_exit or z > z_stop:
                    pair_id_exit = str(uuid.uuid4())[:12]
                    action = "stop" if z > z_stop else "exit"
                    # Close BTC leg (was short) -> long
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="BTC/USDT", direction="long",
                        pattern_id="pairs_short_spread",
                        pair_signal_id=pair_id_exit,
                        pair_leg="btc", pair_action=action,
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=btc_price,
                    ))
                    # Close ETH leg (was long) -> short
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="ETH/USDT", direction="short",
                        pattern_id="pairs_short_spread",
                        pair_signal_id=pair_id_exit,
                        pair_leg="eth", pair_action=action,
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=eth_price,
                    ))
                    in_short_spread = False
                continue  # after exit, no new entry this bar

            # --- ENTRY LOGIC ---
            if not in_long_spread and not in_short_spread:
                if z < -z_entry and cointegrated:
                    # LONG spread: long BTC + short ETH
                    in_long_spread = True
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="BTC/USDT", direction="long",
                        pattern_id="pairs_long_spread",
                        pair_signal_id=pair_id,
                        pair_leg="btc", pair_action="entry",
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=btc_price,
                    ))
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="ETH/USDT", direction="short",
                        pattern_id="pairs_long_spread",
                        pair_signal_id=pair_id,
                        pair_leg="eth", pair_action="entry",
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=eth_price,
                    ))

                elif z > z_entry and cointegrated:
                    # SHORT spread: short BTC + long ETH
                    in_short_spread = True
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="BTC/USDT", direction="short",
                        pattern_id="pairs_short_spread",
                        pair_signal_id=pair_id,
                        pair_leg="btc", pair_action="entry",
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=btc_price,
                    ))
                    out.append(self._emit_leg(
                        ts=ts, venue=venue, timeframe=timeframe,
                        symbol="ETH/USDT", direction="long",
                        pattern_id="pairs_short_spread",
                        pair_signal_id=pair_id,
                        pair_leg="eth", pair_action="entry",
                        z=z, adf_p=adf_p, hedge=hedge,
                        price=eth_price,
                    ))

        self._log.bind(n_signals=len(out), n_bars=len(df)).info(
            "btc_eth_pairs.signals.generated"
        )
        return out

    def _emit_leg(
        self,
        *,
        ts: Any,
        venue: str,
        timeframe: str,
        symbol: str,
        direction: str,
        pattern_id: str,
        pair_signal_id: str,
        pair_leg: str,
        pair_action: str,
        z: float,
        adf_p: float,
        hedge: float,
        price: float,
    ) -> Signal:
        """Bir pairs bacağı için Signal emitlir."""
        # Nominal SL/TP: pairs stratejisi icin z-score bazlı (sembolik)
        # Gercek risk yonetimi pair seviyesinde (backtest engine'de)
        sl = price * (1 - 0.10) if direction == "long" else price * (1 + 0.10)
        tp = price * (1 + 0.05) if direction == "long" else price * (1 - 0.05)
        return self.emit_signal(
            ts=ts,
            venue=venue,
            symbol=symbol,
            timeframe=timeframe,  # type: ignore[arg-type]
            direction=direction,  # type: ignore[arg-type]
            pattern_id=pattern_id,
            confluence_score=abs(z),
            sl_price=sl,
            tp_price=tp,
            suggested_size_atr=1.0,
            metadata={
                "pair_signal_id": pair_signal_id,
                "pair_leg": pair_leg,
                "pair_action": pair_action,
                "spread_z": round(z, 4),
                "adf_p_lag": round(adf_p, 4),
                "hedge_ratio": round(hedge, 4),
            },
        )
