"""Market Scout Agent — Cross-Market Feasibility & Cross-Exchange Arb Scout (Faz 11).

Aylık 1 pazar feasibility study + haftalık 1-2 cross-exchange arb scan üretir.
Çıktı yalnızca **research** doc'u (`doc_type: market_feasibility` /
`market_arb_scan`); deployment kararı CEO + Principal'dadır.

Persona: Bridgewater macro + Hudson River cross-exchange scout + Marko Kolanovic
cross-asset strateg. Hard limit: ASLA live trading veya `configs/strategies/`
final yazımı yapmaz.

Mevcut deployment SADECE crypto (Binance USDM, 10 sembol); scout başka pazarları
**araştırır** ama dokunmaz.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

import yaml

from price_action.logging_config import logger
from price_action.rag import retrieve_for_hypothesis
from price_action.settings import get_settings

from .base import LLMAgentBase

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", s.lower()).strip("-")[:60] or "market"


class MarketScoutAgent(LLMAgentBase):
    """Market Scout — cross-market feasibility studies + cross-exchange arb scans."""

    name: ClassVar[str] = "market_scout"
    default_model: ClassVar[str] = ""  # Opus (settings.claude_model_default)
    allowed_tools: ClassVar[tuple[str, ...]] = (
        "read_file",
        "write_report",
        "web_search",
        "rag_retrieve",
    )

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        if not self.model:
            self.model = self.settings.claude_model_default

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------

    def _reports_dir(self) -> Path:
        s = get_settings()
        p = s.reports_dir / "market_scout"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _calendar_path(self) -> Path:
        s = get_settings()
        return s.configs_dir / "market_scout_calendar.yaml"

    def load_calendar(self) -> dict[str, Any]:
        """`configs/market_scout_calendar.yaml`'ı parse et."""
        p = self._calendar_path()
        if not p.exists():
            logger.warning(
                "market_scout.calendar_missing",
                extra={"path": str(p)},
            )
            return {"rotation": [], "starting_month": 1}
        try:
            with p.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:  # pragma: no cover - defansif
            logger.error(
                "market_scout.calendar_parse_fail",
                extra={"err": str(exc)[:200]},
            )
            return {"rotation": [], "starting_month": 1}
        return data

    def select_market_for_month(
        self,
        *,
        target_month: int | None = None,
        calendar: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Rotation'dan bu ay (veya verilen ay) hangi pazar sırada olmalı?

        `target_month` verilmezse bugünün ayını kullanır. Rotation listesi
        kısa ise modulo ile sarar.
        """
        cal = calendar or self.load_calendar()
        rotation: list[dict[str, Any]] = cal.get("rotation") or []
        if not rotation:
            return None
        starting_month = int(cal.get("starting_month", 1))
        m = int(target_month) if target_month else date.today().month
        # offset: starting_month → rotation[0]
        idx = (m - starting_month) % len(rotation)
        return rotation[idx]

    def select_market_for_week(
        self,
        *,
        target_date: date | None = None,
        calendar: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """FIX 2026-05-26: haftalık rotation (aylık yerine).

        Aylık rotation 5 pazar/yıl × ~2.4 = çok yavaş. Haftalık rotation:
        ISO hafta numarası modulo rotation uzunluğu → 5 haftada tüm pazarları
        gez. ~10× hızlı kapsama.
        """
        cal = calendar or self.load_calendar()
        rotation: list[dict[str, Any]] = cal.get("rotation") or []
        if not rotation:
            return None
        d = target_date or date.today()
        iso_week = d.isocalendar()[1]
        idx = (iso_week - 1) % len(rotation)
        return rotation[idx]

    def find_market_entry(
        self, market_name: str, *, calendar: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Calendar'dan isimle pazar slot bul."""
        cal = calendar or self.load_calendar()
        for slot in cal.get("rotation") or []:
            if slot.get("market") == market_name:
                return slot
        return None

    @staticmethod
    def _weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
        total = 0.0
        wsum = 0.0
        for key, w in weights.items():
            v = float(scores.get(key, 0.0))
            # Clamp 0..1
            v = max(0.0, min(1.0, v))
            total += v * float(w)
            wsum += float(w)
        if wsum <= 0:
            return 0.0
        return total / wsum

    @staticmethod
    def _verdict_from_score(score: float, thresholds: dict[str, float]) -> str:
        go = float(thresholds.get("GO", 0.75))
        defer = float(thresholds.get("DEFER", 0.50))
        if score >= go:
            return "GO"
        if score >= defer:
            return "DEFER"
        return "NO_GO"

    # ------------------------------------------------------------------
    # SOP-1: Monthly feasibility study
    # ------------------------------------------------------------------

    async def monthly_feasibility_study(
        self,
        target_market: str | None = None,
        *,
        target_month: int | None = None,
    ) -> Path | None:
        """Ayın sıradaki (veya verilen) pazarı için feasibility study üretir.

        Akış:
        1. Calendar yükle, hedef slot belirle.
        2. RAG'den ilgili microstructure literatürü çek.
        3. LLM'e 5-boyutlu skorlama + verdict prompt'u gönder.
        4. `write_protocol_doc(doc_type="market_feasibility", ...)`.

        Parameters
        ----------
        target_market : optional
            Pazar adı (`forex_majors`, `bist_xu100`, ...). Yoksa rotation kullanılır.
        target_month : optional
            Ay (1..12). Rotation seçimine etki eder.

        Returns
        -------
        Path | None
            Yazılan feasibility raporu yolu, yoksa None.
        """
        cal = self.load_calendar()
        slot: dict[str, Any] | None = None
        if target_market:
            slot = self.find_market_entry(target_market, calendar=cal)
            if slot is None:
                logger.warning(
                    "market_scout.market_not_in_calendar",
                    extra={"market": target_market},
                )
                return None
        else:
            slot = self.select_market_for_month(target_month=target_month, calendar=cal)
        if slot is None:
            logger.warning("market_scout.no_rotation_slot")
            return None

        market_name = str(slot.get("market", "unknown"))
        symbols = list(slot.get("symbols") or [])
        data_hint = str(slot.get("data_source_hint", ""))
        notes = str(slot.get("notes", ""))
        weights = cal.get("feasibility_weights") or {
            "data_availability": 0.25,
            "strategy_adaptability": 0.30,
            "risk_model_complexity": 0.20,
            "regulatory_burden": 0.15,
            "edge_potential": 0.10,
        }
        thresholds = cal.get("verdict_thresholds") or {"GO": 0.75, "DEFER": 0.50}

        # RAG retrieve — pazar mikroyapı / regülasyon literatürü
        try:
            seed = (
                f"{market_name} market microstructure spread fee rollover "
                f"regulatory feasibility cross-exchange"
            )
            hits = retrieve_for_hypothesis(seed, k=6)
        except Exception as exc:
            logger.warning(
                "market_scout.rag_fail",
                extra={"err": str(exc)[:200]},
            )
            hits = []

        rag_block = (
            "\n\n".join(
                f"[#{i+1} score={h.score:.3f} src={h.metadata.get('source_id', '?')}]\n"
                f"{h.text[:400]}"
                for i, h in enumerate(hits)
            )
            or "(RAG corpus boş veya hit yok)"
        )

        prompt = (
            "SOP-1 Monthly Feasibility Study. Aşağıdaki pazar slot'u için "
            "5 boyutta (0-1 arası) skor üret, weighted total hesapla, "
            "GO/DEFER/NO_GO verdict ver. **Sayı olmayan iddia yazma.**\n\n"
            "MARKET SLOT:\n"
            f"- market: {market_name}\n"
            f"- symbols: {symbols}\n"
            f"- data_source_hint: {data_hint}\n"
            f"- notes: {notes}\n\n"
            f"WEIGHTS: {json.dumps(weights, indent=2)}\n"
            f"VERDICT THRESHOLDS: {json.dumps(thresholds, indent=2)}\n\n"
            "RAG REFERENCES (microstructure / regulatory):\n"
            f"{rag_block}\n\n"
            "GÖREV:\n"
            "1. Her boyut için 0-1 skor (data_availability, strategy_adaptability, "
            "risk_model_complexity [inverse: 1=düşük complexity], "
            "regulatory_burden [inverse], edge_potential).\n"
            "2. Weighted total (formül yazılı görünsün).\n"
            "3. Verdict (GO/DEFER/NO_GO).\n"
            "4. WebSearch ile son 90g düzenleme/fee karşılaştırma yap, "
            "kaynakları markdown ref listesinde göster.\n"
            "5. Eğer GO/DEFER ise: Researcher'a teslim edilecek 2-3 seed konu, "
            "Risk Officer'dan istenecek pre-mortem başlıkları.\n\n"
            "ÇIKTI FORMATI (agents/market_scout.md SOP-1 template'i):\n"
            "Markdown başlıkları: ## 1. Context, ## 2. Data Availability, "
            "## 3. Strategy Adaptability, ## 4. Risk Model Complexity, "
            "## 5. Regulatory Burden, ## 6. Edge Potential, "
            "## 7. Weighted Score → Verdict, ## 8. Recommended Next Steps, "
            "## 9. References."
        )

        body_text = await self.run(prompt, max_tokens=6000)

        # Header — deterministik özet (LLM body üstüne)
        now = datetime.now(UTC)
        header = (
            f"# Market Feasibility — {market_name} — {now.strftime('%Y-%m')}\n\n"
            f"- Reproducibility: scout_run_at={now.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
            f"- Rotation slot: month_target={target_month or now.month}\n"
            f"- Symbols: {symbols}\n"
            f"- Weights: `{json.dumps(weights)}`\n"
            f"- Verdict thresholds: `{json.dumps(thresholds)}`\n\n"
            "---\n\n"
        )
        full_body = header + body_text.strip() + "\n"

        slug = f"{market_name}-{now.strftime('%Y-%m')}"
        path = self.write_protocol_doc(
            doc_type="market_feasibility",
            body=full_body,
            slug=slug,
            target_dir=self._reports_dir(),
            status="DRAFT",
            confidence="med",
            requested_review_from=["ceo", "risk_officer", "researcher"],
            tags=["market_scout", "feasibility", market_name],
        )
        logger.info(
            "market_scout.feasibility_written",
            extra={"market": market_name, "path": str(path)},
        )
        self.record_episodic(
            f"monthly_feasibility_study market={market_name}",
            tags=["feasibility", market_name],
        )
        return path

    # ------------------------------------------------------------------
    # SOP-2: Quick cross-exchange arbitrage scan
    # ------------------------------------------------------------------

    async def quick_opportunity_scan(
        self,
        market_pair: tuple[str, str],
        *,
        symbol: str = "BTC/USDT:USDT",
    ) -> Path | None:
        """Lite cross-exchange arb scan (30dk iş).

        Örnek: `("binance", "bybit")` → BTC perp fee/spread/funding farkı raporu.
        Sadece public market data niyetiyle yazılır; **gerçek ccxt çağrısı yok**
        (LLM'e brief verilir, gerçek market data fetch ileri fazda eklenir).

        Parameters
        ----------
        market_pair : tuple[str, str]
            (exchange_A, exchange_B), örn. ("binance", "bybit").
        symbol : optional
            Pair sembolü, default BTC perp.

        Returns
        -------
        Path | None
            Yazılan arb scan raporu yolu.
        """
        if not market_pair or len(market_pair) != 2:
            logger.warning(
                "market_scout.invalid_arb_pair",
                extra={"pair": market_pair},
            )
            return None
        ex_a, ex_b = market_pair[0], market_pair[1]

        # RAG — cross-exchange funding/arb literatürü
        try:
            seed = (
                f"{ex_a} {ex_b} cross-exchange perpetual funding arbitrage "
                f"taker fee spread microstructure"
            )
            hits = retrieve_for_hypothesis(seed, k=4)
        except Exception as exc:
            logger.warning(
                "market_scout.rag_fail_arb",
                extra={"err": str(exc)[:200]},
            )
            hits = []

        rag_block = (
            "\n\n".join(
                f"[#{i+1} score={h.score:.3f} src={h.metadata.get('source_id', '?')}]\n"
                f"{h.text[:350]}"
                for i, h in enumerate(hits)
            )
            or "(RAG corpus boş)"
        )

        prompt = (
            "SOP-2 Quick Cross-Exchange Arb Scan. **Lite** 30dk iş — "
            "sadece public market data (orderbook top-of-book, funding rate, "
            "fee schedule) gözlemi rapor edilir. **Asla 'alım yapılmalı' "
            "ifadesi yazma**; sadece 'gözlem' ve 'persistence skoru'.\n\n"
            f"PAIR: {ex_a} vs {ex_b}\n"
            f"SYMBOL: {symbol}\n\n"
            "RAG REFERENCES:\n"
            f"{rag_block}\n\n"
            "GÖREV:\n"
            "1. Her iki borsanın taker/maker fee tier'larını (son 90g) WebSearch ile özetle.\n"
            "2. Funding rate son 7g median + dağılım (kaynak: ccxt public REST varsayımı; "
            "şu an gerçek çağrı yok, LLM literatürden estimate verir).\n"
            "3. Round-trip cost = taker_A + taker_B + 0.5*(spread_A + spread_B) + slippage_est.\n"
            "4. Persistent funding diff vs round-trip cost karşılaştır.\n"
            "5. Persistence skoru (0-1): kaç saat/gün pozitif edge gözlemlendi.\n"
            "6. Karar: 'gözleme devam' / 'arşivle, kalıcı edge yok' (asla 'deploy').\n\n"
            "ÇIKTI: ## 1. Pair Context, ## 2. Fee Comparison, ## 3. Funding Diff, "
            "## 4. Round-Trip Cost, ## 5. Persistence Score, ## 6. Observation Verdict, "
            "## 7. References."
        )

        body_text = await self.run(prompt, max_tokens=3500)

        now = datetime.now(UTC)
        header = (
            f"# Cross-Exchange Arb Scan — {ex_a} vs {ex_b} — {now.strftime('%Y-%m-%d')}\n\n"
            f"- Symbol: `{symbol}`\n"
            f"- Mode: LITE (public data observation only)\n"
            f"- Run at: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
            "**HARD LIMIT:** Bu doc gözlemdir, deploy kararı değildir.\n\n"
            "---\n\n"
        )
        full_body = header + body_text.strip() + "\n"

        slug = f"arb-{ex_a}-{ex_b}-{now.strftime('%Y%m%d')}"
        path = self.write_protocol_doc(
            doc_type="market_arb_scan",
            body=full_body,
            slug=slug,
            target_dir=self._reports_dir(),
            status="DRAFT",
            confidence="low",
            requested_review_from=["ceo", "researcher"],
            tags=["market_scout", "arb_scan", ex_a, ex_b],
        )
        logger.info(
            "market_scout.arb_scan_written",
            extra={"pair": [ex_a, ex_b], "path": str(path)},
        )
        self.record_episodic(
            f"quick_opportunity_scan pair={ex_a}-{ex_b}",
            tags=["arb_scan", ex_a, ex_b],
        )
        return path
