---
doc_id: researcher-20260603T143000-ii-double-inside-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-03T14:30:00Z
status: DRAFT
confidence: low
depends_on:
  - shared-fact-current-trading-universe-2026-06
  - active-strategy-vsa_climax_test-d1-crypto
  - researcher-20260601T123000-iii-compression-breakout-low-corr-to-vsa
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - candle-pattern
  - inside-bar
  - ii
  - double-inside
  - volman-dd
  - compression-breakout
  - low-corr-vsa
  - cross-strategy-diversification
supersedes: null
hash: null
---

# HYP-2026-06-03 — Double Inside Bar (ii) Breakout, low-corr-to-vsa

## 0. Bir cümle iddia (ölçülebilir)

> 1D timeframe'de, geçerli 14 sembollük USDT-perpetual evrende, 2022-01-01 — 2026-05-31 penceresinde, **2 ardışık inside bar (ii)** sonrası **bar3'ün kapanışı ii-range dışında olduğunda** açılan, **karşı uç = stop / 2R = TP** kuralıyla, taker 7.5bps + slip 5bps fee modeliyle, **canlı `vsa_climax_test` günlük PnL serisiyle Pearson |ρ| < 0.20** ve aşağıdaki gate'leri AYNI ANDA tutar:
>
> - net annualized return (pool, equal-weight) **≥ +%15**
> - Sharpe (annual, OOS walk-forward ortalaması) **≥ 0.70**
> - MaxDD (account-equity bazlı — CT-RSK-01 dersi) **≤ %25**
> - profit factor **≥ 1.25**
> - shuffle baseline'ı yener (p < 0.05)
> - Bonferroni-eşdeğer düzeltme sonrası anlamlılık korunur (n_trial = 1 — fiksli parametre)

Gate'ler `iii` hipoteziyle karşılaştırıldığında **bilinçli olarak daha gevşek** (return ≥ +%15 vs +%18, Sharpe ≥ 0.70 vs 0.80, PF ≥ 1.25 vs 1.30) çünkü iddiam: **ii pattern, iii'den daha sık tetiklenir ama bar başına edge daha düşük** (Bulkowski'nin tekli inside %54 → çift inside %58-62, üçlü inside ≈ %65 prior'una göre). Eğer ii bu gevşek gate'i geçemezse iii'yi kıyas olarak yenmesi matematiksel olarak imkansızdır.

## 1. Gerekçe (RAG referansları)

- **[RAG #2 book_candlestick_statistics]**: "Tekli inside bar zayıf (Bulkowski %54 breakout win — performance rank 78/103). Ancak **'ii' (double inside bar) veya 'iii' (triple inside bar) breakout daha güçlü**. Volman'ın DD setup'ı buradan türer." → ii ve iii spesifik olarak yan yana zikredilmiş; bizim corpusumuzda iii pre-register edildi (HYP-2026-06-01), ii şu ana kadar pre-register edilmemiş — **eksik kalan boşluğu kapatıyorum**, yeni iddia uydurmuyorum.
- **[RAG #6 book_market_structure_order_flow] — Crypto 1D mekanik çalışabilirlik**: "BOS (close-based, n=3) **Yüksek**. Net kural, backtestable, az parametrik." → ii breakout close-based, n=3 (ii compression + breakout bar) ile aynı sınıfta.
- **[RAG #1 book_lopez_summary] — anti-overfit çerçeve**: "Strategy serbest parametre sayısı / örnek sayısı > 1/30" kırmızı bayraktır → bu hipotez yalnız 4 sabit parametre (ii_n=2, stop_mode=opposite_extreme, tp_R=2.0, entry=breakout+1_open) ile çalıştırılır. **Sweep YOK. Optuna YOK. n_trial=1.**
- **[RAG #10 book_candlestick_statistics] — Mat Hold yan-referans**: Mat Hold (5-bar) %74 continuation. ii compression onun 2-barlık çok daha gevşek versiyonu; **prior'unu agresif çekmek bilim değil narrative bias** — bu yüzden gate +%15'te, vsa_climax canlı seviyenin %40'ında.

## 2. Null hipotez

H0₁: ii sonrası bar3 breakout sinyali, aynı evrende **rastgele bar3 yönüyle alınan** giriş setine kıyasla net edge üretmez (shuffle baseline ile p ≥ 0.05).

H0₂: **|ρ(daily_pnl(ii), daily_pnl(vsa_climax_test_live))| ≥ 0.40** → diversification yararı sıfır → REJECT (cross-strategy seed amacı çürür).

H0₃ (kıyaslama gate): **net_annualized_return(ii) < net_annualized_return(iii)** olamaz **ve aynı zamanda** ii pozitif edge gösteremez. Yani: eğer iii REJECT olduysa (önceki hipotez sonucunda), ii'nin de positive olma olasılığı düşük; eğer ii iii'yi açık fark geçerse → "lev curve-fit" şüphesi devreye girer (gevşek pattern niye daha güçlü?).

## 3. Pre-registered Mekanik Tanım (donmuş)

```python
def ii_breakout_signal(df_1d):
    # df_1d kolonları: open, high, low, close (UTC günlük bar kapanışı)
    # ii: bar t-1, t — her biri bir önceki bar'ın iç barı
    h, l, c = df_1d.high, df_1d.low, df_1d.close

    is_inside_t1 = (h.shift(1) < h.shift(2)) & (l.shift(1) > l.shift(2))
    is_inside_t  = (h         < h.shift(1)) & (l         > l.shift(1))

    ii_complete = is_inside_t1 & is_inside_t  # t bar kapanışında ii tamamlandı

    ii_high = pd.concat([h.shift(1), h], axis=1).max(axis=1)
    ii_low  = pd.concat([l.shift(1), l], axis=1).min(axis=1)

    # bar t+1 kapanışı → karar; entry bar t+2 open (lookahead-safe)
    breakout_up   = ii_complete.shift(1) & (c > ii_high.shift(1))
    breakout_down = ii_complete.shift(1) & (c < ii_low.shift(1))
    # AYNI bar'da yalnız BIR yön True olabilir (ii_range non-overlapping)
    return breakout_up, breakout_down
```

**Pozisyon yönetimi (donmuş):**

- long entry  = bar(t+2).open
- long stop   = ii_low_at_decision_bar  - 1 tick
- long TP     = entry + 2 * (entry - stop)   # 2R fixed
- short entry = bar(t+2).open
- short stop  = ii_high_at_decision_bar + 1 tick
- short TP    = entry - 2 * (stop - entry)
- Time-stop: 10 bar (2 hafta) içinde TP/SL hit olmazsa bar close fill ile kapat
- BE-protect / partial / trailing **YOK** (ekstra parametre → curve-fit yüzeyi)

**Parametre listesi (DONDU — kod yazılmadan önce):**

| Param | Değer | Sweep? |
|---|---|---|
| ii_n_consec_inside | 2 | HAYIR (Volman canonical "ii") |
| decision_basis | bar t+1 close vs ii range | HAYIR |
| entry_bar | bar t+2 open (lookahead-safe) | HAYIR |
| stop_mode | ii opposite extreme ± 1 tick | HAYIR |
| tp_R | 2.0 | HAYIR |
| time_stop_bars | 10 | HAYIR |
| risk_pct | 0.005 (vsa_climax canlı parametre) | HAYIR |
| universe | aktif 14-sembollük futures perp pool | HAYIR (vsa_climax ile birebir kesişim — korelasyon ölçümü için zorunlu) |
| timeframe | 1D | HAYIR |

**Optuna kullanılmayacaktır.** n_trial = 1. Bonferroni yükü minimum.

## 4. Dependent variables (önceden ilan)

- net_annualized_return_pool (equal-weight, fee+slip dahil)
- Sharpe_annual_oos (walk-forward 3y train / 6m test, step 3m)
- MaxDD_equity_based (CT-RSK-01 dersi: zero-base cumulative PnL DEĞİL, gerçek account equity time series)
- profit_factor
- trade_count_per_year_per_symbol (minimum 12 trade/yıl/sembol değilse → "low N, statistically inadmissible" dipnot; <60/yıl pool genelinde → REJECT)
- shuffle_baseline_p
- corr_pearson_daily_pnl_vs_vsa_climax_live (|ρ| < 0.20 hard gate)
- conditional_corr_in_drawdown_regime (sadece her iki strateji de DD modundayken — tail dependency)
- **kıyaslama metriği**: net_return_ii vs net_return_iii (iii hipotez sonucu mevcutsa) — açıklayıcı, gate değil.

## 5. Independent variables (zaten dondurulmuş — bkz §3)

Yok. Sweep yok. Curve-fit yüzeyi yok.

## 6. Beklenen p-value ve gate

- shuffle_baseline_p < 0.05 (yön shuffle, 1000 permütasyon)
- Bonferroni etkili n=1 → eşik aynı, 0.05
- Walk-forward dilimlerinin **en az %66'sı pozitif Sharpe** üretmeli (anti-curve-fit kontrolü)
- IS Sharpe / OOS Sharpe oranı < 1.5 olmalı (Lopez de Prado kırmızı bayrak: IS > 3·OOS ise red)

## 7. Stop criteria (araştırmayı terkettiren red eşikleri)

Bu hipotez aşağıdaki KOŞULLARDAN BİRİ tetiklenirse **terkedilir, iterate yapılmaz, hatta v2 yazılmaz**:

1. **Aktif futures perp universe'da yıllık trade < 60** (toplam 14 sembolde, pool) → pattern çok seyrek değil (ii iii'den ~3x daha sık beklenir); 60'ın altındaysa **veri/kod hatası şüphesi** → audit, REJECT.
2. **In-sample Sharpe < 0.5** → walk-forward'a girmez, ölür.
3. **|ρ(ii_pnl, vsa_climax_live_pnl)| ≥ 0.40** → diversification motoru kaybolur; ROI ne olursa olsun seed'in amacı çürüdüğü için REJECT.
4. **MaxDD (account-equity) > %35** → risk budget'ı aşar.
5. **Shuffle baseline'ı yenemez (p ≥ 0.05)** → gerçek yön edge'i kanıtlanamaz.
6. **ii_net_return > 1.5 × iii_net_return AYNI ANDA ii Sharpe > 1.5 × iii Sharpe** → "gevşek pattern niye sıkıdan ezici fark üstün" sorusu → curve-fit/lookahead/bug şüphesi → kod audit zorunlu, gate'i geçse bile lab'e devretme YOK; researcher tarafında forensic.

> Iterate izni: §3 parametreleri DONMUŞTUR. Eğer sonuçlar pozitif edge gösterir ama gate'i geçemezse (ör. DD yüksek), SOP-4b kapsamında risk_pct/concurrent_max/regime_filter v2 hipotezleri açılır — AMA mekanik tanım (ii_n=2, tp_R=2.0, stop_mode=opposite_extreme) DEĞİŞMEZ.

## 8. Curve-fit Kırmızı-Bayrak Self-Audit (Lopez de Prado §16, ön-uygulanmış)

| Bayrak | Bu hipotezde durum |
|---|---|
| Serbest parametre / örnek > 1/30 | **TEMİZ.** 0 serbest parametre (sweep yok). |
| Bulkowski stats kripto'da test edilmedi | **AÇIK RİSK.** US-equity tabanlı; kripto'da ii istatistikleri yok. Bu yüzden gate +%15'te. |
| Tek bir 2022 LUNA / 2022-11 FTX olayı tüm PnL'i taşıyor olabilir | **Stress-period decomposition zorunlu** (SOP-3 madde 6). %50'den fazla PnL tek stres dilimindense REJECT. |
| ii pattern frequency yüksek olabilir → küçük edge × büyük N = pozitif görünüm | **Per-trade mean_R + standard error raporlanır**; bootstrap CI sıfırı içeriyorsa REJECT (büyük N gizlenmesin). |
| Time-stop = 10 bar self-seçim | **DONDU.** iii ile aynı, kıyaslama için. Sweep yok. |
| Direction = symmetric (her iki yön) — trend filter eklemek cazip | **EKLEMEYECEĞİZ.** Post-hoc filter = gizli parametre. |
| iii ile **aynı** universe ve tarih aralığı kullanılması, korelasyon ölçümünü iyimser yapabilir (örtüşen rejim) | **Conditional-on-DD korelasyon** ayrıca raporlanır; düz Pearson tek başına gate değil. |
| ii iii'nin altküme'sidir (her iii aynı zamanda iidir) → sample contamination | **Açıkça not ediyorum**: ii trade listesinden iii trade'lerini ÇIKARMAYACAĞIZ (mekanik tanım donuk). Ama hibrit kıyaslamada (§6'deki ii vs iii) overlap raporlanır. |

## 9. Reproducibility tag (sonra doldurulacak)

```
git_hash: <doldur>
config_hash: <doldur>
data_hash: <doldur>
universe_snapshot: shared-fact-current-trading-universe-2026-06
```

## 10. Beklenti yönetimi (anti-narrative kalkanı, agresif negatif prior)

ii hipotezi **bilinçli olarak iii'nin gölgesinde** yazıldı. Bulkowski'nin tekli inside %54'üne çok yakın bir prior'um var (ii ≈ %58-62 win, ama 2R asymmetric → ~%40 win-rate edge için yeter, riskli alan). Olasılık dağılımım:

- **%50** hipotez OOS Sharpe < 0.7'de düşer — pattern yeterince güçlü değil.
- **%20** hipotez korelasyon gate'inde düşer (|ρ| ≥ 0.40) — yön sinyalleri VSA ile örtüşür çünkü ii rejim-bağımlı bar4-bar5 hareketi VSA climax'in yan ürünüdür.
- **%15** hipotez stop-criterion-6'da forensic'a düşer (ii iii'yi şüpheli ezerek geçer → kod hatası).
- **%10** hipotez gate'i marjinal geçer + DD agresif → SOP-4b iterate v2.
- **%5** hipotez doğrudan terfi adayı → Lab tournament.

**Pre-test public prior'um**: Bu hipotezin REJECT olmasını bekliyorum. Reject de olsa "iii vs ii relative edge" raporu cross-strategy diversification seed'inin kapısını kapatmaya yardım eder (eğer ii de iii de REJECT → inside-bar ailesini bu universe'da tüketmiş oluruz, başka aileye geçiş gerekçesi sağlam).

## 11. Sonraki adım

1. Bu doc PROPOSED → lab_scientist & risk_officer review (24h SLA).
2. Endorse/critique sonrası: pre-registration commit → git hash dondur.
3. Backtest pipeline: `ii_d1_low_corr_vsa` config, mevcut iii pipeline'inin paramatrik klonu (ii_n=2 set). Mekanik tanımdan farklı parametre denemesi YOK; sadece §3 config tek çalıştırma.
4. Robustness suite (SOP-3) ZORUNLU.
5. Korelasyon: Pearson + Spearman + conditional-on-DD üçü raporlanır.
6. Karar dokümanı: terfi adayı / iterate v2 / REJECT — gerekçe ile arşiv.
7. **iii hipotez sonucu (HYP-2026-06-01) eğer henüz kapanmadıysa**, ii backtest çıktısı iii ile yan yana raporlanır; iii REJECT ise ii pre-test prior'ı bu sonuçla güncellenir (anti-narrative kalkanı: iii edge yoksa ii'nin pozitif olma şansı düşer).
