---
doc_id: strategy_curator-20260529T000000-lifecycle-single-leg
doc_type: decision
agent_id: strategy_curator
created_at: 2026-05-29T00:00:00Z
status: PROPOSED
confidence: med
depends_on: []
blocks: []
requested_review_from: [ceo, risk_officer]
tags: [lifecycle, decay, diversity, concentration_risk, probation]
supersedes: null
---

# Strategy Lifecycle Review — 2026-05-29

## TL;DR
Tek-aktif portföy. Tek aday (vsa_climax_test) decay verdict'i için **veri yetersiz** (n_obs=3, eşik 30). Diversity entropy ≈ 0; library utilization 1/67 = %1.5. **PROBATION** veriyorum; RETIRE için kanıt yok, KEEP için doğrulama yok. ONBOARD havuzu boş — shelf re-scan acil.

---

## Girdi Özeti

| Metrik | Değer |
|---|---|
| Library size | 67 strateji |
| Active in library | **1** (vsa_climax_test) |
| Shelf (idle) | 66 |
| Onboard candidates | **0** |
| Decay rows | 1 (INSUFFICIENT_DATA) |

---

## Verdict Tablosu

### vsa_climax_test → **PROBATION**

**Gerekçe:**
- `n_obs = 3 < min = 30`; `slope_per_day = NaN`. 90-gün rolling Sharpe slope hesaplanamadı → istatistiksel olarak ne decay ne stabilite kanıtlanamaz.
- **KEEP demiyorum:** Alpha-decay testi başarısız (insufficient data ≠ approved). Sample yokken "iyi çalışıyor" demek confirmation bias.
- **RETIRE demiyorum:** 3 gözlem ile RETIRE seçilemez — survivorship + recency bias ihlali. Strateji yeni mi onboard oldu, yoksa journal verisi mi eksik? Önce data_engineer'dan onay alınsın.
- **PROBATION =** canlı kalmaya devam, ancak **sıkı sermaye tavanı** (mevcut allocate'in %50'sini geçmesin) + **30 gözleme ulaşana kadar yeni allocate yok**. Bir sonraki lifecycle review 2026-06-29 veya n_obs ≥ 30 hangisi önce.

**Risk Officer için flag:**
- Bu strateji tek-leg portföyün tamamı. Tek detector hatası / tek rejim dönüşü = portföyün %100 down. `configs/risk*.yaml` içindeki `max_per_strategy_pct` 'ye **ek olarak** "single-leg system" sermaye katman (örn. portfolio NAV'in %30'unu geçmesin) düşünülsün.

### LIBRARY (66 raf stratejisi) → **NO CHANGE (snapshot)**

**Gerekçe:** Bu doc shelf strategy-by-strategy revival kararı vermez; sadece üst-seviye lifecycle çerçevesidir. lab_scientist tournament + researcher onaylı backtest'i olmadan raf'tan hiçbir strateji "ONBOARD" edilmez (ADR-002 + protocol §7).

### ONBOARD → **DEFER (havuz boş)**

**Gerekçe:** `ONBOARD_ROWS=[]` üç şeyden birine işaret eder:
1. **Library scan stale** — researcher backtest_results/ son N gün hangileri marginal Sharpe gate'inden geçti, taranmadı.
2. **Gate'ler doğru kalibre, raf gerçekten zayıf** — `2026-05-29-brooks-*` ve `2026-05-29-forex-*` backtest sonuçları görünüyor ama hiçbiri DSR p<0.05 + effect ≥15% + MaxDD ≤ champion+5% geçemedi.
3. **Champion baseline gevşek** — tek-leg + n_obs=3 olduğundan "challenge edilecek champion" yok; bu durumda marginal Sharpe = aday'ın stand-alone Sharpe'ı.

**Aksiyon önerisi (CEO için):**
- researcher'a: bu hafta `memory/researcher/backtest_results/2026-05-29-*` taraması yap, marginal Sharpe gate'inden geçen var mı (correlation < 0.4 vs vsa_climax_test) tablosu çıkar.
- lab_scientist'e: tournament için "vacuum champion" modu — vsa_climax_test n_obs<30 olduğundan champion = synthetic baseline (örn. equal-weight 3-leg shelf sample), challenger = en yüksek marginal Sharpe aday.

---

## Diversity Entropy

**H = −Σ pᵢ log pᵢ ≈ 0 nats** (tüm kütle tek stratejide).

- Hedef tabanı: H ≥ ln(3) ≈ **1.10 nats** (en az 3 dengeli leg).
- Mevcut: 0.00 nats → **−1.10 açık**.
- Yorum: Konsantrasyon riski **maksimum**. Tek strateji failure = portfolio kill. Bu, ADR'ye yazılı "diversification floor" varsayımının altında.
- Ek not: vsa_climax_test pattern ailesi VSA (volume-spread). Tek pattern ailesinde olmak — pattern-class regime change'e karşı (örn. düşük hacim rejimi) defansız.

## Marginal Sharpe — N/A

Hesaplanamadı:
- ONBOARD_ROWS boş → aday yok → marginal hesabı tanımsız.
- Champion (vsa_climax_test) yetersiz veri → baseline Sharpe yok → "marginal vs champion" gradient çizilemez.

**Yorum:** Bu metrik bir sonraki review'da anlamlı olmaya başlar; ya n_obs ≥ 30 olunca, ya shelf'ten geçici "synthetic champion" inşa edilince. Bu döngüde marjinal Sharpe ile karar verilmez — verilirse sahte sinyal olur.

---

## Conservative Recommendations

### CEO için (öncelik sırası)
1. **PROBATION onayla:** vsa_climax_test allocate **dondurulsun** (mevcut cap'in üstüne çıkma yok) 30 gözleme kadar.
2. **Shelf scan tetikle:** researcher + lab_scientist'e ortak görev: `memory/researcher/backtest_results/2026-05-29-*` üzerinden marginal Sharpe ≥ +0.15 + corr < 0.4 tablosu (1 hafta SLA).
3. **Diversification floor ADR:** "min 3 active strateji veya portfolio NAV %30 cap" kuralı yazılı hale getirilsin (yeni ADR). Tek-leg sistem mevcut hâli **kabul edilebilir geçici durum değil**.
4. Bu doc'a göre yeni allocate edilmez; yeni onboard kararı **ayrı doc ile** Principal sign-off bekler (ADR-002).

### Risk Officer için (audit talebi)
1. `max_per_strategy_pct` mevcut değeri vsa_climax_test için yeterli mi? (single-leg = portfolio NAV'in %100'ü teorik olarak)
2. Tek strateji breaker tripped olursa — fallback portföy "0 leg" olur. Bu acil durum protokol akışı var mı? (`configs/conflict_policy.yaml` kontrol).
3. n_obs=3 olan strateji, journal data integrity'sini onaylamadan canlı sermaye ile devam etmeli mi? (data_engineer'dan veri eksikliği vs strateji yeni-doğmuş ayrımı istensin).

### Reddedilen Aksiyonlar (kayda geçsin)
- ❌ RETIRE vsa_climax_test: kanıt yok; recency bias.
- ❌ ONBOARD bir shelf stratejisi (örn. brooks_failed_breakout veya forex-4h adayları): tournament + DSR + corr gate'lerinden geçtikleri doc'lanmadan, curator yetkisiyle promote edilmez.
- ❌ Marginal Sharpe ile karar: hesaplanabilir değil.

---

## "What would change my verdict"
- vsa_climax_test n_obs ≥ 30 ve slope_se güvenilir → KEEP veya RETIRE kararına geçilir.
- ONBOARD havuzunda ≥ 1 aday (DSR p<0.05, effect ≥%15, corr < 0.4) → diversity entropy ≥ 0.69 (2-leg) hedefiyle ONBOARD verilir.
- Data integrity audit'i "strateji yeni onboard, journal sağlam" derse PROBATION → conditional KEEP; "journal eksik" derse RETIRE adayı.

---

## Bağlantılı Memory
- [[widestop-threshold-validated]] — fee-erozyon disiplini, aynı conservative çizgi.
- [[forex-4h-research-status]] — shelf'teki olası onboard adayı (paper-only, SPK-bloklu canlıda).
