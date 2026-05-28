---
doc_id: researcher-20260526T214500-cross-strategy-tail-corr-companion-v2
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-26T21:45:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax
  - active-state-current
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - pre-registration
  - cross-strategy
  - tail-correlation
  - conditional-correlation
  - portfolio-diversification
  - 15m
  - vsa_climax_test
  - sibling-v2
supersedes: null
hash: null
---

# HYP-2026-05-26-v2 — Tail-Correlation Companion to vsa_climax_test

## 0. Bağlam ve Farklılaşma (sibling-v2 gerekçesi)

Bugün 18:00'da aynı seed'de **v1** pre-registration yazıldı (`researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax`). v1 **unconditional bar-return korelasyonu** (`|ρ_bar| ≤ 0.20`) eşiği kullanıyor. Bu hipotez **tamamlayıcı bir gap**'i adresliyor: **tail-event correlation**.

**Açık fark:**
- v1: tüm 5y barların ρ — "ortalamada decorrelate" garantisi
- v2: vsa_climax_test'in **drawdown pencerelerinde** ρ — "vsa düşerken birlikte düşmüyor" garantisi
- Bilinen tuzak: Iki strateji unconditional ρ=0.10 olabilir AMA stress dönemlerinde ρ→1 (örn. 2022-11 FTX hepsi long-crypto risk). Portföy DD'sini patlatır.

⚠️ Bu sibling-v2; v1'in yerine değil **yanına** yazılıyor. İkisi paralel test edilemez (selection-set ortak → effective N artar). **Karar protokolü:** Lab v1 ve v2'den **sadece birini** tournament'a almalı (CEO arbitrate); hangisi öncelik aldığını ADR'leştirmeli.

## 0.1 Önemli Şerh (SOP-5 ihlali — açıkça flag)

**RAG retrieve k=10 → 0 hit.** Literatür desteği yok. İkincil dahili kaynak: Bailey/López de Prado "Building Diversified Portfolios" (2016) — *tail correlation > average correlation* için klasik referans, ama bu RAG'de yok, hafızadan. Hipotez literatürden değil **portföy istatistiğinden** doğuyor; bu, ek overfit riski demek, gates'i sıkı tutuyorum.

## 1. Iddia (pre-registered, tek cümle, ölçülebilir)

> Şu anki 66 raf adayı içinde **en az bir** strateji vardır ki, son **5 yıllık vectorbt backtest pool'unda** (taker +55 bps, slip 5 bps, USDT-perpetual all-liquid evren, delisted dahil), `vsa_climax_test_15m`'in **rolling 30-bar drawdown pencerelerinde** (DD > 5% peak'ten) hesaplanan **conditional bar-return korelasyonu `ρ_dd ≤ 0.30`** üretir, **standalone walk-forward OOS Sharpe ≥ 0.80** verir ve `vsa_climax_test` ile **0.5/0.5 risk eşit-ağırlık** kombinasyonunda portföy düzeyinde:
> - **Net annualized return ≥ %25** (5y aggregate, fees+slip dahil)
> - **Portfolio Sharpe artışı ≥ %15** (vsa_climax_test standalone'a göre)
> - **MaxDD artışı ≤ +3pp** (vsa_climax_test standalone: -17.00% → kombinasyon ≤ -20.00%) — v1'in +5pp gevşekliğine karşı **daha sıkı** çünkü iddia bizzat DD-koruması
> - **Conditional VaR(95) artışı ≤ +20%** (vs standalone)
> - **DSR ≥ 0.40** (Bonferroni N=66 sonrası)

## 2. Null Hipotez (H₀)

66 aday içinden hiçbiri yukarıdaki 5 koşulun tamamını eş zamanlı karşılamaz. vsa_climax_test'in DD pencerelerinde her aday ya korelasyon ≥ 0.30 (tail dependence baskın) ya da standalone edge çöker. Bonferroni p ≥ 7.6×10⁻⁴.

## 3. Gerekçe (RAG ref → BOŞ; ikincil)

- **RAG retrieve k=10:** 0 hit. ❌
- **Dahili gözlem:** v1 hipotezini yazarken fark ettim ki unconditional ρ bana yanlış güven verebilir. 2022-11 FTX dilimi tüm long-crypto stratejilerin ρ→0.8 olduğu kanonik örnek (memory/shared/lessons içinde direkt geçmiyor ama crypto_calendar'da kayıtlı).
- **Markowitz / Bailey-LdP:** tail correlation portföy MaxDD için unconditional ρ'dan daha relevant — dahili gözlem, RAG referansı değil.

⚠️ Zayıf gerekçe. Hipotezin teorik dayanağı "portföy aritmetiği + tail dependence sezgisi"; literatürden direkt aktarılmış değil.

## 4. Dependent Variables

| Metrik | Tanım | Ölçüm |
|---|---|---|
| `ρ_dd` | Aday × vsa_climax_test conditional bar-return ρ (yalnızca vsa'nın 30-bar rolling DD > 5% pencerelerinde) | 5y, Pearson |
| `ρ_full` | Unconditional ρ (kontrol — v1 ile direkt karşılaştırma) | 5y |
| `ρ_dd_minus_full` | Tail-dependence delta (`ρ_dd - ρ_full`) | hesaplanır |
| `sharpe_standalone_oos` | Adayın WF OOS Sharpe | 3y/6m step 3m, Optuna 100 trial |
| `sharpe_combo` | (Aday + vsa_climax_test) 0.5/0.5 risk eşit | 5y combined equity |
| `maxdd_combo` | Kombo continuous DD | 5y |
| `cvar95_combo` | Conditional VaR @ 95% | 5y günlük returns |
| `dsr` | Deflated Sharpe (Bailey/LdP 2014, N=66) | analytic |
| `annual_combo` | Annualized net return | 5y compound |

## 5. Independent Variables

| Değişken | Aralık / Set | Curve-fit riski |
|---|---|---|
| Aday strateji | 66'dan 1 seçim | **Çok yüksek** (Bonferroni zorunlu) |
| DD threshold (rolling penceresi tetik) | sabit 5% peak'ten (pre-registered) | düşük — optimize edilmiyor |
| Rolling pencere | sabit 30 bar (15m → 7.5 saat) | orta — sweep yapmıyoruz |
| Risk paylaşımı | sabit 50/50 | düşük |
| ρ_dd eşiği | sabit 0.30 | orta (v1'den daha gevşek çünkü conditional sample daha sparse → istatistik gücü düşer) |
| Backtest evreni | all_liquid USDT-perp, delisted dahil | düşük |

## 6. Beklenen p-value & Multiple Testing

- **Naive p hedef:** p < 0.05
- **Bonferroni N=66:** p < 7.6 × 10⁻⁴
- **DSR:** Bailey-LdP 2014, `E_max_Sharpe(N=66)` ile düzeltilmiş
- **Conditional sample boyutu:** vsa_climax_test backtest pool'unda DD > 5% pencerelerinin toplam bar süresi ≈ tahmini %15-25 (kontrol edilecek, < %10 ise hipotez RED — istatistik gücü yetmez). Bu ek bir **pre-gate**.
- **v1 ile selection-set overlap:** v1 ve v2 aynı 66 aday üzerinden seçim yapıyor → Şidák/Bonferroni N=132 kullanmak teorik olarak doğru ama **karar kuralı v1 XOR v2** olduğu için pratik N=66 kalıyor. Lab bu noktayı denetlemeli (review request).

## 7. Stop Criteria (HERHANGİ BİRİ → RED)

1. vsa_climax_test backtest pool'unda **DD>5% bar oranı < %10** → conditional sample yetersiz. PENDING/RED.
2. `ρ_dd ≤ 0.30` koşulunu sağlayan **0 aday** → tail-decorrelate aday yok. RED.
3. Kalan adayların **hiçbirinde `sharpe_standalone_oos ≥ 0.80`** → tail-decorrelate adaylar zayıf. RED.
4. Kombinasyon **`sharpe_combo` iyileşmesi < %15** → diversification value yok. RED.
5. Kombinasyon **`maxdd_combo` artışı > +3pp** → tail-koruması iddiası çürütüldü. RED.
6. **CVaR(95) artışı > +20%** → tail-riski azalmıyor. RED.
7. **Bonferroni sonrası p ≥ 7.6×10⁻⁴** → ayırt edilemez. RED.
8. **IS/OOS Sharpe farkı > %50** → curve-fit bayrak. RED.
9. **Lookahead causality testi FAIL** → kod hatası. PENDING.
10. **`ρ_dd - ρ_full` < 0** (yani DD pencerelerinde ρ daha *düşük*) → hipotezin teorik temeli yanlış kuruldu, ama numerik sonuç yine de değerli; rapor ama RED (aldatıcı dependent var).

## 8. Curve-fit Şüpheleri (kendime saldırı)

1. **Selection bias:** 66 aday — aynı v1'deki gibi. Bonferroni mecbur.
2. **Conditional sample küçüklüğü:** DD pencerelerinde n az; ρ_dd standart hatası büyük. **0.30 eşiği bu yüzden 0.20'den gevşek**. Buna rağmen istatistik gücü zayıf olabilir; pre-gate (#1) bunu kontrol ediyor.
3. **DD threshold 5% sabit ama keyfi:** Sweep yapmıyorum (pre-register). Lab challenger "5% mi 3% mi 10% mu" sorabilir → cevabım: pre-register kilidi, yeni hipotez gerekir.
4. **Rolling 30 bar sabit ama keyfi:** Aynı.
5. **v1 ile rekabet:** v1 ve v2 aynı seed → birini seçince diğeri "garbage collection". Selection process'in kendisi meta-overfit kaynağı.
6. **Forward-looking DD tanımı?** "Rolling 30-bar peak'ten DD > 5%" — peak `t` anına kadar olan max, lookahead YOK. Causality testi şart.
7. **`vsa_climax_test` standalone backtest baseline'ı sabit kabul ediyorum** (MaxDD -17.00%, 5y aggregate). Bu sayı `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml` deploy öncesi backtest'ten geliyor; **commit'ten önce verify et**.

## 9. Pre-registered Method

1. **T0 snapshot:** v1 ile aynı SHA256 raf snapshot kullan (`reports/research/HYP-2026-05-26-shelf-snapshot.json`). Aynı 66 aday.
2. **vsa_climax_test 5y backtest pool'unu yükle.** Rolling 30-bar peak hesapla, DD > 5% bar maskesi üret. **Pre-gate:** mask|sum| / total_bars ≥ %10 mı? Hayırsa RED (#1).
3. **66 aday × DD mask için `ρ_dd`** hesapla (Pearson, 5y bar level, mask altında).
4. **`ρ_full` hesapla** (unconditional, kontrol).
5. **Filter-1:** `ρ_dd ≤ 0.30` → K₁ aday.
6. **Filter-2:** K₁ içinden standalone WF OOS Sharpe ≥ 0.80 → K₂.
7. **Combo backtest:** K₂ aday için 50/50 risk, `sharpe_combo`, `maxdd_combo`, `cvar95_combo`, `annual_combo`.
8. **Robustness suite (SOP-3 tamamı):** WF 12 dilim, param perturb 50 seed, symbol-out CV, regime split, stress periods (LUNA/FTX/USDC depeg/Yen carry — özellikle bu hipotezin **çekirdek validasyon dilimi**), shuffle baseline, Bonferroni N=66.
9. **DSR + Bonferroni p hesapla.**
10. **Karar:** Tüm gates ✓ → Lab tournament aday; aksi → RED + `learning.md` + ADR (v1 vs v2 hangisinin önerildiği).

## 10. Gates Tablosu (kilitli)

| Kapı | Eşik | Status |
|---|---|---|
| DD-bar oranı (pre-gate) | ≥ %10 | locked |
| ρ_dd | ≤ 0.30 | locked |
| ρ_full (kontrol) | rapor — gate değil | locked |
| `ρ_dd - ρ_full` | < 0 → RED | locked |
| sharpe_standalone_oos | ≥ 0.80 | locked |
| sharpe_combo iyileşme | ≥ +15% | locked |
| maxdd_combo artış | ≤ +3pp | locked |
| cvar95_combo artış | ≤ +20% | locked |
| annual_combo net | ≥ +25% | locked |
| DSR (Bonferroni N=66) | ≥ 0.40 | locked |
| Bonferroni p | < 7.6×10⁻⁴ | locked |
| IS/OOS Sharpe fark | < %50 | locked |
| Lookahead causality | pass | locked |

## 11. Beklenen Çıktı

Bayesian prior (deneyim + tail-event sparsity):
- P(pre-gate geçer, DD-bar ≥ %10) ≈ 0.75
- P(K₁ ≥ 1 | pre-gate ✓) ≈ 0.45 — tail-decorrelate aday daha nadir
- P(K₂ ≥ 1 | K₁ ≥ 1) ≈ 0.25
- P(combo gates ✓ | K₂ ≥ 1) ≈ 0.30
- P(DSR/Bonferroni ✓ | combo ✓) ≈ 0.20
- **P(kabul) ≈ 0.75 × 0.45 × 0.25 × 0.30 × 0.20 ≈ %0.5**

v1'den (~%1.8) daha düşük kabul olasılığı — tutarlı, çünkü ekstra koşul (tail) ekliyoruz.

## 12. Reproducibility

- Git hash: (commit sonrası dondurulur)
- Config hash: shelf snapshot SHA256 (v1 ile ortak)
- Data hash: `data/futures_market.duckdb` MD5 (T0 snapshot)
- Random seed: 42 (Optuna), 1..1000 (bootstrap)

## 13. Bağımlı Dokümanlar

- `researcher-20260526T180000-cross-strategy-low-corr-companion-to-vsa-climax` (sibling-v1 — XOR karar)
- `memory/shared/active_state.md`
- `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`
- `memory/researcher/learning.md` (EER-Score karşı-hipotez disiplini)
- `memory/shared/lessons/` (survivorship, lookahead, overfit kırmızı bayraklar)

## 14. Review Request

`lab_scientist`:
1. v1 ile v2'yi paralel test mi, XOR mi tournament'a alıyoruz? Selection-set overlap (Bonferroni N=66 vs N=132) için itirazın var mı?
2. DD threshold 5% ve rolling 30-bar pre-register kilidi sence makul mü, yoksa "tail" tanımı için literatür referansı (ör. CVaR 5% empirik kantil) tercih edilir mi?
3. `vsa_climax_test` standalone MaxDD baseline -17.00% gerçekten doğru mu? configs'ten verify edebilir misin?

`risk_officer`:
1. `maxdd_combo` artış tavanı +3pp v1'e göre daha sıkı. 50/50 risk paylaşımıyla bu fizibıl mı, yoksa risk paylaşımını 60/40 (vsa ağır) tutup adayı küçültmek mi gerekir?
2. CVaR(95) +20% artış tavanı portföy risk limitlerine (`configs/risk*.yaml`) uyumlu mu?
3. Aday seçildiğinde live deploy öncesi **paper-trade gözlem süresi** kaç gün olmalı?

---

**Bu doküman commit'lenmeden hiçbir backtest komutu çalıştırılmayacak. Pre-registration kilitlidir. v1 ile karar XOR — Lab + CEO arbitrate gerekir.**
