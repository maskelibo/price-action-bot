"""HYP-2026-05-16: Regime-Conditional ML — W3 forensik bulgusunun test edilmesi.

Pre-reg: memory/researcher/hypotheses/2026-05-16-regime-conditional-ml.md

Mekanik:
  - In-sample (W1-W5) BTC period_return median = +21.24% (SABIT, pre-reg)
  - regime_mask(window): True if window's BTC period_return < +21.24%
  - Iyi rejim: ML filter aktif (HYP-2026-05-15 sonuclari kullanilir)
  - Kotu rejim: flat T2 (her trade alinir)

W6 hold-out gate:
  - W6 alpha > 0
  - W6 n_taken > 30
  - Random regime null p<0.05

ML v1 walk-forward sonuclari (mevcut JSON'dan):
  W | period_ret | regime_mask | ml_alpha | bl_sharpe | n_taken
  1 | +31.90 | False (pasif) | -0.635 | 2.768 | 123 (ML aktifse)
  2 | +69.45 | False (pasif) | -2.237 | 0.952 | 74
  3 | +13.70 | True (aktif)  | +5.204 | 0.766 | 74
  4 | +21.24 | False (pasif) | -0.255 | 3.694 | 58 (esitlik durumu — pre-reg < kati esit alma)
  5 |  -8.84 | True (aktif)  | +1.376 | 4.457 | 56
  6 | -40.50 | True (aktif)  | +1.407 | 3.405 | 95

Output: reports/research/regime_conditional_ml_results.txt
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

REPORT_OUT = ROOT / "reports" / "research" / "regime_conditional_ml_results.txt"
ML_V1_JSON = ROOT / "reports" / "research" / "ml_meta_v1_results.json"
W3_FORENSIK = ROOT / "reports" / "research" / "w3_forensics.txt"

# Pre-reg SABIT (W1-W5 in-sample BTC period_return median)
W1_W5_PERIOD_RETS = [+31.90, +69.45, +13.70, +21.24, -8.84]
THRESHOLD = float(np.median(W1_W5_PERIOD_RETS))  # = +21.24

# W3 forensik raporundan (kontrol amacli)
WINDOW_PERIOD_RETS = {
    1: +31.90,
    2: +69.45,
    3: +13.70,
    4: +21.24,
    5: -8.84,
    6: -40.50,
}


def regime_mask(period_ret: float, threshold: float = THRESHOLD) -> bool:
    """True = "iyi rejim" (ML filter aktif), False = "kotu rejim" (flat T2)."""
    return period_ret < threshold


def stable_hash(obj) -> str:
    s = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("=" * 86)
    w("HYP-2026-05-16: REGIME-CONDITIONAL ML — W3 FORENSIK TEST")
    w("=" * 86)
    w(f"Generated: {pd.Timestamp.utcnow().isoformat()}")
    w(f"Pre-reg: memory/researcher/hypotheses/2026-05-16-regime-conditional-ml.md")
    w(f"Pre-reg threshold: BTC period_return median(W1-W5) = +{THRESHOLD:.2f}%")
    w("")

    # ML v1 sonuclari yukle
    if not ML_V1_JSON.exists():
        w(f"HATA: {ML_V1_JSON} bulunamadi.")
        return
    with ML_V1_JSON.open() as f:
        ml_v1 = json.load(f)
    per_window = ml_v1["per_window"]
    w(f"ML v1 walk-forward results yuklendi: {len(per_window)} pencere")
    w("")

    # Regime maski uygula per pencere
    w("--- 1) PER-WINDOW REGIME MASK ---")
    w(f"  {'W':>2} {'period_ret':>10} {'regime':>10} {'ml_alpha':>9} {'ml_sh':>7} {'bl_sh':>7} "
      f"{'used_alpha':>10} {'used_n':>6}")
    rows: list[dict] = []
    for r in per_window:
        idx = r["idx"]
        period_ret = WINDOW_PERIOD_RETS[idx]
        is_active = regime_mask(period_ret)
        ml_alpha = r["sharpe_alpha"]
        ml_sh = r["ml_sharpe"]
        bl_sh = r["bl_sharpe"]
        n_oos = r["n_oos"]
        n_taken = r["n_taken"]

        if is_active:
            # ML filter aktif — ml_alpha kullan, n_taken kalir
            used_alpha = ml_alpha
            used_n = n_taken
            regime_str = "AKTIF"
        else:
            # Flat T2 — tum trade'ler alinir, alpha = 0 (baseline ile karsilastirma)
            used_alpha = 0.0  # flat T2 == baseline -> alpha = 0
            used_n = n_oos
            regime_str = "PASIF"

        rows.append({
            "idx": idx,
            "period_ret": period_ret,
            "regime_active": is_active,
            "ml_alpha": ml_alpha,
            "ml_sh": ml_sh,
            "bl_sh": bl_sh,
            "used_alpha": used_alpha,
            "used_n": used_n,
            "n_oos": n_oos,
        })
        w(f"  {idx:>2d} {period_ret:>+10.2f} {regime_str:>10} {ml_alpha:>+9.3f} "
          f"{ml_sh:>+7.3f} {bl_sh:>+7.3f} {used_alpha:>+10.3f} {used_n:>6d}")

    df_res = pd.DataFrame(rows)

    # In-sample (W1-W5) regime istatistik
    w("")
    w("--- 2) IN-SAMPLE (W1-W5) REGIME ANALYSIS ---")
    is_w15 = df_res[df_res["idx"] <= 5]
    n_active_is = int(is_w15["regime_active"].sum())
    w(f"In-sample regime aktif pencere sayisi: {n_active_is}/5 (target >=2)")
    if n_active_is >= 2:
        active_mean = float(is_w15[is_w15["regime_active"]]["used_alpha"].mean())
        passive_mean = float(is_w15[~is_w15["regime_active"]]["used_alpha"].mean()) if (~is_w15["regime_active"]).any() else 0.0
        w(f"In-sample regime AKTIF mean alpha: {active_mean:+.3f}")
        w(f"In-sample regime PASIF mean alpha (flat T2): {passive_mean:+.3f}")
        w(f"In-sample combined mean alpha (regime mask uygulanmis): {float(is_w15['used_alpha'].mean()):+.3f}")
    else:
        w("UYARI: In-sample <2 aktif pencere — regime mask cok sıkı, generalize edilemez.")

    # W6 hold-out gate
    w("")
    w("--- 3) W6 HOLD-OUT GATE ---")
    w6 = df_res[df_res["idx"] == 6].iloc[0]
    w6_active = bool(w6["regime_active"])
    w6_alpha = float(w6["used_alpha"])
    w6_n = int(w6["used_n"])
    w(f"W6 BTC period_ret: {w6['period_ret']:+.2f}%")
    w(f"W6 regime mask: {'AKTIF (ML filter)' if w6_active else 'PASIF (flat T2)'}")
    w(f"W6 alpha (regime mask uygulanmis): {w6_alpha:+.3f}")
    w(f"W6 n_taken: {w6_n}")
    gate_w6_alpha = w6_alpha > 0
    gate_w6_n = w6_n > 30
    w(f"  Gate: W6 alpha > 0 -> {'PASS' if gate_w6_alpha else 'FAIL'}")
    w(f"  Gate: W6 n_taken > 30 -> {'PASS' if gate_w6_n else 'FAIL'}")

    # Random regime null
    w("")
    w("--- 4) RANDOM REGIME NULL TEST (1000 iter) ---")
    rng = np.random.default_rng(42)
    real_active_idx = df_res[df_res["regime_active"]].index.tolist()
    real_alpha_mean = float(df_res.loc[real_active_idx, "ml_alpha"].mean()) if real_active_idx else 0.0
    n_real_active = len(real_active_idx)
    w(f"Real regime aktif pencere sayisi: {n_real_active}")
    w(f"Real regime aktif mean ml_alpha: {real_alpha_mean:+.3f}")

    null_alphas = []
    n_total = len(df_res)
    if n_real_active > 0:
        for _ in range(1000):
            random_active = rng.choice(n_total, size=n_real_active, replace=False)
            null_alpha = float(df_res.iloc[random_active]["ml_alpha"].mean())
            null_alphas.append(null_alpha)
        p_null = float(np.mean([a >= real_alpha_mean for a in null_alphas]))
        w(f"Random null mean: {np.mean(null_alphas):+.3f}, std: {np.std(null_alphas):.3f}")
        w(f"Real alpha {real_alpha_mean:+.3f} vs null distribution p-value: {p_null:.4f}")
        gate_null = p_null < 0.05
        w(f"  Gate: random null p < 0.05 -> {'PASS' if gate_null else 'FAIL'}")
    else:
        p_null = 1.0
        gate_null = False
        w("Real regime aktif pencere yok — null test atlandi.")

    # Combined performance
    w("")
    w("--- 5) COMBINED PERFORMANCE (regime-conditional vs ML always vs flat T2) ---")
    mean_alpha_regime = float(df_res["used_alpha"].mean())
    mean_alpha_ml_always = float(df_res["ml_alpha"].mean())
    mean_alpha_flat_t2 = 0.0  # baseline definition
    w(f"Mean alpha — regime conditional: {mean_alpha_regime:+.4f}")
    w(f"Mean alpha — ML always (baseline ML v1):  {mean_alpha_ml_always:+.4f}")
    w(f"Mean alpha — flat T2 (always all trades): {mean_alpha_flat_t2:+.4f}")

    # Bootstrap CI for regime-conditional
    if len(df_res) > 1:
        bootstrap_means = []
        for _ in range(2000):
            sample = rng.choice(df_res["used_alpha"].values, size=len(df_res), replace=True)
            bootstrap_means.append(float(sample.mean()))
        ci_lo = float(np.percentile(bootstrap_means, 2.5))
        ci_hi = float(np.percentile(bootstrap_means, 97.5))
        w(f"Bootstrap CI(95%) for regime-conditional alpha: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    else:
        ci_lo = ci_hi = 0.0

    # 6) Hold-out genelleme test (KH-2): W6 alpha vs ML always W6 alpha
    w("")
    w("--- 6) KH-2 KONTROLU (W6 regime aktif mi, edge sebebi mi?) ---")
    if w6_active:
        w(f"W6 regime AKTIF — used_alpha == ml_alpha = {w6['ml_alpha']:+.3f}")
        w(f"  Eger regime PASIF olsaydi alpha=0 olurdu — ML filter sebebiyle +{w6['ml_alpha']:+.3f}")
        w(f"  Bu KH-2'yi RED yapar (regime sebebi degil ML filter sebebi)")
        kh2_concern = True
    else:
        w("W6 regime PASIF — used_alpha=0 (flat T2)")
        w("  Eger regime AKTIF olsaydi alpha=ml_v1 = +1.407 olurdu")
        w("  Regime mask edge'i YOK ediyor — fragile karar")
        kh2_concern = True

    # 7) HARD gate karari
    w("")
    w("--- 7) HARD GATE KARARI ---")
    gates_failed: list[str] = []
    if not gate_w6_alpha:
        gates_failed.append(f"NH1 W6 alpha {w6_alpha:+.3f} <= 0")
    if not gate_w6_n:
        gates_failed.append(f"NH2 W6 n_taken {w6_n} <= 30")
    if not gate_null:
        gates_failed.append(f"NH3 random null p {p_null:.4f} >= 0.05")
    if n_active_is < 2:
        gates_failed.append(f"NH4 in-sample regime aktif pencere {n_active_is} < 2")

    if gates_failed:
        w(f"\nGATES FAILED ({len(gates_failed)}/4):")
        for g in gates_failed:
            w(f"  [X] {g}")
        verdict = "RED"
    else:
        w("\nTUM GATES PASS")
        verdict = "PASS"

    w(f"\nKARAR: {verdict}")

    # Reproducibility
    w("")
    w("--- REPRODUCIBILITY ---")
    w(f"git_hash: 5f4da50c7025bde314bf6f90381748b2f3a13b08")
    cfg = {
        "threshold": THRESHOLD,
        "in_sample_window_indices": list(range(1, 6)),
        "metric": "BTC_period_return_pct",
        "rule": "active if period_ret < threshold",
        "ml_v1_results_ref": str(ML_V1_JSON),
        "forensik_ref": str(W3_FORENSIK),
    }
    w(f"config_hash: {stable_hash(cfg)}")
    w(f"run_timestamp: {pd.Timestamp.utcnow().isoformat()}")

    # JSON dump
    json_path = REPORT_OUT.with_suffix(".json")
    json_path.write_text(json.dumps({
        "config": cfg,
        "verdict": verdict,
        "gates_failed": gates_failed,
        "per_window": df_res.to_dict("records"),
        "w6_holdout": {
            "alpha": w6_alpha,
            "n_taken": w6_n,
            "regime_active": w6_active,
        },
        "in_sample": {
            "n_active": n_active_is,
            "active_mean_alpha": float(is_w15[is_w15["regime_active"]]["used_alpha"].mean()) if n_active_is > 0 else 0.0,
            "passive_mean_alpha": float(is_w15[~is_w15["regime_active"]]["used_alpha"].mean()) if (~is_w15["regime_active"]).any() else 0.0,
        },
        "random_null_p": p_null,
        "regime_conditional_mean_alpha": mean_alpha_regime,
        "ml_always_mean_alpha": mean_alpha_ml_always,
        "bootstrap_ci": [ci_lo, ci_hi],
        "kh2_concern": kh2_concern,
    }, indent=2, default=str), encoding="utf-8")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    w(f"\nRapor: {REPORT_OUT}")
    w(f"JSON:  {json_path}")


if __name__ == "__main__":
    main()
