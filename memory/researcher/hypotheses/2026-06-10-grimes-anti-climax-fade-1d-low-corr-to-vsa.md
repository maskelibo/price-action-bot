---
doc_id: researcher-20260610T000000-grimes-anti-climax-fade-1d
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-10T00:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, grimes, anti, climax_fade, counter_trend, 1d, crypto_perp, low_corr_to_vsa]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-10-grimes-anti-climax-fade-1d

## 1. Pre-Registration

### 1.1 İddia (ölçülebilir, tek cümle)

> **2023-01-01 → 2026-05-31 dilimi (3+ yıl), USDT-perpetual likit evren (N≥40 sembol, delisting dahil), 1D timeframe'de:**
>
> Aşağıdaki **DAR** tanımlı koşullar gerçekleştiğinde:
> - (a) günlük bar gövdesi |close - open| ≥ **2.0 × ATR(14)** (climax bar),
> - (b) bar üst/alt iğnesi gövdenin **%30'unu** aşmıyor (climax, exhaustion değil),
> - (c) climax bar yönü, son **10 günlük** EMA20 eğimine PARALEL (yani trendi katlayan extension; counter-trend'e şart),
> - (d) climax bar volatilite z-score (ATR / ATR_rolling_100) **> 1.5** (rejim ekstrem),
> - (e) climax bar **vsa_climax_test_v1 detektörü tarafından TETİKLENMEMİŞ** (champion ile cross-strategy edge testi → düşük korelasyon zorunlu);
>
> ve karar bar'ın close'unda alınıp giriş bir sonraki bar'ın open'ında **counter-trend** (bullish climax → SHORT, bearish climax → LONG) olarak yapılıp, SL climax bar uç noktasının 0.5 ATR ötesi, TP **2R** sabit, fee 7.5 bps taker + slip 5 bps modellenirken:
>
> 1. Net annualized return ≥ **+8%** (compounding değil, sabit-fraksiyon %1/trade)
> 2. Sharpe (annualized, daily) ≥ **0.6**
> 3. MaxDD (equity bazlı) ≤ **18%**
> 4. Win rate ∈ **[35%, 50%]** (Grimes claim aralığında — dışına çıkması overfit/lookahead sinyali)
> 5. Profit factor ≥ **1.15**
> 6. Trade sayısı ≥ **150** (istatistiksel anlam)
> 7. **Pearson korelasyon (günlük PnL series) vs vsa_climax_test_v1 ≤ |0.30|** (düşük-korelasyon zorunluluğu)

### 1.2 Null Hipotez (H0)

> Climax-fade kuralı, returns-shuffle baseline'a göre Sharpe farkı yaratmaz (p > 0.05). Net annualized return ≤ 0 veya korelasyon |ρ| > 0.30 → strateji reddedilir.

### 1.3 Gerekçe — RAG Referansları

- **[Grimes 2012, "The Art and Science of Technical Analysis", ch. "Anti" setup]** (RAG #3): "Trend yönünde aşırı uzayan hareket sonrası ilk küçük pullback başlangıcında KARŞI yönde küçük bir kontre pozisyon. Lokasyon: Bollinger 2σ dışı, climax bar, ATR'nin 2 katından büyük günlük hareket. WR ~%40-45, R 2-3R, expected value hafifçe pozitif." — **DOĞRUDAN bu hipotezin formal-test versiyonu**.
- **[Grimes — pitfalls]** (RAG #4): "Over-leverage iyi sistemleri öldüren #1 sebep." → Position sizing %1/trade sabit fraksiyon, kaldıraç tavanı 3x (configs/risk.yaml kuralına uyum).
- **[Lopez de Prado — DSR]** (RAG #9): Çoklu hipotez testi sonrası DSR ≥ 0.6 gate'i; aşağıda Bonferroni + DSR uygulanır.
- **[Lopez de Prado — w_i = m_i / Σ|m_j|]** (RAG #7): Bu hipotez tek başına portföye eklenirse, korelasyon-bazlı w_i hesaplaması için Curator'a düşük-corr metriği kanıtlanmalı (KPI #7).

### 1.4 Curve-Fit / Overfit Şüphesi (zorunlu açıklama)

Bu hipotez 5 eşzamanlı koşula bağlı (a-e). Parametre uzayı:
- ATR çarpanı: **{1.5, 2.0, 2.5}** (3 nokta — geniş grid, ince-mesh YASAK)
- İğne tavanı: **{20%, 30%, 40%}** (3 nokta)
- EMA lookback: **{10, 20}** (2 nokta)
- vol_z eşiği: **{1.0, 1.5, 2.0}** (3 nokta)
- SL ATR ötesi: **{0.25, 0.5, 0.75}** (3 nokta)
- TP R: **{1.5, 2.0, 2.5}** (3 nokta)

**Toplam grid: 3×3×2×3×3×3 = 486 kombinasyon.** Optuna **YASAK** — sadece full-grid taranır, çünkü Bayesian tuner ile en iyiyi seçince DSR enflasyonu kaçınılmaz.

**Bonferroni düzeltmesi**: p-value cutoff 0.05/486 = **1.03e-4** gerekli. Bunu geçemeyen kombinasyon "anlamlı" sayılmaz.

**Curve-fit kırmızı bayrakları (auto-reject)**:
- Best params parametre uzayının sınırında (örn. ATR=2.5 ve iğne=40% birlikte) → grid'i genişlet ve tekrar dene; hala sınırdaysa hipotezi terk et.
- In-sample / OOS Sharpe farkı > %50.
- En iyi 5 kombinasyonun OOS Sharpe'ı arasında **CV > 0.5** (yani üst kombolar tutarsız) → kalıp gerçek değil, gürültü.
- Trade sayısı < 100 OOS dilimde → reddet.
- Tek bir periyot (örn. 2022-11 FTX shorts) toplam P&L'in > %40'ını veriyorsa → fragile.

### 1.5 Dependent Variables (önceden açıklanmış)

| Metrik | Hedef | Reddet eşiği |
|---|---|---|
| Net annualized return | ≥ 8% | < 4% |
| Sharpe (annualized) | ≥ 0.6 | < 0.3 |
| MaxDD (equity) | ≤ 18% | > 30% |
| Win rate | 35-50% | dışı |
| Profit factor | ≥ 1.15 | < 1.0 |
| Trade count | ≥ 150 | < 100 |
| Corr vs vsa_climax_test_v1 | ≤ 0.30 | > 0.50 |
| DSR (Lopez) | ≥ 0.6 | < 0.5 |
| Bonferroni-adjusted p | ≤ 1.03e-4 | > 1.03e-4 |

### 1.6 Independent Variables

- ATR(14) çarpanı (climax body threshold)
- Üst/alt iğne / gövde oranı tavanı
- EMA eğimi lookback
- vol_z eşiği
- SL ATR ötesi katsayısı
- TP R çarpanı
- (Sabit, sweep YOK) Risk %1/trade, fee 7.5 bps, slip 5 bps, max leverage 3x

### 1.7 Beklenen P-Value

- **Naive (single-test) p-value beklenen**: 0.001 - 0.01 (zayıf ila orta edge)
- **Bonferroni-adjusted** (n=486): cutoff 1.03e-4 → bu eşiği geçemeyecek olasılığım YÜKSEK. Hipotezi reddetmeye eğilimliyim.
- **DSR (Lopez)**: ≥ 0.6 gerekli; 0.5'in altında → "gerçek edge yok, rastlantı".

### 1.8 Stop Criteria (önceden taahhüt edilen iptal koşulları)

1. **In-sample Sharpe < 0.4** → araştırma terk edilir, walk-forward'a geçilmez.
2. **Trade sayısı < 100 (3 yıl, full grid'in en aktif kombinasyonu için)** → setup çok nadir, edge yok.
3. **Best params sınırda + grid genişletildikten sonra hâlâ sınırda** → terk edilir.
4. **Bonferroni sonrası HİÇBİR kombinasyon anlamlı değil** → terk edilir, "Grimes Anti kripto-1D'de işe yaramaz" arşivi açılır.
5. **vsa_climax_test_v1 ile günlük PnL korelasyonu > 0.50** → low-corr şartı düşer, hipotez "champion'ın replikası" olarak red.
6. **Lookahead testi** (causality: `detector(df.iloc[:t+1])[t] == detector(df)[t]`) **başarısız** → hipotez derhal red, kod debug.

### 1.9 Robustness Suite Plan

- Walk-forward: 3y/6m, step 3m (12 dilim)
- Param perturbation: best params ±%10, 50 seed → Sharpe kayıp < %25
- Symbol-out CV: tek sembol dışarıda → ortalama OOS Sharpe değişimi < %20
- Regime split: bull (2023, 2024H1), bear (2022 kısmı yok ama 2024H2 düzeltme), range — en az 2 rejimde pozitif
- Stress: 2022-11 (FTX), 2024-03 (BTC ATH), 2024-08 (Yen carry) — bu dönemlerde kombinasyon "Grimes Anti" mantığı gereği muhtemelen iyi olur (extension fade); fakat bunun şişme yaratmaması için stress hariç tutulup tekrar koşulur, hâlâ pozitif olmalı.
- Shuffle baseline: p < 0.05 zorunlu

### 1.10 Reproducibility

- git_hash: <henüz oluşmadı>
- config_hash: <oluşacak>
- data_hash: ingest manifest 2026-06-10

## 2. Çalıştırma Planı

1. Detector implement: `src/price_action/signals/grimes_anti_climax_fade.py` (vectorized, pure-function, lookahead testi).
2. Detector unit test: `tests/signals/test_grimes_anti_climax_fade.py` (causality + edge cases).
3. Backtest config türet: `configs/strategies/grimes_anti_climax_fade.yaml` (taslak, deploy YOK).
4. Backtest engine çağrısı: 486 grid full-sweep, 2 dilime böl (IS: 2023-01 → 2025-05, OOS: 2025-06 → 2026-05).
5. Cross-strategy correlation: champion vsa_climax_test_v1'in günlük PnL series'i ile Pearson hesapla, 100 sembol-day overlap.
6. Robustness suite tam koşar.
7. Karar dosyası: `reports/research/grimes_anti_climax_fade_1d-2026-06-10.html`.

## 3. Risk Officer Critique İstenen Noktalar

- 2× ATR climax + reverse leveraged short → margin safety ratio sınır altına düşer mi? 3× max leverage + %1 risk'le pratik mi?
- TP=2R sabit hedef, bear climax (panic capitulation) sonrası whip-saw'a girmeye eğilimlidir. Time-stop (örn. 5 bar) eklenmeli mi?

## 4. Lab Scientist Review İstenen Noktalar

- Tournament'ta hangi champion ile karşılaştırılacak? `vsa_climax_test_v1` (düşük-corr şartı yüzünden) **YASAK**. Onun yerine challenger paneli: `bos_donchian_orthogonal`, `halflife_gated_bollinger_fade`.
- DSR'yi 486 trial üzerinden mi yoksa robustness suite kombinasyonu üzerinden mi hesaplayacak?

## 5. Adversary Engineer Kill-Probe İstenen Noktalar

- LUNA 2022-05 dilimi backtest'te yok (2023-01 başlangıç). Ama benzer "panic" eventler (2024-08 Yen carry, FTX echos): bu dönemde Grimes Anti **karşı tarafa düşer** (panik fade'i devam ediyor → SHORT pozisyonun TP'sine kavuşmadan reverse) → kontra-örnek üret.
- Slipaj-yokluğunda Anti edge'i kalır mı? Climax bar sonrası likidite çukurunda 5 bps slip iyimser; 20 bps modeli ile test et.

## 6. Beklenti

**Ben (Researcher) öncelikle bu hipotezin RED olmasını bekliyorum** (Bonferroni 486 yüzünden). Strong opinions, loosely held — hipotez yazıldı ki veriyle çürütülebilsin. Eğer geçerse, **iterate budget**: v2 (TP early-take %50R partial), v3 (regime-conditional: sadece HTF'de bull → bullish climax fade YASAK, sadece HTF'de bear → bearish climax fade YASAK, yani trend rejiminin terse yönlü Anti).

## 7. Pre-registration İmza

Yazıldı: 2026-06-10. Kod yazılmadı. Backtest koşulmadı. Hash dondurulacak: `git add . && git commit -m "preregister HYP-2026-06-10-grimes-anti-climax-fade-1d"`.
