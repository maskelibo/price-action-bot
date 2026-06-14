---
doc_id: researcher-20260601T144500-golden-death-cross-50-200-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T14:45:00Z
status: PROPOSED
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, ma_crossover, trend_following, cross_strategy_edge, low_correlation, kaufman, curve_fit_risk]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-01-golden-death-cross-50-200-low-corr-to-vsa

- Tarih: 2026-06-01
- Versiyon: 0.1
- Pre-registration: YES (kod yazılmadan önce)
- Seed konu: aktif vsa_climax_test ile düşük korelasyonlu raftaki ek strateji adayı (66 candidate içinden).

## 1. İddia (tek cümle, ölçülebilir)

> "1D timeframe'de, USDT-perpetual top-30 evreninde, **EMA50 × EMA200 kapanış-bazlı crossover** (golden cross = EMA50, EMA200'ü yukarı keser → long; death cross → short), bir sonraki barın açılışında piyasa girişi, 1.5×ATR(14) SL, **trailing 10-bar opposite Donchian channel** ile çıkış stratejisi, 2022-01-01 → 2025-06-01 periyodunda, taker fee 7.5 bps + 5 bps slippage dahil:
>   - Annualized **net** return ∈ [25%, 50%]
>   - OOS Sharpe ≥ 0.8 (ama ≤ 1.8 — IS=2× ise overfit kırmızı bayrağı)
>   - MaxDD ≤ 30%
>   - Profit factor ≥ 1.3
>   - **Daily-returns correlation ile aktif vsa_climax_test < 0.25** (gerçek diversifikasyon kanıtı)
>   - Trade sayısı ≥ 80 (multi-symbol; tek sembolde < 5 sinyal düşer → istatistik sıfır)
> üretir."

Bu eşiklerin **üstüne** çıkan herhangi bir sonuç (örn. Sharpe > 2.5, MaxDD < %10) doğrudan **overfit şüphesi** olarak işaretlenecek; bu strateji türünün yapısal asimetri profili (Donchian-trail → düşük WR, yüksek R-multiple) bu kadar parlak performansı üretmez. Eğer üretiyorsa parametre uzayında bir yerde leak vardır.

## 2. Null Hipotez

H₀: 50×200 EMA crossover sinyali, shuffle baseline'a (returns'leri sembol-bağımsız shuffle) karşı net Sharpe iyileştirmesi sağlamaz (p ≥ 0.05). Yani sinyal seçimi değil, **sembol evreni momentum'u** üzerinden trivial bias kazandırır.

Bunu çürütmek için:
- Shuffle-baseline n=1000 permutation testi.
- Random-entry control: aynı symbol-bar dağılımı ile rastgele giriş günleri.

## 3. Gerekçe (RAG referansları)

- **[Kaufman 2013, Ch.5: Trend Systems — Moving Average Crossovers]** (RAG #4):
  - Golden cross/death cross **major trend captures**, daily/weekly ideal, intraday'de gürültü baskın.
  - Beklenen failure modu: **sideways market'te 4-6 ardışık whipsaw**; bu da bizim bear/range regime split'inde net negatif olmasını öngörür → bu beklentiyi test edip doğrulayabiliriz (eğer her rejimde aynı pozitif → overfit alarmı).
- **[Kaufman 2013, Donchian channel — Turtle System]** (RAG #7):
  - Trailing exit mekaniği olarak **10-bar opposite channel** öneriliyor. Bu, biz fix-target yerine bunu seçtiğimizde **asimetrik R-multiple** kazandırır: %35 WR, 3-5R winners.
  - Bu trade-off (düşük WR + yüksek R-multiple) VSA-climax profili ile (orta-yüksek WR + 1-2R hedef) **yapısal olarak ortogonal** → low-correlation prior'unu güçlendirir.
- **[Lopez de Prado 2018, DSR + PBO frameworks]** (RAG #1):
  - DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe → red. Tüm bu kriterleri bu hipoteze uygulamak ZORUNLU.

**RAG'in bana söylemediği şey:** Kripto-spesifik MA crossover net-fee performansı. Akademik backtest'ler genellikle equity index'leri üzerinden; kripto fee yapısı (7.5bps taker) ve volatilite (BTC günlük %5 std) bu strategy'i bozabilir. Bu boşluk **kendi başına bir red gerekçesi olabilir.**

## 4. Independent Variables (parametre uzayı — sweep yapılmaz, sabit tutulur)

> **🔥 CURVE-FIT İLK SAVUNMA: Tek param-set, sweep yok.** Optuna SADECE objective gözlemlemek için tek-run kullanılır; "best params"a göre seçim yapılmaz. Bu, çoklu hipotez testi inflation'ı yok eder.

Sabit (literatür-default; optimize ETMEM):
- Fast EMA period: **50** (Kaufman defaultu; 30/40/60 alternatifleri sweep YAPILMAZ)
- Slow EMA period: **200** (Kaufman defaultu; 150/250 sweep YAPILMAZ)
- ATR period: **14**
- SL multiplier: **1.5 × ATR(14)** (Kaufman defaultu)
- Trail channel length: **10 bar** (Turtle System 1 defaultu)
- Risk per trade: **0.5%** (konservatif; vsa_climax ile aynı blok)
- Entry: BOS-onayı yok, sadece crossover bar **kapanışında** sinyal → t+1 open giriş
- Trend-only filter YOK (golden cross zaten trend filtresi)

Eğer sonuçlar yetersizse → reddedilir. Param tweak yapılmaz; yapılırsa "**multiple testing inflation**" alarmı çalar.

## 5. Dependent Variables (pre-registered metrikler)

| Metric | Hedef | Curve-fit kırmızı bayrak |
|---|---|---|
| Annualized **net** return | 25% — 50% | > %80 → leak şüphesi |
| OOS Sharpe | ≥ 0.8 | > 1.8 → overfit (Kaufman literatür baseline ≈ 0.6–1.0) |
| MaxDD | ≤ 30% | < %10 → unrealistic |
| Profit factor | ≥ 1.3 | > 2.5 → leak şüphesi |
| Win rate | %30 — %45 (Turtle profili) | > %55 → trail kaymış olabilir |
| Avg R-multiple winner | ≥ 2.5R | < 1.8R → trailing exit çalışmamış |
| Trade count (3y) | ≥ 80 | < 50 → istatistiksel anlamsız → red |
| **Daily-returns ρ(vsa_climax_test)** | **< 0.25** | ≥ 0.40 → diversification iddiası çürür → red |
| Walk-forward dilim oranı (pozitif/toplam) | ≥ 9/12 | ≤ 7/12 → tutarsız edge |
| IS / OOS Sharpe oranı | ≤ 1.5 | > 2.0 → Lopez kriteri kırıldı → red |
| Shuffle baseline p-value | < 0.05 | ≥ 0.10 → H₀ reddedilemez → red |

## 6. Beklenen p-value ve düzeltme

- Shuffle baseline H₀ testi: beklenen **p ≈ 0.01 — 0.05**.
- Multiple testing: bu hipotez **tek param-set** ile koşulduğu için Bonferroni n=1; düzeltme gerektirmez. AMA bu hipotez "66 candidate raf"ından geliyor — global aile düzeyinde **Bonferroni n=66 ⇒ effective α = 0.05/66 ≈ 0.00076**. Eğer p ≥ 0.00076 ise "raf-genelinde anlamlı değil" notu düşülür (terfiye engel değil ama uyarı).
- DSR (Deflated Sharpe Ratio): Lopez kriteri ≥ 0.5 olmalı.

## 7. Stop Criteria (araştırma terkedilir, iterate açılmaz)

Aşağıdakilerden **biri** olursa hipotez derhal reddedilir:

1. In-sample Sharpe < 0.5 (literatür baseline'ın altı → edge yok).
2. Trade count < 50 (istatistik sıfır).
3. Symbol-out CV: medyan Sharpe < 0.0 (tek-sembol carry).
4. Lookahead testi başarısız (causality kırıldı).
5. ρ(vsa_climax_test) ≥ 0.40 (cross-strategy edge claim çürür; ana motivasyon yok).
6. Sweep ihtiyacı doğarsa (tek param-set ile gate'i geçemiyor ve **gözüm tweak'e gidiyor**) → DERHAL terk. "Ek param" araması bu hipotezin **bağımsız iddiasını çürütür**, başka hipotez olur.

## 8. Iterate Politikası (SOP-4b)

Bu hipoteze iterate AÇILMAZ — çünkü:
- Tek param-set hipotezi; rescue için "param tweak" = curve-fit kapısı açar.
- Eğer aylık ROI pozitif ama DD yüksekse iterate **sadece risk_pct azaltma** ile yapılabilir (parametre sweep'e izin yok). Yani v2 = `risk_pct: 0.005 → 0.003` tek değişiklik. Başka iterate yapılmaz.

## 9. Beklenen Sonuç (önceden tahmin — bias hunt için)

> **Naif beklentim:** Kripto 1D'de 50×200 EMA crossover yıllık 2-4 sinyal × 30 sembol = ~80-100 trade üretir; bunların ~%35'i kazanır, ortalama winner ≈ 3R, loser ≈ -1R → net beklenti pozitif ama **fee+slip net Sharpe'ı 0.5 — 1.0 aralığına çeker.** Yani gate'i geçmeyecek tahmin ediyorum.
>
> Bu tahmini önceden yazıyorum ki backtest sonucu çok parlaksa (Sharpe > 1.5, MaxDD < %15) **kendi beklentime karşı şüpheci** olabileyim. Hindsight bias panzehri.

## 10. Curve-fit Şüphe Listesi (önceden işaretleniyor)

Backtest sonrası bu listenin **her satırı** kontrol edilecek:

1. **50/200 sayıları ne kadar "magic number"?** Eğer 40/180 veya 60/220 ile sonuç dramatik değişiyorsa → fragile.
2. **Sembol kompozisyonu carry mi?** En iyi 5 sembolün toplam P&L'e katkısı %70'ten fazlaysa → tek-tema (BTC trend) carry.
3. **2024 boğa rallisi tek başına mı taşıyor?** P&L'in %80'i 2024'tense → recency.
4. **Donchian trail = 10 bar nereden geldi?** Turtle System default; AMA kripto'da farklı çalışabilir. 8/12 ile karşılaştırma raporu zorunlu (sweep değil — robustness check).
5. **EMA mi SMA mı kullanıyoruz, neden?** EMA (smoothing tepkiselliği) sebebi vurgulanmalı; SMA ile kıyas testi tek seferlik bilgi olarak alınır, parametre olarak değişmez.

## 11. Reproducibility

- git_hash: (backtest çalıştığında doldurulacak)
- config_hash: (backtest çalıştığında doldurulacak)
- data_hash: data/futures.duckdb @ snapshot 2026-06-01 (delisting-included universe)
- seed: 42 (shuffle baseline ve random-entry control için sabit)

## 12. Sonraki Adımlar

1. ✅ Pre-register (bu doc).
2. ⏳ Backtest config türet (`configs/strategies/_candidate_golden_death_cross_50_200.yaml` — taslak).
3. ⏳ `backtest.engine.run()` tek koşum.
4. ⏳ Robustness suite TAM (SOP-3 8 madde).
5. ⏳ Korelasyon hesabı (aktif vsa_climax_test daily returns ile).
6. ⏳ Raporu yaz → karar: terfi adayı / red / (iterate yasak).

## Doc Status

- **status: PROPOSED** — review için lab_scientist + risk_officer'a gönderildi (`requested_review_from`). Lab istatistik metodolojisi (Lopez kriterleri, multiple testing) için endorse/critique versin; Risk Officer ρ < 0.25 iddiasının diversifikasyon argümanı olarak yeterli olup olmadığına bakar.

---

**🔥 Researcher notu (kendime):** Bu hipotez muhtemelen reddedilecek. Naif tahminim Sharpe < 1.0 ve gate'e takılır. Bu **kötü değil** — pozitif edge bulamamak da bilgidir. Asıl korktuğum, sonuç parlak çıkarsa kendi beklentime karşı doğru şüpheci olamamak. O yüzden §9 ve §10'u pre-register ettim.
