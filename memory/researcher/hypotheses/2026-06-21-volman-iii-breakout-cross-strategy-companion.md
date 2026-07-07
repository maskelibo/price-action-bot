---
doc_id: researcher-20260621T060000-volman-iii-breakout-cross-strategy-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-21T06:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - configs/strategies/classic_pa.yaml
  - researcher-20260621T000000-bos-close-cross-strategy-low-corr-vsa
  - researcher-20260621T000000-mat-hold-continuation-cross-strategy-companion
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [cross_strategy_companion, low_correlation, volman_iii, triple_inside_bar, breakout, vsa_companion]
supersedes: null
hash: null
---

# Hipotez: HYP-2026-06-21-volman-iii-breakout-cross-strategy-companion

## 1. Iddia (pre-registered, ölçülebilir)

**"15m timeframe'de, son N=3 ardışık inside-bar (Volman 'iii' konfigürasyonu — Bar2.high<Bar1.high & Bar2.low>Bar1.low; Bar3 ve Bar4 da kendinden bir önceki içinde) sonrası `t` barın kapanışında Bar1'in tepe/dip tarafına 1×ATR(14) breakout konfirmasyonu veren stop emri, USDT-perpetual evreninde 36-aylık (2023-06-21 → 2026-06-21) dönemde, ücret+slippage modelinin (7.5bps taker + 5 bps slip) dahil olduğu net hesapla:**

- **Annualized net return > %25** (modest hedef, edge'i abartmamak için)
- **Sharpe (OOS, walk-forward) > 0.8** — single asset eşiği (Chan)
- **MaxDD < %25** (champion vsa_climax_test ile aynı tavan)
- **Pearson(daily return, vsa_climax_test live returns) ∈ [-0.20, +0.20]** — companion olabilmesinin zorunlu kriteri
- **Profit factor > 1.4**
- **N trade ≥ 200** (istatistiksel güvenilirlik tabanı)

Bunların **tamamı** sağlanmazsa hipotez **RED**. Sadece düşük korelasyon yetmez; standalone pozitif edge zorunlu (vsa_climax_test'in negative carry'sini taşıyamaz).

## 2. Null Hipotez (ne olursa çürür)

H0: "iii breakout" pattern'in net edge'i = 0 (commission + slippage sonrası beklenen R-multiple ≤ 0).

Bunun shuffle baseline ile karşılaştırması zorunlu (p < 0.05); bar etiketlerini permutasyona uğratıp aynı detector'ı çalıştırınca beklenen değer 0'a yakın olmalı.

## 3. Gerekçe (RAG referansları)

- **[Bulkowski candlestick statistics, RAG#2]**: Tek inside bar breakout WR %54, rank 78/103 — **zayıf**. Volman katmanı ise "ii"/"iii" multiple-inside konfigürasyonunun **daha güçlü** olduğunu iddia eder (DD setup). Bulkowski'nin %54'ü zaten bizim için iyi bir floor; iii koşulu eklendiğinde edge artmalı, artmıyorsa hipotezi reddetmek kolay.
- **[Brooks deep catalog, RAG#3]**: "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir" — testability skor 5 (en yüksek). iii→breakout aynı skala içinde.
- **[Kaufman, RAG#5 + RAG#7]**: Opening-range ve Donchian breakout'lar volatilite-genişleme (vol expansion) edge'inin tarihsel olarak en sağlam kalıpları. iii konsolidasyonu da aynı vol-compression→vol-expansion ailesinde.
- **[Chan, RAG#9]**: Single-asset OOS Sharpe > 0.8 gate'i, hipotezimizin promote eşiği olarak doğrudan benimsenmiştir.
- **[López de Prado, RAG#1]**: DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe kırmızı bayraklarından **biri bile** kırmızıysa RED — bu hipotez için zorunlu.

VSA-orthogonality gerekçesi: vsa_climax_test **hacim-bazlı exhaustion** sinyaliyle çalışır (yüksek vol_z + reversal). Volman iii ise **fiyat-yapısı sıkışması + breakout** (volume-agnostic). İki mekanizmanın korelasyonu, klasik vol-driven mean-reversion ↔ price-structure trend-continuation ayrımının doğrudan sonucu olduğu için düşük olması beklenir; ama empirik test gerekli — beklenti **hipotez değil**, ölçüm.

## 4. Dependent Variables (önceden tanımlanmış metrikler)

| Metrik | Hedef | Kaynak |
|---|---|---|
| `net_annualized_return` | > %25 | backtest engine |
| `sharpe_oos` | > 0.8 | walk-forward (3y train, 6m test, step 3m) |
| `max_dd` | < %25 | equity curve |
| `corr_with_vsa_climax_test` | \|ρ\| ≤ 0.20 | günlük net return Pearson, son 90d overlap |
| `profit_factor` | > 1.4 | gross_win / gross_loss |
| `n_trades` | ≥ 200 | trade journal |
| `dsr` | > 0.5 (López de Prado) | Sharpe deflated |
| `pbo` | < 0.5 | combinatorial purged CV |
| `shuffle_baseline_p` | < 0.05 | 1000 permutation |

## 5. Independent Variables (parametre uzayı — coarse grid, curve-fit önleme)

| Param | Aralık | Adım | Gerekçe |
|---|---|---|---|
| `inside_bar_count` | {2, 3, 4} | 1 | "ii"/"iii"/"iiii" karşılaştırması; iii baseline |
| `breakout_atr_mult` | {0.5, 1.0, 1.5} | 0.5 | coarse — ince grid yasak |
| `atr_window` | {14} | sabit | klasik Wilder ATR; over-search yok |
| `tp_atr_mult` | {2.0, 3.0} | 1.0 | iki seçenek, fit yok |
| `sl_atr_mult` | {1.0, 1.5} | 0.5 | risk/reward tarafı |
| `tf` | {15m} | sabit | scope discipline; çoklu tf olursa multiple-testing inflasyonu |

**Toplam kombinasyon = 3×3×1×2×2×1 = 36.** Optuna **kullanılmayacak** — full grid + Bonferroni düzeltmesi. Trial sayısı bilinçli olarak küçük tutuldu; "1 milyon trial içinde altın" anti-pattern'inden kaçınmak için.

**Curve-fit kırmızı bayrak self-check:**
- ❌ Eğer "best params" grid'in **kenarında** çıkarsa (örn breakout_atr_mult=1.5, tp=3.0) → grid genişlet ve sonucu **tekrar bağımsız** yenile; aksi halde keşfedilmemiş optimum.
- ❌ Eğer ince grid (örn atr_mult 0.1 step) gerekli olduğu hissi gelirse → **dur**, hipotez kalıba zorlanıyor demektir.
- ❌ Eğer trade sayısı 36 kombinasyonun >%50'sinde < 100 ise → evren yetersiz, yorum yapma.

## 6. Beklenen p-value

- Raw shuffle baseline: **p < 0.01** beklenir (eğer edge gerçekse).
- Bonferroni düzeltmesi (n=36): **p_adj < 0.05** gate'i — yani raw p < 0.00139 olmalı.
- Bu eşik **uyumsuzsa hipotez RED**.

## 7. Stop Criteria (önceden bağlanmış, in-flight değişmeyecek)

Aşağıdakilerden **herhangi biri** tetiklenirse araştırma **derhal sonlandırılır**, "bir daha dene"ye yer yok:

1. In-sample Sharpe < 0.5 → terk, devam etme.
2. n_trades(toplam, 36 ay) < 200 → istatistiksel temel zayıf, terk.
3. IS / OOS Sharpe oranı > 2.5 → overfit kırmızı bayrağı (López de Prado kuralı: > 3 ise zaten ölü; > 2.5 self-imposed sıkı eşik).
4. corr(daily_ret, vsa_climax_test) > 0.30 mutlak değerde → companion değil, dublör. Hedef başarısız.
5. Stress periodlarından (2024-08 Yen carry, 2024-12 vol shock, 2025-Q1 chop) en az ikisinde MaxDD > %15 → kırılgan, terk.

## 8. Reproducibility Stamp

- `git_hash`: <to be filled at first run>
- `config_hash`: 36-cell coarse grid spec frozen as JSON
- `data_hash`: USDT-perpetual liquid universe @ 2026-06-21 snapshot (delisting'ler dahil — survivorship anti-pattern uygulanmaz)
- `seed`: 42 (shuffle baseline), 100..149 (param perturb)

## 9. Yapılmayacaklar (Hard Limits)

- ❌ Optuna ile geniş Bayesian arama yapılmayacak (curve-fit kapısı).
- ❌ vsa_climax_test'in live trade'leriyle "filtreleme" denenmeyecek (data snooping).
- ❌ Pattern üzerine "iyileştirici" indikatör eklenmesi yasak (RSI, EMA filter, vs.) — minimal pattern testte kalır.
- ❌ Backtest sonucu pozitif görünürse "lab'e gönderelim" hızı yasak; SOP-3 robustness suite tam yürütülecek.
- ❌ "Edge görünmese bile farklı sembollerde dene" yasak (sembol-out CV içinde zaten test edilecek).

## 10. Beklenen Sonuç (apriori, dürüst)

Pre-registration disiplini gereği önceden söylüyorum: **%70 ihtimalle RED.** Bulkowski'nin tek inside bar %54 WR'si zayıf bir taban; iii konfigürasyonunun crypto 15m'de Volman'ın claim ettiği boost'u getireceğini doğrulayan **bir tane bile bağımsız akademik çalışma** RAG'da yok. Bu hipotezin değeri "edge bulduk" değil, "edge yok"u **mekanik kanıt** ile kayda almak — VSA-orthogonal aday havuzunu daraltmak.

%30 ihtimalle iii→breakout edge'i marginal pozitif çıkar ama korelasyon eşiğini tutmaz (çünkü 15m vol-expansion'ları VSA exhaustion'ları ile bir tema paylaşır — vol regime). O durumda bile RED, çünkü companion kriteri zorunlu.

%5 ihtimalle tüm gate'ler geçer → Lab tournament'a aday. O zaman bile **adversary_engineer kill-probe** gerekir, çünkü "Volman'ın iii"sinin başarısı klasik literatürde forex/equity testlerine dayanır; kripto evreninde tekrar etmesi a-priori olası değil.

## 11. Lab'e Devir Şartı

Yalnızca SOP-3 robustness suite (8 kalem) **tamamen yeşil** + corr gate ≤ 0.20 + DSR/PBO temiz olursa Lab'e tournament için devredilir. Aksi halde `learning.md`'ye 3 satırlık red gerekçesi + hipotez arşive.

---

**Sonraki adım:** `backtest/engine.py` 36-cell grid coarse run → robustness suite → karar matrisi.
