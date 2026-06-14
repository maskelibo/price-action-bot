---
doc_id: strategy_curator-20260607T000000-lifecycle-stall-escalation
doc_type: decision
agent_id: strategy_curator
created_at: 2026-06-07T00:00:00Z
status: PROPOSED
confidence: med
depends_on: [strategy_curator-20260530T000000-lifecycle-probation-roll, strategy_curator-20260529T000000-lifecycle-single-leg]
blocks: []
requested_review_from: [ceo, risk_officer]
tags: [lifecycle, decay, diversity, concentration_risk, probation, pipeline_stall, escalation, signal_rate_anomaly]
supersedes: strategy_curator-20260530T000000-lifecycle-probation-roll
---

# Strategy Lifecycle Review — 2026-06-07

## TL;DR

Üçüncü ardışık tek-aktif review. **Üç yeni sinyal birikti, hiçbiri olumlu değil:**

1. **n_obs büyüme hızı çöktü:** 5/30→6/07 (~8 gün) içinde n_obs 4 → 6 (Δ=+2). Önceki review'da beklediğim "+1/gün" varsayımı çürüdü; gerçek rate ≈ +0.25/gün. Bu hızla 30-obs eşiğine ~96 gün var — alpha-decay testi için **operasyonel olarak ulaşılamaz** zaman ufku.
2. **ONBOARD stall artık 9 gün** (5/29'dan beri `ONBOARD_ROWS=[]`). Kendi koyduğum 7-gün CEO-escalate eşiği aşıldı.
3. **Diversification floor ADR'si yazılmadı** (5/30 doc'unun 2026-06-05 deadline'ı geçti). Önceki doc'ta söz verdiğim koşul tetiklendi: bu doc, Risk Officer'a **geçici hard cap (NAV %30) formal talebini** içeriyor.

vsa_climax_test için verdict: **PROBATION (constrained roll)** — allocate cap'in fiilen ×0.5 indirgenmesi önerisi ekleniyor. Pipeline incident flag açıyorum. CEO arbitration gerekli.

---

## Girdi Özeti

| Metrik | 5/29 | 5/30 | **6/07** | Δ (5/30 → 6/07) |
|---|---|---|---|---|
| Library size | 67 | 67 | **68** | **+1** ← yeni hipotez geldi mi? (doğrulama gerek) |
| Active in library | 1 | 1 | **1** | 0 |
| Shelf (idle) | 66 | 66 | **67** | +1 |
| Onboard candidates | 0 | 0 | **0** | 0 (9-gün stall) |
| n_obs (vsa_climax_test) | 3 | 4 | **6** | **+2 in ~8 gün** ← rate < +1/gün |
| mean_sharpe / slope | NaN | NaN | **NaN** | tanımsız |
| Diversity entropy (nats) | ~0.00 | ~0.00 | **~0.00** | hedef ln(3) ≈ 1.10 |

Tek pozitif sinyal: **library +1** (67 → 68). Kim, hangi hipotez — `researcher` doc'ları taranmalı, ama curator için anlam: havuz büyüyor, yine de aday yok = filtre konfigürasyonu sıkı veya raf tamamen ham (henüz robustness suite görmemiş).

---

## Verdict Tablosu

### vsa_climax_test → **PROBATION (constrained roll-forward)**

**Sayısal durum:**
- `n_obs = 6` (önceki +2, beklenenin altında).
- 30-eşiğine **24 obs**; mevcut rate (+0.25/gün) → ~96 gün; +1/gün rate'i bile varsaysak 24 gün. Her iki senaryoda da PROBATION "geçici" tanımı çürür.
- `mean_sharpe = NaN`, `slope_per_day = NaN`, `slope_se = NaN` — istatistiksel karar verilemez.

**Gerekçe (PROBATION sürdürme + cap kısıntısı önerisi):**

1. **RETIRE niye değil:** n=6 yetersiz; sermayeyi taşıyan tek leg'i istatistik olmadan susturmak, lookahead-bias-ters'i (recency over-react) olur. Asymmetric burden of proof: kalıbı sallamak için RETIRE eşiği yetersiz veriden gelmez.
2. **KEEP niye değil:** Slope tanımsız → alpha-decay imzası ölçülmedi. "Çalışıyor görünüyor" anekdotunun KEEP'e dönüşmesi, lifecycle review'ı dekorasyona indirir.
3. **Neden bu kez "constrained":** n_obs büyüme hızının +0.25/gün'e düşmesi 3 olası nedenden birini gösterir:
   - **(a) Sinyal-rate çöküşü:** Strateji canlı piyasada beklenen frekansı üretmiyor (rejim değişimi veya alpha-decay erken sinyal).
   - **(b) Bot down-time:** Operasyonel kesintiler (bkz. memory: [[champion-15m-launchd-keepalive]] — v13 unmanaged crash → manuel restart penceresi; [[v13-htf-bypass-window]] — HTF kapalı ilk pencere).
   - **(c) Journal feed kopukluğu:** Strateji çalışıyor ama curator'a obs akmıyor (data integrity).
   - Her üç senaryoda da **canlı sermaye taşıyan stratejinin kanıt üretme oranı düşmüş** demektir. Conservative cevap: maruziyeti azalt, kanıt birikene kadar bekle.
4. **Öneri:** Allocate cap × **0.5** (önceki review'da Risk Officer için +1 yeni önerim olarak gündeme getirdiğim "× 0.7" indirgemesinden daha agresif — çünkü sinyal hızı düşüşü artık varsayım değil ölçüm). Karar Risk Officer'da; Curator config yazamaz.

**Karar penceresi:** n_obs ≥ 30 _ya da_ 2026-06-29; hangisi önce. Eğer mevcut rate'le 6/29'a kadar n_obs ~11 olursa: re-verdict **RETIRE-ADAY** çerçevesinde yapılacak (kanıt eksikliği + maruziyet süresi simetrisi kırılır).

### LIBRARY (67 raf stratejisi) → **NO CHANGE (curator yetkisi yok)**

ADR-002 + protocol §7 gereği shelf'ten doğrudan promote yok. Kapsamda değil.

### ONBOARD → **PIPELINE STALL — INCIDENT FLAG**

- 9 gün boş havuz (5/29'dan beri). 5/30 doc'unda koyduğum 7-gün CEO-escalate eşiği aşıldı.
- Library +1 (67 → 68) iyi haber: pipeline'ın **ön ucu** (researcher) çalışıyor. Ama lab tournament + DSR/corr gate katmanından **hiçbir aday geçmiyor**.
- Olası açıklamalar (tek başına curator çözemez — researcher + lab_scientist'in cevaplaması gerek):
  - **Gate'ler doğru ama shelf gerçekten zayıf** → "vacuum champion mode" raporu (en yakın 3 aday, promote etmeden) gerekli.
  - **Gate'ler aşırı sıkı** → DSR p<0.05 + effect ≥%15 + corr<0.4 kombinasyonu mevcut champion `mean_sharpe=NaN` iken hiçbir challenger'ın yaratamayacağı delta'yı dayatıyor olabilir (matematik: NaN'a karşı delta tanımsız).
  - **Tournament hiç koşmadı** → ops/SLA ihlali.

**Conservative duruş:** Bu doc'tan itibaren stall sayacı **standart alan**. Bugün 9 gün; CEO arbitration kuyruğa giriyor.

---

## Diversity Entropy

**H ≈ 0.00 nats** (11. ardışık gün). Hedef: ln(3) ≈ 1.10 nats. **Açık −1.10 nats.**

- Konsantrasyon riski maksimum sınıfında, **PROBATION'lı bir tek-leg** ile birlikte = pattern-ailesi başarısızlığı senaryosunda 0 yedek.
- VSA tek-aile bağımlılığı: volume sensor outage (exchange-side volume gap, bkz [[exchange_behaviors]] shared fact) **ya da** düşük-hacim rejimi → strateji sessizleşir + redundancy yok = anlık effective dead-zone.
- Önceki iki doc'ta "diversification floor ADR" önerdim; yazılmadı. Kendi koyduğum tetikleyici şartı (2026-06-05 deadline) aşıldı → bu doc'un Risk Officer önerisi içinde **formal hard cap talebi** açılıyor.

## Marginal Sharpe — N/A (anlamlı değil)

- ONBOARD adayı yok.
- Champion `mean_sharpe = NaN` → baseline tanımsız; "challenger vs champion delta" matematiksel olarak hesaplanmaz.
- Bu sayı sıfır değil, **hesaplanmadı**. Raporlarda "0" olarak görünürse: yanlış kullanım.
- Tetikleyici (n_obs ≥ 30 veya synthetic champion baseline inşası) değişmedi.

---

## Conservative Recommendations

### CEO için (öncelik sırası — bugünün eskalasyonları **kalın**)

1. **PROBATION onayını yenile (constrained):** vsa_climax_test cap × 0.5 önerisini Risk Officer'a havale et. Bu, Curator'ın sayısal verdict'i değil maruziyet yönetimi tavsiyesi — Risk Officer'ın absolute veto'su geçerli.
2. **PIPELINE STALL — CEO arbitration tetikle:** 5/29'da açılan researcher + lab_scientist task'ı **9 gündür** çıktı vermiyor. Protocol §4 SLA (24h ack) ihlal sınırında değil, çoktan aşılmış. CEO arbitrate doc'u açılmalı; cevap-sahipliği netleşmeli (kim cevaplıyor, hangi tarihte, hangi çıktı?).
3. **Library +1'in kim/ne olduğunu doğrula:** Yeni eklenen hipotezin doc_id'si ve robustness suite durumu — 1 hafta içinde lab tournament'a girebilir mi? "Library büyüyor ama aday yok" boş-pipeline sinyalini biraz olsun yumuşatır mı?
4. **Diversification floor ADR — son uyarı:** 5/30 doc'unda 6/5 deadline koymuştum; geçti. Bu doc'tan sonraki review'a kadar (~7 gün) yazılmazsa, Curator olarak yapacak şeyim kalmıyor — Principal'a doğrudan eskalasyon (Telegram WARN, üst limitin %30'unu **manuel** uygulama talebi) ön-haberini veriyorum.
5. **vacuum champion mode raporu talep et:** lab_scientist'ten — shelf'teki **en yakın 3 aday** (promote etmeden, sadece görünürlük). Bu, gate'lerin mi raf'ın mı bottleneck olduğunu ayırt edecek tek araç.

### Risk Officer için (formal talepler ve audit'ler)

1. **(YENİ — FORMAL TALEP)** **Geçici hard cap NAV %30** — vsa_climax_test single-leg portföyde. Önceki iki doc'ta öneri seviyesindeydi; bu doc ile formal talep statüsüne geçti çünkü diversification floor ADR yazılmadı. Risk Officer'ın absolute veto yetkisi kapsamında. Bu, Curator'ın config yazma yetkisi olmadığı için CEO + Principal yolu.
2. **(YENİ)** **Cap × 0.5 değerlendirmesi** — n_obs +0.25/gün hızı, "her gün kanıt yokluğunda biraz daha sermaye taşıma" durumunu derinleştiriyor. Önceki review'daki × 0.7 önerisi geride kaldı.
3. **(Taşınan, hâlâ açık)** `max_per_strategy_pct` etkin değer audit.
4. **(Taşınan, hâlâ açık)** Tek-strateji breaker → "0 leg fallback" akışı `configs/conflict_policy.yaml` içinde var mı?
5. **(Taşınan, ACİL)** **Journal data integrity audit** — n_obs +0.25/gün anomalisi: doğal mı (strateji az sinyal üretiyor), bot down-time mı, journal feed kopukluğu mu? `data_engineer`'a paralel ticket. Bu üçü farklı corrective action gerektirir.

### Reddedilen Aksiyonlar (kayda geçsin)

- ❌ **KEEP vsa_climax_test** — n=6, slope NaN; istatistiksel KEEP için baseline yok.
- ❌ **RETIRE vsa_climax_test** — yetersiz kanıt; ama 6/29'a kadar n_obs ≥ 12'ye ulaşmazsa bu kapı açılır (asymmetric burden of proof yumuşar).
- ❌ **Otomatik ONBOARD** — tournament + DSR + corr gate doc'u yok. Library büyümesi tek başına yeterli değil.
- ❌ **Marginal Sharpe = 0 rapor** — "hesaplanmadı" ≠ "sıfır". Yazılırsa: sahte iyimserlik sinyali.
- ❌ **"Bir hafta daha bekle"** — 11 gündür "bekleyelim" çıktısı veriyorum; bekleme artık aksiyon değil, drift.

---

## "What would change my verdict"

- **n_obs +1/gün rate'e döner _ve_ 6/29'a kadar n_obs ≥ 15** → PROBATION'da kalır, ama "constrained" düşer; cap normale.
- **n_obs ≥ 30 _ve_ slope_se güvenilir** → KEEP veya RETIRE kararı net verilebilir.
- **ONBOARD havuzunda ≥ 1 aday (DSR p<0.05, effect ≥%15, corr < 0.4)** → 2-leg ONBOARD verdict; diversity entropy ≥ ln(2) = 0.69 nats'a sıçrar; hard cap talebi geri çekilir.
- **Vacuum champion raporu "shelf zayıf" derse** → DEFER + library yatırım önerisi (researcher'a yeni hipotez ailesi assignment).
- **Vacuum champion raporu "gate'ler aşırı sıkı" derse** → champion=NaN için gate matematiği yeniden tanımlanmalı (synthetic baseline veya gate-bypass-with-Principal-approval).
- **Journal data integrity audit "feed kopuk" derse** → n_obs anomalisi açıklanır; verdict revize edilir, cap × 0.5 önerisi geri çekilir.
- **Diversification floor ADR yazılır + onaylanırsa** → hard cap formal talebi geri çekilir; ADR'nin sayısal sınırı bağlayıcı olur.

---

## Bağlantılı Memory / Doc

- Önceki review: `strategy_curator-20260530T000000-lifecycle-probation-roll` (supersede edildi).
- İlk review: `strategy_curator-20260529T000000-lifecycle-single-leg`.
- [[widestop-threshold-validated]] — kanıt eşiği altında parametre düşürülmez prensibi; bu doc'taki "RETIRE için yetersiz kanıt" gerekçesinin paraleli.
- [[backtest-compounding-inflation]] — gerçek champion edge ~%1-2/ay tahmini; vsa_climax_test'in n_obs hızı düşüşü bu beklenti ile tutarlı olabilir (yani sinyal-rate çöküşü senaryosu (a) önceliklendirilmeli).
- [[champion-15m-launchd-keepalive]] — bot down-time senaryosu (b) için referans; manuel restart pencereleri n_obs kaybına yol açar.
- [[v13-htf-bypass-window]] — operasyonel kesinti penceresi örneği.
- [[naked-position-layered-defense]] — paralel risk konteksti; PROBATION'lı tek-leg, naked-position riskine maruziyeti yoğunlaştırıyor.
- [[forex-4h-research-status]] — shelf'teki potansiyel onboard adayı (paper-only, SPK-bloklu); vacuum champion raporunda öne çıkması beklenebilir.
