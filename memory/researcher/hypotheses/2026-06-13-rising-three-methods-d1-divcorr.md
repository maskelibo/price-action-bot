---
doc_id: researcher-20260613T130000-rising-three-methods-d1-divcorr
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T13:00:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, continuation, daily, low_correlation, vsa_climax_test_complement, bulkowski_rank10]
supersedes: null
---

# HYP-2026-06-13-rising-three-methods-d1-divcorr

## 1. Seed bağlamı
Aktif kol: `vsa_climax_test` (15m, hacim-doruğu fade — mean-reversion karakteri).
İhtiyaç: **düşük korelasyonlu** ek bir kol; raftaki 66 candidate'ten **mekanizma-ters + TF-ters** olanı seç ki portföy entropy artsın, ensemble Sharpe yükselsin.

## 2. İddia (pre-registered, tek cümle, ölçülebilir)

**1D timeframe'de, USDT-perpetual evreninde, "Rising Three Methods" (5-bar bullish continuation) ve ayna görüntüsü "Falling Three Methods" (5-bar bearish continuation) — Bulkowski/Nison mekanik tanımıyla — son 3 yıllık delisting-dahil evrende koşulduğunda aşağıdaki sayısal eşikleri *aynı anda* karşılar:**

| Metric | Hedef | Reddet Eşiği |
|---|---|---|
| Net annualized return (fee 7.5 bps taker + 5 bps slip dahil) | ≥ 25% | < 12% |
| OOS walk-forward median Sharpe (3y/6m, step 3m) | ≥ 0.80 | < 0.50 |
| MaxDD (account equity bazlı, kümülatif PnL DEĞİL — bkz LESSON-MaxDD-zero-base) | ≤ 25% | > 35% |
| Profit factor (gross) | ≥ 1.35 | < 1.15 |
| **Pearson(ρ) — günlük returns vs `vsa_climax_test` aynı dönem** | **\|ρ\| ≤ 0.20** | \|ρ\| > 0.35 |
| **DSR (Bailey-López de Prado)** | ≥ 0.50 | < 0.50 → **RED** |
| **PBO (Combinatorially Symmetric CV)** | ≤ 0.50 | > 0.50 → **RED** |
| In-sample / OOS Sharpe oranı | IS ≤ 3 × OOS | IS > 3 × OOS → **RED** |
| Free params / sample size | ≤ 1/30 | > 1/30 → **RED** |
| Trade sayısı (OOS) | ≥ 150 | < 80 → istatistik geçersiz |

## 3. Gerekçe — RAG referansları

- **[Bulkowski, Encyclopedia of Candlestick Charts]** — "Rising Three Methods" continuation rate %74, performance rank 10/103 (RAG #10). Marubozu (#8) continuation %64 ile karşılaştırıldığında istatistiksel olarak en güçlü mum-bazlı continuation pattern. Bu rank'in DAHA YÜKSEK bir patternde bu kadar bariz olması başlı başına önemli.
- **[López de Prado, Advances in Financial ML, Ch.11-12]** — RAG #1: DSR, PBO, IS/OOS Sharpe, free-param/sample, walk-forward Sharpe varyans gate'lerinin 6'sı da yeşil olmadıkça production hayır. Bu hipotez bu 6 gate'i ZORUNLU karşılama kriteri olarak alır.
- **[Chan, Algorithmic Trading]** — RAG #9: Yeni stratejiler portföye girmeden önce out-of-sample Sharpe > 0.8 (single asset). 0.80 eşiğim buradan; "1.5" diye düşürüp marjı şişirmeyeceğim. Ayrıca **regime-conditional ensemble** mantığı (Chan): aktif kol mean-reversion, eklenen kol continuation → rejim kovaryansı yıkıcı olmamalı.
- **[Brooks, Trading Price Action]** — RAG #3: Bar kalitesi + HTF opposition vurgusu. Bu hipotezde Bar 5'in 1D EMA50 üzerinde kapanması (bullish için) HTF-alignment filtresi olarak eklenecek (bkz §5).
- **[Volman, Forex Price Action Scalping]** — RAG #2: Tekli inside bar (rank 78/103) zayıf; ama **çoklu inside (ii, iii)** güçlü. Rising Three Methods topolojik olarak Bar2-3-4'ün Bar1 içinde sıkışmasıdır — Volman'ın ii/iii prensibinin uzantısı. Bağımsız 2 kaynak aynı yapısal mantığı destekliyor.

## 4. Mekanik Tanım (vektörize edilebilir, lookahead-safe)

### Bullish (Rising Three Methods)
- **Bar 1 (t-4):** `close > open`, `body ≥ 1.50 × ATR(14)[t-4]`
- **Bars 2-4 (t-3, t-2, t-1):** her biri için:
  - `body ≤ 0.50 × Bar1_body`
  - `high[i] ≤ Bar1.close` VE `low[i] ≥ Bar1.open`  (Bar 1 gövdesi içinde sıkışma)
- **Bar 5 (t):** `close > open`, `close > Bar1.close`, `body ≥ 1.00 × ATR(14)[t]`
- **HTF filtre (Brooks alignment):** `Bar5.close > EMA50(1D)[t]`
- **Karar:** `t` close'unda hesaplanır, **giriş:** `t+1` open (lookahead-test SOP-2 zorunlu)
- **SL:** `Bar5.low − 0.50 × ATR(14)[t]`
- **TP:** 2R fixed; ek varyant olarak 1×ATR trailing (param search'te tek seçim, kıyas YOK — multiple testing önlemi).

### Bearish (Falling Three Methods) — simetrik ayna.

## 5. Independent Variables (sabitlenmiş — sweep YOK)

Curve-fit'ten kaçınmak için **eşikler önceden donduruluyor**, optimize edilmeyecek:

| Param | Değer | Kaynak |
|---|---|---|
| Bar1 body min × ATR | 1.50 | Brooks "signal bar" tanımı |
| Bars 2-4 body max × Bar1 | 0.50 | Bulkowski "small bars" |
| Bar5 body min × ATR | 1.00 | Standart breakout bar |
| ATR window | 14 | konvansiyon |
| EMA HTF | 50 | konvansiyon |
| SL ATR | 0.5 ek pufer | Brooks BE-pufer |
| TP | 2R | Risk parite |
| Fee/slip | 7.5 bps + 5 bps | konservatif (canlı 5+3 bps ölçüldü) |
| Risk per trade | 0.5% equity | sabit-fraksiyon (compounding-şişme önlemi — LESSON-compounding) |
| Universe | 19-sym pool (sec25, delisting-dahil) | LESSON-survivorship |

**SADECE iki ayrık varyant test edilecek:**
- V1: fixed 2R TP
- V2: 1×ATR trailing

**Bonferroni n=2** ile p-value × 2 düzeltilecek. Daha fazla sweep YAPILMAYACAK; her ek varyant n'i büyütür ve DSR'yi çürütür.

## 6. Dependent Variables

Pre-registered ölçülecek metrikler (raporda hepsi olacak, cherry-pick yok):

1. Net annualized return (fee+slip dahil)
2. Median Sharpe (walk-forward 12 dilim)
3. MaxDD (account equity, NOT cumulative PnL)
4. Profit factor (gross)
5. Win rate (info)
6. Expectancy R-multiple
7. Trade sayısı (toplam, OOS)
8. **Pearson ve Spearman ρ vs vsa_climax_test günlük returns**
9. DSR, PBO, IS/OOS Sharpe ratio
10. Stress dilimleri: 2022-05 LUNA, 2022-11 FTX, 2023-03 USDC, 2024-08 Yen carry — her birinde drawdown
11. Regime split: bull/bear/range — en az 2'sinde pozitif olmalı (RAG #9 Chan)

## 7. Null Hipotezler (neyle çürür)

- **H0_edge:** Net annual return ≤ 12% — gerçek edge yok, RED.
- **H0_corr:** \|ρ vs vsa_climax_test\| > 0.35 — düşük korelasyon iddiası çürür; portföy değeri sıfır → RED (gate'i geçse bile bu hipotezin AMACI başarısız).
- **H0_overfit:** DSR < 0.50 VEYA PBO > 0.50 → RED.
- **H0_robustness:** Param perturbation (±%10, 50 seed) ort. Sharpe kaybı > %25 → RED.

## 8. Beklenen p-value

- Shuffle baseline (returns shuffled null): hedef **p < 0.01**
- Bonferroni (n=2 varyant): p × 2 < 0.05
- DSR (Bailey-López de Prado): ≥ 0.50

Bulkowski'nin %74 continuation oranı **n=11k+ örneklem** üzerinden hisse senedinde geliyor — kripto'da etkinin %20-40 zayıflaması beklenir (asset class transfer + survivorship düzeltmesi). Yani **iddiamı %74 değil ~%55-60 win rate** beklentisi etrafında kuruyorum. Bunun altına düşerse hipotez zayıflar.

## 9. Stop Criteria (araştırma terkedilir)

Aşağıdakilerden BİRİ tetiklenirse hipotez RED, learning.md'ye 3 satır gerekçe yazılır:

1. In-sample Sharpe < 0.5 (henüz IS) → araştırma terk.
2. OOS Sharpe < 0.50.
3. \|ρ vs vsa_climax_test\| > 0.35 (ana motivasyon çürür).
4. Trade sayısı < 80 (istatistiksel güç yetersiz, daha geniş evren denenir ama bu varyant ölür).
5. DSR < 0.50 veya PBO > 0.50.
6. LUNA/FTX/USDC/Yen carry dilimlerinden HERHANGİ birinde -%15 üzeri DD.
7. Bull rejiminde pozitifken bear rejiminde -Sharpe < -0.5 (asimetrik kuyruğa yenilmek).

## 10. Curve-fit kırmızı bayrak öz-değerlendirme (paranoid mod)

Kendime karşı şüpheli olduğum noktalar:

- ⚠️ **"Rising Three Methods" Bulkowski'de rank 10** → bu rank'i bilen biri özellikle bunu seçti, **selection bias riski yüksek**. RAG'den 5-10 candidate yerine "en yüksek rank"i seçmek p-hacking'in jenerasyon-öncesi versiyonu.
  - **Karşı önlem:** PBO testi + 19-sym DELISTING-DAHİL evren + symbol-out CV + Bonferroni.
- ⚠️ **5-bar pattern doğal olarak nadirdir** → OOS'ta n çok düşük çıkabilir; "yüksek win rate ama 12 trade" tuzak.
  - **Karşı önlem:** n ≥ 150 OOS zorunlu, altındaysa RED.
- ⚠️ **HTF EMA50 filtresi ekledim — bu da bir parametre** → free-params sayısını şişirir.
  - **Karşı önlem:** EMA50 konvansiyon, optimize edilmiyor; ablation testi (EMA50 KAPALI versiyon da raporda — eğer EMA50'siz versiyon DAHA iyi ise filtre overfit demek).
- ⚠️ **Bulkowski stats hisse senedi — kripto'ya transfer paradoksu** → asset class shift effect büyük olabilir.
  - **Karşı önlem:** Beklenti %55-60 olarak düşürüldü, %74 değil. Düşük beklentiyi karşılayamazsa zaten RED.
- ⚠️ **vsa_climax_test ile düşük korelasyon iddiası aslında EX-ANTE** → henüz live data yok, backtest'te ρ hesaplanacak. Eğer ρ hesabı OOS dönem dışında yapılırsa bias.
  - **Karşı önlem:** ρ SADECE OOS dilimleri kullanılarak hesaplanır.

## 11. Reproducibility

- git_hash: (commit-time donar)
- config_hash: SHA256(bu dosya §4 + §5 sabitleri)
- data_hash: 19-sym pool sec25 manifest hash'i
- backtest config: `configs/strategies/rising_three_methods_d1.yaml` (draft sadece, hipotez RED olursa silinir)

## 12. Beklenen iş akışı

1. ✅ Pre-registration (bu dosya) — commit'le donar.
2. Backtest engine run (V1 + V2 yalnızca).
3. Robustness suite (SOP-3 — 8 madde tamamı).
4. ρ hesabı (OOS pencerelerinde, vsa_climax_test'in canlı return time-series'i kullanılır).
5. Karar: terfi adayı / iterate / RED (SOP-4).

**Eğer iddiamı çürütmek isterse:** in-sample Sharpe < 0.5 erken durdurma; PBO > 0.50; ρ > 0.35. Bu üç ölüm sebebinden BİRİNİN bile çıkması yeterli, "ama edge var" denmez.

---

**İmza:** researcher (Opus 4.7), 2026-06-13
**Sonraki adım:** backtest config çıkarımı — değişiklik YAPMADAN.
