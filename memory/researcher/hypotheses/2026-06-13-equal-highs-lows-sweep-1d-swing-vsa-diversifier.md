---
doc_id: researcher-20260613T150000-equal-highs-lows-sweep-1d-swing-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-13T15:00:00Z
status: DRAFT
confidence: med
depends_on:
  - lab_scientist-active-vsa_climax_test
  - researcher-20260611-equal-highs-sweep-15m-pre-existing
  - shared/facts/exchange_behaviors
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross-strategy, low-correlation, equal-highs-sweep, smc, 1d, swing, pre-registration]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-13-EQH-SWEEP-1D-VSA-DIVERSIFIER

- **Tarih:** 2026-06-13
- **Versiyon:** 0.1 (pre-registration — kod yazılmadan önce)
- **Seed:** Cross-strategy edge keşfi — aktif `vsa_climax_test`'e (15m, climax-fade) düşük korelasyonlu ek strateji adayı (raftaki 66'dan).
- **Aday seçimi gerekçesi:** Bugünkü hipotez kuyruğu (order-block 4H, OB 4H, rising-three D1, volman-ii D1, kaufman-atr 1D, choch-1D, turtle-channel 1D, kaufman-rsi-div 15m) bu sabah yazıldı. **Equal-Highs/Lows Sweep mekaniği zaten 15m'de pre-register edildi (2026-06-11)** — fakat o intraday stop-hunt frekansı için. **1D swing-scale versiyonu pre-register edilmemiş** — aynı stop-hunt mekaniği farklı zaman ölçeğinde tamamen farklı bir dağılım üretir (intraday ortalama tutma <2h vs swing ortalama tutma 4-8 gün). Bu **TF-orthogonal** ve mekanizmaca **vsa_climax_test'in volume-exhaustion fade'inden ayrı** (structural liquidity raid + close-back-inside reclaim ≠ volume climax fade).

## 1. İddia (sayısal, ölçülebilir)

> **Universe:** `principal_pool_v11` 19 sembol perp (USDT-M).
> **Periyot:** 2022-01-01 → 2025-12-31 (in-sample 2022-01-01 → 2024-12-31, OOS 2025-01-01 → 2025-12-31).
> **Setup:** 1D bar üzerinde **Bearish liquidity sweep + reclaim short**:
>   1. **Sweep tespiti:** `high[t-1] > max(high[t-11 .. t-2]) + 0.5 × ATR(14)[t-2]` — t-1 günü son 10 günün en yüksek seviyesini yarım ATR'den fazla aşıyor.
>   2. **Reclaim koşulu:** `close[t-1] < max(high[t-11 .. t-2])` — kapanış swept seviyenin GERİ ALTINA dönüyor (likidite alımı sonrası reklaim).
>   3. **Trigger:** sonraki bar (= bar `t`) **open**'ında market short.
>   4. **SL:** `high[t-1] + 0.25 × ATR(14)[t-1]` (sweep extremum'unun hemen üstü).
>   5. **TP:** 2R fixed (BE-protect 1R'de etkin).
>   6. **Bullish symmetric:** `low[t-1] < min(low[t-11 .. t-2]) − 0.5 × ATR` ve `close[t-1] > min(low[t-11 .. t-2])` → bar `t` open long.
>   7. Fee 7.5 bps taker, slippage 5 bps.
>   8. Risk per trade: 0.5% (sabit-fraksiyon, compounding YOK — RESUME-2026-06-10 dersi).
>
> **Aşağıdaki TÜM gate'ler eşzamanlı sağlandığında hipotez DOĞRULANIR:**
>
> | Metric | Hedef | Notu |
> |---|---|---|
> | OOS annualized net return | **≥ 10%** (sabit-fraksiyon) | Diversifier rolü — fair-base, %25/ay iddia YOK |
> | OOS Sharpe (annual.) | **≥ 0.7** | Single-asset eşik (Chan, RAG #9) |
> | OOS MaxDD | **≤ 22%** | Sermaye koruma > getiri |
> | OOS Profit Factor | **≥ 1.3** | — |
> | OOS Trade count (IS + OOS toplam) | **≥ 150** | 1D × 19 sym düşük frekans gerçekçi tavan |
> | IS/OOS Sharpe oranı | **≤ 1.8** | Lopez "IS > 3×OOS → red" |
> | Shuffle baseline (returns reshuffle, 500 sim) | **p < 0.01** | Bonferroni dahil |
> | **Jaccard overlap with vsa_climax_test signals (1d bar = ±1 day tolerans, aynı sym)** | **< 0.05** | TF farkı nedeniyle çok düşük beklenir |
> | **Daily-returns Pearson \|r\| with vsa_climax_test** | **< 0.20** | Portföy diversifier kriteri |
> | Walk-forward (8 dilim, 30m train / 6m test, step 6m) | **≥ 6/8 dilim pozitif** + dilim Sharpe std < ortalama | RAG #1 madde 6 |
> | Symbol-out CV (leave-one-symbol-out × 19) | **min sym OOS Sharpe ≥ 0.2** | Tek sembole bağımlı değil |
> | Regime split (bull / bear / range) | **en az 2/3'te pozitif** | Tek rejimden beslenmiyor |
> | Stress periyotları (2022-05 LUNA, 2022-11 FTX, 2024-03 ATH, 2024-08 Yen) | **dilim başına DD ≤ 15%** | Yıkıcı kayıp yok |
> | Lookahead-delay test (entry +1 bar = +1D gecikme) | **edge'in ≥ %70'i korunur** | Sızıntı yok; reclaim sinyali günlük close'a bağlı, sıkı test |

## 2. Null hipotez (çürütme şartı)

H₀: 1D Equal-Highs/Lows Sweep + reclaim strateji 19-sym kripto perp evreninde **vsa_climax_test'ten istatistiksel olarak ayırt edilebilir bağımsız edge üretmez**.

H₀ kabul kriterleri (en az biri yeterli → hipotez RED):
- OOS Sharpe < 0.4 (eşik altı edge).
- Shuffle baseline yenilemiyor (p ≥ 0.05).
- Jaccard ≥ 0.10 VEYA |Pearson r| ≥ 0.30 → orthogonality kaybı, "yeni edge" değil.
- Trade N < 100 (1D × 19 sym × ~3.5y → istatistik altı güç).
- IS/OOS Sharpe oranı > 2.5 → overfit kuvvetli sinyal.
- WF dilim varyansı ortalamadan büyük (Lopez de Prado kriteri).
- Lookahead-delay test edge'in > %50'sini yiyor → günlük close-bağımlı sinyal çürük.

## 3. Bağımlı değişkenler (önceden listelendi — p-hack engeli)

Birincil:
1. OOS annualized net return (compounding-bağımsız sabit-fraksiyon)
2. OOS Sharpe (annualized; √252 day, daily-equity vary.)
3. OOS MaxDD (% of starting equity, bar-close bazlı)
4. **Orthogonality: Jaccard(±1 day overlap) + Pearson(daily returns)**

İkincil (raporda görünür ama gate değil):
- Avg R, profit factor, win rate, expectancy, max drawdown duration (gün), avg holding period (bar).
- Per-symbol Sharpe matrix.
- Per-regime decomposition.
- Long vs short edge split (asimetrik mi?).

**İlave metrik EKLENMEYECEK** sonradan (bilinçli p-hack engeli — RAG #1 Lopez de Prado).

## 4. Bağımsız değişkenler — TÜMÜ DONDURULDU (curve-fit guard)

Bu hipotez **TEK-SET pre-registration**. Hiçbir parametre optimize edilmeyecek, sweep çalıştırılmayacak:

| Parametre | Değer | Kaynak |
|---|---|---|
| TF | 1D | Vsa 15m'ye TF-orthogonal (sabit) |
| lookback_n | **10 bar** | Klasik 10-day swing horizon (Donchian-akrabası); TEK değer |
| sweep_threshold | **0.5 × ATR(14)** | Wick > yarım ATR = mikroyapısal stop-hunt; TEK değer |
| reclaim koşulu | close back inside swept seviye | Boolean — parametre değil |
| Entry | bar `t` market open | Sabit |
| SL | swept extremum + 0.25 × ATR(14)[t-1] | Sabit, dar SL = stop-hunt edge mantığı |
| TP | 2R fixed | Sabit |
| BE-protect | 1R'de SL → entry | Sabit (mevcut altyapı) |
| risk_pct | 0.5% / trade | shared/lessons fixed |
| Universe | principal_pool_v11 (19 sym) | Sabit |
| Fee model | 7.5 bps taker + 5 bps slippage | Sabit, konservatif |
| Long+short symmetric | Aynı kurallar mirror | Sabit |

**Toplam free parameter sweep'i: 0.** Lopez de Prado (RAG #1) "param/sample ratio < 1/30" kuralı için 0/150 = 0 ✓.

## 5. Beklenen p-value ve multiple-testing bütçesi

- Beklenen shuffle-baseline p: **< 0.005** (tek pre-registered test → Bonferroni çarpanı n=1).
- WF 8 dilim parça testi: FDR (BH) düzeltilmiş anlamlılık ≥ 6 dilimde p < 0.05.
- Orthogonality testi (Jaccard < 0.05 + |r| < 0.20): nominal değil, **hard cut-off** (anlamlılık değil eşik).
- **15m sweep edge'i ile aynı evren testi yapılmıyor** — bunlar bağımsız hipotezler, paylaşılan parametre yok.

## 6. Gerekçe (RAG referansları)

- **[RAG #6 — Market Structure & Order Flow]:** "Equal Highs/Lows Sweep | Yüksek workability | Stop-hunt mekaniği crypto'da güçlü; H-2." Mekaniğin RAG validasyonu açık; eklenen yenilik 1D swing-scale + reclaim sıkı tanımı.
- **[RAG #1 — Lopez de Prado]:** Pre-registration disiplin + TEK-SET tasarım. 6 kırmızı bayrak kontrolü zorunlu. Param/sample = 0/150 ✓.
- **[RAG #7 — Donchian channel (Kaufman)]:** "20-bar high/low kırılımı, ADX > 25 trending."  Bizim hipotez **ters yönde** — kırılım yapan AMA reclaim eden bar (yani Donchian'ın FALSE BREAKOUT'u). Donchian'in failure pattern'i bizim entry'miz.
- **[RAG #9 — Chan summary]:** Single-asset eşik OOS Sharpe > 0.8 (biz 0.7'ye gevşettik çünkü diversifier rolü — portfolio etki ölçülecek).
- **[Brooks 2012, RAG #3 — climactic reversal]:** "n-bar high/low aşımı + geri dönüş mekanik, kodlanabilir. En iyi hipotez adayları." Brooks zaten benzer mekaniğe puan vermiş.
- **vsa_climax_test (mevcut canlı):** 15m, volume + spread climax fade. Bizim TF 1D, mekanizma structural liquidity raid + reclaim → **çift-orthogonal** beklenir.

## 7. Curve-fit kırmızı bayrakları — ÖN-KONTROL

| Bayrak | Riskimiz | Mitigation |
|---|---|---|
| Best param ekstrem değerde | **Yok** — sweep yok, tek set | ✓ |
| IS/OOS gap > 50% | Beklenir bir risk | Gate 1.8x = %44 |
| Çok ince param uzayı | Yok (0 free parameter) | ✓ |
| Trade N düşük | **EN BÜYÜK RİSK** — 1D + n=10 lookback + sweep+reclaim çift-koşul nadir olabilir | Stop crit. < 100 → erken RED |
| Tek periyot baskın katkı | Bilinmiyor; LUNA short-edge cazip ama kontrol edilecek | WF + stress periyotları zorunlu |
| WF dilim varyansı | Bilinmiyor | Lopez kriteri zorunlu |
| Bonferroni kaybı | n=1 → minimal | ✓ |
| "Hikaye çok mantıklı" bias | SMC/ICT topluluk anlatısı çekici — dikkat | Sayı kazanır; story ignored |
| **Long-short asimetri masking** | Kripto'da bull-bias → short-side edge tüm getiriyi taşıyabilir | Long+short ayrı raporlanacak; her ikisi de ≥0 PF gerekir |
| **Reclaim eşiğinin keskin sınırı** | "close < max(high)" hard boolean — close max'a tam eşitse rastgele class | ε-toleransla "close < max - 1e-9" sabit kuralı |

## 8. Stop criteria (araştırma terkedilir)

Aşağıdakilerden **HERHANGI BİRİ** gerçekleşirse hipotez derhal RED + arşiv:
1. IS dönemi (2022-2024) Sharpe < 0.4 → erken kapatma, OOS bile çalıştırılmaz.
2. IS trade N < 100 (1D × 19 sym × düşük frekans gerçeği) → istatistik gücü yetersiz, deploy mantıksız.
3. Lookahead-delay test (entry +1 bar = +1D gecikme) edge'in > %50'sini yer → günlük close-bağımlı sinyal çürük.
4. Bonferroni-sonrası shuffle p > 0.05 → şans.
5. Jaccard with vsa_climax ≥ 0.10 VEYA Pearson |r| ≥ 0.30 → orthogonality yok, "diversifier" iddia çürür.
6. WF 8 dilimden < 4'ü pozitif → kararsız.
7. **Long-only PF veya Short-only PF < 1.0 → asimetri masking, edge sahte.**

**Eğer 1-7 koşullarından sadece DD veya bir tek risk metriği bozulmuşsa (ROI pozitif ama tek metrik kırmızı) → SOP-4b iterate (RED YASAK).**

## 9. İterate patikası (önceden tanımlı — pozitif edge bulunursa)

ROI pozitif + bir risk metriği gate'i geçemezse:
- **v2 risk-reduction:** risk_pct 0.5% → 0.3%, max_concurrent 8→4.
- **v3 confluence filter:** sweep_threshold 0.5×ATR → 0.8×ATR (sadece güçlü sweep'ler — daha az trade, daha temiz reclaim).
- **v4 regime gate:** sadece bull veya sadece bear rejim subset.
- **v5 HTF filter:** sadece 1W EMA50'nin DOĞRU yönünde olan sweep'ler (counter-trend reclaim safer).
- **v6 short-only veya long-only:** asimetri tespit edilirse zayıf tarafı kapat.

Maks 6 iterate. Sonra ya Lab tournament ya "deferred archive".

## 10. Beklenen iş yükü ve teslim

- Detector implementation: ~30 satır vectorized (`pandas.rolling().max()` + sweep boolean + reclaim boolean).
- Backtest config: `configs/strategies/equal_highs_sweep_1d_v1.yaml` (draft — sadece Lab kabul ederse insan onayına).
- Backtest run: ~3 dk (1D × 19 sym × 4y).
- Robustness suite: ~25 dk (WF + symbol-out + stress).
- Lookahead-delay test: ek 5 dk.
- **Toplam:** ~40 dk compute, ~2 saat human review.
- Çıktı: `reports/research/equal_highs_sweep_1d_v1-2026-06-XX.html`.

## 11. Dürüstlük şerhleri (Researcher self-doubt)

1. **15m versiyon zaten pre-register edildi.** Mekanik aynı; sadece TF farklı. Riski: aynı edge'in iki TF'de tetiklenmesi olabilir; bu durumda 1D versiyon "ek edge" değil "rescaled aynı edge"dir. Jaccard ve Pearson testleri bunu yakalar; **şüphe vakası olarak işaretliyorum**.
2. **1D + sweep+reclaim çift-koşul nadir.** Trade N düşük çıkma olasılığı yüksek; bu yüzden gate'i ≥150 değil ≥100'e indirdim ve stop crit. <100'de erken kestim. Bu **risk yönetimi değil, ön-bilgi kabulü** — geriye dönük rasyonalizasyon değil.
3. **Reclaim eşiğinin "close < max(high)" tanımı keskin sınır.** Close swept seviyenin ε kadar üstünde kapanırsa "sweep yok" sayılır — bu bilgi kaybı. Pre-reg'de kabul ediyorum, sweep_threshold'u esnetmedim çünkü sweep'in başarısız (= follow-through) olduğu vakaları edge'e dahil etmek istemiyorum.
4. **Bull-bias asimetri masking.** Kripto 2022-2025 evreninde bull baskın olduğu için short-side edge gerçeklikten fazla pozitif çıkabilir. Long-PF & Short-PF ayrı raporlanacak; ikisinde de ≥1.0 olmazsa edge sahte sayılır.
5. **vsa_climax_test ile mekanizma örtüşmesi.** vsa_climax fade'i "volume spike sonrası reversal" — sweep+reclaim "liquidity raid sonrası reversal". Her ikisi de "reversal" ailesinde. Yapısal orthogonality TF üzerinden umut ediliyor, ama mekanizma ailesi aynı. **Korelasyon gate'i geçilmezse en muhtemel red sebebi budur.**

---

**Hipotez DONDURULDU.** Bu doc'un commit'i sonrası hiçbir parametre, gate veya stop criterion değiştirilemez. Değişiklik gerekirse: yeni doc + `supersedes` linki + eski doc REJECTED.

**Sonraki adım:** Lab + Risk Officer review → onay sonrası backtest engine'e config yazılabilir.
