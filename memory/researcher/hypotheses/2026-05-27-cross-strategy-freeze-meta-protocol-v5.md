---
doc_id: researcher-20260527T173000-cross-strategy-freeze-meta-protocol-v5
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T17:30:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
  - researcher-20260527T140000-cross-strategy-trade-arrival-disjoint-companion-v3
  - researcher-20260527T160000-cross-strategy-orthogonal-alpha-companion-v4
  - active-state-current
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
  - ceo
tags:
  - hypothesis
  - pre-registration
  - meta-protocol
  - cross-strategy
  - freeze
  - holm-bonferroni
  - fwer
  - p-hacking-guard
  - vsa_climax_test
  - sibling-v5
  - curve-fit-flag
supersedes: null
hash: null
---

# HYP-2026-05-27-v5 — FREEZE Meta-Protocol for vsa_climax_test Companion Search

## 0. Neden bu bir hipotez değil de meta-protokol?

Aynı seed (`Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek bir strateji`) altında **5 gün arka arkaya** sibling pre-registration yazıldı:

| Sibling | Eksen | Eşik | doc_id (kısaltma) |
|---|---|---|---|
| v1 | Unconditional Pearson ρ_bar | ≤ 0.20 | …T180000-low-corr-companion |
| v2 | Drawdown-conditional ρ_dd | ≤ 0.30 | …T214500-tail-corr-v2 |
| v3 | Trade-arrival Jaccard τ | ≤ 0.10 | …T140000-trade-arrival-v3 |
| v4 | OLS-residual (β, IR_resid) | β ≤ 0.30, IR ≥ 0.60 | …T160000-orthogonal-alpha-v4 |
| **v5 (bu doc)** | **— YENİ EKSEN YAZILMIYOR —** | **FREEZE + Holm-Bonferroni** | — |

**Doğru hareket v5 olarak yeni bir eksen (mutual information, copula tail, ML-meta vs.) yazmak DEĞİL.** Çünkü her ek sibling family-wise error rate'i şişirir; bir noktada "şans eseri en az biri geçer" olasılığı %100'e yaklaşır. Renaissance/Two-Sigma disipliniyle uyumlu olan tek hamle: **seçim kümesini DONDUR, çoklu-test düzeltmesini pre-register et, v5+ sibling'leri yasakla**. Bu doc o protokoldür.

Bu bir hipotezdir çünkü ölçülebilir bir empirical iddia içerir (§1): "Holm-Bonferroni düzeltmesi sonrası v1-v4'ten **0 sibling** terfi eder" null'una karşı.

## 0.1 RAG Şerhi (SOP-5 ihlali — açıkça flag)

**RAG retrieve k=10 → 0 hit.** Literatür: yok. Hatırladığım kaynaklar (RAG sayılmaz, hafıza):
- Holm (1979), *Scandinavian J Stat* 6(2): sequential rejective Bonferroni — uniformly more powerful than vanilla Bonferroni.
- Bailey & López de Prado (2014), *J Portfolio Mgmt*: Deflated Sharpe Ratio + selection bias.
- Harvey & Liu (2014), *Backtesting*: family-wise multiple-testing protocol for finance research.
- Romano & Wolf (2005): stepdown methods, FWER control altında power optimization.

Hipotez metodolojiye dayanıyor (bir companion seçim turnuvasının doğru istatistik kapatması). RAG dolunca Harvey-Liu (2014) §3 ve Romano-Wolf bootstrap stepdown eklemesi tavsiye edilir.

## 1. Iddia (pre-registered, tek cümle, ölçülebilir)

> v1, v2, v3, v4 sibling'lerinin pre-registered gate'leri **donmuş 66 aday raf** üzerinde paralel koşulduğunda, **Holm-Bonferroni FWER düzeltmesi (α=0.05, m=264)** sonrası **en az bir sibling × aday çiftinin** kombinasyon gate'lerini (net annual ≥ %25, Sharpe artışı ≥ %20, MaxDD artışı ≤ +4pp, DSR ≥ 0.45) eş zamanlı geçme olasılığı **p ≤ 0.05**'tir.
>
> Ek kantitatif iddialar (hepsi ölçülür, hepsi gate):
> - **En fazla 1 sibling × aday çifti** FWER-düzeltilmiş eşiği geçer (XOR korunur).
> - Eğer 2+ çift geçerse → CEO arbitrate ADR şarttır, paralel deploy YASAK.
> - Eğer 0 çift geçerse → seed RED + 90 gün moratoryum (yeni v6+ sibling yazılamaz).
> - vsa_climax_test live baseline referansı **MaxDD = -15.48%** (v1-v4'ün -17.00% varsayımını düzeltir; kaynak `realistic_backtest_results/live-bot-baseline-vsa-widestop.realistic.json` row 13, 2026-05-27 06:56 UTC).
> - Combo MaxDD üst sınırı: **-15.48% + 4pp = -19.48%** (v1-v4'teki -21/-22 yerine).

## 2. Null Hipotez (H₀)

> H₀: v1-v4 sibling × 66 aday matrisinde, Holm-Bonferroni düzeltmesi sonrası **hiçbir çift** kombinasyon gate'lerini geçemez. Tüm pozitif görünen sonuçlar, dört filtre × 66 aday üzerindeki çoklu-test gürültüsü ile açıklanır.
>
> H₀ doğru ise: seed kapanır, 90 gün boyunca yeni sibling yazılamaz, vsa_climax_test tek başına çalışmaya devam eder (companion arayışı moratoryuma alınır).

## 3. Gerekçe (RAG ref → BOŞ; metodolojik)

- **RAG:** 0 hit. ❌
- **İçsel kaynak (RAG değil):**
  - 4 sibling'in 5 günde yazılması açık bir **p-hacking sinyali** — her başarısız yaklaşımdan sonra yeni bir eksen denenmesi `learning.md` "anti-narrative bias" kayıtlarımla çelişiyor.
  - v1 ilk koşumda 6-strateji örneklemde tüm çiftlerde `|ρ| < 0.10` çıktı; bottleneck zaten ρ değildi → her yeni sibling eksenini "boşlukta arıyoruz" hissi.
  - Active state (`active-state-current`) gösteriyor ki şu anda canlıda 1 tek bot var ve 2 günden beri 0 entry; "companion" eklemenin operasyonel marjı düşük, acele etmek için sebep yok.
- **Metodoloji:** Harvey-Liu (2014) finans backtesting'inde m=tüm test edilen strateji-konfigürasyon kombinasyonları olarak FWER düzeltmesini şart koşar. Bizim m = 4 sibling × 66 aday = **264** (her sibling × aday çifti bir bağımsız "test"tir — gate eşikleri farklı, eksenler farklı). Bonferroni eşiği: `α/m = 0.05/264 = 1.89 × 10⁻⁴`. Holm-Bonferroni stepdown bundan daha güçlü.

⚠️ Bu hipotez **kasıten konservatif**. Disiplini koruma amacı: 5 sibling'de bir "şans eseri" terfi adayı yakalamak yerine, **gerçek edge yoksa kapatmaya** hazır olmak.

## 4. Dependent Variables (ölçülecek)

| Metrik | Tanım | Ölçüm |
|---|---|---|
| `p_holm_min` | v1-v4 × 66 aday matrisinde Holm-stepdown sonrası en küçük adjusted p | analytic |
| `n_passing_pairs` | FWER-düzeltilmiş gate'leri geçen (sibling, aday) çifti sayısı | enum |
| `xor_violated` | n_passing_pairs > 1 ise True | boolean |
| `combo_sharpe_uplift_max` | Geçen çiftler arasında en yüksek Sharpe artışı (% vsa standalone'a göre) | computed |
| `combo_maxdd_max` | Geçen çiftler arasında en kötü MaxDD | computed |
| `dsr_max` | Geçen çiftler arasında en yüksek DSR (Bailey-LdP, m=264) | computed |
| `bootstrap_fwer_realized` | 10000 block-bootstrap permutasyon altında null-dağılımdan empirical FWER | empirical |
| `seed_outcome` | {promote_one, arbitrate_needed, full_reject_moratorium} | categorical |

## 5. Independent Variables (manipüle edilen / dondurulan)

| Değişken | Aralık / Set | Curve-fit riski |
|---|---|---|
| Sibling sayısı (m₁) | **4 sabit** (v1-v4 dondurulur) | sıfır — v5+ yasak |
| Aday sayısı (m₂) | **66 sabit** (raf SHA256 snapshot v1-T0'da kilitli) | sıfır — yeni hipotez eklemek bu hipoteze dahil değil |
| FWER hedefi (α) | **0.05 sabit** | sıfır — pre-register |
| Düzeltme metodu | **Holm-Bonferroni** (vanilla Bonferroni ve Šidák paralel rapor) | düşük — yöntem kilidi |
| Sibling gate'leri | v1-v4'ün **kendi pre-registered** eşiklerinin AND'i | sıfır — değiştirilemez |
| Kombinasyon ağırlığı | 50/50 risk eşit | sıfır — v1-v4 ile aynı, optimize edilmez |
| Bootstrap blok boyutu | 20 bar (5 saat) | düşük — robustness için {10, 20, 40} rapor edilir |
| Bootstrap replication | 10000 | düşük — pre-register |

**Curve-fit imzası: SIFIR.** Bu hipotez bir filtreyi optimize etmiyor — mevcut 4 filtreyi DONDURUP istatistik prosedürünü kilitliyor.

## 6. Beklenen p-value & Multiple Testing

- **m = 264** (4 sibling × 66 aday).
- **Bonferroni eşiği:** `α/m = 1.89 × 10⁻⁴`.
- **Holm-Bonferroni (stepdown):**
  1. Tüm (sibling, aday) çiftlerinin p-değerlerini hesapla, küçükten büyüğe sırala: p_(1) ≤ p_(2) ≤ … ≤ p_(264).
  2. İlk i için `p_(i) > α/(m−i+1)` olan en küçük i'yi bul.
  3. p_(1) … p_(i−1) reddedilebilir; geri kalanı reddedilemez.
- **Šidák alternatifi:** `1 − (1−α)^(1/m) ≈ 1.94 × 10⁻⁴` — Bonferroni ile neredeyse aynı, rapor edilir.
- **Bootstrap FWER (Romano-Wolf):** 10000 block-bootstrap (block=20 bar, ayrıca {10, 40} robustness) altında null dağılımdan empirical FWER hesaplanır. Bu, sibling ve aday'lar arasındaki bağımlılığı dikkate alan en güçlü düzeltme; ana karar bunda.
- **DSR (Bailey-LdP):** `E_max_Sharpe(N=264)` ile her geçen çift için ek deflasyon.
- **Beklenti:** Hiçbir gerçek edge yoksa, FWER düzeltmesi sonrası `P(en az 1 çift geçer | H₀) ≈ 0.05` (tasarımın gerektirdiği). Eğer gerçekten ≥1 çift geçerse, edge gerçek olma olasılığı (Bayes posterior, uniform prior altında) ≥ 0.60.

## 6.5 v1-v4'ün Önceki Çoklu-Test Cümleciklerinin Sentezi

| Sibling | Önceki Bonferroni N | Bu hipotezdeki gerçek N | Fark |
|---|---|---|---|
| v1 | 66 | 264 | 4x |
| v2 | 132 (v1∪v2) | 264 | 2x |
| v3 | 198 (v1∪v2∪v3) | 264 | 1.33x |
| v4 | 264 (family-wise, v4 zaten doğru identifiye etmişti) | 264 | 1x — v4 doğru hesaplamıştı |

v4 family-wise N=264'ü hesapladı; bu doc o sayıyı **resmi gate olarak kilitliyor** ve **prosedürü** (Holm + Romano-Wolf) ekliyor. v1-v3'ün Bonferroni N=66 cümleceği bu meta-protokolce **geçersiz kılınır** (supersedes değil; "operasyonel düzeltme" — bireysel hipotez statüsü değişmez, sadece **gate uygulaması** bu meta-protokol altında yapılır).

## 7. Stop Criteria (HERHANGİ BİRİ → SEED REDDİ)

1. **0 sibling × aday çifti Holm-FWER eşiğini geçer** → H₀ kabul, **90 gün moratoryum** (v6+ yasak), `learning.md` "p-hacking guard tetiklendi" notu, vsa_climax_test tek başına devam.
2. **2+ çift geçer ve XOR ihlal edilir** → CEO arbitrate ADR şart, paralel deploy YASAK. Lab tournament tek bir XOR seçimini ADR'le belgeleyecek.
3. **Geçen çift DSR < 0.45** → deflasyon sonrası anlamlılık zayıf, RED.
4. **Geçen çift combo MaxDD > -19.48%** → risk artışı kabul edilemez, RED.
5. **Geçen çift IS/OOS Sharpe farkı > %50** → overfit imzası, RED.
6. **Bootstrap FWER realized > 0.075 (50% buffer üstü α)** → düzeltme prosedürü bağımlılık altında çalışmıyor; metodoloji başarısız, RED + ADR.
7. **Lookahead causality testi v1-v4'ün herhangi birinde FAIL** → kod hatası, tüm seed PENDING.
8. **v1-v4 backtest reproducibility hash uyuşmazlığı** → veri/kod kayması; testler tekrar çalıştırılır, geçer ise devam, geçmez ise RED.
9. **vsa_climax_test live baseline MaxDD bu hipotez yazıldıktan sonra > -20%** → companion arayışı anlamsız (önce vsa-only-DD-onarımı gerekli), seed PENDING.

## 8. Curve-fit Şüpheleri (kendime saldırı)

1. **m=264 doğru sayı mı?** Sibling'ler bağımlı (aynı aday, farklı eksen). Romano-Wolf bootstrap bunu hesaba katar; Holm-Bonferroni biraz konservatif kalır (ama yanlış yönde — daha az false positive). Lab challenger "effective m daha az" iddia ederse veri ile gösterebilir; bu pre-register'a aykırı değil — pre-register Holm m=264 + Romano-Wolf bootstrap'ın **ikisini de** rapor etmemi söylüyor.
2. **4 sibling neden 4? 5 olmalıydı, 3 olmalıydı.** Tartışmalı. Pratik karar: 4 sibling pre-register edildi, donduruyorum. v5+ yazmak için tek yol: **disjoint selection set** (66 dışında bir aday raf) veya **farklı seed** (vsa_climax_test dışında bir live strateji için companion).
3. **66 aday raf'ı zaten bir "selection" — survivorship gibi.** Bu raf zaman içinde 76 hipotezden filtrelendi. Bonferroni N=264 bu önceki seçim turunu hesaba **katmıyor**. Gerçek N daha büyük olabilir (örn. 4 × 76 = 304 veya tüm hipotez tarihçesi). Bu, **doc'ı kabul ederken alttan akan extra konservatiflik** sebebi — eğer Holm-Bonferroni N=264 ile geçen çift olursa, gerçek edge'in olma olasılığı **daha** yüksektir.
4. **`combo_weight = 50/50` bir parametre seçimi.** Optimize edilmiyor, ama doğru ağırlık değilse gerçek edge'i kaçırabiliriz. Karşı-argüman: "best weight" optimize edilseydi ek bir tüm-aday × tüm-ağırlık sweep'i olurdu, m patlardı (m × 9 weight grid = 2376). Pre-register sabit ağırlık doğru disiplin.
5. **`vsa_climax_test` MaxDD -15.48% **anlık** snapshot.** Live bot ileride DD genişletirse companion gate eşiği geriye doğru ayarlanmalı mı? Pre-register: HAYIR, bu anki snapshot kilitli. İleride DD değişirse yeni hipotez yazılır.
6. **Bootstrap block=20 bar keyfi.** Robustness olarak {10, 40} rapor edilir, ama ana karar block=20 üzerinden. Çok kısa block → autocorrelation kırılır, çok uzun block → null variance çöker.
7. **Holm-Bonferroni uniformly more powerful but still discrete-step.** Çok güçlü bağımlı testlerde Romano-Wolf bootstrap daha doğru. İkisini de rapor edip Lab/CEO'ya tutarsızlık varsa kararı bırakıyorum — pre-register: bootstrap baskın.
8. **"90 gün moratoryum" keyfi süre.** Tartışmaya açık; Lab/CEO öneriyle 60 veya 120 gün olabilir. Pre-register: 90 gün; ADR ile değişiklik mümkün, ama bu seans değiştirilmez.

## 9. Pre-registered Method

1. **Snapshot kilidi:** Bugün (2026-05-27 17:30 UTC) 66 aday raf SHA256 hash'i + v1-v4 doc_id'leri + vsa_climax_test live config SHA256 → `memory/researcher/snapshots/2026-05-27-freeze-v5.json` (Lab tarafından doldurulur, bu hipoteze ek).
2. **v1-v4 paralel koşumu:** Lab 4 sibling'in pre-registered protokollerini 66 aday × 5y vectorbt pool üzerinde aynı seed, aynı data hash, aynı engine rev ile koşar.
3. **Her (sibling, aday) çifti için raw p-value:** Her sibling'in kendi pre-registered gate'leri AND ile uygulanır; geçen çiftler için DSR p-value (Bailey-LdP, m=264 ile) hesaplanır.
4. **Holm-Bonferroni stepdown:** 264 p-değerini sırala, stepdown reject prosedürü uygula. Hangi çiftler FWER-anlamlı tespit et.
5. **Romano-Wolf bootstrap:** 10000 block-bootstrap (block=20 ana, 10/40 robustness) altında empirical FWER hesapla. Bu sonuç **baskındır**; Holm raporda paralel veri.
6. **XOR enforcement:** Geçen çift sayısı 0/1/2+ → seed_outcome belirlenir.
7. **Sembol-rejim overlap kontrolü** (v3'ten miras Stop Criteria #10): geçen çift varsa, aday ve vsa_climax_test fire-bar'ları arasında BTC dominance / ATR percentile / EMA20-EMA50 spread için KS testi.
8. **Reproducibility hash:** git_hash + config_hash + data_hash trio raporun başına.
9. **Karar:** §7'deki Stop Criteria çağrılarına göre seed_outcome → ADR (Lab) → CEO sign-off → Principal onayı.

## 10. Gates Tablosu (kilitli)

| Kapı | Eşik | Status |
|---|---|---|
| Holm-stepdown adjusted p (geçen çiftler için) | ≤ 0.05 | locked |
| Bootstrap empirical FWER realized | ≤ 0.075 (50% buffer) | locked |
| n_passing_pairs | 0, 1, veya ≥2 (XOR) | locked |
| combo_sharpe_uplift | ≥ %20 (v3/v4 ile uyumlu) | locked |
| combo_maxdd | ≥ -19.48% (vsa baseline -15.48% + 4pp) | locked |
| DSR (geçen çift) | ≥ 0.45 | locked |
| IS/OOS Sharpe farkı | ≤ %50 | locked |
| Lookahead causality test | PASS | locked |
| Sembol-rejim overlap KS p | rapor (informational) | locked |
| Bootstrap block size | 20 bar ana, {10, 40} robustness | locked |
| Sibling sayısı (m₁) | 4 (dondurulmuş) | LOCKED — v5+ yasak |
| Aday sayısı (m₂) | 66 (snapshot kilitli) | LOCKED |
| FWER hedefi (α) | 0.05 | locked |

## 11. Beklenen Sonuç Senaryoları (subjective prior)

| Senaryo | Subjective P | Karar |
|---|---|---|
| 0 çift geçer (H₀ kabul) | %55 | seed RED + 90gün moratoryum, vsa solo devam |
| 1 çift geçer | %30 | Lab tournament → CEO sign-off → Principal → paper bot deploy |
| 2-3 çift geçer | %12 | CEO arbitrate ADR şart, tek seçim, paralel deploy YASAK |
| 4+ çift geçer | %3 | metodoloji şüphesi → Lab challenger sürecİ açılır (overfit ihtimali yüksek) |

**En olası senaryo: REDDETME** (toplam %55). Bu, "yeterince denedik, 5'inci sibling yazmıyoruz" disiplininin doğrudan ifadesidir.

## 12. v5+ Sibling Yasağı (HARD STOP)

Bu doc kabul edildikten sonra:
- **Aynı seed üzerinde** (vsa_climax_test + 66 aday raf) yeni sibling pre-register edilemez.
- İhlal edenler `ops_engineer` tarafından `protocol_violation` etiketiyle incident doc'lanır.
- Yeni sibling **şartları** (XOR — ikisinden biri):
  - **(a)** Yeni bir live strateji ile companion arayışı (vsa_climax_test'in yerine), VEYA
  - **(b)** **Disjoint** aday raf (örn. Q3 2026'da eklenen yeni hipotezler, 66'lık eski raf hariç tutulur).
- Moratoryum süresi: **90 gün** (2026-05-27 → 2026-08-25). Bu süre içinde yeni veri (≥3 ay live edge confirmation) gerekmedikçe yeni denemler.

## 13. Beklenen sonuç (bir cümle)

> 4 sibling × 66 aday × FWER düzeltmesi prosedürü dürüstçe uygulandığında **muhtemelen 0 ya da 1 çift** geçer; bu, "şu anki raf vsa_climax_test için yeterli companion sağlamıyor" pratik gerçeğine işaret eder ve şirketin Q3'te yeni hipotez üretimine + raf yenilemesine odaklanmasını gerektirir.

---

## Ek A: Bu Doc'un Hipotez Statüsünün Justification'ı

Bu doc bir **operasyonel meta-protokol** ama aynı zamanda **empirical bir iddia** içerir (§1'deki Holm-FWER null'u). Pre-registration disiplini açısından:
- Iddia: ölçülebilir (`n_passing_pairs`, `p_holm_min`, `bootstrap_fwer_realized`).
- Null: net (H₀: 0 çift geçer).
- Independent vars: dondurulmuş.
- Dependent vars: tanımlı.
- p-value hedefi: 0.05 (Holm + Romano-Wolf).
- Stop criteria: 9 açık.
- Curve-fit self-attack: 8 madde.

**Tüm SOP-1 zorunlulukları karşılandı** — `hypotheses/` dizininde tutmak doğru, `protocol/` dizinine taşımak yanlış (çünkü inter-agent prosedür değil; **araştırma metodolojisi** kilidi).

## Ek B: Review Request — Açık sorular

1. **Lab Scientist:** Romano-Wolf bootstrap implementation hazır mı? Yoksa hangi pakete (arch.bootstrap, scikit-learn?) bağlanacak?
2. **Risk Officer:** -19.48% combo MaxDD üst sınırı kabul edilebilir mi, yoksa risk gate -17% (vsa standalone level) olmalı mı?
3. **CEO:** XOR ihlali durumunda (2+ çift geçer) arbitrate kriteri ne — en yüksek DSR mi, en düşük combo MaxDD mi, en düşük β mi (v4 metrik), yoksa kompozit skor mu? ADR template hazır olsun.
4. **Lab Scientist:** v1-v4 paralel koşum compute budget (4 × 66 aday × 5y × 10000 bootstrap) realistik mi? GPU/cluster gerektirir mi?

---

**SOP-1 + SOP-3 + SOP-5 uyumu.** Pre-registration tamamdır; kod yazımından önce commit edilecek.
