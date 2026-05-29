# Hipotez: HYP-2026-05-29-mtf-entry-refinement

**PRE-REGISTRATION — kod yazmadan önce.** Popper: null hypothesis önce yazılır.

## Reproducibility
- git_hash: e7d0a90 (branch audit-hardreview-20260528)
- data_hash(3sym x 4tf OHLC): 90bb22160ab3692c
- seed: 12345
- baseline trades: /tmp/rt_trades.pkl (brooks_failed_breakout 4h, fx.gather)

## İddia (H1)
4H brooks_failed_breakout sinyali yön/bias verir. Sinyal onayından (4H bar t kapanışı =
entry_ts = t+4h) SONRA, girişi alt zaman diliminde (1H/30m/15m) zamanlarsak:
- (V1 Pullback) yön-lehine retrace bekleyip daha iyi fiyattan girersek stop daralır → R artar
- (V2 Onay) alt-TF momentum/BOS onayı beklersek sahte sinyal filtrelenir → win% artar
- (V3 Dar stop) giriş ~aynı ama stop alt-TF yapısında → R artar
→ NET ROI (robust medyan aylık) baseline 4H-open girişinden YÜKSEK, ve bu iyileşme OOS'ta tutar.

## Null hypothesis (H0) — ne olursa çürür
H0: MTF entry refinement, baseline 4H-open girişine kıyasla OOS'ta robust medyan aylık
ROI'yi (ve mean R'yi) İSTATİSTİKSEL OLARAK ANLAMLI artırmaz.
H1 doğruysa şu OLMALI: en az bir varyant/TF kombinasyonunda OOS net mean R ve OOS robust
medyan aylık, baseline'dan yüksek, ve IS→OOS decay < %30 (Sharpe). H0 reddedilemezse
(OOS'ta iyileşme yok / IS-only / whipsaw win%'i yiyor) → MTF refinement REDDEDİLİR.

## Falsifikasyon koşulları (önceden yazıldı, hangi veri beni döndürür)
1. OOS'ta hiçbir varyant baseline OOS mean R'yi geçmiyorsa → RED.
2. IS'te iyileşme var ama OOS'ta kayboluyorsa (IS-OOS decay > %50) → entry-optimization overfit, RED.
3. Dar stop R'yi artırıyor ama win% düşüşü net etkiyi negatif/nötr yapıyorsa → RED.
4. Pullback/onay penceresinde skip oranı çok yüksekse (>%50) ve kalan trade'ler büyük
   sağ-kuyruk kazananları kaçırıyorsa (top5_share baseline'dan düşük) → edge kaynağını
   kesiyor, RED.
5. Shuffle null'ı OOS'ta yenemezse → RED.

## Bağımsız değişkenler
- Varyant: {V1 pullback-entry, V2 subTF-confirm, V3 narrow-stop-only}
- Alt-TF: {1h, 30m, 15m}
- Pullback derinliği: {0.382, 0.5} of signal-bar range (V1)
- Refinement penceresi N: {6, 12} sub-TF barı (pencere içinde tetiklenmezse → SKIP, ve
  ayrıca "fallback=4H-market" varyantı da raporlanır)

## Bağımlı değişkenler (ölçülen)
n_trade (tetik/skip), net mean R, win%, profit factor, robust medyan aylık %, monthly
Sharpe, realized contDD %, top5_share (sağ-kuyruk korundu mu).

## Beklenen effect size + predictive interval (Tetlock kalibrasyon)
- Önsel inanç: entry-refinement OOS'ta GERÇEK ROI artışı verme olasılığı ~%25 (entry
  optimization prime overfit alanı; literatürde dar-stop genelde whipsaw'la yenir).
- Eğer çalışırsa beklenen: V1/V2 1h ile OOS mean R +0.05..+0.15 R artış, win% ±, robust
  medyan +1..+3pp. %70 güvenle: en olası sonuç dar-stop V3'ün R↑'sını whipsaw'ın yemesi
  (net nötr/hafif negatif). Brier-tracked.

## Lookahead protokolü (EN KRİTİK)
- Sinyal entry_ts = 4H bar t+1 open = sinyal-bar t kapanış anı. Refinement SADECE sub-TF
  bar open_ts >= entry_ts kullanır. entry_ts'den ÖNCEKİ hiçbir sub-TF barı kullanılamaz.
- Giriş sub-TF bar OPEN'da (slippage uygulanır).
- Intrabar SL/TP: aynı bar içinde hem SL hem TP varsa KONSERVATİF → önce SL (loss) say.
- Pencere içinde tetik yoksa: SKIP (ana rapor) + 4H-market fallback (ek rapor).
- Pullback/onay seviyesi SADECE entry_ts'de bilinen sinyal-bar OHLC'den türetilir.

## Exit modeli (apples-to-apples izolasyon)
Engine'in multi-target runner-trail'ini sub-TF'de RE-IMPLEMENT ETME (divergence riski).
Bunun yerine HEM baseline HEM varyantlara AYNI basit-ama-tutarlı exit uygula:
  fixed target = baseline trade'in gerçekleşmiş R'sini ÜRETEN aynı çıkış mantığı yerine,
  sabit hedef-R modeli: SL=stop, TP=signal-bar tabanlı initial target-R. Baseline'ı da bu
  modelle yeniden sim et ("baseline-resim") → entry farkı İZOLE edilir. Ayrıca orijinal
  engine-R baseline'ı da referans olarak göster (sanity).
İzolasyon mantığı: V vs baseline-resim KIYASI entry etkisini saf ölçer; engine-R sadece
sanity/context.

## Stop criterion (p-hacking guard)
IS'te baseline-resim'i geçen varyant YOKSA → OOS'a BAKMADAN dur, RED. Param search yok
(her varyant pre-reg grid'i; multiple testing = BH-FDR variant×TF×depth×N kombinasyonları).

## Universe / split
3 çekirdek sembol (EUR/USD, GBP/USD, USD/JPY — sub-TF verisi var). IS=[2020,2024),
OOS=[2024,2026) DONMUŞ. Cost: slippage 1.0bps round-trip (sub-TF girişe de uygulanır),
fee=0, swap haircut (orijinal modelle).

## VERDICT (2026-05-29): RED — H0 NOT rejected
Engine-faithful (round-trip max|Δ|=0.0000). Against same-TF baseline-resim anchor, all entry
variants ΔOOS_mR < 0 and ΔrobMed < 0; v2_confirm neutral but symbol-out CV shows sign-flipping
noise (not edge). Falsification cond #1,#3,#4 triggered. The apparent finer-TF improvement is an
EXIT-granularity artifact (identical entry px, 88/0 win->bigger-win via 4H-ATR trail on sub-TF
bars), NOT entry refinement. MTF entry timing does NOT add OOS ROI. Calibration: pre-reg put ~25%
on real edge + most-likely "dar-stop R↑ eaten by whipsaw" — CONFIRMED (narrow wr 37% vs 49%).
