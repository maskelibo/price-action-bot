"""Research-factory prompt safety regressions."""

from __future__ import annotations

from price_action.agents.researcher import _build_hypothesis_prompt


def test_hypothesis_prompt_rejects_instead_of_manufacturing_curve_fit() -> None:
    prompt = _build_hypothesis_prompt("1h breakout", "[#1] causal reference")

    lowered = prompt.lower()
    assert "curve-fit şüphesi yarat" not in lowered
    assert "curve-fit suphesi yarat" not in lowered
    assert "curve-fit üretme" in lowered
    assert "kanıtla ve hipotezi reddet" in lowered
    assert "her sayısal iddia aynı satırda" in lowered
    assert "accept gates yalnız typed" in lowered
    assert "[#1] causal reference" in prompt
