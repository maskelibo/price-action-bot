---
doc_id: researcher-20260603T120000-vsa-widestop-slpctmin-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T12:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - researcher-20260602-v12-entry-quality-vsa-widestop
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [vsa, widestop, sl_pct_min, parameter_sweep, curve_fit_high_risk, pre_registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-03-vsa-climax-test-widestop-sl-pct-min-sweep

**Pre-registered BEFORE code.** git=a8f72539, data=market.duckdb (BTC+altperp 15m
2021-05..2026-06). Champion config = `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`.

> ⚠️ **CURVE-FIT ALERT — bu hipotez tek başına bir parametre sweepi.** Pre-registration
> zorunlu çünkü "best sl_pct_min" optimizasyonu klasik p-hacking yüzeyidir. v12
> (HYP-2026-06-02) zaten WIDESTOP-up'in mean_R artışını **sample-shrink artefaktı**
> olarak teşhis etti. Bu sweep'in **a priori beklentisi NEGATİF**.

## 1. Iddia (tek cümle, ölçülebilir)
> "BTC+altperp 15m, vsa_climax_test sinyal evreninde, sl_pct_min ∈ {0.020, 0.022,
> 0.025 (baseline), 0.028, 0.030, 0.033, 0.035, 0.040} parametre sweep'i içinde,
> **OOS [2024-01..2026-06] mean_R** ve **OOS day-Sharpe @55bps net**'i baseline
> (0.025) üzerinde, IS/OOS ratio < 1.5 + BH-FDR (n=8) alpha=0.05 + shuffle p_gross
> < 0.05 ile, **n_oos_trades ≥ 150** koşulunu KORUYARAK, anlamlı şekilde artıran
> **EN AZ 1 eşik değeri** vardır."

## 2. Null hypothesis (Popper — önce yazılır)
**H0 (a priori bahis):** Sweep'in HİÇBİR eşiği yukarıdaki 4 kriteri (delta-OOS-mean_R
> 0 AND IS/OOS ratio < 1.5 AND BH-FDR sig AND n_oos ≥ 150) AYNI ANDA geçemez. Görünür
"iyileşmeler" salt **sample-shrink artefakti** olacak (yüksek sl_pct_min eşiği →
trade subset shrinks → mean_R görünür artar ama net stack getirisi düşer ya da
sabit kalır). Yani giriş zaten tavanda; sl_pct_min ekseninde **gerçek edge yok**.

**H0 yanlışsa:** En az 1 eşik (≠ 0.025) tüm 4 kriteri AYNI ANDA geçer VE
stack monthly return @ -23% DD'de baseline'ı **mutlak değer olarak ≥ +%2/ay** geçer
(yani mean_R artışı sample küçültmeden kaynaklı değil, gerçek getiriye çevriliyor).

## 3. Gerekçe (RAG referansları)
- **[Brooks 2012, deep_catalog ch. SR-failed-breakout]** — Stop yerleşimi seviye + 1
  tick; "stop yarış kuralları" stop'u test bar opposite end'e koymayı söyler. Bu, sl
  ekseninde optimumun mum-yapısı tarafından belirlendiğini ima eder, sl_pct_min flat
  parametre değil → katı sweep curve-fit riski.
- **[Brooks 2012, summary §reversal-bar-at-SR]** — Tek başına reversal-at-SR setup'ı
  ~%50-55, confluence ile yükselir. sl-only-sweep confluence'a dokunmaz → marjinal.
- **[Volume/Price Divergence summary]** — vol eşik sweep önerisi 0.60-0.90, 0.05 adım.
  Bu, **klasik discrete-grid sweep** örneği; bizim sweep buna benzer ama floor +
  düşük resolution → curve-fit yüzeyi yine de mevcut.
- **[Lopez de Prado, lopez_summary]** — CPCV + Deflated Sharpe + PBO < 0.2; tek
  IS/OOS split fakir, ama biz hesap ekonomisi için tek split + per-symbol-out
  sanity ile gidiyoruz; **MTC zorunlu** (8 trial → BH-FDR).
- **[SMC/ICT, smc_ict_summary]** — Tek setup full rigor: 5+ yıl, OOS 30%, walk-fwd,
  Deflated Sharpe, CPCV. Bizim setup bunun **çıplak versiyonu** — bu yüzden gate'leri
  fazla sıkı tutuyoruz.

## 4. v12 ile farkı (overlap kontrolü)
- v12: **3 kaldıraç** birlikte sweep (confluence + orthogonal filters + WIDESTOP).
  Sonuç: tek filter htf_1d_aligned survived, WIDESTOP-up sample-shrink, confluence
  hardcoded dead. **Sweep grid'i kabaydı (3 değer 0.025/0.030/0.035).**
- Bu hipotez: **TEK eksen** sl_pct_min, **8 değerli daha ince grid** (0.020 dahil!).
- Risk artışı: ince grid + tek eksen = optimumu cımbızlama yüzeyi büyür → curve-fit
  ihtimali ARTAR. Bu yüzden gate'ler v12'den DAHA sıkı.

## 5. Test edilen kaldıraçlar
**TEK eksen, 8 değer:**
sl_pct_min ∈ {0.020, 0.022, 0.025 (baseline), 0.028, 0.030, 0.033, 0.035, 0.040}

> **Not — 0.020/0.022 dahil edildi çünkü:** auto-memory `widestop-threshold-validated`
> "düşürmek BLOCKED, fee-erozyon kalkanı" diyor. Bu pre-registration'ın bir amacı bu
> blokun **veriyle hâlâ ayakta** olduğunu kanıtlamak; eğer 0.020 OOS net Sharpe'ı
> baseline'ı + fee-erozyon hesabı tutuyorsa, blok güncellenir. Ama prior **çok kuvvetli
> NEGATİF**: 0.020 → fee_R baseline'ın ~1.4x'ine zıplar → net negatif beklenir.

Diğer her şey sabit (champion config):
- VSA = vsa_climax_test
- Risk = 0.005, max_concurrent = 16
- Fee = 55bps round-trip
- Exit = TP1 partial + 4% trail from TP1 (a8f7253 baseline)
- Pool = 15 likit perp (champion universe)

## 6. Dependent variables (ölçülecek)
- `mean_R_oos_net` (per-trade R, fees+slip dahil) — primary
- `day_sharpe_oos_net` — primary
- `n_oos_trades` (sample preservation control)
- `is_oos_meanR_ratio` (overfit detector — < 1.5 olmalı)
- `shuffle_p_gross` (direction-shuffle null) — < 0.05 olmalı
- `bh_fdr_pass` (n=8 trial Benjamini-Hochberg) — pass olmalı
- `stack_monthly_return_at_minus23_dd` — secondary, gerçek getiri çevirimi
- `per_year_sign_consistency` (2021..2026 her yıl pozitif mean_R) — overfit detector
- `fee_R_per_trade` (sl_pct_min düşerken fee erozyon kanıtı) — diagnostic

## 7. Independent variable
sl_pct_min (8 değer, yukarıda)

## 8. Walk-forward + MTC protokol
- **IS** = [2021-05-01, 2024-01-01), **OOS** = [2024-01-01, 2026-06-03)
- Her 8 eşik için: IS+OOS metrikleri ayrı hesapla
- **Multiple testing correction:** n=8 trial üzerinden Benjamini-Hochberg, alpha=0.05
- **Direction-shuffle null:** her eşik için 200 seed shuffle, p_gross hesabı
- **Per-symbol-out CV:** her sembolü tek tek dışarıda bırak, mean_R sapması < %25
- **Per-year sign consistency:** 2021..2026 6 yıl, en az 5 pozitif olmalı (v12 dersi)

## 9. Beklenen p-value (calibration)
- Naive (düzeltmesiz): rastgele şansla 8 trial'da en iyi p ≈ 0.05/8 ≈ 0.006 gerekli
- BH-FDR alpha=0.05: en iyi raw-p < 0.006 olmazsa **tek eşik bile geçemez**
- **Beklentim:** Hiçbir eşik BH-FDR'ı geçmeyecek (n=8 küçük ama IS bias yüksek)

## 10. Stop criteria (a priori — ihlal = REDDET)
Bu hipotez aşağıdakilerden HERHANGİ BİRİ ihlal edilirse RED:

| # | Kriter | Eşik | Yakaladığı tuzak |
|---|---|---|---|
| S1 | OOS delta mean_R ≤ 0 (baseline üzerinde) | en iyi eşik | gerçek edge yok |
| S2 | IS/OOS mean_R ratio > 1.5 | herhangi eşik | overfit / IS-bias |
| S3 | BH-FDR alpha=0.05 fail (en iyi raw-p > 0.006) | tüm grid | multiple testing inflation |
| S4 | n_oos_trades < 150 | en iyi eşik | sample-shrink artefakt |
| S5 | shuffle p_gross > 0.05 | en iyi eşik | yön bilgisi sıfır |
| S6 | per-year sign positive < 5/6 | en iyi eşik | regime-luck |
| S7 | stack monthly ret @ -23% DD lift < +%2/ay | en iyi eşik | mean_R artışı para değil |
| S8 | sl_pct_min ≤ 0.022'de net day-Sharpe negatife dönerse | 0.020/0.022 | fee-erozyon kalkanı KANITLANDI; blok ayakta kalır (bu CEZA değil, EDGE — ayrı doc'ta raporla) |

## 11. Curve-fit kırmızı bayrakları (peşinen tanımlıyorum)
v12'den miras + ek:
- **Best eşik grid sınırında (0.020 veya 0.040)** → daha geniş aralık gerekir, bu run RED
- **Best eşik tek başına optimal, komşular çok kötü** → spike = noise, RED
- **n_oos_trades best eşikte baseline'ın < %40'ı** → sample-shrink, RED
- **per-year break-down** → bir yıl P&L'in > %50'sini taşıyorsa, RED (LUNA-türü tek-event capture)

## 12. Önceden taahhüt (Tetlock adversarial — calibrate yourself)
**Bahsim (a priori, kod yazmadan):**
- **%70 olasılık:** HİÇBİR eşik BH-FDR + IS/OOS ratio + n_oos kombinasyonunu geçmez.
  Sweep, sample-shrink artefaktının ince granülerli versiyonu olarak çürütülür.
  v12 sonucunun teyidi.
- **%20 olasılık:** 0.030 veya 0.033 BH-FDR'ı geçer ama stack monthly return @ -23%
  DD lift'i < +%2/ay. "İstatistiksel anlamlı, ekonomik anlamsız." RED ama bilgi.
- **%8 olasılık:** Bir eşik gerçekten tüm gate'leri geçer (sample preservation dahil)
  → Lab tournament adayı, ama hâlâ adversary_engineer kill-probe gerekir.
- **%2 olasılık:** 0.020/0.022 net Sharpe baseline'ı geçer → auto-memory
  `widestop-threshold-validated` güncellenir (CRITICAL — fee-erozyon paradigması
  çöker; bu çok agresif bir prior değişimi). Mevcut canlı çalışan v13 testnet
  sonuçları (RESUME_2026-06-03.md) bu durumda yeniden değerlendirilmeli.

## 13. What would change my mind (Tetlock 5. madde)
H0'i RED etmem için:
1. En az 1 eşik 8 stop kriterinin TAMAMINI geçmeli (sırf BH-FDR yeterli değil)
2. Per-symbol-out CV'de min mean_R, baseline'ın min mean_R'sini geçmeli
3. Stress dönemlerinde (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen) yıkıcı drawdown yok
4. fee_R diagnostic'i mantıklı (sl_pct_min düşerken fee_R DOĞRUSAL artıyor — yoksa
   exit modeli bozuk)

## 14. Dependencies / blocks
- **depends_on:** v12 (HYP-2026-06-02-v12-entry-quality-vsa-widestop) — bu hipotez
  v12'nin sl_pct_min eksenini daha ince granülerle revize ediyor
- **blocks:** Hiçbir Lab tournament adayı (eğer sweep RED ise hiçbir şey değişmez;
  PASS ise yeni champion config taslağı yazılır AMA insan onayı şart)

## 15. Reproducibility
- git=a8f72539
- data_hash: market.duckdb mtime + symbol manifest
- config base: configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml
- Walk-fwd seed: 42 (sabit)
- Shuffle seeds: range(200)

## 16. SLA
- Pre-registered: 2026-06-03T12:00:00Z
- Backtest pipeline runs: 2026-06-04 (cron / orchestrator)
- Tahmini compute: ~25-40 dk (8 config × shuffle × per-sym-out)
- Reviewer SLA: 24h (Risk Officer 6h)
