---
type: hypothesis
hypothesis_id: HYP-REGIME-004
status: pre-registered
date: 2026-05-12
researcher: researcher_agent
related_strategy: TOP_10_OVERLAY
parent_benchmark: v0.9.2 production (yearly +57%, DD -65%)
overlay_type: correlation_risk_filter
---

# HYP-REGIME-004 — Cross-Asset Correlation Cluster Throttle (Correlated DD Suppressor)

## Iddia (pre-registered)

> Sub-Nis 2026 DD analizinin en kritik bulgusu: **aynı yön + aynı gün ≥ 3 simultan kayıp** olayları. (2026-04-21'de BTC+ETH+BNB+XRP short, 2026-02-16'da ETH+DOT short, 2025-08-15'de SOL+BNB+LINK short.) Bunların hepsi aslında **tek bir bet'in 3-4 kopyası** — sistem bunları bağımsız iddia gibi davranıyor.
>
> Hipotez: Sinyal-aday zamanında, **aktif open positions + son 3-gün entry'ler** ile yeni sinyalin **30-gün return correlation matrix**'ine bakılır. Korelasyon kümesi tespit edildiğinde yeni pozisyon ya **bloklanır** ya da **küçültülür**.
>
> Tanımlar:
>
> - **Cluster:** Aynı side'da olup 30-gün getiri korelasyonu ≥ 0.70 olan sembol grubu.
> - **Cluster Exposure Cap:** Bir cluster'da en fazla 2 aktif pozisyon.
> - **3rd Signal in Same Cluster + Same Side + ≤ 2 gün arayla:** half-risk veya block.
>
> Mevcut v0.9.2 production'a OVERLAY:
>
> - **Yıllık ROI:** mevcut +%57 → hedef ≥ +%52 (max %10 ROI kaybı — bu hipotez DD odaklı, ROI'ye az dokunmalı).
> - **Max DD:** mevcut ort. −%65 → hedef ort. **−%50 ile −%55** (en az **−12 pp DD reduction**).
> - **Multi-loss günleri** (2025-08-15, 2026-02-16, 2026-04-13, 2026-04-21): tek-gün max kayıp $-2.3K → ≤ $-1.2K.

## Mekanik Kurallar (kod-edilebilir)

```python
def correlation_throttle(
    candidate_trade,
    open_positions: list,         # aktif open trade'ler
    recent_entries: list,         # son 3 gun entry'ler (closed dahil)
    corr_matrix: pd.DataFrame,    # 30-gun rolling Pearson, gunluk update
) -> tuple[str, float]:
    """Returns (action, risk_multiplier)."""
    sym = candidate_trade.symbol
    side = candidate_trade.side
    # Aday ile her aktif/recent same-side pozisyonun korelasyonunu cek
    cluster_members = []
    for pos in open_positions + recent_entries:
        if pos.side != side: continue
        if pos.symbol == sym: continue
        rho = corr_matrix.loc[sym, pos.symbol] if pos.symbol in corr_matrix.columns else 0
        if rho >= 0.70:
            cluster_members.append((pos.symbol, rho))
    n = len(cluster_members)
    if n == 0:
        return ("PASS", 1.0)
    if n == 1:
        return ("PASS", 1.0)            # 2nd in cluster: full
    if n == 2:
        return ("PASS", 0.5)            # 3rd in cluster: half
    return ("SKIP", 0.0)                # 4th+ in cluster: block
```

Pratikte:

- **2026-04-21**: BTC short → PASS; ETH short (corr ~0.85 ile BTC) → PASS (2nd); BNB short → half-risk (3rd); XRP short → SKIP (4th). Beklenen kurtarma: 1 trade tamamen blok + 1 trade half = ~$-1.6K → $-0.6K.
- **2026-02-16**: ETH short → PASS; DOT short → PASS (2nd in cluster). Bu durum 2 cluster member → hala full risk; bu hipotez tek başına bu günü kurtarmaz. (HYP-REGIME-001 chop filter onu kurtarır.)

## Bağlam Filtresi

| Cluster Üye Sayısı (active+recent, same side, rho≥0.70) | Aksiyon |
|---|---|
| 0 | PASS — full risk (default v0.9.2) |
| 1 | PASS — full risk (allowed 2 pos in cluster) |
| 2 | PASS — half risk (3rd entry conservative) |
| ≥ 3 | SKIP — bloklanır |

**Önemli:** Symbol-level concentration cap (v0.9.2'de `max_notional_pct=0.3`) zaten ayakta — bu hipotez **cluster-level** ek katman ekliyor, mevcut cap'i değiştirmiyor.

## Literatür / Referanslar

- **Markowitz (1952)**: Portfolio variance = Σ wᵢwⱼσᵢσⱼρᵢⱼ. Yüksek korelasyon → diversification fail.
- **Lopez de Prado (2018, "Advances in Financial ML", Ch. 14)**: "Risk Budgeting via Asset Clustering" — korelasyon matrisinden hierarchical clustering ile risk-bütçesi dağıt.
- **Crypto-specific (Glassnode 2022)**: BTC-alt 30-gün getiri korelasyonları stress dönemlerde 0.80-0.95'e fırlıyor ("everything correlates in crisis").
- **Internal known-how**: `scripts/v091_loss_analysis.py` zaten bulguyu netleştirdi: same-day multi-loss = en büyük tek DD katkı kaynağı. Bu hipotez o bulguyu **proaktif önlemeye** çeviriyor.
- **Antonacci (2012, Dual Momentum)**: Cross-asset momentum + low correlation = robust portfolio. Tersini blokluyoruz: yüksek correlation = blok.

## Bağımlı Değişkenler

- annualized_net_return
- max_drawdown (ortalama + worst pencere)
- **single-day max loss** (yeni metric — bu hipotez doğrudan etkiler)
- **multi-symbol same-side same-day frequency** (count) → bu sayı azalmalı
- profit factor
- avg_concurrent_positions
- skip_rate, half_risk_rate

## Bağımsız Değişkenler

- Cluster correlation threshold: {0.65, 0.70, 0.75} — 3 değer
- Cluster size cap: {2-allowed-then-half, 3-allowed-then-half} — 2 değer
- Recent entry lookback: {2 gün, 3 gün, 5 gün} — 3 değer
- Correlation matrix lookback: {30, 60} bar — 2 değer

**Toplam: 3×2×3×2 = 36. Stage-gated:**

1. **Stage 1 (pre-reg default):** {0.70, "2-allowed", 3 gün, 30 bar} — tek konfig.
2. **Stage 2 (robustness sweep):** Perturbation sadece.

## Beklenen p-value

- Stage 1: p < 0.05.
- Permutation test: trade'leri zaman içinde random reshuffle et (cluster yapısı korunmadan); gerçek DD reduction ≥ %95.

## Stop Criteria

- 3y rolling DD reduction < 8 pp → red.
- ROI kaybı > %10 → red (bu hipotez ROI'ye en az dokunmalı).
- Multi-loss gün frekansı azalmadıysa → red.
- Skip rate > %25 → red (overly restrictive, lost too many trades).

## Hangi 3y Rolling Pencerelerinde Etki Beklenir

| Pencere | Multi-loss Gün Yoğunluğu | Beklenen Etki |
|---|---|---|
| 2021-05 (initial bear) | Yüksek (alts collapse beraber) | Büyük etki |
| 2022-01 (LUNA → bear) | Çok yüksek (correlation spike) | Maksimum etki ⭐ |
| 2022-11 (FTX) | Yüksek | Büyük etki |
| 2023-05 (steady bull) | Orta | Orta etki |
| **2025-08-2026-04** | **Yüksek (chop + reversal cluster)** | **Hedef pencere** |

## Walk-Forward Gate'leri

1. **3y/6m walk, 12 dilim:** ≥ 8 dilimde DD daralması; ≥ 10 dilimde single-day max loss düşmesi.
2. **Multi-loss event audit:** 2025-08-15, 2026-02-16, 2026-04-13, 2026-04-21 — bu 4 gün ayrı ayrı raporlanmalı; en az 3'ünde iyileşme.
3. **Correlation matrix stability:** 30-gün rolling matrisin stabilitesini test et (consecutive matris korelasyonu ≥ 0.6) — aksi takdirde matris gürültülü ve filtre overreact.
4. **Symbol-out CV:** 11 sembol; sembol çıkartınca cluster yapısı stabil mi?
5. **Look-ahead bias zorunlu test:** Correlation matrisi mutlaka **t-1 bar kapanışına kadar** verilerle hesaplanmalı. Random spot-check ile doğrulanmalı.

## Apply-On-Top Mantığı

```
corr_matrix_daily = compute_rolling_corr(11_symbols, lookback=30)  # gunluk
gather_top10_signals() -> trades
sort by entry_ts
active_positions = []
recent_entries_3d = deque()
for trade in trades:
    cleanup_expired(active_positions, recent_entries_3d, trade.entry_ts)
    action, mult = correlation_throttle(
        trade, active_positions, list(recent_entries_3d),
        corr_matrix_daily[trade.entry_ts.date()]
    )
    if action == "SKIP": continue
    trade.risk_pct *= mult
    active_positions.append(trade)
    recent_entries_3d.append(trade)
    execute(trade)
```

## Reproducibility

- git_hash: `<filled-on-run>`
- config_hash: `stable_hash(v0.9.2 + corr_overlay_v001.yaml)`
- data_hash: `stable_hash(11_symbols_5y + 30bar_rolling_corr_matrix)`

## Sonuçlar (boş — backtest sonrası doldurulacak)

- [ ] In-sample 3y rolling
- [ ] Single-day max loss before/after
- [ ] Multi-loss event-by-event (audit table)
- [ ] Skip + half-risk rates
- [ ] Correlation matrix stability test
- [ ] Lookahead bias spot-check sonuc
- [ ] Karar: terfi / red

## Notlar

- **HYP-REGIME-001, 002, 003 ile farkı:** 001 (chop) ve 002 (vol) **lokal pasif filter**; 003 (BTC.D) **cross-asset directional bias**; bu hipotez (004) **portfolio-level correlation cap**. Dördü ortogonal — tam takım test edilmeli.
- **v0.9.2 mevcut `max_same_side_concurrent`** parametresi (Defensive preset'te 4) yön bazlı genel cap; bu hipotez korelasyon-koşullu daha akıllı: 4 pozisyon ama hepsi farklı cluster → sorun yok; 3 pozisyon ama hepsi 1 cluster → 3.'sü half.
- **Mevcut concentration cap (per-symbol %20)** ile çakışmaz: per-symbol = tek sembol max; cluster = sembol-grup. İki katmanlı korunma.
- **Implementation kritik:** Correlation matrix backtest replay'inde **point-in-time** hesaplanmalı; "tüm 5y'in matrisini hesaplayıp gerçek-zamanlı sanmak" klasik look-ahead bias. Walk-forward sırasında her bar için ayrı matris.
- **Edge case:** Yeni listelenmiş semboller için 30-bar histori yoksa: o sembol için korelasyon = NaN → cluster'a dahil edilmez (conservative).
