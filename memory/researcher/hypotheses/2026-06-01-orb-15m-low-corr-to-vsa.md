---
doc_id: researcher-20260601T000000-orb-15m-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T00:00:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [orb, opening-range-breakout, intraday-momentum, low-corr-vsa, cross-strategy-edge, pre-registration]
supersedes: null
hash: null
---

# Hypothesis: HYP-2026-06-01-orb-15m-low-corr-to-vsa

- **Tarih:** 2026-06-01
- **Versiyon:** 0.1 (pre-registration — kod yazılmadan)
- **Aktif champion:** vsa_climax_test (15m, gün-içi exhaustion/reversal sınıfı)
- **Aday class:** Opening Range Breakout — intraday momentum/continuation (Kaufman ch.opening-range, RAG #5)

## 1. İddia (tek cümle, ölçülebilir)

15m timeframe'de, **UTC 00:00 günlük session açılışının ilk 1 bar (00:00–00:15 UTC)** Opening Range (OR) olarak alındığında, sonraki 15 bar (≈4 saat) içinde **fiyat OR-high + k×ATR(14) seviyesinin üstüne kırarsa long stop**, OR-low - k×ATR(14) altına kırarsa short stop emriyle giriş; **1.5×ATR(14) SL** ve **2×ATR(14) TP** kurallı çıkışla, son 3 yıl (2023-06-01 → 2026-06-01) Binance USDT-perpetual top-14 likit evreninde, fee 7.5bps taker + slip 5bps konservatif:

- **Annualized net return ≥ %25** (sembol-ortalamalı, equal-weight portfolio),
- **OOS Sharpe ≥ 1.0** (walk-forward median),
- **MaxDD ≤ %25** (portfolio-level),
- **Profit factor ≥ 1.4**,
- **vsa_climax_test ile trade-by-trade Pearson korelasyonu ≤ 0.20** (eş-zamanlı R-multiple stream),
- **PBO < 0.5** ve **DSR > 0.5** (López de Prado, RAG #1).

## 2. Null hipotez

- ORB sinyalleri shuffle baseline'ı yenmiyor (p ≥ 0.05), VEYA
- vsa_climax_test ile korelasyon > 0.40 (cross-strategy edge yok, sadece aynı edge'in yeniden paketlenmesi), VEYA
- Net annualized return < 0 (fee + slip sonrası gerçek negatif), VEYA
- IS/OOS Sharpe oranı > 3 (López de Prado curve-fit kırmızı bayrağı, RAG #1).

## 3. Gerekçe (RAG referansları)

- **[Kaufman summary, Opening Range Breakout, RAG #5]:** "Open + k×ATR(14) üzerine fiyat çıkarsa long stop emri; intraday momentum capture; yüksek win rate (~%55) küçük R ile." Crypto'da "open" tanımı bizde UTC 00:00 (Binance funding settlement). Mekanik kod-edilebilirlik 5/5.
- **[Brooks catalog, RAG #3]:** "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir" — Brooks da intraday breakout class'ını test edilebilir-skala 5 olarak işaretliyor.
- **[López de Prado, RAG #1]:** PBO/DSR/IS-OOS-Sharpe red-flag çerçevesi — bu hipotez gate'i.
- **Anti-RAG (Bulkowski continuation, RAG #10 / Mat Hold %74):** mat-hold zaten 2026-05-31'de denendi ve abort oldu (`memory/researcher/backtest_results/2026-05-31-mat-hold-continuation-low-corr-to-vsa-seed-abort-v2.json`); ORB **farklı bir time-domain class** (gün-başı momentum) olduğu için yeniden test gerekçesi var.

**Düşük korelasyon iddiasının mekaniği:** vsa_climax_test, **yüksek hacim + spread-reversal** koşulunu gün-içi herhangi bir saatte arar; ORB ise **sabit-saat (UTC 00:00 ± 4h)** range-breakout arar. Aynı barda her ikisinin aynı sembolde aynı yönde tetiklenme olasılığı düşük (zaman-pencere ortogonalliği). Korelasyon ölçümünde aynı (symbol, bar) kovasında her iki strateji R-multiple'larının vektörü kullanılır.

## 4. Dependent variables (önceden taahhüt edilen metrikler)

| # | Metrik | Hedef | Source |
|---|---|---|---|
| 1 | Net annualized return | ≥ %25 | backtest engine |
| 2 | OOS Sharpe (walk-forward median) | ≥ 1.0 | walk_forward.py |
| 3 | MaxDD (portfolio, equity-base) | ≤ %25 | engine |
| 4 | Profit factor | ≥ 1.4 | engine |
| 5 | Win rate | informational only | engine |
| 6 | Trade count (toplam) | ≥ 200 (anlamlılık eşiği) | engine |
| 7 | vsa_climax_test ile Pearson corr | ≤ 0.20 | post-backtest analysis |
| 8 | Shuffle baseline p-value | < 0.05 | robustness suite |
| 9 | PBO (Bailey/López de Prado) | < 0.5 | combinatorial CV |
| 10 | DSR (Deflated Sharpe) | > 0.5 | López de Prado formula |
| 11 | IS/OOS Sharpe ratio | < 3 | walk-forward |
| 12 | Param perturb ±%10 ortalama Sharpe kaybı | < %25 | 50 seed |

## 5. Independent variables (parametre grid — SABİT, no Optuna)

**Curve-fit'i sınırlamak için parametre uzayı tek free knob ile:**

| Param | Değer(ler) | Free? |
|---|---|---|
| `opening_range_bars` | 1 (sadece 00:00–00:15 UTC barı) | **sabit** |
| `session_start_utc` | 00:00 | **sabit** |
| `watch_window_bars` | 16 (00:15–04:15 UTC ≈ 4h) | **sabit** |
| `atr_window` | 14 | **sabit** |
| `breakout_k` (× ATR over OR-high/low) | **{0.5, 1.0}** | **FREE — 2 trial** |
| `sl_atr_multiplier` | 1.5 | **sabit** |
| `tp_atr_multiplier` | 2.0 | **sabit** |
| `direction` | both long & short | **sabit** |
| `universe` | top-14 USDT-perp by 30d ADV @ 2023-06-01 | **sabit** |
| `fee_taker` | 7.5 bps | **sabit** |
| `slippage` | 5 bps | **sabit** |
| `risk_per_trade` | %1 (sabit notional sizing) | **sabit** |

**Free parameter sayısı: 1** (yalnız `breakout_k`, 2 değer). López de Prado kriteri (n_params/n_samples > 1/30): minimum 30 trade gerekli — gate 200 trade ile zaten karşılanıyor.

**Bonferroni:** 2 trial → düzeltilmiş p-eşiği = 0.025. Shuffle baseline p < 0.025 olmalı.

## 6. Beklenen p-value

- Shuffle baseline p < **0.025** (Bonferroni sonrası, 2 trial).
- vsa_climax_test korelasyon testi (H0: ρ ≥ 0.40) tek-yönlü t-test p < 0.05.

## 7. Stop criteria (araştırmayı erken sonlandırma kuralları)

Aşağıdakilerden **herhangi biri** gerçekleşirse hipotez **REJECT** ve `learning.md`'ye 3-satır gerekçe:

1. **In-sample Sharpe < 0.5** → edge yok, durdur.
2. **Toplam trade < 200** (3y × 14 sembol × 2 k-değeri) → istatistiksel anlamsız, durdur.
3. **Net annualized return < 0** (fee+slip sonrası) → exhibit-A red.
4. **vsa_climax_test korelasyon > 0.40** → cross-strategy edge yok, mevcut champion'ın yeniden paketlenmesi.
5. **IS/OOS Sharpe oranı > 3** → curve-fit, López de Prado kırmızı bayrağı (RAG #1).
6. **PBO > 0.5** → overfit.
7. **Stress periyot (2024-08 Yen carry, 2025-12 BTC ATH retrace varsa)** yıkıcı kayıp > %20 single-event.

## 8. Curve-fit şüphesi (kendime açık yazıyorum)

**Bu hipotez için aktif kırmızı bayrak adayları:**

- **Crypto 24/7 — "open" tanımı gerçek değil.** Hisse senedinde session-open mekaniği gerçek likidite asimetrisinden gelir (gece order birikimi). Crypto'da UTC 00:00 sadece **funding settlement** anı, doğal bir mikrostruktur açılışı değil. Eğer ORB çalışırsa, **NEDEN** çalıştığını anlamadan deploy etmek tehlikeli. Funding-driven flow varsayımı test edilmeli.
- **Kaufman istatistiği hisse evrenine ait.** %55 win rate intraday hisse senedi backtestleri. Crypto perpetual evreninde transfer edilebilirlik **kanıtlanmamış**. Anti-narrative: "Crypto'da da çalışır" iddiası RAG-destekli değil.
- **Session bias.** Sadece UTC 00:00 başlangıcı denenirse, sonuç UTC 12:00 veya UTC 08:00 başlangıcına ne kadar dayanıklı? Pre-registration'da UTC 00:00 sabit; eğer red olursa **post-hoc başka saat denemek YASAK** (p-hacking).
- **Trade sayısı şişirme riski.** k=0.5 daha çok sinyal üretir → trade sayısı yüksek görünür ama bunlar gürültü olabilir. Per-symbol win rate dağılımına bakılacak (3'den az sembolde >%55 → curve-fit).
- **Bull bias.** Son 3 yıl (2023-06 → 2026-06) tipik olarak bull-dominant. Bear dilimleri (2024-12 → 2025-03 retrace varsa) yıkıcı olabilir. Regime split zorunlu.

## 9. Pre-registration commit

Bu doc commit edildiğinde hipotez **donar**. Sonradan değişiklik = yeni doc (`-v2` suffix) + `supersedes`. Trial sayısı 2 ile sınırlı; ek trial = pre-registration violation.

## 10. Sonraki adım

`backtest/engine.py` ile minimal ORB detector implement edilir (signal_chief'e veto-power için ping atılacak — lookahead test gate'i). Robustness suite (SOP-3) tam olarak uygulanır. Sonuç `reports/research/orb-15m-2026-06-01.html` + JSON.

Lab'e (lab_scientist) tournament adayı olarak iletilmek için: tüm gate'leri geçmiş + vsa_climax_test ile korelasyon ≤ 0.20 + DSR > 0.5 zorunlu. Aksi takdirde `learning.md` red gerekçesi.

## 11. Iterate policy (SOP-4b)

Eğer aylık ROI > 0 ama gate fail (örn MaxDD > %25 ama Sharpe > 1):
- **v2-risk-reduction:** `risk_per_trade` 0.01 → 0.005
- **v3-k-tighten:** `breakout_k` ∈ {1.0, 1.5} (sadece güçlü breakout)
- **v4-session-filter:** sadece USDT-perp 24h hacmi top-7 sembollerde
- 5 iterate budget. Sonra "deferred" (red değil).
