"""Phase-selected 15m paper daemon wrapper with startup parity checks.

PURPOSE
-------
v13 wrapper kalıbında ince yürütme sarmalayıcısı. ``PA_V14_PHASE`` ile seçilen
config'i EXPLICIT yükler ve startup'ta doğrular (audit BLOCKER-3: v13'ün
setdefault tuzağı — yanlış config sessizce koşuyordu). TP merdiveni
engine-native 30/30/40'tır; paper runner halen %1.5 percentage-trail proxy
kullanır. Bu, ATR-chandelier 1.5x paritesi değildir.

v13'TEN FARKLAR
---------------
1. Config     : faza göre v14 frontier / v14p3 / v15p2 (startup-verified)
2. HTF filtre : YOK — v14 backtest'i HTF içermiyor (parite). F2/F4 rejim
                filtreleri RiskOfficer YAML yolundan zaten aktif.
3. Doğrulama  : startup'ta YAML'dan pyramid_enabled/risk/sl_pct_min/breaker
                değerleri assert edilir — uyuşmazlıkta ABORT (sessiz parite
                felaketi yerine gürültülü ölüm).
4. Breaker    : PA_BOT_NAME=v14 veya v15p2 → bot-bazlı state (BLOCKER-2 fix'i).

DEĞİŞMEYENLER (v13'ten miras)
-----------------------------
- BASELINE exit patch: TP1=30%@1R / TP2=30%@1.5R / runner=40%
- E13 kilidi: %1.5 PCT trail canlıda kalır; ATR 1.5x, 40 temiz kapanışa kadar shadow-only
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
    sys.stderr.write(f"[V14] UYARI: PA_15M_CONFIG={_prev_cfg} override ediliyor → {V14_CONFIG}\n")
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
import warnings  # noqa: E402 (kasıtlı: env-setup import'lardan önce — wrapper deseni)

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(ROOT / ".env", override=False)
except Exception as _de_err:
    # log-only: .env yüklenemezse daemon anahtar/telegram'sız başlar — görünür olsun
    # (_vlog henüz tanımsız; launchd stderr'i yakalar)
    sys.stderr.write(f"[V14] dotenv load FAIL: {_de_err}\n")

from price_action.runtime_paths import resolve_runtime_root  # noqa: E402

RUNTIME_ROOT = resolve_runtime_root(ROOT)
_LOG_TAG = "v15p2" if _EXPECT_P3 == "v15p2" else "v14"
LOG_FILE = RUNTIME_ROOT / "logs" / f"futures_daemon_{_LOG_TAG}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
PID_FILE = RUNTIME_ROOT / "logs" / f"{_LOG_TAG}_daemon.pid"


def _vlog(msg: str) -> None:
    ts = datetime.now(UTC).strftime("%H:%M:%SZ")
    # W1-LOW fix (2026-07-10): '[V14]' literal'i v15p2 koşarken yalan söylüyordu;
    # tüketici envanteri temiz (repo-geniş '\[V14\]' grep: 0 tüketici) → dinamik tag.
    line = f"[{ts}] [{_LOG_TAG.upper()}] {msg}"
    # Import-time parity probes and unit tests must not impersonate a daemon
    # restart in the production log.  The actual launchd entry executes this
    # file as ``__main__``; module imports retain stderr diagnostics only.
    file_log_disabled = os.environ.get("PA_DISABLE_FILE_LOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if __name__ == "__main__" and not file_log_disabled:
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
            float(cfg.get("position_sizing", {}).get("risk_per_trade", 0)),
            _EXPECT_RISK,
        ),
        "position_sizing.backtest_risk_pct": (
            float(cfg.get("position_sizing", {}).get("backtest_risk_pct", 0)),
            _EXPECT_RISK,
        ),
        "execution.sl_pct_min": (float(cfg.get("execution", {}).get("sl_pct_min", 0)), 0.025),
        "drawdown_breakers.daily_loss_pct": (
            float(cfg.get("drawdown_breakers", {}).get("daily_loss_pct", 0)),
            0.04,
        ),
        "drawdown_breakers.weekly_loss_pct": (
            float(cfg.get("drawdown_breakers", {}).get("weekly_loss_pct", 0)),
            0.08,
        ),
        "strategy_portfolio.pyramid_enabled": (
            bool(cfg.get("strategy_portfolio", {}).get("pyramid_enabled", False)),
            _EXPECT_P3 != "v15p2",
        ),  # v15p2 → pyramid OFF beklenir; diğerleri ON
    }
    if _EXPECT_P3 == "p3":
        ps = cfg.get("position_sizing", {})
        checks["strategy_risk_weights.vsa"] = (
            float((ps.get("strategy_risk_weights") or {}).get("vsa_climax_test", 0)),
            1.4,
        )
        checks["strategy_risk_weights.grimes"] = (
            float((ps.get("strategy_risk_weights") or {}).get("grimes_abc_pullback", 0)),
            1.0,
        )
        checks["dd_throttle.enabled"] = (
            bool((ps.get("dd_throttle") or {}).get("enabled", False)),
            True,
        )
        checks["strategies_enabled (5)"] = (len(cfg.get("strategies_enabled") or []), 5)
    elif _EXPECT_P3 == "v15p2":
        # v15p2 konsantre filo: grimes+vsa EŞİT (1.0/1.0), 2 strateji, dd_throttle ON.
        ps = cfg.get("position_sizing", {})
        checks["strategy_risk_weights.vsa"] = (
            float((ps.get("strategy_risk_weights") or {}).get("vsa_climax_test", 0)),
            1.0,
        )
        checks["strategy_risk_weights.grimes"] = (
            float((ps.get("strategy_risk_weights") or {}).get("grimes_abc_pullback", 0)),
            1.0,
        )
        checks["dd_throttle.enabled"] = (
            bool((ps.get("dd_throttle") or {}).get("enabled", False)),
            True,
        )
        checks["strategies_enabled (2)"] = (len(cfg.get("strategies_enabled") or []), 2)
        _vt = cfg.get("vol_target") or {}
        checks["vol_target.enabled"] = (bool(_vt.get("enabled", False)), True)
        checks["vol_target.target_atr_pct"] = (float(_vt.get("target_atr_pct", 0)), 0.010)
        checks["vol_target.min_factor"] = (float(_vt.get("min_factor", 0)), 0.20)
        checks["vol_target.max_factor"] = (float(_vt.get("max_factor", 0)), 1.50)
    bad = [(k, got, want) for k, (got, want) in checks.items() if got != want]
    if bad:
        for k, got, want in bad:
            _vlog(f"VERIFY_FAIL: {k} = {got!r}, beklenen {want!r}")
        raise SystemExit("[V14 VERIFY] Config v14 frontier değil — ABORT (BLOCKER-3 gate)")
    n_syms = len(cfg.get("strategy_portfolio", {}).get("symbols", []))
    _n_strat = len(cfg.get("strategies_enabled") or []) or 4
    _vlog(
        f"VERIFY_OK: faz={_PHASE} risk={_EXPECT_RISK * 100:.2f}% d04/w08 "
        f"sl_min=0.025 pyramid={'OFF' if _EXPECT_P3 == 'v15p2' else 'ON'} "
        f"symbols={n_syms} strategies={_n_strat}"
    )
    return cfg


_VERIFIED_CONFIG = _verify_v14_config()

# ── Daemon import + BASELINE exit patch (v13 ile birebir — backtest paritesi) ─
try:
    import scripts.futures_daemon as _daemon
    import scripts.futures_daemon_v13 as _v13mod  # patch fonksiyonunu yeniden kullan
    import scripts.futures_trade_daily as _ftd

    _BASELINE_TRAIL_PCT = float(os.environ.get("PA_V14_TRAIL_PCT", "0.015"))
    _old_trail = _daemon._TRAIL_PCT
    _daemon._TRAIL_PCT = _BASELINE_TRAIL_PCT
    _vlog(
        f"PATCHED _TRAIL_PCT: {_old_trail} → {_daemon._TRAIL_PCT} "
        "(PCT proxy %1.5; ATR 1.5x DEĞİL, E13 shadow-only)"
    )

    # v13 import'u legacy protection wrapper'ını _ftd üzerinde yan etkiyle
    # kurar. Canonical fonksiyon artık kendi içinde 30/30/40 + TP1@1R +
    # deterministic client-id/reconcile güvenliğini taşıyor; eski clone bu
    # korumaları baypas eder. HTF scan snapshot'larını aldıktan hemen sonra
    # canonical nesneyi geri yükle ve identity ile doğrula.
    _ftd.place_protection_orders = _v13mod._original_place_protection_orders
    if _ftd.place_protection_orders is not _v13mod._original_place_protection_orders:
        raise RuntimeError("canonical place_protection_orders geri yüklenemedi")
    if getattr(_ftd.place_protection_orders, "__name__", "") != "place_protection_orders":
        raise RuntimeError("canonical place_protection_orders identity doğrulanamadı")
    _vlog("PATCH OK: canonical protection 30/30/40 + TP1@1R + deterministic reconcile")

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
    except Exception as e:
        _vlog(f"PID_WRITE_FAIL: {e}")  # log-only: PID dosyası izleme-amaçlı, akış değişmez


def _print_banner() -> None:
    portfolio = _VERIFIED_CONFIG.get("strategy_portfolio") or {}
    sizing = _VERIFIED_CONFIG.get("position_sizing") or {}
    execution = _VERIFIED_CONFIG.get("execution") or {}
    vol_target = _VERIFIED_CONFIG.get("vol_target") or {}
    strategies = _VERIFIED_CONFIG.get("strategies_enabled") or []
    symbols = portfolio.get("symbols") or []
    pyramid = bool(portfolio.get("pyramid_enabled", False))
    risk_pct = float(sizing.get("risk_per_trade", 0.0)) * 100.0
    vol_desc = "OFF"
    if vol_target.get("enabled") is True:
        vol_desc = (
            f"ON metric={vol_target.get('input_metric', 'MISSING')} "
            f"target={float(vol_target.get('target_atr_pct', 0.0)):.4f} "
            f"factor=[{float(vol_target.get('min_factor', 0.0)):.2f},"
            f"{float(vol_target.get('max_factor', 0.0)):.2f}]"
        )

    _vlog("=" * 65)
    _vlog(
        f"{_LOG_TAG.upper()} PAPER DAEMON — phase={_PHASE} "
        f"symbols={len(symbols)} strategies={len(strategies) or 4}"
    )
    _vlog(f"  Config      : {V14_CONFIG} (startup-verified)")
    _vlog(f"  Journal     : {_daemon.JOURNAL}")
    _vlog(f"  Breaker     : {_daemon.BREAKER_STATE_15M}")
    _vlog(
        f"  Entry gates : sl>={float(execution.get('sl_pct_min', 0.0)):.3f} "
        f"conf>={float(portfolio.get('signal_confidence_min', 0.0)):.2f}"
    )
    _vlog(
        "  Exit        : PCT trail=1.5% (E13 ATR1.5x shadow-only) / "
        "TP1=30%@1R / TP2=30%@1.5R / runner=40%"
    )
    _vlog(
        f"  Pyramid     : {'ON' if pyramid else 'OFF'} "
        f"triggers={portfolio.get('pyramid_triggers') or []} "
        f"sizes={portfolio.get('pyramid_sizes') or []}"
    )
    _vlog(
        f"  Sizing      : method={sizing.get('method', 'unknown')} "
        f"base_risk={risk_pct:.2f}% vol_target={vol_desc}"
    )
    _vlog("  Run mode    : paper; PA_LIVE_CONFIRM forbidden by wrapper")
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
