---
doc_id: researcher-20260601T123000-iii-compression-breakout-low-corr-to-vsa
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-01T12:30:00Z
status: DRAFT
confidence: low
depends_on:
  - shared-fact-current-trading-universe-2026-06
  - active-strategy-vsa_climax_test-d1-crypto
blocks: []
requested_review_from:
  - lab_scientist
  - risk_officer
tags:
  - hypothesis
  - candle-pattern
  - inside-bar
  - iii
  - volman-dd
  - compression-breakout
  - low-corr-vsa
  - cross-strategy-diversification
supersedes: null
hash: null
---

# HYP-2026-06-01 — Triple Inside Bar (iii) Compression-Breakout, low-corr-to-vsa

## 0. Bir cümle iddia (ölçülebilir)

> 1D timeframe'de, geçerli 14 sembollük USDT-perpetual evrende, 2022-01-01 — 2026-05-31 penceresinde, **3 ardışık inside bar (iii)** sonrası **bar4'ün kapanışı iii-range dışında olduğunda** açılan, **karşı uç = stop / 2R = TP** kuralıyla, taker 7.5bps + slip 5bps fee modeliyle, **canlı `vsa_climax_test` günlük PnL serisiyle Pearson |ρ| < 0.20** ve aşağıdaki gate'leri AYNI ANDA tutar:
>
> - net annualized return (pool, equal-weight) **≥ +%18**
> - Sharpe (annual, OOS walk-forward ortalaması) **≥ 0.80**
> - MaxDD (account-equity bazlı, NOT cumulative-PnL bazlı — CT-RSK-01 dersi) **≤ %25**
> - profit factor **≥ 1.30**
> - shuffle baseline'ı yener (p < 0.05)
> - Bonferroni-eşdeğer düzeltme sonrası anlamlılık korunur (n_trial = 1 — fiksli parametre, multiple-testing yükü minimum)

Bu iddianın TAMAMI çürürse hipotez ölür; "ROI iyi ama korelasyon yüksek" → REJECT (cross-strategy diversification motoru kaybolur).

## 1. Gerekçe (RAG referansları)

- **[RAG #2 book_candlestick_statistics]**: "Tekli inside bar zayıf (Bulkowski %54 breakout win — performance rank 78/103). Ancak **'ii' (double inside bar) veya 'iii' (triple inside bar) breakout daha güçlü**. Volman'ın DD setup'ı buradan türer." → iii compression bottleneck içeren, kompakt bir continuation/breakout setup'ı.
- **[RAG #6 book_market_structure_order_flow]** — Crypto 1D'de mekanik çalışabilirlik tablosu: "BOS (close-based, n=3) **Yüksek**. Net kural, backtestable, az parametrik." → iii breakout n=3 close-based çıkış kuralıyla aynı sınıfta; "az parametrik" oluşu curve-fit yüzeyini bilinçli daraltır.
- **[RAG #1 book_lopez_summary] — anti-overfit çerçeve**: "Strategy serbest parametre sayısı / örnek sayısı > 1/30" kırmızı bayraktır → bu hipotez yalnız 4 sabit parametre (iii_n=3, stop_mode=opposite_extreme, tp_R=2.0, entry=bar5_open) ile çalıştırılır. Sweep YOK. Optuna YOK.
- **[RAG #10 book_candlestick_statistics] — Mat Hold karşılaştırması**: Mat hold (5-bar bull continuation) %74 oranıyla rank 10/103. iii compression mat hold'un 3-barlık daha sıkı versiyonu olarak modellenebilir; ama iii Bulkowski'de eksplisit istatistiklenmediği için **prior'unu agresif çekmeye hakkımız yok** — gate'ler düşük tutuldu (Sharpe ≥ 0.8, return ≥ +%18 — vsa_climax canlı seviyesinin yarısı).

## 2. Null hipotez

H0: iii sonrası bar4 breakout sinyali, aynı evrende **rastgele bar4 yönüyle alınan** giriş setine kıyasla net edge üretmez (Diebold-Mariano veya shuffle baseline ile p ≥ 0.05).

H0 ALSO: **|ρ(daily_pnl(iii), daily_pnl(vsa_climax_test_live))| ≥ 0.40** → diversification yararı sıfır → REJECT.

## 3. Pre-registered Mekanik Tanım (donmuş)

```python
def iii_breakout_signal(df_1d):
    # df_1d kolonları: open, high, low, close (UTC günlük bar kapanışı)
    # iii: bar t-2, t-1, t — her biri bir önceki bar'ın iç barı
    h, l, c = df_1d.high, df_1d.low, df_1d.close

    is_inside_t1 = (h.shift(1) < h.shift(2)) & (l.shift(1) > l.shift(2))
    is_inside_t  = (h         < h.shift(1)) & (l         > l.shift(1))
    is_inside_t2 = (h.shift(2) < h.shift(3)) & (l.shift(2) > l.shift(3))

    iii_complete = is_inside_t2 & is_inside_t1 & is_inside_t  # t bar kapanışında iii tamamlandı

    iii_high = pd.concat([h.shift(2), h.shift(1), h], axis=1).max(axis=1)
    iii_low  = pd.concat([l.shift(2), l.shift(1), l], axis=1).min(axis=1)

    # bar t+1 kapanışı → karar; entry bar t+2 open (lookahead-safe)
    breakout_up   = iii_complete.shift(1) & (c > iii_high.shift(1))
    breakout_down = iii_complete.shift(1) & (c < iii_low.shift(1))
    # Entry: NEXT bar open (bar t+2 open after decision on t+1 close)
    return breakout_up, breakout_down  # iki ayrı boolean serisi, AYNI bar'da ikisi de True olamaz (overlapping range)

# Yönetim:
# long entry  = bar(t+2).open
# long stop   = iii_low_at_decision_bar  - 1 tick
# long TP     = entry + 2 * (entry - stop)   # 2R fixed
# short entry = bar(t+2).open
# short stop  = iii_high_at_decision_bar + 1 tick
# short TP    = entry - 2 * (stop - entry)
# Time-stop: 10 bar (2 hafta) içinde TP veya SL hit olmazsa pozisyon kapatılır (bar close fill)
```

**Parametre listesi (DONDU — kod yazılmadan önce):**

| Param | Değer | Sweep? |
|---|---|---|
| iii_n_consec_inside | 3 | HAYIR (Volman canonical) |
| decision_basis | bar t+1 close vs iii range | HAYIR |
| entry_bar | bar t+2 open (lookahead-safe) | HAYIR |
| stop_mode | iii opposite extreme ± 1 tick | HAYIR |
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
- trade_count_per_year_per_symbol (minimum 8 trade/yıl/sembol değilse → "low N, statistically inadmissible" not düş, ama RED değil; sample bias için dipnot)
- shuffle_baseline_p
- corr_pearson_daily_pnl_vs_vsa_climax_live (|ρ| < 0.20 hard gate)
- conditional_corr_in_drawdown_regime (sadece her iki strateji de DD modundayken — tail dependency)

## 5. Independent variables (zaten dondurulmuş — bkz §3)

Yok. Sweep yok. Curve-fit yüzeyi yok.

## 6. Beklenen p-value ve gate

- shuffle_baseline_p < 0.05 (yön shuffle, 1000 permütasyon)
- Bonferroni etkili n=1 → eşik aynı, 0.05
- Walk-forward dilimlerinin **en az %66'sı pozitif Sharpe** üretmeli (anti-curve-fit kontrolü)
- IS Sharpe / OOS Sharpe oranı < 1.5 olmalı (Lopez de Prado kırmızı bayrak: IS > 3·OOS ise red)

## 7. Stop criteria (araştırmayı terkettiren red eşikleri)

Bu hipotez aşağıdaki KOŞULLARDAN BİRİ tetiklenirse **terkedilir, iterate yapılmaz, hatta v2 yazılmaz** (curve-fit motorunu kapatmak için):

1. **Aktif futures perp universe'da yıllık trade < 60** (toplam 14 sembolde) → pattern çok seyrek, anlamlı istatistik kurulamaz → REJECT.
2. **In-sample Sharpe < 0.5** → walk-forward'a girmez, ölür.
3. **|ρ(iii_pnl, vsa_climax_live_pnl)| ≥ 0.40** → diversification motoru kaybolur; ROI ne olursa olsun seed'in **amacı çürüdüğü için** REJECT (cross-strategy seed bu yüzden açıldı; "iyi strateji ama tek başına" kaydını başka seed'e bırak).
4. **MaxDD (account-equity) > %35** → risk budget'ı aşar.
5. **Shuffle baseline'ı yenemez (p ≥ 0.05)** → gerçek yön edge'i kanıtlanamaz.

> Iterate izni: §3 parametreleri DONMUŞTUR. Eğer sonuçlar pozitif edge gösterir ama gate'i geçemezse (ör. DD yüksek), SOP-4b kapsamında risk_pct/concurrent_max/regime_filter v2 hipotezleri açılır — AMA mekanik tanım (iii_n, tp_R, stop_mode) DEĞİŞMEZ. Aksi takdirde p-hacking'e döner.

## 8. Curve-fit Kırmızı-Bayrak Self-Audit (Lopez de Prado §16, ön-uygulanmış)

| Bayrak | Bu hipotezde durum |
|---|---|
| Serbest parametre / örnek > 1/30 | **TEMİZ.** 0 serbest parametre (sweep yok). |
| Bulkowski stats kripto'da test edilmedi | **AÇIK RİSK.** RAG referansları US-equity tabanlı; kripto'da iii istatistikleri yok. Bu yüzden gate'ler agresif değil (ROI ≥ +%18, vsa_climax canlı seviyenin yarısı). |
| Tek bir 2022 LUNA / 2022-11 FTX olayı tüm PnL'i taşıyor olabilir | **Stress-period decomposition zorunlu** (SOP-3 madde 6). %50'den fazla PnL tek stres dilimindense REJECT. |
| iii pattern rare → trade count düşük → Sharpe gürültülü | **Stop-criterion-1** ile şart bağlanmış: <60 trade/yıl pool → REJECT. |
| Time-stop = 10 bar self-seçim olabilir | **DONDU.** Volman default. Sweep yapmıyoruz. |
| Direction = symmetric (her iki yön) — mute olarak trend filter eklemek cazip | **EKLEMEYECEĞİZ.** Çünkü her ek koşul bir gizli parametre = post-hoc curve-fit. |

## 9. Reproducibility tag (sonra doldurulacak)

```
git_hash: <doldur>
config_hash: <doldur>
data_hash: <doldur>
universe_snapshot: shared-fact-current-trading-universe-2026-06
```

## 10. Beklenti yönetimi (anti-narrative kalkanı)

Bu hipotezin **bilinçli ön-tahmini**: iii compression breakout, klasik trader anlatısında ("coiled spring") çekicidir ama Bulkowski'nin tekli inside bar %54 win-rate sayısı **uyarıdır**. iii bunu yükseltir ama ne kadar olduğu **kripto için ölçülmemiştir**. Bu nedenle olasılık dağılımım:

- %40 hipotez stop-criterion-1'de düşer (yıllık trade < 60) — pattern çok seyrek.
- %25 hipotez OOS Sharpe < 0.8'de düşer (in-sample edge OOS'a taşınmaz).
- %20 hipotez korelasyon gate'inde düşer (|ρ| ≥ 0.40) — yönsel sinyaller VSA ile beklenenden daha fazla örtüşüyor olabilir.
- %10 hipotez gate'i geçer ama MaxDD agresif → SOP-4b iterate v2.
- %5 hipotez direkt terfi adayı → Lab tournament.

Bu beklenti, hipotezin REJECT olduğu durumda kendimi tebrik etmemi sağlar (researcher KPI: terfi oranı %20-40, reddedilenler en az kadar değerli).

## 11. Sonraki adım

1. Bu doc PROPOSED → lab_scientist & risk_officer review (24h SLA).
2. Endorse/critique sonrası: pre-registration commit → git hash dondur.
3. Backtest pipeline çağrısı: `iii_d1_low_corr_vsa` config seed_abort runner üzerinden (existing iterate pipeline). Mekanik tanımdan farklı parametre denemesi YOK; sadece §3 config tek çalıştırma.
4. Robustness suite (SOP-3) ZORUNLU — pas geçilirse ops_engineer protocol_violation flag.
5. Korelasyon ölçümü: günlük PnL serisinde Pearson + Spearman + conditional-on-DD, üçü de raporlanır.
6. Karar dokümanı: terfi adayı / iterate v2 / REJECT — gerekçe ile arşiv.
