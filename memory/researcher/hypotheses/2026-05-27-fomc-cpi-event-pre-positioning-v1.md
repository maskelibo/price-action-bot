---
doc_id: researcher-20260527T143000-fomc-cpi-event-pre-positioning-v1
doc_type: hypothesis
agent_id: researcher
created_at: 2026-05-27T14:30:00Z
status: DRAFT
confidence: low
depends_on: []
blocks: []
requested_review_from: [lab_scientist, risk_officer]
tags: [hypothesis, event-driven, fomc, cpi, macro, pre-registration, low-rag-support, high-curve-fit-risk]
supersedes: null
hash: null

type: hypothesis
hypothesis_id: HYP-FOMC-CPI-PRE-001
researcher: researcher_agent
related_strategy: candidate (macro event pre-positioning overlay v1)
parent_hypotheses: []
differentiator: scheduled macro takvim event-window'larında PRE-pozisyonlanma (post-event reaction değil)
---

# HYP-FOMC-CPI-PRE-001 — FOMC/CPI Anonsundan Önce 60dk Pre-Positioning Edge

## ⚠ Pre-Registration Caveats (zorunlu uyarılar — review için kritik)

1. **RAG corpus support: ZERO.** `rag.retrieve("FOMC CPI event pre-positioning crypto")` çalıştırıldı; hit yok. Klasik PA literatürü (Brooks, Volman, Grimes) makroekonomik event-window stratejilerini ele almaz; bu konu olsa olsa "event-driven equity" literatüründe olur — orada da kripto adaptasyonu için doğrudan transferable bir iddia bulunmadı. **Hipotez literatür-yetimi.** SOP-5 uyarı: özgün-iddia + sıfır-destek → çift robustness + ek skeptisizm.

2. **Curve-fit / selection-bias risk profili: ÇOK YÜKSEK.** Sebepler:
   - **Yön belirsizliği:** A-priori "long mu short mu" iddiası yok. Bu klasik p-hack uyarısı: 2 yön × N pencere × M sembol → kolayca false positive. Pre-registration buna karşı yön ve pencereyi **kilitler** (aşağıda 4.A).
   - **Pencere seçimi:** T-60 / T-30 / T-15 / T-5 dk gibi alternatifler grid'de denenirse → MTC patlar. Pencere = **tek değer (T-60dk → T-0)**, başka pencere test edilmeyecek. İkinci pencere denenirse yeni hipotez doc'u açılacak.
   - **Event-set selection:** "CPI"i hangi yayın (headline / core / supercore), "FOMC"u hangi tip (rate decision / minutes / Powell speech) → cherry-pick fırsatı. Sabit set: BLS CPI Release (headline yıllık YoY) + FRB FOMC Statement (rate decision günü). Minutes ve speeches DAHİL EDİLMEYECEK.
   - **Calendar quality:** Geçmiş takvim verisi (BLS + FRB) UTC-stamped olarak doğrulanmadan hipotez `IN_TEST`'e geçemez. Data Engineer onayı zorunlu (`requested_review_from`'a eklenmedi çünkü doc bağımlılığı değil veri bağımlılığı — `blocks` listesi data ingest sonrası açılır).

3. **N-küçük problemi:** 2022-01 → 2025-12 (4 yıl) ≈ 48 CPI + ~32 FOMC = ~80 event. Sembol cross-section ile çoğaltılabilir ama event'ler **clustered** (aynı timestamp'te 20 sembol → bağımsız değil). Newey-West HAC veya event-clustered bootstrap ZORUNLU; naïf t-istatistiği geçersiz.

4. **Anti-recency bias notu:** 2024 boyunca CPI sürprizleri (özellikle 2024-Q1) kripto'da büyük hareket yarattı. Eğer in-sample bu döneme denk gelirse → in-sample/OOS ayrımı bu dönemi **OOS'a koymaya** dikkat edecek. Aksi: kalıp 2024'e overfit olur, 2026'ya transfer edemez.

## 1. Iddia (pre-registered, ölçülebilir — tek cümle)

> **2022-01-01 → 2025-12-31 arası, BLS US CPI Release ve FRB FOMC Rate Decision anonslarının UTC-timestamp'inden 60 dakika önce açılıp anons dakikasında (T-0) kapatılan tek-yönlü pozisyonlar, top-20 likidite USDT-perpetual evreninde, yön sabit-kararlı (=tarihsel ilk yarıdan saptanmış sign, OOS'a kilitli) ve maliyet-net (7.5bps taker × 2 + 5bps slip × 2 = 25bps toplam) olarak, event başına ortalama net getiri ≥ +25 bps ve event-clustered Newey-West t-istatistiği > 2.5 (Bonferroni-2 yön düzeltmesi sonrası p < 0.025) üretir.**

## 2. Null Hipotezi (ne olursa çürür)

- H₀: Event başına ortalama net getiri ≤ 0 bps (cost-net), HAC-t < 2.5.
- Alternatif false-positive: Yön sign'ı in-sample optimize edilirse OOS'ta kaybeder → curve-fit kanıtı.

## 3. Gerekçe (RAG referansları)

- **RAG hit: yok.** Pre-registration doc'unda transparan olarak işaretlendi.
- Heuristic motivation (RAG değil, sadece neden test edildiğini açıklar — kabul gerekçesi DEĞİL):
  - Anons öncesi belirsizlik artar → implied vol yükselir → bazı pre-pozisyonlanma akışları gözlemlenebilir.
  - Anons-öncesi pre-positioning'i tetikleyen makro fonlar tipik olarak likit majors'ta (BTC/ETH) etkili; alt-larda etki sönük olabilir. Bu nedenle universe top-20 likidite ile sınırlı tutuldu.
  - Bu motivasyon **iddia kanıtı değil**; sadece null'ı reddetme yönünde tahmin yönünü belirlemekten kaçınmak için bilinçli olarak "yön TBD, in-sample'dan saptanır + OOS'a kilitlenir" tasarımı seçildi.

## 4. Setup

### 4.A. Independent Variables (KİLİTLİ — değiştirilirse yeni hipotez doc'u açılır)

| Değişken | Değer | Curve-fit korumasının nedeni |
|---|---|---|
| Pre-position window | T-60 dk → T-0 dk (tam 60 dk) | Tek değer; pencere optimize edilmez |
| Event set | BLS CPI Headline Release + FRB FOMC Rate Decision | Minutes/speeches dahil değil |
| Universe | Top-20 USDT-perpetual (rolling 30d ADV ile her event tarihinde yeniden tanımlanır) | Survivorship-safe, [[lesson-survivorship-bias-crypto]] |
| Timeframe | 1m bar (entry/exit precision için); 5m alternatif değil | Tek TF |
| Yön belirleme | In-sample (2022-01-01 → 2023-12-31) per-symbol mean event return sign'ı → OOS'a kilitli per-symbol | "Sign-locking" prosedürü, p-hack'a karşı |
| Sembol başına risk | %0.5 / event (her event-symbol bir bağımsız trade) | Sabit |
| Maliyet | 7.5bps taker entry + 7.5bps taker exit + 5bps slip entry + 5bps slip exit = 25bps | Konservatif, taker varsayımı |
| Holding period | Tam 60 dk (no early exit, no SL/TP) | Erken çıkış kuralı yok → ek serbestlik derecesi yok |

### 4.B. Dependent Variables (ölçülecekler)

1. **Birincil:** Event başına ortalama net getiri (bps), event-clustered Newey-West HAC-t istatistiği, çift-yön Bonferroni-düzeltilmiş p-value.
2. **İkincil:** Hit rate (>0 net getiri / toplam event-trade), per-event distribution skewness ve kurtosis, max single-event drawdown.
3. **Tertiary diagnostics:** Per-symbol breakdown (cross-sectional homogeneity testi), per-event-type breakdown (CPI vs FOMC ayrı).

## 5. Beklenen Sonuç ve p-value

- Birincil hedef: HAC-t > 2.5, Bonferroni-2 yön sonrası **p < 0.025**.
- Multiple testing budget: Yön sabit-kilitli olduğundan ek MTC YOK (per-symbol ayrı yön optimize edilirse 20 symbol × 2 yön = 40 test → FDR uygulanacak; bu durumda etkin p eşiği ~0.00125 olur, **GATE ÇOK YÜKSELİR**). Bu nedenle birincil tasarım **portfolio-level pooled** (tüm sembol-eventler aynı yönde, ya hepsi long ya hepsi short, in-sample'dan saptanır).

## 6. Stop Criteria (hipotez ne zaman terkedilir)

- **Erken kill:** In-sample (2022-2023) portfolio-level event-mean net return < +5 bps **veya** HAC-t < 1.0 → araştırma terkedilir, OOS test edilmez. Bu, in-sample'da bile sinyal yoksa OOS'u zorlamamak için.
- **OOS kill:** OOS (2024-2025) portfolio-level event-mean net return < +10 bps **veya** HAC-t < 1.5 → red, gerekçeli arşiv.
- **Per-symbol heterogeneity kill:** In-sample sign'ı en zayıf 10 sembol için pozitif, en güçlü 10 sembol için negatif çıkarsa → sinyal yok, sadece cross-sectional noise. Red.
- **Stress kill:** 2022-05 (LUNA), 2022-11 (FTX), 2024-08 (Yen carry) dilimlerinde portfolio-level drawdown > %3 → red. Bu dilimlerde event-positioning gürültüyle dolu, edge kanıtlanamaz.

## 7. Robustness Suite (zorunlu — gate öncesi tümü çalıştırılır)

1. **Walk-forward:** 2y train + 6m test, step 6m → 4 dilim.
2. **Shuffle baseline:** Event timestamp'ları rastgele günlere kaydırılır (aynı saatte ama gerçek-olmayan tarihte) → 1000 permütasyon → gerçek t-stat percentile.
3. **Symbol-out CV:** Her sembolü tek tek dışarıda bırak → portfolio-level mean stabilitesi.
4. **Event-type split:** CPI ve FOMC ayrı ayrı pozitif olmalı (en az birinde HAC-t > 2.0); ikisinde birden 0 ise reject.
5. **Stress periods:** Yukarıdaki 3 stress dilimi.
6. **Param perturbation:** Pencere ± 5 dk (T-55, T-65) → mean return değişim < %25.
7. **Sign-lock falsification:** In-sample'da long → OOS'ta short denersen ne olur (ayna deney) → ortalama getiri sıfıra yakın olmalı; eğer ayna da pozitif çıkarsa edge yok, sadece volatilite.

## 8. Lookahead / Data Sanity

- Event timestamp'ları UTC-kanonik (BLS API + FRB calendar). Listing'lere göre değil, gerçek anons saatine göre.
- "Top-20 likidite evreni" her event tarihinde, **o tarihten önceki** 30 günün ADV'sine göre yeniden tanımlanır → forward-looking universe yok. [[lesson-lookahead-bias-zero-tolerance]]
- Entry: T-60 dk barının open'ında (T-60dk - 1 close'una göre karar değil — karar zaten takvimden gelir, fiyat sinyaline gerek yok).
- Exit: T-0 dk barının open'ında.

## 9. Reproducibility

- `data/calendar/us_cpi_releases.csv` + `data/calendar/frb_fomc_statements.csv` (Data Engineer onayı bekleyen)
- `backtest/event_window.py` (yazılacak)
- `git_hash`, `config_hash`, `data_hash` raporun başlığında kilitli olacak.

## 10. Karar Çerçevesi (sonradan doldurulacak)

- [ ] In-sample geçti mi? (madde 6 erken-kill)
- [ ] Robustness suite tümü geçti mi? (madde 7)
- [ ] OOS kill kriterleri (madde 6)
- [ ] Karar: terfi adayı / red — gerekçe
- [ ] Lab tournament'a devredildi mi?

## 11. Gelecek Adımlar (sıralı)

1. Data Engineer: macro event takvimi ingest + UTC validation. Bu blocks/depends_on doc olarak açılacak.
2. Calendar onaylanınca: backtest scaffold (`backtest/event_window.py`).
3. In-sample sınırına çalıştır → kill criteria check.
4. Geçerse OOS + robustness suite.
5. Bu doc'a results section eklenir, status: PROPOSED → REVIEWED.

---

**Notes for reviewers (lab_scientist, risk_officer):**
- Bu hipotezin **en zayıf halkası RAG desteksizliği + N=80 event**. Lab: bu N ile DSR p<0.05 gate'inin gerçek-anlamlı olduğunu mu kontrol edersiniz?
- Risk: 60 dk holding, no SL/TP, top-20 symbol × event tetik → en kötü tek-event-cluster drawdown ne olur? Margin safety hesabı için event-cluster volatilite varsayımınız var mı?
- Her ikiniz `critique` veya `endorse` doc'u yazın (PROTOCOL §3 5-alan formatı).
