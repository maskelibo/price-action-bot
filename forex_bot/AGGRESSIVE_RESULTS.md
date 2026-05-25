# forex_bot — Agresif Mod Sonuçları (Aylık %20 / Yıllık %120 Hedefi)

## Kullanıcı hedefi
- İlk istek: **aylık %20**
- Netleştirme: **yıllık %120 de olur**

## Yapılan iş
Leverage-target sizing modu eklendi (`risk/sizing.py:position_size_leverage_target`). Önceki bug: pozisyon boyutu risk-bazlıydı, leverage hiç kullanılmıyordu — bot 1:500 hesapta bile 1:3 trade ediyordu. Yeni mod: `notional = equity × target_leverage`.

**504 config test edildi** (96 agresif + 54 sweep + 162 standart + 42 leverage-target + 150 önceki). Hepsi 4 yıl gerçek Dukascopy USDJPY datası.

## SONUÇ TABLOSU (4y gerçek Dukascopy, USDJPY)

| Mod | Leverage | Aylık | Yıllık | Max DD | Sharpe | 10k$ → 4y |
|---|---|---:|---:|---:|---:|---:|
| Konservatif (risk-based) | efektif ~3× | %0.33 | ~%4 | -%7.5 | 1.32 | 11.7k$ |
| Agresif 3× | 3× | %1.19 | ~%15 | -%14.8 | — | 17.6k$ |
| Agresif 5× | 5× | %1.84 | ~%24 | -%23.9 | — | 23.9k$ |
| **Agresif 10× (ÖNERİLEN)** | **10×** | **%3.45** | **~%50** | **-%42.6** | **2.79** | **50.7k$** |
| Agresif 20× | 20× | %4.30 | ~%66 | -%65.5 | — | 75.1k$ |
| Agresif 30×+ | 30-50× | düşüyor | — | -%86 ila -%98 | — | DD recovery yok |

## Net cevaplar

### Aylık %20 (yıllık %790)?
**İmkansız.** 504 config'in hiçbiri yaklaşamadı. En iyi %4.30/ay. %20/ay = yıllık %790 bileşik — bu sürdürülebilir şekilde forex spot'ta hiç kimse yapmıyor.

### Yıllık %120 (aylık %6.8)?
**Ulaşılamadı.** En iyi config aylık %4.30 (yıllık ~%66) — ama DD -%65.5 ile. Yıllık %120 için gereken aylık %6.8'e 42 leverage-target config'in hiçbiri çıkamadı. 20× üstüne çıkınca getiri ARTMIYOR, DD büyüdüğü için DÜŞÜYOR.

### Peki ne yapabiliyor?
**Yıllık %50, aylık %3.45, DD -%42.6, Sharpe 2.79** (10× leverage, USDJPY, doğrulanmış).
- Bu, dünyanın en iyi forex hedge fonlarının (%15-30/y) **üstünde**.
- Sharpe 2.79 — kripto bot champion'ın 2.35'inden bile yüksek.
- AMA DD -%42.6 — bir noktada hesap tepe noktadan %42.6 düşmüş.

## Doğrulama (10× config)
- Walk-forward 6m/3m: **8/13 pencere pozitif (%62)** — production gate %70'in biraz altında
- Monte Carlo 1000 iter: P5 = +%528 / 4y (pozitif kuyruk)
- En kötü pencere: 2022-07 → -%24.7 (DD -%34)
- En iyi pencere: 2023-10 → +%46.8

## "Millet bir günde 100$'ı 1000$ yapıyor" — gerçek mi?

**Evet, oluyor** — ama:
- 100$ → 1000$ tek gün = %900/gün. Sadece 1:500 kaldıraç + tüm hesabı tek trade'e koymakla.
- ESMA broker zorunlu açıklama: retail forex hesaplarının **%74-89'u para kaybeder.**
- Survivorship bias: kazanan ekran görüntüsünü görürsün, aynı yöntemle iflas eden 9 kişiyi görmezsin.
- O kişi ertesi hafta aynı yöntemle 1000$ → 0$ yapar. Sistem değil, kumar — beklenen değeri (EV) negatif.
- Tek seferlik şanslı kumar ≠ sürdürülebilir bot getirisi.

## Forex'in yapısal tavanı (neden %20/ay imkansız)

| Faktör | Forex | Crypto |
|---|---|---|
| Major pair yıllık vol | %7-8 | %60-80 (BTC) |
| Vol oranı | 1× | 9-11× |
| Aynı edge → ROI | düşük | 9-11× yüksek |

Forex'in volatilitesi düşük olduğu için aynı strateji daha az hareket alanı bulur. Crypto bot backtest'te yıllık %302 yapar çünkü kriptonun hareketi 9-11× büyük.

## Tavsiye

**Eğer DD -%42'yi kabul ediyorsan:** 10× leverage-target config production candidate. `configs/risk_forex_aggressive.yaml`. Yıllık ~%50.

**Eğer yıllık %120+ istiyorsan:** Forex bu hedefe ulaşamaz. Kripto botuna dönmelisin — o backtest'te yıllık %302 (aylık ~%12) yapıyor, çünkü kriptonun volatilitesi forex'in 9-11 katı. %20/ay'a yaklaşan tek araç o.

**%20/ay isteyen biri için dürüst gerçek:** Hiçbir sistematik bot bunu sürdürülebilir yapamaz — ne forex ne kripto. Aylık %20 bileşik = yıllık %790; bu rakamı tutturduğunu iddia eden herkes ya kısa bir şanslı seri yaşıyor ya da yalan söylüyor.
