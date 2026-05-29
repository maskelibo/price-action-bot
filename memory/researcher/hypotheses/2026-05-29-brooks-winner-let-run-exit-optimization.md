# Hipotez: HYP-2026-05-29-brooks-winner-let-run-exit-optimization

**PRE-REGISTRATION — kod yazmadan önce.** (Popper: null hypothesis önce yazılır.
Feynman: kendimi kandırmamak için baseline-reproduction zorunlu pre-check.)

## Reproducibility
- git_hash: e7d0a90 (branch audit-hardreview-20260528)
- data_hash(3sym core x4tf + 8fx 4h): c11fe742f9be9099
- seed: 12345
- Engine: real BacktestEngine (src/price_action/backtest/engine.py) — exit knobs are
  CONSTRUCTOR params (runner_trail_mult, trail_activate_stage, tp1_R, tp2_R,
  tp1_close_pct, tp2_close_pct, runner_force_exit_method/bars). NO hand-coded exit.
- Baseline exit = engine defaults: TP1=1R/30%, TP2=1.5R/30%, runner 40% peak-1.5*ATR
  trail (activate after TP2), BE after TP1, time-force-exit 30 bars (sec13.4 artifact guard).

## İddia (H1)
Brooks edge sağ-kuyrukta yoğun (kârın büyük payı top-5% trade). Baseline exit (2R-civarı
çoklu hedef + 1.5*ATR trail + 30-bar time-force-exit) kazananları ERKEN kesiyor olabilir.
Çıkışı GEVŞETİP kazananı daha çok koşturursak (daha geniş/yok TP, daha gevşek trail, daha
geç/iptal time-force-exit, partial+runner ağırlığı), büyük kazananlar BÜYÜR ve net robust
ROI (robust medyan aylık + Sharpe/DD) baseline'dan YÜKSEK olur — ve bu OOS'ta TUTAR.

## Null hypothesis (H0) — ne olursa çürür
H0: Hiçbir gevşetilmiş çıkış varyantı, baseline çıkışa kıyasla OOS'ta robust ROI
(robust medyan aylık VE/VEYA Sharpe-at-equal-DD) ile sağ-kuyruk payını (top5_share)
İSTATİSTİKSEL/ROBUST olarak ANLAMLI artırmaz.
H1 doğruysa şu OLMALI: en az bir varyant OOS'ta hem (a) top5_share baseline'dan yüksek
(kazananlar gerçekten büyüdü) HEM (b) robust medyan aylık VEYA risk-ayarlı getiri (Sharpe
veya median/DD) baseline'dan yüksek, VE (c) IS→OOS decay < %30. H0 reddedilemezse → RED.

## Falsifikasyon koşulları (önceden yazıldı — hangi veri beni döndürür)
1. **BASELINE-REPRODUCTION GATE (Feynman, kod-öncesi):** Engine-default exit ile üretilen
   trade R dağılımı, /tmp/rt_trades.pkl baseline R'siyle bit-yakın eşleşmezse
   (per-sym mean|ΔR| > 0.02) → harness güvenilmez, DÜZELT veya DUR. Variant testine
   geçmeden önce GEÇMELİ.
2. OOS'ta hiçbir varyant top5_share'i artırmıyorsa (kazananlar büyümedi) → H1 ana
   mekanizması yanlış → RED.
3. Bir varyant top5_share'i artırıyor AMA win% düşüşü net mean R'yi/robust medyanı
   negatif/nötr yapıyorsa (trailing daha sık erken stop) → RED (net pozitif değil).
4. IS'te kazanan varyant OOS'ta kayboluyorsa (IS-OOS robust-med decay > %50 veya işaret
   flip) → exit-overfit → RED.
5. "Daha gevşek trail R'yi artırdı" ama bu artış SADECE time-force-exit'i kaldırınca
   geliyor ve realized DD / tutuş süresi patlıyorsa (kuyruk riski) → ret/DD bozulursa RED.
6. **ARTEFAKT GATE:** Sub-TF varyantında trail ATR'si o TF'in kendi bar'larından
   hesaplanmıyorsa (4H-ATR sub-TF'e enjekte) → SONUÇ GEÇERSİZ. Engine'i sub-TF data ile
   ÇALIŞTIRARAK ATR'nin native TF'de hesaplanmasını GARANTİ et (mtf v1 batağı budur).
7. Shuffle/baseline null'ı OOS'ta yenemezse → RED.

## Test edilecek çıkış varyantları (her biri engine constructor param-set; AYRI pre-reg)
Tümü AYNI entry seti (brooks_failed_breakout 4H sinyalleri), DEĞİŞEN tek şey EXIT.
- **B (baseline):** trail_mult=1.5, tp1=1R/.30, tp2=1.5R/.30, activate=2, time-exit 30bar.
- **V1a wide-trail:** trail_mult ∈ {2.0, 2.5, 3.0} (gevşek trail, kazanan koşar). time-exit korunur.
- **V1b no-time-exit + wide-trail:** runner_force_exit_method="atr_only" (30-bar guard KALDIR)
  + trail_mult ∈ {1.5, 2.5}. (kuyruk riski testi; falsif #5 izler).
- **V1c push TP2 + runner ağır:** tp2_R ∈ {2.0, 3.0}, runner pct ↑ (tp1=.30,tp2=.20→runner .50).
- **V2 partial+runner ağır:** tp1=1R/.30, tp2 KAPALI (.0), runner .70 trail (kazananı tek
  partial sonrası serbest koştur). trail_mult ∈ {1.5, 2.5}.
- **V3 no-TP pure-trail:** tp1=.0, tp2=.0, runner 1.0, trail_activate_stage=1 (TP yok, sadece
  trail; saf "let it run"). trail_mult ∈ {1.5, 2.5}.
- **V4 sub-TF trail (DOĞRU ölçekli):** engine'i 15m/30m data ile çalıştır → ATR native sub-TF.
  3 core sym. trail_mult ∈ {1.5, 2.5}. (artefakt yok çünkü engine ATR'yi 15m bar'dan hesaplar.)
- **V5 chandelier eşik taraması:** IS'te trail_mult grid {1.5,2,2.5,3,3.5} + activate {1,2}
  tarayıp IS-best seç → OOS DONMUŞ tek değer test. (param search → BH-FDR düzeltmesi.)

## Bağımsız değişkenler
- Çıkış params: trail_mult, tp1_R, tp2_R, tp1/tp2_close_pct, trail_activate_stage,
  runner_force_exit_method/bars. Timeframe (4h vs 15m/30m, V4).

## Bağımlı değişkenler (her varyant, B ile kıyas, IS+OOS ayrı)
net mean R, win%, profit factor, **top5_share (sağ-kuyruk büyüdü mü)**, robust medyan
aylık %, monthly Sharpe, realized contDD %, ortalama tutuş süresi (bar/gün), median/DD,
final_x.

## Beklenen effect size + predictive interval (Tetlock kalibrasyon)
- Önsel inanç: gevşek-çıkış OOS'ta GERÇEK robust-ROI artışı verme olasılığı ~%30. Exit
  optimization de overfit alanı; ayrıca baseline zaten sec11b/sec13.4'te optimize edilmiş
  (defaultlar tuning ürünü) → marjinal iyileşme zor.
- %70 güvenle en olası sonuç: trail_mult↑ top5_share'i ARTIRIR (mekanik) ama win%↓ +
  ortalama R'deki "geri-verme" (giveback) net etkiyi NÖTR/HAFİF-NEGATİF yapar; no-time-exit
  DD/tutuş süresini şişirir → ret/DD bozulur. V2 (tek-partial+runner) en umutlu aday (~%35).
- Eğer çalışırsa: OOS mean R +0.03..+0.12, top5_share +5..+15pp, robust med +0.5..+2pp.
  Brier-tracked.

## Lookahead / artefakt protokolü (EN KRİTİK)
- Exit kararları engine içinde bar-by-bar, t bar kararı t-close bilgisiyle (engine causal).
- ATR trail: engine `sig.metadata["atr14"]` kullanır = strateji o TF bar'larında hesaplar.
  Sub-TF (V4) çalıştırınca ATR NATIVE 15m/30m → MTF v1 artefaktı YOK (4H-ATR enjekte edilmez).
- Intrabar SL/TP çakışması: engine'in mevcut konservatif kuralı (SL-first) korunur.
- IS=[2020,2024) OOS=[2024,2026) DONMUŞ. V5 param-search SADECE IS; OOS tek-shot.
- Cost: slippage 1.0bps round-trip, fee=0, swap haircut (forex_4h_research modeliyle aynı).

## Stop criterion (p-hacking guard)
1. Baseline-reproduction gate geçmezse OOS'a BAKMA.
2. IS'te B'yi (top5_share VE robust-med birlikte) geçen varyant YOKSA → OOS'a bakmadan dur.
3. Multiple testing: variant×param grid → Benjamini-Hochberg FDR (shuffle-p üzerinden).

## Universe / split
- 4H portföy: 8 FX (netUSD<=3, mc6 — honest_cap ile aynı), risk-parity AUD/NZD.
- Sub-TF (V4): 3 core (EUR/USD, GBP/USD, USD/JPY).
- IS=[2020,2024), OOS=[2024,2026) DONMUŞ.

## VERDICT (2026-05-29): H1 REJECTED for H0 — GENUINE EDGE FOUND (terfi adayı)
Engine-faithful (GATE 1: 7/8 sym bit-identical max|ΔR|=0.0000, AUD mean|ΔR|=0.0058<0.02 PASS).
Wider runner trail (1.5→3.0) WHILE KEEPING the 30-bar time-exit guard genuinely lets winners
run: OOS pooled mR +0.297→+0.798, robMed +4.06→+16.68, Sharpe +0.412→+0.738, top5_share 43→51%,
win% ~UNCHANGED (48→47%), PF 1.61→2.65, realized DD UNCHANGED (-68→-67%). NOT overfit:
(a) smooth MONOTONE response surface trail 1.5→4.0, IS→OOS Sharpe decay only 6%;
(b) gain in EVERY year 2020-2025 and EVERY symbol; (c) symbol-out CV ΔrobMed +10..+19 all 8 legs;
(d) sign-flip permutation null p=0.00005; (e) drop-top-3-trades still +451R (not a few lucky tails);
(f) maxR bounded 19.1R (NOT artifact). force_exit_from_entry=True bounds maxHold 129d→8d and
LIFTS OOS robMed to +19.51 (Sharpe 0.713) → CLEANER candidate.
REJECTED variants: V1b no-time-exit (maxR exploded 143R = sec13.4 stuck-trade artifact, falsif#5);
V1c push-TP2 (top5↑ but mR↓, giveback); V2/V3 single-partial/pure-trail (top5 COLLAPSED 43→20%,
killed the right tail — falsif#3,#4). Calibration: pre-reg put ~30% on real edge; CONFIRMED real
(Brier reward). Recommend CAND = trail_mult 3.0 + force_exit_from_entry=True (entry-anchored time
guard). Hand to Lab for tournament + DSR; this is exit-config change to engine defaults, entry
strategy unchanged.
