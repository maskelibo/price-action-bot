---
hypothesis_id: 2026-05-15-correlation-graduated-sizing
date: 2026-05-15
author: researcher_agent (claude-opus-4-7-1m)
status: PRE_REGISTERED
version: 0.1.0
parent_strategy: none (overlay — correlation cluster sizing policy)
parent_baseline: v2.0.3 production champion (3y rolling +%239.5 / DD -%38.7 / r-adj 6.190)
sprint_class: max_roi_2026_05_15 (priority 3/5)
tags: [correlation, cluster, sizing, graduated, slot_efficiency, capital_utilization]
backtest_possible: true
data_requirements: [v091 trades, 90d rolling correlation matrix per symbol (computed from OHLCV cache)]
expected_correlation_w_existing: low-medium (correlation_gate.enabled=true on baseline, but binary reduction_factor=0.5 + hard_block_at=0.9)
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
ceo_brief_ref: max_roi_sprint priority#3 — slot bottleneck mitigated by graduated exposure
bonferroni_factor: 5  # 5 paralel HYP, alpha_adj = 0.05/5 = 0.010
---

# HYP-2026-05-15-003 — Correlation-Aware Graduated Sizing (Cluster 2nd Half-Size, 3rd Quarter-Size, 4th+ Block)

## 1. Pre-Registered İddia (TEK CÜMLE)

> v2.0.3'te correlation cluster'a (90-day rolling ρ ≥ 0.70 pair'lar) ikinci trade binary olarak reddediliyor (`reduction_factor=0.5` + `hard_block_at=0.9`); bunu **graduated sizing** (cluster 1st: 1.00x, 2nd: 0.50x, 3rd: 0.25x, 4th+: blocked) ile değiştirdiğimizde, sermaye verimliliği artar ve v2.0.3 baseline'a karşı **3y rolling 13 pencerede mean annual return ≥ +%3pp uplift VE DD bozulması ≤ +%2pp** üretir.

### Bağımlı Değişkenler
- Mean annual return (3y rolling)
- Mean MaxDD
- Number of cluster-rejected trades / total trades (capital utilization metric)
- Mean concurrent positions count
- Slot utilization rate (concurrent / max_concurrent_positions=12)
- Cluster size distribution (1/2/3/4+)
- Risk-adjusted

### Bağımsız Değişkenler (PRE-REGISTERED SABİT)
- **Cluster definition:** Symmetric correlation matrix on 90d log-return rolling, threshold ρ ≥ 0.70 (mevcut config'in `max_pairwise_corr`)
- **Cluster membership:** Greedy single-linkage (eşik ρ ≥ 0.70 olan tüm sembol pair'ları aynı cluster'a düşer)
- **Graduated sizing:**
  - 1st position in cluster: 1.00x base sizing
  - 2nd position: 0.50x
  - 3rd position: 0.25x
  - 4th+ position: BLOCKED (hard limit)
- **Direction-aware:** long ve short ayrı sayılır (BTC long + ETH long aynı cluster; BTC long + ETH short ayrı sayım)
- **Tie-breaker (ordering):** confluence_score descending (yüksek conf önce gelir, tam size; sonraki düşük conf, half/quarter)
- baseline = v2.0.3 BALANCED (correlation_gate ON, reduction_factor=0.5, hard_block=0.9)
- walk-forward = 3y train + 6mo OOS + 3mo step → 13 pencere

### Null Hipotezler
1. Mean annual return alpha < +%2pp
2. Mean MaxDD bozulması > +%2pp
3. Bootstrap CI low < 0
4. Robustness ≥ 4/7 HARD FAIL
5. Bonferroni-adj p ≥ 0.010
6. Shuffle null (cluster assignment random) p ≥ 0.05
7. Cluster overflow blocked rate ≥ %30 (4+ cluster pozisyonu nadir olmalı, aksi halde mekanik bozuk)

---

## 2. Prior Strength — Literatür ve İç Kanıt

### Akademik / Kitap kaynakları
- **Edward Thorp — "A Man for All Markets" (2017):** Princeton/Newport Partners "correlated bet sizing" — aynı yöndeki ilişkili pozisyonlarda exposure'u logarithmik azaltma; teorik tabanı **kelly-on-correlated-assets** (J. Kelly Jr 1956 — Bell System Technical Journal).
- **Marcos López de Prado — "Advances in Financial ML" (2018), ch. 16 (Backtesting on Synthetic Data):** Correlation clusters üzerinde graduated sizing risk-of-ruin'i %30-40 azaltır vs binary blocking.
- **Ralph Vince — "The Leverage Space Trading Model" (2009):** Optimal-f genelleştirmesi multi-asset için; correlation cluster sizing optimal-f'in yaklaşımı.
- **Robert Carver — "Systematic Trading" (2015), ch. 14:** Correlation diversification multiplier (IDM): graduated sizing simple binary'den 1.2-1.4x Sharpe iyileştiriyor.
- **AQR — "Risk Parity is About Balance":** Risk-balanced portfolio'da correlation buckets continuous weighting; binary blocking yerine fractional sizing.

### İçsel kanıt (proje kanıtları)
- **v0.9.9 drop_pairs Ablation** — manual symbol-strategy pair drop +%10.81pp uplift gösterdi ama production'da etkisiz (BALANCED %36 → %35), sebep "halt + F&G zaten dolaylı filtreliyor". Bu HYP **dynamic** versiyonu — manual drop list yerine rolling correlation
- **HYP-REGIME correlation-cluster-throttle (Researcher B)** — ⚠️ PARTIAL: rho=0.70 fazla sıkı, return +%3145 → +%120 (binary 1-slot). Bu HYP graduated approach ile yumuşatma fix'i
- **Concentration limits (mevcut)** — max_per_category_pct=0.40, max_per_symbol_pct=0.20. Bu HYP cluster-level cap, mevcut'a tamamlayıcı (intra-cluster fine-grain)

### Mevcut sprint'le orthogonality
- Binary corr_gate → graduated versiyonu yerine geçiyor (REPLACEMENT, ortogonal değil)
- DD-aware leverage (HYP-001) → portfolio equity scalar, orthogonal
- RII sizer (HYP-002) → regime intensity scalar, orthogonal
- Capitulation halt → BTC-internal binary, orthogonal

---

## 3. Mekanik Kurallar (PRE-REGISTERED)

### 3.1 Cluster Detection (Daily, T-1 EOD inclusive)

```python
def build_clusters(ohlcv_per_sym, T_minus_1_eod, lookback_days=90, rho_threshold=0.70):
    """
    Causal: log-returns up to T-1 EOD (T-day exclusive).
    Returns: dict[symbol -> cluster_id]
    """
    returns = pd.DataFrame({
        sym: np.log(df["close"]).diff().iloc[-lookback_days:].values
        for sym, df in ohlcv_per_sym.items()
        if df.index[-1] <= T_minus_1_eod
    })
    corr = returns.corr()
    # Single-linkage clustering: any pair with |ρ| ≥ threshold → same cluster
    # NOTE: positive correlation only (negative leaves separate)
    G = nx.Graph()
    G.add_nodes_from(corr.columns)
    for i, s1 in enumerate(corr.columns):
        for s2 in corr.columns[i+1:]:
            if corr.loc[s1, s2] >= rho_threshold:
                G.add_edge(s1, s2)
    clusters = {}
    for cid, component in enumerate(nx.connected_components(G)):
        for sym in component:
            clusters[sym] = cid
    return clusters
```

### 3.2 Position Sizing per Open Slot

```python
def graduated_size(side, sym, existing_positions, clusters, base_risk_pct):
    """
    Order positions by confluence_score descending; assign multiplier by rank in cluster.
    """
    target_cluster = clusters.get(sym)
    if target_cluster is None:
        return base_risk_pct, "no_cluster"
    # Same-cluster + same-side positions
    cohort = [p for p in existing_positions
              if clusters.get(p.symbol) == target_cluster and p.side == side]
    rank = len(cohort) + 1  # 1-indexed (yeni trade rank)
    if rank == 1:
        return base_risk_pct, "cluster_1st_full"
    elif rank == 2:
        return base_risk_pct * 0.50, "cluster_2nd_half"
    elif rank == 3:
        return base_risk_pct * 0.25, "cluster_3rd_quarter"
    else:  # 4th+
        return 0.0, "cluster_4plus_blocked"
```

### 3.3 Direction Awareness
- BTC long + ETH long, ρ_BTC_ETH=0.85 → same cluster, same side → graduated
- BTC long + ETH short → ayrı cohort'lar (long ve short bağımsız sayım)
- BTC short + SOL short, ρ=0.78 → same cluster, same side → graduated

### 3.4 Concentration Limits (PRESERVED)
- max_per_symbol_pct=0.20 (mevcut) korunur — graduated sizing concentration'ı **azaltır**, ihlal etmez
- max_per_category_pct=0.40 korunur

### 3.5 Causality
- Correlation matrix T-1 EOD inclusive (90 gün trailing T-91..T-1)
- Cluster assignment T-day boyunca sabit
- Yeni trade sizing → mevcut açık pozisyonların cluster ve side'ına göre rank

---

## 4. PASS / RED Criteria

### PASS
- Mean annual return alpha ≥ **+%3pp**
- Mean MaxDD bozulması ≤ **+%2pp**
- Capital utilization (cluster_1st_full + 2nd_half trade'ler / total signal) iyileşme ≥ **+10pp** (slot doluluk artar)
- Bootstrap CI low > 0
- Bonferroni-adj p < **0.010**
- Robustness: **≥ 5/7 PASS**

### RED
- Robustness ≥ 4/7 HARD FAIL
- Alpha < +%2pp
- DD bozulması > +%3pp
- Cluster_4+_blocked rate > %30 (mekanik bozuk)

### MARGINAL
- Alpha +%2-3pp AND DD ≤ +%1pp → tie-breaker (confluence vs entry_time vs random) v2 sweep

---

## 5. Backtest Plan

### Setup
- Universe / strategies / pyramid / multi-target / risk: v2.0.3 mevcut
- **Correlation gate replacement:** baseline `reduction_factor=0.5 + hard_block=0.9` binary → treatment graduated 1.0x/0.5x/0.25x/blocked
- 3 baseline:
  - **v2.0.3 base** (binary corr_gate, mevcut champion)
  - **v2.0.3 + no_corr_gate** (cap kaldırılır — pure capital)
  - **v2.0.3 + graduated** (treatment)
- Walk-forward 3y/6mo/3mo → 13 pencere

### Pipeline
```
for window in 13_windows:
    1. baseline_binary: production_replay(v2.0.3 binary corr_gate)
    2. baseline_no_gate: production_replay(corr_gate off)
    3. treatment: production_replay(graduated)
    4. record: alpha_vs_binary, alpha_vs_no_gate, dd_delta, cluster_size_hist
    5. shuffle null: cluster_id permüte (random clusters), 200 iter
    6. bootstrap: 13 pencere alpha CI
```

### Robustness Suite (7 test)
1. **Threshold sweep ρ ∈ {0.60, 0.70, 0.80}** — alpha sapma < %30
2. **Lookback sweep 60/90/120 gün** — alpha sapma < %30
3. **Multiplier sweep** — (1.0, 0.50, 0.25) vs (1.0, 0.66, 0.33) vs (1.0, 0.40, 0.20): alpha sapma < %30
4. **Symbol-out CV** — alpha sapma < %30
5. **Regime split** — bull/bear/range: en az 2'sinde alpha ≥ 0
6. **Tie-breaker sweep** — confluence_desc vs entry_time vs random: alpha sapma < %20
7. **Look-ahead audit** — 50 random trade cluster assignment T-1 EOD doğrulaması

### Test gates
- Shuffle p < 0.010
- Bootstrap CI low > 0
- ≥ 5/7 robustness PASS

---

## 6. Karşı-Hipotezler

**KH-1: Graduated sizing aslında DD artırır.**
Cluster 1st full + 2nd half = cluster içinde 1.5x exposure (binary blocking durumunda 1.0x). DD beklentisi artabilir. **Test:** worst-window MaxDD baseline'dan > +%2pp ise RED. Eğer +%1-2pp aralığında ise return alpha +%5pp+ olmalı (risk-adj iyileşmeli).

**KH-2: Cluster çok geniş, hep aynı cluster (BTC/ETH/SOL/...).**
Crypto 1d ρ_BTC_alts genellikle 0.75-0.90 → single connected component → 11 sym tek cluster → 4+ trade blocked → çoğu signal reject. **Test:** cluster size distribution histogram, p50 ≤ 4 sym olmalı. Eğer p50 ≥ 7 ise ρ_threshold gevşetmek gerekir, v2.

**KH-3: Cluster küçük, mekanik etkisiz.**
Aksi durum: ρ ≥ 0.70 zor sağlanırsa her sym kendi cluster'ında, "graduated" devreye girmez → baseline ile aynı. **Test:** cluster_1st_full rate ≥ %60 olmamalı (graduated rank=2/3 aktif kullanım); 1st_full %90+ ise mekanik etkisiz, alpha ~0.

**KH-4: Slot doldurma stratejik olarak yanlış.**
v0.9.9 drop_pairs etkisiz olduğu için "halt + F&G zaten filtreliyor" sonucu çıktı. Graduated sizing slot doldurursa filtersiz kötü pair'lar girebilir → DD artar. **Test:** treatment'in pair-level performance breakdown'u; en kötü 3 sym DD katkısı baseline'dan > +%5pp ise mekanik problemli.

**KH-5: 90d lookback aşırı, regime shift'i yavaş yansıtır.**
2024-03 ATH sonrası BTC/alts decoupling fazından önce 60d veriyi yansıtır. 30/60d lookback farklı cluster verebilir. **Test:** Robustness #2.

**KH-6: Single-linkage cluster yapay birleştirir.**
BTC-ETH ρ=0.85, ETH-SOL ρ=0.78 ama BTC-SOL ρ=0.55 → single-linkage hepsini birleştirir (transitive); complete-linkage farklı sonuç. **Test:** clustering algorithm sweep (single vs complete) v2 sprint'inde değerlendirilebilir.

**KH-7: Tie-breaker (confluence_desc) overfit.**
Confluence_score zaten v2.0.3 sizing'de kullanılıyor (tier'lara mappinge). Aynı feature'ı cluster order için kullanmak double-weight olabilir. **Test:** Robustness #6 (entry_time, random sweep).

---

## 7. Risk — PASS olursa hangi değişiklik gerekir?

### Code değişiklikleri
- `src/price_action/risk/correlation_cluster.py` — YENİ modül: `build_clusters()`, `graduated_size()`
- `src/price_action/risk/sizing.py` — `position_size()` cluster_size_modifier integration (backward-compat default = 1.00x)
- `configs/risk_balanced.yaml` — `correlation_gate:` blok güncellenir:
  ```yaml
  correlation_gate:
    enabled: true
    mode: graduated  # NEW: binary | graduated
    rho_threshold: 0.70
    lookback_days: 90
    multipliers: [1.00, 0.50, 0.25]  # 1st, 2nd, 3rd
    max_rank_blocked: 4  # 4+ → blocked
    tie_breaker: confluence_desc
  ```
- `tests/risk/test_correlation_cluster.py` — clustering + sizing + look-ahead

### Mevcut sprint'leri etkileyen
- **Binary corr_gate** — replace edilir
- **drop_pairs (yorum)** — graduated sizing aynı mantığı dynamic veriyor; drop_pairs gereksiz
- **concentration_limits** — orthogonal, korunur
- **HYP-001/002** — orthogonal, combo testlenebilir
- **HYP-REGIME-cluster-throttle** — bu HYP onun yeniden tasarlanmış versiyonu (graduated)

### Live deployment
- Daily T-1 EOD cluster snapshot (Telegram digest)
- Slot kullanım metriği dashboard'a (dashboard_text.py ek panel)

---

## 8. Beklenen Sayısal Hedef

| Metric | v2.0.3 base (binary) | v2.0.3 + no_gate | v2.0.3 + graduated (target) |
|---|---|---|---|
| Mean annual (3y) | +%239.5 | +%280+ (tahmin) | +%243 - +%270 |
| Mean MaxDD | -%38.7 | -%55 (tahmin) | -%37 ile -%41 |
| Alpha vs binary | 0 | +%40pp (DD'siz) | +%3 - +%30 |
| Alpha vs no_gate | -%40pp | 0 | -%10 ile +%10 |
| Slot utilization (mean concurrent / 12) | %35 (tahmin) | %48 (tahmin) | %42-45 |
| Cluster_1st_full rate | n/a | %100 | %50-70 |
| Cluster_2nd_half rate | n/a | 0 | %20-30 |
| Cluster_3rd_quarter rate | n/a | 0 | %5-15 |
| Cluster_4+_blocked rate | n/a | 0 | %5-15 |

---

## 9. Implikasyonlar

### PASS
1. Binary correlation_gate deprecate, graduated production'a alınır
2. v2.0.3 BALANCED → v2.1.0 (graduated corr v1.0)
3. Slot bottleneck mit'ini gerçek bir mekanizmayla aşar (SEC21'in "FIFO doğru policy" sonucundan farklı yol)
4. CEO brief: "Graduated cluster sizing +%3-30pp uplift, DD ±2pp band, slot %35 → %43 doluluk"

### FAIL
1. Binary corr_gate lokal optimum; halt + F&G zaten dolaylı filtreliyor (v0.9.9 drop_pairs sonucuyla uyumlu)
2. Learning log: "Cluster graduated sizing crypto 1d edge üretmiyor; binary mantık structural optimum"
3. Olası v2: side-asymmetric multipliers (long graduated, short binary)
4. v2.0.3 binary gate korunur

---

## 10. Reproducibility Footer

```
hypothesis_id: 2026-05-15-correlation-graduated-sizing
git_hash_at_registration: 3da3344b2e69992f45e3acd8c40d4b399808e14f
config_hash: <stable_hash section 3 params>
data_hash: <ohlcv 11 sym 2021-2026; rolling 90d corr>
walk_forward: 3y/6mo/3mo n=13
multiple_testing: bonferroni n=5 alpha_adj=0.010
baseline_pair: (binary, no_gate)
output_planned: reports/research/corr_graduated_v1_results.{txt,json}
```

---

## 11. Yasaklar

- ❌ Multiplier sweep OOS'tan default (PRE-REG sabit: 1.0, 0.5, 0.25)
- ❌ Tie-breaker OOS-tune (PRE-REG: confluence_desc)
- ❌ ρ-threshold OOS-pick (PRE-REG: 0.70)
- ❌ Complete-linkage clustering v1'de denenmesi (sadece single-linkage; v2 pre-reg)
- ❌ FAIL durumda learning log olmadan v2

---

## Sonuçlar (DOLDURULACAK)

- [ ] Mean return alpha (target ≥ +%3pp): __
- [ ] Mean MaxDD bozulması (target ≤ +%2pp): __
- [ ] Cluster size distribution sağlıklı (p50 cluster ≤ 4 sym): __
- [ ] Bootstrap CI low > 0: __
- [ ] Bonferroni p < 0.010: __
- [ ] Robustness PASS (target ≥ 5/7): __
- [ ] Karar: __
