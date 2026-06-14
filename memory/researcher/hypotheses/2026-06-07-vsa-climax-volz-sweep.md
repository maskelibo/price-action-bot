---
doc_id: researcher-20260607T093000-vsa-climax-volz-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T09:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, vsa, volume_z, parameter_sweep, curve_fit_risk, pre_registration]
supersedes: null
hash: null
---

# HYP-2026-06-07-vsa-climax-volz-sweep

## 0. Curve-Fit Honesty Warning (pre-amble)

Bu seed (vsa_climax_test üzerinde vol_z parameter sweep) **klasik curve-fit
patern**: canlıda **deploy edilmiş** bir stratejinin **tek bir parametresini**
in-sample veriyle yeniden ararsak, "best vol_z" neredeyse kesin **noise +
deployment-period selection bias** çıkarır. Bu nedenle:

1. Grid **DAR** tutulur (4 nokta, 0.5 step) — 0.1 adımlı ince tarama YASAK.
2. Family-wise N (cross-seed register) bugün ≥34 (v12 abort log) → +4 trial =
   N=38. Holm-α = 0.05 / 38 = **0.001316** per-test. Bu bar geçilmezse REJECT.
3. OOS holdout = canlı deployment dönemi (2026-04-15 → bugün) **dışarıda**;
   sweep yalnız 2023-01-01 → 2026-04-14 IS dilimi üzerinde.
4. Canlı vsa_climax_test 30d rolling P&L (Welch t-test, BH-FDR) referans null.
   "Best threshold" canlıyı yenmek zorunda, **gross** edge'de değil **net**
   günlük-Sharpe CI > 0'da.

Eğer iddia geçmezse `hypotheses/2026-06-07-vsa-climax-volz-sweep-REJECT.md`
yazılır. Iterate yasak — yine sweep grid'i genişletmek aileyi şişirir.

---

## 1. İddia (pre-registered, ölçülebilir)

> "1h timeframe'de, mevcut `vsa_climax_test` detector'ının `vol_z_min` parametresi
> {1.5, 2.0, 2.5, 3.0} arasında 4 noktada test edildiğinde, EN AZ BİR eşik,
> 2023-01-01 → 2026-04-14 IS dönemi, 15 aktif sembol evreni, taker 7.5bps + 5bps
> slippage maliyet modeli altında aşağıdakileri **HEPSİNİ** karşılayan istatistiksel
> olarak anlamlı bir konfigürasyon üretir:
>
> - IS mean net R-multiple > +0.15
> - IS Sharpe (daily) > 0.80
> - IS/OOS Sharpe oranı **< 1.50** (overfit kalkan)
> - Shuffle-baseline p_gross < 0.05 (yön anti-fit)
> - Per-year sign consistency: 6 yıldan en az 5'i pozitif net R toplamı
> - Holm-α (N=38) sonrası p < 0.001316
> - OOS (2026-04-15 → 2026-06-06) net günlük Sharpe CI alt sınırı > 0
> - Canlı vsa_climax_test 30d rolling mean R'sini Welch t-testinde
>   p<0.05 ile **POZİTİF** yönde aşar (≥ +15% relative lift)."

## 2. Null hipotez

H₀: Vol_z eşiği değiştirmek, vsa_climax_test'in net R-multiple dağılımının
ortalamasını canlı baseline'a göre değiştirmez (mean-fark = 0, Welch p ≥ 0.05).

H₀ red edilemezse → eşik araması **bilgisizlik**: mevcut default eşiği koru.

## 3. Gerekçe (RAG)

- **[volume_price_divergence]** vol_z = (V[t] − μ₂₀)/σ₂₀ tanımı; threshold önerisi
  "Başlangıç ±2.0σ, Güçlü ±2.5σ, Aşırı ±3.0σ" (RAG #4, #9). Bu, grid'imizin
  literatür-uyumlu üst/alt sınırını verir. {1.5, 2.0, 2.5, 3.0} — uçlar dahil 4 nokta.
- **[volume_price_divergence #9]** Stopping volume: vol_z>2.0 + spread<0.8×ATR +
  range-orta kapanış → reversal candidate. Bu vsa_climax_test'in zaten
  uyguladığı mekanik — sweep parametre değil mekanizma değişikliği DEĞİL.
- **[smc/ict #5, #7]** Sweep + reclaim mekaniği için ek vol filter ≥1.5× ortalama
  şartı; vol_z=1.5 ≈ 86. yüzdelik → bu alt sınırın "spike değil" bölgesine
  kaymasını engeller (RAG'a göre 1.5'in altı zayıf sinyal kümesi).

RAG'da ince-grid (her 0.1) için **destek YOK**; literatür kaba bölgeler önerir.
0.5 step bu yüzden seçildi (over-fit defense, RAG-grounded).

## 4. Independent variables

Yalnız bir parametre değişir:

| Param | Grid | Step | Trial sayısı |
|---|---|---|---|
| `vol_z_min` | {1.5, 2.0, 2.5, 3.0} | 0.5 | 4 |

Tüm diğer parametreler vsa_climax_test'in **mevcut canlı config**'inden DONUK:
spread_atr, range_close_pct, atr_window, sl ATR çarpanı, TP R, time-exit,
htf_filter, regime_gate. **Hiçbiri sweep'e dahil değil** — multi-param
sweep yasak (combinatorial explosion = garanti curve-fit).

## 5. Dependent variables (önceden taahhüt)

Birincil: **net daily Sharpe** (IS + OOS).
İkincil:
- mean net R-multiple
- IS/OOS Sharpe oranı (overfit kalkanı)
- Shuffle-baseline p_gross (yön anti-fit)
- Per-year sign consistency (6 yıl)
- Welch t-test vs canlı vsa_climax_test 30d
- Bonferroni/Holm-α post p-value

Pre-commit: yukarıdaki sırada raporlanır; her metrik kendi gate'inde durur.
"Şu metrik kötü ama bu iyi" cherry-picking yasak — **HEPSI** geçmek zorunda.

## 6. Beklenen p-value

- Gross-edge shuffle: p_gross < 0.05 (her trial bağımsız)
- Welch (canlı baseline vs aday): p < 0.05
- Holm-α (N=38 family-wise): p < 0.001316

Beklenti **DÜŞÜK**: 4 trial × 8 metric gate, sıkı Holm-α → tarihsel base-rate
(SMC continuation 24 config × 0/24 geçti; cross-strategy seed v1-v12 → 0/12)
sıfıra yakın. Bu yüzden **confidence: low** — null hipotezi yenememe ihtimali
yüksek; pre-register tam da bu yüzden gerekli.

## 7. Stop criteria (terkedme şartları — her biri tek başına yeter)

1. IS Sharpe (en iyi trial) < 0.5 → araştırma terkedilir, REJECT doc.
2. Tüm 4 trial Holm-α'yı geçemezse → REJECT (family-wise burnout).
3. IS/OOS Sharpe oranı > 2.0 → curve-fit kanıtı, REJECT.
4. Per-year < 4/6 pozitif → regime-luck, REJECT.
5. Canlı baseline'a karşı Welch p > 0.10 **veya** mean-fark işareti negatif →
   "best threshold canlıdan kötü" — REJECT.
6. Shuffle p_gross > 0.10 herhangi bir trial'da → yön anti-fit kırık, REJECT.
7. Trade sayısı n < 100 herhangi bir trial'da → istatistik anlamsız, REJECT.

## 8. Backtest setup (frozen pre-execution)

- Universe: 15-sym crypto perp (vsa_climax_test'in canlı evrenine bit-identical)
- Timeframe: 1h (primary), 1d (HTF filter — canlı configtan)
- IS: 2023-01-01 → 2026-04-14
- OOS holdout (TOUCH'SUZ): 2026-04-15 → 2026-06-06
- Fees: 7.5 bps taker (entry+exit = 15 bps round-trip)
- Slippage: 5 bps
- Risk model: vsa_climax_test canlı configinden (risk_pct, max_concurrent,
  daily_dd_halt aynı — sadece signal threshold sweep'i)
- Engine: `src/price_action/backtest/engine.py` HEAD@audit-hardreview branch
- Seed (shuffle): 50 fixed seeds (deterministic, reproducibility için)

## 9. Karar matrisi (önceden taahhüt)

| Durum | Karar |
|---|---|
| 0 trial gate'i geçer | REJECT — null reddedilemedi |
| 1+ trial tüm gate'leri geçer | TERFİ adayı → Lab tournament |
| Best trial 7 gate'ten 6'sını geçer | REJECT — "kısmen geçti" curve-fit'in görüntüsü |
| Canlı baseline'ı yenen var ama IS/OOS > 1.5 | REJECT — curve-fit |
| Hiçbiri canlıyı yenmiyor ama hepsi pozitif Sharpe | REJECT — "edge var ama mevcuttan iyi değil" = iterate yasak (canlı zaten edge) |

## 10. Reproducibility

- git_hash: HEAD audit-hardreview-20260528 (commit fd80d4c snapshot)
- config_hash: pre-execution donduralacak
- data_hash: `data/market.duckdb` SHA-256 pre-execution donduralacak

---

## Sonuç (pre-execution)

Bu hipotez **terfi olasılığı düşük** bilinerek yazıldı. Family-wise burden (N=38,
Holm-α 0.001316) + canlı baseline benchmark + 7 sıkı stop criteria + OOS
holdout, "sweep ile iyi parametre buldum" curve-fit anlatısını kanıt
gerektiren bilim haline çevirir. Çoğu olası sonuç: REJECT, default eşik korunur,
bilgi kazanımı = "vol_z sweep bu evrede ölçülebilir lift üretmiyor".

REJECT bile bilgidir — learning.md'ye eklenir.
