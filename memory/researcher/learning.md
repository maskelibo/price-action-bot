---
agent: researcher
type: learning
created: 2026-05-08
---

# Researcher Learning

## Format

```
### YYYY-MM-DD — <slug>
- **Hipotez:** ...
- **Sonuç:** terfi / red / belirsiz
- **Ne öğrendim:** ...
- **Hangi bias'a düştüm:** confirmation / narrative / recency / ...
- **Bir dahaki sefer:** ...
```

---

### 2026-05-08 — Boot
- Ders defterinin başlangıcı. İlk hipotezden itibaren doldurulacak.

---

### 2026-05-13 — EER-Score v1 RED (ama yan-bulgu önemli)

- **Hipotez:** 180-gün rolling 6-dim bucket avg_R percentile (EER), CONF tier sizing'e karşı OOS Sharpe %20+ uplift verir.
- **Sonuç:** RED (3/5 pre-registered gate FAIL).
  - Bucket coverage %0 (sample_min=30 ile hiç bucket dolmuyor).
  - Shuffle null 0/6 pencerede p<0.05 (etiket permutation Sharpe'i değiştirmedi).
  - Top-vs-bottom Welch t-test imkânsız (top/bottom tier boş).
- **Ne öğrendim:**
  1. 6-dim bucket key (1772 unique bucket / 4787 trade = 2.7 trade/bucket avg) **fazla geniş**. Karşı-hipotez 1 (bucket clustering bias) **pre-registered olarak yazılmıştı ve doğrulandı**. Önemli: karşı-hipotezi yazmasaydım sonucu "edge bulundu" diye yutardım çünkü Mean ΔSharpe +0.26 PASS gibi görünüyor.
  2. **Paradox bulgu (KRİTİK):** EER fallback davranışı (tüm trade T2'de %2 risk + 2x lev) CONF-based sizing'i (T4'te %78 sinyal, %4 risk + 3x lev) +0.26 Sharpe uplift verdi. Bu EER mekaniğinin edge'i değil — **CONF'un bozuk olması ortaya çıktı** (DYNAMIC v0.9.8 felaketi yeniden gözlendi). Yan-aday: "flat T2 sizing" baseline as Lab W3 tournament challenger.
  3. Pre-registration disiplini Phase 1'i kurtardı — eğer karşı-hipotez yazmasaydım "Sharpe uplift +0.26 = PASS" rapor edip Lab'e gönderirdim, oradan tournament zaman/efor kaybı.
- **Hangi bias'a düşmedim:** Confirmation bias riski yüksekti — pozitif Mean ΔSharpe gözlemlemek mıknatıs gibi. Karşı-hipotez 1 önceden yazılmıştı, sonuç ona bakınca düştü.
- **Hangi bias'a düştüm:** **Combinatorial naivety** — 10 strat × 11 sym × 3 × 3 × 3 × 5 = 14850 bucket olabileceğini hesapladım ama pratikte 4787 trade'i dağıttığında bucket başına ortalama 2.7 düşeceğini hesabıma katmadım. Sample size matematiğini sadece n>=30 düzeyinde aldım, kombinatorik dağılımı değil.
- **Bir dahaki sefer:**
  - Pre-registration'a "expected n_trades_per_bucket" hesap koy: 4787/14850 = 0.32 (zaten %1 olabilirdi). Mathematicaly impossible'ı önceden gör.
  - Hierarchical bucket fallback: spesifik bos → parent (strategy+symbol+regime) → grand mean.
  - Bayesian shrinkage: avg_R = (n_bucket * avg_bucket + sample_min * grand_mean) / (n_bucket + sample_min). Smooth transition fallback'tan tahmine.
  - Bucket dimensionality 4'ten fazlaya çıkmamalı (3-4 olmalı).

### 2026-05-13 — 3 ikincil hipotez quick backtest (single 3y window)

- **HYP-1 funding-oi-divergence:** FAIL. n=4 trade. Sebep: OI verisi yok, funding-only proxy yetersiz triple-confluence vermiyor. **Ders:** Data Engineer'a "OI fetch" işemri verilmesi gerekiyor; bu hipotez backtest edilemez.
- **HYP-2 compression-breakout-nr7:** FAIL. n=67 trade, WR %38.8, avg_R +0.06, Sharpe 0.24 (gate >0.5). **Ders:** Crabel'in S&P futures'taki edge'i (WR %58, avg_R 1.4) 1d crypto'ya transfer edilmedi. Crypto volatilitesi compression-breakout için "yeterli sessizlik öncesi fırtına" mekaniğini yıkıyor — sürekli vol-clustering ile NR7 anlamını kaybediyor.
- **HYP-3 correlation-cluster-throttle:** PARTIAL. DD +33.9pp iyileşti ama return +%3145 → +%120 çakıldı (1797/2754 trade blocked, %65 skip rate). **Ders:** rho=0.70 + cluster_cap=2 fazla sıkı; cluster eşiği 0.80 veya cluster_cap=3 ile retest gerekli. Hipoteze göre skip_rate >%25 RED gate'i zaten ihlal edildi (%65).

---

> Hafta sonu konsolidasyonu Lab tarafından.
