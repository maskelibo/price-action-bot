---
doc_id: researcher-20260604T093000-time-of-day-session-bias-15m
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T09:30:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260509-day-of-week-effects   # prior 1D DOW (REJECTED, trivially null on HOD)
  - widestop-threshold-validated              # 15m sl_pct_min fee shield
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [time_of_day, session_bias, calendar_filter, 15m, curve_fit_suspect, low_confidence]
supersedes: null
hash: null
hypothesis_id: HYP-2026-06-04-tod-session-bias-15m
strategy_class: calendar_filter
strategy_name: vsa_widestop_15m (parasitic filter on existing champion pool)
---

# Hipotez: 15m VSA-WIDESTOP havuzunda Time-of-Day (UTC saat) edge konsantrasyonu

> **Up-front curve-fit uyarısı:** 24 saat × 7 gün = 168 hücrelik bir parametre uzayı.
> Multiple-testing düzeltmesi olmadan en az 8 hücre saf şansla p<0.05 verir. Bu hipotez
> büyük olasılıkla **REJECT** ile sonuçlanacak; pre-registration'ın asıl amacı, "test ettik
> ama yok" sonucunu arşive geçirmek ve gelecekteki tekrar denemelerini önlemektir
> (bkz. `learning.md` "Reddedilen hipotezi 6 ay tekrar denemek p-hacking'tir").

---

## 1. İddia (Pre-Registration)

15m timeframe'de, son **3 yıllık** (2023-06-01 → 2026-05-31) tüm aktif perp evreninde
(`liquid_perp_15`, ~15 sembol), **VSA-WIDESTOP** havuz çıktısı (sec53_*_pool_v11_*.pkl)
üzerinde, entry zamanının UTC **saatine** ve **gününe** göre koşullu edge analizinde:

- **H1 (primary):** Hiçbir UTC saati (24 hücre), `mean_R` cinsinden, **shuffle baseline**'i
  Bonferroni-corrected α = 0.05/24 = **0.00208** anlamlılığında geçemez.
- **H2 (primary):** Hiçbir (day-of-week × session) hücresi (7×4 = 28 hücre), Bonferroni
  α = 0.05/28 = **0.00179** anlamlılığında shuffle null'u geçemez.
- **H3 (alt):** Eğer en az 1 saat geçerse (H1 ihlal), o saatin **per-yıl** sign-consistency'si
  (6 yıllık dilim, en az 4'ünde pozitif) eşiğini geçemez → curve-fit verdict.

**Karşı-iddia (H_alt):** En az 1 saat aralığı (örn. **13-15 UTC = US session açılışı**) hem
Bonferroni-corrected p<0.00208 **VE** per-yıl en az 4/6 yıl pozitif mean_R sergiler.
Bu durumda **DEFER** (filtre olarak değil, izleme listesinde).

---

## 2. Gerekçe (RAG + iç literatür)

### 2.1 RAG bulguları — ZAYIF

Sağlanan 10 chunk'tan **9'u alakasız** (Jane Street magic-trace, Hyperliquid positioning,
AlphaZero failure modes, vs.). Tek dolaylı destek:

- [#4 bennett_daily_pa]: "Daily timeframe best — intraday reliability drops significantly."
  → Bu **anti-destek**: intraday TOD filtreleme için literatür uyarısı.

**Dürüstlük notu:** RAG corpus'ta TOD session bias için crypto-perp seviyesinde
güvenilir akademik referans **bulunamadı**. Mevcut literatür (Aharon-Qadan 2018,
Caporale 2019) DOW/HOD edge'in sample-dependent olduğunu ve OOS'ta nadiren
tutarlı kaldığını gösteriyor. **RAG'ı zorlamak yerine bu hipotezi düşük-öncelikli
olarak işaretliyorum.**

### 2.2 İç literatür (memory/shared/lessons)

- `lessons/overfit_red_flags.md`: 24-168 hücreli parametre uzayında düzeltmesiz sonuç
  güvenilmez. **Bu hipotez tam o uyarının tarif ettiği şekle benziyor.**
- 2026-05-09 DOW analizi: 1D bar'da HOD trivially null (tüm entry = 00:00 UTC). 15m bar
  bu sorunu **yapısal olarak** çözer (HOD gerçek varyans taşır). Bu, hipotezi en azından
  **test edilebilir** kılıyor.

### 2.3 Davranışsal mekanizma (a priori)

| Saat (UTC) | Beklenen mekanizma | Beklenen yön |
|---|---|---|
| 00-07 | Asya ağırlıklı, düşük EU/US depth | Düşük edge, geniş spread |
| 07-08 | London open | Volatilite spike, breakout pattern |
| 13-14 | NY open + EU overlap | En yüksek likidite, en temiz patterns |
| 16-20 | US-only | Sürdürülen trend devamı |
| 21-23 | Late US, Asya açılış öncesi | Düşük depth, stop-hunt |

Bu **anlatı** test edilecek; sayısal olarak doğrulanmadığı sürece **karar gerekçesi
olamaz**.

---

## 3. Metodoloji

### 3.1 Veri Kaynağı

- **Pool:** En son `sec53_*_pool_v11_*.pkl` (champion VSA-WIDESTOP 15m havuzu)
- **Period:** 2023-06-01 → 2026-05-31 (36 ay)
- **Universe:** Pool'da görünen tüm semboller (~15 perp)
- **Fee model:** 7.5bps taker + 5bps slippage = 55bps round-trip (mevcut champion ile aynı)
- **Reproducibility:** `git_hash` + `pool_hash` + `data_hash` rapor başında

### 3.2 Hücre tanımları

**HOD analizi (H1):**
```
hour = entry_ts.hour  ∈ {0,1,...,23}
n_cells = 24
metric = mean_R per cell
```

**DOW × Session analizi (H2):**
```
day = entry_ts.dayofweek  ∈ {0,...,6}  # 0=Pzt
session = bucket(entry_ts.hour):
    asia    : 00-07
    london  : 07-13
    overlap : 13-16
    us      : 16-21
    latenight: 21-24
n_cells = 7 × 5 = 35  (Bonferroni α = 0.05/35 = 0.00143)
```

### 3.3 Null model (shuffle baseline)

Her hücre için:
- Gerçek mean_R hesaplanır.
- Trade timestamps **shuffle** edilir (1000 permütasyon).
- Empirik null dağılımının %99.79 percentile'i (Bonferroni alpha üzerinden) eşik.
- p-value = `sum(shuf_mean_R >= real_mean_R) / 1000`

### 3.4 Multiple-testing correction

- **Bonferroni** (primary, en konservatif):
  - H1: α = 0.05/24 = **0.00208**
  - H2: α = 0.05/35 = **0.00143**
- **Benjamini-Hochberg FDR** (sekonder, daha yumuşak): q=0.10 ile karşılaştırma raporlanır
  ama karar kriteri DEĞİL.

### 3.5 Per-yıl sign consistency (H3 — curve-fit dedektörü)

Eğer bir hücre Bonferroni'yi geçerse, **per-yıl mean_R işaretine** bakılır:
- 6 yıllık dilim (2020 dahil yoksa 3, son 36 ay → 3 yıl dilim).
- En az **4/6** yıl (veya 2/3 yıl) pozitif mean_R **OLMALI**.
- Aksi halde "regime-luck" → kalan testleri kazansa bile **REJECT**.

### 3.6 Sample-size gating

Hücre başına min N=30 trade gerekiyor. Az olursa hücre **dropped**, gözlem listesine alınır.
24 hücre × 30 min = ~720 trade pool'da olmalı; aksi halde HOD analizi **underpowered**
işaretlenir.

---

## 4. Pre-registered Metrics (Dependent / Independent Variables)

| Tür | Değişken | Açıklama |
|---|---|---|
| Dependent | `mean_R` per cell | Birincil edge metriği |
| Dependent | `p_shuffle` per cell | Null model üzerinden p-value |
| Dependent | `years_positive` per cell | Per-yıl sign consistency (H3) |
| Dependent | `n_trades` per cell | Sample size gating |
| Independent | `hour_utc` | 0-23 (H1) |
| Independent | `day_of_week` | 0-6 (H2) |
| Independent | `session_bucket` | asia/london/overlap/us/latenight (H2) |
| Independent | `symbol` | (kontrol — symbol-out CV için) |

**Beklenen p-value (priors):**
- H1 modal beklenti: **tüm 24 hücre p > 0.00208** (REJECT) — olasılık ~%75
- H2 modal beklenti: **tüm 35 hücre p > 0.00143** (REJECT) — olasılık ~%75
- H3 (eğer 1-2 hücre p geçerse): per-yıl tutarsızlık → REJECT — olasılık ~%18

---

## 5. Stop Criteria (Pre-Registered)

### 5.1 Hipotez TERK (early stop, kod yazılmadan)

- Pool dosyası mevcut değilse VEYA `n_total < 720` ise → **HOLD**, daha fazla canlı veri biriksin.

### 5.2 Hipotez REJECT

Aşağıdakilerden HERHANGİ BİRİ:
- H1: 0/24 hücre Bonferroni p<0.00208 (beklenen sonuç).
- H1 geçen hücre var ama H3 başarısız (per-yıl 4/6 altında) → **REJECT, curve-fit verdict**.
- En iyi hücrenin etki büyüklüğü (mean_R artışı) < **+0.05R** → "ekonomik olarak anlamsız".
- IS/OOS split (son 12 ay OOS): geçen hücrenin OOS mean_R'i IS'in %30 altında → overfit.

### 5.3 Hipotez DEFER (filtre değil, izleme)

- H1: tam **1 hücre** Bonferroni'yi geçer, H3'ü de geçer, etki ≥ +0.05R, IS/OOS dengeli.
- Karar: champion config'e **EKLENMEZ**; 90 gün sonra canlı verilerle tekrar test.
- Lab tournament'a sokulmaz (sample yeterince zenginleşene kadar).

### 5.4 Hipotez PROMOTE (filtre adayı)

Aşağıdakilerin **TAMAMI** gerekir:
- ≥2 bitişik saat (örn. 13-15 UTC) tek tek Bonferroni geçer (komşuluk = mekanizma kanıtı).
- H3: per-yıl 4/6+ pozitif.
- Etki ≥ +0.10R.
- IS/OOS ratio ∈ [0.7, 1.3].
- Symbol-out CV: en kötü sembol bırakıldığında bile etki ≥ +0.05R.
- **Tradeability gate:** Filtre uygulandığında trade sayısı champion'ın %50'sinin altına
  düşmez (yoksa pratik değer yok).

**PROMOTE'un a-priori olasılığı: ~%5.** Bu hipotez `DEFER` veya `REJECT` ile bitecek
gibi tasarlanmış.

---

## 6. Curve-fit Kırmızı Bayrakları (önceden tanımlı)

Test sırasında AŞAĞIDAKİLERİ gördüğümde hipotez **derhal REJECT**:

1. **Tek izole saat** Bonferroni geçer, komşuları geçmez → mekanizma yok, izole şans.
2. **En iyi saat parametre uzayının "psikolojik" yerinde** (00:00, 12:00, 16:00 gibi) →
   data-mining yapısal etkisi olabilir.
3. **2022-05 (LUNA) veya 2022-11 (FTX) tek başına o saatin tüm edge'ini taşıyor** →
   stress-period luck, regime-conditional değil tek-olay.
4. **Sembol başına alt-analiz: 1 sembol tüm edge'i taşıyor** → genelleme yok.
5. **Best hour'da mean_R > +0.30R** → kripto bar-OHLCV'de bu seviye **anormal**;
   muhtemelen lookahead veya pool oluşturma sırasında time-leakage.

---

## 7. Reproducibility & Audit

- `git_hash`: rapor oluştururken commit edilir.
- `pool_hash`: SHA256 of pool .pkl.
- `data_hash`: SHA256 of relevant DuckDB partition.
- Tüm shuffle seed'leri = `range(1000)` deterministic.
- Rapor: `reports/research/tod-session-bias-15m-2026-06-04.html` + .md.

---

## 8. Karar Çerçevesi (Pre-Registered)

```
1. Pool var? n>=720? → yoksa HOLD.
2. H1 (24 saat): 0 geçen → REJECT (primary outcome, beklenen).
3. H1 1-2 geçen + H3 başarısız → REJECT (curve-fit).
4. H1 1 geçen + H3 OK + ekonomi zayıf → DEFER (90d watchlist).
5. H1 ≥2 bitişik + H3 OK + ekonomi OK + IS/OOS OK + sembol robust + tradeability OK
   → PROMOTE (Lab tournament adayı).
```

---

## 9. Bu Çalışmanın Değeri (REJECT senaryosunda bile)

- DOW (1D) 2026-05-09'da çürütüldü. HOD (15m) henüz **resmi olarak** çürütülmedi.
- Reddedilirse, **şu soru bir daha sorulmasın**: "TOD filtresi eklesek?" — cevap arşivde.
- Pool'daki **trade dağılımı** (saat × gün) yan ürün olarak elde edilir; başka filtreler için
  exposure haritası niteliğinde.

---

## 10. Sonuçlar

> _Bu bölüm backtest çalıştıktan sonra doldurulacak._

VERDICT: ☐ REJECT ☐ DEFER ☐ PROMOTE
