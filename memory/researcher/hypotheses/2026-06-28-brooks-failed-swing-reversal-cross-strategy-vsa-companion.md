---
doc_id: researcher-20260628T180000-brooks-failed-swing-reversal-cross-strategy-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-28T18:00:00Z
status: DRAFT
confidence: low
depends_on:
  - researcher-20260628T060000-mat-hold-5bar-continuation-cross-strategy-vsa-companion
  - researcher-20260623T220000-golden-death-cross-50-200-ema-cross-strategy-companion-vsa
  - researcher-20260623T100300-donchian20-vsa-companion
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags:
  - hypothesis
  - pre-registration
  - cross-strategy
  - brooks-failed-swing
  - reversal
  - vsa-companion
  - curve-fit-watch
  - correlation-risk-acknowledged
  - lopez-prado-familywise-inflation
  - recurring-seed-degeneracy-noted
supersedes: null
hash: null
---

# HYP-2026-06-28-brooks-failed-swing-reversal-cross-strategy-vsa-companion

## Seed Context
Cross-strategy edge keşfi — canlıdaki `vsa_climax_test` (volume-climax + spread reversal, **volume-driven mean-reversion**) için companion. **Seed-degeneracy uyarısı:** Bu seed son 4 haftada 26 kez tekrar tetiklendi (`memory/researcher/learning.md` recurring-20260628-053000). Önceki 13 farklı mekanik (Mat Hold, Donchian, Golden Cross, CHoCH, FVG, Order Block, EQH-EQL Sweep, Marubozu x2, Volman-iii, Chan-halflife, BOS x6) zaten pre-register edildi. Bu hipotez bugünkü RAG kart setindeki **henüz işlenmemiş tek mekanik** olan RAG #3 Brooks failed-swing'i hedefler. Eğer reddedilirse bir sonraki tetiklemede **seed-abort** kararı verilmeli.

## 1. Hipotez (pre-registered, ölçülebilir)

> "**1D timeframe**'de, mevcut **18-sembol** USDT-perpetual evreninde ([uni-watchlist-candidate-cut sonrası](memory/...)), **Brooks "failed-swing reversal at n-bar new extreme"** kalıbı — mekanik tanım:
> - **Tetik bar (t):** Close-based 20-bar new high (long-fade için) VEYA 20-bar new low (short-fade için).
> - **Reversal şartı:** Bar t'nin close'u, bar t'nin (high − low) range'inin **alt %33**'ünde (long-fade için → upper-shadow > 67%) veya **üst %33**'ünde (short-fade için).
> - **HTF opposition filtresi (zorunlu):** 1W timeframe'inde EMA(20) eğimi son 4 hafta `sign(slope_t) ≠ sign(daily_fade_direction)` (yani haftalık trend, fade yönüne **karşı** olmalı — Brooks'un "overextended trend + HTF opposition" kuralı).
> - **Giriş:** Bar t+1'in **open**'ında (lookahead-free, signal_chief standartı).
> - **SL:** Bar t'nin extreme (high long-fade için ise high, short-fade için low) ± `0.5×ATR(14)`.
> - **TP:** `2R` fixed (ATR-tabanlı değil — basit risk-multiple).
> - **Time-stop:** max-hold 10 bar.
> - **Risk:** %0.5/trade (canlı v14p3 ile aynı taban).
> - **Fee:** 7.5 bps taker + 5 bps slippage (konservatif).
> - **Dönem:** 2023-01-01 → 2025-12-31 (3 yıl OOS-fresh window — bu dönemin daha öncesi RAG/hipotez seçim sürecinde kullanılmadığı için kontamine değil).
>
> Bu setup OOS taramada şu **6 koşulu AYNI ANDA** karşılarsa kabul:
>
> - **Net annual return ≥ %18** (fee+slip dahil, account-equity bazlı)
> - **OOS Sharpe ≥ 0.8** (Chan single-asset eşiği, RAG #9)
> - **MaxDD ≤ %22** (account equity üzerinden, CT-RSK-01 standardı — %0-base PnL DEĞİL)
> - **Profit factor ≥ 1.35**
> - **Trade sayısı ≥ 80** (istatistik anlamlılık eşiği)
> - **`vsa_climax_test` ile günlük getiri korelasyonu \|ρ\| ≤ 0.30** (her iki sinyal de reversal olduğu için **0.20 yerine 0.30 daha gevşek eşik** kullanıldı; bu bir gerekçeli a priori karardır, ρ ölçüldükten SONRA eşik gevşetme YASAK)"

**Null hipotez (H0):** Brooks failed-swing reversal kalıbının kripto perpetual 1D evrenindeki net annual return'ü, shuffle baseline'dan (returns rastgele yer değiştirilmiş, 1000 iter) istatistiksel olarak ayırt edilemez (p ≥ 0.05).

## 2. Gerekçe (RAG referansları)

- **[RAG #3 — book_brooks_deep_catalog]** "Önceki önemli SR + overextended trend + reversal bar kalitesi yüksek + HTF opposition" — Brooks'un failed-swing setup'ı. **Test edilebilirlik skoru 5/5** (RAG'in en yüksek kategorisi): "n-bar high/low aşımı + geri dönüş mekanik, tamamen kodlanabilir. En iyi hipotez adaylarından biri." Bu hipotezde "önemli SR" gereksinimini düşürdüm (subjektif → mekanikleşmesi zor); yerine **HTF opposition + reversal-shadow %67** ile sertleştirdim.
- **[RAG #9 — book_chan_summary]** OOS Sharpe ≥ 0.8 single-asset gate'i buradan. Hand-pick değil.
- **[RAG #1 — book_lopez_summary]** López de Prado 6-kriter overfit listesi (DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, params/sample > 1/30) — robustness suite §5'te bunlara uyulacak.

**Cross-strategy gerekçesi (ve şerhi):**
- `vsa_climax_test` driver = **volume-spread** (climax volume + range expansion).
- Bu setup driver = **price-structure** (n-bar new extreme + reversal bar + HTF trend).
- **Mekanik driver farkı** düşük korelasyon için **a priori gerekçe** sağlar AMA garanti etmez. Her iki sinyal de "reversal at extreme" olduğu için aynı bar/aynı gün tetiklenebilir → ρ ≤ 0.30 koşulu **iki başarısızlık modunu** birden test eder: (i) driver farkı yetersizse ρ > 0.30 → hipotez reddedilir; (ii) ρ ≤ 0.30 olsa bile diğer 5 koşul tutmazsa edge gerçek değil.

## 3. Dependent Variables (önceden belirlenmiş metrikler, post-hoc eşik değişimi YASAK)

| Metrik | Hedef | Gerekçe |
|---|---|---|
| Net annualized return (fee+slip dahil) | ≥ %18 | Canlı v14p3 hedef bandının (+15-20/ay → ≥%180/yıl) **on'da biri** — companion için mütevazı |
| OOS Sharpe (annualized, equity-based) | ≥ 0.8 | Chan single-asset eşiği [RAG #9] |
| MaxDD (account equity, CT-RSK-01) | ≤ %22 | Canlı v14 DD %19-24 dürüst bandının üst sınırına yakın → konservatif |
| Profit factor | ≥ 1.35 | Sektör standardı; 1.0-1.2 noise, 1.5+ güçlü |
| Trade sayısı (OOS, 3 yıl, 18 sembol) | ≥ 80 | < 80 → istatistik güçsüz; Lopez params/sample kriteri için ham minimum |
| Realized reversal-success rate | info-only | (Bulkowski paralel istatistik yok bu specific kombinasyon için) |
| Daily-return correlation vs vsa_climax_test | \|ρ\| ≤ 0.30 | Cross-strategy premise; **post-hoc eşik gevşetme YASAK** |
| Shuffle-baseline p-value | < 0.05 | Edge'in gerçekliği |
| Bonferroni-düzeltilmiş p-value (66-shelf familywise) | < 0.05 → α_individual < **0.000758** | RAG #1 Lopez |

## 4. Independent Variables (önceden kilitli — perturbation listesi)

**Sabitlenen (fix-locked, optimize EDİLMEYECEK):**
- Timeframe = 1D
- Universe = 18-sembol futures evreni (uni-watchlist-candidate-cut sonrası: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, MATIC, DOT, LTC, ATOM, NEAR, ARB, OP, APT, SUI — UNI dahil DEĞİL)
- Dönem = 2023-01-01 → 2025-12-31
- Fee = 7.5 bps taker + 5 bps slip
- Risk = %0.5/trade
- TP = 2R (fixed multiple)
- Time-stop = 10 bar
- Bonferroni n = 66 (mevcut shelf büyüklüğü)

**Perturbation suite (parametre uzayı — Optuna **DEĞİL**, sadece robustness):**
Aşağıdaki her parametre **single-axis perturbation** ile test edilecek; Optuna multi-axis arama **YAPILMAYACAK** (curve-fit önleme — bu bir framework testi, parametre arama değil).

| Parametre | Default | Perturbation grid |
|---|---|---|
| n-bar new-extreme window | 20 | {10, 15, 20, 25, 30} |
| Reversal shadow eşiği | 0.67 (üst/alt %33 close) | {0.55, 0.60, 0.67, 0.75, 0.80} |
| ATR(14) SL multiplier | 0.5 | {0.25, 0.5, 0.75, 1.0} |
| HTF opposition window (1W EMA-slope lookback) | 4 hafta | {2, 4, 6, 8} hafta |

**Beklenen davranış:** Sharpe ortalaması perturbation sonrası **%25'ten az** düşmeli; tek-bir-pik (sadece n=20 ile çalışıyor, n=15 veya 25 ile çökmüş) görülürse **curve-fit kırmızı bayrak**, hipotez reddedilir.

## 5. Curve-fit Şüphesi (a priori — robustness raporundan ÖNCE)

Bu hipoteze **dört kırmızı bayrak adayı** önceden tanımlandı:

1. **HTF opposition filtresi tek başına performansın çoğunu üretiyor mu?**
   → Ablation testi: HTF filtresi KAPALI iken Sharpe nedir? Kapalı/Açık fark > %50 ise filtre = curve-fit araç.
2. **n-bar window pik davranışı.**
   → Yukarıdaki perturbation grid'ten %25+ düşüş varsa kabul edilmez.
3. **Reversal shadow eşiği keskinliği.**
   → 0.67 default, ama 0.60 veya 0.75'te Sharpe yarıya düşüyorsa eşik = arbitrary fit.
4. **Universe-out cross-validation.**
   → Her 18 sembolden 1'i out-bırakılarak 18 alt-test; en kötü alt-test Sharpe < 0.5 → hipotez fragile.

## 6. Expected p-value (pre-registered)

- **Naive shuffle baseline:** p < 0.05 (her seri için 1000 iter, Brock-Lakonishok-LeBaron tarzı).
- **Bonferroni (66-shelf familywise):** p_individual < **0.000758** (= 0.05 / 66).
- **Benjamini-Hochberg FDR (q = 0.10):** alternatif düzeltme; her ikisinden hangisi geçer raporda işaretlenecek.

## 7. Stop Criteria (araştırma terkedilir)

Aşağıdaki **herhangi biri** gerçekleşirse hipotez derhal reddedilir, ileri optimize edilmez:

1. **In-sample (2020-2022) Sharpe < 0.5** — fast-fail kapısı; OOS'a geçmeye değmez.
2. **Trade sayısı < 80** (OOS) — istatistik güçsüz, sonuç ne olursa olsun anlamsız.
3. **ρ vs vsa_climax_test > 0.30** — cross-strategy premise çökmüştür; setup kendi başına edge olsa bile **bu seed bağlamında reddedilir** (ayrı bir standalone hipotez olarak yeniden açılabilir).
4. **IS Sharpe / OOS Sharpe > 3** — Lopez kriteri; overfit.
5. **HTF-filter ablation farkı > %50** — filtre olmadan setup ölü; rejim-bazlı tek-trick.
6. **Perturbation Sharpe kaybı > %25** — fragile, robust değil.

## 8. Reproducibility

- `git_hash`: TBD (backtest commit hash backtest çalıştırılınca eklenecek)
- `config_hash`: bu doc'un SHA256'sı (immutable pre-registration)
- `data_hash`: `data/futures_1d_*.parquet` manifest'i (delisted dahil)
- `seed`: 42 (Optuna **yok**, sadece perturbation grid; seed shuffle baseline için)

## 9. Karar Akışı (sonuç raporunda doldurulacak)

- [ ] **Terfi adayı** (tüm 6 koşul + robustness suite ✓)
- [ ] **Iterate** (aylık ROI > 0 ama DD/diğer risk metriği gate'i geçemedi → SOP-4b v2)
- [ ] **Red** (ROI ≤ 0 veya lookahead/leakage veya stop-criteria tetiklendi)
- [ ] **Defer** (cross-strategy premise çöktü ama standalone setup ilginç → ayrı hipoteze taşı)

## 10. Sonraki Adım (kod yazmadan ÖNCE bu doc commit'lenir)

1. Bu pre-registration commit'lenir → hash dondurulur.
2. `signal_chief` Brooks-failed-swing detector implementasyonu (vektörize, lookahead-free, `tests/test_lookahead.py` zorunlu).
3. `backtest/engine.py` ile 2020-2022 IS smoke-test (stop-criteria #1 kapısı).
4. Geçerse 2023-2025 OOS + robustness suite §3 (SOP-3 tam paket).
5. Ablation + perturbation + universe-out CV (§5 kırmızı bayrak kontrolleri).
6. Karar yazılır, `lab_scientist`'e devredilir (tournament).

---

**Not (Recurring-Seed Politikası):** Bu seed (`Cross-strategy edge keşfi: aktif vsa_climax_test ile düşük korelasyonlu ek strateji`) son 4 haftada **26 kez** tetiklendi ve 14 farklı mekanik pre-register edildi. Henüz **hiçbiri Lab tournament'i geçmedi**. Bu hipotez reddedilirse veya iterate yoluna girip 5 versiyon tüketirse, bir sonraki tetiklemede `learning.md`'ye **seed-abort kaydı** yazılmalı ve seed `daily_seed_pool.yaml`'dan çıkarılmalıdır — bu cognitive bias (recency + sunk-cost) korumasıdır.
