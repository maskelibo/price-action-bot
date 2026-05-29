# Hipotez: HYP-2026-05-29-brooks-3fx-vol-targeting

## Pre-registration (KOD ÖNCESİ — yazıldı 2026-05-29)

### Bağlam
`scripts/brooks_portfolio_3fx.py` mevcut: brooks_failed_breakout, 3 FX (EUR/GBP/USD-JPY 4H),
eff_r=3% → medyan +10.1%/ay, AMA MaxDD(MC) -41%, ham continuous -91%, OOS kırılgan,
aylık dağılım SAĞ-ÇARPIK (mean +16% >> medyan +10%). Korelasyon ort 0.13.
Principal "1 ay %400 bir ay %0 olmasın" = DÜŞÜK VARYANS, yüksek aylık Sharpe istiyor.
Bu kaldıraç değil RİSK-MÜHENDİSLİĞİ problemi.

### İddia (test edilecek)
"Sabit-risk sizing yerine, t-1'e kadar bilinen REALIZED volatiliteye TERS ölçekli
pozisyon boyutu (vol-targeting) + eşzamanlı-açık-risk cap + per-sembol eşit-risk
(risk-parity) ağırlıklandırması uygulandığında; AYNI continuous-MaxDD seviyesinde
aylık getiri dağılımının STANDART SAPMASI ve SAĞ-ÇARPIKLIĞI düşer (dağılım sıkışır),
aylık Sharpe artar — getiri medyanı bozulmadan veya artarak."

### Null hipotez (Popper — ne olursa çürür)
H0: Vol-targeting, sabit-risk'e göre AYNI MaxDD'de aylık-Sharpe'ı anlamlı artırmaz
(Δ Sharpe ≤ 0 veya std düşüşü çarpıklık-sabit MaxDD'de fark yaratmaz).
Eğer H0 doğruysa: vol-scaled ve fixed-risk eşit-MaxDD noktalarında medyan/std/Sharpe
İSTATİSTİKSEL OLARAK AYIRT EDİLEMEZ olmalı (bootstrap CI'ları örtüşür).
Çürütme kanıtı: eşleştirilmiş-MaxDD'de Sharpe-artışı bootstrap %95 CI alt-sınırı > 0
VE OOS'ta da yön korunur.

### Falsify edici kırmızı bayraklar (önceden taahhüt)
1. Vol-target parametreleri (lookback, hedef-vol, floor/cap) IS'te optimize edilip
   OOS'ta Sharpe-artışı yön değiştirirse → vol-targeting OVERFIT, REDDET.
2. Vol-targeting yalnızca aşırı-DD kuyruğunu kesiyor ama medyanı %30+ düşürüyorsa →
   "risk azaltma" trivially; gerçek "free lunch" değil, sadece de-risk. Şerh düş.
3. Eşzamanlı-risk cap tek başına MaxDD'yi açıklıyorsa (vol-target marjinal) →
   dürüstçe "asıl kazanım concurrency cap" de.

### Dependent variables (ölçülecek, pre-registered)
aylık: mean, MEDIAN, std (dağılım genişliği), skew (çarpıklık), min-ay, max-ay,
neg-ay%, aylık-Sharpe (mean/std), continuous-MaxDD, MC-medianDD, MC-ruin.

### Independent variables (taranacak — multiple testing FARKINDA)
- vol_lookback ∈ {10, 20, 40, 60} bar (trailing realized port-return std)
- target_monthly_vol ∈ {6%, 8%, 10%, 12%}
- vol_floor/cap (scale clamp) ∈ {[0.25,3], [0.33,2.5], [0.5,2]}
- max_concurrent ∈ {2, 3, 4, 6}
- total_open_risk_cap ∈ {3%, 5%, 8%, none}
- weighting ∈ {equal-notional(baseline), risk-parity-inverse-vol}
→ grid büyük; multiple-testing düzeltmesi (BH-FDR) + OOS-validation = anti-p-hacking koruması.
   IS'te en iyi 3 konfig SEÇİLİR, OOS'ta TEK SEFER doğrulanır (held-out).

### Lookahead disiplini
- Vol tahmini SADECE t-1 ve öncesine kapanmış trade R'leri / kapanmış-bar ATR'sinden.
- Trade entry sırasında o-an açık trade'ler vol'e GİRMEZ (sonuç bilinmez).
- Engine'in dolar-bazlı equity compound mantığı korunur; yalnız per-trade risk_pct
  causal-vol-scale ile çarpılır.

### Beklenen sonuç (Tetlock — kalibrasyon, predictive interval)
- %60 olasılık: eşleştirilmiş-MaxDD'de aylık std %20-40 düşer, Sharpe +0.1..+0.3 artar,
  medyan ≈ sabit (±%2pp). (Diversification + vol-targeting literatürü bunu destekler.)
- %30 olasılık: std düşer ama medyan da düşer (de-risk, free-lunch değil).
- %10 olasılık: hiçbir anlamlı kazanım (H0 reddedilemez).
- NET hedef "aylık %15-20 ortalama + düşük varyans": ÖN-TAHMİN gerçekçi DEĞİL —
  %15-20 mean'i tutturmak yüksek risk_pct gerektirir, bu da std/MaxDD'yi şişirir.
  Beklenen tavan: ~%8-12 medyan @ kabul edilebilir (-25%..-30%) MaxDD, std düşürülmüş.

### Stop criteria
IS'te hiçbir vol-target konfig sabit-risk'e göre eşit-MaxDD'de Sharpe artışı
göstermezse → hipotez terkedilir (3 satır learning.md).

### Reproducibility
git=audit-hardreview-20260528 @ commit (run-time stamped),
data=snapshot /tmp/forex_snap_*.duckdb (sha256 ef034c8d…), seed=12345.
cost: fee=0, slip=1.0bps, swap=0.3bps/night Wed3x (mevcut honest model, DEĞİŞMEZ).
