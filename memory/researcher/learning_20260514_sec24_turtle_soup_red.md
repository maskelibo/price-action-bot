# Learning — SEC24 Turtle Soup 20D Failed Breakout Fade: RED

**Tarih:** 2026-05-14
**Sprint:** SEC24 Researcher (PA mastery gap + mean-rev class pre-build)
**Hipotez:** [HYP-2026-05-14-TURTLE-SOUP-V2](hypotheses/2026-05-14-turtle-soup-20day-failed-breakout-v2.md)
**Karar:** **HARD RED (standalone) — kalıcı archive aday**

---

## TL;DR

Raschke/Connors "Street Smarts" 1996 Turtle Soup pattern'i (yeni 20D high/low ama
kapanış prior range içine reclaim + body rejection) crypto 1d × 11 sym × 5y'de
**edge taşımıyor.** Default config standalone gate FAIL, 18-config parametre grid
sweep'in HİÇBİR config'i naive p<0.05 gate'ini geçmedi (en iyi p=0.103).

| Gate | Default | Best (lb=15/body=0.50) |
|---|---:|---:|
| n ≥ 200 | 475 ✓ | 177 ✗ |
| mR ≥ +0.10 | +0.026 ✗ | +0.131 ✓ |
| WR ≥ 45% | 46.5% ✓ | 48.0% ✓ |
| p_shuffle < 0.05 | 0.318 ✗ | 0.103 ✗ |
| max_R < 10 | 4.82 ✓ | -- |
| per-sym pos ≥ 6 | 6/11 ✓ | -- |
| symout dev < 30% | **79.5%** ✗ | -- |
| Bonferroni p < 0.00278 | -- | 0/18 |

---

## Doğrulanmış Bulgular

### 1. Yapısal Orthogonality Hipotezi ✓ DOĞRULANDI

Pre-registered iddiada Turtle Soup'un `donchian_breakout` ve `failed_bo_bos_reclaim`
ile uncorrelated trigger zamanları olacağı tahmini doğrulandı:

| Strategy | n_my (TS) | n_other | overlap | Jaccard |
|---|---:|---:|---:|---:|
| donchian_breakout | 475 | 233 | **0** | **0.000** |
| failed_bo_bos_reclaim | 475 | 325 | 11 | 0.014 |
| equal_highs_sweep | 475 | 278 | 22 | 0.030 |

**Yorum:** Donchian breakout overlap=0 = Turtle Soup yapısal olarak donchian
sinyalinin **tam tersi gün** tetikleniyor. Bu pre-reg counter-hypothesis #2
(equal_highs_sweep correlation > 0.7 ile pure overlap) hipotezini DA reddediyor;
Jaccard 0.030 << 0.5. ORTHOGONALITY KANITLANDI ama EDGE YOK — bu kombinasyon
"yapısal eksik" değil "yapısal var ama anlamsız" durumu.

### 2. Asymmetric edge BULUNAMADI

Pre-registered counter-hypothesis #4 (bull market'te long-fade kaybeder, bear
market'te short-fade kazanır → asymmetric edge production'a tek yönlü variant)
sınandı:

| Side | n | mR | p |
|---|---:|---:|---:|
| short | 275 | +0.074 | 0.170 |
| long | 200 | -0.039 | -- |
| Combined | 475 | +0.026 | 0.318 |

Short-only mR=+0.074 default config'de, AMA p=0.170 gate-ten 3.4x uzak. Best
short-only (lb=15/body=0.50): n=107, mR=+0.093, p=0.238 — n threshold altında AND
p uzak. **Asymmetric edge YOK** (var olsaydı short tarafta p<0.10 + n≥200 birlikte
olurdu).

İlginç: **Long-side mR DAHA YÜKSEK** lb=15/body=0.50 config'de (+0.189 vs short
+0.093). Bu pre-reg counter-hipoteziyle TERS — long fade crypto bull bias'a karşı
çalışmıyor olmalıydı. Açıklama: Body 0.50 filter sadece "kaliteli failure
candle" yakalıyor (small body değil — STRONG rejection wick); bu candle tipi
**hem long hem short tarafta** kalite çıkarıyor ama n düşürüyor.

### 3. Regime split: bear/range yıllar pozitif, bull yıllar negatif

| Yıl | n | mR | Regime |
|---|---:|---:|---|
| 2021 | 54 | -0.356 | bull (BTC ATH) |
| 2022 | 120 | +0.095 | bear (LUNA/FTX) |
| 2023 | 101 | +0.049 | range |
| 2024 | 85 | -0.002 | bull (BTC ATH) |
| 2025 | 86 | +0.266 | mixed |
| 2026 | 29 | -0.250 | data partial, bull |

3/6 yıl pozitif. Crypto bull regime'inde failed-breakout candle'lar GERÇEK
"fakeout sonrası continuation" oluyor (fade kaybeder). Bear/range regime'inde
fade çalışıyor. **Regime-conditional variant** sonraki sprint için yapısal sebep
ama pre-registered hipotez direct standalone edge — RED ana karar.

---

## Pre-Registered Counter-Hypotheses Sonuçları

1. **Donchian edge bittiyse Turtle Soup da bitmiş olabilir.** Donchian breakout
   2024-2025'te muhtemelen zayıflamış (sec22 mean-rev ve sec23 OOS bulguları).
   Turtle Soup bunun yapısal inverse'i ama HER İKİSİ de aynı zamanda zayıflamış
   olabilir — yapısal SR aşımı = noisy event genelinde. **Counter-hyp 1
   muhtemelen doğru ama bu gözlem ile doğrudan kanıtlanamadı** (donchian OOS
   karşılaştırması scope dışı).
2. **equal_highs_sweep overlap > 0.7** — DOĞRULANMADI (Jaccard 0.030).
3. **Crypto'da failed-breakout = continuation, fade kaybeder** — KISMEN
   DOĞRULANDI (bull yıllar negatif mR, bear yıllar pozitif).
4. **Asymmetric edge** — REDLEDİLDİ (short-only zayıf pozitif AMA gate altı).

---

## Hangi Bias'a Düşmedim

- **Pre-registration sayesinde** "best Top 5 by mR" tablosunu görünce
  "lb=15/body=0.50 PASS!" demek yerine Bonferroni alpha=0.00278'e bakıp
  0 / 18 sonucunu kabul ettim.
- **Symbol-out CV %79.5 dev** ETH+BNB tek-tek konsantrasyon — bu olmasaydı
  default mR=+0.026 marjinal pozitif yorumlanırdı. CV gate yapısal cherry-pick
  guard'ı.
- **Asymmetric edge çekiciliği** — short mR=+0.074 default'ta görünce
  "production'a short-only çıkar!" demek yerine p_shuffle=0.170 + n=275 düşük
  edge size kombinasyonu RED.

## Hangi Bias'a Düştüm

- **Bayesian prior overestimation:** Bayesian prior bölümünde "PASS-CANDIDATE
  yüksek ihtimal" yazmıştım, dayanak: "klasik 30 yıl, mekanik temiz". Bu
  **literatür-kaynaklı autorite bias'ı** — Raschke/Connors orijinal evren US
  equities/FX 1990s, crypto 24/7 + perp leverage + low-liquidity Sunday cycle
  TAMAMEN farklı microstructure. **Crypto-uyumsuz pattern**'ler için "klasik
  edge" argümanı düşük güvenilir. **Ders:** literatür kaynaklı autorite bias'ı
  Bayesian prior'a ENBÜYÜK +%30 prior weight ile koymak gerek (max), gerisini
  veri belirler.

---

## Bir Dahaki Sefer

1. **Asset-specific PA pattern envanteri:** "klasik 30 yıl edge" iddiası
   crypto'da geçmiyorsa, pattern crypto microstructure (24/7 trade, perp
   leverage cascade, low-Sunday-liquidity Monday spike) için **uyumsuz**
   olabilir. Sonraki sprintte "stocks/FX'te çalışan ama crypto'da test
   edilmemiş pattern" listesi sırasını **literatür-kaynaklı priorden** indirip
   "crypto-spesifik mekanik" pattern'leri yukarı çekmeli (örn. perpetual basis
   convergence fade, funding cascade fade — bunlar zaten alt_data class'ta var
   ama mean_rev class'a price-action versiyonları üretilebilir).
2. **Regime-conditional variant**: Turtle Soup 2022 bear ve 2025 mixed
   regime'de pozitif mR gösteriyor. **Regime overlay** (BTC.D rising / vol-z
   high / 90-d capitulation flag) ile conditional gate uygulansa standalone'da
   PASS olabilir. Ama bu **yeni hipotez** — SEC24 scope dışı. Backlog.
3. **Pure-orthogonality bilgisi de değerli:** Edge YOK ama trigger uncorrelated.
   Bu strateji ortagonal güvenilir benchmark olarak kullanılabilir (örn.
   "trigger zamanları rastgele" baseline'da random-strategy yerine Turtle Soup
   olabilir). Yapısal kullanım scope dışı, not olarak ekliyorum.

---

## Karar

**RED — kalıcı archive aday.**

Sebepler:
1. Standalone 7-gate'ten 3'ü FAIL (mR, p, symout)
2. 18-config grid Bonferroni alpha=0.00278: 0 / 18 PASS
3. Asymmetric edge hipotezi reddedildi
4. Orthogonality kanıtlandı AMA edge yokken bu izole bilgi production aday
   yapmıyor

**ENGINEERING SEC21 KOORDİNASYON:**
```yaml
# configs/strategy_taxonomy.yaml (gelecek update)
mean_reversion:
  # ...mevcut listе...
  # turtle_soup_20d    # SEC24 RED standalone, archive
disabled:
  # ...mevcut listе...
  - turtle_soup_20d   # SEC24 standalone n=475 mR+0.026 p=0.318 — crypto-uyumsuz
```

**Strategy file silinmez** (regression koruma + ortagonal benchmark olarak
yapısal kullanım potansiyeli). Manifest disable flag ile production'a
girmesi engellenir.

---

## Reproducibility

- Strategy: `src/price_action/strategies/turtle_soup_20d.py`
- Standalone script: `scripts/sec24_turtle_soup_standalone.py`
- Drill script: `scripts/sec24_turtle_soup_drill.py`
- JSON outputs:
  - `reports/researcher/sec24_turtle_soup_standalone.json`
  - `reports/researcher/sec24_turtle_soup_drill.json`
- Trades pickle: `reports/researcher/sec24_turtle_soup_trades.pkl`
- Pre-reg: `memory/researcher/hypotheses/2026-05-14-turtle-soup-20day-failed-breakout-v2.md`
- Seed: 42 (numpy default_rng)
- n_perm: 2000 (standalone), 1000 (drill)
- Git ref: SEC24 branch / main

---

## Sources

- [Raschke & Connors — Street Smarts (1996), Turtle Soup chapter](https://www.amazon.com/Street-Smarts-Surviving-Strategies-Markets/dp/0965046109)
- [Linda Raschke — Turtle Soup Original (Traders Mastermind)](https://tradersmastermind.com/turtle-soup-trading-strategy-rules/)
- [New Trader U — Turtle Soup Rules](https://www.newtraderu.com/2021/06/05/the-turtle-soup-stock-trading-strategy/)
- SEC22 mean-rev pre-build: `reports/researcher/2026-05-14_sec22_summary.md`
- SEC23 OOS validation paradigm: `reports/researcher/2026-05-14_sec23_rsi2_oos_validation.md`
- PA mastery gap: `reports/researcher/2026-05-14_pa_mastery_gap.md`
