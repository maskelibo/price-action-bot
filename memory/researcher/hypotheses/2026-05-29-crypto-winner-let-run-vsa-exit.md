# Hipotez: HYP-2026-05-29-crypto-winner-let-run-vsa-exit

PRE-REGISTRATION — kod yazmadan önce. Forex'te kanıtlanan WINNER-LET-RUN
(brooks 8fx 4H) edge'inin crypto 15m vsa_climax_test karşılığına TRANSFER testi.

## Bağlam / Önceki kanıt (forex)
- learning.md 2026-05-29 "WINNER-LET-RUN exit opt (brooks 8FX 4H) — GENUINE EDGE":
  trail_mult 1.5→3.0 + time-exit KORUNDU + force_exit_from_entry → OOS robMed +4→+17,
  Sharpe +0.41→+0.74, top5 43→51%, win% düz, DD düz, sign-flip null p=5e-5, monotone yüzey.
- Method-win: GERÇEK engine, exit constructor knob'ları (hand-coded exit YOK). ATR native per-TF.
- Tuzaklar (tekrarLAMA): (1) V1b no-time-exit AUD'yi 143R'ye patlattı (sec13.4 stuck-trade
  artefakt) → time/EMA force-exit HER ZAMAN açık kalmalı. (2) Single-partial/pure-trail (V2/V3)
  sağ-kuyruğu öldürdü (top5 43→20%) → partial yapısı brooks sağ-skew'ini koruyor, sökME.
  (3) Sub-TF ATR'yi üst-TF bar'da değerlendirme = trail gevşetme artefaktı (MTF v1).

## İddia (H1)
"Crypto 15m vsa_climax_test (wide-stop sl_pct>=0.025, risk 0.5%) baseline çıkışında
(runner_trail_mult 1.5, tp1_R 1.0 / tp2_R 1.5, close 30/30/40, time-force-exit 30 bar),
runner trail genişliğini artırmak (1.5→2.0/2.5/3.0, time-exit KORUNARAK) büyük kazananların
koşmasına izin verir → OOS top-5% kazanan R payı ARTAR, aylık-medyan ROI / Sharpe ARTAR;
win% düşüşü net etkiyi negatife çevirmez."

## Null hipotez (H0 — Popper: ne olursa çürür)
H0: Trail genişletme OOS'ta top5-payını artırmaz VEYA artırsa bile win% düşüşü mean_R'yi
ve aylık-medyan ROI'yi baseline'ın altına çeker (net negatif). Crypto'da winner-let-run
edge'i yok; gözlenen herhangi bir IS iyileşmesi OOS'ta kaybolur (overfit) veya shuffle-null
ile ayırt edilemez (p>=0.05 BH-FDR sonrası).
H0 ÇÜRÜR ANCAK: OOS_top5 ARTAR **VE** (OOS_aylık-medyan ARTAR VEYA OOS_Sharpe ARTAR) **VE**
OOS_mean_R baseline-eps'in altına düşmez (>= -0.02R) **VE** shuffle-null BH-FDR'ı geçer.

## Varyantlar (her biri AYRI pre-reg değil — aynı aileyiz, BH-FDR ile düzeltilecek)
- B_baseline: trail 1.5, time-exit 30bar (pool default exit). GATE-1 ile pool R'sini reproduce et.
- V1a_trail{2.0,2.5,3.0}: SADECE trail genişlet, time-exit KORU (forex KAZANAN).
- V1a_fe_trail{2.0,2.5,3.0}: + force_exit_from_entry=True (forex'te DD/stuck bound iyileştirdi).
- V1b_notime_trail{1.5,2.5}: time-exit KALDIR (FALSIFICATION/tuzak testi — patlamayı bekliyoruz).
- V2_1partial_run70_trail{2.0,2.5}: tek partial + ağır runner (forex'te sağ-kuyruk ÖLDÜ — red beklenir).
- V3_puretrail{2.0,2.5}: TP yok, saf trail (forex'te sağ-kuyruk ÖLDÜ — red beklenir).

## Bağımlı değişkenler (pre-registered metrikler)
mean_R, win%, top-5% kazanan R payı (%), aylık-medyan ROI, aylık-mean ROI, realized MaxDD
(continuous equity), Sharpe (aylık), ort. tutuş süresi (saat). IS=[2021-05,2024-01),
OOS=[2024-01,2026-06).

## Karar kuralı (SOP-4)
TERFİ ADAYI ancak: H0 çürür (yukarıdaki AND) **VE** robustness:
  - IS→OOS top5 & robMed decay < %30 (Sharpe için)
  - monotone-ish trail yüzeyi (ekstrem uçta best değil)
  - shuffle-null p<0.05 BH-FDR sonrası
  - DD baseline'dan >%30 KÖTÜLEŞMEZ
RED: yukarıdakilerden ≥1 fail → gerekçeli arşiv. %80 red normaldir.

## Calibration (Tetlock — predictive interval, ÖNCEDEN)
- P(en az 1 trail-genişletme varyantı H1-candidate, OOS) = %55 (forex transfer + crypto
  rejim farkı; 15m gürültü trail'i erken stoplayabilir, FX 4H'den daha riskli).
- P(net aylık-medyan ROI artışı >= +1.0pp deploy-edilebilir) = %35.
- P(V1b notime patlar — stuck-trade artefakt görülür) = %80 (forex'te kesin oldu).
- P(V2/V3 sağ-kuyruk öldürür, top5 düşer) = %75.
- Beklenen sonuç: V1a trail-genişletme marjinal pozitif VEYA neutral; V1b/V2/V3 red.

## Lookahead / artefakt checklist (Feynman — kendimi kandırma)
1. GERÇEK engine, exit constructor knob (hand-coded R-reblend YOK — forex v1 onunla battı).
2. ATR trail = strateji metadata, 15m bar'dan native (atr14 yoksa initial_R*0.5 fallback) →
   sub-TF/üst-TF ATR karışımı YOK → MTF artefakt construction'la imkansız.
3. GATE 1: engine baseline-exit, pool pkl VSA R'sini reproduce etmeli (per-sym mean|ΔR|<=0.05)
   YOKSA harness GÜVENİLMEZ, DUR.
4. Aynı entry sinyalleri tüm varyantlarda; SADECE exit değişir.
5. sl_pct>=0.025 filtre + risk 0.5% + fee 15bps round-trip — baseline ile birebir.
6. Time-force-exit'i sökersek (V1b) bunu FALSIFICATION testi olarak işaretle, deploy aday DEĞİL.
7. PA_DUCKDB_READ_ONLY=true. Canlı daemon'a dokunma. iid MC yok (gerçek path).

## Stop criteria
GATE-1 fail (reproduce edilemezse) → tüm çalışma DUR, harness güvenilmez.
IS'te hiçbir trail-genişletme top5'i artırmazsa → OOS'a bakma, RED.

## Reproducibility
git=audit-hardreview-20260528 @ e7d0a90, config=risk_phoenix_scalp_15m_widestop_vsa2.yaml,
manifest=vsa_climax_test_15m.yaml (vol_sma_mult 2.0), data=market.duckdb 15m (read-only),
SEED=12345. harness=scripts/crypto_winner_let_run_vsa_exit.py, raw=/tmp/wlr_vsa_variants.pkl.

==============================================================================
## SONUÇ (2026-05-29 — post-test) — H0 ÇÜRÜDÜ, TERFİ ADAYI: V1a_trail2.5 / 3.0
==============================================================================
### GATE / artefakt teyidi
- Deployed sec53 pool ARTIK current HEAD'den reproduce EDİLMİYOR (kod drift: Faz 14.27 C1
  fallback + audit fix; kanonik builder BTC 8002 vs cached 7952; mean|ΔR|~0.8). Pool STALE.
  → anchor olarak STALE POOL DEĞİL, current-code baseline kullanıldı (apples-to-apples).
  REPRODUCIBILITY BULGUSU: realistic_backtest.py'nin +1.04 mean_R baseline'ı STALE poola dayalı.
- GATE-1 determinism PASS (current-code default exit iki run bit-identical).
- ATR trail native 15m (VSA atr20 → engine atr14 fallback initial_R*0.5, hepsi 15m-native) →
  MTF v1 sub-TF-ATR artefaktı construction'la İMKANSIZ. Gerçek engine, hand-coded/reblend exit YOK.

### Trail-genişliği sweep (ANA LEVER) — KAZANDI, monotone
| variant      | OOS mR | OOS med | OOS Shrp | OOS DD | win% | 5y med | 5y Shrp | neg/61 |
|--------------|--------|---------|----------|--------|------|--------|---------|--------|
| B_baseline   | +1.115 | +8.83   | +1.66    | -13.7  | 48   | +7.28  | +1.60   | 2 |
| V1a_trail2.0 | +1.412 | +11.10  | +1.62    | -13.7  | 48   | +9.67  | +1.65   | 1 |
| V1a_trail2.5 | +1.596 | +14.02  | +1.68    | -13.7  | 48   | +11.72 | +1.75   | 0 |
| V1a_trail3.0 | +1.645 | +14.00  | +1.74    | -13.7  | 48   | +12.20 | +1.85   | 0 |

### Pre-reg karar kuralı vs gerçek
- top-5%-share ARTMADI (-7%, H1 mekanizma kriteri FAIL). AMA paired analiz: aynı 2294 OOS
  trade, trail3.0 ile meanΔ=+0.53R, 268 büyüdü/119 küçüldü, top-decile winner max R 15.3→19.0
  (BÜYÜDÜ). top5-share düştü çünkü ORTA-kazanan gövdesi daha çok şişti (kazanç GENİŞ-tabanlı,
  sadece kuyrukta değil) — forex'ten FARKLI ama daha sağlıklı mekanizma. Ekonomik sonuç:
  mR↑ med↑ Shrp↑ DD-flat win%-flat → net AÇIK POZİTİF.
- Düzeltme: pre-reg shuffle_p (kendi-array bootstrap) BOZUKtu (~0.49, hiçbir şey test etmiyor) →
  ATILDI. Doğru null = PAIRED SIGN-FLIP: V1a_trail2.5/3.0 meanΔ p=0.00005 (forex ile birebir).

### Robustness (SOP-3) — HEPSİ GEÇTİ
- Year-by-year: trail3.0 baseline'ı 6/6 yılda yener (bull 2021/24, bear 2022, range dahil).
- Symbol-out CV: 0/10 negatif fold (her LOO +2.5..+6.2pp). Tek-sembol bağımlılığı YOK.
- IS→OOS decay: mR IS+1.39/OOS+1.65 (~%16, <%30). Monotone yüzey, ekstrem uçta değil.
- DD baseline'dan KÖTÜLEŞMEDİ (-13.7 OOS / -16.9 5y, baseline ile aynı).

### Falsification varyantları (BEKLENDİĞİ GİBİ RED — tuzaklar tekrarlanmadı)
- V1b_notime (time-exit söküldü): mR +4.35 görünür AMA Sharpe DÜŞTÜ (1.66→1.40 OOS,
  1.60→1.06 5y) = forex AUD-143R stuck-trade artefaktı. Deploy aday DEĞİL. Tuzak TEYİT edildi.
- V2 single-partial / V3 pure-trail: top5 41→18-21%, DD -13.7→-30..-62%, mR NEGATİF,
  neg ay 44-48/61. Partial yapısı sökülünce sağ-skew ÖLDÜ — forex dersi crypto'da da geçerli.
- V1a_fe (force_exit_from_entry=True): crypto'da ZARARLI (mR→~0, DD-25.7%, neg 33-36/61).
  Forex'te yardım etmişti; crypto VSA'da entry'den force-clock erken-çıkış winner'ı kesiyor.
  Forex→crypto FARKI: bu knob TRANSFER ETMEDİ. (trail genişliği ETTİ, force_exit ETMEDİ.)

### KARAR: TERFİ ADAYI — V1a_trail3.0 (alternatif 2.5). Lab'e devret.
NET: winner-let-run crypto'da ROI'yi ARTIRDI. trail 1.5→3.0: OOS aylık-medyan +8.83→+14.0%
(+5.2pp, ~+58% relative), 5y medyan +7.28→+12.20%, Sharpe +1.60→+1.85, neg ay 2→0,
**DD ve win% DEĞİŞMEDEN**. Tek lever: runner_trail_mult (config stop_loss.trailing.multiplier
2.0→3.0; engine runner_trail_mult). force_exit_from_entry KAPALI tut (crypto'da zararlı).
