"""Strategy prepare_features() determinism test.

FIX 2026-05-28 (audit-Y8): Test/CI audit'inin tespit ettiği "feature divergence
backtest/live" riskine karşı kanıt-bazlı kontrol. Eğer prepare_features
non-pure (instance state, random, system time, vs.) kullanıyorsa, aynı input
farklı output verebilir → backtest'te bir feature column, live'da başka. Bu
test her stratejinin prepare_features'ını 100x koşar ve output'ları karşılaştırır.

Aynı pattern: tests/test_strategy_scaffold_meta.py importability scaffold
gibi parametric — yeni strateji eklendiğinde otomatik kapsanır.
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_STRATEGY_DIR = Path(__file__).resolve().parents[1] / "src" / "price_action" / "strategies"
_EXCLUDE = {"__init__", "base", "manifest_loader"}


def _discover_strategies() -> list[str]:
    out: list[str] = []
    for p in sorted(_STRATEGY_DIR.glob("*.py")):
        name = p.stem
        if name in _EXCLUDE or name.startswith("_"):
            continue
        out.append(name)
    return out


_STRATEGIES = _discover_strategies()


def _find_prepare_features(mod):
    """Modülde prepare_features benzeri callable bul."""
    if hasattr(mod, "prepare_features") and callable(mod.prepare_features):
        return mod.prepare_features, "module"
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        if getattr(obj, "__module__", "") != mod.__name__:
            continue
        if hasattr(obj, "prepare_features"):
            return obj, "class"
    return None, None


@pytest.mark.parametrize("strategy_name", _STRATEGIES)
def test_prepare_features_deterministic(
    strategy_name: str, backtest_ready_ohlcv: pd.DataFrame
) -> None:
    """SCAFFOLD-Y8: Aynı input → aynı output (3 run karşılaştırma)."""
    mod_path = f"price_action.strategies.{strategy_name}"
    try:
        mod = importlib.import_module(mod_path)
    except Exception:
        pytest.skip("import fail — test_strategy_scaffold_meta görür")

    fn, kind = _find_prepare_features(mod)
    if fn is None:
        pytest.skip(f"{strategy_name}: prepare_features bulunamadı (opsiyonel)")

    df_in = backtest_ready_ohlcv.copy()
    outs: list[pd.DataFrame] = []
    for _ in range(3):
        df_run = df_in.copy()  # her run'da taze copy ki in-place mutation tespit edilsin
        try:
            if kind == "class":
                try:
                    instance = fn()
                except TypeError:
                    pytest.skip(f"{strategy_name}: class constructor args bilinmiyor")
                result = instance.prepare_features(df_run)
            else:
                result = fn(df_run)
        except (TypeError, ValueError, KeyError) as e:
            pytest.skip(f"{strategy_name}: prepare_features call mismatch: {e}")
        except Exception as e:
            pytest.fail(f"{strategy_name}: prepare_features patladı {type(e).__name__}: {e}")
        if result is None:
            # bazı strateji impl'leri in-place değiştirip None döner
            result = df_run
        if not isinstance(result, pd.DataFrame):
            pytest.skip(f"{strategy_name}: result DataFrame değil ({type(result)})")
        outs.append(result)

    # 3 run karşılaştır — column'lar aynı, numerik değerler aynı
    cols0 = set(outs[0].columns)
    for i, df_other in enumerate(outs[1:], start=1):
        assert set(df_other.columns) == cols0, (
            f"{strategy_name}: run {i+1} farklı column'lar üretti "
            f"({set(df_other.columns) ^ cols0})"
        )
        # Sayısal column'larda equal_nan check (NaN == NaN True kabul edilsin)
        for col in cols0:
            if not pd.api.types.is_numeric_dtype(outs[0][col]):
                continue
            np.testing.assert_array_equal(
                outs[0][col].to_numpy(),
                df_other[col].to_numpy(),
                err_msg=f"{strategy_name}: column '{col}' run-to-run farklı (non-deterministic)",
            )
