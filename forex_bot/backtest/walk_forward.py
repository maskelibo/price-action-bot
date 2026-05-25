"""Walk-forward analysis: 6 month train, 3 month test, rolling window."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

import pandas as pd


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardRunner:
    train_months: int = 6
    test_months: int = 3

    def build_windows(self, full_start: pd.Timestamp, full_end: pd.Timestamp) -> list[WalkForwardWindow]:
        windows = []
        cur_train_start = full_start
        while True:
            tr_end = cur_train_start + pd.DateOffset(months=self.train_months)
            te_end = tr_end + pd.DateOffset(months=self.test_months)
            if te_end > full_end:
                break
            windows.append(WalkForwardWindow(
                train_start=cur_train_start, train_end=tr_end,
                test_start=tr_end, test_end=te_end,
            ))
            cur_train_start = cur_train_start + pd.DateOffset(months=self.test_months)
        return windows

    def run(
        self,
        df: pd.DataFrame,
        full_start: pd.Timestamp,
        full_end: pd.Timestamp,
        run_window_fn: Callable[[pd.DataFrame, pd.DataFrame], dict],
    ) -> list[dict]:
        windows = self.build_windows(full_start, full_end)
        results = []
        for w in windows:
            train = df.loc[w.train_start: w.train_end]
            test = df.loc[w.test_start: w.test_end]
            kpis = run_window_fn(train, test)
            kpis.update({
                "train_start": str(w.train_start.date()),
                "train_end": str(w.train_end.date()),
                "test_start": str(w.test_start.date()),
                "test_end": str(w.test_end.date()),
            })
            results.append(kpis)
        return results
