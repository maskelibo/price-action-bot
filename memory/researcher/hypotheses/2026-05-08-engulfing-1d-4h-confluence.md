---
hypothesis_id: engulfing-1d-4h-confluence
date: 2026-05-08
author: researcher_agent
status: in_test
parent_strategy: engulfing_continuation
version: 1.0.0
tags: [multi_timeframe, confluence, brooks_always_in, 4h, 1d, engulfing]
---

# Hipotez: Engulfing 1d + 4h Confluence (Multi-Timeframe)

## Motivasyon

`engulfing_continuation` strateji, yıllık +%10.4 (baseline) ve +%68 (conf-based dynamic leverage, Production A) performans
göstermektedir. Ancak 1d bar-only yaklaşımı, "yanlış engulfing" sinyallerini — yani 1d kapanışında güçlü görünen
ama altta yatan 4h yapısı tersine dönen veya dağınık olan — geçirmeye devam etmektedir.

Brooks'un "Always-In" prensibi, her zaman diliminde piyasanın net bir yön eğilimi olması gerektiğini söyler.
Grimes'ın multi-timeframe alignment prensibi ise üst TF sinyalinin alt TF tarafından teyit edilmesini ister.
Bu iki çerçeve birleştirildiğinde:

> 1d engulfing GÜÇLÜdür — ama 4h de aynı yönde "always-in flip" gösteriyorsa ÇIFTE GÜÇLÜdür.

## Hipotez Özeti

1. 1d engulfing_continuation sinyali tetiklenir (mevcut Production strateji kuralları).
2. 1d sinyal anında, geriye dönük son 4-6 adet 4h barına bakılır.
3. Bu 4h barlarında aynı yönde Brooks "always-in flip" var mı?
   - **YES (4h teyit)**: Confluence boost x1.3 (max 1.0 cap), yüksek conviction — Production A ile birleştiğinde 5x lev.
   - **NO (opposite 4h always-in)**: Sinyal REDDEDİLİR — karşı yön 4h momentum varken 1d engulfing genellikle tuzak.
   - **NEUTRAL (4h belirsiz)**: Sinyal değişmeden geçer (orijinal confidence).

## Teorik Gerekçe

### Brooks Perspektifi
Brooks'un "always-in" konsepti, her bar için net yön gerektir. Eğer 1d bar N'de bullish engulfing görüyorsak
ama 4h'de son 4-6 bar kümülatif olarak bearish kapanıyorsa, bu: (a) 1d engulfing'in "short covering" olduğunu,
(b) alıcıların güçlü ve kararlı olmadığını, (c) "always-in long" olmadığını gösterir.

### Grimes Perspektifi
Grimes, setup quality'nin en büyük faktörlerinden birinin "timeframe alignment" olduğunu vurgular. 4h + 1d
aynı yönde olduğunda win rate ~%58-62 (standalone engulfing ~%50'den). İki bağımsız timeframe'in aynı yönde
yapısal onay vermesi, istatistiksel edge'i artırır çünkü farklı participant grupları aynı sonuca ulaşıyor demektir.

### Operasyonel 4h Always-In Flip Tanımı
Brooks 3-bar trend konfirmasyonuna dayanarak:
- Son 4-6 4h barında: en az 3 bar trend yönünde kapanış (close > close[-1])
- VE son bar, son N bar high'ını geçmiş (long) / low'unu kırmış (short)
Bu, 4h'de "always-in long/short" statüsünü verir.

## Beklenen Davranış

| Durum | 1d Sinyal | 4h Durum | MTF Kararı | Leverage |
|---|---|---|---|---|
| A | Bull engulfing | 4h always-in long | Tam sinyal, boost x1.3 | 5x (prod A) |
| B | Bull engulfing | 4h nötr | Tam sinyal, boost yok | 2-4x (prod A norm) |
| C | Bull engulfing | 4h always-in short | RET | 0x (atla) |
| D | Bear engulfing | 4h always-in short | Tam sinyal, boost x1.3 | 5x |
| E | Bear engulfing | 4h nötr | Tam sinyal, boost yok | normal |
| F | Bear engulfing | 4h always-in long | RET | 0x |

## Risk / Sorunlar

1. **Sample reduction riski**: 4h filtreleme, sinyallerin ~%20-40'ını eleyebilir.
   Bu trade count'u düşürür — daha az örneklemle istatistik daha az güvenilir.

2. **Lookahead riski**: 4h barlar 1d barı kapatmadan önce kapanmaz — dikkat edilmeli.
   1d bar N kapandığında, son tam 4h bar da kapanmış olmalı (UTC timestamp alignment).

3. **Rejim hassasiyeti**: Crypto bull market'te 4h genellikle 1d ile aligned;
   bear market'te veya range'de 4h diverge edebilir. Filter hem bull hem bear için test edilmeli.

4. **Overfitting riski**: MTF filter sadece 3y backtest'te değil, walk-forward'da da test edilmeli.

## Başarı Kriterleri

- Yıllık net return: Production A (%68) üzerinde, ya da benzer return + düşük MaxDD
- MaxDD: Production A'dan düşük veya eşit
- Win rate: baseline engulfing win rate'ine göre artış (veya eşit, daha az trade ile)
- 4h teyit alan sinyallerin win rate'i > 4h teyit almayan sinyallerin win rate'i

## VERDICT Kriteri

- **REPLACE**: Production A'yı (yıllık %68) anlamlı şekilde aşıyor (>%10 fark) VE MaxDD daha az.
- **SUPPLEMENT**: Production A ile birleştirildiğinde (Prod A + 4h filter) daha iyi sonuç — yeni Production variant.
- **REJECT**: Win rate düşüyor, return düşüyor, veya sample çok küçülüyor (sample integrity riski).
