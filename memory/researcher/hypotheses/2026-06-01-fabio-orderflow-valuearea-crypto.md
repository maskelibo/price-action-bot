# Hipotez: HYP-2026-06-01-fabio-orderflow-valuearea-crypto

**Durum:** REJECT (2026-06-01). Null hipotez ÇÜRÜTÜLEMEDİ: 0bps'te real mean_R=+0.024
vs shuffle +0.025, p=0.50 → value-area seviyesi YÖN edge'i taşımıyor. 55bps'te micro-stop
fee erozyonu -3.7R; sl_min=0.030'da bile -0.196R. 0/6 pozitif yıl. Detay: reports + learning.md.
Kalibrasyon (Tetlock): "%25 < 0" demiştim; gerçek < 0 ÇIKTI (kalibre tahmin tuttu).

**Durum (orijinal):** PRE-REGISTERED (kod yazmadan önce)
**git_hash:** af14df4
**Tarih:** 2026-06-01
**Kaynak:** YouTube "Fabio" order-flow scalping transkripti. DÜZELTME: Fabio'nun
piyasası FOREX DEĞİL → NASDAQ (NQ futures) + CRYPTO ("Saturday I do crypto order
flow", "crypto scalping extremely profitable"). NQ verimiz yok; crypto'da GERÇEK
HACİM (data/market.duckdb ohlcv.volume) var → order-flow proxy'leri kurulabilir.

## Iddia (tek cümle, ölçülebilir)
Likit crypto majorlarında (5m), önceki seansın GERÇEK-hacim Volume Profile'ından
hesaplanan Value-Area Low (VAL) yakınında oluşan rejection (alış absorption proxy)
long, Value-Area High (VAH) yakınında oluşan rejection short verir; seviye-ötesi
sıkı stop + hedef POC/karşı-kenar (R:R≈1.5) ile, dürüst maliyet (55bps round-trip)
sonrası **mean_R_after_fees > 0 ve shuffle baseline'ı p<0.05 ile yener**.

## Null hipotez (Popper — ne olursa çürür)
VAL/VAH rejection girişlerinin mean_R'si, aynı entry-zamanlarında YÖN-SHUFFLE
edilmiş (veya rastgele-zaman) baseline'dan istatistiksel olarak farksızdır
(mean_R_after_fees ≤ 0 VEYA shuffle p ≥ 0.05). Bu durumda value-area "seviyesi"
bir edge taşımıyor, sadece volatilite/mean-reversion gürültüsü.

## Bağımsız değişkenler (param uzayı — KABA, curve-fit önleme)
- VA penceresi: önceki 1 takvim-günü (kapanmış), seans-bazlı opsiyon.
- value_area_pct: 0.70 (standart Market Profile %70 VA). Tek değer, sweep YOK.
- price bins: round-number/ATR-ölçekli kova (~50 bin).
- proximity: |close - VAL| < k*ATR, k ∈ {0.25, 0.5} (2 değer).
- rejection: bar VAL altına sarkıp VAL üstünde kapanır (wick reddi).
- stop: VAL - m*ATR (m=0.5), hedef: POC veya VAH (R:R doğal).
- seans: NY / London / Asya (filtre, optimize edilmez — Fabio'nun iddiası test).

## Bağımlı değişkenler (pre-registered metrikler)
mean_R_after_fees, MaxDD (R), monthly ROI proxy, win%, n_trades, calendar-day Sharpe.

## Pre-registered eşikler / kalibrasyon (Tetlock)
- GO adayı: mean_R_after_fees(55bps) > +0.10 R VE shuffle p<0.05 VE
  n_trades ≥ 200 VE walk-forward yıllarının ≥3/5'i pozitif.
- Tahmin (kalibre, %60 güven): mean_R_after_fees(55bps) 0.00–0.10 aralığında
  çıkar (zayıf/marjinal). %25 ihtimal < 0 (red). %15 ihtimal > 0.10 (GO).
  Gerekçe: 5m mean-reversion klasik olarak fee'ye karşı kırılgan; canlı VSA
  botu mean_R≈0.96 ama O trend/breakout, bu reversion — farklı rejim.

## Stop criteria (fail-fast)
mean_R_after_fees(55bps) < 0 VEYA shuffle p≥0.05 → terk, learning.md'ye 3 satır.

## Lookahead protokolü (Feynman — kendini kandırma)
- VA SADECE t-bar'dan ÖNCE kapanmış günün barlarından hesaplanır (t-1'e kadar).
- shift(-1), center=True, future-bar YOK. Entry bar'ın KAPANIŞINDA karar, dolum
  bir sonraki bar open (veya entry close, konservatif).
- Stop/target intrabar dolumu: aynı bar high/low ile çözüm; ambiguity'de
  STOP-ÖNCE (konservatif) kuralı.

## Multiple testing
proximity k (2) × seans (3) × sembol = küçük grid. Raporlanan headline GO/red
kararı için Bonferroni (m = k×seans = 6) uygulanır.

## Delta/CVD feasibility (dürüst şerh)
Stored OHLCV'de taker-buy yok → gerçek delta YOK. Bir doğrulama penceresinde
(son 6-12 ay, 2-3 sembol) Binance aggTrades çekip CVD proxy denenebilir; ağırsa
follow-up. Footprint=tick → kapsam dışı.
