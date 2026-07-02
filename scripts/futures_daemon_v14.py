"""V14 FRONTIER Testnet Daemon — 19-sym WIDESTOP + PYRAMID-ON + F2/F4 regime.

PURPOSE
-------
v13 wrapper kalıbında ince yürütme sarmalayıcısı. v14 frontier config'i
(configs/risk_phoenix_scalp_15m_v14_frontier.yaml) EXPLICIT yükler ve startup'ta
DOĞRULAR (audit BLOCKER-3: v13'ün setdefault tuzağı — yanlış config sessizce
koşuyordu). Exit yapısı backtest paritesi: engine-native 30/30/40 + %1.5 trail.

v13'TEN FARKLAR
---------------
1. Config     : v14_frontier (risk 0.62%, d04/w08, PYRAMID ON, 19 sembol)
2. HTF filtre : YOK — v14 backtest'i HTF içermiyor (parite). F2/F4 rejim
                filtreleri RiskOfficer YAML yolundan zaten aktif.
3. Doğrulama  : startup'ta YAML'dan pyramid_enabled/risk/sl_pct_min/breaker
                değerleri assert edilir — uyuşmazlıkta ABORT (sessiz parite
                felaketi yerine gürültülü ölüm).
4. Breaker    : PA_BOT_NAME=v14 → bot-bazlı temiz state (BLOCKER-2 fix'i).

DEĞİŞMEYENLER (v13'ten miras)
-----------------------------
- BASELINE exit patch: TP1=30%@1R / TP2=30%@1.5R / runner=40%, trail %1.5
- Sizing: fixed-fraction (başlangıç-equity, non-compounding)
- DMS / kill-switch / idempotency / N-tick orphan koruması / watchdog katmanları
- PA_LIVE_CONFIRM ASLA set edilmez — testnet/paper only

ACTIVATION (testnet only)
-------------------------
    python scripts/futures_daemon_v14.py --timeframe 15m
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Environment: EXPLICIT (BLOCKER-3 — setdefault sessiz tuzağı yasak) ───────
# FAZ seçimi: PA_V14_PHASE=1 (default, flat r0.62) | 3 (final 5-strateji
# +ağırlık+throttle, tur-15 backtest +26.1/ay). Her faz kendi beklenen
# değerleriyle startup-verify edilir — yanlış config = gürültülü ABORT.
_PHASE = os.environ.get("PA_V14_PHASE", "1").strip()
_PHASE_CONFIGS = {
    "1": ("configs/risk_phoenix_scalp_15m_v14_frontier.yaml", 0.0062, "frontier"),
    "3": ("configs/risk_phoenix_scalp_15m_v14p3.yaml", 0.0075, "p3"),
    # v15p2 (2026-07-02, Principal onayı): grimes+vsa konsantre filo, risk 0.010,
    # PYRAMID OFF (validasyonla birebir — robustness TAM PASS + lookahead-audit GO).
    # 3. eleman artık mode-string (eski bool → "frontier"/"p3"/"v15p2").
    "v15p2": ("configs/risk_phoenix_scalp_15m_v15p2.yaml", 0.010, "v15p2"),
}
if _PHASE not in _PHASE_CONFIGS:
    raise SystemExit(f"[V14] PA_V14_PHASE={_PHASE} tanımsız (1 / 3 / v15p2)")
V14_CONFIG, _EXPECT_RISK, _EXPECT_P3 = _PHASE_CONFIGS[_PHASE]
_prev_cfg = os.environ.get("PA_15M_CONFIG")
if _prev_cfg and _prev_cfg != V14_CONFIG:
    sys.stderr.write(
        f"[V14] UYARI: PA_15M_CONFIG={_prev_cfg} override ediliyor → {V14_CONFIG}\n"
    )
# v15p2 → ayrı bot-adı: temiz journal (futures_journal_v15p2.duckdb) + temiz
# breaker state (Principal "temiz başlangıç" direktifi, 2026-07-02).
os.environ["PA_BOT_NAME"] = "v15p2" if _EXPECT_P3 == "v15p2" else "v14"
os.environ["PA_RUN_MODE"] = "paper"
os.environ["PA_15M_CONFIG"] = V14_CONFIG
os.environ.setdefault("PA_DUCKDB_READ_ONLY", "true")

# SAFETY GATE: v14 testnet wrapper'ı live mode ile ASLA koşmaz.
if os.environ.get("PA_LIVE_CONFIRM", "").strip():
    raise SystemExit(
        "[V14 SAFETY] PA_LIVE_CONFIRM set — v14 testnet wrapper live koşmayı reddeder."
    )

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass

_LOG_TAG = "v15p2" if _EXPECT_P3 == "v15p2" else "v14"
LOG_FILE = ROOT / "logs" / f"futures_daemon_{_LOG_TAG}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
PID_FILE = ROOT / "logs" / f"{_LOG_TAG}_daemon.pid"


def _vlog(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    line = f"[{ts}] [V14] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ── STARTUP DOĞRULAMA (BLOCKER-3): config gerçekten v14 mü? ──────────────────
def _verify_v14_config() -> dict:
    import yaml as _yaml

    cfg_path = ROOT / V14_CONFIG
    if not cfg_path.exists():
        raise SystemExit(f"[V14 VERIFY] Config yok: {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f) or {}

    checks = {
        "position_sizing.risk_per_trade": (
            float(cfg.get("position_sizing", {}).get("risk_per_trade", 0)), _EXPECT_RISK),
        "position_sizing.backtest_risk_pct": (
            float(cfg.get("position_sizing", {}).get("backtest_risk_pct", 0)), _EXPECT_RISK),
        "execution.sl_pct_min": (
            float(cfg.get("execution", {}).get("sl_pct_min", 0)), 0.025),
        "drawdown_breakers.daily_loss_pct": (
            float(cfg.get("drawdown_breakers", {}).get("daily_loss_pct", 0)), 0.04),
        "drawdown_breakers.weekly_loss_pct": (
            float(cfg.get("drawdown_breakers", {}).get("weekly_loss_pct", 0)), 0.08),
        "strategy_portfolio.pyramid_enabled": (
            bool(cfg.get("strategy_portfolio", {}).get("pyramid_enabled", False)),
            _EXPECT_P3 != "v15p2"),  # v15p2 → pyramid OFF beklenir; diğerleri ON
    }
    if _EXPECT_P3 == "p3":
        ps = cfg.get("position_sizing", {})
        checks["strategy_risk_weights.vsa"] = (
            float((ps.get("strategy_risk_weights") or {}).get("vsa_climax_test", 0)), 1.4)
        checks["strategy_risk_weights.grimes"] = (
            float((ps.get("strategy_risk_weights") or {}).get("grimes_abc_pullback", 0)), 1.0)
        checks["dd_throttle.enabled"] = (
            bool((ps.get("dd_throttle") or {}).get("enabled", False)), True)
        checks["strategies_enabled (5)"] = (
            len(cfg.get("strategies_enabled") or []), 5)
    elif _EXPECT_P3 == "v15p2":
        # v15p2 konsantre filo: grimes+vsa EŞİT (1.0/1.0), 2 strateji, dd_throttle ON.
        ps = cfg.get("position_sizing", {})
        checks["strategy_risk_weights.vsa"] = (
            float((ps.get("strategy_risk_weights") or {}).get("vsa_climax_test", 0)), 1.0)
        checks["strategy_risk_weights.grimes"] = (
            float((ps.get("strategy_risk_weights") or {}).get("grimes_abc_pullback", 0)), 1.0)
        checks["dd_throttle.enabled"] = (
            bool((ps.get("dd_throttle") or {}).get("enabled", False)), True)
        checks["strategies_enabled (2)"] = (
            len(cfg.get("strategies_enabled") or []), 2)
    bad = [(k, got, want) for k, (got, want) in checks.items() if got != want]
    if bad:
        for k, got, want in bad:
            _vlog(f"VERIFY_FAIL: {k} = {got!r}, beklenen {want!r}")
        raise SystemExit("[V14 VERIFY] Config v14 frontier değil — ABORT (BLOCKER-3 gate)")
    n_syms = len(cfg.get("strategy_portfolio", {}).get("symbols", []))
    _n_strat = len(cfg.get("strategies_enabled") or []) or 4
    _vlog(
        f"VERIFY_OK: faz={_PHASE} risk={_EXPECT_RISK*100:.2f}% d04/w08 "
        f"sl_min=0.025 pyramid={'OFF' if _EXPECT_P3 == 'v15p2' else 'ON'} "
        f"symbols={n_syms} strategies={_n_strat}"
    )
    return cfg


_verify_v14_config()

# ── Daemon import + BASELINE exit patch (v13 ile birebir — backtest paritesi) ─
try:
    import scripts.futures_daemon as _daemon
    import scripts.futures_daemon_v13 as _v13mod  # patch fonksiyonunu yeniden kullan
    import scripts.futures_trade_daily as _ftd

    _BASELINE_TRAIL_PCT = float(os.environ.get("PA_V14_TRAIL_PCT", "0.015"))
    _old_trail = _daemon._TRAIL_PCT
    _daemon._TRAIL_PCT = _BASELINE_TRAIL_PCT
    _vlog(f"PATCHED _TRAIL_PCT: {_old_trail} → {_daemon._TRAIL_PCT} (BASELINE %1.5)")

    # v13 wrapper import'u kendi patch'ini _ftd'ye zaten uyguladı (30/30/40).
    if getattr(_ftd.place_protection_orders, "__name__", "") != "_v13_place_protection_orders":
        raise RuntimeError("place_protection_orders 30/30/40 patch'i uygulanmadı")
    _vlog("PATCH OK: place_protection_orders 30/30/40 (v13 BASELINE, yeniden kullanıldı)")

    # PARITE: v13 import'u _scan_signals_15m'e HTF filtresini import-time enjekte
    # ediyor (v13:388). v14 backtest'i HTF İÇERMİYOR → orijinal scan'i geri koy.
    _daemon._scan_signals_15m = _v13mod._original_scan_15m
    if hasattr(_v13mod, "_original_scan_5m") and hasattr(_daemon, "_scan_signals_5m"):
        _daemon._scan_signals_5m = _v13mod._original_scan_5m
    _vlog("UNPATCHED: HTF 1d filtresi geri alındı (v14 backtest paritesi — HTF yok)")

    # PYRAMID doğrulama: router init'inin gerçekten açılacağını logla
    if _EXPECT_P3 == "v15p2":
        # v15p2 PYRAMID OFF bekler (validasyonla birebir). Router init edilmemeli.
        if _daemon._pyramid_enabled_15m():
            raise RuntimeError("v15p2 pyramid-OFF bekler ama config ON okudu — ABORT")
        _vlog("PYRAMID: v15p2 → OFF doğrulandı (PyramidRouter init EDİLMEYECEK)")
    elif not _daemon._pyramid_enabled_15m():
        raise RuntimeError("pyramid_enabled=false okundu — v14 tezi pyramid-ON gerektirir")
    else:
        _vlog("PYRAMID: enabled=true doğrulandı (PyramidRouter init edilecek)")
except Exception as _patch_err:
    _vlog(f"PATCH_FAIL: {_patch_err} — ABORT")
    raise SystemExit(f"V14 daemon patch failed: {_patch_err}") from _patch_err


def _write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def _print_banner() -> None:
    _vlog("=" * 65)
    _vlog("V14 FRONTIER TESTNET DAEMON — 19sym WIDESTOP + PYRAMID + F2/F4")
    _vlog(f"  Config      : {V14_CONFIG} (startup-verified)")
    _vlog("  Journal     : data/futures_journal_v14.duckdb")
    _vlog("  Breaker     : logs/risk/futures_breaker_state_15m_v14.json (temiz)")
    _vlog("  Entry gates : WIDESTOP sl>=0.025 + conf>=0.25 + F2/F4 regime (RO yolu)")
    _vlog("  Exit        : BASELINE trail=1.5% / TP1=30%@1R / TP2=30%@1.5R / runner=40%")
    _vlog("  Pyramid     : ON — triggers [1.0,1.5]R, sizes [0.50,0.30], leg-fill SL resize")
    _vlog("  Sizing      : FIXED-FRACTION 0.62% (non-compounding)")
    _vlog("  Beklenti    : dürüst bant +%15-18.5/ay, DD bandı -%19..-22 (hardened)")
    _vlog("  PA_LIVE_CONFIRM: NOT SET — testnet only")
    _vlog("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V14 Frontier Testnet Daemon")
    parser.add_argument("--once", action="store_true", help="Tek bar döngüsü (test)")
    parser.add_argument("--timeframe", choices=["15m"], default="15m")
    args = parser.parse_args()

    _write_pid()
    _print_banner()
    _vlog(f"Delegating to futures_daemon.run_15m_mode(once={args.once})")
    _daemon.run_15m_mode(once=args.once)
