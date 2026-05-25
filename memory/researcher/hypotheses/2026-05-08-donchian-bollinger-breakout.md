---
type: hypothesis
hypothesis_id: H-005
status: pre-registered
date: 2026-05-08
researcher: researcher_agent
related_strategy: donchian_breakout
decorrelation_target: engulfing_continuation
doc_type: hypothesis
agent_id: researcher
---

# Hipotez H-005: Donchian Channel Breakout + Bollinger Squeeze Volatility Expansion

## Iddia (pre-registered)

> 1D timeframe'de, **55-bar Donchian kanalının üst bantını kıran** ve bu kırılım öncesinde
> son 5 bar içinde **Bollinger Squeeze** (BB içinde KC) yaşanmış olan sembollerde,
> Kaufman ER >= 0.30 filtresi eşliğinde, N+1 bar açılışında long alım;
> SL olarak 20-bar Donchian düşüğü, TP olarak 3R veya trailing Donchian20-low exit ile:
>
> - Annualized net return > %40 (fee+slip dahil)
> - Sharpe > 0.8
> - MaxDD < %45
> - Profit factor > 1.3
> - **engulfing_continuation ile rolling 60-day sinyal korelasyonu < 0.35**

(Bearish simetri: 55-bar Donchian alt bandı kırılımı + squeeze → short.)

## Gerekçe (literatür)

### Kaufman — Trading Systems and Methods

- **Donchian Channel Breakout** (Setup 1, s. 97): "N-bar high/low kırılımı. Turtle System 1 default.
  Edge: Asimetrik R-multiple; %35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R."
- **Bollinger Squeeze** (Setup 9, s. 187): "BB genişliği N-bar minimum + Keltner band içinde — sıkışma.
  Giriş: Squeeze release, Keltner dışına çıktığında. Edge: Asimetrik payoff; küçük başlangıç riski,
  büyük expansion potansiyeli."
- **Efficiency Ratio Filter** (Setup 7, s. 166): "ER > 0.30 ise trend-following sistemi aktif;
  ER < 0.30 ise mean-reversion sistemi aktif." Bizim yapımızda ER < 0.30 = sinyal iptal.
- **Trend-following imzası**: Win rate %30-40, Average win/loss R 2.5-4.0, Sharpe 0.5-1.2,
  MaxDD %20-40. Hedefler bu aralıkla uyumlu.
- **Turtle 55/20 sistemi**: Entry on 55-bar high, exit on 20-bar low. Bu kombinasyon onlarca yıllık
  literatürle doğrulanmış; Kaufman "complexity must be earned" ilkesine göre baseline olmalı.

### Chan — Algorithmic Trading

- **Volatility Breakout** (Setup 7, s. 128): "Realized volatility uzun compression sonrası genişlediğinde
  momentum yönünde giriş. ATR(20) son 60 günün en düşük %10 percentile'ında ise compression;
  ATR ani sıçrama ise expansion sinyali."
- **VIX Regime analoji**: "Düşük vol → momentum çalışır (sakin, trending piyasa)." Bollinger Squeeze
  düşük vol rejimini tespit eder; kırılım bu rejim geçişini confirm eder.
- **Momentum imzası**: "Time-series momentum (futures): Sharpe 0.7-1.0 (tek varlık), 1.2-1.5
  (diversified portfolio across asset classes)." Donchian + Squeeze kombinasyonu momentum'a yakın
  davranır; aggregate portfolio Sharpe > 0.8 hedefi gerçekçidir.

### Turtle Trading System (Dennis & Eckhardt, 1983)

- System 2: 55-bar breakout entry, 20-bar opposite channel exit. Tarihsel Sharpe ~0.5-0.8
  (kendi kategorisinde kanıtlı). Squeeze filtresi bunu iyileştirmeyi hedefler: whipsaw'ı azaltır,
  sadece volatility expansion öncesi kırılımları yakalar.

## Decorrelation Hipotezi

**Engulfing_continuation** ile decorrelation beklentisi yüksektir çünkü:

1. **Zamanlama farklı**: Engulfing, fiyat 20-EMA'ya pullback yaptıktan sonra reversal bar arar
   (erken dönüş noktası). Donchian breakout ise N-bar high üzerinde kırılım ister
   (geç ama confirmed trend giriş). Aynı trend hareketi için farklı giriş barlarını tetikler.

2. **Yapı farklı**: Engulfing = candlestick pattern (2-bar body relationship).
   Donchian = price channel (55-bar rolling high). İki detektör piyasanın farklı özelliklerini ölçer.

3. **Volatility koşulu farklı**: Engulfing ATR filter kullanır ama squeeze aramaz. Donchian ise
   özellikle düşük-volatilite→yüksek-volatilite geçişini (Bollinger Squeeze release) bekler.

4. **Trade duration farklı**: Engulfing 2R hedef (kısa), Donchian trailing exit (uzun).

Bu farklılıklar sinyallerin kronolojik çakışmasını minimize eder. Beklenti: rolling 60-day sinyal
korelasyonu < 0.35, portfolyo Sharpe katkısı pozitif.

## Test Edilebilir Kurallar (Kesin Kural Seti)

### Uzun Sinyal (Long)

1. Hesapla: `donchian55_high = rolling 55-bar high.shift(1)` (bugünkü bar hariç, N-1 bar)
2. Hesapla: `squeeze_active = BB(20,2) içinde KC(20,1.5×ATR)` — her bar için flag
3. Koşul A: `close > donchian55_high` (bugün kırılım)
4. Koşul B: `squeeze_active.rolling(5).max() == True` (son 5 barda squeeze var mıydı)
5. Koşul C: `kaufman_er(14) >= 0.30` (güçlü trend rejimi)
6. Giriş: Bir sonraki bar açılışı
7. Stop-Loss: `donchian20_low = rolling 20-bar low.shift(1)`
8. TP: 3R (primary) VEYA trailing donchian20_low (Turtle exit, yani fiyat 20-bar low'a değerse kapat)

### Kısa Sinyal (Short) — Simetrik

1. `donchian55_low = rolling 55-bar low.shift(1)`
2. Koşul A: `close < donchian55_low`
3. Koşul B: squeeze_active son 5 barda
4. Koşul C: `kaufman_er(14) >= 0.30`
5. Stop-Loss: `donchian20_high = rolling 20-bar high.shift(1)`
6. TP: 3R veya trailing donchian20_high

## Gates (Pre-defined)

| Metrik | Eşik (PASS) | Neden? |
|---|---|---|
| Annualized net return | > %40 | Kaufman trend-following beklentisi |
| Sharpe | > 0.8 | Chan volatility breakout aralığı (0.5-1.0) üst yarısı |
| MaxDD | < %45 | Trend-following inherent DD + crypto premium |
| Profit Factor | > 1.3 | Kaufman "PF > 1.5 acceptable" — gevşetildi çünkü crypto whipsaw |
| Sinyal korel. (vs engulfing) | < 0.35 | Decorrelation için gerekli |
| Win rate | > %25 | Trend-following expected %30-40 — minimum bound |

## Failure Modes (Pre-defined)

1. **Whipsaw bombardımanı**: Donchian klasik zayıflık. Squeeze filter bu riski azaltmalı.
   Eğer sinyal sayısı > 200 (3y, 10 sembol) ve win rate < %25 → REJECT.

2. **Squeeze fake-out**: BB Keltner dışına çıkar sonra geri döner. 5-bar squeeze window
   ve ER >= 0.30 filtresi bunu kısmen önler.

3. **Yüksek korelasyon**: Eğer her iki strateji de aynı trendi yakalarsa, portfolyo Sharpe
   artışı minimal olur. Korelasyon > 0.5 → SUPPLEMENT değil REJECT.

4. **Crypto bear market performansı**: 2022 gibi uzun down-trend dönemlerinde short
   Donchian gereksiz sinyaller üretir. ER filtresi bu korumayı sağlamalı.

## Onay Mekanizması

- OOS performans / IS performans >= 0.50 (Chan kriteri)
- Tüm 10 sembolün en az 7'si pozitif net P&L
- Aggregate Sharpe > 0.8 (portfolio seviyesi)
- Engulfing ile sinyal korelasyonu < 0.35

**PROMOTE** koşulu: Tüm gates PASS + korelasyon < 0.35
**SUPPLEMENT** koşulu: Return gate PASS + korelasyon < 0.35 (DD veya Sharpe marginal fail)
**REJECT** koşulu: Return gate FAIL veya korelasyon > 0.50

## Veri / Evren

- Semboller: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT, DOGE/USDT,
  ADA/USDT, AVAX/USDT, LINK/USDT, DOT/USDT
- Timeframe: 1D
- Süre: 3 yıl (~1095 bar)
- Başlangıç kapital: 10.000 USDT / sembol (standalone)
- Komisyon: taker 0.075%, maker -0.010%
- Slippage: 5 bps
- Warmup: 250 bar (55-bar Donchian + 200-bar EMA için yeterli)
