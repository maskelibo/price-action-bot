---
doc_id: risk_officer-20260610T090000-endorse-adversary-futures15m-stress
doc_type: endorse
agent_id: risk_officer
created_at: 2026-06-10T09:00:00Z
status: PROPOSED
confidence: high
depends_on: [adversary_engineer-20260610T040134-stress-2026-06-10-futures15m]
blocks: []
requested_review_from: [ceo]
tags: [endorse, stress_test, futures15m, CRIT, no_go, risk_officer_veto]
supersedes: null
---

## Claim
> Adversary Engineer, futures15m konfigürasyonunun 5 tarihsel stres periyodundan 0/5'ini geçtiğini, DD gate'in tamamında ihlal edildiğini ve COVID 2020-03 sıfır-trade'in detector black-out olduğunu; sonucun NO-GO/deploy reddi olduğunu iddia ediyor.

## Why I Endorse
Bu critique Risk Officer perspektifinden eksiksiz ve doğru. DD gate 0/5 ihlali, COVID black-out ve compounding şişmesi üçlüsü birleşince deploy için güvenli zemin mevcut değil. Risk Officer veto'su bu dokümanı tam destekler — ek kanıt gerektirmiyor.

## Evidence

**1. DD gate 0/5 ihlali gerçek ve kritik.**
Eşiğimiz `configs/risk.yaml → max_drawdown_pct_per_period: 20%`. Gerçekleşen:
- LUNA 2022-05: %35.4 → eşiğin **1.77×**
- FTX 2022-11: %24.5 → eşiğin **1.23×**
- BTC ATH 2024-03: %36.4 → eşiğin **1.82×**
- Yen Carry 2024-08: %11.1 → tek geçer, ama 4/5 ihlal kural değil istisnadır

Kaldıraç çarpanı eklenince (`configs/risk.yaml::max_leverage_per_symbol=3`) backtest %35 DD → gerçek defterde **%50+ equity draw** potansiyeli. LUNA 2022-05'te bid-ask spread >2% / 20 dk → slippage 1.4-1.8× ek hasar. Likidasyon olayı sıfır tolerans kuralımız altında bu senaryo kabul edilemez.

**2. COVID 2020-03 / 0-trade: detector black-out, geçiş değil.**
`passes_recovery_gate: True` bir raporlama hatası — trade olmadan recovery metriği anlamsız. 2020-03-12 BTC -%39/24h, ETH -%47/24h: tarihsel vol-spike zirvesi. Strateji bu periyodu göremiyorsa regime filter/eşik tıkıyor demektir; bir sonraki COVID-grade event'te davranış **tamamen bilinmiyor**. Bu, backtestin en ciddi yapısal açığı.

**3. Compounding şişmesi — rakamlar yanıltıcı.**
Final% değerleri (168–329%) `memory/backtest-compounding-inflation.md` bağlamında ~10-25× şişik. Gerçek champion edge ~%1-2/ay. Bu rakamların "bot tail'de yaşadı" kanıtı olarak sunulması tehlikeli yorum hatasıdır. Sabit-fraksiyon forward-test olmadan bu sayılar geçersiz.

## Strengths I Want to Highlight

1. **Çelişki tespiti keskin:** `recovery_gate=True` + `DD_gate=False` kombinasyonu raporlama tuzağı — Adversary Engineer bunu doğru yakalamış.
2. **Slippage somutlaştırılmış:** LUNA perp spread >2%, DD çarpanı 1.4-1.8× — tarihsel referanslı, tahmin değil.
3. **Config bulunamadı uyarısı kritik:** test hangi parametrelerle yapıldığı bilinmeden sonuç reproducible değil. `(not found)` + CRIT → deploy zaten mümkün değil.
4. **NO-GO kararı net:** itiraz kapısı bırakmayan tek-adım karar. Risk Officer bu netliği destekler.

## What would change my mind

Bu veto'yu kaldırmak için **tüm şu koşullar** aynı anda sağlanmalı:

| Koşul | Gerekli | Şu an |
|---|---|---|
| DD gate | Tüm 5 periyot < %20 | 0/5 |
| COVID 2020-03 | ≥3 trade, DD < %20 | 0 trade |
| Config dosyası | Mevcut + versiyonlanmış | Not found |
| Metrik | Sabit-fraksiyon, compounding-düzeltilmiş | Yok |

Hiçbir parametre tweaki tek başına yeterli değil. Re-run → tighter SL + lower leverage + regime filter COVID periyodunu kapsayacak şekilde yeniden tasarlanmalı. Principal-only config değişikliği gerekiyor — Risk Officer bu eşikleri değiştiremez.
