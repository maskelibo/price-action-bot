---
doc_id: researcher-20260527T084500-rsi2-extreme-fade-iterate-v2-risk-reduction
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T08:45:00Z
status: DRAFT
confidence: med
iterate_from: hyp-2026-05-14-rsi2-extreme-fade
iterate_version: v2
iterate_theme: risk_reduction
depends_on:
  - 2026-05-14-rsi2-extreme-fade
  - active-state-current
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - iterate
  - risk_reduction
  - rsi2_extreme_fade
  - v2
supersedes: null
hash: null
---

# HYP-2026-05-27 — rsi2-extreme-fade iterate v2: risk reduction

## 0. Bağlam (Iterate Tetiği)

Baseline (v1): `hyp-2026-05-14-rsi2-extreme-fade`
- Aylık ROI: **+13.61%** (champion +12.99% ile uyumlu, hatta hafifçe daha yüksek!)
- DD: **-79.47%** (champion -15.48% ile karşılaştırınca 5x kötü)
- n_trades: 38131
- WR: %43 (varsayım, raw replay)

**Sorun:** Edge VAR (aylık ROI champion seviyesinde), risk KONTROLSÜZ. Persona SOP-4b'ye göre **REDDEDİLMEZ — iterate edilir**. Bu v2 risk-reduction patikasını test eder.

## 1. Iddia (H1)

**RSI2-extreme-fade base sinyali, agresif risk azaltma (risk_pct 0.005 → 0.002, max_concurrent 16 → 6, daily_dd 0.04 → 0.02) ile +DD'yi -20%'nin altına indirip aylık ROI'yi en az +%4 koruyabilir.**

Mantık: Çoğu DD episodes "aşırı agresif sizing × cluster losses" kaynaklı. Risk per trade ve concurrent pozisyon sayısını sıkılaştırınca:
- Cluster losses portfolio'da daha az ağırlık taşır (max_concurrent azaltma)
- Daily halt erken devreye girer (daily_dd 0.04 → 0.02)
- Position sizing daha küçük (risk_pct halve)

Sonuç: aylık ROI ~halve (13.61 × 0.4 = +5.4 tahmini), DD ~quarter (-79 × 0.3 = -24% tahmini). **Aday: aylık +5%, DD -20% — champion'a yakın ama farklı edge ailesi.**

## 2. Bağımsız değişkenler (parametre uzayı — grid)

```yaml
risk_pct: [0.001, 0.002, 0.003]              # baseline 0.005'ten 2-5x azaltılmış
max_concurrent_positions: [4, 6, 8]          # baseline 16'dan azaltılmış
daily_dd_halt_pct: [0.015, 0.02, 0.025]      # baseline 0.04'ten sıkılaştırılmış
monthly_dd_halt_pct: [0.10, 0.15, 0.20]      # baseline 0.99 yok-gibi → makul
consecutive_loss_pause: [3, 5, 7]            # baseline 0 → cluster losses break
```

Toplam grid: 3×3×3×3×3 = **243 cell**. Çoklu test düzeltmesi: Bonferroni α = 0.05/243 ≈ 0.000206.

## 3. Bağımlı değişkenler (pre-registered metrikler)

| Metrik | Hedef | Şart |
|---|---|---|
| Aylık ROI mean (5y compound) | **≥ +4%** | minimum survivable edge |
| Max DD (compound) | **≤ -20%** | champion +5pp buffer içinde |
| Neg ay sayısı (61 ay) | **≤ 18 (30%)** | |
| Sharpe (annualized) | **≥ 0.8** | risk-adjusted edge |
| OOS (son 1.5y) aylık ROI | **≥ +3%** | konsistens |
| Trade rate (n_trades) | ≥ 3000 (önceki 38K'tan azaltılmış olur) | statistik anlamlılık |

## 4. Kabul Kriteri (HARD gate — terfi adayı için hepsi geçmeli)

1. ✅ Aylık ROI ≥ +4% (5y span)
2. ✅ Max DD ≥ -20% (compound)
3. ✅ Neg ay ≤ 18/61 (%30)
4. ✅ TRAIN→OOS aylık ROI degradasyonu < %50
5. ✅ +65bps stress senaryosunda pozitif (LUNA/FTX replay)
6. ✅ DSR p (Bonferroni 243 trial) < 0.05

**Yedek karar yolu:**
- 1-2 cell geçerse → ŞANSLI, sadece bonus aday (Lab tournament + risk officer review)
- 3-5 cell geçerse → SAĞLIKLI, bu iterate başarılı
- 0 cell geçerse → v3 iterate (trade quality filter ekle)
- 10+ cell geçerse → SUSPICIOUS (overfit alarm — DSR ile incele)

## 5. Beklenen Sonuç Profili

| Senaryo | Olasılık | Ne yapacağız |
|---|---|---|
| 2-5 cell geçer (gate'i tutar) | %40 | Lab tournament — companion strategy adayı |
| 0 cell geçer (gate çok agresif) | %30 | v3 iterate: trade quality filter ekle (confluence ≥ 2.5) |
| Aylık ROI çöker (<+2%) | %20 | Edge sadece agresif sizing'le yaşıyormuş — v4 iterate: position management (BE-protect + trailing) |
| Tüm cell'ler patlar | %10 | Strateji terk (baseline rsi2 edge sahte olabilir — RAG ile re-validate) |

## 6. Stop Criteria

- In-sample aylık ROI < +2% → araştırma terkedilir, v3 iterate'e geç
- Tüm cell'lerde DD > -30% → risk azaltma yeterli değil, **trade quality** patikası (v3)
- Compute > 30 dk → batch size azalt veya pool ön-filtrele

## 7. Reproducibility

- `git_hash`: HEAD@2026-05-27 08:45 UTC
- `data_hash`: data/market.duckdb son timestamp
- `pool_source`: live strategy generate_signals → custom exit_detect (scripts/run_new_strategy_backtest.py)
- `config_hash`: bu YAML

## 8. RAG Referansları (delegated to Researcher v2 koşumunda)

- [Wilder 1978] RSI-2 fade literature
- [LarryConnors 2009] "Short Term Trading Strategies That Work" — RSI2 mean reversion
- Internal: backtest_results/hyp-2026-05-14-rsi2-extreme-fade.realistic.json

## 9. Notlar

Bu hipotez **Faz 14.22 iterate mekanizmasının ÖRNEK ÇIKTISI**. Manuel olarak yazıldı (örnek şablon), normalde:
- scripts/find_promising_to_iterate.py haftalık queue üretir
- Researcher persona SOP-4b'ye göre her aday için min 1 iterate hipotezi pre-register eder
- Bu hipotez Lab tournament'a teslim edilir, realistic_backtest koşturulur

Bu örnek Researcher'a "iterate hipotezi nasıl yazılır" şablonu — gelecekteki otomatik üretim bu kalitede olmalı.
