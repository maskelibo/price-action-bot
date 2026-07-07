# TAM OTONOMİ PLANI — "İnsan Eli Değmeden Aksın"

**Tarih:** 2026-07-07 · **Principal direktifi:** piyasayı anlasın → binlerce ilişkiyi tarasın → hipoteze çevirsin → test etsin → botlaştırsın → (testnet'te) trade etsin; TF'leri ve piyasaları ben push etmeden kendisi denesin.
**Tek insan kapısı (bilinçli):** GERÇEK PARA — RUNBOOK GO/NO-GO tablosu. Testnet/paper zincirinin tamamı otonomlaşır.

## 0. Neden bugüne kadar otonom değildi? (kanıtlı kök nedenler)

| Belirti (senin gözlemin) | Kanıtlı kök neden |
|---|---|
| "Bayadır yeni bot fikri üretilmedi" | Üretiliyordu ama: %99'u 35 seed'in geri-dönüşümü (biri 87×), motor hipotezlerin %82'sini `NOT_EXECUTABLE` diye reddediyordu, terfi kapısı DSR bug'ıyla 2 Tem'e dek matematiksel kapalıydı |
| "Neden geçemedi, araştırdı mı?" | Evet — frontier programı 13 tur/41 varyantla 4-detektör ailesinin tavanını 3 kez bağımsız kanıtladı; AMA sonuç yeni arama uzayına yönlendirilmedi (rapor tüketicisizdi) |
| "Piyasayı anlayıp ona göre bot yaptı mı?" | HAYIR — hipotezler 4 sabit temadan geliyordu (biri emekli 5m botunu refere ediyordu); sistematik feature×return taraması hiç yoktu |
| "15m'i 1h/4h/1d'ye çevirip denedi mi?" | tf_exploration her gün koştu ama `["5m","15m"]` hardcode'luydu (sadece pool'u olan TF'ler) → her rapor "STAY 15m"; motor 1h/4h/1d'yi ZATEN destekliyordu, kimse çağırmıyordu |
| "Farklı piyasa (forex) denedi mi?" | Denedi ve **pozitif sonuç buldu** (EUR/USD 4H equal_highs_sweep OOS PF 1.99, 29 May) — sonuç deploy kuyruğuna hiç bağlanmadı; market_scout'un 2 Bybit GO'su da tüketicisiz kaldı |

**Desen:** Veri ve kod hazırdı; kopukluk hep AYNI yerdeydi — *keşif çıktısı → sonraki aşamanın girdisi* kablosu yok.

## 1. BUGÜN DEVREYE GİREN (OTONOMI-1, canlı — commit e81fbba)

```
                    ┌─────────────────────────────────────────────┐
  GECE 04:10 TR     │ feature_sweep (deterministik, LLM yok)      │
  her gün           │ 18 sym × 13 feature × 3 hedef × IS/OOS      │
                    │ Spearman IC + BH-FDR + OOS-onay             │
                    └──────────────┬──────────────────────────────┘
                                   ▼ sweep_candidates.jsonl (ilk koşu: 149 aday)
  09:00 / 21:00 TR  ┌─────────────────────────────────────────────┐
                    │ researcher_pulse — 4 KANIT-TEMELLİ tema:    │
                    │ AILE-SWEEP (adaylar prompt'ta!) · AILE-TF   │
                    │ (1h/4h varyant) · AILE-FUNDING · AILE-MIKRO │
                    └──────────────┬──────────────────────────────┘
                                   ▼ pre-registered hipotez
  30 dk'da bir      │ hypothesis_runner → backtest → kapılar (DSR-fixed)
  07:00 TR          │ tournament (SADECE yeni materyal varsa — boş tören bitti)
                    ▼
                    │ promote → deploy_queue → [GERÇEK PARA: Principal]
```

Ek olarak bugün: iterate_orchestrator **TF parametrik** oldu (1h/4h/1d denemeleri artık mümkün), **donchian** kayda girdi, **dominance+sentiment verisi** ilk kez bağlandı, spin-loop üreten researcher_5batch durduruldu.

## 2. FAZLAR — kalan kablolar

### FAZ-2 (bu hafta): Motor köprüsü — "raf → motor"
`hypothesis_runner`'a `new_strategy` dalı: Strategy sınıfını çöz → `engine.run(strategy, universe, timeframe=hyp.tf)` → sonuç JSON'u turnuva şemasında. Kilidi açtığı şey: ~75 hazır detektör + tüm TF'ler otonom test edilebilir; NOT_EXECUTABLE sınıfı ölür. (Agent-C spec'i: adaptör + sonuç-şekillendirme; engine/loader/Strategy hepsi mevcut — `engine.py:154,225`, `iterate_orchestrator.py:441-499` desen olarak.)
**Kabul testi:** 29 Haz'ın 5 substantive hipotezi (donchian dahil) uçtan uca koşup GO/RED alıyor.

### FAZ-3 (bu hafta): TF-sweep gerçek keşif
tf_exploration'ı pool-bağımlılığından çıkar → FAZ-2 köprüsüyle 4 base + yeni detektörleri **1h/4h/1d'de** tara; verdict `DEPLOY <tf>` ise otomatik hipotez + deploy_queue kaydı üret (rapor-mezarlığı deseni biter).
**Kabul testi:** İlk 1h/4h sonuç tablosu; en az 1 TF-varyant hipotezi kapılara girdi.

### FAZ-4 (2 hafta): Otonom testnet-shadow deploy
Zincirdeki son manuel halka: promote → Telegram → insan. Değişim: promote → `bot_factory.generate_bot` → launchd bootstrap → **testnet-shadow** (sim_only, ayrı journal) OTOMATİK; 2 hafta shadow + kill_criteria temizse CEO brief'e "terfi-hazır" düşer. GERÇEK para flip'i (`sim_only:false` + canlı kilitler) Principal'da kalır.
Gerekli: daemon'a 1h/4h TF desteği (`futures_daemon.py:3881` bugün 15m/5m/1d) + bot_factory'ye launchctl adımı + shadow-slot yönetimi.
**Kabul testi:** Kapılardan geçen bir aday, insan dokunmadan testnet'te tarama yapan ayrı bir bot süreci olarak doğuyor.

### FAZ-5 (2-4 hafta): Forex + çok-piyasa
Eldeki gerçek sonuç (EUR/USD 4H PF 1.99) + `configs/risk_forex.yaml` + 844K satır 4H verisi var; eksikler: (a) FX veri feed'i CANLI değil (2026-01'de donuk — HistData aylık yenileme ile başla), (b) FX paper-broker adaptörü (`broker_base.py` soyutlaması mevcut; bar-close paper-sim en ucuz yol), (c) daemon'ın forex_market.duckdb tüketimi. SPK gereği **kalıcı paper-only** — bu kısıt korunur. Bybit-perp shadow (2×GO) aynı fazda: ccxt zaten Bybit'i destekliyor, testnet anahtarı yeterli.
**Kabul testi:** Forex paper-bot bar-close döngüsünde sinyal üretiyor; haftalık KPI raporuna giriyor.

### FAZ-6 (ay 2): Kapanış halkaları
- Sweep genişletme: feature 13→50+ (OI/dominance/sentiment/cross-sectional/event-time), TF {1h,4h,1d}, hedef vol-normalize R — "on binlerce ilişki" hedefi burada gerçek sayıya ulaşır (≈50×4×3×18×2 ≈ 22k test/tur, FDR aynı).
- LLM eval harness (fabrika kalite ölçümü) + VPS failover (tek-makine SPOF).
- FULL_AUDIT D-listesi kalanları (D1 cap-parite doğrulaması EN ÖNCE — mikro-canlı kararını etkiliyor).

## 3. Koruma rayları (otonomi ≠ başıboşluk)

1. **Kapılar gevşetilemez** — DSR/robustness/OOS zinciri her otonom adayın önünde aynen durur; sweep adayları bile FDR+OOS-onaysız researcher'a gösterilmez.
2. **Token hard-cap** aktif (dün): fabrika kaçarsa kendi kendini keser.
3. **Testnet/paper sınırı** — FAZ-4/5 dahil hiçbir otonom yol gerçek para emri veremez (dörtlü kilit + wrapper reddi aynen).
4. **Denetim hattı** — günlük 06:00 TR audit sweep'i otonom zinciri de tarar; yeni job'lar promises.yaml'a SLA olarak eklenecek.
5. **Novelty koruması** — pulse temaları aile-rotasyonlu; aynı seed'in 87× tekrarı sınıfı, sweep-aday havuzunun sürekli tazelenmesiyle yapısal olarak ölür (aday dedupe anahtarı: symbol|feature|target).

## 4. İzleme — "çalışıyor mu?"nun tek bakışta kanıtı

| Ne | Nerede | Beklenen ritim |
|---|---|---|
| Sweep koşumu | `reports/research/feature_sweep/*.md` | her gece 04:10 TR |
| Yeni adaylar | `memory/researcher/sweep_candidates.jsonl` | büyüyor + dedupe |
| Kanıt-temelli hipotezler | `memory/researcher/hypotheses/` (AILE-* etiketli) | 2/gün (pulse) |
| Koşan backtest oranı | backtest_results status=OK oranı | FAZ-2 sonrası %18→%80+ |
| Turnuva skip/koşum | app.log `tournament_skipped_no_challenger` | materyal yoksa skip |
| Fatura | llm_calls.jsonl + haftalık token raporu | ≤$120/ay eşdeğeri hedef |
