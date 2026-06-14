---
doc_id: researcher-20260607T060000-vsa-widestop-slpct-sweep
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-07T06:00:00Z
status: DRAFT
confidence: low
depends_on:
  - lesson-widestop-threshold-validated
  - learning-vsa-honest-reconciliation-20260603
  - learning-per-year-sign-consistency
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, vsa, widestop, parameter_sweep, anti-curve-fit, negative-prior]
supersedes: null
hash: null
---

# HYP-2026-06-07: vsa_climax_test — wide-stop `sl_pct_min` sweep (negatif prior)

## 0. A priori curve-fit şüphesi (önce yazıyorum, sonra teste girerim)

Bu sweep'in **negatif prior**la giriyorum, kararsızlıkla değil. Önceden bilinenler:

1. **Live floor (sl_pct_min=0.025 @ 15m) zaten "fee-erozyon kalkanı" olarak doğrulandı** (`memory/MEMORY.md → widestop-threshold-validated`). Düşürme zaten BLOCKED.
2. **VSA champion'ın honest reconciliation'ı negatif:** `mR_55=+0.08, total_ret=-9.2%, DD=-42%` (data/market.duckdb, 2026-06-03 learning). "+0.84 mR / +12-15%/mo" claim'i mevcut veriyle **yeniden üretilemiyor**.
3. **Daha önce `htf_1d_aligned` dışındaki tüm entry-quality lever'ları VSA'da çürüdü** (climax-intensity → no OOS lift; vol_z/spread_atr → per-year flip).
4. **Per-year sign consistency = en ucuz overfit detector** (2026-06-03 dersi). Burada hard-gate olarak uygulayacağım.

Bu sweep'in **null hipotezi savunma pozisyonu**: "Live floor (0.025) zaten optimal; herhangi bir başka grid noktası Holm/Bonferroni + per-year + shuffle-null gate'lerinin TAMAMINI birlikte geçemez." Sweep'in pass etmesi 4 ayrı gate'i aynı anda kırmasını gerektirir.

---

## 1. İddia (pre-registered, numeric)

> 15m timeframe'de, `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` champion config'i dondurulmuş şekilde (vol_z eşikleri, climax intensity, htf_1d_aligned, RO, fee model = LIVE), **sadece `sl_pct_min` parametresi** önceden donmuş 4-noktalı grid'de sweep edildiğinde:
> `sl_pct_min ∈ {0.025 (champion baseline), 0.030, 0.035, 0.040}` (4 nokta, ince grid YASAK),
> 3y in-sample (2023-01-01 → 2025-12-31) + 6m walk-forward OOS (2026-01-01 → 2026-06-01), all-liquid USDT-perp evreni (delisting'ler dahil, survivorship-safe), fee 5.5bps taker + 5bps slip:
>
> **En iyi non-baseline grid noktası (0.030/0.035/0.040'tan biri), baseline (0.025)'e karşı OOS daily-Sharpe lift'i +0.10 ve üstünde, Holm-corrected p<0.0125 (α=0.05/4) ile, AND shuffle p_gross<0.05, AND per-year sign consistency ≥5/6 üretemez.**

Yani **null'um sweep'in tamamen başarısız olmasıdır** — bu, current floor'un zaten kanıt yüküyle savunulduğu pozisyonun korunması anlamına gelir. Eğer null reddedilirse, gerçek bir fee-erozyon vs trade-rejection tradeoff'unun grid içinde optimum'u bulunmuş demektir.

---

## 2. Gerekçe (RAG referansları)

- **[Brooks deep catalog]:** "stop wide ya da tight tradeoff, level + 2 tick fade vs ATR-multiple". Geniş stop → WR↑ ama R↓; net edge teorik olarak belirsiz, ampirik karar.
- **[Adam Grimes summary]:** range trader %55-60 WR @ R 1.0-1.5; wider stop range trader'da yüksek WR'a destek ama büyük loser riski → "disiplin kritik". Bizim VSA climax test'i range/reversal sınıfında.
- **[Lopez de Prado summary]:** "CPCV ortalama Sharpe>1.0, std<0.5; PBO<0.2" + deflated Sharpe. 4-trial sweep için bile **multiple testing correction zorunlu**.
- **[SMC ICT — liquidity sweep]:** stop "wick'in en uzak ucunun 0.2-0.5× ATR ötesi" → wide-stop'un teorik tabanı; ama crypto OHLCV bar-direction edge'inin SIFIR olduğu 2026-06-02 dersini hatırla (SMC continuation, fbo, sfp hepsi p_gross gate'i geçemedi).
- **[Volume divergence book]:** hacim eşiği sweep önerisi "0.05 adımlarla" — ince grid riski; biz 4 noktayla kalıyoruz.

**RAG zayıflığı:** Hiçbir RAG kaynağı "sl_pct_min'i 0.025'ten 0.030+'a çıkar" şeklinde **spesifik** bir reçete vermiyor. Mantıksal/teorik destek var, ampirik destek YOK. Bu yüzden negatif prior.

---

## 3. Dependent variables (önceden donmuş, primary önce yazıldı)

**Primary (karar verici, tek):**
- OOS daily-Sharpe — best non-baseline vs baseline lift

**Secondary (constraint gates — hepsi pass etmek zorunda):**
- Net mean_R (55bps round-trip dahil) — lift > +0.05R
- MaxDD (account-equity based, ADR-002 doğru base) — champion+5pp tavanı (champion DD-42% → tavan -47%)
- Shuffle p_gross — < 0.05 (yön bilgisi gerçek mi)
- Per-year sign consistency — ≥5/6 yıl pozitif (2021-2026)
- IS/OOS daily-Sharpe ratio — < 1.5 (overfit gate)
- Bonferroni-corrected p — Holm α=0.0125 (4 grid nokta)
- Symbol-out CV minimum Sharpe — ≥ 0 (en kötü sembol bile patlamasın)

**Info-only (karar vermez, raporlanır):**
- Trade count, win rate, average R, fee_R, slip_R

---

## 4. Independent variables (donmuş — tek değişken sweep)

**Sweep edilen TEK parametre:**
- `sl_pct_min ∈ {0.025, 0.030, 0.035, 0.040}` — 4 nokta, ince ara grid YASAK

**Dondurulmuş (champion config'ten ALINDI, değişmeyecek):**
- `vol_z_min`, `vol_z_max`, `spread_atr_min` — champion değerleri
- `climax_intensity_threshold` — champion değeri
- `htf_1d_aligned = true` (sadece OOS-survivor entry filter)
- `risk_pct`, `max_concurrent`, `daily_dd_halt`, `monthly_dd_halt`
- Fee model: 5.5bps taker + 5bps slip (konservatif tarafta)
- Universe: all_liquid_3y, delisting'ler dahil

**Donma garantisi:** Pre-registration commit'i `git_hash`'le bağlı. Sweep süresince başka parametreye dokunulursa hipotez **otomatik invalid** sayılır.

---

## 5. Beklenen p-value ve karar eşikleri

| Test | Eşik | Korunma |
|---|---|---|
| Best non-baseline OOS Sharpe lift | ≥ +0.10 | primary effect size |
| Holm-corrected p | < 0.0125 (α=0.05/4) | multiple testing |
| Shuffle p_gross | < 0.05 | yön-edge null |
| Per-year sign consistency | ≥ 5/6 | regime-luck filter |
| IS/OOS Sharpe ratio | < 1.5 | overfit filter |
| Symbol-out CV min Sharpe | ≥ 0 | concentration risk |
| MaxDD (best variant) | ≤ champion + 5pp | risk gate |

**HEPSİ birlikte pass etmek zorunda.** Tek bir gate düşerse → null reddedilemez → **mevcut floor korunur**.

---

## 6. Stop criteria (early-kill)

Aşağıdaki şartların **herhangi biri** oluşursa araştırma o anda terkedilir, kalan testler çalıştırılmaz, doc `status: REJECTED` olur:

1. **Boundary effect:** Best `sl_pct_min` grid'in uçlarında (0.025 veya 0.040) → grid yanlış kurulmuş, fine-tune YASAK, doc red.
2. **IS Sharpe lift < 0.05:** zaten in-sample bile yok, OOS testine geçme.
3. **Shuffle p_gross > 0.10:** gross direction edge yok (Fabio/SMC pattern'ı tekrar — 2026-06-01/02 dersleri).
4. **Per-year sign:** herhangi bir grid noktasında pozitif yıl sayısı < 4/6 → regime-luck, "vol_z/spread_atr 2026-06-03 trap" tekrar.
5. **IS/OOS ratio > 2.0:** dramatic overfit, ışıkları söndür.
6. **Sembol-konsantrasyon:** toplam PnL'in >%50'si tek bir sembolden → diversifikasyon yok, red.
7. **Champion baseline (0.025) zaten en iyi:** sweep gereksiz, "current optimal" sonucu yaz, doc REJECTED ama bu **olumlu bir red** (existing floor savunulmuş olur).

---

## 7. Reproducibility

- `git_hash`: pre-registration commit'inde kilitlenir
- `config_hash`: champion config'in SHA256'sı
- `data_hash`: data/market.duckdb snapshot SHA256 (2026-06-07 itibarıyla)
- `seed`: backtest engine seed dondurulur (50 seed Monte Carlo perturb için)

Sweep çalıştırılıp sonuç yazıldıktan sonra **bu üç hash + seed** rapor frontmatter'ına işlenir; bit-identical yeniden çalıştırılabilir.

---

## 8. Family-wise gözlem (cross-strategy cousin counter)

Bu hipotez VSA family'de tekil değil — VSA üzerinde son 6 ayda denenmiş cousin sweep/iterate sayısı (climax-intensity, vol_z, spread_atr, htf_1d_aligned) **family-wise N ≥ 5**. Bu yüzden:
- Family-Holm α'nı ek olarak da hesapla (α=0.05/5=0.01) ve raporda göster.
- N ≥ 30'a ulaşırsa Lopez-Prado PBO>0.5 zone'una giriyoruz demektir → VSA ailesinden iterate KAPATILIR, deferred arşiv'e taşınır. Şu an N=5 → güvenli ama izlenir.

---

## 9. Pozitif edge politikası (SOP-4b uyarlaması)

**EĞER** sweep null'u reddederse (yani gerçekten +0.10 OOS Sharpe lift, Holm p<0.0125, shuffle p_gross<0.05, per-year ≥5/6 hepsi pass):

→ **REDDETMEK YASAK** (SOP-4b). Bu pozitif edge — Lab tournament'a `vsa_climax_widestop_v2` adıyla challenger olarak gönderilir; champion v13 ile head-to-head 90-gün paper test'e girer.

**EĞER** sweep null'u reddedemezse:
→ Current floor (0.025) korunur, sonuç `decisions/2026-06-07-vsa-slpct-floor-defended.md` ADR'sine yazılır. Bu **olumlu bir red**: mevcut deployment'ın doğru kalibre edildiği kanıtlanmış olur.

**EĞER** sweep partially pass eder (örn p_gross<0.05 ama per-year 4/6):
→ "Edge gerçek olabilir ama regime-luck şüphesi var" → 6 ay paper-only forward test gözetimine alınır, **deploy YASAK**.

---

## 10. Bağımlılıklar ve onay zinciri

- Bu doc DRAFT olarak yazıldı.
- `requested_review_from`: lab_scientist (tournament setup), risk_officer (DD/concentration gates), adversary_engineer (stress + kill probe).
- Sweep çalıştırılmadan önce **3 reviewer'ın ACK'ı** zorunlu (PROTOCOL §4 SLA: 24h, Risk 6h).
- ACK sonrası: backtest engine + walk-forward + robustness suite tek seferde koşulur, sonuçlar tek raporda toplanır.
- ASLA "0.027 dene, 0.028 dene" yok — 4 nokta sabit, başka değer YOK.

---

## 11. Beklediğim sonuç (pre-registered prediction — honest prior)

Negatif prior'a göre tahminim:
- En olası sonuç (~%55): Stop criterion #4 veya #7 tetiklenir, doc REJECTED (floor savunulur).
- İkinci olası (~%30): IS'de küçük lift (+0.05) ama OOS'da düşer veya per-year flip → REJECTED.
- Üçüncü (~%12): Tek bir grid noktası tüm gate'leri geçer ama lift marjinal (+0.10-0.15) → SOP-4b paper-only forward-test'e taşınır.
- Düşük olasılık (~%3): Dramatic OOS lift (+0.20+) tüm gate'leri geçer → genuine edge, Lab tournament'a.

Bu tahmini yazmamın sebebi: sweep bittiğinde sonuçların prior'a "şüpheli derecede uyup uymadığını" görmek. Aşırı uyum → ben sonuca yönlendirici bias soktum demektir; aşırı sapma → priors'ım yanlıştı, sebebini araştırmam gerekir.

---

**Pre-registration commit hash buraya commit anında yazılacak — sonra DEĞİŞTİRİLEMEZ.**
