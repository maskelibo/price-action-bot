---
doc_id: researcher-20260611T093000-kaufman-volbreak-1h-vsa-diversifier
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-11T09:30:00Z
status: DRAFT
confidence: med
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, cross_strategy_diversifier, volatility_breakout, kaufman, vsa_orthogonal, pre_registration]
supersedes: null
hash: null
---

# Hipotez: Kaufman Volatility Breakout (Open + k·ATR) — vsa_climax_test Diversifier (1H)

## 0. Bağlam & Motivasyon

Aktif `vsa_climax_test` stratejisi **hacim-tabanlı climax/wide-range** sinyali kullanıyor → tek "edge tipi" üzerinden risk alıyoruz. RAG corpus'unda **strafştırma için yapısal olarak ortogonal** ve **mekanik tanımı net** aday: **Kaufman volatility breakout** ([#5 book_kaufman_summary]). Bu sistem:

- Hacim KULLANMAZ — sadece `ATR(14)` ve `Open` üstünden tetiklenir.
- "Bar exhaustion / climax" değil, **momentum-continuation** mantığı (yapısal olarak VSA-climax'in TERSİ — climax = mean-reversion potansiyeli, breakout = trend-continuation).
- Hipotez sahibi (bu doc) RAG'den TEK referans aldı (k=8); benzer sweep ile diğer denenmiş kandiyatlardan (mat-hold, donchian, ma-crossover, marubozu, vsa-volz) **ayrı bir mekanik aile**.

## 1. İddia (pre-registered — DEĞİŞTİRİLEMEZ)

> 1H timeframe'de, **19-sembol USDT-perpetual havuzunda** (build_pool_19sym), 2023-01-01 → 2026-06-01 (3.42 yıl) penceresinde, aşağıdaki sabit kurallarla:
>
> - **Setup:** Önceki 1H bar'ın close'unda `ATR(14) > 1.2 × rolling_median(ATR(14), 100)` (yüksek-vol rejim filtresi).
> - **Entry (long):** Bar `t` içinde fiyat `Open[t] + 0.6 × ATR(14)[t-1]` üstüne çıkarsa → o seviyede **stop-market long**.
> - **Entry (short):** Bar `t` içinde fiyat `Open[t] − 0.6 × ATR(14)[t-1]` altına inerse → stop-market short.
> - **SL:** entry ∓ 1.5 × `ATR(14)[t-1]`.
> - **TP:** 2R fixed (asimetrik; `Open ± k·ATR` literatürünün "küçük R ile yüksek WR" karakterini koruyoruz).
> - **Time exit:** entry barı + 8 bar (8 saat) içinde TP/SL yoksa close.
> - **Trade budget:** Sembol başına 1 entry / 24h.
> - **Risk:** %1 equity / trade, taker fee 7.5 bps, slippage 5 bps (konservatif).
>
> aşağıdaki metrikler aynı anda sağlanır:
>
> | Metrik | Eşik | Yön |
> |---|---|---|
> | Net annual return | > **%35** | fee+slip dahil |
> | OOS Sharpe (walk-forward) | > **1.0** | annualized, 252×24 |
> | MaxDD | < **%25** | account-equity bazlı (lesson: zero-base değil) |
> | Profit factor | > **1.3** | gross |
> | Trade count | > **250** | 3.42y toplam |
> | Win rate | **%50–%60** | Kaufman teorik %55'e tutarlı |
> | **Pearson(daily_ret_strategy, daily_ret_vsa_climax_test)** | < **0.30** | **sine qua non — diversifier amacı bu** |
> | DSR (Lopez) | > **0.5** | multiple-testing düzeltmesinden sonra |
> | PBO (combinatorial WF) | < **0.5** | curve-fit testi |

**Null hipotez (H₀):** Yukarıdaki kurallar shuffle-returns baseline'ından istatistiksel olarak ayırt edilemez (p ≥ 0.05) **VEYA** korelasyon ≥ 0.30 (yani diversifier değil, sadece aynı edge'in başka kılığı).

## 2. Gerekçe (RAG referansları + mekanik)

1. **[#5 book_kaufman_summary §Volatility Breakout]** — "Open ± k·ATR, k tipik 0.5–1.0, yüksek WR (~%55) küçük R ile; intraday momentum capture; düşük volatilite günlerinde tetiklenmez (zaten istenen)." Bu, **mekanik olarak ortogonal** bir aile (Open-relative breakout) ve vsa-climax'in volume-burst mantığından **ayrı bir tetik koşulu**.
2. **[#1 book_lopez_summary]** — `DSR < 0.5`, `PBO > 0.5`, `IS Sharpe > 3·OOS Sharpe` herhangi birisi production-block; pre-reg metriklerimi bu gates'e göre kalibre ediyorum.
3. **[#7 book_kaufman_summary §Channel Breakout 20/55]** — kanal-bazlı breakout'ların "choppy/range-bound rejimde back-to-back whipsaw" karakteri → bu nedenle rejim filtresi **zorunlu** (ATR > 1.2 × rolling_median).
4. **[#2 book_candlestick_statistics §Inside Bar]** ve **[#10 §Mat Hold]** — bunlar denenmiş kandiyatlar; mekaniği zaten *consolidation breakout* türü → bizim hipotezimiz `Open + k·ATR` ile **bar-içi intraday** breakout → farklı tetik penceresi, **portföy düzeyinde ayrı edge**.

**VSA-climax ile orthogonal mekaniği — argüman:**
- vsa_climax_test → "barlar uç hacim + dar range" → climax/exhaustion → mean-reversion eğilimi.
- Bu hipotez → "bar Open'ın 0.6 ATR üstüne kırılma" → continuation/momentum.
- Mantıksal olarak: climax bir bar'da gerçekleşmişse continuation sinyali aynı barda **zayıf** olur (overextension). Yani sinyal-zaman örtüşmesi düşük → düşük korelasyon hipotezimiz makul.

## 3. Dependent Variables (ölçeceğimiz)

- `net_annual_return_pct` (fee+slip dahil)
- `sharpe_oos` (walk-forward 4-split ortalaması, NaN-safe annualizer = 252×24)
- `max_drawdown_pct` (equity-base; NOT zero-base — lesson 2026-05-22)
- `profit_factor` = sum(wins) / abs(sum(losses))
- `trade_count`
- `win_rate`
- `avg_R`
- `pearson_corr_with_vsa_climax_test` (daily returns, 3y window)
- `DSR` (Lopez deflated Sharpe), `PBO` (combinatorial walk-forward)

## 4. Independent Variables (SABIT — sweep YOK)

> Curve-fit önleme amacıyla **TEK SET parametre**, pre-reg'de kilitleniyor. Sweep yapılırsa hipotez iptal edilir, yeni doc açılır.

| Param | Değer | Kaynak |
|---|---|---|
| Timeframe | 1H | Kaufman intraday; 15m gürültü, 1d trade-count yetersiz |
| `k` (ATR mult, entry) | 0.6 | [#5] aralığı 0.5–1.0; orta-konservatif |
| `atr_lookback` | 14 | endüstri standart |
| Rejim filtresi: `ATR > c × median(ATR, 100)` | c=1.2, 100 bar | [#5] "düşük-vol günlerde tetiklenmez" → ayrıca CV'de yüksek-vol-only |
| SL ATR-mult | 1.5 | [#5] doğrudan |
| TP | 2R fixed | [#5] "2×ATR target" eşdeğeri (entry-relative) |
| Time exit | 8 bar | konservatif; data-driven değil |
| Risk/trade | 1% equity | desk policy |
| Fee/slippage | 7.5 bps taker + 5 bps slip | [shared/facts/exchange_behaviors] |
| Universe | 19-sym pool | `scripts/research/build_pool_19sym.py` |

## 5. Beklenen p-value & istatistiksel gates

- **Shuffle-baseline test:** Returns'leri (per-symbol, per-day) shuffle → null modeli kur. Hipotez Sharpe'ı null dağılımın **üst %5'inde** olmalı → p < 0.05.
- **Multiple testing düzeltmesi:** TEK set parametre denendiği için Bonferroni m=1 → ham p kullanılır. **Eğer ileride sweep yapılırsa** (örn. k ∈ {0.4, 0.5, 0.6, 0.7, 0.8} → m=5) düzeltilmiş p = 5·p_ham hesaplanır; düzeltme sonrası p ≥ 0.05 ise hipotez reddedilir.
- **DSR (Lopez):** OOS Sharpe'ı non-Gaussian return distribution + multiple-trial inflation için defleder. `DSR > 0.5` zorunlu (Lopez kriterleri #1).
- **PBO:** combinatorial walk-forward (8 dilim, 4 train / 4 test kombinasyonları). `PBO < 0.5` zorunlu (Lopez kriterleri #2).

## 6. Stop Criteria (early kill — pre-reg)

| Tetik | Aksiyon |
|---|---|
| In-sample Sharpe < 0.5 | **Araştırma terkedilir**, seed_abort_log'a yaz |
| IS/OOS Sharpe gap > %50 (IS Sharpe > 2·OOS Sharpe) | Reject (Lopez #4) |
| Korelasyon vsa_climax_test ile ≥ 0.30 | Reject — diversifier amacı yok, raftaki diğer kandiyatlara dön |
| Trade count < 150 / 3.42y | Reject — istatistik anlamsız |
| PBO ≥ 0.5 | Reject (Lopez #2) |
| DSR ≤ 0.5 | Reject (Lopez #1) |
| MaxDD > %35 | Reject (champion DD'sinin 1.5x üzerinde — risk_officer politikası) |
| Tek 1-haftalık dilim toplam P&L'ın > %40'ını taşıyor | Reject (overfit kırmızı bayrak [#1 + learning.md]) |

## 7. Curve-fit Şüphe Bayrakları (kendime not — denetim için)

Bu hipotezi yazarken **kendi kafamda** şu şüpheler var, raporlamada açık tutacağım:

1. **`k=0.6`, `c=1.2`, `time_exit=8` üçü birden** parametre — m=1 dediysem de **konseptin başında bilinçli 3 sayı seçtim**. Optuna ile sweep ettiğim ANDA m=3 olur → "Bonferroni m=3" hâlâ ucuz ama "ben ilk denemede en iyiyi denk getirdim" varsayımı kuşkulu. **Politika:** sweep yapmıyorum bu doc altında. Sweep gerekirse v2 doc açacağım, m'i resmi belirteceğim, p × m hesaplayacağım.
2. **Rejim filtresi (ATR > 1.2·median)** kendisi *post-hoc* bir filtre. Yüksek-vol-only seçmek, low-vol whipsaw'ları **ex-post** atıyor → çok kullanıcı dostu görünüm. Buna karşı: **filter-OFF baseline'ı da koşacağım** — eğer filter-OFF Sharpe ≈ filter-ON Sharpe ise filter "iş yapıyor", eğer filter-OFF çok kötü ve filter-ON parlak ise filter "veri sızıntısı" potansiyeli (yüksek-vol rejimini retrospektif seçmek edge'i yakalanmış olabilir; ATR(14) ve median(100) ile lookahead yok ama dağılım payına dikkat).
3. **2R fixed TP** asimetri yaratır ama Kaufman'ın orijinal sisteminde "bar/gün sonu close" exit'i de var. 2R tercihim → backtest engine'de basit; ama gerçekte "1R partial + 2R runner" daha gerçekçi. Bunu test etmiyorum bu doc altında — overfit yüzeyi açmamak için.
4. **19-sym pool** USDT-perpetual evrenle survivorship'siz mi? `build_pool_19sym.py` delisting'leri dahil ediyor mu? Backtest öncesi doğrulanmalı → check-list'e ekledim (madde 9).

## 8. Robustness Suite (zorunlu — SOP-3)

| Test | Eşik | Reject koşulu |
|---|---|---|
| Walk-forward (8 dilim, 4 IS / 4 OOS combinatorial) | OOS Sharpe ortalaması > 1.0 | aksi reject |
| In-sample/out-of-sample fark | Sharpe gap < %30 | Lopez #4 |
| Param perturbation: k ∈ [0.54, 0.66] ±10%, c ∈ [1.08, 1.32] ±10% — 50 seed | Ortalama Sharpe kaybı < %25 | aksi fragile |
| Symbol-out CV: her sembolü tek tek dışarıda bırak | Min OOS Sharpe > 0.6 | tek sembol sonucu taşımıyor olmalı |
| Regime split: bull (2023H1, 2024H1), bear (2022H2, 2024H2), range (2023H2 ve karışım) | En az **2 / 3** rejimde Sharpe > 0.5 | aksi reject |
| Stress periods: 2024-08 Yen carry, 2024-03 BTC ATH whipsaw, 2025-04 USDT depeg | Hiçbirinde tek-haftalık DD > %15 | aksi reject |
| Shuffle baseline (per-symbol per-day) | p < 0.05 | null'dan istatistiksel ayrılma |
| Multiple testing (Bonferroni m=1 başlangıçta) | Düzeltilmiş p < 0.05 | sweep yaparsam yeniden hesap |
| Korelasyon stabilitesi: 6-aylık rolling Pearson vs vsa_climax_test | Hiçbir 6-aylık pencerede ρ > 0.40 | aksi diversifier kararsız |

## 9. Pre-Backtest Check-List

- [ ] `build_pool_19sym.py` delisting dahil mi? (`data/universe.py` ile karşılaştır)
- [ ] `ATR(14)` ve `rolling_median(100)` causal mı? (`tests/test_lookahead.py` ile detector yeni eklendiğinde çalıştır)
- [ ] Backtest config'i `hash` ile dondur (reproducibility frontmatter)
- [ ] vsa_climax_test günlük return serisi hazır (3.42y, same universe)
- [ ] Fee + slip parametreleri `shared/facts/exchange_behaviors.md`'den çekilmiş
- [ ] Sharpe annualizer 1H için **252×24 = 6048** (CT-RES-01 / Sharpe annualization bug korunması)

## 10. Beklenti (önceden yazılı — sonra utanmamak için)

Bu hipotez büyük olasılıkla **REDDEDİLİR**, çünkü:

- Kripto 1H'de Open-relative breakout'lar **microstructure noise** (exchange-spread, taker-burst) altında istikrarsız olabilir.
- Rejim filtresi açık iken trade count **150'nin altına düşebilir** → istatistik anlamsız.
- Korelasyon vsa_climax_test ile **beklenenden yüksek** çıkabilir; çünkü her ikisi de "volatility regime'de aktifleşen" sistemler — VSA hacim eşiği yüksek-vol günlerinde, bu sistem ATR eşiği yüksek-vol günlerinde tetikleniyor → **gizli aynı rejim** seçilimi olabilir.

Reddedilirse `learning.md`'ye 3 satır gerekçe + `seed_abort_log.jsonl`'a kayıt → raftan bir sonraki orthogonal aday (Equal Highs/Lows Sweep / Donchian-ADX kombinasyonu / Wyckoff Spring 4H) denenir.

**Eğer geçerse (terfi adayı):** Lab tournament'a sunulur (challenger), 4-hafta paper shadow, sonra %0.5 risk_pct ile testnet → risk_officer review → CEO approval → live.

## 11. Reproducibility

- `git_hash`: (frontmatter `hash` alanına backtest sırasında doldurulacak)
- `config_hash`: backtest config dondurulduğunda hesaplanacak
- `data_hash`: 19-sym pool snapshot'ı bu doc commit edildiğinde dondurulur (`scripts/research/build_pool_19sym.py` çıktısı)

---

**Pre-registration tamam.** Kod yazımı backtest çalıştırması — bu commit'ten SONRA. Sonuç ne olursa olsun yukarıdaki metrikler aynen raporlanır; herhangi bir gate'in altını oymak için doc REVIZE edilmez, yeni `supersedes` doc açılır.
