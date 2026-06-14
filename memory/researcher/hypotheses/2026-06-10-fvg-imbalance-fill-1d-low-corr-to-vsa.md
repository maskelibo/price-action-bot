---
doc_id: researcher-20260610T180000-fvg-imbalance-fill-1d-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T18:00:00Z
status: DRAFT
confidence: low
depends_on:
  - shared-lessons-overfitting
  - shared-lessons-survivorship
  - shared-lessons-lookahead
  - backtest-compounding-inflation
  - smc-course-no-edge
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, fvg, fair-value-gap, smc, low-correlation, vsa-orthogonal, curve-fit-watch]
supersedes: null
hash: null
---

# Hipotez — Fair Value Gap (FVG) Imbalance-Fill, vsa_climax_test'e Düşük Korelasyonlu Aday

## 0. Bağlam (neden bir FVG hipotezi, hem de SMC'nin "no edge" notuna rağmen?)

Aktif champion **vsa_climax_test** hacim-spike + bar-exhaustion mekaniği üzerine kurulu. Portföye **mekanik olarak ortogonal** bir aday arıyoruz; son 7 günde sınanan adaylar (Donchian-20, Marubozu, Mat Hold, BOS-3bar, ATR-k, Volman ii/iii, MA50/200, Brooks H2/L2, Grimes anti-climax, Equal-highs sweep) ya breakout/momentum ya da tek-bar reversal — hiçbiri **çok-bar imbalance/gap-fill** mekaniğini test etmedi.

**Curve-fit kırmızı bayrak #0 — başta deklare:** Memory'de [[smc-course-no-edge]] dersi var: "161 video tam test edildi; 4 mekanizma da kripto bar'da RED; tekrar test etme." FVG bu 4 mekanizmadan biri olabilir; ama derste **hangi 4 mekanizma** olduğunun açık spesifikasyonu memory index'te yok. Bu hipotezi yazmadan önce **bu kontrol zorunlu** (aşağıda Stop Criteria §8 madde 1). Daha önce reddedildi ise hipotez **yazılmadan** çekilir, "tekrar test etme" 4. seferdir olurdu.

Hipotezin yazılma gerekçesi: SMC dersinde reddedilen FVG'nin **hangi spesifikasyonla** reddedildiği bilinmiyor olabilir (entry timing, gap eşiği, fill horizon). Eğer red "displacement > ATR*0.30, anında entry" ile geldiyse, "displacement > ATR*0.50, 2-bar gecikmeli fill-zone touch" farklı bir test olabilir. Ama bu argüman **kolayca p-hacking'e dönüşür** — bu yüzden Stop Criteria sert: önce arşiv kontrolü, kontrol negatifse hipotez **YAZILMADAN ÖLÜR**.

## 1. Iddia (pre-registered, ölçülebilir)

> **1D timeframe'de, USDT-perpetual likit evren (≥ 50 sembol, survivorship-corrected, 2022-01-01 → 2025-12-31), bullish FVG (3-bar kalıbı: bar1.high < bar3.low, gap_size ≥ k×ATR(14)) oluştuktan sonra fiyat gap zone'una geri döndüğünde (mitigation), gap'in üst sınırında limit-entry; SL = gap alt sınırının altı (gap_size × 1.2); TP = gap_size × 2.0 (sabit-R); maksimum bekleme 10 bar. Fee 7.5 bps taker / -1 bp maker + 5 bps slippage altında:**
>
> - **OOS annualized net return** > **%30** (in-sample %45 hedefi, OOS düşüş kabul)
> - **OOS Sharpe** > **0.8** (in-sample %30 düşüşe izin)
> - **OOS MaxDD (equity-base, sabit-fraksiyon)** < **%30** ([[backtest-compounding-inflation]] uyumlu)
> - **vsa_climax_test ile günlük getiri korelasyonu** | ρ_pearson | < **0.25** (rolling 90d, OOS ortalama)
> - **Trade sayısı (3y, 50 sembol)** ≥ **120** (overfit-base-rate kontrolü; N<120 → istatistiksel anlamsız, otomatik red)

Bu **beş eşiğin tümü** aynı anda geçilmezse hipotez reddedilir.

## 2. Null Hipotez

> FVG mitigation entry'sinin OOS net Sharpe'ı **0**'a istatistiksel olarak ayırt edilemez (shuffle baseline t-testinde p > 0.05).
> VEYA vsa_climax_test ile korelasyon ≥ 0.25 → "aynı pivot rejimini yakalıyor".
> VEYA trade sayısı < 120 → "edge gerçek bile olsa sample yetersiz, sample'ı büyütmek için kalibrasyon zorlamak = curve-fit".

## 3. Gerekçe (RAG referansları — eleştirel okuma)

- **[#6 market_structure_order_flow]:** "FVG (gap > ATR*0.15) — **Orta** mekanik çalışabilirlik. Tanım net ama **fill oranı değişken**." → Bu "fill oranı değişken" notu yapısal şüphenin kaynağı. Fill garantisi yoksa win-rate bar-bar değişir, rejim-bağlı olur → düşük Sharpe.
- **[#3 Brooks deep catalog]:** "n-bar high/low aşımı + geri dönüş — testable 5/5". FVG'nin **mitigation** komponenti Brooks'un "geri dönüş" çerçevesine yapısal olarak benzer; ama Brooks bunu **reversal bar kalitesi + HTF opposition** ile koşullandırır. FVG saf gap-fill mekaniği bu kalite filtrelerini kaybeder → daha çok false positive bekle.
- **[#1 Lopez de Prado overfitting kriterleri]:** "Strategy serbest parametre sayısı / örnek sayısı > 1/30 → red." Beklenen sample N=120-300, dolayısıyla **maks 4 serbest parametre** (k_atr_threshold, sl_mult, tp_mult, max_wait_bars). DSR < 0.5 ve PBO > 0.5 ek red sebepleri.
- **[#9 Chan]:** "Yeni stratejiler portföye girmeden önce out-of-sample Sharpe > 0.8." Bu eşik §1'e direkt taşındı.
- **[memory: smc-course-no-edge]:** 161-video SMC corpus'ta 4 mekanizma red. FVG bunlardan biri olabilir — Stop Criteria §8 madde 1 ile koruma altında.

## 4. Dependent Variables (ölçülecek metrikler)

| Metrik | Tip | Eşik | Yorum |
|---|---|---|---|
| Annualized net return (OOS) | continuous | > %30 | sabit-fraksiyon, fee+slip dahil |
| Sharpe (OOS) | continuous | > 0.8 | annualize √252 |
| MaxDD (equity-base, OOS) | continuous | < %30 | sabit-fraksiyon, cumulative-pnl base değil |
| Profit factor (OOS) | continuous | > 1.3 | info-only (gate değil) |
| Win rate (OOS) | continuous | n/a | info-only |
| Trade count (3y) | discrete | ≥ 120 | <120 ise otomatik red |
| Corr(strategy, vsa_climax_test) | continuous | \|ρ\| < 0.25 | rolling 90d, OOS |
| Shuffle baseline p-value | continuous | < 0.05 | null reddedildi mi |
| Bonferroni-corrected p | continuous | < 0.05 | Optuna trial sayısına göre düzeltilmiş |
| IS/OOS Sharpe ratio | derived | < 3.0 | Lopez de Prado kriteri |

## 5. Independent Variables (sweep — MAKS 4 SERBEST PARAMETRE)

| Param | Aralık | Adım | Justifikasyon |
|---|---|---|---|
| `gap_size_atr_mult` (k) | [0.30, 0.80] | 0.10 | RAG #6 0.15 önerdi; biz daha katı eşikle başla, false positive azalt |
| `sl_gap_mult` | [1.0, 1.5] | 0.10 | gap alt sınırının ne kadar altı |
| `tp_r_mult` | [1.5, 2.5] | 0.25 | gap_size cinsinden hedef |
| `max_wait_bars` | [5, 15] | 5 | mitigation gerçekleşmezse iptal |

**Toplam grid** = 6 × 6 × 5 × 3 = 540 kombinasyon. Optuna TPE + Median pruner, n_trials = 100. Bonferroni düzeltmesi: p_target = 0.05 / 100 = 0.0005.

**Sabit parametreler (sweep değil):**
- Pattern tanımı (3-bar bullish FVG: bar1.high < bar3.low) — değişmez.
- Entry: limit at gap upper edge (gap'in mitigation seviyesi).
- Direction: bullish-only **VE** bearish-only ayrı testler; ikisini birleştirme (correlation muhasebesi ayrı).
- Position sizing: %0.005 risk/trade (üretim default'una uyumlu).

## 6. Beklenen p-value ve Test Plani

- Shuffle baseline (returns shuffle, 1000 simülasyon) p < 0.05.
- Bonferroni sonrası n=100 trial için p < 0.0005.
- DSR (Deflated Sharpe Ratio) > 0.5.
- PBO (Probability of Backtest Overfitting) < 0.5.

## 7. Robustness Suite (zorunlu — hepsi geçmeli)

1. **Walk-forward** 3y/6m, step 3m → 12 dilim, **en az 7**'si pozitif net.
2. **In-sample / OOS Sharpe farkı** < %40 (Lopez de Prado IS Sharpe > 3·OOS → red kriteri).
3. **Parameter perturbation:** her parametre ±%10, 50 seed → ortalama Sharpe kayıp < %25.
4. **Symbol-out CV:** her sembolü tek tek dışarıda bırak; min OOS Sharpe ≥ 0.5 (kümülatif ortalamadan en fazla %40 düşüş).
5. **Regime split:** bull / bear / range — en az **2 rejimde** pozitif net.
6. **Stress periods (yıkıcı kayıp yok):** 2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC depeg), 2024-08 (Yen carry).
7. **Shuffle baseline:** p < 0.05.
8. **Lookahead test:** `detector(df.iloc[:t+1])[t] == detector(df)[t]` her t için. Bar3 oluşurken bar1/bar2 zaten kapanmış olmalı; **giriş t+1 bar open'ta** (gap mitigation bar'ı kapanışında karar, bir sonraki bar open'ta limit).
9. **Survivorship:** delisted sembollerin delist tarihine kadar dahil olduğu evren ([[memory: survivorship_bias]]).
10. **Bonferroni / DSR / PBO** §6'ya göre.

## 8. Stop Criteria (sırayla, herhangi biri tetiklenirse hipotez ölür)

1. **ÖN-KONTROL — kod yazılmadan önce:** `memory/researcher/learning.md` ve `memory/researcher/seed_abort_log.jsonl` taranır; "FVG / fair value gap / smc gap-fill / imbalance fill" şeklinde reddedilmiş kayıt var mı? VAR ise hipotez **çekilir** (smc-course-no-edge dersinin 4. tekrarı olmaz). YOKSA devam.
2. In-sample Sharpe < 0.5 → araştırma terkedilir (compute boşa).
3. In-sample trade count < 120 → sample yetersiz, kalibrasyon zorlamak yasak (curve-fit), terk.
4. Walk-forward 12 dilimden 7'sinden azı pozitif → red.
5. IS/OOS Sharpe oranı > 3.0 → red (Lopez de Prado).
6. Bonferroni sonrası p > 0.05 → red.
7. vsa_climax_test ile |ρ| ≥ 0.25 → portföy katkısı yok, red (cross-strategy hipotezi olarak amaca aykırı).
8. Lookahead test başarısız → red ve `signal_chief`'e incident report (FVG detector lookahead-paranoid yazılmalı).

## 9. Curve-Fit Kırmızı Bayraklar (yazılım önceden — gözlem sonrası "açıklama" yasağı)

- **SMC mekanizması 4. red** olma riski (madde §8.1 ön-kontrol).
- **Sister-pattern risk:** Mat hold (Jun 8 red), Volman ii/iii (Jun 10 red), Marubozu (Jun 7 red) — hepsi "consolidation/momentum kalıbı" alt-ailesi. FVG da imbalance-fill ailesi → aile-genelinde overfit base rate yüksek.
- **Gap eşiği kalibrasyonu hassas:** RAG 0.15 önerdi, biz 0.30-0.80 aralığı seçtik. Eğer **best param sınır değerinde** (0.30 veya 0.80) çıkarsa → overfit kırmızı bayrak (genişlet, yeniden test).
- **Mitigation horizon:** "10 bar" sabiti keyfi; max_wait_bars sweep'i bunu yumuşatıyor ama yine de [5, 15] dar bir aralık. Sınır değerde çıkarsa genişlet.
- **Bullish/bearish ayrı test:** Tek yöne overfit edip diğerini saklama riski → ikisi de pozitif olmazsa "tek-yönlü edge" arşivi (production'a sadece pozitif yön gider, ama doc'a yazılır).

## 10. Karar Çerçevesi

| Sonuç | Karar |
|---|---|
| Beş §1 eşiği + robustness §7 + stop §8'in tümü ✓ | **Terfi adayı** → `configs/strategies/fvg_imbalance_fill_1d.yaml` taslak + Lab tournament |
| §1'in 1-2 eşiği fail, ROI pozitif, korelasyon < 0.25 | **Iterate** (SOP-4b) — v2 risk-reduction veya v2 confluence-filter |
| §1'in 3+ eşiği fail VEYA korelasyon ≥ 0.25 VEYA stop §8 tetik | **Red — gerekçeli arşiv** (learning.md + seed_abort_log.jsonl) |
| Ön-kontrol §8.1 SMC arşivde FVG-red gösteriyor | **Hipotez yazılmadan ölür** (memory'ye not: smc-course 4. tekrar kaçırıldı) |

## 11. Reproducibility

- git_hash: (run sırasında stamp)
- config_hash: hypothesis_runner içinde otomatik
- data_hash: DuckDB snapshot hash, 2026-06-10 ingest manifest
- seed: 42 (Optuna), 1000 (shuffle baseline)

## 12. Beklenti (yazar tahmini, hipotezi etkilemez)

Yazarın subjektif önsel: **%70 red** (smc-course derslerinin ve sister-pattern run'larının base rate'ine bakarak). Pozitif çıkma ihtimali %30, korelasyon eşiğini geçme ihtimali pozitif olanların %50'si → toplam terfi olasılığı ~%15. Bu **negatif önsel** hipotezi rafa kaldırma sebebi DEĞİL — pre-registration disipliniyle test edilir, sonuç ne olursa olsun arşivlenir.

## 13. Lab'e Devir Notu (sonuç pozitifse)

- Tournament'a "challenger" olarak gir.
- Champion: vsa_climax_test.
- Promotion gates: DSR p < 0.05, effect ≥ %15 (Sharpe artışı), MaxDD ≤ champion + %5.
- Drift monitoring: live göre 30d KS test.
