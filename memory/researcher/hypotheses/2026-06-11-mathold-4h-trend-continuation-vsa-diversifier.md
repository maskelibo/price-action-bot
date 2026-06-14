---
doc_id: researcher-20260611T180000-mathold-4h-trend-continuation-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T18:00:00Z
status: DRAFT
confidence: med
depends_on:
  - researcher-vsa_climax_test-live-baseline  # aktif strateji daily return serisi
blocks: []
requested_review_from: [lab_scientist, risk_officer, adversary_engineer]
tags: [hypothesis, pre-registration, mat-hold, cross-strategy, diversifier, low-correlation, 4h, trend-continuation]
supersedes: null
hash: null
---

# Hipotez HYP-2026-06-11-mathold-4h — Mat Hold (4H) trend-continuation, vsa_climax_test diversifier'ı

## 0. Bağlam ve seçim gerekçesi

Aktif kol: `vsa_climax_test` (volume-spread analysis, climax/exhaustion → reversal-bias). Aktif kol-ailesi yapı olarak **mean-reverting / counter-trend**. Cross-strategy edge keşfi seed'i: portföye **yapısal ortogonal** bir kol eklemek.

Mat Hold (RAG#10, Bulkowski rank **10/103**, continuation rate **%74**, avg move **%6.1**) — 5-bar bullish-flag formasyonu. Trend-continuation çekirdeği; climax/exhaustion ile aynı bar'da nadiren tetiklenmeli ⇒ **a priori ρ(mathold, vsa) ≈ 0.0–0.20** beklentisi makul (kanıt: yapı seviyesinde mantık, ampirik test sonra).

Raftaki 66 stratejiden Mat Hold'u seçme nedeni: (i) Bulkowski'de rank 10 — istatistiksel taban güçlü; (ii) tanım Volman ii/iii inside-bar/Brooks flag continuation'larından **net ayrı** (sample örtüşmesi düşük); (iii) parametrik yüzeyi dar (5-bar geometrik tanım + ATR mültipler) — **az parametre, az sweep yüzeyi** (RAG#1 Lopez kriteri: param/N < 1/30 hedefi).

## 1. İddia (single sentence, ölçülebilir)

**"4H timeframe'de, 1D EMA50 üzerinde olan USDT-perpetual sembollerinde, Bulkowski Mat Hold (5-bar) bullish continuation pattern'ı Bar5 kapanışında alımla, 1.5×ATR(14) SL ve 3.0×ATR(14) TP (fixed 2R) ile, 2022-01 → 2026-06 sliding-OOS evreninde:**
- **Net monthly return > +3.0%** (fees 7.5bps taker + slip 5bps dahil, sabit-fraksiyon %1/trade, ay-bağımsız taze-$10k metodolojisi)
- **OOS Sharpe > 0.80** (Bonferroni n=15 sonrası anlamlı; ham OOS Sharpe > 1.20)
- **MaxDD < 22%** (account-equity tabanlı, mark-to-market)
- **Profit factor > 1.40**
- **|ρ(daily_return_mathold, daily_return_vsa_climax_test)| < 0.20** (Pearson, aynı pencere)
- **Jaccard overlap (gün+sembol) < 0.05** (trades aynı bar/sembolde örtüşmüyor)
- **Trade sayısı N ≥ 150** (istatistiksel taban)
**üretir."**

## 2. Null hipotez (H0)

H0: Mat Hold 4H aday kol, yukarıdaki 7 metriğin **en az birinde** hedefi yakalayamaz; özellikle (a) |ρ| ≥ 0.20 (diversifier değil) **veya** (b) net monthly ≤ 0% (edge yok) **veya** (c) Bonferroni-düzeltilmiş p ≥ 0.05 (rastgele ile ayrılmıyor).

H0 reddedilemezse → hipotez **RED**, "Bulkowski-rank-zorla-diversifier" anti-pattern olarak `learning.md`'ye yazılır.

## 3. Gerekçe — RAG referansları

- **[Bulkowski candlestick stats, RAG#10]**: Mat Hold bullish continuation rate **%74**, average move **+6.1%**, rank **10/103**. Hisse senedi günlük verisi tabanı; kripto 4H'da continuation rate'in **%55–62** bandında olmasını bekliyorum (asset-class shrinkage); bu bile %50 baseline'ın üzerinde.
- **[Kaufman, RAG#7 Donchian]**: 20-bar high/low breakout %35 WR ile pozitif beklenti çünkü **asimetrik R-multiple** (3–5R winners vs 1R losers). Mat Hold da fixed 2R + trend filter ile aynı asimetrik yapıyı taklit ediyor; düşük WR + büyük winner mantığı transfer edilebilir.
- **[Market Structure, RAG#6]**: BOS close-based n=3 → crypto'da "Yüksek mekanik çalışabilirlik". Mat Hold'un Bar5 breakout'u zaten close-based n=4 (4-bar consolidation üstüne BOS); aynı sınıf.
- **[Lopez de Prado, RAG#1]**: **DSR < 0.5, PBO > 0.5, IS Sharpe > 3·OOS Sharpe, param/N > 1/30** kırmızı bayrak. Bu hipotez tek tepe parametre seti ile pre-register edilir — Optuna sweep YASAK; SOP-3 robustness suite zorunlu.
- **[Chan, RAG#9]**: Yeni stratejiler portföye OOS Sharpe > 0.8 eşiğini geçmeli — bu rakam diversifier hedefimle uyumlu.

**Yapısal argüman (RAG-ötesi)**: vsa_climax_test volume z-score + reversal-bias arar; Mat Hold trend-continuation arar. İki kol aynı bar'da aynı sembolde TETİKLENEMEZ — vsa exhaust gördüğü yerde mat hold trend-pullback değil, climax görür ve almaz. Korelasyonun yapısal olarak düşük olması beklenir; ampirik doğrulama gate'in birincil amacı.

## 4. Dependent variables (pre-registered metric set, sıralı)

1. **ρ_pearson** = Pearson(daily_net_return_mathold, daily_net_return_vsa_climax_test) — **PRIMARY**: |ρ| < 0.20.
2. **net_monthly_return** (ay-bağımsız taze-$10k tabanı) > +3.0%.
3. **OOS Sharpe** (4H annualized, sqrt(6×252)) > 0.80 Bonferroni sonrası, ham > 1.20.
4. **MaxDD** (mark-to-market equity, account-base; **zero-base cumulative PnL KULLANILMAZ** — `learning.md` "MaxDD %43 inflation" dersi).
5. **Profit factor** > 1.40.
6. **Jaccard overlap** (set: (gün, sembol) çiftleri) < 0.05.
7. **Trade count N** ≥ 150 (param/N ≤ 4/150 ≈ 1/37 — Lopez 1/30 sınırının altında, marjin dar).

## 5. Independent variables — **FROZEN**, sweep YASAK

| Param | Değer | Kaynak | Sweep? |
|---|---|---|---|
| timeframe | 4H | seed seçimi | ❌ |
| HTF trend filter | 1D close > EMA(50) | klasik | ❌ |
| pattern: Bar1 | bullish, body ≥ 0.6 × range | Bulkowski standart | ❌ |
| pattern: Bar2–4 | tamamen Bar1 range içinde (high≤Bar1.H, low≥Bar1.L), en az 1 bar bearish close | Bulkowski klasik tanım | ❌ |
| pattern: Bar5 | bullish, close > Bar1.high | Bulkowski breakout | ❌ |
| entry | Bar5 close fill | klasik | ❌ |
| SL | entry − 1.5 × ATR(14) | RAG#7 Kaufman standardı | ❌ |
| TP | entry + 3.0 × ATR(14) (fixed 2R) | asimetrik R | ❌ |
| risk | %1 / trade, sabit-fraksiyon | Lab standard | ❌ |
| universe | pool_19sym (Lab dondurulmuş liste) | Lab freeze | ❌ |
| fees | 7.5bps taker | bot standard | ❌ |
| slippage | 5bps | bot standard | ❌ |
| max concurrent | 4 | risk-cap | ❌ |
| direction | long-only | continuation hipotezi sadece bullish | ❌ |

**Sweep yapmama gerekçesi**: param/N taban risk altında (RAG#1). Bir tek parametre bile sweep edilirse Bonferroni çarpanı 15→30 kategorisine geçer, OOS Sharpe gate'i aşılamaz.

## 6. Beklenen p-value ve istatistiksel düzeltmeler

- **Shuffle baseline** (returns shuffle, 5000 perm): p < **0.01**.
- **Bonferroni**: aile büyüklüğü n=15 (raftan denenen son 15 hipotez), düzeltilmiş α = 0.05/15 = **0.0033**.
- **Benjamini-Hochberg FDR**: q < 0.10.
- **DSR (Bailey-Lopez)**: > **0.50** (RAG#1 kırmızı çizgisi).
- **PBO**: < **0.40**.
- **Lookahead-delay test** (entry +1 bar geciktir): edge ≥ **%80 korunmalı** (timing-leak yok ⇒ yapısal edge).

## 7. Stop criteria — hipotezi TERK ETME koşulları

Aşağıdakilerin **en az biri** doğruysa: kod yazma/çalıştırma durur, hipotez REJECT olarak arşivlenir.

- IS Sharpe < 0.5 (4H, 2022-2023 in-sample).
- N < 150 trade tüm evrende (statistical underpowered).
- IS Sharpe / OOS Sharpe > 3.0 (RAG#1 — overfit imzası).
- **|ρ(mathold, vsa_climax_test)| > 0.40** ⇒ diversifier teorisi çürür; ROI iyi olsa bile portföye eklenmez.
- Bull rejim hariç (bear + range) toplam P&L < 0 ⇒ "sadece bull" edge — kabul ama portföy ağırlığı **maks %5** öneri.
- Walk-forward 12 dilimden ≥ 5 dilim negatif ⇒ regime-fragile.
- Shuffle baseline p > 0.05 ⇒ null model yenilemiyor.
- 2022-05 LUNA / 2022-11 FTX / 2024-08 Yen carry stress dilimlerinden **birinde** -20%'den derin DD ⇒ stress-fragile.

## 8. Curve-fit kırmızı bayrak ön-listesi

| Risk | Mitigation |
|---|---|
| Bar2–4 "Bar1 range içinde" tanımı esnek → "0.7×range" gibi parametre sızması | Klasik Bulkowski sınırı (high ≤ Bar1.H VE low ≥ Bar1.L) zorlanır, gevşetilmez |
| ATR multiplier (1.5/3.0) yerine 1.0/2.0 veya 2.0/4.0 denenirse | Pre-reg ihlali; reject. Standart Kaufman/Bulkowski set kullanılır |
| Universe cherry-pick | pool_19sym Lab freeze; symbol-out CV ile kontrol |
| Bull-only pattern, evrenin %70'i 2024 bull rally → IS-OOS şişme | Stress dilim split ZORUNLU (2022 bear) |
| N marjı dar (150 ≈ 4/N ≤ 1/30 sınırı) | Param/N raporda explicit yazılır; N < 200 ise confidence "low" |
| Multiple-testing family inflation (66 raf stratejisi) | Bonferroni n=15 zaten konservatif; family-wide raf-test FDR ayrı raporlanır |

## 9. Beklenen sonuç (honest prior — calibration için)

Önceden tahmin (kayıt için, post-hoc rationalization önlemi):

- **Trade sayısı**: 4 yıl × 19 sembol × 5800 bar (4H) × Mat Hold frekansı (~1/450) ≈ **245 trade** — N gate marjlı geçer.
- **Continuation rate (cripto 4H asset shrinkage)**: %55–62 bandı.
- **WR / R-multiple**: %38–45 WR, ortalama winner +2R, ortalama loser -1R ⇒ expectancy ≈ 0.3–0.5 R/trade.
- **Net monthly**: **+1.5% ile +3.5%** bandı bekliyorum — gate sınırda.
- **Sharpe OOS**: 0.8–1.3 bandı.
- **MaxDD**: 18–28% bandı — gate sınırda.
- **ρ(vsa)**: 0.05–0.18 bandı (yapısal argüman güçlü).
- **En büyük risk**: 2022 bear dilimi — long-only continuation pattern bear'da sessiz, P&L flat olabilir; sorun değil **ama** "tüm edge 2024-25 bull'undan" çıkarsa gate FAIL.

**P(hipotez geçer ve diversifier onaylanır)** ≈ %25–35. **Realistik** — RAG taban güçlü ama N marjlı, asset-class shrinkage gerçek, bull-bias gerçek.

## 10. Plan — sıralı adımlar

1. **Pre-reg COMMIT** (bu dosya, immutable hash). **Bu noktadan sonra parametre değişmez.**
2. `scripts/research/mathold_4h_backtest.py` yaz: vectorized, lookahead-test'li.
3. Pool 19-sym × 2022-01..2026-06 1 koşu.
4. Lookahead-delay test (+1 bar) — kanıt şart.
5. Daily return serisini `data/strategies/mathold_4h_daily_returns.parquet` olarak çıkar.
6. vsa_climax_test daily return ile Pearson ρ + Jaccard hesapla.
7. SOP-3 robustness suite **TAMAMI**: walk-forward 12 dilim, param-perturb (ATR'leri ±%10 sadece **post-hoc sanity**, kabul/red için değil), symbol-out CV, regime split, 4 stress dilim, shuffle baseline 5000 perm, Bonferroni n=15, DSR.
8. Karar: 7 gate hepsi PASS → Lab tournament aday. Bir tane FAIL → REJECT + learning.md kaydı.

## 11. Reproducibility

- git: TBD (commit sonrası eklenir)
- config_hash: bu MD'nin sha256'sı
- data: pool_19sym v11 snapshot (Lab dondurulmuş)
- code path: `scripts/research/mathold_4h_backtest.py` (henüz yok)

---

**STATUS: DRAFT — pre-registration. Kod yazılmadan önce frontmatter PROPOSED'a alınacak ve `inbox.jsonl`'e lab_scientist + risk_officer + adversary_engineer review'ı için kayıt düşülecek.**
