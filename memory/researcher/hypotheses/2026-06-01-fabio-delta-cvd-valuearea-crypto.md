# Hipotez: HYP-2026-06-01-fabio-delta-cvd-valuearea-crypto

**Pre-registered (kod öncesi).** Önceki tur (HYP-2026-06-01-fabio-orderflow-valuearea-crypto)
value-area'yı TEK BAŞINA test etti → RED: 0bps'te bile gerçek yön ≈ shuffle (p=0.50), yani
seviye yön bilgisi taşımıyor. Bu tur eksik katmanı ekliyoruz: **ORDER FLOW onayı (bar-bazlı
signed delta / CVD)** — Fabio'nun "look at the delta of the buyers" dediği şey.

## İddia (falsifiable)
"BTC/ETH/SOL 5m+15m, son ~12 ay. Value-area (VAH/VAL/POC) rejection setup'ına, Binance
taker-buy klines'tan türetilmiş **bar-bazlı signed delta + CVD onayı** eklenince — VAL'da
LONG yalnız delta/CVD pozitife dönüyorsa (buyer absorption), VAH'da SHORT yalnız delta/CVD
negatife dönüyorsa — bu kombinasyon (b), value-area TEK BAŞINA (a) baseline'ının üstüne
istatistiksel olarak anlamlı (shuffle p<0.05) ek mean_R_after_fees edge'i KATAR."

## Null hipotez (Popper — bunu çürütemezsem RED)
"Delta onayı, value-area baseline'ının üstüne edge KATMAZ: (b) varyantının mean_R_after_fees'i
(a) ile istatistiksel olarak ayırt edilemez VE/VEYA (b) kendi shuffle baseline'ını geçemez
(p>=0.05). Yani Fabio'nun edge'i bar-bazlı delta'da DEĞİL, ulaşamadığımız tick/footprint
seviyesindedir."

## Değişkenler
- **Dependent:** mean_R_after_fees (55/100bps), win%, calendar-day Sharpe, shuffle-p, n.
- **Independent:** delta-onay eşiği (CVD yön değişimi, delta-momentum işareti), value-area
  prox_k (0.25/0.5), absorption proxy (seviyede yüksek hacim + delta flip).
- **Ablation (asıl test):** (a) value-area tek / (b) value-area + delta onayı / (c) sadece
  delta-CVD momentum (value-area yok).

## Lookahead-güvenlik tasarımı (önceden taahhüt)
- Delta bar t için taker-buy(t) − (vol(t)−taker-buy(t)); bu bar t KAPANDIĞINDA bilinir.
- Karar bar t kapanışında, **t-1 bar delta'sı ve t-1'e kadar CVD** ile (giriş t+1 open).
  Onay sinyalinde t bar'ın delta'sını KULLANMA → t-1'e kadar olan delta/CVD.
- Value-area yalnız önceki kapanmış gün (t-1 günü) barlarından.
- shift(-1)/center=True YOK. Intrabar çakışmada STOP önce.
- En sert sızıntı testi: shuffle (yön rastgele) onayı baseline'ı geçememeli.

## Beklenen sonuç + kalibrasyon (Tetlock — predictive interval)
- P(delta onayı (a) üstüne anlamlı edge katar, shuffle p<0.05) = **%20**.
  Gerekçe: önceki tur baseline'ın 0bps yön-edge'i tam sıfırdı (p=0.50). Delta bir sinyale
  yön katabilir AMA bar-bazlı delta klasik "delta = fiyat hareketinin kendisi" tautolojisine
  yakındır (delta pozitif → bar yeşil); gerçek absorption tick/footprint ister. Yine de
  VAL'da satış emilimi (fiyat düşmez ama delta negatif kalır → sonra pozitife döner) bar
  düzeyinde yakalanabilir, bu yüzden sıfır değil %20.
- P(0bps'te marjinal pozitif ama fee öldürür) = %45.
- P(net RED, delta hiç katmaz / shuffle geçilmez) = %35.
- Effect size beklentisi: anlamlıysa bile mean_R_after_fees(55bps) muhtemelen <+0.05R
  (micro-stop fee erozyonu önceki turda -3.7R'ydi; stop floor gerekecek).

## Stop criteria
- (b) varyantı 0bps'te bile shuffle'ı geçemezse (p>=0.05) → delta katmanı ÖLÜ, iterasyon yok.
- (b) − (a) mean_R farkı pozitif ama shuffle-p>=0.05 → curve-fit gürültüsü, RED.

## Multiple-testing notu
12 ay = küçük örneklem. Test ettiğim varyant sayısı: 3 ablation × 2 TF × birkaç eşik.
~12-15 hipotez testi. Bonferroni-vari: tek bir varyantın "kazandı" demesi için ham p<0.004
(0.05/12) ararım, yoksa "marjinal/belirsiz" derim.

## Veri
Binance fapi klines (fapiPublicGetKlines), index 9 = taker buy base asset volume, index 5 =
total base volume. BTC/ETH/SOL, 5m+15m, son ~365 gün. aggTrades'e DÜŞMÜYORUM (bar-bazlı
delta yeterli proxy; tick footprint kapsam dışı, şerh düşülecek).

## Reproducibility
git=<commit>, script=scripts/research/fabio_delta_cvd_valuearea_crypto.py, SEED=7,
taker-buy cache=data/_fabio_delta_klines/<sym>_<tf>.parquet (read-only sonrası).
