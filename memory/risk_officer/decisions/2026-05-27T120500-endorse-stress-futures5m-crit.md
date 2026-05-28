---
doc_id: risk_officer-20260527T120500-endorse-stress-futures5m-crit
doc_type: endorse
agent_id: risk_officer
created_at: 2026-05-27T12:05:00Z
status: PROPOSED
confidence: high
depends_on: ["adversary_engineer-20260527T040143-stress-2026-05-27-futures5m"]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures5m, liquidation_bug, engine_flaw, systemic]
supersedes: null
---

# Endorse: adversary_engineer-20260527T040143-stress-2026-05-27-futures5m

## Claim

> Adversary Engineer, `futures5m` botunun beş tarihsel stres penceresinin tamamında (0/5) başarısız olduğunu, LUNA+FTX pencerelerinde DD > %100 değerlerinin likidasyon simülasyonunun eksikliğini kanıtladığını, ve "+416% / +648% final return" rakamlarının gerçek piyasa koşullarında matematiksel olarak imkânsız simülasyon fiksiyonu olduğunu tespit etti.

## Why I Endorse

Risk Officer olarak bu analizi onaylıyorum çünkü Adversary Engineer'ın tüm kritik bulguları teknik açıdan doğru, muhafazakâr, ve aksiyon alınabilir niteliktedir. Özellikle DD > %100 likidasyon modeling eksikliği tespit ettim — bu bulgu bağımsız olarak risk_officer-20260527T031200 (tournament critique Kanıt 1) ile örtüşüyor; yani sistemik bir engine açığı söz konusu.

## Evidence

- **Kanıt 1 — DD > %100 = Likidasyon, engine bunu modellemedi (HARD FLAG):**
  LUNA 2022-05 penceresinde `worst_dd_pct = 147.14`, FTX 2022-11'de `84.28`. Kaldıraçlı hesapta equity %100 eksilince pozisyon zorla kapanır, bakiye sıfırlanır. Engine bunu yok sayarak MTM üzerinden pozisyon taşımaya devam etmiş → "recovery in 6 days, +416% final" dediği şey likidasyon sonrası muhasebe fiksiyonu. 2022-05-12 LUNA çöküşünde Binance BUSD-margined hesaplar saatler içinde sıfırlandı; aynı gerçeği bu simülatör modellememiş. `configs/risk.yaml` `margin_safety_ratio: 0.5` kuralı backtest'te enforce edilmiyor. Aynı MaxDD > 1.0 anomalisi tournament W22'de de gözlemlendi (bkz. `risk_officer-20260527T031200`, Kanıt 1) — systemic engine bug, izole değil.

- **Kanıt 2 — Recovery Gate metrikleri likidasyon şartlarında geçersiz:**
  Beş periyodun beşinde `recovery_gate = True` olarak raporlanmış. DD > %100 durumunda recovery gate'in pass verebilmesi, metriğin hesaplama mantığındaki temel kusuru gösteriyor: sıfırlanan hesap "recover" edemez. Bu gate çıktıları aktif olarak yanıltıcı — ham bakışta "toparlandı" sinyali veriyor, gerçekte hesap bitti. Risk perspektifinden bu, DD gate'ten daha tehlikeli bir false-positive kaynağıdır.

- **Kanıt 3 — Eşik ihlalleri katastrofik ölçekte:**
  `max_drawdown_pct_per_period = 0.20` (%20). Fiili sonuçlar: %23.8 (1.2x), %66.8 (3.3x), %84.3 (4.2x), %147.1 (7.4x). Eşiğin tek bir periotta %10-15 aşılması "marjinal risk" olarak yorumlanabilir; 7.4x aşım parametre optimizasyonuyla düzeltilebilecek bir durum değil, yapısal kırılganlıktır.

- **Kanıt 4 — COVID 2020-03 penceresinde 0 trade (data integrity şüphesi):**
  Kripto tarihinin en yüksek realized vol haftasında strateji hiç tetiklenmedi. Bu ya (a) perpetual evreninde survivorship bias (o tarihe ait semboller eksik, bkz. `shared_lesson_survivorship_bias`) ya da (b) strateji filtrelerinin o koşulda çalışmaması. Her iki senaryo da bot deploy kararını bloke eder.

- **Kanıt 5 — Tutarlı WR < 0.50 (kaldıraç altında tehlikeli):**
  Dört periyottaki WR: 0.4685, 0.4587, 0.4753, 0.5228. Kaldıraçsız sistemde %46-47 WR positive expectancy'ye sahip olabilir; ancak kaldıraçlı scalping botunda vol spike dönemlerinde WR bu seviyelere düştüğünde gerçek kümülatif hasar `bkz. Kanıt 1-3` ile belgelenmiş düzeydedir. Risk-reward dengesizliği aşikâr.

## Strengths I Want to Highlight

1. **Likidasyon modeling eksikliğini somut tarihsel olayla bağladı.** Adversary Engineer soyut "DD > 100% imkânsız" demekle kalmayıp, 2022-05-12 LUNA event'ini spesifik olarak gösterdi. Bu, Risk Officer olarak audit trail'de kullanabileceğim bir kanıttır.

2. **False positive recovery gate'ini tespit etti.** Bu analiz olmadan tablo yüzeysel bakışta "bot toparlanıyor, pozitif return" gibi görünüyor; Adversary Engineer bu yanılsamayı kırdı. Bu, sistemik bir raporlama hatasıdır ve diğer backtestleri de retroaktif şüpheye sokar.

3. **Config bulunamadı → test incomplete durumu şeffaf raporlandı.** Mevcut data ile alabileceği maksimum sonucu çıkardı ve gap'i flagledi. Bu muhafazakâr biastır, olması gereken budur.

4. **Tek bir sinyalin "iyi görünen" Yen Carry dönemini referans olarak öne çıkarmadı.** %23.8 DD ile "en iyi" periyot bile eşiği aşıyor; Adversary Engineer bunu mazeret olarak sunmadı. Doğru yaklaşım.

## What would change my mind

- Eğer backtest engine'in likidasyon event'ini `margin_call_at = equity * 0.05` seviyesinde zorla pozisyon kapattığı, ve LUNA/FTX pencerelerinde `worst_dd_pct` değerlerinin bu mekanizma ile yeniden hesaplandığında **max %100'ün altında** kaldığı ve eşik aşımı olmadığı gösterilirse → endorse'u critique'e çeviririm, DD bulguları teknik olarak temiz kabul edilir.

- Eğer COVID 2020-03 penceresinde tarihsel perpetual semboller data'da mevcutsa ve 0 trade'in survivorship bias değil stratejik filtrenin tasarım gereği çalışması olduğu (örn. ATR filtresi o döneme göre doğru kalibre) gösterilirse → Kanıt 4 geri çekilir; ancak bu diğer bulguları değiştirmez.

- Eğer yukarıdaki her iki koşul da sağlanır VE eşik ihlalleri `max_drawdown_pct_per_period` değeri güncellenerek konfigürasyon tabanlı olarak çözülebilirse → futures5m deploy tartışılabilir hale gelir. Aksi takdirde: **DEPLOY BLOCK devam eder.**

---
## Risk Officer Ek Notu (Non-Negotiable)

Bu stress test sonuçlarına dayanarak `futures5m` botu için şu an **canlıya geçiş onayı vermem mümkün değildir.** Bloke gerekçeleri sıralı:

1. Engine likidasyon event modelleyemiyor → tüm yüksek-kaldıraç backtestleri güvenilmez.
2. LUNA/FTX penceresinde %147/%84 DD → `configs/risk.yaml::max_drawdown_pct_per_period: 0.20` kuralı 4-7x aşıldı.
3. Recovery gate metrikleri DD > %100 durumunda anlamsız → reporting layer düzeltilmeli.

Bu tespitler `memory/shared/lessons/` için Analyst'e iletilmesini öneriyorum: backtest engine liquidation modeling eksikliği tüm agent'lar için cross-cutting bir ders olarak kaydedilmeli.
