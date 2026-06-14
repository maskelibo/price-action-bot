---
doc_id: researcher-20260612T103000-grimes-anti-climax-fade-4h-chan-halflife-prescreen
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T10:30:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-vsa_climax_test-live-baseline
  - researcher-20260605-kaufman-rsi-div-chan-halflife-regime-gate-crypto-1d
  - researcher-20260610-grimes-anti-climax-fade-1d-low-corr-to-vsa
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, pre-registration, grimes-anti, climax-fade, 4h, chan-halflife-prescreen, lopez-discretization, counter-trend, low-correlation, curve-fit-warning]
supersedes: null
hash: null
---

# Hipotez HYP-2026-06-12-anti-4h-chan — Grimes "Anti" climax-fade 4H, Chan half-life pre-screen + López discretization sizing

## 0. Bağlam ve seçim gerekçesi

Aktif kol: `vsa_climax_test` (volume-spread analysis, climax/exhaustion → reversal-bias, mean-reverting çekirdek). Cross-strategy edge seed'i: aynı sınıfta (mean-reverting) ama **farklı tetikleyici + farklı timeframe** üreterek **regime/sample-overlap** ölçmek; gerçek ortogonalite mi yoksa "aynı ailenin iki kopyası" mı?

Grimes Anti (RAG#3): climax bar sonrası **ilk küçük pullback'i karşı yönde fade** etmek; yapısal olarak "exhaustion-fade" — VSA climax'a tematik **yakın** ama tetikleyici farklı (volume spike değil, bar-range/Bollinger uç). 1D'da paralel hipotez 2026-06-10'da pre-register edildi; bu hipotez **4H** timeframe'inde + **iki ek filtre** ile (Chan half-life + López w_i sizing) **örnek seti farklılaştırmayı** test eder.

Bu hipotez **kasıtlı olarak temkinli** — Grimes'ın kendisi setup'ı "düşük WR (~%40–45), R büyük olabilir, expected value hafifçe pozitif" diye tarifliyor (RAG#3). Yani **bar yüksek değil**: pozitif edge'in zar zor çıkması beklenti. Bu durumda overfit/curve-fit ekstra tehlike — aşağıda red-flag bölümü çok geniş tutuldu.

## 1. İddia (single sentence, ölçülebilir)

**"4H timeframe'de, USDT-perpetual top-20 ADV evreninde, son 60-bar rolling Chan half-life'ı ≤ 5 bar olan sembollerde, Grimes Anti climax-fade pattern'ı (bar_range/ATR(20) > 2.0 VE close 2σ Bollinger(20) bandı dışında) sonrası ilk reversal bar (close 1σ Bollinger bandı içine geri dönüş) close'unda KARŞI yönde alımla, climax bar extreme'i + 0.1×ATR(14) SL ve fixed 2R TP ile, López discretization (w_i = m_i/Σ|m_j|, m_i = 1/N concurrent open) ile sizing'lenmiş şekilde, 2022-01-01 → 2025-12-31 IS / 2026-01-01 → 2026-05-31 OOS sliding-OOS evreninde:**
- **Net monthly return > +1.5%** (fees 7.5bps taker + slip 5bps dahil, sabit-fraksiyon %1/trade baz, ay-bağımsız taze-$10k metodolojisi)
- **OOS Sharpe > 0.60** (Bonferroni n=1 sonrası anlamlı; tek-set tasarım, sweep yok)
- **MaxDD < 28%** (account-equity tabanlı, mark-to-market)
- **Profit factor > 1.20**
- **Win rate ∈ [%38, %50]** (Grimes'ın predicted bandı — bu bandın dışı = pattern uymadı)
- **|ρ(daily_return_anti_4h, daily_return_vsa_climax_test)| < 0.30** (Pearson, aynı pencere — 1D Anti versiyonundan daha yumuşak çünkü VSA'ya tematik yakın)
- **Jaccard overlap (gün+sembol) < 0.10** (trade sample örtüşmesi)
- **Half-life pre-screen pass rate ≥ %30** (bar-zamanı bazlı; aksi halde strateji pratik değil)
- **Trade sayısı N ≥ 80** (4H × ~3.5 yıl × 20 sym; istatistiksel taban düşük ama tolere edilir)
**üretir."**

## 2. Null hipotez (H0)

H0: Yukarıdaki 9 metriğin **en az birinde** hedef yakalanmaz; özellikle:
- (a) net monthly ≤ 0% (edge yok), **veya**
- (b) IS/OOS Sharpe gap > %50 (overfit), **veya**
- (c) WR < %38 (pattern Grimes'ın bandının altında — tetikleyici bozuk), **veya**
- (d) |ρ| ≥ 0.30 (diversifier değil, VSA'nın 4H'da yeniden ifade edilmesi), **veya**
- (e) Half-life pass rate < %30 (filtre çok dar, strateji pratik dışı).

H0 reddedilemezse → hipotez **RED**, ama:
- net monthly ∈ (0%, 1.5%) AND tüm risk metrikleri PASS → SOP-4b devrede (iterate budget v2-v5).
- net monthly ≤ 0% → arşiv (red); "1D Anti'nin 4H taşınması fonksiyonel değil" learning.md'ye 3 satır.

## 3. Gerekçe — RAG referansları

- **[Grimes, RAG#3 — "Anti" setup]**: Climax bar sonrası karşı yön kontre. Lokasyon: Bollinger ±2σ dışı + bar > 2×ATR. WR ~%40-45, R 2-3 olabilir, EV hafifçe pozitif. Setup'ın sahibi Grimes "zor + yüksek-iskontolu, sadece deneyimli" diyor — biz mekanik kuralla simüle ediyoruz, **insan-discretion edge'i yok**; bu zaten EV'yi negatif tarafa kaydırabilir.
- **[Grimes, RAG#4 — sermaye disiplini]**: "Over-leverage = iyi sistemleri bozan #1 sebep." Bu hipotez %1 risk/trade SABİT — emergent leverage yok. "Adding to losers" YASAK — partial-fill veya retry-on-stop tetikleyicisi YOK.
- **[Chan, RAG#5 — mean-reversion half-life]**: Sharpe ∝ 1/√half-life. Half-life ≤ 5 bar (4H'da 5 bar = ~20 saat) çok kısa — Chan'a göre yüksek-Sharpe rejim. Pre-screen: rolling 60-bar (close - SMA(20)) spread'in AR(1) coefficient'ından half-life. **Eğer half-life > 30 bar → "trade için sabır, capital cost yüksek" (RAG#5) → SKIP.**
- **[López, RAG#7 — capital allocation matrisi]**: w_i = m_i / Σ|m_j|, discretization: w_i < 0.05 → 0. Eş zamanlı N pozisyon varken her bir trade'in **gerçek dollar exposure**'u 1/N'ye orantılı; portföy volatilite katkısı kontrollü. Bu, naïve "fixed %1 her trade" yerine **portföye-duyarlı** sizing — Anti gibi düşük-WR setup'ta varyans azaltıcı.
- **[López, RAG#9 — DSR thresholds]**: DSR < 0.5 = rastlantı, [0.5, 0.6] = kararsız, [0.6, 0.95] = kabul edilebilir, > 0.95 = güçlü kanıt. Bu hipotezde OOS Sharpe hedefi 0.60 = DSR ~0.5–0.6 bandı (yani "kararsız" sınırı). **Kabul edilebilir minimum**, ne fazla.

**Tematik yakınlık riski:** Grimes Anti + VSA climax aynı "exhaustion-fade" ailesinden. Bu hipotezin ana keşif eksenı **timeframe + filtre stack** ile gerçek ortogonalite üretmek; eğer ρ ≥ 0.30 çıkarsa "aynı setup'ın iki uygulaması" sonucuna varır, diversifier değildir.

## 4. Pre-registered metrikler (tek-set, sweep YASAK)

### 4.1 Sabit parametreler (Optuna sweep YOK)

| Parametre | Değer | Kaynak / gerekçe | Sweep yasağı |
|---|---|---|---|
| Timeframe | 4H | Grimes 1D versiyonundan farklılaştırma | YASAK |
| Climax bar_range / ATR(20) | > 2.0 | Grimes RAG#3 "2 ATR'den büyük" | YASAK |
| Climax Bollinger σ | 2.0 | Grimes RAG#3 "2 sigma+ basan bar" | YASAK |
| Reversal bar tanımı | close 1σ Bollinger içine geri dönüş | Anti = "first pullback başlangıcı" yapısal okunuş | YASAK |
| Entry | reversal bar close | Pre-register, no slippage modeling | YASAK |
| Direction | climax YÖNÜNÜN TERSİ | RAG#3 net | YASAK |
| SL | climax bar extreme + 0.1×ATR(14) | Grimes RAG#3 "extension high/low'unun ötesi" | YASAK |
| TP | fixed 2R | Standart, çoklu-TP YOK (curve-fit önleme) | YASAK |
| Position sizing baz | %1 risk/trade | Grimes RAG#4 "anti-over-leverage" | YASAK |
| López discretization eşik | w_i < 0.05 → 0 | RAG#7 "turnover azaltır" | YASAK |
| Half-life rolling | 60 bar (=10 gün 4H'da) | Chan RAG#5 "1-60 gün tradeable" alt-eşiği | YASAK |
| Half-life threshold | ≤ 5 bar | Chan RAG#5 "kısa half-life = yüksek Sharpe" | YASAK |
| Half-life base spread | close - SMA(20) | Klasik mean-rev base | YASAK |
| Sample evren | Top-20 USDT-perp by 90d ADV | Likidite filtresi, survivorship-aware | YASAK |
| IS period | 2022-01-01 → 2025-12-31 | ~4 yıl, LUNA + FTX + bull-bear-range dahil | YASAK |
| OOS period | 2026-01-01 → 2026-05-31 | Pure forward, 5 ay (kısa OOS = istatistiksel zayıflık — kabul edildi) | YASAK |
| Fees | 7.5 bps taker + 5 bps slip | Konservatif | YASAK |

### 4.2 Bağımlı değişkenler (raporlanacak)

- Net monthly return (% — ay-bağımsız taze-$10k)
- IS Sharpe, OOS Sharpe (annualized, sqrt-365×6 4H bar)
- MaxDD (account-equity, mark-to-market)
- Profit factor (gross win / gross loss)
- Win rate
- Average R (winners + losers, R-multiple)
- Trade count N
- Half-life pre-screen pass rate (kaç bar'da half-life ≤5 koşulu sağlandı / toplam bar)
- ρ(daily_return_anti_4h, daily_return_vsa_climax_test)
- Jaccard overlap (gün+sembol)
- López w_i ortalama (%) — sizing katkısı kontrolü
- DSR (López RAG#9 formülü)

### 4.3 Bağımsız değişkenler (sabit, açıkça raporlanır)

- Timeframe: 4H
- Climax tetik: bar_range/ATR(20), Bollinger σ
- Filtre stack: Chan half-life + López sizing
- Universe & period (yukarıdaki)

## 5. Beklenen p-value

- Single-set tasarım → Bonferroni n=1.
- H0 (net monthly ≤ 0%) için tek-tail t-test, hedef **p < 0.05**.
- Shuffle baseline (returns shuffle, 1000 perm) yenmek zorunda — **p < 0.05**.
- DSR ≥ 0.50 (López RAG#9 kabul tabanı).

**Multi-testing context:** Bu hipotez tek-set, ancak proje genelinde 30+ paralel hipotez sürüyor. Family-wise correction: hipoteze p < 0.05 / 30 = **0.0017** lazım derseniz aday düşer. Buradaki tavır: **per-hipotez p < 0.05 göster; family-wise düzeltmeyi Lab tournament gate'inde uygula** (DSR + PBO ile).

## 6. Stop criteria (red flags — abandon koşulları)

Aşağıdakilerden HERHANGİ BİRİ tetiklenirse araştırma terkedilir (iterate dahi yapılmaz):

1. **IS Sharpe < 0.5** → "bu setup 4H'da çalışmıyor"; arşiv.
2. **IS/OOS Sharpe gap > %50** → curve-fit/overfit; arşiv.
3. **Half-life pre-screen pass rate < %30** → filtre çok dar, strateji pratik dışı.
4. **Trade sayısı N < 80** → istatistiksel taban yok; hipotez sonuçsuz.
5. **Win rate < %38** → Grimes'ın predicted bandının altı; tetikleyici tanımı bozuk demektir.
6. **Win rate > %55** → Grimes'ın predicted bandının üstü; muhtemelen lookahead/leakage var, AUDIT.
7. **Param perturb (±%10, 50 seed) Sharpe ortalama kayıp > %30** → kırılgan, arşiv.
8. **Stress periyodlarından (2022-05 LUNA, 2022-11 FTX, 2024-08 Yen) herhangi birinde -20% drawdown** → tail-risk kontrol edilemiyor.
9. **Lookahead test (entry +1 bar geciktirme) edge'i %50+ siler** → timing-dependent leakage; arşiv.

## 7. Curve-fit / overfit RED FLAGS (kasıtlı self-skeptic bölüm)

Bu hipotezin **olası overfit kaynakları** — pre-test olarak açıkça yazıyorum ki Lab + Adversary kontrol edebilsin:

1. **2.0 ATR climax eşik kayan** — Grimes "2 ATR'den büyük" diyor ama sayı subjektif. Eğer 1.8 ile 2.2 arası sweep yapsam ve "best" seçsem, **kesin overfit**. Pre-register: 2.0 SABİT, sweep YASAK. Sonuç negatifse "2.0 yanlış noktaymış" denemez — hipotez RED.
2. **Bollinger 2σ + 1σ band çiftleşmesi** — 2 parametre var (climax band, reversal band). Bunlar arası ratio (2:1) Grimes'tan değil, benim tasarımım. **Tartışmalı**.
3. **Half-life ≤ 5 bar eşiği** — Chan'da "1-60 gün tradeable" diyor ama "5" benim seçimim. 4H'da 5 bar = 20 saat = günler değil. **Çağrışım zorlaması olabilir.**
4. **60-bar rolling window** — Chan kitabı sabit window önermiyor. 60 = "10 gün 4H'da" pratik seçim ama keyfi.
5. **Top-20 ADV evren seçimi** — N=20 keyfi (15 veya 30 değil). Universe-out CV (her sembolü dışarıda bırak) zorunlu.
6. **2R fixed TP** — Anti'de Grimes "2-3R" bandı tarif ediyor. 2R seçimi muhafazakar ama 3R deneseydim sonuç değişirdi. Pre-register: 2R, sweep YASAK; 3R sonradan "daha iyi" diye değiştirilmez.
7. **López discretization 0.05 eşiği** — López "çok küçük w_i'leri yuvarla" diyor ama "çok küçük" tanımını vermiyor. 0.05 benim seçimim; **bu da curve-fit kaynağı**.
8. **OOS 5 ay çok kısa** — Pure-forward sample küçük. OOS Sharpe büyük güven aralığı taşır. Sonuç anlamlılığı şüpheli.
9. **Anti + climax tematik yakınlığı VSA'ya** — Eğer ρ < 0.30 çıkarsa "gerçek diversifier" diyebiliriz ama [%0, %30] arası bir ρ "aynı sample'ın farklı ifadesi" olarak yorumlanır; risk_officer çağrılır.

**Eğer 9'dan 3+ kırmızı bayrak aday'da tetiklenirse: hipotez RED, iterate budget açılmaz** (positive-edge rescue politikasının istisnası — overfit-tabanlı edge gerçek edge değildir).

## 8. SOP-3 robustness suite (zorunlu kontrol listesi)

Aday gate'i geçerse, aşağıdakilerin TÜMÜ koşulur (vectorbt + walk-forward harness'i):

| Test | Hedef | Sonuç |
|---|---|---|
| Walk-forward 3y/6m, step 3m | en az 9/12 dilim pozitif | TBD |
| In-sample / out-of-sample Sharpe gap | < %30 | TBD |
| Random param perturbation (±%10, 50 seed) | ortalama Sharpe kayıp < %25 | TBD |
| Symbol-out CV (20 fold) | min Sharpe > 0.4 | TBD |
| Regime split (bull/bear/range) | en az 2'sinde pozitif | TBD |
| Stress periodları (LUNA, FTX, USDC, Yen) | DD < -15% her dilimde | TBD |
| Shuffle baseline (1000 perm) | p < 0.05 | TBD |
| Lookahead delay test (+1 bar) | edge'in %80'i kalır | TBD |
| DSR (López) | ≥ 0.50 | TBD |
| PBO (probability of backtest overfit) | < 0.50 | TBD |
| Bonferroni / FDR düzeltme | family-wise n=30 → α=0.0017 | (info only, per-hipotez α=0.05) |

## 9. Karar matrisi (gate sonrası 3-yol)

```
IF (tüm 9 metrik PASS) AND (SOP-3 robustness ALL PASS) AND (curve-fit red-flag < 3):
    → terfi adayı, Lab tournament'a teslim (configs/strategies/grimes_anti_4h_chan.yaml taslak)
ELSE IF (net monthly > 0%) AND (risk metrikleri PASS) AND (curve-fit red-flag < 3):
    → SOP-4b iterate (v2-v5 budget):
        v2: risk_pct 0.01 → 0.005
        v3: trade-quality filter (confluence >= 2.0)
        v4: regime-only (bull-only veya bear-only subset)
        v5: time-exit (24h max hold)
ELSE:
    → RED, gerekçeli arşiv, learning.md 3-satır
```

## 10. Pre-registration commit (reproducibility lock)

- Bu doküman **commit edilir** ve git hash ile mühürlenir.
- Backtest config (`configs/research/grimes_anti_4h_chan.yaml`) bu doc'un hash'iyle bağlanır.
- Veri snapshot: `data/snapshots/<git_hash>/` (DuckDB read-only mount).
- Sonuç raporu (`reports/research/grimes_anti_4h_chan-2026-06-12.html`) bu doc'a `depends_on` ile bağlanır.

## 11. Beklenti dürüst beyanı (anti-narrative bias)

Bu hipotezin **ön-deneysel kişisel olasılığı**:

- P(net monthly > 1.5% AND tüm gate PASS) ≈ **%12–18** (düşük; Anti zaten zor setup)
- P(net monthly ∈ [0%, 1.5%], iterate'e gider) ≈ **%25–35**
- P(net monthly ≤ 0%, RED) ≈ **%50–60**

Yani **en olası sonuç: RED**. Bu sağlıklı baz oran — SOP-1 KPI'sı "terfi oranı %20-40" bandı. Hipotez negatif çıkarsa şaşırmam; sürpriz olan tarafı **pozitif çıkması**.

**Anti-narrative bias guard:** "Grimes legend, Chan klasik, López altın standart → kombo çalışmalı" duygusu narrative bias'tır. Bu üçü ayrı ayrı doğru olabilir, kombosu **kripto 4H mikro-yapıda** çalışmayabilir. Sayı söyler, narrative söylemez.

## 12. Sonraki adımlar (lab + adversary)

- **lab_scientist**: Tournament eligibility — bu aday gate geçerse VSA + 15m-Grimes-ABC ile head-to-head; portföy-marjinal Sharpe katkısı raporu.
- **risk_officer**: Sizing politikası uyumlu mu? López discretization mevcut allocator'a injekte edilebilir mi yoksa wrapper mı gerekir?
- **adversary_engineer**: Stress replay (LUNA + FTX + Yen) ve kill-probe; pre-deploy gate.

---

**Bu hipotez tek-set pre-registration. Param sweep YASAK. Sonuç ne olursa olsun raporlanacak — null sonuç bile değerlidir.**
