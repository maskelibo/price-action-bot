---
doc_id: researcher-20260623T000000-order-block-mitigation-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-23T00:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260512T000000-liquidity-sweep-displacement-fvg
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - cross_strategy_companion
  - vsa_climax_diversifier
  - smc
  - order_block
  - mitigation_entry
  - displacement
  - pre_registration
  - low_corr_target
  - curve_fit_watch
supersedes: null
hash: null
hypothesis_id: 2026-06-23-order-block-mitigation-cross-strategy-companion-vsa
version: 0.1
---

# Hipotez: Order Block Mitigation Entry — vsa_climax_test düşük-korelasyonlu refakatçi

## 1. Iddia (pre-registered, ölçülebilir)

> 1D timeframe'de, USDT-perpetual evreninde (3 yıl, survivorship-dahil, ~50 sembol), aşağıdaki mekanik kurallarla tanımlanan **bullish/bearish Order Block (OB) mitigation** sinyali — bar açılışında market emirle, 1.0R fixed RR ile — son 3 yılda aşağıdaki metrikleri birlikte sağlar:
>
> - **Net annualized return ≥ %25** (fees 7.5bps taker + 5bps slip dahil)
> - **OOS Sharpe ≥ 0.8** (walk-forward, 3y/6m, 12 dilim)
> - **MaxDD ≤ %25** (account equity bazında, López-Prado convention)
> - **Profit factor ≥ 1.30**
> - **N_trades ≥ 200** (universe genelinde 3y) — düşük-N reddi için sert eşik
> - **Spearman korelasyonu (gün-bazlı PnL, vsa_climax_test ile) |ρ| ≤ 0.25** — bu **birincil koşul**; düşük korelasyon yoksa edge yeterli olsa bile companion olarak deploy ETMEM

Notlar:
- Korelasyon hedefi yapısal: VSA climax mean-reversion'a yakın (yüksek hacim + geniş range exhaustion), OB mitigation devam (displacement sonrası geri-test). Mekaniğin farklılığı bekleyişi destekler ama **kanıt zorunlu** — "mantıklı geliyor" hipotezi geçirmez.

## 2. Mekanik Tanım (curve-fit'e karşı sabitlenmiş, daha-sonra-değişmez)

**Displacement leg tanımı (tetikleyici):**
- Bar `t`'nin range'i ≥ **1.5 × ATR(20)**
- Bar `t`'nin body / range oranı ≥ **0.60**
- Yön: bullish (close > open) → potansiyel long-OB; bearish → short-OB

**Order Block tanımı:**
- Bullish displacement için: bar `t`'den geriye doğru **ilk bearish bar** (close < open). Maks lookback **5 bar**; bulunamazsa setup iptal.
- Bearish displacement için: simetrik (ilk bullish bar, lookback 5).
- OB seviyeleri: bullish OB için `[OB_low, OB_high]` = ilgili bar low/high.

**Mitigation (entry koşulu):**
- `t+1` ile `t+20` arasında fiyat OB range'ine geri döner.
- Tetik: bullish OB için low ≤ OB_high ve close > OB_low (kısmi mitigation OK, full sweep gereksiz). Simetrik short için.
- Entry: tetik barının **kapanışı doğrulandıktan sonraki barın açılışında market**.
- 20 bar içinde mitigation olmazsa setup expires.

**Stop & target:**
- SL: bullish için `min(OB_low, tetik_bar_low) − 0.5 × ATR(20)`; simetrik short.
- TP: 1.0R fixed (entry'den SL mesafesinin 1 katı, karşı yön). 1R seçimi pre-registered — sweep'le optimize EDİLMEYECEK.
- Max bar in trade: **10 bar**; aşılırsa time-exit market.

**Position sizing:**
- risk_pct = 0.005 (sembol başına %0.5 equity).
- Eşzamanlı maks pozisyon: 8.
- Sembol kategorisi başına maks 3 (BTC-correlated cluster overload önleme).

## 3. Gerekçe (RAG referansları)

- **[book_market_structure_order_flow §6 — RAG #6]**: SMC'de OB ve displacement leg kavramları. Crypto 1D'de "Orta" mekanik çalışabilirlik etiketi — displacement eşiği kalibrasyonu gerektirdiği vurgulanmış. **Bu kalibrasyon riski hipotezin curve-fit zayıflığıdır; ATR çarpanı 1.5'i pre-registration ile dondurarak in-sample optimization sızıntısını engelliyoruz.**
- **[book_candlestick_statistics — RAG #8]**: Bearish marubozu (gövde/range ≥ %90) continuation %64 oranla devam ediyor (Bulkowski). OB'nin displacement leg'i marubozu-benzeri davranış; istatistiksel temel kısmen burada. Ama ben body/range eşiğini %60'a indirdim (%90 çok kısıtlayıcı, N düşürür) — **bu indirme curve-fit kapısı, çünkü kanonik tanımdan saptırıyor; stop criteria bu eşiği zorlayacak.**
- **[book_lopez_summary — RAG #1]**: DSR, PBO, IS/OOS Sharpe oranı sertçe gate edilmeli. Parametre sayısı (displacement_atr_mult, body_ratio, OB_lookback, mitigation_window, sl_atr_buf, R_target = **6 serbest parametre**) / örnek sayısı oranı ≤ 1/30 olmalı → ≥ 180 trade gerekiyor (N_trades ≥ 200 hedefimiz bunu sınırda karşılıyor; bu **bilerek sıkışık marjin** — uyarı bayrağı).
- **[book_chan_summary — RAG #9]**: Yeni stratejinin portföye alınabilmesi için OOS Sharpe > 0.8 (single-asset) gate'i; ben tam bu eşiği koydum. Companion olduğu için aslında "marginal Sharpe" daha doğru metrik — Lab tournament'a teslim ederken bunu da rapor edeceğim.
- **[book_market_structure_order_flow — RAG #6]**: BOS/CHoCH/FVG/OB ailesi içinde OB'nin "Orta" sıralaması, alternatiflerden (BOS "Yüksek") düşüktür. Yani bu hipotez **a priori beklentim mütevazı**; iyimserliğin bias kaynağıdır.

## 4. Bağımlılıklar (depends_on derin gerekçe)

`2026-05-12-liquidity-sweep-displacement-fvg`'den **kasıtlı olarak farklılaşıyorum**:
- O hipotez sweep + displacement + FVG kombosu (3-faktör), single-bar trigger.
- Bu hipotez displacement + **last-opposite-bar mitigation** (2-faktör), multi-bar setup (1-20 bar gecikme).
- Mekanik örtüşmesi: displacement eşiği aynı (1.5 ATR). Eğer sweep+FVG hipotezi gate'i geçerse bu OB hipotezi onunla yüksek korelasyon riski taşır → Lab tournament'ta yan-yana corr testi zorunlu.

## 5. Dependent Variables (test edilecek metrikler)

| Variable | Pre-registered hedef | Sertlik |
|---|---|---|
| Net annualized return | ≥ %25 | hard floor |
| OOS Sharpe (12-dilim ortalama) | ≥ 0.8 | hard floor |
| MaxDD (equity bazlı) | ≤ %25 | hard ceiling |
| Profit factor | ≥ 1.30 | hard floor |
| N_trades (3y, universe) | ≥ 200 | hard floor (düşük-N reddi) |
| ρ(daily PnL, vsa_climax_test) | \|ρ\| ≤ 0.25 | **birincil — yokluğunda diğer metrikler önemsiz** |
| Win rate | rapor edilir, gate yok | info |
| IS/OOS Sharpe oranı | ≤ 1.8 | hard ceiling (López-Prado) |
| DSR (Bailey-Lopez) | p ≥ 0.05 (anlamlı) | hard floor |
| Shuffle baseline p-value | < 0.05 | hard floor |

## 6. Independent Variables (optimize EDİLMEYECEK — sabit)

- `displacement_atr_mult` = 1.5 (donmuş)
- `body_ratio_min` = 0.60 (donmuş; %90 marubozu varyantı stop criteria'da test edilebilir ama bu hipotezin reddi/kabulü 0.60 üzerinden)
- `OB_lookback` = 5 bar (donmuş)
- `mitigation_window` = 20 bar (donmuş)
- `sl_atr_buf` = 0.5 (donmuş)
- `R_target` = 1.0 (donmuş)

**Curve-fit guard:** Walk-forward'da bu parametreler optimize EDİLMEZ. Optuna sadece evren-seçimi (universe filtresi) ve risk_pct dolayı için kullanılabilir — entry mekaniği donmuş.

## 7. Beklenen p-value ve Çoklu-Test Düzeltmesi

- Single-hypothesis test: shuffle baseline'a karşı p < **0.01**.
- Bu hipotez **15. cross-strategy companion** (önceki 14 vsa_climax companion'ı sayılır) → Bonferroni-düzeltilmiş eşik α = 0.05/15 ≈ **0.0033**.
- Shuffle baseline p ≥ 0.0033 ise düzeltme-sonrası anlamlı değil → RED.
- Benjamini-Hochberg FDR alternatifi rapor edilir; ikisinden biri kırmızıysa RED.

## 8. Null Hipotezi (ne olursa çürür)

- N_trades < 200 → istatistik zayıf, RED.
- |ρ(vsa_climax_test)| > 0.25 → companion mantığı çöker, edge varsa bile bu hipotez **bu seed için** RED. (Bağımsız strateji olarak ayrı pre-registration gerekir.)
- IS Sharpe / OOS Sharpe > 1.8 → López-Prado overfit kırmızı bayrak.
- Walk-forward 12 diliminden ≤ 6 dilim pozitif → reject (≥ 8/12 isteniyor).
- Bull/bear/range rejimden en az 2'sinde net pozitif değilse RED.
- 2022-05 LUNA / 2022-11 FTX / 2024-08 Yen carry stres dilimlerinde herhangi birinde dilim-MaxDD > %15 → RED (tail-risk red flag).
- Param perturb (her parametre ±%10, 50 seed) ortalama Sharpe kaybı > %25 → RED (kırılgan optimum).

## 9. Stop Criteria (araştırmayı erken kes)

- **IS Sharpe < 0.5** → araştırma terkedilir, OOS'a geçilmez.
- **N_trades (full sample) < 100** → "edge yok / çok seyrek" diyerek bırakılır.
- 3 walk-forward dilimi üst üste negatif → kalan dilimlere geçmeden RED.
- **Curve-fit kırmızı bayrak:** Eğer in-sample'da best body_ratio_min veya displacement_atr_mult parametre uzayının uç değerinde çıkarsa (ki bu hipotezde optimize edilmiyor; ama post-hoc sensitivity check'te uç değer baskınsa) → RED + arşiv.

## 10. Curve-Fit Şüpheleri (kendi-kritik)

1. **Displacement eşiği 1.5 ATR**: Mevcut `2026-05-12-liquidity-sweep-displacement-fvg` hipotezinde aynı eşik kullanılmış. Bu **veri-bilinçli seçim**; tek-projeye-spesifik conformity tehlikesi. Mitigasyon: post-hoc 1.0 / 1.5 / 2.0 ATR sweep sensitivity (sadece rapor için, kabul/red 1.5 üzerinden).
2. **Body ratio 0.60**: Bulkowski marubozu kanonik tanımı 0.90; benim 0.60'a indirgemem N için. Gevşeklik = curve-fit kapısı. Mitigasyon: 0.90 varyantı ayrı backtest, eğer Sharpe karşılaştırması anlamlı farklı değilse OK; çok farklıysa "eşik kaymasıyla beslenen edge" şüphesi.
3. **Mitigation window 20 bar**: Geniş pencere → seyrek setup'ları yakalar ama "ne kadar bekleriz" tartışmalı. 1D'de 20 bar = ~3 hafta; düşük frekanslı strateji. Sensitivity 10 / 20 / 40 bar rapor.
4. **6 serbest parametre / 200 trade marjini ince**: López-Prado 1/30 oranı tam sınırda. N < 180 ise hipotez parametre-yoğunluğu testini geçemez.
5. **vsa_climax companion ailesinin 15. hipotezi**: Her companion hipotezi vsa ile düşük korelasyon arıyor; tekrar denemeler **selection bias** üretebilir — sonunda biri tesadüfen düşük korelasyonlu görünür. Bonferroni n=15 düzeltmesi bunu cezalandırır.

## 11. Plan (kod öncesi commit)

1. Bu doc commit → git hash dondurma.
2. Pattern detector'ı `signal_chief`'e teslim et (lookahead causality test zorunlu).
3. `backtest/engine.py` çalıştır (vectorbt, 3y, all_liquid universe, fees + slip).
4. Lookahead causality test (`detector(df[:t+1])[t] == detector(df)[t]`) — başarısızsa ANINDA RED, sayılara bakma.
5. Walk-forward 12 dilim, robustness suite TAMAMI (SOP-3).
6. ρ(daily PnL, vsa_climax_test 3y daily PnL series) Spearman + Pearson.
7. Bonferroni + BH-FDR düzeltmesi (n=15).
8. Karar yaz: terfi adayı / iterate (SOP-4b) / red.

## 12. Iterate Patikası (eğer pozitif edge + risk kötü)

SOP-4b uyarınca: ROI > 0 ama DD > %25 veya |ρ| > 0.25 çıkarsa **REDDETMEM**, v2 yazarım:
- v2-risk-cut: risk_pct 0.005 → 0.002, max_concurrent 8 → 4.
- v3-symbol-prune: ρ-yüksek sembolleri evrenden çıkar (BTC-correlated cluster shrink).
- v4-regime: ADX > 20 filtresi (trend-only); range rejimde tetiklenme yok.
- v5-be-protect: 0.5R sonrası SL → entry, time-exit 5 bar.

Iterate budget: maks 5 versiyon. Sonra "deferred" veya arşiv.

## 13. Karar Sonrası Output Hedefi

- Reddedilirse → `learning.md`'ye 3 satırlık özet (hangi gate kırıldı + ders).
- Geçerse → `configs/strategies/<name>.yaml` taslak (insan onayı zorunlu) + Lab tournament için manifest.
- Her durumda `reports/research/2026-06-23-order-block-mitigation-vsa-companion.html` raporu.

---

**Self-assessment (researcher persona, dürüstlük şartı):**
A priori bu hipoteze **düşük güven** veriyorum. Sebepleri: (i) 14 önceki companion'ın çoğu abort/red oldu — base rate düşük; (ii) OB'nin RAG'da "Orta" sıralanması; (iii) body_ratio 0.60'a indirgeme curve-fit kapısı; (iv) parametre-yoğunluğu/N marjini ince. En olası sonuç: shuffle baseline'ı geçer ama Bonferroni n=15 ile anlamlılığı kaybeder veya ρ > 0.25 çıkar. Yine de hipotezi düşürmeden test etmek gerekiyor çünkü companion arayışı sürüyor ve OB rafta açık duran nadir mekanik.
