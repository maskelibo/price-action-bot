# Learning — SEC27 Alt-Coin Sub-Portfolio REJECT (with Sürpriz Yan-Bulgu)

**Tarih:** 2026-05-15
**Pre-reg:** [2026-05-15-alt-coin-sub-portfolio.md](hypotheses/2026-05-15-alt-coin-sub-portfolio.md)
**Verdict:** REJECT (pre-reg disipliniyle) + YAN-BULGU (conservative LP variant adayı)

---

## 1. Üç Satırlık Sebep (gerekçeli postmortem)

1. **Hipotez RED**: Alt-only (V1) / alt-heavy (V2/V3) sub-universe BALANCED champion'ı yıllık return ekseninde yenmedi (Δ_ann -20pp ila -75pp, CI95 negatif, p<0.0001). Top-volume V4 da fiyasko (-75pp).
2. **Sürpriz**: H_anti'nin "DD ağırlaşır" iddiası **YANLIŞ ÇIKTI** — alt-only DD %50 iyileşti (-34.5 → -16.8). Yapısal sebep: 11-sym diversification ekstra ~%18 DD ekliyor, alt-coin clustered volatility aslında DD-protective.
3. **Mekanik**: Alt-coin mR 3.22x doğru ama n=2870 (43% V0) → sumR yetersiz, slot bottleneck V1'de yarı-doluyor, equity yatakta duruyor. Pencere korelasyonu V0/V1 = +0.845 (deflated version, max +169→+81 right-tail explosion'u kaçırıyor).

---

## 2. Yapısal Bulgular (Permanent Knowledge)

### Bulgu A — Alt-coin mR boost gerçek ama "slot dispersion bottleneck" tarafından sınırlı

Alt-coin sembol başına mR baseline'dan **3.22x** üstün (V0+SEC26 doğrulama, V1+SEC27 doğrulama). Ama production_replay sermaye dağıtımı (max_concurrent=12, max_per_sym=0.20, cooldown=3g) **universe size**'a duyarsız sabit — n_sym=5 → slot'lar yarı dolu. SEC13.3 RED ile zincir kanıt: universe size optimumu **11-sym BTC-anchor**.

### Bulgu B — H_anti partial yanlış: alt-only DD iyileşir

Naive intuition "alt-coin overweight = concentration risk = DD ağırlaşır" yanlış çıktı. Çünkü:
- Alt-coin'ler arası korelasyon yüksek → 11-sym'e ekstra alt-coin eklemek diversification benefit'i sıfır
- BTC/ETH likidite tabakaları stress'te alt-coin'lerden DAHA HIZLI çakılıyor (LUNA 2022-05 stress V1 mR +0.969 vs V0 +0.465 = **2.08x stress-hedge**)
- DD'nin "diversification fonksiyonu" assumption'ı crypto'da çakıyor → tek-renk volatilite

### Bulgu C — Conservative LP value proposition aday: V3 alt5+BTC

V3 (SOL ADA DOT AVAX MATIC + BTC): yıllık +%77 / DD -%18 / r-adj **4.196** (BALANCED 3.035'tan üstün). 5y compound $10k → $1.7M (BALANCED $2.7M). Risk-averse LP utility'de cazip.

**Production manifest değil bu sprint'te** — preset variant olarak Lab tournament adayı. Pre-reg gate revision (Δ_ann ≥ +10pp gevşemesi, Δ_radj + DD reduction'a ağırlık) gerekli.

### Bulgu D — Stress period mR alt-only'de baseline'dan üstün

V1 stress mR LUNA +0.969 / FTX +0.237 / ATH +0.445 — hepsi V0'dan yüksek. Alt-coin pattern triggers stress'te keskin (retail panic + funding cascade), ama production sermaye dağıtımı bu edge'i tam realize etmiyor (slot bottleneck).

Bu **PA mastery noktası**: edge **microstructure level**'da var, **portfolio compounding level**'da yoktur — iki katman birleştirme zorunluluğu.

---

## 3. Pre-Reg Disiplin Notu

Hard gate sıkı yazıldı (Δ_ann ≥ +10pp **AND** CI_low > 0). Bu Bonferroni k=4 ile doğru bağlanmıştı.

**Çelişki**: V1/V3 Δ_radj +0.95/+1.17 ve Δ_dd +17pp/16pp (her ikisi de pozitif iyileşme, CI95 dar). Pre-reg "OR" koşulu (Δ_radj ≥ +0.30) sağlandı, ama ana gate CI_low > 0 **yıllık delta için** yazılmıştı.

**Karar**: pre-reg sıkı yorum → REJECT. **Lab'e iletilecek not**: gate revision için strategic discussion açılmalı (mutlak return optimizasyonu vs risk-adjusted optimization farklı manifesto kararı).

---

## 4. Zincir Bulgular (Cumulative Evidence)

- **SEC13.3 RED** (20-sym): universe genişletme seyreltici
- **SEC27 REJECT** (5-sym): universe daraltma return killer
- **SEC14.0 cap probe** (0.30): concentration limit zorlama felaket
- **SEC11e WIN** (FVG ekle): orthogonal pattern eklemek + slot fix WIN

**Sentez**: BTC-anchor'lı 11-sym × 11-strategy × max_concurrent=12 × per_sym=0.20 cap **lokal optimumda kilitli**. Universe-size eksenindeki tüm sapmalar return'u öldürüyor.

Bu **5. sprint zincir kanıt** "lokal optimum kilitli" hipotezi için (sec4 yeni strateji RED, sec5 manifest gap, sec6 4h pivot RED, sec13.3 universe RED, sec27 sub-universe REJECT).

---

## 5. Yapısal Yan-Bulgu (sürpriz)

Pool'da alt5'in anchored_vwap_reversal mR = +0.376 (V0 baseline +0.073, **5.15x boost**). Mean-rev pattern AVWAP institutional fair-value reversion alt-coin retail-driven likidite parçalı yapısında **çok daha güçlü trigger ediyor**.

Bu PA mastery için orthogonal bulgu: **mean-reversion classının niche edge'i alt-coin universe'da unleashed olabilir** — ama production_replay slot allocation sub-universe'da yetersiz.

**Backlog hipotez**: "Per-strategy per-symbol allocation" — anchored_vwap_reversal'i sadece alt-coin'lerde aktif et, BTC/ETH'de skip et. Bu **strategy-symbol pair** boyutunda granularity. SEC11cd `per_sym_per_strat` zaten ablation testi yapmıştı (marjinal r-adj iyileşme), ama o asymmetric drop'tu, asymmetric activate değil. Test edilebilir.

---

## 6. Gelecek Adımlar

1. PA mastery gap raporunda "alt-coin sub-universe TESTED-REJECT (yan-bulgu: conservative LP variant adayı)" satırı.
2. `pattern_crypto_winner_anatomy.md` section 8 mental model: "Universe size 11-sym BTC-anchor optimum (SEC13.3 + SEC27 zincir)" ekle.
3. HYP-2026-05-15-001 conservative LP variant backlog'a — Lab strategic discussion.
4. HYP-2026-05-15-002 dynamic slot allocation per universe size → Engineering (SEC21 slot allocation sprint çıkışından sonra).
5. HYP-2026-05-15-003 per-strategy per-symbol asymmetric activate (anchored_vwap_reversal alt-only) — researcher backlog.
