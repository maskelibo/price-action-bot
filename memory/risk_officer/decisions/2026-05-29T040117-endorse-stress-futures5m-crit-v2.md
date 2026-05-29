---
doc_id: risk_officer-20260529T040117-endorse-stress-futures5m-crit-v2
doc_type: endorse
agent_id: risk_officer
created_at: 2026-05-29T04:01:17Z
status: PROPOSED
confidence: high
depends_on: ["adversary_engineer-20260529T040117-stress-2026-05-29-futures5m"]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures5m, liquidation, crit, sizing_bug, v2]
supersedes: null
---

# Endorse: adversary_engineer-20260529T040117-stress-2026-05-29-futures5m

## Claim

> Adversary Engineer, `futures5m` botunun 5 tarihsel kriz penceresinde 0/5 geçtiğini, LUNA 2022-05'te trade #772'de equity sıfırlanarak tamamen likide olduğunu, diğer "kazançlı" görünen periyotlarda (%84.28 / %66.83 DD) recovery'nin şans eseri gerçekleştiğini, ve mevcut yapının kaldıraçlı bir likidasyon makinesi olduğunu tespit etti.

## Why I Endorse

Risk Officer olarak bu analizi onaylıyorum. Adversary Engineer'ın üç temel bulgusu teknik açıdan sağlam, muhafazakâr, ve 2026-05-27 tarihli önceki futures5m stress testinin bulgularıyla tutarlıdır (bkz. `risk_officer-20260527T120500-endorse-stress-futures5m-crit`). Kritik ayrım doğru kurulmuş: LUNA'da edge değil **sizing/leverage** öldürdü; WR %46.85 normal aralıktaydı. Bu, engine'in drawdown sınırına ulaşınca pozisyonu zorla kapatmaması veya lot size'ı volatiliteye göre daraltmaması sorunudur — backtest simulasyonu gerçek broker likidasyon mekaniğini modellememiş.

Ek olarak: **config dosyasının bulunamadığı** (Setup: "Config: not found") belirtilmemiş ama bu kritik — test varsayılan veya çalışma zamanı parametresiyle yapıldıysa gerçek canlı risk parametrelerinin ne olduğu belirsizdir. Bu gap, bulguları daha da ağırlaştırır; hafifletmez.

## Evidence

- **Kanıt 1 — LUNA 2022-05: %100 DD, trade #772'de equity sıfır (HARD LIKIDASYON).**
  3902 trade'in 772'nci işleminde hesap tükendi — periyodun %20'sinde. WR %46.85 iken likide olmak, sizing/leverage sorununu izole eder: 2022-05-07 UST de-peg → 2022-05-12 LUNA $0.10 penceresinde 5m bar'lar yüksek volatilite nedeniyle ATR patlamış olmalı; risk.yaml'daki `max_leverage` ve `atr_multiplier` bu volatilite rejimine uygun lot azaltması yapmadı. Gerçek Binance BUSD-margined hesaplar bu pencerede saatler içinde sıfırlandı — simülatör bunu modellemedi.

- **Kanıt 2 — FTX %84.28 DD "kazandı" analizi doğru: bu edge değil, şans.**
  8 günlük recovery matematiksel olarak tutarlı ama likidasyon eşiğine (%100) **%15.72 mesafede** kapandı. 6 Kasım CZ tweet → 9 Kasım FTT $22→$2 penceresi. Bir WS kopması, funding spike (%0.3/8h), ya da 1 bar atlama bu bot'u LUNA senaryosuna taşırdı. Recovery gate'in geçmesi (`recovery_days=8 < 30`) kırılganlığı maskeliyor; DD gate (%84 vs threshold %20) gerçeği söylüyor.

- **Kanıt 3 — BTC ATH %66.83 / +648% — over-leveraged bull-regime sömürüsü.**
  Concave=False: equity eğrisi içbükey — en büyük kazanımlar erken, sonra sertleşme. %66.83 DD, Kelly fraction'ın muhtemelen 2-3x üzerinde sizing'e işaret eder. Edge sadece bull rejimde geçerli; bir trend kırılmasında LUNA patikasına girer.

- **Kanıt 4 — 0/5 periyot DD gate geçemedi (threshold %20 vs gerçek %23.79-%100).**
  Yen Carry 2024-08 en "iyi" periyot: %23.79 DD, gate %20 — sadece %3.79 marjla sınırın üstünde. Bu marj herhangi bir parametre varyasyonu veya gerçek slippage ile aşılabilir. Robustness yok.

## Strengths I Want to Highlight

1. **Doğru root cause izolasyonu:** "WR normal ama likide oldu → bu edge sorunu değil sizing/leverage sorunu." Bu ayrım birçok analist tarafından kaçırılır. Adversary Engineer bunu açıkça yazmış.
2. **"Şans vs edge" argümanı sağlam:** FTX ve BTC ATH kazancını "şans" olarak etiketlemek ve somut karşı-olgularla desteklemek (WS kopması, funding spike senaryoları) metodolojik açıdan güçlü bir red team yaklaşımı.
3. **CRIT verdict cesurca verilmiş:** "0/5 pass, CRIT" — false-positive endişesi olmadan conservative bias korunmuş. Risk Officer bu tutumu onaylar.
4. **Günlük trade hacmi hesabı:** "3902 trade / 8 gün = ~488 trade/gün" — bu hesap volatil dönemde pozisyon açma frekansının kontrolsüz olduğunu somutlaştırıyor.

## What Would Change My Mind

- **Engine'e gerçek likidasyon mekaniği eklenirse ve LUNA testi DD < %20 çıkarsa:** `margin_safety_ratio` backtest'te enforce edilmiş, lot size volatilite-uyarlamalı (örn. `vol_targeting` aktif) ve sonuç hâlâ LUNA'da <%20 DD ise bu endorse geri çekilir, yeniden değerlendirme gerekir.
- **Stress test gerçek config ile yeniden çalıştırılırsa:** "Config: not found" durumunda yapılan test parametreler bilinmeden çalışmış olabilir. Eğer gerçek `configs/risk_futures5m_*.yaml` parametreleriyle sonuçlar materyal ölçüde değişirse (özellikle Yen Carry <%20 DD), periyot bazında yeniden review yaparım. Ancak LUNA %100 DD → likidasyon bu config'den bağımsız bir engine sorunudur; config fix tek başına yeterli olmaz.
- **Hiçbir şey futures5m'i LUNA'da kurtaramaz:** Bu bot `live` veya `paper` modda olmamalı, engine likidasyon simülasyonu düzeltilmeden ve vol-targeting eklenmeden. Bu kriter değişmez.
