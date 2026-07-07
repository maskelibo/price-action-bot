---
doc_id: researcher-20260622T173000-fvg-gap-fill-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T17:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [cross-strategy, low-correlation, fvg, fair-value-gap, smc, mean-reversion, vsa-companion, pre-registration, search-space-depleted]
supersedes: null
hash: null
---

# Hipotez — FVG (Fair Value Gap) Fill, vsa_climax_test ile Düşük Korelasyonlu Companion

## 0. Bağlam (zorunlu şeffaflık + curve-fit ön-itirafı)

- **Aktif champion:** `vsa_climax_test` (volume-climax exhaustion reversal).
- **Daha önce denenmiş companion adayları (hepsi seed-abort veya gate-fail, v6→v71+):**
  Mat Hold (×3), Marubozu (×2), BOS-close (×2), CHoCH, Volman iii, Volatility breakout ATR, Engulfing (×13), Pin bar SR (×4), Golden/Death cross (×2), Donchian 20/55 (×5), Anchored VWAP (×8), Kaufman ATR/RSI-div (×4), Equal Highs/Lows sweep (×2), Wyckoff Spring (forex-only). **Toplam denenmiş companion ailesi sayısı ≈ 14, toplam pre-registered varyant ≈ 70+.**
- **Bu yüzden curve-fit ön-uyarı:** Cross-strategy companion arama uzayı **görgül olarak tükenmiş** görünüyor. Yeni bir kalıp v1'de gate geçerse "şans / multiple-testing" şüphesi default. Meta-Bonferroni n_companion ≈ 70+ → istenen p_adj **< 0.05 / 70 ≈ 7e-4** (literatür düzeltmesi).
- **FVG'nin diğerlerinden farkı (test edilebilir):**
  - VSA climax: bar-içi volume + range exhaustion (single bar).
  - FVG: 3-bar imbalance (bar1 high < bar3 low veya tersi), 1D'de görece seyrek.
  - FVG mean-reversion (price returns to gap to fill), VSA climax mean-reversion (extreme'den dönüş). İki tetik aynı bar'da örtüşme olasılığı düşük olmalı, ama bu **ölçülmeden iddia değil**.

## 1. İddia (pre-registered, ölçülebilir)

> **1D timeframe'de**, USDT perpetual `all_liquid` evreninde (son 3 yıl, delisted-dahil),
> **3-bar FVG tanımı**:
> - Bullish FVG: `bar[t-2].high < bar[t].low`, gap_size = `bar[t].low − bar[t-2].high`, gap_size > **0.15×ATR(14, @t-1)**.
> - Bearish FVG: `bar[t-2].low > bar[t].high`, gap_size = `bar[t-2].low − bar[t].high`, gap_size > **0.15×ATR(14, @t-1)**.
> **Tetik (entry)**: FVG oluşumundan sonraki N=10 bar içinde, fiyat gap mid-line'ına (close-based) dokunursa, dokunan bar'ın **next open**'ında **gap fill yönünde** market emir.
> - Bullish FVG → long (price returned to gap from above; expecting bounce back up after closing inefficiency).
> - Bearish FVG → short.
> SL = gap'in ters tarafı + 0.25×ATR(14) padding.
> TP = gap full fill (gap'in orijinal başlangıcı).
> Eğer 10 bar içinde dokunulmazsa veya 20 bar içinde fill/SL olmazsa **time-exit (close)**.
> fee 7.5 bps taker + 5 bps slippage,
> portföy: `risk_pct=0.5%` per trade, `max_concurrent=4`, leverage tavan 3x,
> aşağıdaki TÜM koşulları aynı anda sağlar:

| Metrik | Eşik | Ölçüm |
|---|---|---|
| Net annualized return (OOS, fee+slip dahil) | **> %25** | Walk-forward OOS dilim compound ort. |
| Sharpe (OOS, günlük returns annualize) | **> 1.0** | sqrt(365) × mean/std |
| MaxDD (equity-base) | **< %30** | Peak-to-trough |
| Profit factor | **> 1.4** | Σwin / Σloss |
| Toplam OOS trade sayısı (3y) | **≥ 100** | Portföy toplamı (signal density gate) |
| **\|ρ\| günlük returns vs vsa_climax_test live+backtest hibrit serisi** | **< 0.30** | Pearson, 3y overlap |
| Single-test shuffle baseline p | **< 0.01** | n_iter=1000 |
| Meta-Bonferroni p_adj (n_companion ≈ 70) | **< 7e-4** | 0.05/70 |

## 2. Null hipotez (ne olursa çürür)

- H0a: Net annual return ≤ %15 → companion ekleme değer üretmiyor.
- H0b: \|ρ\| ≥ 0.30 → "düşük korelasyon" iddiası boş.
- H0c: Single-test p ≥ 0.01 VEYA meta-Bonferroni p_adj ≥ 7e-4 → istatistik anlam yok.
- H0d: Walk-forward 12 dilimden < 7'sinde pozitif değil → consistency yok.
- H0e: Trade sayısı < 100 → istatistik yetersiz.
- H0f: FVG signal density < 0.5 per symbol per year (1D, all_liquid → çok seyrek) → portföy ekonomisi çökmüş.

Bunlardan **herhangi biri** doğrulanırsa hipotez **REDDEDİLİR**.

## 3. Gerekçe (RAG referansları)

- **[market_structure_order_flow §"Mekanik Çalışabilirlik (Crypto 1D)"]** — FVG (gap > ATR*0.15): mekanik çalışabilirlik **Orta**, "Tanım net ama fill oranı değişken" (RAG #6). Bu "değişken fill" doğrudan H0f'nin nedeni.
- **[lopez_summary]** — Pre-registered metrikler + Bonferroni + DSR + walk-forward dilim varyansı kırmızı bayrakları gözetilecek (RAG #1).
- **[chan_summary]** — Yeni stratejiler portföye girmeden OOS Sharpe > 0.8 (single asset) eşiği; bizim eşik 1.0 (daha sıkı) (RAG #9).
- **[brooks_deep_catalog]** — n-bar mekanik kalıplar "tamamen kodlanabilir" (skor 5, RAG #3); FVG bunun structural-imbalance varyantı.

## 4. Independent Variables (DAR uzay, kasıtlı)

| Parametre | Aralık | Adım | Justification |
|---|---|---|---|
| `gap_atr_min` | {0.10, 0.15, 0.25} | discrete | RAG #6 default 0.15; sınır komşusu kontrol |
| `entry_window_bars` (oluşumdan sonra geri-dönüş arama penceresi) | {5, 10, 15} | discrete | Stale-gap eliminasyonu |
| `sl_atr_pad` | {0.1, 0.25, 0.5} | discrete | Volman/Brooks standardı |
| `tp_mode` | {full_fill, half_fill, 2R_fixed} | categorical | Asimetri vs determinism |
| `htf_filter` (1W EMA50 yönü ile uyum: bullish FVG ↔ 1W trend up) | {off, on} | binary | Brooks HTF opposition kuralı |

**Toplam grid = 3×3×3×3×2 = 162.** Bayesian/Optuna kullanılmayacak (grid kasıtlı). Bonferroni n=162.

**Curve-fit savunması:**
- Her parametre 2-3 nokta.
- "Best param sınırda mı" testi otomatik (sınırda ise red).
- `gap_atr_min` çok düşürülmez (0.10 alt sınır) — gürültü çekmemek için.
- TP'de "fixed 2R" üçüncü mod olarak var → mean-reversion vs trailing perspektifi test edilir.

## 5. Dependent Variables

- `annualized_return_oos`
- `sharpe_oos`
- `maxdd_oos`
- `profit_factor_oos`
- `n_trades_oos`
- `corr_with_vsa_climax_returns` (Pearson, günlük)
- `shuffle_p_value` (n_iter=1000, single-test)
- `bonferroni_adjusted_p` (n_local=162)
- `meta_bonferroni_p_adj` (n_meta≈70 companion ailesi)
- `walk_forward_positive_slice_count` (12 dilimden kaçı)
- `signal_density_per_symbol_year`
- `fvg_fill_rate` (oluşan FVG'lerin % kaçı 10 bar içinde dokunuluyor — info)

## 6. Beklenen p-value

- Pre-registered:
  - **Single-test shuffle p < 0.01.**
  - **Local-Bonferroni n=162: p_adj < 3e-4.**
  - **Meta-Bonferroni n_companion≈70: p_adj < 7e-4.**
- Meta-Bonferroni gate'i geçemeyen hiçbir aday Lab'e gitmez.

## 7. Stop Criteria (fail-fast — seed-abort)

Aşağıdaki erken sinyallerden HERHANGİ BİRİ varsa research **anında durdurulur**, arşivlenir:

1. In-sample Sharpe < 0.5 (162 trial'in en iyisi bile) → **terk**.
2. In-sample trade sayısı < 100 → **terk** (signal density yetersiz, H0f).
3. FVG signal density < 0.5 / symbol / year → **terk** (FVG too sparse on 1D crypto).
4. \|ρ\| in-sample > 0.4 → **terk** (ortogonalite iddiası boş — bu vakaya kritik).
5. Best parametreler grid'in sınır komşusunda (örn. `gap_atr_min=0.25` veya `entry_window_bars=15`) → **terk** (uzay sınır-dışında olabilir).
6. IS/OOS Sharpe farkı > %50 → overfit → **terk**.
7. Walk-forward dilim varyansı > ortalama → **terk** (Lopez kırmızı bayrak).
8. Meta-Bonferroni p_adj ≥ 7e-4 → **red** (companion ailesi inflation aşılmadı).

## 8. Iterate Politikası (SOP-4b)

Eğer gate (§1) yalnızca DD veya tek-metrik kötü düşmesinden geçemezse AMA:
- Net annual return > 0
- \|ρ\| < 0.30 (companion mantığı korunuyor)
- Meta-Bonferroni p_adj < 7e-4 (istatistik anlam KORUNUYOR)

→ **REDDETME YASAK**. v2 iterate seçenekleri:
- Risk reduction (`risk_pct` 0.5%→0.25%, `max_concurrent` 4→2).
- HTF filter forced on (rejim subset).
- TP partial (full_fill yerine 1R'de %50 close + trail).
- Time-exit penceresi kısalt (20 → 10 bar).
- 4H timeframe'de re-test (FVG fill rate yüksek olabilir).

İterate budget: max 5 versiyon. Hepsi başarısızsa **deferred archive** (red değil — "FVG edge gerçekse bizim kapasitemizde değil").

## 9. Curve-fit Şüpheleri (kasıtlı listeleme — tehdit dolu)

- ⚠️ **Search space depleted.** 70+ companion seed-abort = arama uzayı yorgun. Yeni bir kalıp v1'de gate geçerse **default şüphe yüksek**. Meta-Bonferroni n=70 düzeltmesi bu yüzden zorunlu.
- ⚠️ **FVG retail-popüler.** SMC/ICT content'inde FVG son derece popüler; popülerlik → arbitraje edilmiş edge şüphesi (RAG'de SMC kursları zaten kripto'da edge yok sonucuna ulaştı — bkz. shared lesson "smc-course-no-edge"). Bu hipotez **bilinçli olarak SMC kursu narrative'inden bağımsız bir matematik tanım kuruyor** (gap > 0.15×ATR + 10-bar window + ATR-padded SL); sonuç negatifse "FVG edge'i SMC kursları zaten tükettik" hipotezi doğrulanmış olur — bu da pozitif epistemic katkı.
- ⚠️ **1D'de FVG seyrek.** Signal density H0f olarak gate'de; sweep edilirken `gap_atr_min` düşürmeye eğilim olabilir (gürültü çekme) — bu **yasak** (alt sınır 0.10).
- ⚠️ **3-bar FVG bizim ad-hoc tanımımız.** Literatür FVG için kesin n vermez; 3-bar SMC kuruyor ama 5-bar/7-bar varyantları aranmıyor — bunu **kasıtlı olarak dondurduk**, p-hacking penceresi açmamak için.

## 10. Pre-registration Commit

Bu doküman yazıldıktan sonra **kod yazımı veya backtest başlatılmadan** Git'e commit edilir; hash bu YAML frontmatter'ın `hash` alanına commit sonrası eklenir. Sonraki tüm raporlar bu hash'e referans verir.

## 11. Karar (boş — backtest sonrası doldurulur)

- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [ ] Red — gerekçe: ...
- [ ] Seed-abort (early stop criteria) — gerekçe: ...
- [ ] Deferred archive (FVG edge gerçek ama kapasitemizde değil)
