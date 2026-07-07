---
doc_id: researcher-20260615T060000-chan-halflife-sharpe-scaling-meta-validation
doc_type: hypothesis
agent_id: researcher
created_at: 2026-06-15T06:00:00Z
status: PROPOSED
confidence: low
depends_on:
  - rag-chunk-book_chan_summary-halflife-mr-sharpe
  - rag-chunk-book_lopez_summary-dsr-threshold
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, meta_validation, mean_reversion, chan_halflife, selection_gate, no_new_signal]
supersedes: null
hash: f8bd7ec
---

# Hypothesis: chan-halflife-sharpe-scaling-meta-validation-crypto-1d

## 0. Meta — Niye Bu, Niye Yeni Bir Climax-Fade Değil

Son 14 günde 5 Grimes-Anti / climax-fade pre-registration kayıtlı (06-01, 06-04, 06-10, 06-12, 06-14). Aile-içi tekrar bir varyant daha eklemek **p-hacking-via-repetition**. Bugün RAG'deki en az kullanılmış orijinal iddia: **Chan'ın mean-reversion Sharpe ∝ 1/√half-life** ilişkisi. Yeni sinyal üretmiyorum — mevcut **mean-reversion stratejilerine bir SEÇİM/SİZİNG-GATE** olarak Chan prensibinin gerçekten geçerli olup olmadığını ölçüyorum. Bu, başarısız olursa tüm "half-life pre-screen" ailesini (06-08, 06-09, 06-12) sorgulamaya açar; başarılı olursa Lab tournament'a sembol-evren filtresi olarak girer.

## 1. Iddia (Tek Cümle, Ölçülebilir)

> 2022-01-01 → 2025-12-31 arasında, en az 200 günlük likit (24h notional medyanı > 50M USDT) tüm USDT-perpetual sembollerin 1D close serisi üzerinde, sembol-bazlı **Ornstein-Uhlenbeck half-life** hesaplanır (regression on Δlog-price vs lagged log-price). Aynı sembollerde **sabit-parametre Bollinger fade** stratejisi (20-bar SMA, ±2σ touch → ertesi bar open entry, mean revert/SL 3σ) yürütülür ve sembol başına OOS net Sharpe ölçülür. Chan iddiası: **Sharpe ile 1/√half-life arasındaki Spearman rank korelasyonu ρ ≥ +0.50** (p < 0.01, n ≥ 30 sembol). Eğer ρ < +0.30 ise prensip kripto bağlamında reddedilir ve mevcut "half-life pre-screen" gate'leri (HYP 06-08, 06-09, 06-12) kullanım dışı bırakma adayı olur.

## 2. Null Hipotez

H₀: ρ(Sharpe, 1/√half-life) = 0 — yani half-life, Bollinger-fade Sharpe'ı için yordama gücü olmayan bir gürültü değişkeni; Lopez (#1) "kararsız sembol seçimi" uyarısı yine de geçerli, ama Chan iddiası **bizim kripto evrenimizde** geçerli değil.

H₁: ρ ≥ +0.50, p < 0.01 → Chan iddiası kripto perpetual'larda geçerli, half-life küçük olan semboller daha yüksek Sharpe üretir.

**Tek-test** — multiple testing yok. Tek sayı, tek p-değeri. Bu, ailenin overfit'ten kurtulmasının yegane yolu.

## 3. Gerekçe (RAG Referansları)

- **[Chan 2013, Algorithmic Trading, Ch.2 §Mean Reversion]** (RAG #5): "Sharpe oranı half-life'ın square-root'una ters orantılıdır (kabaca)." Half-life 5g sembol, 30g sembolden ~2.4× daha yüksek Sharpe üretmeli. Bu bizim üzerinde **doğrudan test edebileceğimiz** somut bir niceliksel iddia.
- **[López 2018, Advances in Fin ML, Ch.8 DSR]** (RAG #9): Sharpe rapor edilen bir metriktir; trial sayısına ve yüksek momentlere göre düzeltilmelidir. Burada **trial sayısı = sembol sayısı = ~30-50**, dolayısıyla per-symbol Sharpe'ler Bonferroni-deflate edilmeli. Korelasyon hesabı ham Sharpe'lar üzerinde yapılır; DSR-deflated Sharpe'lar üzerinde de tekrarlanır (ikinci kontrol).
- **[López 2018, Ch.16 Position Sizing]** (RAG #7): w_i = m_i / Σ|m_j| — birden fazla aktif sinyalin sermaye payını ölçer. Bu test bunu kullanmaz ama POZİTİF SONUÇ DURUMUNDA `m_i = 1/√half-life_i` ölçüsü doğrudan w_i için motivasyon olur.
- **[Grimes 2012, Art & Science]** (RAG #4): "Ignoring transaction costs in backtests." → her sembol Sharpe'i fee+slippage dahil (7.5bps taker + 5bps slip). Aksi durumda korelasyon yapay olarak şişer (küçük half-life = yüksek frekans = fee'den daha çok yenir; net Sharpe ile gross Sharpe ilişkisi yön değiştirebilir — bu testin tek anlamlı versiyonu **net**).

## 4. Dependent Variables (Ölçülecekler)

| Metrik | Tanım | Hedef |
|---|---|---|
| ρ_spearman_main | Spearman ρ(net_Sharpe, 1/√half-life) | ≥ +0.50, p < 0.01 |
| ρ_spearman_dsr | Aynı ρ, ama Sharpe yerine DSR-deflated Sharpe | ≥ +0.40 (sekonder kontrol) |
| ρ_subset_top30 | Sadece en likit 30 sembolde aynı korelasyon | ≥ +0.40 (subset robustness) |
| ρ_subset_excl_2022 | 2022 sembollerini (LUNA+FTT epoch) çıkarınca aynı korelasyon | ≥ +0.40 (rejim robustness) |
| n_symbols | Test edilen sembol sayısı (200g+ veri + delisting'i dahil) | ≥ 30 |

## 5. Independent Variables (Sabit Tutulan Parametreler — Kasten Az)

Curve-fit yüzeyini minimize için tüm parametreler **literatürdeki varsayılan** değerlere sabitlenir; tarama YOK:

- Bollinger SMA window = **20** (Bollinger 1980 orijinal)
- Bollinger σ band = **±2.0** (orijinal)
- Stop loss = **±3.0σ** (entry-vs-mean'in 1.5×'i, standart)
- Half-life regresyon penceresi = sembol bazında **tüm tarih** (ekspanding); rolling değil
- Entry: bar `t` close ±2σ dışında → bar `t+1` open giriş (lookahead yasak)
- Exit: SMA orta-bant temas VEYA ±3σ stop VEYA 5 bar time-stop
- Fee: 7.5 bps taker, slippage 5 bps tek yön (toplam 25 bps round trip)
- Universe: 2022-01-01 → 2025-12-31, 200g+ data, 24h medyan notional > 50M USDT; **delisting dahil** (survivorship-free)
- Sembol bazlı risk = sabit %1/trade (sabit-fraksiyon, compounding YOK)

**Parametre taraması: 0 trial.** Optuna çağrılmaz. Walk-forward yok (tek geçişli korelasyon testi). Bu, Bonferroni cezasını **n=1** yapan ve hipotezi en katı testten geçiren tasarım.

## 6. Beklenen p-değeri ve Eşik

- Birincil eşik: **p(ρ) < 0.01** (tek test, Bonferroni-düzeltme gerekmez).
- Etki büyüklüğü eşiği: **ρ ≥ +0.50**. Daha zayıf bir korelasyon istatistiksel olarak anlamlı olsa bile pratik gate olarak işe yaramaz (sembol başına büyük varyans nedeniyle ranking gürültülü kalır).
- Sekonder: DSR-deflated Sharpe ile ρ ≥ +0.40, ki bu DSR'nin half-life-tabanlı Sharpe sıralamasını ne kadar bozduğunu ölçer.

## 7. Curve-Fit Şüphesi — Bu Hipotezin İçindeki Riskler (Dürüst Liste)

Pre-registration formatı gereği aday tasarımının kendi zayıf noktalarını **şimdi** yazıyorum, sonradan değil:

1. **Bollinger 20/2.0 seçimi self-curve-fit.** Bu parametreler "varsayılan" olduğu için seçildi, ama farklı sembollerde optimal Bollinger 50/2.5 olabilir; o zaman Sharpe-half-life korelasyonu rastgele başka bir patern alır. **Risk:** Sonuç ρ ≥ 0.5 bile gelse, "Bollinger 20/2.0 evrenine özgü bir buluntu" olabilir. **Mitigation:** Sonuç ρ ≥ 0.5 ise, aynı test **donchian 20-channel mean-revert** ile tekrarlanır; her iki ilkel mean-revert ailesinde de pozitif çıkarsa prensip onaylanır.

2. **Half-life OU regresyonu rejim-bağlı.** Half-life 2022 bear'da farklı, 2024 ralisinde farklı. Tüm-tarih regresyon "ortalama half-life"ı verir, **anlık olarak yanlış olabilir**. **Risk:** ρ statik analizinde yüksek görünür ama canlı kullanımda (rolling 90g half-life) yön değiştirebilir. **Mitigation:** ρ_subset_excl_2022 ek kontrolü zorunlu.

3. **Symbol selection bias.** En likit 30/50 sembol = zaten "trade edilebilir" altküme. Half-life dağılımı oldukça dar kalabilir; ρ sıkışık aralıkta zayıf görünebilir. **Risk:** Geçici-likit altcoin'ler (örn. 2022 H2 DeFi token'ları) muhtemelen kısa half-life + negatif Sharpe → ρ'yi yapay olarak negatife çekebilir. **Mitigation:** n_symbols ≥ 30 zorunlu; dağılım histogram'ı raporda.

4. **Net Sharpe fee'ye çok hassas.** 7.5bps yerine 5bps olsa kısa-half-life sembolleri korunur, ρ farklı çıkar. **Risk:** Fee parametresi seçimi sonucun yönünü değiştirebilir. **Mitigation:** Fee ile **sensitivity row** raporda — 5bps/7.5bps/10bps üç değerinde ρ.

5. **Tek test, ama "ya başarılıysa?" Hindsight.** İlk denemede ρ ≥ 0.5 çıkarsa, "demek ki Chan haklı" demek yerine **out-of-time** ekstensiyon test edilir: 2026-Q1 datası ayrı tutuldu (yoksa data dondur), oraya da bakılır.

## 8. Stop Criteria — Erken Terk Şartları

Aşağıdaki şartlardan herhangi biri olursa **araştırma durdurulur**, raporun "Karar = RED" damgasıyla `learning.md`'ye yazılır:

- **S1:** n_symbols < 30 (likit-evren çok dar) → metodolojiyi terk et, half-life selection-gate genelde işe yaramaz.
- **S2:** ρ_spearman_main < +0.30 → Chan iddiası kripto'da geçerli değil; tüm "half-life pre-screen" aile gate'leri (06-08, 06-09, 06-12) yeniden gözden geçirme adayı.
- **S3:** ρ_spearman_main ≥ 0.30 ama p ≥ 0.05 → veri yetersiz, daha fazla sembol/zaman olmadan ileri gitme.
- **S4:** ρ_subset_excl_2022 < +0.20 iken main ρ ≥ +0.50 → korelasyon LUNA/FTT döneminden geliyor (yapay), red.
- **S5:** Fee 10bps olduğunda ρ < 0 (yön değişir) → buluntu fee-hassasiyetli, pratik kullanılamaz, deferred archive.

## 9. Promotion Path (Kabul Edilirse)

Bu hipotez bir strateji DEĞİL, bir **sembol-seçim gate'idir**. Kabul edilirse Lab tournament'a şu şekilde girer:

- Mevcut tüm mean-reverting champion/challenger'lar için (örn. bollinger_fade, vwap-poc-reversal, vol-z-spike-fade) önceden **half-life ≤ median_half_life** filtresinden geçen semboller alt-evren olur.
- A/B karşılaştırması: aynı strateji, filtreli evren vs filtresiz evren — 6 ay forward Sharpe farkı ≥ +0.3 olursa filter aktif kalır.

## 10. Reproducibility

- git=`f8bd7ec` (HEAD audit-hardreview-20260528 branch)
- data=`reports/data_quality/manifest_2026-06-15.json` (Data dept'ten alınacak)
- config=`backtest/configs/halflife_meta_validation_v1.yaml` (yazılacak; parametre yok, sabitler)
- seed=42 (random_state for Spearman ranking ties — deterministik tie-breaking)

## 11. Deliverable

`reports/research/halflife-meta-validation-2026-06-15.html` — tek sayfa: korelasyon scatter (Sharpe vs 1/√half-life), Spearman ρ + p, dört sekonder ρ değeri, sensitivity row, dağılım histogram'ı, karar (terfi/red/deferred).

## 12. Estimated Compute / Wall-Clock

- Half-life regresyonları (50 sembol × 1 regresyon) = ~5 saniye
- Bollinger backtest (50 sembol × 4 yıl 1D) = ~3 dakika (vectorbt)
- Korelasyon + sensitivity = anlık
- Toplam: < 10 dakika tek-makine

Düşük maliyet, yüksek bilgi-değeri; **negatif sonuç bile faydalı** (gate ailesini temizler).
