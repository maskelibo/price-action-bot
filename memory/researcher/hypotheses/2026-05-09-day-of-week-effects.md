---
hypothesis_id: day_of_week_effects_v1
date: 2026-05-09
author: researcher_agent
status: pre_registered
strategy_class: calendar_filter
strategy_name: engulfing_continuation
tags: [calendar_effects, day_of_week, hour_of_day, crypto, bonferroni, retail_behavior]
---

# Hipotez: Kripto Engulfing Trade'lerinde Gün/Saat Takvim Efektleri

## 1. Iddia (Pre-Registration)

Engulfing Continuation stratejisinin 3 yıllık backtest geçmişindeki ~166 trade üzerinde
yapılacak day-of-week (DOW) ve hour-of-day (HOD) analizinde:

- Bonferroni-corrected alpha (DOW): 0.05/7 = **0.0071**
- Bonferroni-corrected alpha (HOD): 0.05/24 = **0.0021**

Her grup için Fisher exact test veya chi-square testi uygulanacak. En az 1 gün/saat
bu düzeltilmiş eşiğin altında anlamlı çıkarsa hipotez **DEFER** (n çok küçük, daha
fazla veri toplanacak) olarak değerlendirilir. Hiç anlamlı çıkmazsa **REJECT**.

---

## 2. Gerekçe — Yapısal Farklılık

### 2.1 Kripto vs. Geleneksel Piyasalar

- **Forex / Equity**: 24/5 + tatil kısıtlamaları. Calendar efektleri iyi belgelenmiş.
- **Kripto**: 7/24/365 kesintisiz. Teknik olarak hiçbir "kapanış" yok.

Ancak **davranışsal kalıplar** varlığını koruyor:

| Gün | Beklenen Mekanizma | Harris Çerçevesi |
|---|---|---|
| Pazar gece (UTC) | BTC pump folkloru — Asya seansı likidite sweep | Stop-hunting fade setup |
| Pazartesi | Taze sermaye deploymanı, haftalık pozisyon açımı | Value trader + asset allocator flow |
| Cuma akşam | "Weekend risk" satışı — institutionellar hafta sonuna taşımak istemiyor | Hedger + risk reducer flow |
| Cumartesi | Düşük kurumsal katılım, retail dominan | Market maker spread genişlemesi |
| Pazar | En düşük kurumsal hacim — sporadic whale faaliyeti | Shallow depth, stop-hunting prone |

### 2.2 Harris Microstructure Bağlantısı

Harris'in `harris_summary.md` bölüm: *Liquidity Concepts* — "liquidity gate" (Asya seansı
düşük depth) ve *Auction Mechanisms* (hafta sonu: "özel an" yokluğu). Crypto'da:

> "hafta sonu spread anormal biçimde genişler çünkü kurum masaları kapalı; retail flow
> baskın; bu hem stop-hunting için hem de engulfing pattern'ları için özel bağlam sağlar"

### 2.3 Akademik Dayanak

- **Borges (2009):** DOW efektleri equity'de persistence; crypto'ya benzer mekanizma önerilmiş.
- **Aharon & Qadan (2018):** Bitcoin'de belirgin haftalık örüntü; ancak sample küçük.
- **Caporale et al. (2019):** DOW anomalies in crypto; "calendar anomalies may exist but
  are sample-dependent" uyarısı.

**Kritik dürüstlük notu:** Bu akademik çalışmaların tamamı küçük örneklerle çalıştı ve
çoğu OOS'ta tutarlılık gösteremedi.

---

## 3. Metodoloji

### 3.1 Veri Kaynağı

- Engulfing Continuation stratejisi, 10 sembol × 1d × 3 yıl backtestinden çıkan trade'ler.
- Beklenen trade sayısı: ~166 (yaklaşık 22-24 trade/gün = 166/7).
- Her trade için `entry_ts` UTC timestamp → DOW ve HOD çıkarılır.

### 3.2 Day-of-Week Analizi

```
DOW = entry_ts.dayofweek  (0=Pazartesi, 6=Pazar)
Gruplar: 7 grup (her gün)
Metrik: win_rate = n_win / n_total
Test: Fisher exact (iki kuyruk) — her grup vs. kalan tüm günler
Bonferroni alpha: 0.05 / 7 = 0.00714
```

### 3.3 Hour-of-Day Analizi

```
HOD = entry_ts.hour  (0-23 UTC)
Not: 1d barlar genellikle gün başı (00:00 UTC) açılır — HOD ~0 olacak.
     Bu analiz hourly bar'larda daha anlamlı olurdu.
Metrik: win_rate = n_win / n_total
Bonferroni alpha: 0.05 / 24 = 0.00208
```

### 3.4 Win/Loss Tanımı

- Win: `realized_r_multiple > 0`
- Loss: `realized_r_multiple <= 0`

### 3.5 Multiple Testing

Bonferroni: en muhafazakar yaklaşım; yanlış pozitif oranını sıkı kontrol eder.
n = 22-24/gün → power düşük. Cohen's h (effect size) da hesaplanır.

---

## 4. Beklenen Sonuçlar (Pre-Registration)

| Beklenti | Gerekçe |
|---|---|
| Çoğu gün p > 0.0071 | n=22-24 → test gücü <%50 |
| Anlam tespit edilirse "lucky pattern" şüphesi | 7 test × küçük n → Type I error mümkün |
| DOW etkisi varsa: Pazartesi veya Cuma muhtemel | Behavioral microstructure |
| HOD etkisi 1d barlarında zayıf | Barların çoğu 00:00 UTC'de açılıyor |

**Dürüstlük uyarısı:** 166 trade / 7 gün = 23.7 trade/gün. Tek günde %65 win rate
(tipik ortalama ~%50) ile bile p~0.08 (Bonferroni öncesi) çıkar. Bu büyük olasılıkla
anlamlı olmayacak.

---

## 5. Decision Flow

```
IF en az 1 gün/saat p < Bonferroni alpha:
    → DEFER
    Gerekçe: İstatistiksel sinyal var AMA n çok küçük (22-24/gün).
              6+ ay daha veri topla, n'i 50+'ya çıkar, yeniden test et.
    EYLEM: Calendar filter olarak DEĞİL, takip amaçlı izle.

ELSE (hiç anlamlı yok):
    → REJECT
    Gerekçe: Mevcut trade'lerde DOW/HOD etkisi bulunamadı.
              Engulfing continuation stratejisi rejimde sabit kalır.
    EYLEM: Hiçbir değişiklik yapma.
```

**PROMTE filter koşulu:** Bonferroni-corrected p < 0.0071 VE Cohen's h > 0.4 (medium
effect) VE n ≥ 50 (o gün için). Bu koşullar mevcut veriyle karşılanamaz.

---

## 6. Falsification Kriterleri (REJECT Koşulları)

1. Tüm 7 gün için p > 0.0071 (Bonferroni-corrected) — takvim etkisi yok.
2. En yüksek win rate farkı (en iyi gün - ortalama) < %5 — ekonomik anlam yok.
3. HOD analizi: 1d barlarında tüm trade'ler benzer HOD → HOD analizi trivially null.

---

## 7. Strateji Dosyaları

- Analiz scripti: `scripts/day_of_week_analysis.py`
- Test: `tests/test_dayofweek.py`
- Hipotez: `memory/researcher/hypotheses/2026-05-09-day-of-week-effects.md` (bu dosya)

---

## 8. Kritik Tablo (Önceden Belirlenmiş Beklenti)

| Senaryo | Olasılık (pré-analiz tahmini) | Sonuç |
|---|---|---|
| Hiç anlamlı gün yok | %85 | REJECT — strateji değişmez |
| 1-2 gün p < 0.0071 | %12 | DEFER — n yetersiz, izle |
| 3+ gün anlamlı | %3 | DEFER + high "lucky pattern" şüphesi |

---

## 9. Harris Çerçevesiyle Bağlantı (Auction/Calendar Section)

Harris'in `Auction Mechanisms` bölümünden türetilen bağlantı: Equity'de opening/closing
auction "özel anlardır" çünkü kurumsal flow yoğunlaşır. Kripto'da bu anın muadili:

- **Hafta açılışı (Pazartesi UTC):** Kurumsal desk'ler haftalık pozisyon alır.
- **Cuma kapanışı (ABD saati):** Weekend risk kapatılır.
- **Pazar geç gece (UTC):** En düşük kurumsal likidite → stop-hunt ortamı.

Ama Harris aynı zamanda uyarıyor: "Düşük likidite dönemlerinde backtest'te güzel
görünen sinyaller, gerçek piyasada execute edilemez veya 3-5x slippage öder."
Bu, herhangi bir pozitif takvim efektinin "gerçekten trade edilebilir mi?" sorusunu
ciddi şekilde gündeme taşır.

---

## 10. Sonuçlar (2026-05-09 — scripts/day_of_week_analysis.py)

### Veri

- Toplam trade: **166** (10 sembol × 1d × ~3 yıl)
- Toplam kazanan: **73** | Genel win rate: **44.0%**
- Her sembol trade sayıları: BTC:17, ETH:13, SOL:19, BNB:16, XRP:21, DOGE:9, ADA:11, AVAX:23, LINK:22, DOT:15

### Day-of-Week Win Rate Tablosu

| Gün | N | Win | WR% | vs. Ort. | p-value | Cohen's h | Anlamlı? |
|---|---|---|---|---|---|---|---|
| Pazartesi | 25 | 10 | 40.0% | -4.0% | 0.827 | 0.095 | Hayır |
| Salı | 21 | 7 | 33.3% | -10.6% | 0.352 | 0.250 | Hayır |
| Çarşamba | 25 | 14 | 56.0% | +12.0% | 0.198 | 0.284 | Hayır |
| Perşembe | 31 | 13 | 41.9% | -2.0% | 0.843 | 0.051 | Hayır |
| Cuma | 34 | 18 | 52.9% | +9.0% | 0.251 | 0.226 | Hayır |
| Cumartesi | 20 | 6 | 30.0% | -14.0% | 0.232 | 0.329 | Hayır |
| Pazar | 10 | 5 | 50.0% | +6.0% | 0.750 | 0.129 | Hayır |

Bonferroni-corrected alpha = 0.00714 | **Anlamlı gün: 0 / 7**

### Hour-of-Day Tablosu

1D barlarında tüm entry_ts = 00:00 UTC. HOD analizi trivially null — tek bir değer
(00:00) mevcut. HOD filtresi 1D bar üzerinde **uygulanamaz**.

### Gözlemler

- En iyi gün: Çarşamba (%56 WR, p=0.198) — anlamlı değil.
- En kötü gün: Cumartesi (%30 WR, p=0.232) — anlamlı değil.
- Cuma "weekend risk fade" folkloru: %52.9 WR, p=0.251 — anlamlı değil.
- Pazar "Asia pump" folkloru: %50 WR, p=0.750 — anlamlı değil.
- Tüm p-value'lar 0.198-0.843 arasında (Bonferroni alpha: 0.00714).

### Power Analizi

- Gun basına N = ~23.7 trade.
- %10 fark tespit için gerekli N (power=0.8, alpha=0.0071): **~623**.
- Mevcut N, gerekenden **26x küçük** → test gücü < %5.

### Retail Tradeability Değerlendirmesi

Hiçbir gün/saat istatistiksel anlamlılık eşiğini geçemedi. Çarşamba ve Cuma görece
daha yüksek WR gösterse de p-value'ları sıradan gürültü ile tutarlı. 166 trade / 7 gün
= 23.7 trade/gün → bu veri büyüklüğünde %10 fark bile tespit edilemez.

Harris uyarısı (microstructure): Düşük likidite dönemlerine (örn. Pazar) odaklanmak
pratik olarak backtest'te görünenden 3-5x daha kötü slippage ile sonuçlanır.

### VERDICT: **REJECT**

- [x] DOW tablosu: 0 / 7 gün Bonferroni-anlamlı
- [x] HOD tablosu: 1D barlarında trivially null (tek HOD değeri)
- [x] Bonferroni-corrected anlamlı gün/saat: **0**
- [x] VERDICT: **REJECT**
- [x] Retail tradeability: Hayır — ne istatistiksel anlamlılık ne yeterli sample.

**Eylem:** Engulfing continuation stratejisi rejimde sabit kalır. DOW/HOD filtresi
eklenmez. Bu hipotez kanıtlanamadı olarak arşivlenir.

**Arşiv notu:** Sonuç beklenen yöndeydi. Pre-analiz tahmini %85 "REJECT" idi.
Hipotez dürüstçe test edildi ve reddedildi — bu doğru bilimsel süreçtir.
