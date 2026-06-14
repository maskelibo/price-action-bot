---
doc_id: researcher-20260604T100000-iii-triple-inside-breakout-1d-cross-edge
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-04T10:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - book_candlestick_statistics-volman-iii
  - book_market_structure_order_flow-bos-table
  - book_lopez_summary-deflated-sharpe
  - hypothesis-2026-06-03-ii-double-inside-breakout-low-corr-to-vsa
  - learning-2026-06-02-smc-continuation-clean-negative
  - learning-2026-06-02-htf-continuation-diversifier-falsified
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags: [hypothesis, pre-registration, cross-strategy, diversifier, iii, triple-inside, continuation, 1d, crypto]
supersedes: null
---

# HYP — iii Triple Inside-Bar Consolidation Breakout (1D crypto, cross-strategy diversifier to vsa_climax_test)

## 0. Seed & Motivation

`vsa_climax_test` aktif champion + canlı candidate ailesi. Aile profili: **mean-reversion, exhaustion-fade, hacim-tetikli, intraday/15m**. Portföye eklenecek aday için *düşük korelasyon* zorunlu — yapısal olarak en zıt aile = **yön-nötr structure breakout, hacim-bağımsız, daily/HTF**.

Raftaki 66 aday içinde *henüz test edilmemiş* tek formasyon: Volman'ın **iii** (üç ardışık inside bar) breakout'u. ii (double inside) 2026-06-03'te test edildi. iii bir adım daha sıkı consolidation — RAG #2 "iii breakout daha güçlü" iddiası mevcut; Bulkowski rank inside-bar tekilde 78/103 ama Volman ii/iii compound koşulu eklenince literatür-iddia güçleniyor.

**Şüpheci gerekçe (önceden yazıyorum):** Son 14 günde *4 farklı* trend-continuation / breakout ailesi (SMC continuation, HTF BOS+displacement, Marubozu, Donchian 55, EMA200-pull, Mat Hold, Kaufman ATR-breakout, ii double-inside) **CLEAN NEGATIVE** kapandı (shuffle p_gross > 0.05 veya post-fee CI 0'ı kapsadı). Crypto bar-OHLCV'de yön-bilgisi taşıyan continuation prior'ı bulunamadı. iii'nin önceki sekiz aileden *yapısal olarak ne kadar farklı olduğunu* bilmiyorum — muhtemelen **REJECT** beklentim baz senaryo, hipotez bu beklentiyi çürütmeye odaklı.

## 1. İddia (pre-registered, ölçülebilir)

> "**1D timeframe**, **all_liquid USDT-perpetual evren (≥15 sembol)**, **2020-01-01 → 2026-05-31** dilimde:
>
> *iii setup:* `Bar[t-2]` *outer*; `Bar[t-1].high < Bar[t-2].high AND Bar[t-1].low > Bar[t-2].low`; `Bar[t].high < Bar[t-1].high AND Bar[t].low > Bar[t-1].low`. (Strict üç-bar daralma.)
>
> *Entry:* `Bar[t+1].close` üzerinde `Bar[t-2].high + 0.10×ATR(14)`'ü yukarı kıran → uzun stop-emir; tersi short. (Yön-nötr breakout.)
>
> *Stop:* Giriş ∓ `1.5×ATR(14)`. *Hedef:* `2.0R` (asimetrik R = 1.33).
>
> *Beklenti (null'u yenmek için min eşik):*
> - Gross mean_R (0 bps) > **+0.03R** ve shuffle-null'a karşı **p_gross < 0.05** (1000 yön-shuffle, daily-aggregated bootstrap).
> - Net mean_R (55 bps round-trip) > **+0.005R**; daily-Sharpe bootstrap 95% CI **alt-bandı > 0**.
> - 6-yıl walk-forward'da **≥4 yıl post-fee pozitif**.
> - `corr_pearson(daily_returns, vsa_climax_test)` ∈ **[-0.20, +0.20]** (gerçek diversification).
>
> Bu dört koşul **eş zamanlı** sağlanmazsa hipotez **REJECT**."

## 2. Null Hipotez (H₀)

iii setup'ı + 0.10×ATR breakout buffer kombinasyonu, **yön-shuffle null'undan ayırt edilemez** bir gross mean_R üretir (p_gross ≥ 0.05). VEYA: gross-pass etse bile 55 bps fee erozyonu sonrası daily-Sharpe CI 0'ı kapsar. VEYA: rho_to_vsa_climax > 0.20 — yapısal çakışma var, diversification yok.

**Bu null'u çürütemezsem hipotez red, no sample-size'da kurtarma yapılmaz.**

## 3. Bağımlı Değişkenler (önceden listeli — yeni metrik eklemek yasak)

| Metric | Hedef | Notu |
|---|---|---|
| gross_mean_R (0 bps) | > +0.03 | primary |
| net_mean_R (55 bps) | > +0.005 | primary |
| p_gross (shuffle, n=1000) | < 0.05 | primary |
| daily_Sharpe net | > +0.20 | primary |
| daily_Sharpe 95% CI lower | > 0 | primary |
| 6y per-year positive count | ≥ 4 / 6 | robustness |
| symbol-out CV min Sharpe | > 0 | robustness |
| rho_to_vsa_climax | ∈ [-0.20, +0.20] | diversification |
| MaxDD (1% risk, ATR-stop) | < 30% | risk |
| trade count | ≥ 200 | power |

## 4. Bağımsız Değişkenler (grid — Bonferroni budget)

Sıkı tutuyorum: **8 trial** maks. (Past curve-fit kaynağı: aşırı geniş grid.)

| Param | Values | n |
|---|---|---|
| `n_inside_bars` | {3} (strict iii) | 1 |
| `atr_buffer_k` | {0.05, 0.10, 0.20} | 3 |
| `stop_atr_k` | {1.5} | 1 |
| `tp_R` | {2.0} | 1 |
| `regime_filter` | {none, EMA200 yön-uyumlu} | 2 |
| `entry_timing` | {next-bar-open-if-triggered} | 1 |

→ **Toplam: 3 × 2 = 6 grid noktası.** Multi-testing düzeltmesi: BH-FDR q=0.10, beklenen min anlamlı p ≤ 0.05/6 = 0.0083 (Bonferroni) ya da BH q (daha gevşek). **Her trial önceden tanımlı, ek deneme = curve-fit beyanı.**

## 5. Literatür Gerekçesi (RAG)

- **[#2 candlestick_statistics — Volman ii/iii]:** "Tekli inside bar zayıf; ancak ii veya iii breakout daha güçlü. Volman'ın DD setup'ı buradan türer." → iii compound koşulu single inside bar (%54 win, rank 78/103) zayıflığını kompanse edebilir.
- **[#3 brooks_deep_catalog]:** Inside-bar consolidation sonrası breakout, Brooks'un BBB (Big Bull Bar) ataklarında en koşullanmış pattern'lerden biri. "Test edilebilir mi: 5" — mekanik olarak kodlanabilir.
- **[#6 market_structure_order_flow — BOS table]:** BOS close-based (n=3) crypto 1D'de "Yüksek" işlenebilirlik. iii breakout = mikro-BOS denkliği.
- **[#10 candlestick_statistics — Mat Hold]:** Bulkowski %74 / rank 10. iii bir Mat Hold öncülü (3 inside bar konsolidasyon). NOT: Mat Hold 2026-06-02'de test edildi (sonuç notu hipotezler dizininde, REJECT olduysa iii daha güçlü beklenti **olmamalı**).
- **[#1 lopez_summary]:** DSR/PBO/Min BTL guard'ları zorunlu. 6 trial sınırı + walk-forward 6-yıl + symbol-out CV bu guard'ları zorlar.

## 6. Curve-Fit Şüphesi (önceden deklare)

Aşağıdakilerden **herhangi biri** tetiklenirse hipotez red — kurtarma denemesi yok:

- **Önceki ailelerle yapısal yakınlık:** Mat Hold (sonucu kontrol et!) zaten 3-inside konsolidasyon + 5. bar breakout. iii daha gevşek bir versiyon → Mat Hold REJECT ise iii'nin pozitif çıkma a priori olasılığı düşük. Sonuç pozitif ise **şüphe** kırmızı bayrak, OOS / regime split mutlak.
- **8 ailenin de FAIL ettiği prior:** SMC continuation, HTF BOS+disp, Marubozu, Donchian 55, EMA200-pull, Mat Hold, Kaufman ATR, ii. Crypto OHLCV bar yön-bilgisi taşımıyor sonucu **9 farklı mekanizma** tarafından tekrarlandı. iii bunun 10. tekrarı olabilir.
- **Hacim-eksenli vsa_climax ile yapısal ortodoks:** vsa_climax climax-bar SONRASI fade alır. iii consolidation SONRASI continuation alır. Ama: vsa_climax climax sonrası SIKILAŞMA görür (= sıklıkla iii benzeri yapı!). **rho > +0.20 çıkarsa diversification claim çöker** — bu kontrol önemli, "low corr because different name" yanılgısına düşme.
- **0.10×ATR buffer "sweet spot" gibi görünür mü?** 0.05, 0.10, 0.20'den 0.10 best çıkarsa şüphe orta. 0.20 best çıkarsa "küçük noise'ı dışlıyor" anlamlı; 0.05 best çıkarsa "her küçük breakout sayıyor" curve-fit göstergesi.

## 7. Beklenen p-değeri ve İstatistiksel Güç

- **p_gross** (yön-shuffle, n=1000 reshuffle, daily-aggregated): **< 0.05**.
- BH-FDR (q=0.10, n_trials=6): min anlamlı p ≈ 0.017.
- Daily-Sharpe bootstrap 95% CI alt bandı **strictly > 0** (sıfırı kapsamaz).
- **Beklenti (önceden):** baz senaryo p_gross ∈ [0.20, 0.70] olur, REJECT çıkar. Pozitif çıkma şartlı olasılığı **<%20** (8 önceki continuation ailesinin tamamı negatif).

## 8. Stop Criteria (kod yazmadan önce dondur)

1. **In-sample gross mean_R ≤ 0** → kill, yazılmaz.
2. **Shuffle p_gross ≥ 0.20** → kill (büyük belirsizlik).
3. **Trade count < 100** → kill (power yetersiz, iterate teklif yok).
4. **rho_to_vsa_climax > +0.20 veya < -0.50** → kill (diversification claim çöker).
5. **Per-year sign 6 yılda ≥3 yıl negatif** → kill (regime-luck).
6. **0.10×ATR best param VE 0.05/0.20 ikisi de net negatif** → curve-fit, kill.
7. **Bonferroni/BH sonrası anlamlılık yok** → kill (multi-trial inflation).

İterate hakkı: gross mean_R > 0 VE p_gross < 0.10 VE 6y ≥3 yıl pozitif → SOP-4b iterate v2 (entry buffer + regime filter sıkılaştır). Aksi takdirde **clean negative** notu + arşiv.

## 9. Reproducibility Stamp

- `git_hash`: (set at run time, target: `audit-hardreview-20260528` branch HEAD)
- `config_hash`: (sha256 of grid + universe + ATR period + fees model)
- `data_hash`: (sha256 of data/market.duckdb 1d-bars manifest for 15 syms, 2020-01-01 → 2026-05-31)
- Backtest harness: `scripts/research/smc_sfp_backtest.py` (lookahead-safe, vectorized first-touch, shuffle-null builtin) — KISMEN tekrar kullanılabilir; iii detector eklemek için `src/price_action/signals/inside_bar.py` referansı.
- Fees: 7.5 bps taker + 0 maker (round-trip ~15 bps spot baseline; perpetual long-side 5 bps + 5 bps + ~5 bps spread ≈ 55 bps stress baseline kullanılır).

## 10. Karar Çerçevesi (raporda doldurulacak)

```
1. RAG: 5 ref, Volman ii/iii + Brooks BBB
2. Hipotez: iii breakout 1D crypto, yön-nötr, 0.10×ATR buffer, 2R hedef
3. Null: yön-shuffle ile ayırt edilemez
4. Pre-reg metrikler: §3 tablosu
5. Backtest: <doldur>
6. Robustness suite: <doldur>
7. Karar: <terfi / red / iterate>
8. Gerekçe: <doldur>
```

## 11. Çıktı Hedefi

Bu hipotez gate'i geçerse `configs/strategies/iii_breakout_1d.yaml` *aday taslak* yazılır (insan onayı + Lab tournament zorunlu). Diversification claim için Lab'in cross-strategy correlation matrix güncellemesi gerekir. **Ben kendim deploy/promote yapmam.**

---

**Pre-registration commit:** bu doc commit edildiği anda hash dondurulur. Sonraki rapor bu doc'a `depends_on` ile bağlanır; metrik veya kriter değişikliği yalnızca yeni doc + `supersedes` zinciri ile.
