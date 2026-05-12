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


# =====================================================================
# Production Config — tek doğruluk kaynağı
# =====================================================================


@dataclass(frozen=True)
class ProductionConfig:
    """Canonical replay icin tum parametreler. Default'lar risk.yaml'dan."""

    # Sizing
    risk_pct: float = 0.030
    max_notional_pct_equity: float | None = 0.30  # v0.9.2 cap

    # Filtering
    conf_min: float = 0.20
    drop_strategies: frozenset[str] = field(default_factory=frozenset)

    # Concurrency / cool-downs
    max_concurrent: int = 8
    same_symbol_side_cooldown_days: int = 3

    # DD breakers
    daily_dd: float = 0.05
    weekly_dd: float = 0.10
    monthly_dd: float = 0.15

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

    # Initial capital
    initial_capital: float = 10_000.0

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
            max_concurrent=int(cl.get("max_open_positions", sp.get("max_concurrent_positions", 8))),
            same_symbol_side_cooldown_days=int(sp.get("same_symbol_side_cooldown_days", 3)),
            daily_dd=float(dd.get("daily_loss_pct", 0.05)),
            weekly_dd=float(dd.get("weekly_loss_pct", 0.10)),
            monthly_dd=float(dd.get("monthly_loss_pct", 0.15)),
            consecutive_loss_n=(
                int(dd["consecutive_losses"])
                if dd.get("consecutive_losses") not in (None, 0)
                else None
            ),
            consecutive_loss_pause_days=int(dd.get("consecutive_loss_pause_days", 5)),
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

    # Filtering
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
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
    last_entry: dict[tuple, Any] = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count: dict = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(p["R"])
                eq_curve.append(equity)
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

        # Same-day cap (opsiyonel — default kapalı)
        d_key = t["entry_ts"].date()
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
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1)
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7)
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30)
            continue

        if len(open_pos) >= cfg.max_concurrent:
            continue

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
        risk_d = equity * cfg.risk_pct * risk_modifier
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

        # Cross-margin yaklasimi — 3x
        margin = notional / 3.0
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
        })

    # Acik pozisyonlari kapat
    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
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
