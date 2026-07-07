---
doc_id: researcher-20260629T060500-donchian-20-55-channel-breakout-cross-strategy-vsa-companion
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-29T06:05:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, pre-registration, cross-strategy, donchian, turtle, channel-breakout, momentum, vsa-companion]
supersedes: null
hash: null
---

# HYP-2026-06-29-donchian-20-55-channel-breakout-cross-strategy-vsa-companion

## 1. Hipotez (pre-registered, ölçülebilir)

> "**1D timeframe**'de, mevcut 18-sembol kripto perpetual evreninde, **Donchian 20-bar (entry) / 10-bar (exit) channel breakout** kalıbı (Turtle System 1 — Dennis/Eckhardt 1983 mekaniği) — **ADX(14) > 25 trend-filtresi gate'i** ile, kırılım barının kapanışında piyasa alımı (long: close > prev-20-high; short: close < prev-20-low), SL = giriş ± 2.0×ATR(20), exit = 10-bar opposite channel'a değme veya 30-bar max-hold, risk = %0.5/trade, fee = 7.5 bps taker + 5 bps slip, leverage = 1× — 2023-01-01 → 2025-12-31 dönemi out-of-sample tarama sonucunda:
> - **Net annualized return > %22** (fee + slip dahil)
> - **OOS Sharpe > 0.8** (Chan single-asset eşiği, RAG #9)
> - **MaxDD < %30** (account equity üzerinden, CT-RSK-01 standardı — trend-follow için yüksek tolerans bilinçli)
> - **Profit factor > 1.4**
> - **Average R-multiple ≥ 2.2** (Turtle asimetrik R yapısı — kazananlar 3-5R kabul, RAG #7)
> - **Win rate ∈ [%28, %42]** (>%50 olursa overfit şüphesi, <%28 olursa pattern bozulmuş — info+gate)
> - **vsa_climax_test ile günlük getiri korelasyonu \|ρ_daily\| < 0.20** (1D resample, son 250 ortak trade-günü, rolling-30d window median)
> - **Trade sayısı ≥ 90** (18 sembol × 3 yıl OOS için minimum istatistik anlamlılık)
> - **Shuffle-baseline p-value < 0.05** (returns rastgele yer değiştirilmiş null model)
> - **Bonferroni-düzeltilmiş p-value (n=18 grid) < 0.05** → α_individual < 0.00278
> üretir."

**Null hipotez (H0):** Donchian 20/10 channel breakout + ADX>25 trend-gate'in kripto perpetual 1D evrenindeki net annualized return'ü, shuffle baseline'dan (returns rastgele yer değiştirilmiş, 1000 iter) istatistiksel olarak ayırt edilemez (p ≥ 0.05). VEYA vsa_climax_test ile |ρ| ≥ 0.35 (cross-strategy diversification değeri sıfır).

## 2. Gerekçe (RAG referansları)

- **[RAG #7 — book_kaufman_summary, Turtle Channel Breakout]** "20-bar veya 55-bar high/low kırılımı; trending market'te ADX > 25 ideal; **asimetrik R-multiple — %35 win rate ile pozitif beklenti, çünkü winners 3-5R, losers 1R**; failure: choppy/range rejimde back-to-back whipsaw → kümülatif %20-40 drawdown." → Bu hipotezin gate'leri Kaufman'ın açık tanımından türedi (param hand-pick değil).
- **[RAG #6 — book_market_structure_order_flow]** BOS close-based n=3 → **"Yüksek" mekanik çalışabilirlik kripto 1D'de** (net kural, backtestable, az parametrik). Donchian channel breakout BOS'un parametrize edilmiş atası: 20-bar high break = swing-high break.
- **[RAG #9 — book_chan_summary]** Sharpe-based strategy gating: yeni stratejiler portföye girmeden önce out-of-sample Sharpe > 0.8 (single asset) eşiği. Bu hipotezdeki **OOS Sharpe > 0.8 gate'i** Chan'in retail-realistic edge tablosuyla uyumlu — keyfi değil.
- **[RAG #1 — book_lopez_summary]** López de Prado'nun 6-kriterli overfit kontrol listesi (DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, params/sample > 1/30, walk-forward Sharpe varyansı > ortalama) — bu hipotezin robustness suite'i 6'sını da kontrol edecek.

**Cross-strategy edge gerekçesi (a priori, ispat değil):**
- `vsa_climax_test` = **volume climax + reversal** karakter (mean-reversion, extreme'de fade).
- `donchian_20_55_breakout` = **consolidation kırılımı + momentum continuation** karakter (trend-following, extreme'de chase).
- İki strateji a priori **birbirinin tersi rejimde aktive olur**: VSA climax sinyali piyasa "tükenmiş extreme'de" yanar; Donchian breakout piyasa "yeni high/low yaparken" yanar. → Negatif veya düşük korelasyon **beklenir**, ama bu **ölçülecek bir hipotez**, varsayım değil. |ρ| < 0.20 ayrı bir gate olarak doğrulanacak.

## 3. Dependent Variables (önceden kilitli metrikler)

| Metrik | Hedef | Tip |
|---|---|---|
| Net annualized return | > %22 | gate |
| OOS Sharpe (annualized, equity-based) | > 0.8 | gate |
| MaxDD (account equity, CT-RSK-01) | < %30 | gate |
| Profit factor | > 1.4 | gate |
| Average R-multiple | ≥ 2.2 | gate |
| Win rate | ∈ [%28, %42] | gate (band) |
| Trade sayısı (OOS) | ≥ 90 | gate |
| \|ρ_daily\| vs vsa_climax_test | < 0.20 (median rolling-30d) | gate |
| Shuffle-baseline p-value | < 0.05 | gate |
| Bonferroni-düzeltilmiş p (n=18 grid) | < 0.05 → α_indiv < 0.00278 | gate |
| Largest single-trade contribution | < %25 of total PnL | gate (anti single-event) |
| Bull/Bear/Range regime split — kaç rejimde pozitif | ≥ 2 of 3 | gate |
| Stress periyot (LUNA/FTX/2024-08) maks dilim DD | < %15 | gate |

## 4. Independent Variables (önceden kilitli — perturbation listesi)

**Sabitlenen (fix-locked) — bu değerler hipotez yazılırken seçildi, optimization yasak:**
- Timeframe = 1D
- Universe = mevcut 18-sembol kripto futures perpetual evreni (uni-watchlist-candidate-cut sonrası, UNI hariç)
- Entry channel = prev-20-bar high/low (klasik Turtle System 1)
- Exit channel = prev-10-bar opposite (klasik Turtle exit)
- ADX(14) gate = > 25 (Kaufman önerisi, RAG #7)
- SL = entry ± 2.0 × ATR(20) (Turtle default)
- Max-hold = 30 bar (whipsaw'dan çıkış sigortası — RAG #7 "choppy rejimde back-to-back whipsaw" uyarısı)
- Risk = %0.5/trade (mevcut bot risk profili)
- Leverage = 1× (sermaye koruma — kripto kaldıraç disiplini facts/leverage-discipline ile uyumlu)
- Fee = 7.5 bps taker + 5 bps slip (konservatif)

**Perturbation grid (robustness suite — sweep için):**
- Entry channel N ∈ {20, 55} (Turtle System 1 vs System 2; 2 değer, **küçük tutuldu**)
- SL ATR-multiplier ∈ {1.5, 2.0, 2.5} (Turtle ±0.5)
- Exit channel N ∈ {10, 20, max-hold-only} (3 değer)

**Toplam param uzayı = 2 × 3 × 3 = 18 kombinasyon.** Bu sayı **kasıtlı olarak küçük** — Bonferroni mantıklı kalsın diye. **Optuna kullanılmayacak**; full grid evaluation + her hücre için ayrı OOS Sharpe rapor + Bonferroni-FDR düzeltmesi.

**Yasak — keyfi parametre genişletme:** Bonferroni gate'i geçemediği takdirde "daha fazla denerim" yasak (post-hoc p-hacking).

## 5. Beklenen p-value & Multiple Testing Düzeltmesi

- **Pre-registered Bonferroni:** n=18 grid → α_individual = 0.05 / 18 ≈ **0.00278**.
- **Beklenen shuffle baseline p-value:** < 0.001 olmazsa edge gerçek değil; çünkü Donchian breakout'un long-horizon kripto bull-bias'tan **trivially** kâr çıkarması mümkün → shuffle null bunu kontrol eder.
- **Benjamini-Hochberg FDR alternatifi:** 18 hücreden ≥ 5'i bireysel p < 0.05 verirse FDR @ q=0.10 ile genel anlamlılık.
- **Walk-forward Sharpe varyansı kontrolü (Lopez kriteri):** 12 dilimden Sharpe std-dev < ortalama olmalı; aksi halde stratejinin "şanslı dilim" sürüklediği kabul.

## 6. Stop Criteria (terkten — overfit veya null edge işaretleri)

| Koşul | Aksiyon |
|---|---|
| IS Sharpe < 0.5 | Araştırma terkedilir, learning.md'ye 3-satır gerekçe |
| Trade sayısı IS < 60 | Frekans çok düşük — istatistik anlamsız, terk |
| \|ρ_daily\| vs vsa_climax_test > 0.35 (median) | Cross-strategy diversification yok, terk |
| IS Sharpe / OOS Sharpe > 3.0 (Lopez kriteri, RAG #1) | Klasik overfit, terk |
| Walk-forward 12 dilim, pozitif dilim sayısı < 4 | Edge gerçek değil, şans, terk |
| Stress periyot (LUNA / FTX / 2024-08) dilim DD > %20 | Tail-risk kabul edilemez, terk |
| Best-param ATR-mult sınırda (1.5 veya 2.5) | Daha geniş aralık dene; hâlâ sınırdaysa overfit, terk |
| Toplam PnL'in > %30'u tek trade'den | Single-event bias, terk |
| Bull rejim pozitif + Bear rejim pozitif + Range rejim < 0 — kabul edilebilir | OK, ama range performance raporlanır |
| Bear-only veya Range-only edge → red değil ama Lab tournament'a "regime-gated" varyant olarak gider | conditional accept |

## 7. Curve-Fit Şüphesi Notları (paranoya bölümü)

> Bu hipotez yazılırken **şu curve-fit risklerinin farkındayım**, robustness suite bunları aktif test edecek:

1. **Turtle default'ları (20, 55, 2×ATR, 10-bar exit) Dennis tarafından 1983'te ex-post seçildi.** Yani bu sayılar zaten **bir kez optimize edilmiş** — kripto'ya direkt aktardığımda "bedava lookahead" alıyor olabilirim. Robustness: Bonferroni düzeltmesi + 12 dilim WF varyans kontrolü ile mit edilecek.
2. **Bulkowski / Kaufman istatistikleri US equities 1980-2020.** Kripto 2017+, çok farklı volatilite + 24/7 rejim. RAG #7'deki "%35 win rate" hedefi **kripto'da daha düşük çıkabilir** → win rate band [28, 42] kasıtlı olarak Bulkowski'nin altında.
3. **Son 3 yıl kripto bull-bias.** Donchian breakout = trend-follow → uzun side'da **trivial pozitif** olabilir. **Shuffle baseline + bull/bear/range split bunu yakalar.** Sadece bull rejimde pozitifse → "bull-only edge", regime-gated varyant olur, "evrensel strateji" değil.
4. **ADX > 25 trend-filter ayarlanabilir bir param.** Bu hipotezde **fix-locked** (=25), perturbation grid'ine girmedi → keyfi gibi görünüyor. Gerekçe: ADX 25 = Kaufman'ın açık önerisi, hand-pick değil. Eğer hipotez gate'i geçer ama ADX'i değiştirince OOS Sharpe %30+ değişirse → "trend-filter overfit" kırmızı bayrağı.
5. **18 sembollük dar evren.** Symbol-out CV ile her sembolü tek tek çıkararak Sharpe stabilitesini test edeceğim. Bir sembol kaldırıldığında ortalama Sharpe %25+ düşerse → "1-2 sembol kâr taşıyor", red.
6. **Survivorship — UNI bot evreninden çıkarıldı (en kötü performans).** Backtest UNI'siz koşacak → kripto evrenine genel uygulanabilirlik testi için **UNI dahil** ayrı bir kontrol koşusu yapılacak.

## 8. Reproducibility

- Backtest engine: `backtest/engine.py` @ git HEAD `audit-hardreview-20260528`
- Data: DuckDB futures_journal universe, 1D bars, 2023-01-01 → 2025-12-31
- Config hash: hesaplama sonrası rapor footer'ında
- Seed: 42 (shuffle baseline + WF split deterministic)
- Tüm sonuçlar `(git_hash, config_hash, data_hash)` üçlüsü ile etiketlenecek

## 9. Lab Tournament Devir Koşulu

Yukarıdaki **TÜM gate'ler** + tüm SOP-3 robustness suite ✓ olmadan Lab'e devir YOK. Eğer gate'lerin bir kısmı geçer ama biri kalırsa **SOP-4b iterate patika**:
- v2: ADX > 30 (sıkı trend filter)
- v3: bull-only regime gate (bear/range skip)
- v4: tighter trailing exit (5-bar opposite channel)
- v5: confluence gate (üst-TF EMA200 yön onayı)

Max 5 iterate v sonra **deferred** (red değil), edge gerçek ama mevcut konfigürasyon hatlarında değil notu + arşiv.

## 10. Şu Anki Bilinen Riskler (Pre-mortem)

- **En olası başarısızlık modu:** kripto bull-bias trivial pozitif eşik geçirir ama bear rejimde tüm getirileri verir → "bull-only edge" verdict.
- **İkinci en olası:** Bonferroni düzeltmesi α'yı 0.00278'e indirir, hiçbir grid hücresi geçemez → sonuç "noise içinde sinyal yok".
- **Üçüncü:** vsa_climax_test ile ρ beklenenden yüksek (0.30+) çıkar → diversification değeri kalkar, cross-strategy gerekçesi çürür.

---

**İmza:** researcher (pre-registered, kod yazılmadan önce, git commit ile dondurulacak)
**Sonraki adım:** `backtest/engine.py` config'i bu hipotezden türet → backtest çalıştır → SOP-3 robustness suite → rapor.
