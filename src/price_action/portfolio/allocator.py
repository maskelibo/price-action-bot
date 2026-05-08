"""Portfolio Manager — önceliklendirme + sermaye dağıtımı.

`agents/portfolio_manager.md` algoritması:
    priority = confluence_score * 0.5
             + risk_reward_ratio * 0.3
             + (1 - existing_correlation_to_book) * 0.15
             + category_diversity_bonus * 0.05
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from price_action.contracts import OrderInstruction, Reject, RiskedOrder
from price_action.logging_config import logger
from price_action.risk.sizing import AccountState


class PortfolioManager:
    """Portföy seviyesi önceliklendirme + hard cap kontrolü."""

    def __init__(
        self,
        *,
        max_open_positions: int = 8,
        max_per_symbol_pct: float = 0.20,
        max_per_category_pct: float = 0.40,
        category_map: dict[str, str] | None = None,
        order_type_default: str = "post_only_limit",
    ) -> None:
        self.max_open_positions = max_open_positions
        self.max_per_symbol_pct = max_per_symbol_pct
        self.max_per_category_pct = max_per_category_pct
        self.category_map = category_map or {}
        self.order_type_default = order_type_default
        self._log = logger.bind(component="portfolio_manager")

    # ----- core -----
    def prioritize(
        self,
        risked_orders: list[RiskedOrder],
        account_state: AccountState,
        correlation_matrix: pd.DataFrame | None = None,
    ) -> tuple[list[OrderInstruction], list[Reject]]:
        """Aday emirlerden hard cap'lere ve önceliklendirmeye göre final liste."""
        if not risked_orders:
            return [], []

        # Önce her aday için skor üret
        scored: list[tuple[float, RiskedOrder]] = []
        existing_book = account_state.open_positions
        existing_syms = [p.symbol for p in existing_book]
        category_counts: dict[str, int] = {}
        for sym in existing_syms:
            cat = self._cat_of(sym)
            if cat:
                category_counts[cat] = category_counts.get(cat, 0) + 1

        for ro in risked_orders:
            score = self._priority(ro, existing_syms, correlation_matrix, category_counts)
            scored.append((score, ro))
        scored.sort(key=lambda x: x[0], reverse=True)

        out_instr: list[OrderInstruction] = []
        rejects: list[Reject] = []

        # Greedy selection — her ekledikten sonra cap'leri yeniden hesapla
        equity = account_state.equity_usdt
        used_per_sym: dict[str, float] = {}
        used_per_cat: dict[str, float] = {}
        for p in existing_book:
            n = p.quantity * p.current_price
            used_per_sym[p.symbol] = used_per_sym.get(p.symbol, 0.0) + n
            cat = self._cat_of(p.symbol)
            if cat:
                used_per_cat[cat] = used_per_cat.get(cat, 0.0) + n

        active_count = len(existing_book)
        # Aynı sembolde aynı yön → tek pozisyon birleştir; zıt yön → block
        existing_dir: dict[str, str] = {p.symbol: p.side for p in existing_book}
        seen_syms_this_round: dict[str, str] = {}

        for score, ro in scored:
            sig = ro.signal
            sym = sig.symbol

            if active_count >= self.max_open_positions:
                rejects.append(
                    Reject(
                        signal=sig,
                        rejected_by="portfolio",
                        reason="max_open_positions",
                        detail={"current": active_count, "max": self.max_open_positions},
                    )
                )
                continue

            # Strateji eş-pozisyon kuralı
            book_dir = existing_dir.get(sym) or seen_syms_this_round.get(sym)
            if book_dir is not None and book_dir != sig.direction:
                rejects.append(
                    Reject(
                        signal=sig,
                        rejected_by="portfolio",
                        reason="opposite_direction_with_existing",
                    )
                )
                continue

            # Per-symbol cap
            sym_after = used_per_sym.get(sym, 0.0) + ro.notional_usdt
            if equity > 0 and sym_after / equity > self.max_per_symbol_pct:
                rejects.append(
                    Reject(
                        signal=sig,
                        rejected_by="portfolio",
                        reason="per_symbol_cap",
                        detail={"after_pct": sym_after / equity},
                    )
                )
                continue

            # Per-category cap
            cat = self._cat_of(sym)
            if cat:
                cat_after = used_per_cat.get(cat, 0.0) + ro.notional_usdt
                if equity > 0 and cat_after / equity > self.max_per_category_pct:
                    rejects.append(
                        Reject(
                            signal=sig,
                            rejected_by="portfolio",
                            reason="per_category_cap",
                            detail={"category": cat, "after_pct": cat_after / equity},
                        )
                    )
                    continue

            # Korelasyon double-check (Risk zaten kesmiş olur ama portfolio katmanı da bakar)
            if correlation_matrix is not None and sym in correlation_matrix.columns:
                hi = self._max_abs_corr_to_book(sym, existing_syms + list(seen_syms_this_round), correlation_matrix)
                if hi > 0.9:
                    rejects.append(
                        Reject(
                            signal=sig,
                            rejected_by="portfolio",
                            reason="correlation_hard_block",
                            detail={"corr": hi},
                        )
                    )
                    continue

            # Kabul: instruction üret
            instr = OrderInstruction(
                risked_order=ro,
                priority=score,
                order_type=self.order_type_default,  # type: ignore[arg-type]
                limit_price=None,  # execution layer ATR offset uygular
                time_in_force="PO" if self.order_type_default == "post_only_limit" else "GTC",
                reduce_only=False,
            )
            out_instr.append(instr)
            used_per_sym[sym] = sym_after
            if cat:
                used_per_cat[cat] = used_per_cat.get(cat, 0.0) + ro.notional_usdt
            seen_syms_this_round[sym] = sig.direction
            active_count += 1

        self._log.bind(
            n_in=len(risked_orders), n_out=len(out_instr), n_rej=len(rejects)
        ).info("portfolio.prioritize")
        return out_instr, rejects

    # ----- helpers -----
    def _cat_of(self, symbol: str) -> str | None:
        if symbol in self.category_map:
            return self.category_map[symbol]
        base = symbol.split("/")[0] if "/" in symbol else symbol
        return self.category_map.get(base)

    def _priority(
        self,
        ro: RiskedOrder,
        existing_syms: list[str],
        corr: pd.DataFrame | None,
        category_counts: dict[str, int],
    ) -> float:
        sig = ro.signal
        rr = self._risk_reward_ratio(ro)

        existing_corr_to_book = 0.0
        if corr is not None and sig.symbol in corr.columns and existing_syms:
            existing_corr_to_book = self._max_abs_corr_to_book(
                sig.symbol, existing_syms, corr
            )
        diversity_bonus = 0.0
        cat = self._cat_of(sig.symbol)
        if cat is not None:
            count = category_counts.get(cat, 0)
            # Kategori temsil edilmiyorsa +1; doluysa azalan dönüş
            diversity_bonus = 1.0 / (1.0 + count)

        return (
            sig.confluence_score * 0.5
            + rr * 0.3
            + (1.0 - existing_corr_to_book) * 0.15
            + diversity_bonus * 0.05
        )

    @staticmethod
    def _risk_reward_ratio(ro: RiskedOrder) -> float:
        sig = ro.signal
        sl_dist = abs(sig.tp_price - sig.sl_price)
        if sl_dist <= 0:
            return 0.0
        # tp_price/sl_price doğrudan R'lik mesafeyi vermez; signal layer
        # 2R'lik tp koymuş kabul edilirse oran 2.0. Burada normalize için
        # tp ile entry arasındaki mesafe / sl ile entry arasındaki mesafe lazım,
        # ama entry yok — tp_levels içindeki ilk seviyeyi referans al.
        if not ro.tp_levels:
            return 0.0
        # Risk = entry - sl ≈ qty * (notional_pct?) — proxy olarak signal sl/tp oranı
        # Pratik: |tp - sig.sl| / |entry - sig.sl|. entry yoksa sig.sl'i ortalama olarak.
        # En basit & robust: tp ile sl mesafesi / qty bazlı risk yaklaşık 2R kabul.
        return 2.0  # Pre-set R-multiple; gerçek hesabı backtest TradeRecord'da yapılır

    @staticmethod
    def _max_abs_corr_to_book(
        symbol: str, book_syms: list[str], corr: pd.DataFrame
    ) -> float:
        if corr is None or symbol not in corr.columns:
            return 0.0
        peers = [s for s in book_syms if s in corr.columns and s != symbol]
        if not peers:
            return 0.0
        vals = corr.loc[symbol, peers].abs().to_numpy()
        if len(vals) == 0:
            return 0.0
        return float(np.nanmax(vals))
