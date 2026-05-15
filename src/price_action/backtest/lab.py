"""Canonical backtest replay — tek source of truth.

Tum scripts buradan import etsin. risk.yaml'dan default parametre okur,
explicit override kabul eder.

Eski replay fonksiyonlarini (scripts/v09_optimize_top10.replay,
scripts/v09_dd_protect.replay_protected, scripts/v091_fix_test.replay_fixed)
zamanla deprecate ediyoruz — yeni scriptler `production_replay()` kullansin.

Kullanim:
    from price_action.backtest.lab import production_replay, ProductionConfig

    cfg = ProductionConfig.from_yaml()  # configs/risk.yaml'dan
    result = production_replay(trades, cfg)
    print(result.summary())
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_YAML = ROOT / "configs" / "risk.yaml"


def _load_strategy_taxonomy(path: str | Path | None = None) -> tuple[dict, dict, str]:
    """SEC21 — slot allocation icin strategy taxonomy yukle.

    Default path: configs/strategy_taxonomy.yaml (repo root).
    Returns (taxonomy_map, default_slot_caps, default_class).
    Eger dosya yoksa bos dict + default 'trend_continuation' doner (FIFO fallback).
    """
    p = Path(path) if path else (ROOT / "configs" / "strategy_taxonomy.yaml")
    if not p.exists():
        return {}, {}, "trend_continuation"
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        tax = dict(raw.get("taxonomy", {}) or {})
        caps = dict(raw.get("default_slot_caps", {}) or {})
        default_class = str(raw.get("default_class", "trend_continuation"))
        return tax, caps, default_class
    except Exception:
        return {}, {}, "trend_continuation"


def _lazy_build_btc_halt(regime_cfg: dict) -> dict | None:
    """from_yaml -> regime.py lazy import (dairesel import'tan kacin).

    YAML'da `regime_filter.btc_capitulation_halt_enabled: true` ise BTC halt
    calendar uretilir. Parametreler regime_cfg'den okunur (varsayilan analyst HYP).
    """
    try:
        from price_action.backtest.regime import compute_btc_capitulation_halt
        return compute_btc_capitulation_halt(
            atr_threshold=float(regime_cfg.get("atr_pct_threshold", 6.0)),
            ema200_streak_threshold=int(regime_cfg.get("ema200_streak_days", 10)),
            dd_90d_threshold=float(regime_cfg.get("dd_90d_threshold_pct", -25.0)),
            resume_atr_threshold=float(regime_cfg.get("resume_atr_threshold", 4.0)),
            resume_streak_days=int(regime_cfg.get("resume_streak_days", 5)),
        )
    except Exception:
        return None


def _lazy_build_funding_filters(alt_cfg: dict) -> tuple[dict | None, dict | None]:
    """YAML alt_data block'undan calendar'lar uretir.

    Iki kaynak union edilir:
      1. funding_filter_enabled (BTC perpetual funding)
         avg > long_thr  -> long skip (overheated long crowd)
         avg < short_thr -> short skip (overshort squeeze)
      2. fng_short_skip_enabled (Fear&Greed Index)
         value <= threshold -> short skip (extreme fear contrarian)

    v0.9.6 LOOK-AHEAD FIX: funding_aggregation_mode:
      "00:00_only"  (DEFAULT) — sadece T 00:00 UTC funding (causal)
      "lag1d"       — T-1 gunun daily avg'i (ultra-causal)
      "daily_full"  — T'nin TUM gun daily avg'i (LOOK-AHEAD)

    v0.9.7: F&G short-skip union eklendi. BALANCED B3 sweep'te WIN-WIN.

    Returns: (long_skip_dict, short_skip_dict). Both None if both disabled.
    """
    funding_on = alt_cfg.get("funding_filter_enabled", False)
    fng_on = alt_cfg.get("fng_short_skip_enabled", False)
    if not funding_on and not fng_on:
        return None, None

    long_skip: dict = {}
    short_skip: dict = {}
    try:
        import pandas as pd

        # --- 1. Funding rate filter ---
        if funding_on:
            p = ROOT / "data" / "alt_data" / "funding_BTCUSDT.csv"
            if p.exists():
                df = pd.read_csv(p)
                df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
                df["date"] = df["ts"].dt.date

                mode = str(alt_cfg.get("funding_aggregation_mode", "00:00_only"))
                long_thr = float(alt_cfg.get("funding_long_threshold", 0.0001))
                short_thr = float(alt_cfg.get("funding_short_threshold", -0.0001))

                if mode == "00:00_only":
                    df_00 = df[df["ts"].dt.hour == 0]
                    daily = df_00.groupby("date")["fundingRate"].mean().reset_index()
                elif mode == "lag1d":
                    daily_full = df.groupby("date")["fundingRate"].mean().reset_index()
                    daily_full = daily_full.sort_values("date").reset_index(drop=True)
                    daily_full["next_date"] = daily_full["date"].shift(-1)
                    daily = daily_full.dropna(subset=["next_date"])[["next_date", "fundingRate"]]
                    daily = daily.rename(columns={"next_date": "date"})
                elif mode == "daily_full":
                    daily = df.groupby("date")["fundingRate"].mean().reset_index()
                else:
                    raise ValueError(f"Bilinmeyen funding_aggregation_mode: {mode}")

                for _, r in daily.iterrows():
                    if not pd.notna(r["fundingRate"]):
                        continue
                    if r["fundingRate"] > long_thr:
                        long_skip[r["date"]] = True
                    if r["fundingRate"] < short_thr:
                        short_skip[r["date"]] = True

        # --- 2. F&G fear -> short skip union ---
        if fng_on:
            p_fng = ROOT / "data" / "alt_data" / "fng_daily.csv"
            if p_fng.exists():
                fng_thr = int(alt_cfg.get("fng_short_skip_threshold", 20))
                fng = pd.read_csv(p_fng)
                fng["date"] = pd.to_datetime(fng["date"]).dt.date
                for _, r in fng.iterrows():
                    if pd.notna(r["value"]) and int(r["value"]) <= fng_thr:
                        short_skip[r["date"]] = True

        return (long_skip if long_skip else None,
                short_skip if short_skip else None)
    except Exception:
        return None, None


# =====================================================================
# Production Config — tek doğruluk kaynağı
# =====================================================================


@dataclass(frozen=True)
class ProductionConfig:
    """Canonical replay icin tum parametreler. Default'lar risk.yaml'dan."""

    # Sizing
    risk_pct: float = 0.030
    max_notional_pct_equity: float | None = 0.30  # v0.9.2 cap
    # v0.9.8: leverage carpani (margin = notional / leverage). 3 = backwards-compat default.
    leverage: float = 3.0
    # v0.9.8: confidence-based dynamic sizing — TIER YAPISI
    # Eger None: sabit risk_pct + leverage kullanilir (eski davranis)
    # Eger set edilir: her trade'in conf_pct (rolling rank) bucket'ina gore risk + lev
    confidence_risk_tiers: tuple | None = None
    leverage_tiers: tuple | None = None
    # v0.9.8: conf'i percentile rank ile yeniden hesapla (180-gun rolling)
    use_conf_percentile: bool = False
    conf_pct_lookback_days: int = 180
    # v1.5.1 (sec15.1): sl_pct rolling-180g percentile rank — CONF DATA QUALITY FIX
    # SEC9 forensik: %96.9 trade conf=0.333 (tek-tier yığılma) — tier sistemi etkisiz.
    # Çözüm C: sl_pct rank (Spearman vs R = +0.30, p<0.001 — gerçek alpha sinyali).
    # Use_sl_pct_conf=True ise pool'a conf_pct = sl_pct rolling rank yazılır,
    # confidence_risk_tiers / leverage_tiers bunu kullanır.
    use_sl_pct_conf: bool = False

    # Filtering
    conf_min: float = 0.20
    drop_strategies: frozenset[str] = field(default_factory=frozenset)
    # v0.9.5 ablation: per-symbol drop (analyst ablation testlerinde kullanilir)
    drop_symbols: frozenset[str] = field(default_factory=frozenset)
    # v0.9.5 ablation: belirli (strategy, symbol) ciftlerini drop
    drop_pairs: frozenset[tuple] = field(default_factory=frozenset)

    # Concurrency / cool-downs
    max_concurrent: int = 8
    same_symbol_side_cooldown_days: int = 3

    # DD breakers
    daily_dd: float = 0.05
    weekly_dd: float = 0.10
    monthly_dd: float = 0.15
    # v1.3 sec12a: monthly halt configurable (default 30g, 21g WIN: +%9 yıllık)
    monthly_halt_days: int = 30
    daily_halt_days: int = 1
    weekly_halt_days: int = 7
    # v1.5 sec14.1: side-conditional monthly_dd (long_dd=0.12, short_dd=0.06 +%4.3pp)
    # None ise monthly_dd kullan (geriye uyumlu). Set edilirse side-spesifik anchor track.
    monthly_dd_long: float | None = None   # set edilirse long-only equity halt
    monthly_dd_short: float | None = None  # set edilirse short-only equity halt
    # v2.0 sec15.5: PYRAMIDING R-adjust (sim-equivalent, production_replay seviyesinde)
    # R_pyramid = R_orig + sum_i [ s_i * max(0, R_orig - t_i) ] (BE-protect)
    # standard winner: triggers=[1.0, 2.0], sizes=[0.50, 0.30] -> sim +%150
    pyramid_enabled: bool = False
    pyramid_triggers: tuple = ()  # ör (1.0, 2.0)
    pyramid_sizes: tuple = ()     # ör (0.50, 0.30)

    # Consecutive-loss cool-down (v0.9.1)
    consecutive_loss_n: int | None = 3
    consecutive_loss_pause_days: int = 5

    # Equity protection (v0.9 testleri)
    equity_protect_30: bool = False  # -%30 DD'de half risk
    equity_protect_50: bool = False  # -%50 DD'de hard stop

    # Same-day cap (v0.9.2 reddedildi ama parametre kalsın deney icin)
    same_day_max: int | None = None

    # Production-realistic gate'ler (live'da RiskOfficer.evaluate'ta var, backtest'te yok)
    # Default None -> backward compat. Set edilirse production'a daha yakin simulasyon.
    concentration_max_per_symbol_pct: float | None = None  # 0.20 = %20 per symbol cap
    max_same_side_concurrent: int | None = None  # 4 = max 4 long VE 4 short ayni anda

    # Vol-target sizing (high-vol gunlerde kucuk pos, low-vol'de buyuk)
    # vol_factor = target_atr_pct / sl_pct, clamped [min,max]
    vol_target_enabled: bool = False
    vol_target_atr_pct: float = 0.04   # %4 SL hedef (BTC normal)
    vol_min_factor: float = 0.20       # extreme high-vol max %80 azalt
    vol_max_factor: float = 1.50       # extreme low-vol max %50 buyut

    # v0.9.4 REGIME FILTERS (Analyst + Researcher B HYP)
    # BTC capitulation halt — dict[date -> halt:bool]
    btc_halt_calendar: dict | None = None
    # Per-symbol chop classifier — dict[symbol -> dict[date -> "chop"|"transition"|"trend"]]
    chop_calendars: dict | None = None
    # Chop modlarinda risk carpani
    chop_risk_factor: float = 0.0          # "chop" -> skip
    transition_risk_factor: float = 0.5    # "transition" -> half risk

    # v0.9.5 ML TRADE SCORING FILTER
    # dict[(symbol, entry_ts) -> proba]. proba < score_threshold ise skip.
    # entry_ts pd.Timestamp veya datetime (UTC, exact match).
    score_filter: dict | None = None
    score_threshold: float = 0.0  # 0 = filter disabled even if dict set

    # v0.9.5 ALT-DATA FILTERS (date -> bool)
    # True -> skip o gunu. Date-aligned (entry_ts.date()).
    # alt_data_skip_long: long taraf icin "skip" gunleri (overheated -> contrarian)
    # alt_data_skip_short: short taraf icin "skip" gunleri
    # alt_data_skip_all: her iki tarafa da skip (extreme regime)
    alt_data_skip_long: dict | None = None
    alt_data_skip_short: dict | None = None
    alt_data_skip_all: dict | None = None

    # v1.6 sec15.4: VOL-CONDITIONAL ADAPTIVE RISK (BTC ATR%-based dynamic sizing)
    # Default kapali (False) -> backwards compat, sabit cfg.risk_pct kullanilir.
    # Aktif edilirse: trade entry_ts'inden onceki son 14-bar BTC ATR% bakilir.
    #   ATR% < vol_low_atr_pct  -> risk_pct = vol_low_risk_pct  (sakin -> agresif)
    #   ATR% > vol_high_atr_pct -> risk_pct = vol_high_risk_pct (oynak -> defensive)
    #   araligi    -> risk_pct = cfg.risk_pct (normal)
    # btc_atr_pct_calendar: dict[date -> float (oran, %0.04 = 0.04 NOT 4)]
    # Lookahead-bias yasak — calendar'da tarih T icin ATR%, T-1 close-of-day verisi.
    vol_conditional_risk: bool = False
    vol_low_atr_pct: float = 0.03    # ATR%<3 (sakin)
    vol_high_atr_pct: float = 0.05   # ATR%>5 (oynak)
    vol_low_risk_pct: float = 0.05   # sakin gunlerde risk %5 (agresif)
    vol_high_risk_pct: float = 0.03  # oynak gunlerde risk %3 (defensive)
    btc_atr_pct_calendar: dict | None = None  # date -> float ATR% (oran)

    # Initial capital
    initial_capital: float = 10_000.0

    # SEC21: per-strategy-class slot allocation
    # Default OFF (backwards compat — pure FIFO at cfg.max_concurrent).
    # When True: lookup strategy class via taxonomy, enforce per-class max + min_reserved.
    # taxonomy: dict[strategy_module_name -> class_label]
    # slot_caps: dict[class_label -> {"max": int, "min_reserved": int}]
    slot_allocation_enabled: bool = False
    slot_taxonomy: dict | None = None       # strat_name -> class
    slot_caps: dict | None = None           # class -> {max, min_reserved}
    slot_default_class: str = "trend_continuation"

    @classmethod
    def from_yaml(cls, path: str | Path | None = None) -> ProductionConfig:
        """risk.yaml'dan productionconfig olustur."""
        p = Path(path) if path else DEFAULT_YAML
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        ps = raw.get("position_sizing", {}) or {}
        dd = raw.get("drawdown_breakers", {}) or {}
        sp = raw.get("strategy_portfolio", {}) or {}
        cl = raw.get("concentration_limits", {}) or {}
        vt = raw.get("vol_target", {}) or {}
        cg = raw.get("correlation_gate", {}) or {}
        rg = raw.get("regime_filter", {}) or {}
        alt = raw.get("alt_data", {}) or {}
        sa = raw.get("slot_allocation", {}) or {}  # SEC21

        # v0.9.5: alt_data funding filter lazy build
        fund_long, fund_short = _lazy_build_funding_filters(alt)
        # v0.9.5: drop_pairs YAML list -> frozenset[tuple]
        pairs_raw = sp.get("drop_pairs", []) or []
        drop_pairs_set = frozenset(tuple(p) for p in pairs_raw) if pairs_raw else frozenset()

        # v0.9.8: dynamic sizing tier'lari ve leverage
        # MASTER FLAG: ps.use_confidence_dynamic_sizing. False ise tier'lar yok sayilir
        # (backwards-compat). True ise YAML'da yazili tier'lar aktif.
        use_dynamic = bool(ps.get("use_confidence_dynamic_sizing", False))
        lev_block = raw.get("leverage", {}) or {}
        if use_dynamic:
            conf_risk_tiers_raw = ps.get("confidence_risk_tiers")
            lev_tiers_raw = lev_block.get("confidence_tiers")
            conf_risk_tiers = tuple(conf_risk_tiers_raw) if conf_risk_tiers_raw else None
            lev_tiers = tuple(lev_tiers_raw) if lev_tiers_raw else None
        else:
            conf_risk_tiers = None
            lev_tiers = None
        leverage_default = float(lev_block.get("default_leverage", 3.0))

        # SEC21: slot allocation taxonomy + caps
        sa_enabled = bool(sa.get("enabled", False))
        sa_tax, sa_caps_default, sa_default_class = _load_strategy_taxonomy()
        # YAML override (per preset slot_caps override taxonomy file defaults)
        sa_caps_yaml = sa.get("class_caps") or {}
        sa_caps_final = dict(sa_caps_default)
        for klass, caps in sa_caps_yaml.items():
            sa_caps_final[klass] = dict(caps)

        # v0.9.3: optional ek alanlar
        drop_list = sp.get("drop_strategies", []) or []
        return cls(
            # v0.9.2: backtest_risk_pct YAML alani once gelir, yoksa risk_per_trade fallback.
            # Live tier sistemi backtest replay'de uygulanmıyor — sabit %3 kullaniyoruz.
            risk_pct=float(ps.get("backtest_risk_pct", ps.get("risk_per_trade", 0.02))),
            max_notional_pct_equity=(
                float(ps["max_notional_pct_equity"])
                if ps.get("max_notional_pct_equity") not in (None, 0, 0.0)
                else None
            ),
            conf_min=float(sp.get("signal_confidence_min", 0.20)),
            drop_strategies=frozenset(drop_list),
            max_concurrent=int(cl.get("max_open_positions", sp.get("max_concurrent_positions", 8))),
            same_symbol_side_cooldown_days=int(sp.get("same_symbol_side_cooldown_days", 3)),
            daily_dd=float(dd.get("daily_loss_pct", 0.05)),
            weekly_dd=float(dd.get("weekly_loss_pct", 0.10)),
            monthly_dd=float(dd.get("monthly_loss_pct", 0.15)),
            monthly_halt_days=int(dd.get("monthly_halt_days", 30)),
            daily_halt_days=int(dd.get("daily_halt_days", 1)),
            weekly_halt_days=int(dd.get("weekly_halt_days", 7)),
            monthly_dd_long=(
                float(dd["monthly_loss_pct_long"])
                if dd.get("monthly_loss_pct_long") is not None
                else None
            ),
            monthly_dd_short=(
                float(dd["monthly_loss_pct_short"])
                if dd.get("monthly_loss_pct_short") is not None
                else None
            ),
            pyramid_enabled=bool(sp.get("pyramid_enabled", False)),
            pyramid_triggers=tuple(sp.get("pyramid_triggers") or ()),
            pyramid_sizes=tuple(sp.get("pyramid_sizes") or ()),
            consecutive_loss_n=(
                int(dd["consecutive_losses"])
                if dd.get("consecutive_losses") not in (None, 0)
                else None
            ),
            consecutive_loss_pause_days=int(dd.get("consecutive_loss_pause_days", 5)),
            # v0.9.3: ileri risk gate'leri
            concentration_max_per_symbol_pct=(
                float(cl["max_per_symbol_pct"])
                if cl.get("backtest_apply_concentration_gate", False)
                else None
            ),
            max_same_side_concurrent=(
                int(ps["max_same_side_concurrent"])
                if ps.get("max_same_side_concurrent") not in (None, 0)
                else None
            ),
            vol_target_enabled=bool(vt.get("enabled", False)),
            vol_target_atr_pct=float(vt.get("target_atr_pct", 0.04)),
            vol_min_factor=float(vt.get("min_factor", 0.20)),
            vol_max_factor=float(vt.get("max_factor", 1.50)),
            # v0.9.4: regime filter (BTC capitulation halt)
            # YAML'da `regime_filter.btc_capitulation_halt_enabled: true` ise
            # lab.regime modulu calendar uretir, replay'de overlay olur.
            btc_halt_calendar=(
                _lazy_build_btc_halt(rg) if rg.get("btc_capitulation_halt_enabled", False) else None
            ),
            # v0.9.5: alt-data funding filter
            alt_data_skip_long=fund_long,
            alt_data_skip_short=fund_short,
            # v0.9.5: ablation pair drops
            drop_pairs=drop_pairs_set,
            # v0.9.8: dynamic sizing + leverage
            confidence_risk_tiers=conf_risk_tiers,
            leverage_tiers=lev_tiers,
            leverage=leverage_default,
            use_conf_percentile=bool(ps.get("use_conf_percentile", False)),
            conf_pct_lookback_days=int(ps.get("conf_pct_lookback_days", 180)),
            # SEC21 slot allocation
            slot_allocation_enabled=sa_enabled,
            slot_taxonomy=sa_tax if sa_tax else None,
            slot_caps=sa_caps_final if sa_caps_final else None,
            slot_default_class=sa_default_class,
        )

    def with_overrides(self, **kw: Any) -> ProductionConfig:
        """Yeni bir config dondur (override icin) — dataclasses.replace."""
        return replace(self, **kw)

    def label(self) -> str:
        cap = f"cap{self.max_notional_pct_equity:.2f}" if self.max_notional_pct_equity else "no-cap"
        return (
            f"r%{self.risk_pct*100:.1f}_conf{self.conf_min}"
            f"_{cap}_cd{self.consecutive_loss_n or 0}/{self.consecutive_loss_pause_days}d"
        )


# =====================================================================
# Result
# =====================================================================


@dataclass(frozen=True)
class ReplayResult:
    """Tek bir replay sonucu — tum metrikler."""

    final_equity: float
    initial_capital: float
    trades: int
    win_rate: float
    max_drawdown: float  # negatif (örn -0.65 = -%65)
    avg_r: float
    sum_r: float
    config_label: str

    @property
    def total_return(self) -> float:
        """Toplam getiri (oran). Yıl bağımsız."""
        return self.final_equity / self.initial_capital - 1.0

    def annualized(self, years: float) -> float:
        """Yillik gettiri (compounding) — pencere uzunlugu years arg ile verilir."""
        if years <= 0 or self.final_equity <= 0:
            return 0.0
        return (self.final_equity / self.initial_capital) ** (1.0 / years) - 1.0

    def summary(self, years: float | None = None) -> str:
        """Tek satir ozet — log/print icin."""
        lines = [
            f"final=${self.final_equity:,.0f}",
            f"return={self.total_return*100:+.1f}%",
            f"DD={self.max_drawdown*100:+.1f}%",
            f"n={self.trades}",
            f"WR={self.win_rate*100:.1f}%",
        ]
        if years:
            lines.append(f"ann={self.annualized(years)*100:+.2f}%/y")
        return "  ".join(lines)


# =====================================================================
# Production Replay — canonical
# =====================================================================


def production_replay(trades: list[dict], cfg: ProductionConfig | None = None) -> ReplayResult | None:
    """Canonical backtest replay.

    Args:
        trades: scripts/v09_optimize_top10._gather()'in dondurdu liste.
                Her dict: entry_ts, exit_ts, entry_price, initial_sl, R,
                          symbol, side, conf, strategy
        cfg: ProductionConfig. None ise risk.yaml'dan okur.

    Returns:
        ReplayResult or None (sinyal yok / filter sonrasi bos kaldi).
    """
    if cfg is None:
        cfg = ProductionConfig.from_yaml()
    if not trades:
        return None

    # v0.9.8: optional conf_pct percentile rank (rolling 180g)
    if cfg.use_conf_percentile:
        from price_action.backtest.scoring import normalize_conf_percentile
        # Inplace: trades'e conf_pct alani eklenir (orijinal conf korunur)
        normalize_conf_percentile(trades, lookback_days=cfg.conf_pct_lookback_days)
    # v1.5.1: sl_pct rolling-180g percentile rank (CONF DATA QUALITY FIX)
    # use_sl_pct_conf use_conf_percentile'den bagimsiz; ikinci icin daha agir
    # data quality: sl_pct trade pool'da daima mevcut + Spearman(R)=+0.30.
    if cfg.use_sl_pct_conf:
        from price_action.backtest.scoring import (
            normalize_conf_via_sl_pct_percentile,
        )
        normalize_conf_via_sl_pct_percentile(
            trades, lookback_days=cfg.conf_pct_lookback_days,
        )

    # Filtering
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
        and (t["strategy"], t["symbol"]) not in cfg.drop_pairs
    ]
    if not filtered:
        return None
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos: list[dict] = []
    eq_curve: list[float] = [cfg.initial_capital]
    Rs: list[float] = []

    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date()
    last_w = first.isocalendar()[1]
    last_m = first.month
    blocked_until = None
    # v1.5: side-conditional dd: ay başından beri side-bazlı net pnl
    monthly_long_pnl = 0.0
    monthly_short_pnl = 0.0
    blocked_long_until = None
    blocked_short_until = None
    last_entry: dict[tuple, Any] = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count: dict = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        nonlocal monthly_long_pnl, monthly_short_pnl
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                # v2.0.3 PYRAMID R-adjust (SEC16 düzeltmeleri)
                # MFE-aware: peak_R kullan (ek pos peak >= trigger ise açıldı)
                # Slippage erosion proper: 0.06R per ek pos
                #   = fee 0.075% × 2 (entry+exit) / initial_R~4% = 0.0375R
                #   + spread/slippage 5bps × 2 / 4% = 0.025R = ~0.06R total
                # Realistic ek pos cost (Quality agent: önceki 0.001R 60x küçüktü)
                R_use = p["R"]
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p = float(p.get("peak_R", R_use))  # MFE-aware fallback final R
                    bonus = 0.0
                    slippage_erosion = 0.0
                    SLIP_PER_EKPOS = 0.06  # realistic fee+spread+slip
                    for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                        # Ek pos açıldıysa (peak >= trigger) bonus + slippage erosion
                        if peak_R_p >= float(trig):
                            bonus += float(sz) * max(0.0, R_use - float(trig))
                            slippage_erosion += SLIP_PER_EKPOS * float(sz)
                    R_use = R_use + bonus - slippage_erosion
                pnl = p["risk"] * R_use
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(R_use)
                eq_curve.append(equity)
                # v1.5: side-bazlı pnl tracking
                if p.get("side") == "long":
                    monthly_long_pnl += pnl
                elif p.get("side") == "short":
                    monthly_short_pnl += pnl
                if pnl < 0:
                    consecutive_losses += 1
                    if cfg.consecutive_loss_n and consecutive_losses >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            continue

        d_key = t["entry_ts"].date()

        # v0.9.4 BTC CAPITULATION HALT (Analyst HYP)
        if cfg.btc_halt_calendar is not None:
            if cfg.btc_halt_calendar.get(d_key, False):
                continue  # capitulation rejiminde yeni pozisyon yok

        # v0.9.5 ALT-DATA FILTERS (funding / F&G / liquidations)
        # alt_data_skip_all -> her iki taraf kapali (ornek: extreme greed regime'inde tum trade skip)
        if cfg.alt_data_skip_all is not None:
            if cfg.alt_data_skip_all.get(d_key, False):
                continue
        # alt_data_skip_long -> sadece long taraf skip
        side_t = t.get("side", "").lower()
        if cfg.alt_data_skip_long is not None and side_t == "long":
            if cfg.alt_data_skip_long.get(d_key, False):
                continue
        # alt_data_skip_short -> sadece short taraf skip
        if cfg.alt_data_skip_short is not None and side_t == "short":
            if cfg.alt_data_skip_short.get(d_key, False):
                continue

        # v0.9.5 ML SCORE FILTER
        if cfg.score_filter is not None and cfg.score_threshold > 0:
            key_score = (t["symbol"], t["entry_ts"])
            proba = cfg.score_filter.get(key_score)
            if proba is None or proba < cfg.score_threshold:
                continue

        # v0.9.4 PER-SYMBOL CHOP CLASSIFIER (Researcher B HYP-REGIME-001)
        chop_factor = 1.0
        if cfg.chop_calendars is not None:
            sym_cal = cfg.chop_calendars.get(t["symbol"])
            if sym_cal is not None:
                mode = sym_cal.get(d_key, "trend")
                if mode == "chop":
                    chop_factor = cfg.chop_risk_factor
                elif mode == "transition":
                    chop_factor = cfg.transition_risk_factor
            if chop_factor <= 0:
                continue  # chop -> skip

        # Same-day cap (opsiyonel — default kapalı)
        if cfg.same_day_max is not None:
            if same_day_count.get(d_key, 0) >= cfg.same_day_max:
                continue

        # Same-symbol-side cool-down
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cfg.same_symbol_side_cooldown_days:
            continue

        # DD breakers
        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d:
            daily_anchor = equity
            last_d = cd
        if cw != last_w:
            weekly_anchor = equity
            last_w = cw
        if cm != last_m:
            monthly_anchor = equity
            last_m = cm
            # v1.5: side-bazlı monthly pnl reset
            monthly_long_pnl = 0.0
            monthly_short_pnl = 0.0
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.daily_halt_days)
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.weekly_halt_days)
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
            continue
        # v1.5 SIDE-CONDITIONAL monthly_dd
        side_t = str(t.get("side", "")).lower()
        if cfg.monthly_dd_long is not None and side_t == "long":
            if blocked_long_until and t["entry_ts"] < blocked_long_until:
                continue
            # Long-side ay başından beri net loss
            long_loss_pct = -monthly_long_pnl / max(monthly_anchor, 1) if monthly_long_pnl < 0 else 0
            if long_loss_pct >= cfg.monthly_dd_long:
                blocked_long_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                continue
        if cfg.monthly_dd_short is not None and side_t == "short":
            if blocked_short_until and t["entry_ts"] < blocked_short_until:
                continue
            short_loss_pct = -monthly_short_pnl / max(monthly_anchor, 1) if monthly_short_pnl < 0 else 0
            if short_loss_pct >= cfg.monthly_dd_short:
                blocked_short_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                continue

        if len(open_pos) >= cfg.max_concurrent:
            continue

        # SEC21 PER-STRATEGY-CLASS SLOT ALLOCATION
        # Default OFF: skip block entirely (pure FIFO at cfg.max_concurrent).
        # When ON: enforce class.max cap AND reserve slots for under-represented
        # classes (min_reserved). Reserved slots are NOT available to other classes
        # while their owning class has 0 open positions, until cfg.max_concurrent
        # leaves enough room for both this trade AND every other class's reservation.
        if (
            cfg.slot_allocation_enabled
            and cfg.slot_taxonomy is not None
            and cfg.slot_caps
        ):
            strat_name = t.get("strategy", "")
            trade_class = cfg.slot_taxonomy.get(
                strat_name, cfg.slot_default_class
            )
            caps_for_class = cfg.slot_caps.get(trade_class, {})
            class_max = int(caps_for_class.get("max", cfg.max_concurrent))
            # Count currently open positions per class
            open_by_class: dict = {}
            for p in open_pos:
                pc = cfg.slot_taxonomy.get(
                    p.get("strategy", ""), cfg.slot_default_class
                )
                open_by_class[pc] = open_by_class.get(pc, 0) + 1
            n_open_class = open_by_class.get(trade_class, 0)
            if n_open_class >= class_max:
                continue  # class cap exhausted
            # Reservation check: for OTHER classes with min_reserved > 0 and
            # open_count < min_reserved, those slots are "reserved" and cannot
            # be taken by this trade (unless after taking the slot we'd still
            # leave their reservations honored).
            other_reserved_unfilled = 0
            for klass, caps in cfg.slot_caps.items():
                if klass == trade_class:
                    continue
                min_res = int(caps.get("min_reserved", 0) or 0)
                if min_res <= 0:
                    continue
                cur_open = open_by_class.get(klass, 0)
                shortfall = max(0, min_res - cur_open)
                other_reserved_unfilled += shortfall
            # After taking this slot, used_slots = len(open_pos)+1
            # Free remaining = max_concurrent - used_slots
            # Must be >= other_reserved_unfilled
            free_after = cfg.max_concurrent - (len(open_pos) + 1)
            if free_after < other_reserved_unfilled:
                continue  # taking this slot would crowd out reserved classes

        # Equity protection
        dd_from_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_modifier = 1.0
        if cfg.equity_protect_50 and dd_from_peak >= 0.50:
            continue
        if cfg.equity_protect_30 and dd_from_peak >= 0.30:
            risk_modifier = 0.5

        # Sizing
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        # v0.9.8: confidence-based dynamic risk_pct (tier sistemi)
        # Eger confidence_risk_tiers verildi ise trade'in conf_pct/conf'una gore tier sec.
        # Yoksa sabit cfg.risk_pct kullan (backwards-compat).
        if cfg.confidence_risk_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_risk_pct = float(get_tier_value(
                cfg.confidence_risk_tiers, conf_for_tier, "risk_pct", cfg.risk_pct
            ))
        else:
            trade_risk_pct = cfg.risk_pct

        # v1.6 sec15.4: VOL-CONDITIONAL adaptive risk override
        # Vol-targeting yapisina yakin ama farkli mekanik:
        # vol_target -> per-trade SL'e gore size carpani (continuous).
        # vol_conditional_risk -> BTC market-wide ATR% bucket'ina gore risk_pct DEGISTIRIR.
        # NOT: confidence_risk_tiers ile cakistiginda vol-conditional cfg.risk_pct'e
        # default referans alir, conf-tier degerini OVERRIDE etmez (yalnizca cfg.risk_pct
        # set edildiginde override eder). Kullanim: vol_conditional ile tier'lar
        # birlikte kullanilirsa, conf-tier degeri pas gecilir; sweep ic tutarlilik icin
        # tier'lar None birakilir.
        if cfg.vol_conditional_risk and cfg.btc_atr_pct_calendar is not None:
            atr_p = cfg.btc_atr_pct_calendar.get(d_key)
            if atr_p is not None:
                if atr_p < cfg.vol_low_atr_pct:
                    trade_risk_pct = cfg.vol_low_risk_pct
                elif atr_p > cfg.vol_high_atr_pct:
                    trade_risk_pct = cfg.vol_high_risk_pct
                # else normal range -> trade_risk_pct degismez (cfg.risk_pct)
        risk_d = equity * trade_risk_pct * risk_modifier

        # v0.9.4 chop transition mode -> half risk
        risk_d *= chop_factor

        # Vol-target: high-vol gunlerde kucuk pos, low-vol'de buyuk
        if cfg.vol_target_enabled:
            vol_factor = cfg.vol_target_atr_pct / sl_pct
            vol_factor = max(cfg.vol_min_factor, min(cfg.vol_max_factor, vol_factor))
            risk_d *= vol_factor

        notional = risk_d / sl_pct

        # v0.9.2 NOTIONAL CAP
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct  # efektif risk dusur

        # Production concentration gate: max per-symbol exposure (live RiskOfficer'da var).
        # Backtest replay'lerde default kapalı; set edildiginde live'a yakin simulasyon.
        if cfg.concentration_max_per_symbol_pct is not None:
            sym = t["symbol"]
            existing_sym_notional = sum(
                p["notional"] for p in open_pos if p.get("symbol") == sym
            )
            total_sym = existing_sym_notional + notional
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if total_sym > sym_cap:
                continue  # reject — same-symbol exposure cap'i ihlal

        # Side concentration: max long ya da max short ayni anda
        if cfg.max_same_side_concurrent is not None:
            side = t["side"]
            same_side_count = sum(1 for p in open_pos if p.get("side") == side)
            if same_side_count >= cfg.max_same_side_concurrent:
                continue

        # v0.9.8: dynamic leverage (confidence tier veya sabit cfg.leverage)
        if cfg.leverage_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_lev = float(get_tier_value(
                cfg.leverage_tiers, conf_for_tier, "leverage", cfg.leverage
            ))
        else:
            trade_lev = cfg.leverage
        if trade_lev <= 0:
            trade_lev = 1.0
        margin = notional / trade_lev
        if margin > cash:
            continue

        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "exit_ts": t["exit_ts"],
            "margin": margin,
            "notional": notional,
            "risk": risk_d,
            "R": t["R"],
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t.get("strategy", ""),  # SEC21: needed for slot class lookup
            "peak_R": t.get("peak_R", t["R"]),  # SEC16 MFE-aware pyramid
        })

    # Acik pozisyonlari kapat (v2.0.3 SEC16 fix)
    for p in open_pos:
        R_use = p["R"]
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            peak_R_p = float(p.get("peak_R", R_use))
            bonus = 0.0
            slippage_erosion = 0.0
            SLIP_PER_EKPOS = 0.06
            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                if peak_R_p >= float(trig):
                    bonus += float(sz) * max(0.0, R_use - float(trig))
                    slippage_erosion += SLIP_PER_EKPOS * float(sz)
            R_use = R_use + bonus - slippage_erosion
        cash += p["margin"] + p["risk"] * R_use
        equity = cash
        Rs.append(R_use)
        eq_curve.append(equity)

    # Max DD hesap
    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    win_rate = (sum(1 for x in Rs if x > 0) / len(Rs)) if Rs else 0.0
    avg_r = (sum(Rs) / len(Rs)) if Rs else 0.0

    return ReplayResult(
        final_equity=equity,
        initial_capital=cfg.initial_capital,
        trades=len(Rs),
        win_rate=win_rate,
        max_drawdown=max_dd,
        avg_r=avg_r,
        sum_r=sum(Rs),
        config_label=cfg.label(),
    )


__all__ = [
    "ProductionConfig",
    "ReplayResult",
    "production_replay",
]
