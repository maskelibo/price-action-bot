# Hipotez: HYP-2026-05-29-brooks-1h-timeframe-diversification

**PRE-REGISTERED — kod sonuçlarından ÖNCE yazıldı (git=e7d0a90).**

## İddia
4H brooks_failed_breakout 7-bacak risk-parity portföyüne (medyan +11.2%/ay, STD 18.5%,
moSharpe 0.66, MC MaxDD -18% @ eff_r 1.07%) **1H zaman-diliminde 3 sembol bacağı**
(EUR/USD, GBP/USD, USD/JPY) eklemek, **aynı DD'de daha yüksek medyan VEYA aynı medyanda
daha düşük DD** sağlar (frontier yukarı kayar) — ÇÜNKÜ farklı TF'ler kısmen bağımsız
edge taşır (aylık-R korelasyonu < 0.6 ise diversifikasyon değeri var).

## Null hipotez (Popper — ne olursa ÇÜRÜR)
1. **Fee-kurban:** 1H net mR <= 0 (round-trip spread erozyonu 1H'in daha sık trade'ini öldürür).
   → 1H bacak portföye GİREMEZ.
2. **Tekrar-edge:** aynı sembolün 1H ve 4H aylık-R korelasyonu > 0.6 → 1H "yeni bacak" değil,
   aynı edge'in gürültülü kopyası; STD'yi düşürmez.
3. **Frontier kaymaz:** 11-bacak, matched-DD'de 7-bacaktan daha yüksek medyan vermezse
   (Δmed <= 0) → ekleme reddedilir.
4. **OOS çöker:** 1H bacaklar OOS net mR <= 0 veya shuffle p >= 0.05 → overfit, reddedilir.

## Yöntem (frozen, p-hacking yok)
- **Maliyet:** 4H ile BİT-AYNI honest model (forex_4h_research.gather VERBATIM):
  fee=0, slippage_bps=1.0 round-trip spread (engine entry+exit uygular), swap=0.3bps/gece
  (Wed 3x). 1H'te FEE EROZYONU otomatik: daha çok bar → daha çok trade → daha çok spread.
  Swap per-gece olduğu için 1H'i şişirmez; erozyon round-trip spread'ten gelir.
- **TF=1h.** Session 07-16 UTC (bar OPEN ts, lookahead-free), weekend-flat (Fri>=16 UTC),
  cooldown 1.0 gün (24h = 24 bar 1H'te), max_concurrent korunur.
- **atr_min_pct kalibrasyonu (PRE-REG kural, sonuçtan bağımsız):** 1H ATR% medyanı 4H'in
  ~0.5 katı (ölçülen: 4H med ~0.24%, 1H med ~0.12%, oran 0.50). 4H floor=0.0008 dağılımın
  ~p2-3'ünde (negligible alt-kuyruk keser). AYNI göreli seçiciliği korumak için
  **atr_min_pct_1h = 0.0008 * 0.5 = 0.0004**. Bu TEK değer; parametre TARAMASI YOK.
- **IS=[2020,2024) OOS=[2024,2026) frozen.** Seçim full+shuffle ile (OOS peek YOK).
- **Korelasyon:** 3×1H + 3×4H (aynı semboller) + tüm 8×4H ile 6×6 / cross aylık-R matrisi.
  Aynı-sembol cross-TF korelasyon < 0.6 ise "bağımsız bacak"; > 0.6 ise "tekrar".
- **Birleşik portföy:** 8×4H + (kabul edilen) 1H bacaklar = risk-parity replay
  (AUD/NZD bloğu yarım-risk korunur; 1H bacaklar tam-risk ya da bağımsızlık derecesine göre).
- **Robustluk:** WF (2y/6m/3m) pooled, shuffle OOS, symbol-out CV.

## Pre-registered metrikler & eşikler
- 1H standalone: n, IS net mR, OOS net mR, full mR, shuffle p, BH-FDR (3 sembol + bundle).
  KABUL: full mR>0 AND IS mR>0 AND shuffle BH-pass AND OOS mR>0.
- Korelasyon: aynı-sembol cross-TF aylık-R corr. Bağımsız eşik < 0.6.
- 11 vs 7 kıyas: matched MC_medDD'de Δmedyan (pp), ΔmoSharpe, ΔSTD.
- KABUL (frontier yukarı): matched DD'de Δmedyan > +1pp VEYA matched medyanda ΔDD < -2pp,
  AND 11-bacak moSharpe >= 7-bacak moSharpe.

## Beklenti (Tetlock — kalibre tahmin, %60 güven)
- 1H net mR pozitif kalır ama 4H'ten DÜŞÜK (spread erozyonu mR'yi ~%30-50 tıraşlar): %60.
- Cross-TF aylık-R korelasyon 0.3-0.55 bandında (kısmen bağımsız): %55.
- Frontier marjinal yukarı (Δmed +1 ila +3pp matched DD): %45. (Çoğu TF-div marjinaldir.)
- 1H'in tamamen fee'ye kurban gitme olasılığı: %25.

## Stop criteria
- 1H IS net mR < 0 → 1H bacak KILL, param iterate YOK (p-hacking yasak). 4H-only ile kal.
- Cross-TF corr > 0.6 VE frontier kaymıyor → "tekrar edge", reddet.

## AMENDMENT 1 (post-run-1, PRE-REG before run-2 result)
Run-1 finding (root cause, not fee): default brooks fires only n=8/29/27 over 6y on 1H
vs ~350 on 4H. fee_drag negligible (+0.004..0.008 R). Cause: pattern is BAR-COUNTED
(lookback_period=20, max_bars_to_fail=3, SR lookback_bars=120). On 4H these span
~3.3d/12h/20d wall-clock; on 1H they collapse to ~20h/3h/5d — a different (intraday-noise)
structural horizon, so "failed breakout of 20-bar high within 3 bars" almost never resolves.
IS mR is POSITIVE (edge exists per-trade) but n is far too small to carry a portfolio leg.

SOP-4b (never discard positive edge — iterate, NOT param-search): ONE theory-driven
transform = scale bar-windows by 4 so 1H spans the SAME wall-clock structure as 4H:
lookback 20->80, max_bars_to_fail 3->12, SR lookback_bars 120->480, max_age_bars 120->480.
This is registered BEFORE seeing the result. Stop criterion unchanged: IS net mR<0 -> KILL.
KABUL (new leg): n_full >= 100 AND IS_mR>0 AND OOS_mR>0 AND shuffle BH-pass AND
cross-TF corr<0.6 AND frontier Δmed>+1pp at matched DD. If n still < ~80 -> 1H structurally
unusable as a brooks leg; report honestly, no further window search (p-hacking guard).

## VERDICT (post-run, run=brooks_1h_tf_diversification.py, data_hash=56832c1edbe099ef)
**PARTIAL-REJECT (frontier NOT lifted under honest risk-parity). 1H legs are real but WEAKER.**

(a) 1H NET EDGE = POSITIVE, NOT fee-victim. At pre-reg matched floor 0.0004:
    EUR +0.233 / GBP +0.234 / USD/JPY +0.429 net mR; fee_drag negligible (+0.009..0.012 R).
    shuffle p=0.0002 all, BH-pass all, OOS_mR>0 all (OOS shuf_p 0.0002–0.0138). But per-trade
    edge ~HALF of 4H (4H mR +0.43..+0.59, tShrp +0.18..+0.27 vs 1H tShrp +0.12..+0.18).
    NOTE: project ships a 1h manifest atr_min=0.004 (~30x 1H median ATR%) -> n<30/6y,
    unusable; the binding floor was apply_tf_manifest YAML, NOT fees. Honest comparison
    needs matched-selectivity floor (0.0004), which I forced.
(b) INDEPENDENCE = YES. Same-symbol cross-TF corr ~0.00 (+0.033/-0.002/-0.032). Div ratio
    8-leg 0.467 -> 11-leg 0.388 (floor 0.316). Genuinely uncorrelated risk units. Null#2 REJECTED.
(c)/(d) FRONTIER: depends ENTIRELY on 1H risk weight (the trap):
    - full-risk 1H (deploys ~6x annual risk, 2200 vs 360 trades): +5.9pp@DD-15% — ARTIFACT
      (leverage concentration on 1H, not diversification).
    - EQUAL deployed-risk (true risk-parity, scale 0.165): frontier DOWN -4..-6pp.
    - half-scale: ~breakeven@DD-15%, negative elsewhere.
    Null#3 (frontier doesn't lift at matched DD under risk-parity) NOT rejected -> CONFIRMED.
(e) ROBUST: WF gap 4% pos 16/16; OOS shuffle PASS. NOT overfit. But leg-out shows dropping
    EUR/GBP@1h RAISES median (over-weight artifact again).

NET: 1H brooks is a positive-edge, independent, robust signal — but a LOWER-Sharpe one. Under
the principal's low-variance mandate (=equal risk-parity), it dilutes return-per-DD, not lifts
it. Does NOT advance %15-20 target on a risk-honest basis. Clean point stays 4H-only ~%11@-18%.
SOP-4b (don't discard edge): KEEP for FUTURE use as a small-weight diversifier IF combined with
a 1H-native higher-edge pattern; do NOT promote as full-risk leg. No further p-hacking on floor.

## Reproducibility
git=e7d0a90, seed=12345, data=forex_market.duckdb (1H 3sym + 4H 8sym, hash run-time).
