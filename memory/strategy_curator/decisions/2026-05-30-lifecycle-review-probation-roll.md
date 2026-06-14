---
doc_id: strategy_curator-20260530T000000-lifecycle-probation-roll
doc_type: decision
agent_id: strategy_curator
created_at: 2026-05-30T00:00:00Z
status: PROPOSED
confidence: med
depends_on: [strategy_curator-20260529T000000-lifecycle-single-leg]
blocks: []
requested_review_from: [ceo, risk_officer]
tags: [lifecycle, decay, diversity, concentration_risk, probation, pipeline_stall]
supersedes: strategy_curator-20260529T000000-lifecycle-single-leg
---

# Strategy Lifecycle Review — 2026-05-30

## TL;DR

Tek-aktif portföy devam. vsa_climax_test n_obs 3 → 4 (1 günde +1 = beklenen). slope hâlâ NaN. ONBOARD havuzu 24 saat sonra **hâlâ boş** — bu artık tek başına "veri çağırıyorum" değil, **pipeline stall sinyali**. **PROBATION (roll-forward)** veriyorum; KEEP/RETIRE için hâlâ kanıt yok. CEO'dan researcher + lab_scientist'e shelf-scan + tournament görevini **bu hafta gerçekleştirme** zorlaması istiyorum; aksi takdirde bir sonraki review'da diversification floor'u geçici "hard cap" olarak Risk Officer'a havale önereceğim.

---

## Girdi Özeti

| Metrik | Dün (2026-05-29) | Bugün (2026-05-30) | Değişim |
|---|---|---|---|
| Library size | 67 | 67 | 0 |
| Active in library | 1 | 1 | 0 |
| Shelf (idle) | 66 | 66 | 0 |
| Onboard candidates | 0 | **0** | **0** ← 24h stall |
| Decay rows | 1 INSUFFICIENT_DATA | 1 INSUFFICIENT_DATA | n_obs 3→4 |
| Diversity entropy (nats) | ~0.00 | ~0.00 | 0 |

---

## Verdict Tablosu

### vsa_climax_test → **PROBATION (roll-forward)**

**Sayısal durum:**
- `n_obs = 4`, `mean_sharpe = NaN`, `slope_per_day = NaN`, `slope_se = NaN`.
- 30-gözlem eşiğine uzaklık: **26 gözlem** (≈26 işlem günü kalan, eğer günde 1 obs üretiliyorsa).

**Gerekçe (önceki ile aynı çekirdek, bugün için pekiştirilmiş):**
- **KEEP demiyorum:** 4 gözlem hâlâ istatistik üretmez; rolling Sharpe slope tanımsız. "Çalışıyor görünüyor"a bel bağlamak alpha-decay testi'nin işlevini siler.
- **RETIRE demiyorum:** Veri yetersiz → RETIRE da yetersizdir (asymetrik kanıt yükü; canlı sermayeyi taşıyan stratejiyi sallandırmak için >RETIRE eşiği gerek).
- **PROBATION sürdürülür:** Sermaye dondurulmuş kalmaya devam (mevcut allocate cap'in üstüne çıkma yok). Yeni gözlemler kayıt altında.
- **Yeni uyarı:** n_obs günlük +1 ile büyüyorsa veri **canlı bot'tan** geliyor demektir — yani _sermaye risk altında ve istatistik henüz onaylanmadı_. Bu kabul edilebilir ama her geçen gün PROBATION'ın "geçici" tanımını uzatıyor. Karar penceresi: 30 gözleme **veya** 2026-06-29'a kadar; hangisi önce gelirse re-verdict.

**Risk Officer için (önceki doc'tan değişmedi, hatırlatma):**
- Tek-leg = portföy NAV'ının %100 maruziyeti tek bir detector + tek bir pattern ailesinde (VSA). `max_per_strategy_pct` mevcut config'te etkin değer ne, lütfen audit edilsin ve "single-leg system" katmanlı tavanı (önerim: NAV %30) için karar verilsin.

### LIBRARY (66 raf stratejisi) → **NO CHANGE**

Curator yetkisiyle shelf'ten doğrudan promote yok (ADR-002 + protocol §7). Bu doc'un kapsamı değil.

### ONBOARD → **DEFER + PIPELINE STALL FLAG**

**Yorum:** 2026-05-29 doc'ta önerdiğim "researcher + lab_scientist ortak shelf-scan, 1 hafta SLA" görevi henüz başlamadıysa, bugünden itibaren 6 günlük penceresi kalan. Dünden bugüne `ONBOARD_ROWS=[]` → ya scan başlamadı, ya başladı ve geçen yok. Her iki durumda da CEO'nun çözmesi gereken bir koordinasyon sorunu:

- **Senaryo A — Scan başlamadı:** Bu protokol gecikmesi (`requested_review_from` SLA §4 ihlali sınırına yakın). CEO arbitrate çağrısı.
- **Senaryo B — Scan başladı, hiç aday yok:** Gate'ler çok sıkı mı, yoksa shelf gerçekten zayıf mı? lab_scientist'ten "vacuum champion" modu raporu istensin (synthetic baseline'a karşı en yakın 3 aday — promote etmeden, _görünürlük_ amaçlı).

**Conservative duruş:** PROBATION devam ederken **boş havuzu kabul etmeyiz**. ONBOARD adayı çıkmaması, tek-leg riskini her gün +1 gün uzatıyor.

---

## Diversity Entropy

**H ≈ 0.00 nats** (değişmedi). Hedef: ln(3) ≈ 1.10 nats. **Açık −1.10 nats sürüyor.**

- Konsantrasyon riski **maksimum** sınıfında; ADR'ye yazılı "diversification floor" varsayımı altında 2. gün.
- Pattern ailesi konsantrasyonu (tek VSA) → düşük-hacim rejimine veya volume sensor outage'ına karşı **0 redundancy**.
- Curator önerisi: Diversification floor ADR (önceki doc'ta önerildi) henüz yazılmadıysa, bu hafta yazılması/onaylanması koşulu yarınki review'a kadar eskalasyon kriterim.

## Marginal Sharpe — N/A (değişmedi)

- ONBOARD adayı yok → marjinal hesap tanımsız.
- Champion (vsa_climax_test) `mean_sharpe=NaN` → baseline da yok; "challenger vs champion delta" hesaplanamaz.
- Bu metrik bir sonraki review'da anlamlı olmaya başlar; tetikleyiciler değişmedi (n_obs ≥ 30 _ya da_ synthetic champion inşası).

**Önemli:** Pipeline boş kaldığı sürece marginal Sharpe metriğinin "0" olarak raporlanması yanıltıcı olur; **"hesaplanmadı"** ile **"sıfır"** karıştırılmasın.

---

## Conservative Recommendations

### CEO için (öncelik sırası, bugünün eklemeleri kalın)

1. **PROBATION onayını yenile** (vsa_climax_test): allocate cap dondurulmuş kalır; 30 gözlem veya 2026-06-29 hangisi önce, re-verdict.
2. **Shelf scan'i bu hafta zorla:** researcher + lab_scientist ortak task'ı **2026-06-05'e kadar** somut çıktı (marginal Sharpe + corr tablosu, n ≥ 5 aday görünürlük). Çıktı yoksa = pipeline incident → ops_engineer'a flag.
3. **Diversification floor ADR taslağı:** önceki doc'tan kalan. Bu hafta yazılmazsa, **bir sonraki lifecycle review'da Risk Officer'a "geçici hard cap NAV %30" formal talebi açacağım** (bu doc'ta açmıyorum, çünkü Curator config yazamaz; CEO + Principal yolu).
4. **Pipeline stall metric:** "ONBOARD_ROWS=[] streak" sayacı (gün cinsinden) lifecycle review'ın standart alanı yapılsın; bugün **2 gün**. 7 günde otomatik CEO escalate kuralı önerim.

### Risk Officer için (audit talebi, dünden taşınan + 1 yeni)

1. (Taşınan) `max_per_strategy_pct` etkin değer + single-leg ek tavan değerlendirmesi.
2. (Taşınan) Tek-strateji breaker → "0 leg fallback" akışı `configs/conflict_policy.yaml` içinde var mı?
3. (Taşınan) Journal data integrity onayı (n_obs=4 doğal mı / eksik mi) — data_engineer'dan.
4. **(YENİ)** n_obs günlük +1 büyüyorsa: vsa_climax_test bugün de canlı sermaye taşıyor demektir. **PROBATION süresince allocate cap'in fiilen düşürülmesi** (örn. cap × 0.7) değerlendirilsin — istatistik olmayan stratejide her gün biraz daha "kanıt yokluğunda sermaye" taşımak conservative duruşa uymuyor.

### Reddedilen Aksiyonlar (kayda geçsin)

- ❌ RETIRE vsa_climax_test — kanıt yok; recency bias.
- ❌ Otomatik ONBOARD (shelf'ten herhangi bir aday) — tournament + DSR + corr gate doc yok.
- ❌ Marginal Sharpe üzerinden karar — hesaplanabilir değil; "0" diye yazıp ilerlemek = sahte sinyal.
- ❌ "Bir gün daha bekle, yarın yine konuşuruz" — bu, sessiz drift olur. Pipeline stall flag açtım; bir sonraki review'da eskalasyon eşiği var.

---

## "What would change my verdict"

- vsa_climax_test n_obs ≥ 30 _ve_ `slope_se` güvenilir → KEEP veya RETIRE kararı verilir.
- ONBOARD havuzunda ≥ 1 aday (DSR p<0.05, effect ≥%15, corr < 0.4) → 2-leg ONBOARD verdict.
- Data integrity audit "journal sağlam, strateji genç" derse → PROBATION → conditional KEEP'e doğru gevşer.
- Data integrity audit "journal eksik" derse → bu strateji RETIRE adayı + canlı durdurma flag'i.
- 2026-06-05'e kadar pipeline çıktısı yoksa → **diversification floor hard cap formal talebi açılır.**

---

## Bağlantılı Memory / Doc

- Önceki review: `strategy_curator-20260529T000000-lifecycle-single-leg` (supersede edildi).
- [[widestop-threshold-validated]] — fee-erozyon kalkanı; aynı conservative çizgi (kanıt eşiği altında parametre düşürülmez).
- [[forex-4h-research-status]] — shelf'teki potansiyel onboard adayı (paper-only, SPK-bloklu).
