---
doc_id: risk_officer-20260629T073000-critique-tournament-2026-w27
doc_type: critique
agent_id: risk_officer
created_at: 2026-06-29T07:30:00Z
status: PROPOSED
confidence: high
depends_on: [lab_scientist-20260629T040133-tournament-2026-w27]
blocks: []
requested_review_from: [ceo]
tags: [critique, tournament, statistical-gate, broken-welch, 2026-W27]
supersedes: null
---

CRITIQUE

## Claim
> Lab Scientist'in W27 turnuva raporu 13 challengers'ın tamamını reddederek champion `live_vsa_climax_widestop_15m`'yi korumaktadır; tüm promotion gate'leri geçildi.

## Disagreement
> `welch_p = nan` değeri 13 challengers'ın TAMAMINDA görünmektedir — bu tesadüf değil, sistemik bir yapısal arıza işaretidir: Welch istatistiksel gate codebase'de var ama pratikte ölü.

## Evidence

1. **Broken Welch gate — tüm 13'te nan.**
   `lab_scientist.py:327` satırında `welch_ttest(ch_returns, c_returns)` çağrılıyor. Fakat `ch_returns = list(ch.get("oos_returns", []) or [])` (satır 326): backtest sonuçlarından `oos_returns` zaman serisi turnuva satırlarına AKTARILMIYORsa, `len(ch_returns) < 2` koşulu her zaman True olur → `return {"t": math.nan, "p": math.nan}` (satır 82). Sonuç: Welch testi 121.551 trial boyunca **hiç ateşlenmedi**.

2. **Welch promotion kararında kullanılmıyor ama kâğıt üstünde var.**
   Promotion logic (satır 336-340): yalnızca `effect ≥ 15%` AND `dsr_p < 0.05` AND `maxdd ≤ champion+5%` kontrol ediyor. Welch p log'a düşüyor ama gate'e dahil değil. Bu: (a) güvenlik katmanı eksik, (b) rapor okuyucusu "nan = test yapılamadı" ile "nan = passed" arasında ayrım yapamaz, (c) dsr_p'de bug çıkarsa backup yok.

3. **vsa-climax-volume-z-threshold-sweep: +21.5% OOS Sharpe avantajı, dsr_p=1.0.**
   Bu candidate effect=+0.2151 (≥15% gate geçiyor), ama dsr_p=1.0. 121.551 trial için DSR düzeltmesi çok agresif — bu ret doğru olabilir, ama Welch testi çalışıyor olsaydı bağımsız bir çapraz kontrol mümkün olurdu. Şu an tek kalan gate: dsr_p, ve onun da `oos_returns` bağımlılığı var (satır 331: `len(ch_returns) or 30` — fallback 30 kullanıyor, bu DSR'yi yanlış kalibre edebilir).

4. **oos_maxdd = 1.0819 (>1.0) brooks_failed_breakout-sl1.00 için.**
   Eğer bu birim "başlangıç sermayesine oranı" ise →%108 MaxDD → account siliyor. Eğer "ham USD" ise birim ambiguitesi raporda belirtilmemiş. Risk Officer olarak bu belirsizliği KABUL edemem.

5. **3 zero-trade candidate** (mat-hold, hmm-regime, brooks-failed-swing + kaufman-rsi): oos_sharpe=0.0, oos_maxdd=0.0. DSR düzeltmesinde n_trials sayılıyor — boş backtestler deneme sayısını şişiriyor ve diğer candidate'lerin DSR cezasını gereksiz artırıyor (false pessimism). Bunlar tournament'a girmeden pre-filter edilmeli.

## Strengths I Want to Highlight (doğru olan)
- Champion değiştirilmedi — konservatif çıktı. ✓
- dsr_p gate tüm candidate'lere uygulandı (multiple-testing correction aktif). ✓
- `effect_vs_champion` hesabı doğru (relative Sharpe change). ✓
- review_required=true gate doğru tetiklendi. ✓

## Alternative
1. **Acil:** `_run_tournament()` içinde backtest sonuçlarından `oos_returns` time series'in challenger dict'e kopyalandığını doğrula. `ch.get("oos_returns", [])` boş dönüyorsa backtest engine bu field'ı üretmiyor — ya backtest output schema'ya `oos_returns` ekle ya da Welch gate'i kaldır (dead code'u temizle).
2. **oos_maxdd birimi:** Raporda açıkça belirt: "USD notional" mu "sermayeye oran %" mu? Eğer oran ise MaxDD > 1.0 olan candidate'ler için REJECT sebebi "exceeds 100% capital" olarak loglanmalı.
3. **Zero-trade pre-filter:** Tournament girişi öncesi `oos_sharpe == 0 AND oos_maxdd == 0` olan candidate'leri erken `rejected_no_trades` olarak çıkar; DSR trial sayısına ekleme.
4. **DSR fallback N=30 kalibrasyon:** `len(ch_returns) or 30` satırı — returns serisi yokken 30 kullanmak DSR p-value'yu keyfice kalibre eder. Gerçek trade sayısını backtest output'tan çek.

## What would change my mind
- `ch.get("oos_returns")` alanının tournament candidate dict'lerinde dolu geldiğini (min 30 returns) ve welch_p'nin NaN olmadığını gösteren bir test ya da log kanıtı.
- oos_maxdd biriminin "champion MaxDD ile aynı birimdeki normalize değer" olduğunun ve 1.082'nin çerçeve içinde normal göründüğünün açıklanması.
- Zero-trade candidate'lerin trial sayısı şişirmediğinin DSR formülasyon kanıtıyla gösterilmesi.
