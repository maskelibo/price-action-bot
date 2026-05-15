# SEC22 Researcher Learning — Mean-Reversion Pre-Build Sprint (2026-05-14)

## Sprint Context

Engineering SEC21 paralel slot-allocation; Researcher SEC22 paralel mean-rev class pre-build. CEO mandate: yeni-strateji araştırması ŞU AN düşük ROI (slot doymuş), AMA fix sonrası mean-rev yedek aday yok → "engineering bittiğinde HAZIR" olacak class strategy üret.

## Sonuç Özeti

- **1 standalone PASS-MARGINAL** (rsi2_extreme_fade, parametre selection ile)
- **2 RED** (three_push_wedge_fade n bottleneck, bb_extreme_reversal crypto-mechanic ters)
- **HTF retest TÜMÜ RED** (10 config, pattern crypto 1d için yapısal ölü kalıcı archive)

Detay: `reports/researcher/2026-05-14_sec22_summary.md`.

## Öğrenimler

### 1. Selection Bias Paradigmasi — "Borderline PASS with grid"

**Durum:** rsi2_extreme_fade default config gate-borderline (mR=+0.095, p=0.040). 27 config grid sweep'te 5 robust config PASS bulundu (rsi=5 thresh). En iyi: n=356 mR+0.144.

**Risk:** Bu klasik "selection bias / p-hacking lite":
- 27 hipotez test → Bonferroni α=0.05/27=0.0019 → none pass strict.
- FDR-BH q=0.10 → 5 config marginally meaningful ama family p<0.05 zayıf güvence.
- En iyi config production'a alınırsa OOS (out-of-sample) performansı çok daha düşük olabilir.

**Lesson:** Grid sweep + tek "best config" seçimi yeterli değil. Sonraki adımda **temporal hold-out (2024-2025 OOS)** zorunlu. Pre-registration disipliniyle "BEFORE seeing data" en iyi config'i sabitlemek imkansız (default'u zaten test ettik); ensemble retest'te **walk-forward kararı** kullan, in-sample tuning sonrası OOS hold-out.

### 2. Artifact Gate False Positive

**Durum:** rsi2_extreme_fade default max_R=10.53 → gate threshold (max_R<10) tarafından FAIL flag'lendi. Ama forensik (top 5 R trades inspection) hiçbirinin dataset-end clip artifact olmadığını gösterdi: BTC short 2022-07 hold=42d gerçek bear regime edge.

**Lesson:** max_R<10 gate threshold "crypto bear regime gerçek 8-15R trade'leri" yanlış flagler. Gate'i softening önerisi (max_R<15 + ek median_R artifact audit) sonraki sprintte. **Gate threshold parametreleri kendi başına subject to research** — blindly applied gate'ler false positive/negative üretebilir.

### 3. Rare Pattern + Standalone n Bottleneck

**Durum:** three_push_wedge_fade gerçek edge gösteriyor (45 sweep config 30+ pozitif mR, peak +0.66), AMA n hiç 150 gate'ini aşamıyor (max n=77). 5y × 11 sym × 1d pattern çok rare.

**Lesson:** Compound filtre (3 swing-high + marjinal_gain range + wedge convergence + body + wick) trade'i çok seçici yapıyor. Pattern-pure detection için ya:
1. Universe expansion (20+ sym SEC13.3 sonucu RED ama slot fix sonrası yeniden değerlendirilebilir)
2. Alternative timeframe (4h SEC6 RED ama bu pattern multi-bar yapısal, 4h'de daha fazla pivot bulabilir)
3. Filter relax (false-positive trade-off)

Standalone n<150 gate **strikt**; rare pattern'ler için **alternative power calculation** (effect size + bootstrap CI) gerekebilir.

### 4. Crypto vs. Stocks/FX Mean-Rev Divergence

**Durum:** Bollinger 2.5σ Extreme Reversal stocks/FX'te dokumante edilmiş classical mean-rev edge ama crypto'da TERS yön: mR=-0.288, 0/11 sym pozitif. Hold median 1d (SL hızlı çarpıyor).

**Yapısal sebep:** Crypto yüksek-vol persistence — +2.5σ excursion = momentum başlangıcı, NOT exhaustion. Fade trade'i trend'e ters durup kaybediyor.

**Lesson:** "Stocks edge'i crypto'da işler mi" sorusu **CASE-BY-CASE** validation gerektirir. Naive transfer assumption riskli. **Genel kural:** Yüksek-vol asset class'larda **persistence > mean-rev** dominant.

### 5. Pattern Originally Designed for Different Universe

**Durum:** HTF (High-Tight Flag) — Bulkowski'nin original çalışması US small-cap stock equities. SEC19 RED, SEC22 retest 10/10 config RED.

**Lesson:** Pattern originally designed for X universe başka universe'e (crypto 1d) transfer edilmek üzere geliştirilirken **adaptation gerekli**. Crypto'da pole + flag dynamics farklı (24/7 trading, no overnight gaps, leverage-driven volatility). Sadece parametre tuning yetmez; tetik mekaniği kendisi geçersiz olabilir. **HTF kalıcı archive.**

### 6. Vectorized vs. Subjective Pattern Detection Gap

**Durum:** Brooks 3-push wedge — pattern subjective, trader klasik chart'ta "gözüyle" görür. Vektörize implement (5-bar fractal + marjinal_gain + body+wick) original setup'ların belki %30-50'sini yakalar.

**Lesson:** Vektörize implement original "trader gözünden gördüğü" pattern'in alt-setine erişiyor. False positives sınırlı (n düşük, edge pozitif). Pattern-pure detection için sonraki adım: **ML feature engineering** (CNN üzerinde candlestick sequence, embedding-based pattern matching) veya **manual labeling + supervised classifier**. Bu sprint scope dışı ama backlog.

## Sonraki Sprint için Hatırlatma

1. **rsi2_extreme_fade ensemble retest (yüksek ROI):** Engineering SEC21 slot fix sonrası ANAHTAR sprint:
   - Default + rsi=5 best config → ensemble walkforward 3y rolling 13 pencere.
   - **2024-2025 OOS hold-out zorunlu** (selection bias guard).
   - Class slot allocation policy: rsi2 mean-rev slot'a aday, eğer slot 4-6'ya çıkarsa.
   - Production gate: delta_yıllık ≥ +%2pp veya delta_r-adj ≥ +0.05.

2. **three_push backlog:** Universe expansion sonrası retest (slot fix policy değişikliği veya 20+ sym kabul).

3. **Mean-rev class 4. iteration:** Daha "egzotik" candidate'lar (Andrew's Pitchfork, COT-derived, stat-arb spread) sonraki sprint backlog.

4. **Crypto mean-rev vs trend-cont regime switch (kavram):** BB extreme crypto'da continuation → bu insight bir trend-cont strategy'e dönüştürülebilir mi? `bb_extreme_continuation` (close outside band → trade WITH excursion) sonraki sprint analiz konusu, ama bu trend-cont class olur, mean-rev DEĞİL.

## Kayıtlı Hipotezler

- `memory/researcher/hypotheses/2026-05-14-rsi2-extreme-fade.md` — ⚠️ PASS-MARGINAL
- `memory/researcher/hypotheses/2026-05-14-three-push-wedge-fade.md` — ❌ RED-CONDITIONAL
- `memory/researcher/hypotheses/2026-05-14-bb-extreme-reversal.md` — ❌ HARD RED
