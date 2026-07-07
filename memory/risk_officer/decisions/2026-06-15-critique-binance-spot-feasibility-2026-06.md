---
doc_id: risk_officer-20260615T143000-critique-binance-spot-feasibility-2026-06
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-15T14:30:00Z
status: PROPOSED
confidence: high
depends_on: [market_scout-20260615T090255-binance_spot-2026-06]
blocks: []
requested_review_from: [ceo]
tags: [critique, market_feasibility, binance_spot, concentration_risk, long_only_tail, correlation_gate]
supersedes: null
---

CRITIQUE

## Claim
Binance Spot BTC/ETH/BNB/SOL/ADA evreninde long-only 1× kaldıraçlı işlem yapmanın GO kriterini karşıladığı ve mevcut strateji portföyüyle uygulanabilir edge üretebileceği.

## Disagreement
Long-only kısıtı + 5 yüksek-korelasyonlu kripto varlık kombinasyonu, `configs/risk.yaml` korelasyon kapısını fiilen bloke eder ve 2022-tipi bear rejiminde %70-90 portföy DD açığa çıkarır; rapor bu kuyruk riskini quantify etmemiş, post-constraint (long-only filtreli) strateji edge'ini backtest kanıtı sunmadan varsaymıştır.

## Evidence

1. **Korelasyon kapısı ihlali (configs/risk.yaml doğrudan atıf):**
   `correlation_gate.hard_block_at = 0.9` — BTC/ETH/BNB/SOL/ADA arasındaki 90-günlük pairwise korelasyon, 2022 bear + 2024-08 Yen Carry Unwind dönemlerinde ölçülen değerler 0.85-0.95 bandındaydı. Bu demek ki 5 sembolden 3-4'ü eş zamanlı `hard_block` eşiğine düşer → portföy pratikte bloke olur. Kalan 2 sembol için `reduction_factor = 0.5` aktive olur → `max_per_symbol_pct = 0.20` ile zaten kısıtlıyken nominal size yarıya iner, effective exposure trivial kalır.

2. **Long-only + kripto bear = hedge yok:**
   2022 yıllık kayıplar: BTC -%65, ETH -%68, BNB -%55, SOL -%95, ADA -%90. Long-only spot portföyde bu periyotta hiçbir savunma mekanizması yoktur; futures tarafında short / hedge açma imkânı da yoktur. Rapor tail-analysis bayrağı "true" döndürmüş ancak somut MaxDD projeksiyonu (2022 bear, 2024-08 flash) doküman gövdesinde görülmüyor.

3. **Sinyal yarılanması kanıtsız:**
   `vsa_climax`, `phoenix_scalp_15m`, `brooks_failed_breakout`, `anchored_vwap_reversal` → hepsi **bi-yönlü tasarlanmış**, long bacağı izole edildiğinde kalan yarı sinyal setinin walk-forward OOS Sharpe'ı bilinmiyor. "Long bacağı çalışır" varsayımı; strateji robustness suite'i bu kısıt altında çalıştırılmadan öne sürülmüş.

4. **Fee erosion — calibrasyon eksik:**
   Spot taker 0.10% vs mevcut perp ~0.04% (VIP-0). 2-way round-trip spot = 0.20%, perp = 0.08%. 15m barlar için WIDESTOP sl_pct_min = 0.025 mevcut sistemde perp feelerine göre calibrate edilmiş; spot'ta aynı eşik geçersiz (fee/stop-ratio bozulur). Rapor bu hesabı yapmamış.

5. **`max_per_category_pct = 0.40` + tek kategori:**
   5 sembol de "crypto-largecap" kategorisi → coğunluğu aşar. `concentration_limits` açısından tüm open pozisyonlar tek kategoride yığılır. Mevcut 11-sembol perp evreninde kategori çeşitliliği var; spot pilot bunu bozmadan eklenemez.

## Alternative
**DEFER — şu koşullar sağlanana kadar:**

1. **Scope daralt — 2 sembol pilot (BTC/USDT + ETH/USDT):**
   Korelasyon hâlâ yüksek ama en likit, en az crash-wipeout riski. `concentration_limits` açısından 2 varlık ≤ 2 slot (max_open_positions=8 içinde rahat).

2. **Adversary Engineer: 2022-01 → 2022-12 long-only stress backtest:**
   MaxDD < 30% ve Sharpe > 0.5 görülmeden GO verilemez. Bu test olmadan "tail_analysis_done=true" credible değil.

3. **Researcher: long-only filtreli walk-forward:**
   Sadece `session_orb` (full compatible) + `chan_halflife` (ilkesel uyumlu) ile 2-sembol OOS Sharpe > 0.5 kanıtı. Yarı-uyumlu stratejiler (`vsa_climax`, `phoenix_scalp`, `brooks`, `anchored_vwap`) spot için ayrı onay almadan dışarıda.

4. **Fee-adjusted sl_pct_min hesabı:**
   Spot 0.10% taker ile 15m'de minimum stop mesafesi en az 2× perp eşiğine çıkarılmalı (öneri ≥ 0.050). Risk.yaml güncellemesi sadece human_principal yapabilir; bu bir öneri notudur.

## What would change my mind
1. Adversary Engineer 2022 stress raporu: long-only 2-sembol (BTC+ETH) MaxDD < 30%, Sharpe > 0.5 — somut sayılarla.
2. Researcher'dan long-only filtreli walk-forward: `session_orb` + `chan_halflife` OOS Sharpe > 0.5, N_trades > 200.
3. Pairwise korelasyon heatmap (son 90-gün + 2022 stress): tüm çiftlerde `hard_block_at = 0.9` altında kaldığı gösterilirse korelasyon itirazım düşer.
4. 2-sembol pilot olarak scope daraltılmış yeni feasibility versiyonu — 5 sembol → 2 sembol; rapor yenilenirse bu critique supersede edilir.
