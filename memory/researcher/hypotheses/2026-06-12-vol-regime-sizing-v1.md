---
doc_id: researcher-20260612T093000-vol-regime-sizing-v1
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-12T09:30:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [sizing, volatility_regime, kaufman, lopez, fractional_f, pre_registered, single_setup]
supersedes: null
hash: null
---

# Hipotez: vol-regime-sizing-v1

**Seed konu:** Volatility regime sizing optimization
**Yaklaşım:** Tek setup, sıfır sweep, sabit thresholds. Klasik kurallar (Kaufman + López) literatürden alınarak FIXED. Sadece kabul/red verdir.

---

## 1. İddia (tek cümle, ölçülebilir)

> 15m timeframe canlı champion (`risk_phoenix_scalp_15m_widestop_vsa2.yaml`, fixed `risk_pct=0.005`) üzerine eklenen **volatility-regime sizing adapter** (regime classifier + López deleveraging backstop), **2024-01-01 → 2026-04-30 OOS dilimi**nde, aynı evren (19 sembol) ve aynı entry/exit sinyalleri altında, baseline (fixed 0.005) ile karşılaştırıldığında:
>
> - **Calmar ratio** Δ ≥ **+0.15** (absolute)
> - **MaxDD** Δ ≤ **−5pp** (absolute azalma)
> - **Sharpe** kaybı ≤ **−0.10** (en az korunmalı)
> - **Net annual return** göreceli kaybı ≤ **%15**
> - **Trade count** Δ ≤ **±%3** (sanity — sizing değişimi count'u taşımamalı; aşarsa metodolojik leak vardır)

Bu beş koşulun **hepsi** sağlanırsa hipotez "uygun aday"; herhangi biri ihlal edilirse RED.

---

## 2. Setup (pre-registered, FIXED — optimize EDİLMEYECEK)

### 2.1 Regime classifier
- **Sinyal:** `ATR_pct = ATR(14, 15m) / close`
- **Lookback:** son **60 bar** (Kaufman 30-trade window'unun 15m muadili; 60 × 15m = 15h ≈ 1 işlem günü)
- **Eşikler:**
  - `low_q = 0.33` → düşük volatilite rejimi
  - `high_q = 0.66` → yüksek volatilite rejimi
- **Atama:** Her bar için ATR_pct rolling 60-bar percentile'ına bakılır; <0.33 = LOW, 0.33-0.66 = MID, >0.66 = HIGH.

### 2.2 Sizing multiplier (Kaufman fractional-f → regime-down-only)
| Regime | mult |
|---|---|
| LOW  | 1.00 |
| MID  | 0.75 |
| HIGH | 0.50 |

**Not:** Yukarı doğru ölçeklemeyiz — LOW = baseline. Bu, Kaufman'ın "alpha decay'de küçül" prensibinin volatilite versiyonudur (RAG #4).

### 2.3 López deleveraging backstop (RAG #5)
- `L_t = L_baseline · (1 − D_t / DD_max)`
- `DD_max = 0.20` (champion realistik DD bandı, [[v14-frontier-20pct-config]] tutarlı)
- `α = 1.0` (fixed; López baseline)
- `D_t` = rolling 30-bar equity'deki cari drawdown
- **Combine kuralı:** Final risk = `risk_pct_base × regime_mult × lopez_scalar`, döşeme min(0.10×base).

### 2.4 Veri ve infra
- **Universe:** mevcut canlı 19 sembol (no swap — survivorship leak yok)
- **TF:** 15m
- **Fees:** 7.5 bps taker (canlı ile aynı)
- **Slippage:** 5 bps konservatif
- **Engine:** `backtest/engine.py` (deterministic mode)
- **OOS dilimi:** 2024-01-01 → 2026-04-30 (28 ay)
- **In-sample (sadece sanity):** 2022-06 → 2023-12 (DD_max baseline doğrulama için, parametre seçimi DEĞİL)

---

## 3. Gerekçe (RAG referansları)

- **[Kaufman, fixed-fractional + regime modulation]** (RAG #4): rolling pencerede "kötü rejimde küçül" kuralı; %50 size reduction. Burada win-rate yerine **volatilite percentile** kullanıyoruz çünkü trade sayısı (60 bar ≠ 60 trade) yetersiz — vol-regime daha sağlam tetik.
- **[López, dynamic deleveraging]** (RAG #5): `L_t = L* · (1 − D_t/DD_max)^α`. Geçmiş drawdown'a göre kaldıraç azaltma — fonun ölmesini önler.
- **[Kaufman, fractional optimal-f]** (RAG #6): 0.5×–1.0× tipik pratik. Bizim multiplier'lar (1.0 / 0.75 / 0.5) bu bandın içinde — keyfi seçim DEĞİL.
- **[Kaufman, crypto risk]** (RAG #7): kripto fat-tail için 0.5–1.0% baseline. Champion 0.005 = 0.5% bu bandın alt sınırında, doğru başlangıç.
- **[Grimes, volatility cycles]** (RAG #9): volatilite döngüseldir, düşük → yüksek → düşük. Vol-regime sizing bu döngüye binmeyi değil, **yüksek vol dönemlerinde küçülmeyi** hedefler (savunma, hücum değil).

---

## 4. Null hipotez

> Regime sizing adapter, baseline'a kıyasla **istatistiksel olarak ayırt edilebilir bir Calmar iyileşmesi sağlamaz** (paired bootstrap; H0: ΔCalmar ≤ 0.15).

---

## 5. Bağımsız değişkenler (FIXED — pre-registered, sweep yapmıyoruz)

```yaml
regime_lookback_bars: 60      # 15h ≈ 1 işlem günü
regime_low_q: 0.33
regime_high_q: 0.66
mult_low: 1.00
mult_mid: 0.75
mult_high: 0.50
dd_max: 0.20
alpha: 1.0
dd_lookback_bars: 30
mult_floor: 0.10              # asla baseline'ın %10'una düşmesin (likidite/min-notional koruması)
```

**Sweep yok. Optuna yok. Tek setup test edilir.** Sebep: 8 parametrede en küçük 3'er level grid bile 6561 trial = ciddi multiple-testing katlama. Pre-registration disiplini sweep'i yasaklar.

---

## 6. Bağımlı değişkenler (ölçeceğimiz metrikler)

| Metrik | Hedef | Karşılaştırma |
|---|---|---|
| Calmar (primary) | Δ ≥ +0.15 | baseline vs adapter |
| MaxDD | Δ ≤ −5pp | absolute |
| Sharpe | Δ ≥ −0.10 | en az korunmalı |
| Net annual return | göreceli kayıp ≤ %15 | trade-off |
| Trade count | Δ ≤ ±%3 | sanity (metodolojik leak guard) |
| Profit factor | info | bilgi amaçlı |
| Regime split breakdown (LOW/MID/HIGH için ayrı PnL) | info | adapter'ın doğru yerde küçüldüğünü kanıtla |

---

## 7. İstatistiksel test planı

- **Paired bootstrap** (B=1000 resample, equity-curve günlük returns'ler üzerinden, semboller arası bağımsızlık değil — günlük portfolio returns paired).
- **H1:** ΔCalmar > 0.15 → p < 0.0125 (Bonferroni n=4 primary metric)
- **H1:** ΔMaxDD < −5pp → p < 0.0125
- **Sharpe ve return non-degradation** için tek-yön test, p < 0.05 (gating, primary değil).

---

## 8. Stop criteria (araştırma terkedilir)

1. **In-sample sanity check** (2022-2023): adapter ekleyince in-sample Calmar Δ < 0 → metod baştan yanlış, terk.
2. **OOS Sharpe Δ < −0.30**: çok büyük degradation → sizing kuralı yanlış kurgu.
3. **Trade count Δ > %5**: metodolojik leak (sizing entry/exit sinyaline sızıyor) → kodda bug, hipotez değil.
4. **LOW regime'de kayıp**: baseline LOW'da edge varken adapter LOW'da kaybediyorsa kurgusal hata.
5. **Bonferroni sonrası ΔCalmar p > 0.05**: anlamlılık yok → red.

---

## 9. Curve-fit kırmızı bayrakları (proaktif itiraf)

- ⚠️ **8 parametre var.** Şu an FIXED ama gelecekte "ufak bir tweak" cazip gelecek. **Bu hipotez committed olunca paramlar dondurulur** — herhangi bir değişiklik = yeni hipotez ID.
- ⚠️ **DD_max=0.20** çok yakın geçmişe (champion ölçümlerine) bakıyor — circular reasoning riski. Mitigasyon: 0.15 ve 0.25 ile **sadece sensitivity check** (gate değiştirme), ana karar 0.20 ile.
- ⚠️ **Regime lookback 60 bar** keyfi — "1 işlem günü" gerekçesi rasyonelleştirme olabilir. Bu yüzden TEK lookback ile test, 30/120 ile sweep YOK.
- ⚠️ **Walk-forward yapamıyoruz** çünkü tek setup; bunun yerine **2024-2026 sürekli OOS** + **regime split breakdown** + **paired bootstrap** ile triangulate.
- ⚠️ **Survivorship**: 19 sembol şu an aktif; geçmişte delist olan var mı kontrol — eğer varsa universe genişlet.

---

## 10. Robustness (zorunlu — SOP-3 alt-küme, tek-setup kısıt nedeniyle adapte)

| Test | Plan |
|---|---|
| OOS continuous (24+ ay) | 2024-01 → 2026-04 |
| Regime split (LOW/MID/HIGH ayrı PnL) | her rejimde adapter ≥ baseline olmalı (en az 2'sinde, HIGH'da kesin) |
| Stress periodları | 2024-03 (BTC ATH), 2024-08 (Yen carry), 2025-Q1 alt-vol (varsa) |
| Symbol-out CV | 19 sembolden her birini tek tek dışarıda bırak, ortalama Calmar değişmemeli |
| Sensitivity (DD_max ∈ {0.15, 0.20, 0.25}) | yalnız bilgi — gate değiştirmez |
| Shuffle baseline | adapter mantığını random regime atamasıyla yenmeli (p < 0.05) |
| Lookahead testi | entry +1 bar geciktir → edge korunmalı (vol-regime hâlâ geçmiş baktığı için) |

---

## 11. Reproducibility

- `git_hash`: hipotez commit'te eklenecek
- `config_hash`: `configs/research/vol_regime_sizing_v1.yaml` (sha256)
- `data_hash`: DuckDB snapshot 2026-06-12

---

## 12. Karar matrisi (test sonrası doldurulacak)

- [ ] Tüm 5 primary koşul ✓ + Bonferroni p<0.0125 → **Lab tournament adayı** (iterate v2 yasak — TEK setup disiplini)
- [ ] Calmar+DD geçer ama Sharpe Δ < −0.10 → **SOP-4b iterate**: mult'ları zayıflat (1.0/0.85/0.70) veya López α=2 dene, **YENİ hipotez ID ile**
- [ ] Trade count Δ > %5 → kod bug; düzelt; tekrar koş
- [ ] Hiçbir gate geçilemez → **gerekçeli RED** + `learning.md`'ye 3 satır

---

## 13. İlişkili memory

- [[v14-frontier-20pct-config]] — DD_max=0.20 baseline gerekçesi
- [[backtest-compounding-inflation]] — sabit-fraksiyon kullanımı zaten doğru taraftayız
- [[smc-course-no-edge.md]] — geniş-stop dersi 3. kez; bu hipotez de FIXED setup disiplinine bağlı

---

**Pre-registration tamamlandı. Kod yazımı bu commit'ten sonra.**
