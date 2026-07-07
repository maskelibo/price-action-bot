---
doc_id: researcher-20260622T100100-choch-trend-reverse-cross-strategy-companion-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-22T10:01:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [cross-strategy, low-correlation, choch, smc, structure, vsa-companion, pre-registration]
supersedes: null
hash: null
---

# Hipotez — CHoCH (Change of Character) Trend-Reverse, vsa_climax_test ile Düşük Korelasyonlu Companion

## 0. Bağlam (zorunlu şeffaflık)

- **Aktif champion:** `vsa_climax_test` (VSA climax — high-volume reversal/exhaustion pattern).
- **Şu ana kadar denenen düşük-korelasyon companion'lar (hepsi terfi edemedi):**
  Mat Hold (×3), Marubozu (×2), BOS-close (×2), Volman iii, Volatility breakout ATR, Engulfing (×13), Pin bar SR (×4), Golden/Death cross (×2), Donchian 20/55 (×5), Anchored VWAP (×8), Kaufman ATR/RSI-div (×4), Equal Highs/Lows sweep (×2), Wyckoff Spring (forex-only).
- **Curve-fit kırmızı bayrağı (öncesi):** Cross-strategy companion arayışı v6→v71 seed-abort silsilesi ürettiyse arama uzayı **muhtemelen tükenmiştir**. Bu hipotez bu yüzden a-priori düşük güven (confidence: low) ile pre-register ediliyor; sonuç negatifse "arama uzayı tükenmiş" hipotezi ek doğrulanır.
- **Bu hipotezin diğerlerinden farkı:** BOS (yapı kırılımı, trend-continuation) tek başına denendi; CHoCH (trend-state-flip = ilk opposite-direction structure break) ayrı bir trigger setidir. CHoCH girişleri yapısal olarak reversal/transition; vsa_climax_test ise exhaustion-spike. İki sinyalin ortak bar'da tetiklenmesi mantıken seyrek olmalı — düşük korelasyon iddiası burada test edilir.

## 1. İddia (pre-registered, ölçülebilir)

> **1D timeframe'de**, USDT perpetual `all_liquid` evreninde (son 3 yıl, delisted-dahil),
> **3-bar swing tanımıyla close-based CHoCH** (bullish CHoCH = downtrend state'inde son swing-high close üstü kapanış; bearish CHoCH = uptrend state'inde son swing-low close altı kapanış; trend-state HMM yerine `last_bos_direction` ile)
> tetik bar'ının bir sonraki barının **açılışında** girişle,
> SL = sinyal bar'ının opposite extremesi (long için bar low; short için bar high) ile pad = **0.25×ATR(14)**,
> TP = **2R fixed**,
> fee 7.5 bps taker + 5 bps slippage,
> portföy konfigürasyonu `risk_pct=0.5%` per trade, `max_concurrent=4`, leverage tavan 3x,
> aşağıdaki TÜM koşulları aynı anda sağlar:

| Metrik | Eşik | Ölçüm |
|---|---|---|
| Net annualized return (OOS, fee+slip dahil) | **> %25** | Walk-forward OOS dilimlerinin compound ort. |
| Sharpe (OOS, günlük returns annualize) | **> 1.0** | sqrt(365) × mean/std |
| MaxDD (equity-base) | **< %30** | Peak-to-trough |
| Profit factor | **> 1.4** | Σwin / Σloss |
| Toplam OOS trade sayısı (3y) | **≥ 100** | Tek sembol değil portföy toplamı |
| **|ρ| günlük returns vs vsa_climax_test live + backtest hibrit serisi** | **< 0.30** | Pearson, 3y overlap |
| Bonferroni-düzeltilmiş p (shuffle baseline'a karşı) | **< 0.05** | n_trials sayısına göre |

## 2. Null hipotez (ne olursa çürür)

- H0a: Net annual return ≤ %15 (champion'un altına düşer → ekleme değer üretmez).
- H0b: |ρ| ≥ 0.30 (düşük korelasyon iddiası boş — companion mantığı çöker).
- H0c: Bonferroni sonrası shuffle baseline'ı yenemez.
- H0d: Walk-forward 12 dilimden en az 7'sinde pozitif değil (consistency yok).
- H0e: Trade sayısı < 100 (istatistik yetersiz).

Bunlardan **herhangi biri** doğrulanırsa hipotez **REDDEDİLİR**.

## 3. Gerekçe (RAG referansları)

- **[market_structure_order_flow §"Mekanik Çalışabilirlik (Crypto 1D)"]** — CHoCH (close-based, n=3): mekanik çalışabilirlik **Yüksek**, "BOS gibi, trend-state makinesi gerektirir" (RAG #6).
- **[lopez_summary]** — Hipotez kayıt anında pre-registered metrikler ve Bonferroni düzeltmesi olmazsa DSR/PBO red bayrakları otomatik atar (RAG #1).
- **[brooks_deep_catalog]** — n-bar overextended + reversal mekaniği "tamamen kodlanabilir" (skor 5, RAG #3); CHoCH bunun structural varyantı.
- **[chan_summary]** — Yeni stratejiler portföye girmeden önce OOS Sharpe > 0.8 (single asset) eşiği (RAG #9). Hipotez eşiği 1.0 → biraz daha sıkı.

## 4. Independent Variables (sweep edilecek — ÖZELLİKLE DAR uzay)

| Parametre | Aralık | Adım | Justification |
|---|---|---|---|
| `swing_n` (swing tanımı için lookback) | {2, 3, 5} | discrete | RAG #6 n=3 default; sınır komşusu kontrolü |
| `entry_offset_bars` (close→next open) | {1} (fixed) | n/a | Lookahead'a yer açma yok |
| `sl_atr_pad` (ATR padding swing extremede) | {0.1, 0.25, 0.5} | discrete | Volman/Brooks standardı |
| `rr_target` (R:R) | {1.5, 2.0, 2.5} | discrete | Asimetri testi |
| `htf_filter` (1W EMA50 yönü ile uyum) | {off, on} | binary | Brooks HTF opposition kuralı (RAG #3) |

**Toplam trial = 3×3×3×2 = 54.** Optuna kullanılmayacak (zaten dar uzay, grid search). Bonferroni n=54.

**Curve-fit savunması:** Parametre adım sayısı kasıtlı az; her parametre 2-3 nokta. "Best param sınırda mı" testi otomatik (sınırda ise red).

## 5. Dependent Variables

- `annualized_return_oos`
- `sharpe_oos`
- `maxdd_oos`
- `profit_factor_oos`
- `n_trades_oos`
- `corr_with_vsa_climax_returns` (Pearson, günlük)
- `shuffle_p_value`
- `bonferroni_adjusted_p`
- `walk_forward_positive_slice_count` (12 dilimden kaçı)

## 6. Beklenen p-value

- Pre-registered: **shuffle baseline'a karşı p < 0.01** (single-test); Bonferroni n=54 sonrası **p_adj < 0.05**.

## 7. Stop Criteria (fail-fast)

Aşağıdaki erken sinyallerden HERHANGİ BİRİ varsa research **anında durdurulur**, arşivlenir (seed-abort):

1. In-sample Sharpe < 0.5 (54 trial'in en iyisi bile) → **terk**.
2. In-sample trade sayısı < 100 → **terk** (signal density yetersiz).
3. |ρ| in-sample > 0.4 → **terk** (ortogonalite iddiası boş — bu vakaya özel kritik).
4. Best parametreler grid'in sınır komşusunda (örn. `swing_n=5` veya `sl_atr_pad=0.5`) → **terk** (uzay sınır-dışında olabilir, geniş test gerekirdi).
5. IS/OOS Sharpe farkı > %50 → overfit → **terk**.
6. Walk-forward dilim varyansı > ortalama → **terk** (RAG #1 Lopez kırmızı bayrağı).

## 8. Iterate Politikası (SOP-4b)

Eğer gate (§1) DD veya başka tek-metrik kötü düşmesinden geçemezse AMA:
- Net annual return > 0
- |ρ| < 0.30 (companion mantığı korunuyor)

→ **REDDETME YASAK**. v2 iterate:
- Risk reduction (risk_pct 0.5%→0.25%)
- HTF filter forced on (rejim subset)
- TP partial (1R'de %50)
- max_concurrent 4→2

İterate budget: max 5 versiyon.

## 9. Curve-fit Şüpheleri (kasıtlı listeleme)

- ⚠️ **Cross-strategy companion arayışı 70+ seed-abort üretti.** Yeni bir Bulkowski/Brooks pattern'ı v1'de gate geçerse multiple-testing inflation şüphesi otomatik yüksek; Bonferroni'yi tüm bu deneme havuzuyla genişletmek gerek (n_meta ≈ 70+ companion). Bu hipotezin OOS p < 0.05 vermesi tek başına yetmez; meta-Bonferroni p < 0.0007 (0.05/70) hedefi raporda ayrıca rapor edilecek.
- ⚠️ **Yapısal ortogonalite "mantıklı geliyor" ama veri kazansın.** vsa_climax_test ile CHoCH'in aynı bar tetikleme istatistiği ölçülmeden iddia kanıtlanmaz.
- ⚠️ **3-bar swing tanımı bizim ad-hoc tercihimiz.** Literatür `n` için kesin değer vermez; 2/3/5 grid'i sınır komşu testiyle savunulur, daha geniş aralık aranmaz.

## 10. Pre-registration Commit

Bu doküman yazıldıktan sonra **kod yazımı veya backtest başlatılmadan** Git'e commit edilir; hash bu YAML frontmatter'ın `hash` alanına commit sonrası eklenir. Sonraki tüm raporlar bu hash'e referans verir.

## 11. Karar (boş — backtest sonrası doldurulur)

- [ ] Terfi adayı
- [ ] İterate (SOP-4b)
- [ ] Red — gerekçe: ...
- [ ] Seed-abort (early stop criteria) — gerekçe: ...
