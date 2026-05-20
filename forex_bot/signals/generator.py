"""SignalGenerator orchestrates strategies, session/news filters, and emits Signals.

Flow per bar t:
    1. Compute features (ATR, EMA, swings, SMC, volume proxy).
    2. For each enabled strategy: collect raw candidate.
    3. Apply session filter (PAIR_SESSION_SCORE >= min_score).
    4. Apply news guard (blackout window).
    5. Compute confluence score.
    6. Emit Signal if confluence >= threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from ..contracts import Signal
from ..indicators.confluence import confluence_score, ConfluenceWeights
from ..indicators.ohlc import atr, ema
from ..indicators.volume_proxy import participation_score
from ..news.guard import NewsGuard
from ..session.tagger import tag_session_series, session_score_for_pair
from ..strategies.base import Strategy


@dataclass
class GeneratorConfig:
    confluence_threshold: float = 0.55
    min_session_score: float = 0.50
    use_news_guard: bool = True
    weights: ConfluenceWeights = field(default_factory=ConfluenceWeights)


@dataclass
class SignalGenerator:
    pair: str
    strategies: list[Strategy]
    config: GeneratorConfig = field(default_factory=GeneratorConfig)
    news_guard: Optional[NewsGuard] = None

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["atr14"] = atr(df, 14)
        df["ema20"] = ema(df["close"], 20)
        df["ema50"] = ema(df["close"], 50)
        df["ema200"] = ema(df["close"], 200)
        df["participation"] = participation_score(df)
        df["session"] = tag_session_series(pd.DatetimeIndex(df.index)).values
        return df

    def generate(self, df: pd.DataFrame) -> list[Signal]:
        df_feat = self.prepare_features(df)
        signals: list[Signal] = []
        for strat in self.strategies:
            candidates = strat.generate_signals(df_feat, self.pair)
            for c in candidates:
                sess_score = session_score_for_pair(self.pair, c.session)
                if sess_score < self.config.min_session_score:
                    continue
                if self.config.use_news_guard and self.news_guard is not None:
                    blocked, _evt = self.news_guard.is_blackout(c.ts, self.pair)
                    if blocked:
                        continue
                # recompute confluence with weighting
                conf = confluence_score(
                    pattern_hit=c.meta.get("pattern_hit", True),
                    structure_hit=c.meta.get("structure_hit", False),
                    smc_hit=c.meta.get("smc_hit", False),
                    volume_score=c.meta.get("volume_score", 0.5),
                    session_score=sess_score,
                    trend_aligned=c.meta.get("trend_aligned", False),
                    weights=self.config.weights,
                )
                if conf < self.config.confluence_threshold:
                    continue
                c.confluence = conf
                signals.append(c)
        return signals
