---
doc_id: researcher-20260527T090000-btcd-shift-trigger-event-v1
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T09:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260512-regime-btc-dominance-trend-veto
  - researcher-20260509-btc-dominance-altrotation
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, btc-dominance, regime, event-trigger, pre-registration, low-rag-support]
supersedes: null
hash: null

type: hypothesis
hypothesis_id: HYP-BTCD-SHIFT-EVENT-001
researcher: researcher_agent
related_strategy: candidate (cross-asset regime overlay v2)
parent_hypotheses:
  - HYP-22 (2026-05-09 BTC.D altrotation — continuous slope filter)
  - HYP-REGIME-003 (2026-05-12 BTC.D trend veto — continuous + asymmetric)
differentiator: bu hipotez sürekli slope filtresi değil — DISCRETE TRANSITION EVENT'i tetikleyici olarak kullanır
---

# HYP-BTCD-SHIFT-EVENT-001 — BTC.D Regime Shift Event Triggers Alt Long/Short Setup

## ⚠ Pre-Registration Caveats (zorunlu uyarılar)

1. **RAG corpus support: ZERO.** Bu hipotezi pre-register etmeden önce `rag.retrieve("BTC dominance shift trigger regime")` çalıştırıldı — corpus boş. Klasik PA literatüründe (Brooks, Volman, Grimes) BTC dominance kavramı yok (zaten kripto-spesifik). Akademik kripto literatüründe BTC.D continuous regime indicator olarak çalışılmış; **discrete shift event** olarak iddia kaynaklı destek bulunamadı. **Bu hipotez literatür-yetimi.** Pre-register edilmesi → test edilebilir hale getirme amacıyla; gate'i geçse bile SOP-5 gereği özgün-iddia + zayıf-destek kombinasyonu → çift robustness suite uygulanacak.
2. **Curve-fit risk profili: YÜKSEK.** İki ön-uyarı:
   - Parent HYP-REGIME-003 zaten BTC.D continuous slope üzerine optimize edildi; bu hipotez aynı altyapıyı **event** olarak yeniden paketler → in-sample contamination şüphesi. Out-of-sample dilim aynı dönemlerden gelirse anlamsız.
   - 4 parametre (slope_window, shift_threshold_pp, lookback_for_confirmation, event_decay_bars) Optuna'da serbest bırakılırsa → çok kolay overfit. Sınırlı grid'de çalışacak (aşağıda madde 5).
3. **Symbolic/alpha-data dependency:** Hipotez CoinGecko BTC.D snapshot'una bağımlı. Veri kalitesi (Data dept) onaylamadan `IN_TEST`'e geçemez. Stablecoin supply'ı (HYP 2026-05-09) entegre edildi mi belli değil — total mcap'ten USDT/USDC payını çıkarmak gerekiyor olabilir; aksi halde "BTC.D shift" gerçek değil mekanik artefakt olabilir.

## 1. Iddia (pre-registered, ölçülebilir)

> **BTC.D'nin 7 günlük basit hareketli ortalamasının (BTC.D-SMA7) 30 günlük SMA'sını (BTC.D-SMA30) yukarı/aşağı kestiği "shift event" mumu, alt-coin perpetual evrenindeki yön-spesifik LONG/SHORT setup'larının 5-bar forward Sharpe'ını istatistiksel olarak değiştirir.**
>
> İki kantite iddiası (her ikisi ayrı testler — Bonferroni uygulanacak):
>
> **Iddia-A (Long bias):** BTC.D SMA7↓×SMA30 (DOWN-cross, alt-rotation event başlangıcı) bar'ından sonraki 5 bar (1d timeframe) içinde, alt-coin LONG sinyallerinin (mevcut v0.9.2 production sinyal seti) ortalama 1-bar forward log-return'ü, koşulsuz örnekleme göre **≥ 25 bps daha yüksek** (one-sided t-test, α=0.025 / Bonferroni sonrası).
>
> **Iddia-B (Short bias):** BTC.D SMA7↑×SMA30 (UP-cross, BTC re-dominance event) bar'ından sonraki 5 bar içinde, alt-coin SHORT sinyallerinin ortalama 1-bar forward log-return'ü, koşulsuz örnekleme göre **≥ 25 bps daha yüksek** (one-sided t-test, α=0.025 / Bonferroni sonrası).
>
> Bu iki iddianın **en az biri** gate'i geçerse hipotez `IN_TEST` → tournament adayı. **Her ikisi** geçerse asimetrik veto overlay önerilir (HYP-REGIME-003 ile çakışma testi → Lab'in işi).

## 2. Mekanik Tetikleyici Tanımı (kod-edilebilir, dondurulmuş)

```python
# Pre-registered freeze — parametreler test sırasında değişmeyecek
WINDOW_FAST = 7          # gün
WINDOW_SLOW = 30         # gün
EVENT_DECAY_BARS = 5     # event-after window (5 bar = ~1 hafta 1d)
MIN_SHIFT_MAGNITUDE_PP = 0.20  # SMA7 - SMA30 ≥ 20 bps farkı geçmeli (gürültü filtresi)

def btcd_shift_event(btcd_df: pd.DataFrame, i: int) -> str:
    """Returns DOWN_CROSS | UP_CROSS | NONE for bar i (decisions made on i-1 close)."""
    if i < WINDOW_SLOW + 1:
        return "NONE"
    sma_fast_now = btcd_df['btc_dom'].iloc[i-WINDOW_FAST:i].mean()
    sma_slow_now = btcd_df['btc_dom'].iloc[i-WINDOW_SLOW:i].mean()
    sma_fast_prev = btcd_df['btc_dom'].iloc[i-1-WINDOW_FAST:i-1].mean()
    sma_slow_prev = btcd_df['btc_dom'].iloc[i-1-WINDOW_SLOW:i-1].mean()
    diff_now = sma_fast_now - sma_slow_now
    diff_prev = sma_fast_prev - sma_slow_prev
    if abs(diff_now) < MIN_SHIFT_MAGNITUDE_PP:
        return "NONE"
    if diff_prev <= 0 and diff_now > 0:
        return "UP_CROSS"     # BTC re-dominance start
    if diff_prev >= 0 and diff_now < 0:
        return "DOWN_CROSS"   # Alt rotation start
    return "NONE"
```

**Causality protect:** Tüm hesaplamalar `i-1` close'una kadar olan veriyi kullanır; karar bar `i`'de, giriş bar `i+1` open'da.

## 3. Bağımlı Değişkenler (dependent variables)

| Değişken | Tanım | Hedef yön | Birim |
|---|---|---|---|
| `fwd_logret_1d_long` | Iddia-A için: DOWN_CROSS sonrası 5-bar penceredeki alt-long sinyallerinin 1-bar forward log-return ortalaması | yukarı | bps |
| `fwd_logret_1d_short` | Iddia-B için: UP_CROSS sonrası 5-bar penceredeki alt-short sinyallerinin 1-bar forward log-return ortalaması (short için negate edilmiş) | yukarı | bps |
| `sharpe_5bar_long` | Iddia-A penceredeki long P&L Sharpe (annualized) | > 1.0 | scalar |
| `sharpe_5bar_short` | Iddia-B penceredeki short P&L Sharpe (annualized) | > 1.0 | scalar |
| `event_count` | 3y test süresinde detect edilen event sayısı (DOWN ve UP ayrı) | ≥ 20 her yön | int |
| `placebo_diff` | Aynı pencere random shuffle edilirse (1000 reshuffle) ölçülen avg fwd_logret farkı | ≤ 5 bps (kontrol) | bps |

## 4. Bağımsız Değişkenler (independent variables) — DONDURULDU

Pre-registration aşamasında **sadece dondurulmuş parametreler** ile test edilir; Optuna kullanılmaz çünkü:
- 4 parametre × 10 değer = 10,000 trial → Bonferroni n=10,000 → α=5e-6, gerçek edge olmadan geçmesi imkânsız.
- "Tek nokta" test → curve-fit yok, ya çalışır ya çalışmaz.

| Parametre | Dondurulmuş değer | Yan-grid (sadece robustness için, optimize edilmeyecek) |
|---|---|---|
| `WINDOW_FAST` | 7 | {5, 10} → sensitivity report |
| `WINDOW_SLOW` | 30 | {20, 50} → sensitivity report |
| `EVENT_DECAY_BARS` | 5 | {3, 7, 10} → sensitivity report |
| `MIN_SHIFT_MAGNITUDE_PP` | 0.20 | {0.10, 0.30} → sensitivity report |

> **Curve-fit Tripwire:** Eğer dondurulmuş değerlerde gate başarısız ve sensitivity yan-grid'inde başarılı bir nokta var → bu hipotez **REDDEDİLİR**, "post-hoc kurtarma" yasaktır.

## 5. Veri & Setup

| Field | Value |
|---|---|
| Universe | `all_liquid` USDT-perpetual (delisting'ler dahil) |
| Timeframe (primary) | 1d |
| BTC.D source | CoinGecko `/coins/bitcoin/market_chart` (Data dept onaylı snapshot) |
| Stablecoin correction | Total mcap'ten (USDT + USDC + DAI + BUSD) çıkarılarak BTC.D yeniden hesaplanır (artefakt önleme) |
| Sample period | 2023-01-01 → 2026-05-01 (3y4ay) |
| Train / OOS split | Train: 2023-01-01 → 2024-12-31 (2y). OOS: 2025-01-01 → 2026-05-01 (1y4ay). |
| Walk-forward | 6 dilim (train 18m / test 4m, step 4m) — OOS sonrası ek robustness |
| Fees | 7.5 bps taker (conservative) |
| Slippage | 5 bps |
| Risk per trade | 1% (sembol başına) |
| SL/TP | ATR-based 2× SL, 2R TP (parent v0.9.2 ayarı) |
| Signal source | Mevcut v0.9.2 production engulfing/pin bar set (yeni detector eklenmez) |

## 6. Beklenen p-Value & Multiple-Testing

- **Per-iddia raw p-value hedefi:** < 0.025 (one-sided)
- **Bonferroni düzeltmesi:** 2 iddia × 4 sensitivity yan-test (sadece raporlama) = 8 test → α=0.05/8 = **0.00625**.
- **Asıl gate:** Iddia-A veya Iddia-B raw p < 0.025 **VE** Bonferroni-sonrası en az bir iddia hâlâ p < 0.00625 olmalı.
- **Shuffle baseline (placebo):** 1000 reshuffle ile null distribution. Event timing'lerini random tarihlere taşıdığımızda `fwd_logret` farkı **|Δ| ≤ 5 bps**. Eğer placebo'da da pozitif fark çıkıyorsa → calendar effect, hipotez red.

## 7. Stop Criteria (kod-yazımına başlamadan önce dondurulmuş)

Aşağıdaki **herhangi biri** karşılanırsa hipotez **TERK** edilir ve `learning.md`'ye 3 satırlık gerekçeyle yazılır:

| Stop kriteri | Eşik | Yorum |
|---|---|---|
| In-sample Sharpe (any side) | < 0.5 | Düşük edge — devam etmeye değmez |
| Event count (any side) | < 20 (3y) | İstatistik anlamsız |
| Placebo Δ |  ≥ 5 bps | Calendar / chance effect — gerçek event-edge yok |
| In-sample / OOS Sharpe farkı | > 50% | Overfit kırmızı bayrağı (lessons §learnings_overfit_redflags) |
| Walk-forward pozitif dilim oranı | < 60% (6 dilimden 4+) | Stabil değil |
| Bonferroni sonrası anlamlılık | başarısız | Multiple-testing zaferi şans olabilir |
| Stress dilim (LUNA/FTX/USDC depeg) MaxDD | > %12 single-event | Tail bozar |
| Sensitivity yan-grid tek noktada parlıyor (madde 4 tripwire) | true | "Post-hoc kurtarma" yasak |

## 8. Robustness Suite (zorunlu, SOP-3) + ek

| Test | Beklenti |
|---|---|
| Walk-forward 6 dilim | ≥ 4 dilim pozitif Sharpe her iddia için |
| Param perturbation (madde 4 yan-grid) | Sharpe drop < %25 ortalama |
| Symbol-out CV | Top-3 sembolü dışarıda bırak — Sharpe drop < %30 |
| Regime split (bull/bear/range) | En az 2/3'te pozitif (bull-only edge kabul edilmez) |
| Stress periods | 2022-05 (LUNA), 2022-11 (FTX), 2023-03 (USDC depeg), 2024-03 (BTC ATH), 2024-08 (Yen carry) — single-event MaxDD < %12 |
| Shuffle baseline | p < 0.05 (placebo'yu yenmeli) |
| **EK 1 — Stablecoin sensitivity:** | Stablecoin correction uygulanmazsa sonuç >%30 değişiyorsa → hipotez **mekanik artefakt** + red |
| **EK 2 — Parent contamination check:** | HYP-REGIME-003 ile aynı event tarihlerinde örtüşme > %70 ise → bağımsız edge yok, parent'ı yeniden paketliyor + red |

## 9. RAG Referansları

- (yok) — corpus search empty. ⚠ Bu hipotez literatür-yetimi.
- İlgili olabilecek genel kaynaklar (henüz corpus'a alınmamış, citation değil):
  - Glassnode Insights — BTC dominance regime studies (web, citation yok)
  - Adam Grimes — "Trading from a Quantitative Edge" ch. on regime filters (genel, BTC.D özel değil)

> Lab'in RAG corpus refresh sırasında (haftalık) bu konuyu cover eden kaynak eklemesi rica edilir.

## 10. Karar Çerçevesi (önceden taahhüt)

1. **Tüm gate ve robustness ✓:** `IN_TEST` → Lab tournament'a aday gönderilir. **Ek koşul:** HYP-REGIME-003 ile ayrı bağımsız edge olduğu kanıtlanmalı (Lab'e devr).
2. **Gate ✓ ama EK 1/2 başarısız:** Red. "Edge yok, artefakt veya parent kopyası."
3. **Gate ≥1 başarısız:** Red. Gerekçe `learning.md`'ye.
4. **Belirsiz (event count borderline, p marjinal):** Veri uzatma → +1y veri ekle, test bir kez (sadece) tekrarlanır. İkinci kez belirsizse red.

## 11. Bağlı Doc'lar (depends_on)

- `researcher-20260512-regime-btc-dominance-trend-veto` (HYP-REGIME-003) — continuous slope; bu hipotezin **NULL alternatifi**
- `researcher-20260509-btc-dominance-altrotation` (H22) — orijinal BTC.D iddiası

## 12. Reproducibility

- git_hash: (test sırasında doldurulacak)
- config_hash: (backtest config'in pre-registration hash'i — kod yazılır yazılmaz dondurulacak)
- data_hash: BTC.D snapshot manifest + universe build manifest hash'leri raporda

---

**Not — researcher self-check:** Bu hipotez `low confidence` ile pre-register edildi çünkü (a) RAG=0, (b) parent kontaminasyon riski yüksek, (c) discrete event tabanlı kripto edge'i literatürde nadir. Beklentim: **%30 ihtimal IN_TEST'e geçer, %70 ihtimal red.** Bu sağlıklı baz oran (mandate KPI: %20-40 terfi).
