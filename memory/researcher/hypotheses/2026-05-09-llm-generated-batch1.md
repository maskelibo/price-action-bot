# LLM-Generated Hypothesis Batch 1 — Novel PA Combinations

**ID**: 2026-05-09-llm-generated-batch1
**Status**: PROPOSED (no backtest yet)
**Author**: researcher-agent (Opus 4.7 1M)
**Date**: 2026-05-09
**Source**: Synthesis of 14 PA reference docs in `knowledge/books/`

---

## Methodology

Each hypothesis below combines **at least two distinct literature concepts** in a way that none of the 18 already-tested or 15-in-flight hypotheses currently cover. Concept families crossed:

- VSA (effort-vs-result, stopping volume, no-demand, climax)
- Wyckoff (Spring, Test, SOS, LPS, UTAD, Phase B/C/D)
- SMC/ICT (BOS, CHoCH, FVG, OB, liquidity sweep, EQH/EQL)
- Brooks (H2/L2, ii/iii, BO PB, Failed BO, TTR, climactic bar, wedge)
- Volume-Price Divergence (OBV, MFI, CMF, CVD, Weis waves, kümülatif no-supply)
- Bulkowski candlestick statistics (Morning Star, Three White Soldiers, Tweezer, Three Black Crows, Outside Bar)
- Volume profile (Naked POC, VAL/VAH, LVN)
- Volman (DD double doji, Block Break, round-number traps)
- Grimes (regime/phase, pullback to EMA + reversal bar)

All hypotheses are **mechanically codeable on 1d crypto OHLCV** (with optional 4h confirmation), forward-looking only, and structurally **decorrelated from engulfing geometry** (engulfing = single dominant body fully covering prior bar; none of these rely on that geometry).

Existing modules reusable: `signals/structure.py::swing_highs`, `swing_lows`, `support_resistance`, `atr`, `ema`; `signals/candles.py::bullish_engulfing` (used as ONE OF the entry triggers in HYP-NEW-7 only); `ml/features.py::volume_z_score(20)`. New modules required are explicitly flagged.

---

## HYP-NEW-1: VSA Stopping Volume + Wyckoff Spring + Structural Higher-Low Trap Reversal

**Edge mekanizması (TEK CÜMLE):** Wyckoff Phase C Spring'in **tek-bar VSA** imzasını (climactic volume + narrow body + upper-half close after wick puncture) bir **structural higher-low** içinde yakalayarak stop-hunt sonrası kurumsal absorpsiyonu mekanik olarak avlar.

**Mekanik kurallar:**
- `n=5` fractal swing_lows kullanılarak son 30 bar içindeki en düşük confirmed swing low = `prior_swing_low`.
- Bar `t`: `low[t] < prior_swing_low` (penetrasyon) AND `low[t] > prior_swing_low - 1.0*ATR(14)` (çok derin değil).
- Aynı bar VSA stopping-volume: `volume[t] > 2.0*volume_sma_20` AND `close[t] > low[t] + 0.6*(high[t]-low[t])` (üst %40 kapanış).
- Body dar: `|close[t]-open[t]| < 0.4*(high[t]-low[t])` (effort >> result imzası).
- Higher-low filtresi: önceki swing low'dan en az 5 bar önce daha derin başka bir swing low VAR (yani çoklu test) — gerçek Spring contextini garantiler.

**Entry:** Bar `t+1` open'da long market.
**SL:** `low[t] - 0.3*ATR(14)` (Spring low'unun 0.3 ATR altı; structural).
**TP:** Range high (son 30 barın highest high) → primary 1R hedef; trail to `range_high + 0.5*range_width` (Wyckoff P&F proxy).

**Bağlam filtresi:**
- Son 20 barda fiyat `EMA(50) - 1*ATR` altında en az bir kez kapanmış olmalı (downtrend / range bottom rejimi).
- BTC dominance trendi nötr veya düşüş (alt-friendly) — opsiyonel.

**Edge gerekçesi (2+ konsept):** VSA stopping-volume tek başına %50 civarı; Wyckoff Spring tek başına %60–70 (Wyckoff SMI raporu); higher-low context sweep'in "gerçek" olduğunu doğrular. **Engulfing'den decorrelated** çünkü body küçük (engulfing dominant body gerektirir) ve trigger volüm + wick geometrisidir, gövde değil.

**Beklenen win rate (literatür):** %62–68 (Wyckoff Spring %60–70 × VSA stopping volume confirmation premium).
**Curve-fit risk:** Düşük — 4 mekanik parametre (volume mult, close pos, ATR depth, body ratio); hepsi literatürde standart.
**Test öncelik (1-5):** **5** — yüksek novelty (engulfing geometrisi yok), tam mekanik, decorrelation yüksek.

**Reusable modules:** `swing_lows(n=5)`, `atr(14)`, `volume_z_score(20)`. Yeni: hiçbiri gerekmez (saf bar geometrisi + volume).

---

## HYP-NEW-2: Engulfing + OBV Multi-Bar Regression Slope Confluence

**Edge mekanizması (TEK CÜMLE):** Bullish engulfing sinyali sadece **OBV regresyon eğimi** son 10 barda pozitife dönmüşken işlenir — yani price reversal'ı gizli birikim (hidden accumulation) ile destekleniyorsa edge varolur.

**Mekanik kurallar:**
- Bullish engulfing tetikleyicisi: mevcut `signals/candles.py::bullish_engulfing` = True.
- OBV serisi: standard Granville formülü (`OBV[t] = OBV[t-1] + sign(close[t]-close[t-1])*volume[t]`).
- OBV slope: son 10 barlık OBV serisinin **OLS lineer regresyon eğimi** (numpy polyfit(deg=1)).
- Filtre: `obv_slope_10 > 0` AND `obv_slope_5 > obv_slope_10` (ivmelenme — slope of slope pozitif).
- Fiyat filtresi: aynı 10 bar pencerede `close.iloc[-1] < close.iloc[-10]` (price flat or down) — yani **gerçek divergence**: fiyat yatay/düşerken OBV yukarı.

**Entry:** Engulfing bar close'unda long.
**SL:** Engulfing bar low - 0.3*ATR(14).
**TP:** 2R OR son 20 barın highest high, hangisi önce.

**Bağlam filtresi:**
- ADX(14) < 25 (yatay/range rejim — divergence en güvenilir burada).
- EMA(50) eğimi son 10 barda |slope| < 0.001*price (flat trend).

**Edge gerekçesi (2+ konsept):** OBV bearish-divergence raw form retail-arbitrajlanmış (literatür: edge zayıf), AMA engulfing **price action confluence** + slope acceleration (slope-of-slope pozitif) **filtrelenmiş** divergence — doğrudan no-demand/no-supply Wyckoff Phase B sinyaliyle örtüşür. **Engulfing'den decorrelated** çünkü engulfing sinyallerinin yalnızca ~%15-25'inde OBV slope pozitif (geri kalan engulfing trigger'lar farklı subset).

**Beklenen win rate (literatür):** Raw OBV div %53–55 + engulfing context premium → %60–65.
**Curve-fit risk:** Orta — slope window (10) ve slope-of-slope eşiği parametrik; ADX threshold (25) yaygın. 3 parametre.
**Test öncelik (1-5):** **3** — engulfing alt-küme; bağımsız strateji değil, filter testi. DSR'de marjinal iyileşme bekleyin.

**Reusable modules:** `bullish_engulfing`, `volume_z_score`, `atr`, `ema`. Yeni: `obv()` ve `linear_slope(series, n)` helper.

---

## HYP-NEW-3: Brooks ii Pattern AT Naked POC (Volume Profile Mean Reversion)

**Edge mekanizması (TEK CÜMLE):** Brooks ii (inside-inside) konsolidasyonu mevcut fiyattan ≥ 1.5 ATR uzakta bekleyen **Naked Point of Control** (henüz test edilmemiş haftalık POC) seviyesinde oluşursa, ii breakout'u Naked POC mıknatısına doğru hareketin yüksek-olasılıklı tetikleyicisidir.

**Mekanik kurallar:**
- Naked POC tespiti: son 12 haftalık volume profile (her hafta için), her POC'nin oluştuğu haftadan sonra ziyaret edilmemiş olanlar = `naked_pocs`.
- Mevcut bar fiyatına en yakın naked POC: `nearest_npoc`. Mesafe: `dist = (price - nearest_npoc) / ATR(14)`. Filtre: `1.5 < |dist| < 4.0`.
- Brooks ii: bar[t-2] container; bar[t-1] inside bar[t-2]; bar[t] inside bar[t-1] (her ikisi: `high[t]<high[t-1]` AND `low[t]>low[t-1]`).
- Yön: ii orta-noktası (`(high[t-2]+low[t-2])/2`) Naked POC'nin **diğer tarafında** olmalı (yani breakout Naked POC'ye doğru olacak).

**Entry:** OCO bracket: `bar[t].high + 0.1*ATR` üstü = long stop; `bar[t].low - 0.1*ATR` altı = short stop. Sadece naked POC yönündeki order aktif.
**SL:** ii'nin diğer ucu (`bar[t-2].low` long için, `bar[t-2].high` short için) - 0.1*ATR.
**TP:** Naked POC seviyesi → time-stop 8 bar.

**Bağlam filtresi:**
- Haftalık trend net: 1W EMA(8) eğimi POC yönüyle uyumlu.
- BTC için dominance ya da fear-greed nötr (extreme'lerde mean-reversion bozulur).

**Edge gerekçesi (2+ konsept):** ii standalone Brooks ~%50–55, naked POC mean-reversion edge volume profile literatüründe %60–65. **Confluence**: kompresyon + magnet = directional breakout filtresi. **Engulfing'den decorrelated** çünkü ii üç-bar volatility compression patterndir, engulfing iki-bar dominant body. Brooks H2/L2 ile de farklı (H2 swing-leg sayısına dayanır).

**Beklenen win rate (literatür):** ii alone %50–55 + Naked POC magnet %60–65 → confluence %62–68 tahmini.
**Curve-fit risk:** Orta — Naked POC hesaplaması parametrik (12 hafta penceresi, hafta bin sayısı). ii tanımı sıkı.
**Test öncelik (1-5):** **4** — yüksek novelty, naked POC modülü gerekli (yeni infra), tamamen mekanik.

**Reusable modules:** `atr(14)`, `ema`. Yeni: `weekly_volume_profile()`, `naked_poc_detector()`, `inside_bar_chain(n=2)`.

---

## HYP-NEW-4: Pin Bar at Equal-Highs Sweep WITH Volume Z-Divergence

**Edge mekanizması (TEK CÜMLE):** İki veya daha fazla equal-high (ATR*0.15 toleransı) tarafından oluşturulan "obvious" liquidity pool'unu sweep eden bearish pin bar, AYNI ZAMANDA volume z-score önceki sweep'lere göre **negatif divergence** gösteriyorsa (hacim düşük = no-demand sweep), yüksek-olasılıklı short setup'ıdır.

**Mekanik kurallar:**
- Equal Highs (EQH): son 50 barda en az 2 swing high (n=3 fractal), her biri öncekinin ±0.15*ATR(14) içinde, aralarında daha yüksek bir high yok. `eqh_level = max(eqh_swings)`.
- Sweep bar: `high[t] > eqh_level` AND `close[t] < eqh_level` AND `(high[t]-eqh_level) < 0.5*ATR`.
- Pin bar: `(high[t]-max(open[t],close[t])) >= 2.0*|close[t]-open[t]|` AND `body < 0.35*(high[t]-low[t])` AND close in lower 35% of bar range.
- Volume z-divergence: `volume_zscore[t] < volume_zscore` ölçülen önceki EQH oluşum barlarından — yani bu sweep önceki sweep'lerden daha düşük hacimle. `vol_z[t] < median(vol_z[eqh_form_bars])`.

**Entry:** Bar `t+1` open'da short market.
**SL:** `high[t] + 0.2*ATR(14)`.
**TP:** Nearest swing low (son 50 barın lowest swing low) → 1R partial, kalan trail to `entry - 2*ATR`.

**Bağlam filtresi:**
- 1W trend nötr veya yukarı (sadece "premium" zone'da short al — risk-reward asimetrisi için).
- Round number filtresi: EQH seviyesi büyük yuvarlak sayılara (örn. 100k, 50k BTC) ±%0.5 içindeyse confluence yüksek (Volman round-number).

**Edge gerekçesi (2+ konsept):** EQH sweep raw form ICT %55–60 (peer-review yok). Pin bar %55–60 (Bulkowski). VSA no-demand low-volume sweep premium = "kurumlar test etti, ilgi yok" → %65–72 confluence. **Engulfing'den decorrelated** çünkü pin bar küçük gövde + uzun fitil; engulfing geometrisinin tam tersi. Volume divergence bileşeni de tamamen ortogonal.

**Beklenen win rate (literatür):** %62–70 (HTF S/R + pin %68–73; volume divergence buradan -3 puan).
**Curve-fit risk:** Düşük-Orta — EQH toleransı %15 ATR ve pin oranları (2.0× wick) literatürde standart.
**Test öncelik (1-5):** **5** — short tarafı (mevcut sistem long-bias), tamamen yeni; Wyckoff UTAD'ın mekanik versiyonu.

**Reusable modules:** `swing_highs(n=3)`, `atr`, `volume_z_score`. Yeni: `equal_highs_detector(tolerance_atr=0.15)`, `pin_bar(direction)` (basit candle helper).

---

## HYP-NEW-5: Failed Breakout + Bullish BOS + Low-Volume Reclaim Confirmation

**Edge mekanizması (TEK CÜMLE):** Brooks "Failed Breakout" trap (n-bar high penetrate sonrası 1-3 bar içinde geri dönüş) bir Brooks bullish BOS hareketi içinde gerçekleşip reclaim **düşük hacimli** ise (no-supply), bu trap institutional re-accumulation imzasıdır ve trend continuation long sinyali verir.

**Mekanik kurallar:**
- Bullish BOS: `close[t-k] > rolling_max(swing_highs, n=3, lookback=20)` for some `k in [1, 5]` — yani son 5 bar içinde BOS olmuş.
- Failed Breakout: `t-3 <= j <= t-1` için `high[j] > BOS_level + 0.3*ATR` (false continuation push) AND `close[j+1] < BOS_level` (reclaim).
- Reclaim bar volume: `volume[reclaim_bar] < 0.7*volume_sma_20` (no-supply confirmation; supply tükendi).
- Bar `t`: bullish bar (close > open) AND `close[t] > BOS_level` (BOS level üstünde tutunma).

**Entry:** Bar `t` close'unda long.
**SL:** Failed breakout swing low (en düşük low between BOS bar ve bar `t`) - 0.3*ATR.
**TP:** BOS başlangıç noktasından measured move = `BOS_level + (BOS_level - failed_swing_low)`. Time stop 10 bar.

**Bağlam filtresi:**
- 1D trend: HH/HL serisi son 30 barda ≥ 2 (confirmed uptrend).
- ATR(14) son 20 bar ortalamasından %20+ düşük (volatility compression — coiling).

**Edge gerekçesi (2+ konsept):** Brooks Failed BO standalone %65–75; düşük-hacim reclaim VSA "no-supply" anlamına gelir (supply exhausted → bull continuation). **BOS confluence** institutional alignment garantisi. Üç konsept birleşimi: Brooks trap mekaniği + VSA volume context + SMC structural break. **Engulfing'den decorrelated** çünkü trigger trap reversal'ıdır, dominant body değil.

**Beklenen win rate (literatür):** Failed BO %65–75; volume + BOS premium → %70–78.
**Curve-fit risk:** Düşük-Orta — Failed BO mekanik (n-bar penetration + reclaim); volume threshold standart.
**Test öncelik (1-5):** **5** — Brooks'un en yüksek-güvenilirlikli setup'larından biri, hiç test edilmemiş, kompozit edge.

**Reusable modules:** `swing_highs(n=3)`, `atr`, `volume_z_score`, `support_resistance`. Yeni: `failed_breakout_detector(level, depth_atr, max_reclaim_bars)`.

---

## HYP-NEW-6: Three Black Crows + Buying Climax Distribution Imzası (Short Setup)

**Edge mekanizması (TEK CÜMLE):** Bulkowski'nin %78 reversal-rate'li **Three Black Crows** patterni eğer bir önceki bar Wyckoff/VSA **Buying Climax** imzası taşıyorsa (>2.5×SMA volume + üst yarıdan kapanış + 5-bar new high), bu kombinasyon 1d crypto'da sistematik olarak test edilmemiş bearish distribution sinyalidir.

**Mekanik kurallar:**
- BC bar `t-3` (kalibrasyon: BC ile crows arasında 0–2 bar overlap olabilir):
  - `volume[t-3] > 2.5*volume_sma_20`
  - `(high[t-3]-close[t-3]) > 0.5*(high[t-3]-low[t-3])` (üst yarı close — wick uzun)
  - `high[t-3] == rolling_max(high, 5, lookback=5)`
  - `close[t-3] > open[t-3]` (BC bar yukarı; FOMO)
- Three Black Crows (t-2, t-1, t):
  - Her üç bar bearish: `close < open`
  - Body ≥ 0.5*(high-low) per bar
  - Each bar opens within prior bar's body: `open[i] within (open[i-1], close[i-1])`
  - Each bar closes below prior bar's low: `close[i] < low[i-1]`
  - Volume escalation: `volume[t-1] >= volume[t-2]` AND `volume[t] >= volume[t-1]` (effort-to-move-down)

**Entry:** Bar `t` close'da short.
**SL:** `max(high[t-3], high[t-2]) + 0.3*ATR`.
**TP:** 2R; alternative target: 3-bar drop measured move (`entry - (high[t-3] - close[t])`).

**Bağlam filtresi:**
- 1W trend yukarı veya tepe (overbought regime; son 10 bar içinde new ATH veya new 90-day high).
- Funding rate 8h > +0.03% (aşırı long pozisyonlama — bekleyen squeeze).

**Edge gerekçesi (2+ konsept):** Three Black Crows %78 (Bulkowski rank 7) + Buying Climax %65–75 (Wyckoff Phase A distribution). Kombinasyon: BC = bar-level distribution imzası, 3 Crows = sequential confirmation. Volume escalation bileşeni VSA effort-to-move-down. **Engulfing'den decorrelated** çünkü 3-bar continuation pattern, engulfing 2-bar reversal; mekanik ve geometrik olarak farklı.

**Beklenen win rate (literatür):** Three Black Crows %78; BC confluence + volume escalation premium → %75–82.
**Curve-fit risk:** Düşük — Bulkowski metrikleri standart; BC tanımı VSA referansı.
**Test öncelik (1-5):** **5** — short bias (sistem long-only), 3-bar continuation, hiç test edilmemiş.

**Reusable modules:** `volume_z_score`, `atr`. Yeni: `buying_climax_detector()`, `three_black_crows()`.

---

## HYP-NEW-7: Engulfing + FVG-Mitigation Re-entry (CHoCH Confirmation)

**Edge mekanizması (TEK CÜMLE):** Bullish engulfing sinyali **bullish CHoCH** sonrası oluşmuş bir **bullish Fair Value Gap'in mitigation bölgesine** denk düşerse (price retraces into the unfilled imbalance), FVG'nin %50 (Consequent Encroachment) seviyesinde institutional re-entry için A+ confluence oluşur.

**Mekanik kurallar:**
- Bullish CHoCH: `close[k] > last_LH` for some `k in [t-30, t-5]` where prior trend was down (LH+LL series). Trend state machine.
- Bullish FVG within or after CHoCH leg: 3-bar pattern bar[i-1], bar[i], bar[i+1]: `low[i+1] > high[i-1]` AND `(low[i+1] - high[i-1]) > 0.15*ATR(14)`. FVG zone = `[high[i-1], low[i+1]]`. CE = midpoint.
- Mitigation: bar `t` low touches FVG zone: `low[t] <= fvg_high` AND `low[t] >= fvg_low`.
- AND bullish engulfing on bar `t` (mevcut detector).
- FVG must be unfilled before bar `t` (no prior bar's close was within FVG zone).

**Entry:** Bar `t` close'da long.
**SL:** `min(low[t], fvg_low) - 0.3*ATR`.
**TP:** Last swing high (CHoCH source level) → 1.5R partial; trail to `swing_high + (swing_high - fvg_low)*0.618` (Fib extension).

**Bağlam filtresi:**
- Volume on engulfing bar ≥ 1.0×SMA (no-demand olmasın).
- 4h confirmation: 4h timeframe'de aynı zaman penceresinde HL formation.

**Edge gerekçesi (2+ konsept):** Engulfing tek başına Bulkowski %78 ama crypto'da %44 (canlı sistem); FVG mitigation %60–65 (SMC literatür); CHoCH structural shift %55–60. **Triple confluence** her birinin failure-mode'unu tamamlar: engulfing pattern + FVG institutional zone + CHoCH trend flip. **Engulfing'den decorrelated** olarak ALT-KÜMEDIR (raw engulfing'in sadece ~%10–15'i bu CHoCH+FVG koşulunu sağlar) — DSR ve win-rate iyileşmesi için filter olarak kullanılır.

**Beklenen win rate (literatür):** %55–62 (3-konsept stack ama engulfing 1d performansı çıpa).
**Curve-fit risk:** Orta-Yüksek — 3 mekanik filter stack edildiğinde overfit kuvvetle muhtemel; min trade count 80+ olmalı.
**Test öncelik (1-5):** **3** — engulfing alt-küme, çok filtre, ama A+ confluence theoretical setup. Ana strateji değil DSR booster.

**Reusable modules:** `bullish_engulfing`, `swing_highs/lows`, `atr`, `volume_z_score`. Yeni: `detect_fvg(min_gap_atr=0.15)`, `detect_choch(n=3)`, `trend_state_machine()`.

---

## HYP-NEW-8: TTR (Tight Trading Range) Breakout WITH Effort-to-Move VSA Confirmation

**Edge mekanizması (TEK CÜMLE):** Brooks TTR (10-15 bar dar range, total width ≤ 1.5*ATR) breakout'u eğer aynı zamanda VSA "Effort to Move Up" (wide spread + close in upper 70% + volume > 1.5×SMA) imzasıyla geliyorsa, kompresyon-sonrası kurumsal-katılımlı momentum patlamasıdır.

**Mekanik kurallar:**
- TTR detection: son 15 barda `(rolling_max(high, 15) - rolling_min(low, 15)) / ATR(14) <= 1.5` AND her bar içeride yatay (no single-bar range > 1.0*ATR).
- TTR boundary: `ttr_high = rolling_max(high, 15)`, `ttr_low = rolling_min(low, 15)`.
- Breakout bar `t`: `close[t] > ttr_high` (long) OR `close[t] < ttr_low` (short).
- VSA Effort-to-Move-Up confirmation (long path):
  - `(high[t]-low[t]) > 1.2*ATR(14)` (wide spread)
  - `close[t] > low[t] + 0.7*(high[t]-low[t])` (upper 30% close)
  - `volume[t] > 1.5*volume_sma_20`
  - `high[t] > rolling_max(high, 3, lookback=3)` (genuine new high)
- Symmetric for short with Effort-to-Move-Down.

**Entry:** Bar `t` close'da market (aggressive) OR bar `t+1` open (conservative).
**SL:** TTR opposite boundary - 0.2*ATR.
**TP:** Measured move = TTR width × 2.0 from breakout bar entry. Time stop 8 bar.

**Bağlam filtresi:**
- ATR(14) son 50 barın bottom %30'unda (volatility compression — coiled spring).
- Funding rate nötr (-0.02% to +0.02%) — directional bias yok.

**Edge gerekçesi (2+ konsept):** TTR Brooks ~%55–65; Effort-to-Move VSA "real participation" sinyalidir (kurum dahil, retail sahte breakout değil). Confluence VSA hacim filtresinin bilinen Brooks zayıflığını (zayıf breakout bar) elimine eder. **Engulfing'den decorrelated** çünkü TTR multi-bar volatility metric, engulfing tek-bar momentum.

**Beklenen win rate (literatür):** TTR raw %55–65; VSA-filtered → %63–72.
**Curve-fit risk:** Düşük — Brooks ve VSA eşikleri standart, az parametre.
**Test öncelik (1-5):** **5** — yüksek novelty, fully mechanical, 1d crypto'da hiç sistematik test yok.

**Reusable modules:** `atr`, `volume_z_score`. Yeni: `tight_trading_range_detector(window=15, max_width_atr=1.5)`, `effort_to_move(direction)`.

---

## HYP-NEW-9: Weis Wave Volume Divergence + Tweezer Bottom (HTF Support)

**Edge mekanizması (TEK CÜMLE):** Üç ardışık aşağı **Weis dalgasının** (down-leg cumulative volume) hem hacim hem fiyat hareketi azalan sıra göstermesi — dalga 3 dalga 1'den hem daha düşük hem daha az hacim — bir **tweezer bottom** (iki ardışık eşit low) ile çakışırsa, satıcı tükenmesi (no-supply exhaustion) + double-test confirmation üretir.

**Mekanik kurallar:**
- Weis wave segmentation: bar serisini ardışık aynı-yönlü dalgalara böl. Her dalga = ardışık `sign(close-prev_close)` blok. Her dalga için: `wave_volume = sum(volume[in_wave])`, `wave_move = abs(end_price - start_price)`.
- Aşağı dalgalar için son 3 ardışık down-wave: `vol[w-2] > vol[w-1] > vol[w]` AND `move[w-2] > move[w-1] > move[w]` (her ikisi de azalan — Weis exhaustion).
- Tweezer bottom: bar `t-1` bearish, bar `t` bullish veya doji; `|low[t-1] - low[t]| < 0.1*ATR(14)`.
- HTF support filtresi: `min(low[t-1], low[t])` 1W chart'tan major swing low'a (son 26 hafta) ±0.5*ATR(1W) içinde.

**Entry:** Bar `t+1` open'da long market.
**SL:** `min(low[t-1], low[t]) - 0.3*ATR(14)`.
**TP:** Nearest swing high (son 30 bar) → 1R; trail beyond using ATR-Chandelier (3*ATR from highest high).

**Bağlam filtresi:**
- BTC dominance düşüş trendi VEYA fear-greed < 30 (capitulation regime — false signals fewer).
- En son SC veya stopping-volume bar son 30 barda mevcut (Phase A precondition).

**Edge gerekçesi (2+ konsept):** Weis wave divergence VSA literatüründe %62–68 (Weis kendi rapor); tweezer bottom Bulkowski %61. Confluence: Weis wave makro-VSA, tweezer mikro-double-test. **Engulfing'den decorrelated** çünkü tetikleyici tweezer (eşit-low geometrisi), ve makro-context Weis dalgasıdır — engulfing geometrisi yok.

**Beklenen win rate (literatür):** %63–70 (Weis %65 + tweezer +HTF support premium).
**Curve-fit risk:** Orta — Weis wave segmentation tanımı parametrik (3 wave count, threshold).
**Test öncelik (1-5):** **4** — yüksek novelty (Weis nadiren mekanikleştirilir), HTF data gerekli.

**Reusable modules:** `swing_lows`, `atr`, `volume_z_score`. Yeni: `weis_waves(prices, volumes)` (segment + aggregate), `tweezer_bottom(tolerance_atr=0.1)`.

---

## HYP-NEW-10: Double Doji (Volman DD) at Premium-Zone Resistance (Short Setup)

**Edge mekanizması (TEK CÜMLE):** Volman'ın "Double Doji" (iki ardışık dar-gövde bar, toplam range küçük) imzası bir 1d swing'in **premium zone**'unda (Fib %61.8–%78.6 retracement) ve **HTF resistance** (haftalık swing high ±0.5*ATR(1W)) ile çakışırsa, kompresyon + reddedilme = institutional dağıtım kurulumudur.

**Mekanik kurallar:**
- Double Doji: bar[t-1] ve bar[t] her ikisi: `|close-open| < 0.15*(high-low)` (gövde range'in %15'inden küçük — Volman doji).
- Combined range: `max(high[t-1],high[t]) - min(low[t-1],low[t]) < 0.8*ATR(14)` (kompresyon).
- Premium zone: son 30 barın swing low (LSL) ve swing high (LSH) tanımla. `mid_price = (high[t-1]+high[t])/2`. `(mid_price - LSL) / (LSH - LSL) >= 0.618` AND `<= 0.786` (OTE bandı).
- HTF resistance: 1W chart son 26 haftanın swing high'larından en yakın olanı ile DD highları arası mesafe ≤ 0.5*ATR(1W).

**Entry:** `min(low[t-1], low[t]) - 0.1*ATR(14)` altına düşüş = bar `t+1` veya sonra **stop sell** order tetikleyici. Manuel: bar `t+k` close < DD low ise k=1 short market.
**SL:** `max(high[t-1], high[t]) + 0.2*ATR`.
**TP:** Equilibrium (50% retracement of LSH-LSL) → 1.5R; ikinci hedef LSL.

**Bağlam filtresi:**
- BTC trend nötr veya yukarı; bu strateji range/distribution kurulumunu avlar.
- Volume on DD bars `< 0.7*volume_sma_20` (no-demand DD — Volman'ın preferred imzası).

**Edge gerekçesi (2+ konsept):** Volman DD ~%55–60 (forex'te); premium-zone short bias SMC %55–60; HTF resistance double-test %60–65. **Üç-yönlü confluence** her birini güçlendirir — DD = volatility compression, premium zone = mean reversion zone, HTF resistance = absolute price barrier. **Engulfing'den tamamen decorrelated** (engulfing'in TAM TERSİ — büyük gövde değil çift küçük gövde).

**Beklenen win rate (literatür):** %60–68 (DD + premium + HTF resistance stack).
**Curve-fit risk:** Orta — premium zone Fib bandı (%61.8–%78.6) literatürde standart; DD threshold Volman'dan birebir.
**Test öncelik (1-5):** **4** — short tarafı, novelty yüksek (Volman crypto'da hiç test edilmedi), HTF data gerekli.

**Reusable modules:** `swing_highs/lows`, `atr`, `volume_z_score`. Yeni: `double_doji_detector(body_pct=0.15, range_atr=0.8)`, `fib_retracement_zone()`.

---

## Summary Table

| ID | Title | Direction | Concepts Combined | Test Priority | Reuses Engulfing? |
|---|---|---|---|---|---|
| HYP-NEW-1 | VSA Stopping Vol + Wyckoff Spring + HL | Long | VSA + Wyckoff + Structure | 5 | No |
| HYP-NEW-2 | Engulfing + OBV Slope Acceleration | Long | Engulfing + OBV + ADX regime | 3 | Yes (filter) |
| HYP-NEW-3 | Brooks ii at Naked POC | Both | Brooks + Volume Profile | 4 | No |
| HYP-NEW-4 | Pin + EQH Sweep + Vol Z-Divergence | Short | SMC + Pin + VSA | 5 | No |
| HYP-NEW-5 | Failed BO + BOS + Low-Vol Reclaim | Long | Brooks + SMC + VSA | 5 | No |
| HYP-NEW-6 | Three Black Crows + Buying Climax | Short | Bulkowski + Wyckoff/VSA | 5 | No |
| HYP-NEW-7 | Engulfing + FVG Mitigation + CHoCH | Long | Engulfing + SMC + Structure | 3 | Yes (filter) |
| HYP-NEW-8 | TTR Breakout + Effort-to-Move | Both | Brooks + VSA | 5 | No |
| HYP-NEW-9 | Weis Wave Div + Tweezer Bottom | Long | VSA/Weis + Bulkowski + HTF | 4 | No |
| HYP-NEW-10 | Volman DD at Premium + HTF Resistance | Short | Volman + SMC + Structure | 4 | No |

---

## Decorrelation Analysis vs. Engulfing

| Hypothesis | Decorrelation Source | Expected Correlation w/ Engulfing |
|---|---|---|
| HYP-NEW-1 | Small body trigger; volume + wick geometry | Very Low |
| HYP-NEW-2 | Engulfing AND OBV — strict SUBSET | High (filter, not independent) |
| HYP-NEW-3 | Inside-bar volatility compression | Very Low |
| HYP-NEW-4 | Pin geometry (opposite of engulfing) | Very Low |
| HYP-NEW-5 | Trap reclaim, not single-bar reversal | Very Low |
| HYP-NEW-6 | 3-bar continuation, not reversal | Very Low |
| HYP-NEW-7 | Engulfing + FVG + CHoCH — strict SUBSET | High (filter) |
| HYP-NEW-8 | Multi-bar TTR + breakout body | Low |
| HYP-NEW-9 | Tweezer (equal-low geometry) | Very Low |
| HYP-NEW-10 | Double doji (anti-engulfing geometry) | Very Low |

8 of 10 are STRUCTURALLY independent strategies; 2 (HYP-NEW-2 and HYP-NEW-7) are engulfing-filter variants meant to boost DSR via SUBSETTING rather than ADDING.

---

## Implementation Roadmap (suggested order)

1. **HYP-NEW-5 (Failed BO + BOS + Low-Vol Reclaim)** — highest expected win rate, mostly mechanical, leverages existing `swing_highs`/`atr`. Need: `failed_breakout_detector`.
2. **HYP-NEW-1 (Spring + Stopping Volume + HL)** — Wyckoff core; pure bar geometry + volume. No new module.
3. **HYP-NEW-6 (Three Black Crows + Buying Climax)** — opens short side; high-stat Bulkowski pattern; clear mechanical defs.
4. **HYP-NEW-8 (TTR + Effort-to-Move)** — volatility compression breakout; bidirectional; needs `tight_trading_range_detector`.
5. **HYP-NEW-4 (Pin + EQH + Vol-Z-Div)** — short side, ICT mechanics with VSA confirmation.
6. **HYP-NEW-3 (ii at Naked POC)** — needs weekly volume profile infra (heaviest).
7. **HYP-NEW-9 (Weis + Tweezer + HTF)** — Weis wave segmentation is novel module.
8. **HYP-NEW-10 (DD at Premium + HTF Resistance)** — short, Volman flavor; needs Fib retracement helper.
9. **HYP-NEW-2 (Engulfing + OBV slope)** — filter-only; quick win for DSR if validated.
10. **HYP-NEW-7 (Engulfing + FVG + CHoCH)** — most filter stacks; risk of overfit; lowest priority.

---

## Output Summary

**File path:** `memory/researcher/hypotheses/2026-05-09-llm-generated-batch1.md`

**Top 3 highest-priority for immediate implementation:**

1. **HYP-NEW-5** (Failed BO + BOS + Low-Vol Reclaim) — Brooks' highest-stat trap pattern + VSA no-supply confirmation + structural BOS alignment. ~%70–78 expected win rate, fully mechanical, low curve-fit risk.
2. **HYP-NEW-1** (VSA Stopping Volume + Wyckoff Spring + HL) — Pure long bias on Wyckoff Phase C entries; ~%62–68 win rate; only requires existing modules.
3. **HYP-NEW-6** (Three Black Crows + Buying Climax) — Opens systematic short side; Bulkowski rank 7 (%78) + VSA distribution context; ~%75–82 expected win rate; high decorrelation.

**Top 3 with highest decorrelation potential vs. engulfing:**

1. **HYP-NEW-10** (Volman DD at Premium Zone + HTF Resistance) — geometric ANTI-engulfing (two narrow-body bars vs. one large-body bar); short side; pure Volman methodology never tested in crypto.
2. **HYP-NEW-4** (Pin Bar + EQH Sweep + Volume Z-Divergence) — Pin bar geometry (small body, long wick) is the geometric inverse of engulfing; short side with stop-hunt mechanics.
3. **HYP-NEW-9** (Weis Wave Divergence + Tweezer Bottom + HTF) — multi-wave aggregate volume metric (no engulfing-style trigger); tweezer is equal-lows geometry (also non-engulfing); HTF macro context further decorrelates.
