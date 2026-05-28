---
doc_id: researcher-20260527T100000-daily-scan-shuffle-null-v1v2-companion-precheck
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T10:00:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
blocks:
  - lab-tournament-decision-v1-vs-v2
requested_review_from:
  - lab_scientist
  - adversary_engineer
tags:
  - hypothesis
  - pre-registration
  - daily-scan
  - shuffle-null
  - selection-bias-test
  - negative-control
  - cross-strategy
  - 15m
supersedes: null
hash: null
---

# HYP-2026-05-27 — Daily Scan: v1/v2 Companion Pre-Check via Shuffle-Null

## 0. Bağlam — Neden bugün YENİ strateji yazmıyorum

**SOP-5 ihlali açıkça flag:** RAG retrieve k=10 → **0 hit**. Literatür desteği yok.
Kural: "RAG bulgu yoksa hipotezi terk etmeyi düşün." Buna ek:

1. **Queue dolu.** 2026-05-26'da aynı seed altında v1 (`unconditional ρ ≤ 0.20`) ve
   v2 (`tail ρ_dd ≤ 0.30`) sibling pre-reg'leri yazıldı, ikisi de hâlâ
   `status: DRAFT`. CEO arbitrate beklemede. Üçüncü bir paralel hipotez
   eklemek effective-N'i şişirir, Bonferroni kütlesini ağırlaştırır.
2. **KPI rejimi.** Aylık %20-40 terfi oranı hedefi. Son 30 günde 7 hipotez
   yazıldı, 5 RED. Yeni strateji üretiminin marjinal değeri düşük; mevcut
   pipeline'ın overfit-temizliği daha yüksek değerde.
3. **Learning 2026-05-13 ders:** Karşı-hipotez (negatif kontrol) yazılmasaydı
   EER v1 false-positive olarak Lab'e gönderilirdi. Aynı disiplini v1/v2
   companion seçimine **şimdi** uygulamak gerekiyor.

Bu yüzden günlük tarama çıktısı = **negatif kontrol pre-registration**.
İddianın kendisi v1/v2'nin selection-bias dayanıklılığını ölçer.

## 1. İddia (H1, tek cümle, ölçülebilir)

> v1 ve v2 companion seçim prosedürünün (66 raf adayı içinde `vsa_climax_test_15m`
> ile en düşük korelasyona sahip standalone-Sharpe ≥ 0.80 strateji bulma)
> **gerçek vsa_climax_test'in DD pencereleri** üzerindeki **selection-score'u**,
> aynı prosedürün **vsa_climax_test'in shuffled-DD-windows** üzerindeki selection-
> score'undan istatistiksel olarak ayrılabilir (one-sided permutation p ≤ 0.05,
> B=500 permütasyon). Yani: prosedür "bilgisiz baseline"i p≤0.05'le yener.

**Selection-score tanımı (pre-registered, kapalı):**
`score(candidate) = standalone_OOS_Sharpe(candidate) − 2.0 × max(0, ρ − 0.30)`
burada ρ = candidate ↔ vsa_climax_test conditional bar-return correlation
(DD-window içinde). Top-1 candidate'in score'u "selection score"dur.

## 2. Null hipotez (H0)

Gerçek DD windows ↔ shuffled DD windows arasında selection-score dağılımı
ayrılamaz (one-sided p > 0.05). Yani: v1/v2 prosedürü **bilgi-rejimi vs
gürültü-rejimi** ayrımı yapamıyor → companion iddiası **selection bias**
ürünüdür, Lab tournament'a girerse %95+ olasılıkla data-mined winner.

**Çürütür:** B=500 permütasyon altında gerçek-score quantile ≥ %5 (yani null
dağılım gerçek-score'u rahat üretebiliyor).

## 3. Gerekçe (literatür → BOŞ; ikincil/dahili)

- RAG: 0 hit. Tail-correlation literature (Bailey/López de Prado 2016,
  "Building Diversified Portfolios") hafızadan biliniyor ama corpus'ta yok.
- **Asıl gerekçe:** v1/v2 pre-reg'lerinin §3'ünde her ikisi de "RAG ref boş"
  flag'lemiş. İkincil/hafıza-temelli iddialar için shuffle-null **standart**
  prosedürdür (López de Prado 2018 *Advances in Financial ML*, ch.7 — yine
  RAG'de yok, hafızadan).
- **Yan-gerekçe (sayı):** 66 candidate × 2 procedure (v1, v2) = 132 effective
  test. Bonferroni p = 0.05/132 = 3.8×10⁻⁴. Shuffle-null **bu kütleyi
  kontrol etmenin tek istatistiksel-temiz yolu** çünkü candidate'ler arası
  korelasyon Bonferroni'yi over-conservative yapıyor — permutation test
  empirical null'u doğrudan veriyor.

## 4. Bağımsız değişkenler (parametre uzayı — DAR tutuldu)

- Permütasyon sayısı B: **500** (sabit, ablation yok)
- Shuffle birimi: **30-bar DD pencereleri** (block-shuffle, time-of-day korunur)
- DD eşiği: **5%** (v2 ile birebir aynı — değiştirilmez)
- Candidate evren: **66 raf adayı** (CEO 2026-05-26 raf listesi, dondurulmuş)
- Korelasyon tipi: **conditional bar-return ρ** (v2 ile birebir aynı)
- Seed: 42 (deterministic; reproducibility için config'e yazılır)

Toplam serbestlik derecesi: **TEK trial**. Grid yok. Curve-fit yüzeyi sıfır.

## 5. Bağımlı değişkenler (pre-registered metrikler)

| Metrik | Tanım | Pre-reg değer |
|---|---|---|
| `score_real` | Gerçek DD windows'ta top-1 selection score | tek skalar |
| `score_null_dist` | B=500 shuffle altında selection score dağılımı | empirical CDF |
| `p_one_sided` | (1 + #{score_null ≥ score_real}) / (B+1) | ≤ 0.05 → PASS |
| `quantile_real` | score_real'in null dağılımdaki yüzdelik konumu | ≥ 95th → PASS |
| `null_mean ± sd` | Bilgilendirici (effect-size için) | rapor |
| `effect_size` | (score_real − null_mean) / null_sd | bilgi |

## 6. Kabul kriteri (PASS / FAIL gate)

**PASS (v1/v2 Lab tournament'a girebilir):**
- `p_one_sided ≤ 0.05` VE
- `score_real` ≥ `null_mean + 1.5 × null_sd` (effect-size sanity)

**FAIL (v1 ve v2 RED — Lab tournament iptal):**
- `p_one_sided > 0.05` VEYA
- `score_real` null mean'in ±1 sd içinde (procedure bilgi vermiyor)

**BORDERLINE (0.05 < p ≤ 0.10):**
- "Belirsiz, ek veri" — başka DD eşiklerinde (3%, 8%) tek-replikasyon test;
  her ikisi de p≤0.10 ise PASS sayılır, biri p>0.15 olursa FAIL.
- Bu borderline rule **şimdi yazıldı, sonra revize edilmez** (post-hoc patch
  yok).

## 7. Anti-overfit / curve-fit şüpheleri (kendim flag)

1. **Block-shuffle window büyüklüğü.** 30-bar = v2 ile aynı tutuldu;
   "alternatif window dene" yetkisi reddedildi (HARC eğilim).
2. **Candidate evren dondurma.** 2026-05-26 CEO raf listesi commit hash ile
   kilitleniyor. Yeni candidate eklenirse yeni hipotez gerekir.
3. **Selection score formülü.** `λ=2.0` cezası **şimdi yazıldı**, sweep
   yapılmaz. Sweep yapılırsa shuffle-null'un kendisi data-mined olur.
4. **Reproducibility.** `(git_hash, config_hash, data_hash, seed=42)`
   sonuçla beraber rapora yazılır; bit-identical replay zorunlu.
5. **Çoklu test.** Tek hipotez, tek p-value. Bonferroni gerek yok.

## 8. Önsel tahmin

**Strong opinion, loosely held:** v1/v2 prosedürü FAIL edecek diye %55-65
ihtimal veriyorum. Sebep: vsa_climax_test'in DD pencereleri **piyasa-geneli
risk-off pencereleri**dir (bütün crypto birlikte düşer). Shuffled DD
pencereleri RANDOM 30-bar dilimler de **çoğunlukla** risk-off'a denk gelir
(crypto vol-clustered). Yani null dağılım, gerçek dağılımdan dramatik
ayrılmayabilir → p ~ 0.10-0.30 bandı tahmin.

**Bu tahmin doğruysa:**  v1/v2 ikisi de RED, Lab tournament 1-2 haftalık
boşa-cycle önlenir.

**Bu tahmin yanlışsa (p ≤ 0.05):** v1 ve v2 selection-bias-clean,
CEO arbitrate'i sağlam zeminde yapar.

## 9. Stop criteria

- B=500 permütasyon bittikten **sonra** ek permütasyon koşulmaz (p-hack yok).
- Sonuç borderline çıkarsa §6'daki "3%, 8% replikasyon" yolu izlenir;
  başka hiçbir yan yol açılmaz.
- Sonuç PASS çıksa bile **v1 vs v2 arasında tercih yapma yetkim yok** —
  o Lab + CEO arbitrate kararı.

## 10. Hesaplama maliyeti & timeline

- 1 candidate × 66 evren × 500 permütasyon ≈ 33,000 conditional-ρ hesabı.
- vectorbt cached pool ile tahmin: **~20-40 dk single-process**.
- Hedef tamamlanma: **2026-05-28 EOD**.
- Çıktı: `reports/research/2026-05-28_v1v2_shuffle_null.html` +
  bu doc'un §11'inde SONUÇ tablosu.

---

## 11. SONUÇ — (hesap sonrası doldurulacak, ŞİMDİ BOŞ)

```
score_real:       ___
null_mean ± sd:   ___ ± ___
quantile_real:    ___ %
p_one_sided:      ___
effect_size:      ___ σ
Verdict:          PASS / FAIL / BORDERLINE
Reproducibility:  git=___, config=___, data=___, seed=42
```
