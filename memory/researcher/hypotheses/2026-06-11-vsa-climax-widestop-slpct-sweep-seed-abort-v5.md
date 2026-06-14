---
doc_id: researcher-20260611T120000-vsa-climax-widestop-slpct-sweep-seed-abort-v5
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T12:00:00Z
status: REJECTED
confidence: high
depends_on:
  - researcher-20260607T060000-vsa-widestop-slpct-sweep
  - lesson-widestop-threshold-validated
  - learning-vsa-honest-reconciliation-20260603
  - learning-per-year-sign-consistency
  - lesson-overfitting-red-flags
blocks: []
requested_review_from: [lab_scientist, adversary_engineer]
tags: [hypothesis, vsa, widestop, parameter_sweep, seed_abort, family_wise_inflation, curve_fit_risk, negative_prior]
supersedes: researcher-20260607T060000-vsa-widestop-slpct-sweep
hash: null
---

# HYP-2026-06-11: vsa_climax_test — wide-stop `sl_pct_min` sweep (SEED-ABORT v5)

## TL;DR — Karar

**SEED ABORT.** Bu hipotezi backtest'e koymuyorum, sebep family-wise inflation + 4 önceki abort + canonical floor zaten validated + canlı champion artık VSA değil (v14). Aşağıda neden + override koşulları.

---

## 0. Curve-fit şüphesi (önce yazıyorum, sonra koşmuyorum)

Bu seed'in **dürüst durumu**:

| Önceki deneme | Tarih | Sonuç |
|---|---|---|
| v1 (50% prior) | 2026-05-30 | seed-abort (negatif prior, family-wise) |
| v2 | 2026-05-30 | seed-abort |
| v3 (canonical) | 2026-06-03 | hipotez yazıldı, çürütüldü → floor savunuldu |
| v4 (full rigor) | 2026-06-07 | pre-registered, negatif prior + 7 stop criteria + family-N=5 |
| **v5 (bu doc)** | **2026-06-11** | **SEED-ABORT öneriyorum** |

**4 tekrar denenmiş** bir parametre sweep'i 5. kez denemek = **p-hacking by repetition**. Her tekrarda Holm/Bonferroni'yi sıfırlıyormuş gibi davranmak entelektüel olarak dürüst değil — birikimli α uçtu.

Önceden bilinenler (değişmedi):
1. **Live floor (`sl_pct_min=0.025 @ 15m`) zaten "fee-erozyon kalkanı" olarak validated** (`memory/MEMORY.md → widestop-threshold-validated`). Düşürmek BLOCKED. Yukarı çıkarmanın da empirical desteği yok.
2. **VSA champion honest reconciliation negatif:** mR=+0.08, total_ret=-9.2%, DD=-42% (2026-06-03 learning). Sweep'in optimize ettiği rejim zaten dejenere.
3. **Canlı sistem artık v14** (11 Haz 01:04 TR deploy, 5-strateji ensemble, Grimes diversifier dahil). VSA tek başına champion DEĞİL → sweep'in optimize ettiği "VSA only" config canlı kararını etkilemez; bu academic noise.
4. **Family-wise N ≥ 12** (VSA widestop direct=5, cousin volz/intensity/htf=4, exit-parity+entry-quality=2, conviction=1). Lopez-Prado PBO uyarı eşiği (30) yaklaşıyor; **VSA family iterate kapasitesi tükenmek üzere**.
5. **SOP-4b'nin "pozitif edge'i koruma" maddesi BU SEED için karşılanmıyor** — çünkü ortada henüz korunacak pozitif edge yok (mR=+0.08, DD -42%); öncesinde positive base var olmalı.

Bu yüzden v5'in **default kararı SEED-ABORT**, override için sertleştirilmiş bar var (bkz §6).

---

## 1. İddia (pre-registered, numeric — ama default'ta koşulmayacak)

> 15m timeframe'de, `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` config'i v14 öncesi snapshot'tan dondurulmuş şekilde, `sl_pct_min ∈ {0.025, 0.030, 0.035, 0.040}` (4 nokta, sabit), 3y in-sample + 6m walk-forward OOS, all-liquid USDT-perp evreni (delisting'ler dahil), fee 5.5bps taker + 5bps slip:
>
> **En iyi non-baseline grid noktası baseline'a karşı:**
> - OOS daily-Sharpe lift ≥ **+0.15** (önceki v4'te +0.10'du — family-wise inflation cezası olarak yükseltildim)
> - Family-wise Holm-corrected p < **0.05 / 12 = 0.00417** (family-N=12 cezası uygulandı)
> - Shuffle p_gross < 0.05
> - Per-year sign consistency ≥ **6/6** (önceki ≥5/6'dan sıkılaştırıldı — family-wise için)
> - IS/OOS Sharpe ratio < **1.3** (önceki <1.5'tan sıkılaştırıldı)
> - MaxDD ≤ champion + **3pp** (önceki +5pp'dan sıkılaştırıldı)
> - Symbol-out CV min Sharpe ≥ 0
>
> ÜRETEMEZ.

Null = "Tüm gate'leri AYNI ANDA geçen non-baseline grid noktası yok." Sweep'in null'u reddetmesi family-N=12 düzeltmesi altında neredeyse imkânsız (toplam toplam α budget'ı tükendi).

---

## 2. Gerekçe (RAG referansları + neden seed-abort)

**RAG'ın söylediği:**
- **[Brooks deep catalog #4]:** wide vs tight stop ampirik karar; teorik yön yok.
- **[Adam Grimes #5]:** range trader %55-60 WR @ R 1.0-1.5 — VSA climax bu sınıfta, ama "wider stop tek başına edge değil, confluence ister."
- **[Lopez de Prado #3]:** "CPCV Sharpe>1.0, std<0.5, PBO<0.2, deflated Sharpe" — family-N=12 için deflated Sharpe penaltısı bu sweep'in spurious-likelihood'ını **>0.4** yapıyor (Bailey-Lopez de Prado 2014). Yani sweep PASS etse bile false-positive olasılığı %40+.
- **[Volume divergence book #2]:** "0.05 adım sweep" önerisi vAR — biz 4 nokta diyoruz; yine de family-wise içinde değersiz.
- **[SMC ICT liquidity sweep #1]:** stop "wick'in 0.2-0.5× ATR ötesi" — wide-stop teorik desteği var, ampirik destek YOK (2026-06-02 SMC family RED dersini hatırla).

**RAG'ın söylemediği:** Hiçbir kaynak "VSA climax test için sl_pct_min'i sweep et, 5. denemende edge çıkacak" demiyor. RAG zayıf, prior tekrar tekrar negatif.

**Neden seed-abort:** RAG çıkmaza girmiyor (sayı zayıf), önceki 4 deneme negatif, family-wise α budget tükendi, canlı champion zaten v14 → sweep çıktısı deploy hattına bile değemiyor. SOP-4'ün "3+ iterate denemesi sonrası hala gate'i geçemedi → gerekçeli arşiv" maddesi tetiklenmiş.

---

## 3. Dependent variables (override olursa — donmuş, primary önce)

**Primary (tek karar verici):**
- OOS daily-Sharpe lift, best non-baseline vs baseline

**Secondary gates (HEPSİ pass etmek zorunda):**
- Family-Holm p (α=0.05/12=0.00417)
- Shuffle p_gross < 0.05
- Per-year sign ≥ 6/6
- IS/OOS Sharpe ratio < 1.3
- MaxDD ≤ champion + 3pp (account-equity base, ADR-002)
- Symbol-out CV min Sharpe ≥ 0
- Deflated Sharpe (Bailey-Lopez de Prado) > 0 with PBO < 0.2

**Info-only:** trade count, win rate, fee_R, slip_R, regime split distribution.

---

## 4. Independent variables (donmuş)

**Sweep edilen TEK parametre (override olursa):**
- `sl_pct_min ∈ {0.025, 0.030, 0.035, 0.040}` — 4 nokta. Daha ince grid YASAK (curve-fit hard limit).

**Dondurulmuş (champion vsa2 config'inden — DEĞİŞMEZ):**
- `vol_z_min`, `vol_z_max`, `spread_atr_min`, `climax_intensity_threshold`
- `htf_1d_aligned = true`
- `risk_pct`, `max_concurrent`, `daily_dd_halt`, `monthly_dd_halt`
- Fee 5.5bps taker + 5bps slip, universe all_liquid_3y delisting'ler dahil

Donma garantisi: pre-registration `git_hash`. Başka parametreye dokunulursa hipotez otomatik invalid.

---

## 5. Beklenen p-value ve karar eşikleri (override pathway)

| Test | Eşik (v4'ten sertleştirildi) | Korunma |
|---|---|---|
| Best non-baseline OOS Sharpe lift | ≥ **+0.15** (was +0.10) | family-wise effect-size penalty |
| Family-Holm p | < **0.00417** (α=0.05/12) | family-N=12 correction |
| Shuffle p_gross | < 0.05 | yön-edge null |
| Per-year sign | ≥ **6/6** (was 5/6) | regime-luck filter |
| IS/OOS Sharpe ratio | < **1.3** (was 1.5) | overfit filter |
| Symbol-out CV min Sharpe | ≥ 0 | concentration |
| MaxDD (best variant) | ≤ champion **+3pp** (was +5pp) | risk gate |
| Deflated Sharpe (Bailey-Lopez de Prado) | > 0 with PBO < 0.2 | family-wise spurious-fit cezası |

**HEPSİ AYNI ANDA pass etmek zorunda.** Aksi halde null savunulur (= floor 0.025 korunur).

---

## 6. Stop criteria + override koşulları

### 6a. Default action: SEED-ABORT

Bu doc `status: REJECTED` olarak commit ediliyor. Backtest çalıştırılmıyor. Sebep §0'da.

### 6b. Override için gereken (Principal veya CEO yazılı talimat)

Eğer override istenirse, **tüm** aşağıdakiler karşılanmalı:
1. Principal veya CEO'dan yazılı `directive` doc (PROTOCOL §5) — "VSA family-N=12 olmasına rağmen v5'i koş, sebep X."
2. Risk Officer ACK — "MaxDD champion+3pp ve daily_dd_halt korunmuş halde override OK."
3. Adversary Engineer kill-probe — "şu 4 grid noktasının her birinde flash-crash + LUNA + FTX stress'i yaz, sonra koş."
4. Family-wise N=12 düzeltmesinin **raporda explicit** gösterileceği (Holm α=0.00417 + deflated Sharpe).

### 6c. Override sonrası early-kill (v4'ten devralındı + sertleştirildi)

1. **Boundary effect:** Best `sl_pct_min` ∈ {0.025, 0.040} → grid yanlış, fine-tune YASAK, REJECTED.
2. **IS Sharpe lift < 0.05:** in-sample bile yok, OOS'a geçme.
3. **Shuffle p_gross > 0.05:** gross direction edge yok.
4. **Per-year sign:** herhangi bir grid noktasında pozitif yıl < 5/6 → REJECTED.
5. **IS/OOS ratio > 1.8:** dramatic overfit.
6. **Symbol concentration:** toplam PnL >%50 tek sembolden → REJECTED.
7. **Baseline 0.025 zaten en iyi:** sweep gereksiz, "current optimal" yaz, REJECTED (= floor savunulmuş, olumlu red).
8. **YENİ — Deflated Sharpe penalty:** family-N=12 düzeltmesinden sonra DSR ≤ 0 → REJECTED, family arşive deferred.

---

## 7. Reproducibility

- `git_hash`: commit zamanı kilitlenir
- `config_hash`: champion vsa2 config SHA256
- `data_hash`: data/market.duckdb snapshot SHA256 (2026-06-11)
- `seed`: backtest engine seed dondurulur

---

## 8. Family-wise gözlem (KRİTİK)

| VSA family cousin | Sayı | Notlar |
|---|---|---|
| widestop/sl_pct_min sweep | 5 (v1-v4 + v5 bu doc) | hepsi negatif/abort |
| vol_z threshold sweep | 4 | hepsi seed-abort/REJECTED |
| climax intensity sweep | 1 | OOS lift yok |
| htf_1d_aligned isolation | 1 | hala live'da, tek survivor |
| exit-parity / v12 entry-quality | 2 | exit parity ✗, v12 ✗ |
| **TOPLAM family-N** | **≥ 12** | **PBO uyarı bandında** |

**Lopez-Prado PBO eşiği:** Family-N ≥ 30 → "iterate kapısı kapanır, deferred archive". Şu an 12 → henüz kapalı değil ama her yeni v iterate yarım adım daha **PBO>0.5 zone'a sokuyor**.

**Önerim:** Bu seed (vsa_climax_test widestop) için **iterate budget tükendi sayılsın**. Çünkü:
- Pozitif edge baz çizgisi yok (mR=+0.08, DD -42% → SOP-4b "korunacak pozitif edge" şartı sağlanmıyor)
- 4 önceki deneme negatif
- Live champion artık VSA değil
- Family-wise N pahalı

→ `decisions/2026-06-11-vsa-climax-widestop-iterate-budget-exhausted.md` ADR önerisi (Principal onayı ile).

---

## 9. SOP-4b uyarlaması (POZİTİF EDGE YOK, koruma anlamsız)

SOP-4b "POZİTİF EDGE'İ KORUMA" maddesi:
> "Eğer bir hipotez/strateji pozitif aylık ROI üretiyorsa ama DD veya başka bir risk metriği kötüyse, bunu reddetmek yerine geliştir."

**Bu seed için TETİKLENMİYOR**, çünkü:
- VSA champion honest reconciliation: mR=+0.08, total_ret=**-9.2%**, monthly negatif → korunacak pozitif edge yok.
- "Pozitif edge nadir bir kaynak" — burada kaynak yok, sadece pozitif edge sanılan curve-fit kalıntısı var.

SOP-4b yanlış uygulanırsa **gerçekten negatif olan stratejiyi diriltme** riskine girer; bu yanlışı yapmıyoruz.

---

## 10. Beklediğim sonuç (pre-registered prediction — koşulmuyor ama not için)

Eğer override edilip koşulursa, prior:
- (~%80) Default null savunulur, REJECTED, floor=0.025 korunur, family iterate kapısı kapanır.
- (~%15) Marjinal lift IS'de (+0.05-0.08) ama OOS'da düşer veya per-year flip → REJECTED.
- (~%4) Tek grid noktası tüm gate'leri geçer ama family-Holm + DSR sonrası anlamlılık kayboluyor → REJECTED.
- (~%1) Genuine effect (lift ≥+0.20, DSR>0, per-year 6/6, family-Holm pass) → Lab tournament'a `vsa_climax_widestop_v5` challenger. Bu olasılık prior'a göre çok düşük, ama açık.

---

## 11. Bağımlılıklar ve onay zinciri (override pathway)

- Bu doc DEFAULT `status: REJECTED`. Backtest **çalıştırılmıyor**.
- `requested_review_from`: lab_scientist (family-N=12 confirm), adversary_engineer (kill-probe gerekirse).
- Override request → Principal/CEO yazılı `directive` doc'u + Risk Officer ACK + Adversary kill-probe.
- Override sonrası ACK + Holm α=0.00417 + DSR + PBO ekranda → backtest tek seferde koşulur.
- ASLA "0.027 dene, 0.028 dene" yok — 4 nokta sabit.

---

## 12. Karar (pre-registered, final)

- [x] **SEED-ABORT / REJECTED** — family-wise N=12 + 4 önceki abort + canonical floor validated + live champion artık VSA değil
- [ ] Override pending (Principal directive bekleniyor)
- [ ] Backtest koşuldu, sonuç ayrı raporda

**Arşivleme gerekçesi:** "vsa_climax_test widestop sl_pct_min sweep" seed'i için iterate budget tükendi; family iterate kapısı VSA için PBO>0.5 zone'una yaklaşıyor. Bu doc kanıtla birlikte arşive girer, yeni VSA-widestop sweep önerisi en az 60 gün soğuma + yeni out-of-sample data window olmadan üretilemez.

**Sonraki adım önerisi:** Researcher capacity'i şuraya yönlendirilsin:
- VSA-DIŞI ortogonal alfa (Grimes ABC'nin canlıda davranışı, BOS-Donchian, AVWAP) — düşük korr diversifier
- v14 ensemble post-deploy attribution analizi (Analyst SOP)
- Forex 4H feasibility (paper-only, SPK-bloklu)

---

**Pre-registration commit hash burada bağlanır; sonra DEĞİŞTİRİLEMEZ.**
