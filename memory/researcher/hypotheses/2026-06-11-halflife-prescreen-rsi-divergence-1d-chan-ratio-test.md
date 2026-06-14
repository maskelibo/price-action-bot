---
doc_id: researcher-20260611T120000-halflife-prescreen-rsi-divergence-1d-chan-ratio-test
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T12:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, halflife, rsi_divergence, chan, kaufman, 1d, crypto_perp, falsification_test, low_corr_to_vsa]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-11-halflife-prescreen-rsi-divergence-1d-chan-ratio-test

## 0. Bu hipotez NEDEN farklı (öncekilerden ayrım)

- `2026-06-09-halflife-gated-rsi-divergence-sr-confluence-crypto-4h.md` → 4H + S/R confluence; bu **1D**, **S/R gate'i YOK** (mekanizmayı izole etmek için).
- `2026-06-08-halflife-gated-bollinger-fade-1d.md` → entry sinyali Bollinger, bu RSI-div.
- **Yeni köşe (falsification asıl amaç)**: Chan'ın "Sharpe ∝ 1/√half_life" iddiasını **önceden sayısal tahminle test ediyoruz** (yön yoksa kalıbı öldür).

## 1. Pre-Registration

### 1.1 İddia (ölçülebilir, tek cümle, sayısal tahmin dahil)

> **2023-01-01 → 2026-05-31 dilimi (3+ yıl), USDT-perpetual likit evren (N≥40 sembol, delisting dahil), 1D timeframe'de:**
>
> Aşağıdaki **dar** tanımlı RSI-divergence kuralı tek başına koşulduğunda:
> - (a) RSI(14) ile fiyat arasında **bullish divergence**: fiyat son **20** barda lower-low, RSI aynı pencerede higher-low (mirror için bearish: fiyat HH, RSI LH).
> - (b) Divergence pivot bar'dan **≤ 3 bar** sonra **confirmation candle**: bullish için close > son 3 bar high'ının orta noktası (mirror bear için tersi). 3 bar geçerse setup invalidate.
> - (c) Entry confirmation bar'ın close'unda karar, **bir sonraki bar'ın open'ında** market.
> - (d) SL = divergence pivot low/high'ının **0.5 ATR(14) ötesi**.
> - (e) TP = **2R sabit**.
> - (f) Risk %1/trade sabit-fraksiyon, kaldıraç ≤ 3x, fee 7.5 bps taker + slip 5 bps.
>
> Bu temel kural ile **iki paralel backtest** yapılır:
>
> **Branch A (filtresiz):** Tüm semboller, her zaman.
> **Branch B (half-life pre-screened):** Bir günde, sadece o sembolün **son 60 günlük close** üzerinde hesaplanan Ornstein-Uhlenbeck half-life'ı **≤ 7 trading day** olan semboller trade edilebilir. Half-life her bar yeniden hesaplanır (causal, NO lookahead).
>
> **Chan'ın teorik tahmini**: Sharpe ∝ 1/√half_life. Tipik filtresiz evren ortalama half-life'ı ≈ 25-30 gün varsayımı altında (kripto perp literatüründe gözlemsel), beklenen oran:
>
> **Sharpe_B / Sharpe_A ∈ [1.8, 2.4]** (yani √(30/7) ≈ 2.07 ± %15 toleransla).
>
> Aynı zamanda **mutlak** gate'ler:
>
> | Metrik | Branch A | Branch B |
> |---|---|---|
> | Net annualized return | ≥ 4% | ≥ 10% |
> | Sharpe (annualized) | ≥ 0.3 | ≥ 0.7 |
> | MaxDD | ≤ 25% | ≤ 18% |
> | Win rate | 30-50% | 30-55% |
> | Profit factor | ≥ 1.1 | ≥ 1.25 |
> | Trade count | ≥ 200 | ≥ 80 |
> | Corr vs vsa_climax_test_v1 | ≤ 0.30 | ≤ 0.30 |

### 1.2 Null Hipotez (H0) — üç ayrı falsifier

1. **H0a (yönsel):** Sharpe_B ≤ Sharpe_A. Yani half-life pre-screen HİÇBİR fark yaratmaz veya tersine çevirir.
2. **H0b (büyüklük):** Sharpe_B / Sharpe_A < 1.5 veya > 3.0. Yani Chan'ın √-yasası KIRILIR; ya effect daha zayıf (başka şey çalışıyor, half-life epifenomen) ya da daha güçlü (curve-fit / confound).
3. **H0c (mutlak):** Branch B gate'lerinin herhangi biri kırılır.

**Bu üçten herhangi biri tutarsa hipotez RED.**

### 1.3 Gerekçe — RAG Referansları

- **[Chan — half-life ve Sharpe ilişkisi]** (RAG #5): "Mean-reversion stratejisinin Sharpe'ı half-life'ın square root'una ters orantılıdır." → **doğrudan tahmin formülü**.
- **[Kaufman — RSI divergence]** (RAG #6): "Bullish divergence + confirmation candle → long, stop divergence low altı, target 2-3R. Failure: RSI strong trend'de saatlerce/günlerce overbought kalır." → **divergence YAPI tanımı + uyarı**.
- **[Lopez de Prado — DSR]** (RAG #9): "DSR ∈ [0.6, 0.95] kabul edilebilir." → Bonferroni + DSR gate.
- **[Grimes — over-leverage pitfall]** (RAG #4): "İyi sistemleri öldüren #1 sebep." → %1/trade, 3x cap zorunlu.
- **[Lopez — w_i = m_i / Σ|m_j|]** (RAG #7): Bu hipotez tek başına kullanılırsa portföye **düşük-korrelasyon** kanıtlanmalı (vsa_climax_test_v1 ile |ρ| ≤ 0.30).

### 1.4 Curve-Fit / Overfit Şüphesi (zorunlu, AÇIK)

**Tetik şüphesi nokta nokta:**

1. **Half-life eşiği = 7 keyfi mi?** Evet, kısmen — Chan literatürü "5-7 gün low, 30 gün high" der. Sweep YASAK; tek değer (7) test edilecek. Daha sonra robustness için **{5, 7, 10}** denenecek; tutarsızlık (CV>%30) → hipotez şüpheli.
2. **RSI lookback 14 ve divergence window 20 ne kadar dayanıklı?** 1D piyasada standart; sweep yapılmayacak (curve-fit önleme). Sadece robustness'ta **{10, 14, 21}** denenecek, ana karar `14` üzerinden alınacak.
3. **Beklenen Sharpe oranı bandı [1.8, 2.4]** — bu sıkı bir bant. Bandın dışına çıkma kontra-kanıt; içine girme tek başına kanıt değil (DSR ve Bonferroni ayrıca gerekir).
4. **Branch A başarısızsa**: Branch B "iyi" gözükse bile, **half-life pre-screen'in yarattığı veri-azlığı + rastgele seçim** edge gibi görünebilir. Bu sebeple Branch B'nin trade sayısı ≥ 80 ve Branch A'nın da ≥ 200 zorunlu.
5. **Half-life hesabı her bar yeniden** — lookahead için kritik test (causality testi 1.8'de).

**Auto-reject kırmızı bayraklar:**

- Sharpe oranı [1.8, 2.4] dışına düşerse (H0b) → red, çünkü Chan'ın yasası kırılmış demek mekanizmamızı anlamıyoruz.
- Branch B'nin OOS Sharpe'ı IS Sharpe'ından > %35 düşükse → overfit.
- Best half-life eşiği (5/7/10) sınırda kalır ve trend dışarı doğruysa → red.
- Tek bir periyot toplam P&L'in > %40'ını üretirse → fragile.
- Bonferroni-adjusted p > 0.05 / 6 (Branch A/B × 3 robustness window, ≈ 0.0083).

### 1.5 Dependent Variables

| Metrik | Branch A hedef | Branch B hedef | Reddet eşiği |
|---|---|---|---|
| Net annualized return | ≥ 4% | ≥ 10% | A<2% veya B<5% |
| Sharpe (annualized) | ≥ 0.3 | ≥ 0.7 | A<0.15 veya B<0.4 |
| **Sharpe_B / Sharpe_A** | **∈ [1.8, 2.4]** | — | dışı → kalıp red |
| MaxDD (equity) | ≤ 25% | ≤ 18% | > 35% |
| Win rate | 30-50% | 30-55% | dışı |
| Profit factor | ≥ 1.1 | ≥ 1.25 | < 1.0 |
| Trade count | ≥ 200 | ≥ 80 | < (100, 50) |
| Corr vs vsa_climax_test_v1 (B) | — | ≤ 0.30 | > 0.50 |
| DSR (Lopez) | ≥ 0.55 | ≥ 0.65 | < 0.5 |
| Bonferroni-adj p | ≤ 0.0083 | ≤ 0.0083 | > 0.0083 |

### 1.6 Independent Variables (sweep DAR)

- **Half-life eşiği:** **7** (ana karar). Robustness: {5, 7, 10}.
- **RSI lookback:** **14** (ana karar, sweep yok). Robustness: {10, 14, 21}.
- **Divergence window:** **20** bar (sabit).
- **Confirmation pencere:** **3** bar (sabit).
- **SL ATR ötesi:** **0.5** (sabit, sweep YASAK).
- **TP R:** **2.0** (sabit, sweep YASAK).
- (Sabit) Risk %1/trade, fee 7.5 bps, slip 5 bps, max leverage 3x.

**Toplam test sayısı:** 1 ana karar × 2 branch + 3 robustness × 2 branch = 8 test. Bonferroni cutoff = 0.05 / 8 = **6.25e-3**.

### 1.7 Beklenen P-Value

- **Naive p (Branch B vs shuffle baseline)**: 0.001 - 0.02 beklenen.
- **Bonferroni cutoff**: 6.25e-3 — eşikte. **Geçemeyebilir** (yani başarısız olmaya hazırım).
- **DSR**: ≥ 0.65 hedef.
- **Açıklama**: Beklentim mütevazı pozitif — Branch B'nin ölçülebilir bir Sharpe avantajı olacak ama oran [1.8, 2.4] bandında **olmama olasılığı yüksek**. En olası başarısızlık: oran 1.2-1.5 (yani half-life etkisi var ama Chan √-yasasından daha zayıf — çünkü kripto'da rejim değişikliği half-life'ı dinamik kılıyor).

### 1.8 Stop Criteria (önceden taahhüt)

1. **Lookahead testi başarısız** (`detector(df.iloc[:t+1])[t] != detector(df)[t]` her t için) → derhal red, kod debug.
2. **Half-life hesabında causality kırılırsa** (örn. her bar yeniden hesaplama yerine batch hesaplama kullanılmışsa) → derhal red.
3. **Sharpe_B / Sharpe_A ∉ [1.8, 2.4]** → red (H0b).
4. **Branch B Sharpe < 0.4** → red (H0c — mutlak gate).
5. **Branch A pozitif değilse VE Branch B pozitif** → ŞÜPHELİ; özellikle Branch A trade count > 5x Branch B ise muhtemelen Branch B'nin "iyi"liği survivorship + selection bias. Reddedilmek üzere flag.
6. **Robustness eşik sweepi (5/7/10)** OOS Sharpe CV > %30 → red.
7. **3 yıl bütününde Branch B trade sayısı < 80** → setup çok nadir, edge istatistiksel anlamsız.
8. **Corr(Branch B, vsa_climax_test_v1) > 0.5** → champion replikası, red.

### 1.9 Robustness Suite Plan

- **Walk-forward**: 3y/6m, step 3m (12 dilim). Her dilimde Branch A/B ayrı.
- **Param perturbation**: ana karar parametrelerine ±%10, 50 seed (half-life 7 → 6.3/7.7; RSI 14 → 13/15); ortalama Sharpe kayıp < %25.
- **Symbol-out CV**: tek sembol dışarıda → Branch B ortalama OOS Sharpe değişimi < %20.
- **Regime split**: bull (2023, 2024H1), bear (2024H2 düzeltme), range (2023 yaz) — en az 2 rejimde Branch B pozitif.
- **Stress**: 2024-03 BTC ATH (RSI overbought saatlerce kalır — Kaufman'ın failure mode'u burada test edilir), 2024-08 Yen carry. Branch B bu dönemlerde yıkıcı kayıp vermemeli.
- **Shuffle baseline**: Returns shuffled, 1000 boot → p < 0.05 zorunlu.
- **Bonferroni**: cutoff 6.25e-3 (n=8).
- **DSR (Lopez)**: trial sayısı 8, mean Sharpe ve skewness/kurtosis dahil edilmiş hesap.

### 1.10 Reproducibility

- git_hash: <commit sonrası doldurulacak>
- config_hash: <oluşacak>
- data_hash: ingest manifest 2026-06-11

## 2. Çalıştırma Planı

1. **Detector implement** (vectorized, pure-function):
   - `src/price_action/signals/rsi_divergence_v1.py` — bullish/bearish divergence detector.
   - `src/price_action/signals/halflife_ou.py` — Ornstein-Uhlenbeck half-life, rolling 60-day, causal (NaN ilk 60 bar).
2. **Causality testleri** (CI gate):
   - `tests/signals/test_rsi_divergence_lookahead.py`
   - `tests/signals/test_halflife_ou_lookahead.py`
3. **Backtest config**: `configs/strategies/halflife_rsi_divergence_v1.yaml` (taslak — deploy YOK).
4. **Backtest çalıştırma**:
   - Branch A: filtersiz; Branch B: half_life ≤ 7 gate.
   - IS: 2023-01 → 2025-05 (29 ay). OOS: 2025-06 → 2026-05 (12 ay).
5. **Correlation hesabı**: champion vsa_climax_test_v1 günlük PnL series'i ile Pearson, sembol-day overlap.
6. **Robustness suite** tam koşar.
7. **DSR + Bonferroni** raporu.
8. **Karar dosyası**: `reports/research/halflife_rsi_divergence_chan_ratio_test-2026-06-11.html`.

## 3. Risk Officer Critique İstenen Noktalar

- Half-life pre-screen, evrenden günlük olarak %75'ini eler → açık pozisyon yoğunlaşır. Concentration limit (`max_per_category_pct`) ile çakışır mı?
- RSI divergence + 2R sabit TP — strong trend'de Kaufman'ın "RSI can stay overbought longer than you can stay solvent" uyarısı pratikte SL'ye yapışmamızı sağlar mı? Time-stop (10 bar) zorunlu mu olmalı?
- 0.5 ATR SL — 1D timeframe'de bu çok dar olabilir; günlük noise > 0.5 ATR sık. SL hit oranı projeksiyonu nedir?

## 4. Lab Scientist Review İstenen Noktalar

- Tournament için challenger paneli: `bos_donchian_orthogonal`, `marubozu_continuation`, `engulfing_continuation_v3`. **vsa_climax_test_v1 YASAK** (champion + low-corr şartı).
- DSR'yi 8 trial üzerinden mi yoksa robustness suite kombinasyonu üzerinden mi (12 dilim × 8 = 96)? Cevaba göre Bonferroni cutoff değişir.
- Branch A/B karşılaştırmasında paired-test mi (aynı tarihler) yoksa independent mi? Önerim: paired Welch's t-test günlük returns üzerinde.

## 5. Adversary Engineer Kill-Probe İstenen Noktalar

- **Stress 2024-03 BTC ATH**: RSI 14 günlerce 70+ → bearish divergence sinyali bombardımanı, hepsi SL hit; Branch A'da bu dilim "Kaufman failure mode" net görünmeli, Branch B'de half-life filtresi BTC'yi eler mi? Etmeyebilir (BTC half-life'ı bu dönemde düşük olabilir momentum-mean-reversion karışımı sebebiyle).
- **Survivorship**: 2023 başında listede olup 2025'te delist olan sembollerde (LUNA-ish) Branch B davranışı? Half-life hesabı 60 bar veri ister; delist öncesi son bar'larda likidite çukuru + half-life çöküşü Branch B'yi yanlış pozisyona itebilir.
- **Slippage**: Half-life ≤ 7 gün olan semboller genellikle düşük market-cap → 5 bps slip iyimser. 15 bps slip ile Branch B Sharpe nasıl etkilenir? **20 bps stress slip** koş, hâlâ Sharpe ≥ 0.5 olmalı.
- **Funding**: Mean-reverting kripto perp'lerde funding rate volatilitesi yüksek; Branch B'nin gerçek net edge'i (funding maliyeti dahil) raporlanan'dan ne kadar düşük?

## 6. Beklenti (dürüst tahmin)

**Ben (Researcher) bu hipotezin %60-70 olasılıkla RED olmasını bekliyorum.** Sebebi:

1. Sharpe oran bandı [1.8, 2.4] **sıkı bir falsifier** — kripto'da half-life dinamik (rejim değiştikçe), Chan'ın varsayımı durağan OU; oran muhtemelen 1.2-1.6 aralığında düşecek → H0b tutar.
2. Branch B trade sayısı 80 eşiğine yetişmeyebilir (yıllık ~25 trade gerekir, 3 yıl × 1D × N≥10 aktif sembol filtreden geçen × düşük frekanslı divergence sinyali).
3. Bonferroni 6.25e-3 sıkı.

**Eğer geçerse**, iterate budget:
- v2: half-life threshold {5, 7, 10} en iyisi üzerinden re-test (robust mu, curve-fit mi).
- v3: Branch B'ye S/R confluence ekle (mevcut 4h hipotezi ile çift-test).
- v4: TP yapısı R-multiple yerine ATR-bazlı (1D noise'a daha uygun).

**Strong opinions, loosely held.** Hipotez yazıldı ki sayı çürütsün.

## 7. Pre-registration İmza

- Tarih: 2026-06-11 12:00 UTC.
- Kod yazılmadı. Backtest koşulmadı. Hash dondurulacak: `git add memory/researcher/hypotheses/2026-06-11-halflife-prescreen-rsi-divergence-1d-chan-ratio-test.md && git commit -m "preregister HYP-2026-06-11-halflife-prescreen-rsi-divergence-1d"`.
- Bu hipotez **hiçbir veri/backtest bakılmadan** yazılmıştır — Chan'ın √-yasası ve Kaufman'ın divergence yapısından deduktif.
