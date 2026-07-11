# KALAN İŞLER — Kapanış Sprinti Sonrası Defter (2026-07-10)

> **11 Temmuz üst-notu — bu dosyanın “kod tarafında açık iş kalmadı” sonucu
> artık güncel değildir.** Sonraki bağımsız execution/rate/DR incelemesi çoklu
> protection-fill lifecycle'ı, pending-entry WAL silme yarışı, deterministik
> fill çatışması, DMS'in 20 saniyelik private REST polling'i, cooldown sırasında
> acil-flatten retry tüketimi ve ingest→consumer snapshot gecikmesi buldu.
> Disk düzeltmeleri ve testleri 11 Temmuz tesliminde yer alır; açık pozisyonlar
> nedeniyle trade-daemon deployu ve 48 saatlik 418 kanıtı beklemektedir. Güncel
> karar/kapanış kaynakları:
> `docs/OPERATIONS_DECISIONS_2026-07-11.md`,
> `docs/OPERATIONS_PENDING_2026-07-11.md` ve
> `memory/shared/incidents/INC-2026-07-11-binance-testnet-rate-ban.md`.

> **🏁 NİHAİ DURUM (10 Tem gece):** #6/C1 (`29936e3`) + #7/CVE 8-of-9 (`0417651`,
> A/B-kanıtlı + canlı venv + restart) + #8/DEGRADED_READ (`b07745c`) + #4/retention-3g
> (`ad4aaab`, disk %85→%82) KAPANDI. **Kod tarafında AÇIK İŞ KALMADI.** Kalanlar:
> (a) Principal-fiziksel: healthchecks-URL, 2. testnet hesabı; (b) Principal-karar:
> vol_target EKLE onayı (öneri: ekle), E13 trail (40-kapanış verisi sonrası);
> (c) dış-bağımlı: chromadb CRITICAL (fix dünyada yayınlanmamış — pip-audit takibi).

> Bağlam: 10 Tem tam-kapanış turu bitti — **CRIT 5/5 + kod-fixable HIGH'ların tamamı
> + 87 MED/LOW kalemi KAPALI** (15 commit: `fe741e6..a65a5b6`, hepsi origin'de).
> Bu dosya geriye kalan HER ŞEYİN tek kaynağı: 39 karar-sınıfı kalem (sayım filosu
> `wf_c50ca86e`'nin `skipped_as_unsafe` çıktısı, kod-doğrulamalı) + açık Principal
> kararları + ertelenen cerrahi işler. Kural: buradaki kalemler "temizlik" DEĞİL —
> ya davranış değiştirir ya tasarım kararı ister; körlemesine uygulanmaz.

---

## 0. KAPANAN (referans — tekrar açma)

| Tabaka | Durum | Kanıt |
|---|---|---|
| CRIT 5/5 | slippage-ölçüm, WF-p 19×, feature_sweep-p, ccxt_live ×2, replay-equity MTM bandı | `fe741e6` `13b29a8` `7d6fc29` `d8dc70c`; parite `verify_widestop_parity [PASS]` |
| HIGH kod-fixable | T5-02 CT-OPS-02 wiring, T5-01 ghost-owner→ops_engineer, DR9 crash-loop alarmı, T5 log-scan→v15p2, T3 idempotency leak, maker-kalibrasyon, 12 silent-except | `8402e88` `3f1cfe0` `8e8cd03` `4cdea32` |
| MED/LOW 87 kalem | A=32 config-etiket, B=22 except→log, C=19 doc-hijyen, D=14 DuckDB try/finally | `cb5c287` `81f6ef5` `a65a5b6` `609fe96` |
| Principal hızlı-kararlar | A1-02 defter onarımı (+29.09), Telegram token rotasyonu, healthchecks altyapısı | journal düzeltildi; token canlı; bekçi inert-kurulu |
| Replay-equity nicel sonuç | 374K-trade havuz: eski −17.13% → dürüst bant **[−14.89%, −14.98%]** | arşiv DD'leri 2.2pp FAZLA imiş (muhafazakâr yön) |

---

## 1. 🔴 YÜKSEK ÖNCELİK — risk/güvenlik KARARLARI (fail-open → fail-closed sınıfı)

> **✅ GÜNCELLEME (10 Tem, aynı gün — commit `2a54956`):** Principal "düzelt ama
> yeni hata çıkarma" onayıyla **1-7 KAPANDI** (fail-closed + parite-kanıtlı,
> 11 test + 622 regresyon): p1c halt-koruma · sl_pct_min anahtar-eksik→1.0 ·
> breaker bozuk-state→24h süreli halt · DMS init-fail→SystemExit (3 site; DR9
> alarmı güvence) · kaldıraç _LEV_HARD_CAP hiyerarşisi · breaker_monitor ARŞİV ·
> pyramid default False. **Yalnız #8 açık** (sistemik tasarım mini-projesi).
> Canlı daemon satırları sonraki doğal restart'ta devreye girer.

Her biri davranış değiştirir; tek tek tasarım + test-first ister. Önerilen sıra bu.

1. **p1c_walker halt fail-open** — `p1c_walker.py:297` halt `release_at` parse
   fail → halt sessizce DÜŞER (**risk-halt fail-open!**); `:524` 3-loss halt
   hesabı fail → halt hiç eklenmez; `:233` .bak kopya fail sessiz. Doğru fix
   fail-closed kararı. Şerh: modül yalnız emekli 5m yolu + ops_status'ta canlı.
2. **sl_pct_min anahtarı kaybolursa WIDESTOP sessiz KAPANIR** (E7,
   `futures_daemon.py` ~2225) — fee-erozyon kalkanının kendisi korumasız;
   fail-closed (anahtar yok → REJECT-hepsi + alarm) önerilir.
3. **Breaker bozuk-state'te sıfırlanıyor** — tripped halt restart'ta kaybolur;
   fail-closed (bozuk state → halt + alarm) tasarım kararı.
4. **DMS init-fail'de switch'siz devam** — kill-switch kurulumu başarısızsa
   daemon korumasız koşuyor; fail-closed (başlamayı reddet?) kararı.
5. **Kaldıraç üç-kaynak** (T2-02): daemon hardcode `min(3,..)` ⊕ yaml
   `max_leverage_per_symbol` ⊕ lab `default_leverage` — tek-kaynaklama tasarımı
   + mutlak-tavan clamp şartı.
6. **breaker_monitor.py ikinci kill-switch yazarı** (T2-04) — split-brain
   sınıfı: arşive taşı YA DA yaml'a bağla; karar senin.
7. **pyramid_enabled default True→False** (T2-05, `futures_daemon.py:148/150`)
   — fail-closed; E6/P17 cerrahi paketiyle birlikte.
8. **Exchange okumalarının başarı-şekilli boş dönüşleri** (`[]`/`{}`) — hata ile
   "gerçekten boş"u ayırt etmeyen desen; sistematik tasarım kararı.

## 2. 🟠 PAKET İŞLERİ — davranışsal rework (kod, ama batch değil)

> **✅ GÜNCELLEME (10 Tem, "turuncu-sarıları kapat" onayı):** 🟠 9,10,11(minimal),
> 12,13,14,16,17,18,19 + 🟡 20(kısmi+D16+DR11),23(doğrulama),24(analiz),28,29,30
> KAPANDI — commit'ler: `4d253e1` `6568f5a` `bf9c23a` `fd198bb`. AÇIK KALAN:
> #15 C1-enforcement + #25 CVE (kendi oturumlarını ister, plan aşağıda) +
> #8 boş-dönüş mini-projesi + Principal-fiziksel: #21 healthchecks-URL,
> #22 vol_target kararı, #26 2.hesap, #27 VPS, retention DEĞERİ, E13-trail kararı.

9. **Paket-5: cancel-yutma kardeşleri** — `order_router.py:191,315`,
   `maker_only_router.py:306`, ccxt_live cancel yolu: doğru fix cancel-verify +
   filled-ise-pozisyon-sahiplen (ccxt_live fix'i `7d6fc29` şablon). Modüller
   şu an test-only/latent; **gerçek-canlı ŞARTI**.
10. **fetch_order poll-loop yutmaları** — `post_only_router.py:75`,
    `ccxt_live.py:180`, `maker_only_router.py:286`, `order_router.py:308,315`:
    log eklemek s başına spam üretir; doğru fix "timeout başına tek özet log"
    (küçük state). Paket-5 ile birlikte.
11. **HEAL + PROT_CHECK dev-blok cerrahisi** — `futures_daemon.py` 1227 (~70
    satır) + 1371 (~430 satır) try/finally dönüşümü: canlı trade-mantığı
    yeniden-girintileme; ayrı test-first cerrahi iş. (Not: ro/rw mixed-connect
    'different configuration' riski de aynı bölgede — birlikte ele al.)
12. **mae_R pool-zenginleştirme** — MTM stress bandını -1R üst-sınırından
    gerçek-MAE'ye indirir; sec53 pool builder'lara mae_R alanı + rebuild.
13. **T5-01 gerçek fix** — audit_chief kapsama taramasına phantom-owner/
    ajan-varlık kontrolü + universe owner reassignment + signals domain (P4).
14. **T5-03(b) enforcement gate** — risk_officer endorse + adversary kill-probe
    PASS'ini promote/deploy zincirine ön-koşul yapmak; bugün 0 promote olduğu
    için test edilmemiş blok yolu — test-first (P4).
15. **C1 read-only runtime enforcement** — `base.py:731-741` allowedTools
    eşlemesi ajanları fiilen kısıtlar; ajan-ajan smoke test şart (P6).
16. **provenance.py:71-72** — startup banner iki anahtarı yanlış yaml yolundan
    okuyor (T2-08); kod fix'i (banner çıktısı değişir).
17. **check_promises.py bilinmeyen-kind fail-loud** (T2-06 kod tarafı) — yeni
    alarm sınıfı; "uygula vs header'dan sil" kararıyla birlikte.
18. **'[V14]' log-tag yalanı** (W1-LOW, `futures_daemon_v14.py`) — canlı log
    string'i; log_pattern/CT-OPS tüketici envanteri çıkarılmadan değiştirme
    (monitör kırma riski, D1 yalancı-CRIT sınıfı).
19. **15M_SCAN_ERROR '0 sinyal gibi görünme'** — scan hatası loglanıyor ama
    sonuç 0-sinyalle aynı görünüyor; ayrım tasarım maddesi.

## 3. 🟡 OPS / ALTYAPI KARARLARI (Principal)

20. **Backup retention/off-site (DR14)** — disk %85'in GERÇEK kaldıracı:
    data/backups 18G (7g retention TASARIM GEREĞİ doğru çalışıyor; 5 gün mevcut).
    Seçenekler: retention 7→3g (~7G kazanç) / off-site taşı / kabul et.
    + D16: dbbackup plist'i önce repoya alınmalı (W7-H1) — env=3d vs yorum=7d
    çelişkisi ancak ondan sonra düzeltilebilir.
21. **healthchecks.io URL** — altyapı kurulu+inert; hesap+URL an meselesi
    (runbook: `reports/audit/dalga4/T8...md` §DR1). ⏳ senden URL bekliyor.
22. **vol_target (E2)** — canlıya ekle YA DA vol_target'sız re-validate.
    Karar öncesi yaml bloğuna 'ÖLÜ' etiketi BİLE yanlış (durumu mühürler).
23. **monthly_loss_pct yaml'ı** — F3 aylık fren kodu CANLI (`828fad0`) ama bu
    yaml anahtarları breaker'a bağlı değil; doğru fix kod-bağlama (etiket değil).
24. **E13 exit-paritesi** — pct-trail vs ATR-trail kararı. DİKKAT: F2 fix'i
    (`e702555`) canlı TP merdivenini 1R/1.5R + 30/30/40 yaptı — take_profit
    yaml blokları artık canlıyla EŞLEŞİYOR olabilir; önce yeniden karşılaştır,
    körlemesine DEAD etiketi yanlış.
25. **9 CVE upgrade** — izole shadow-venv'de (çalışan env riski).
26. **2. testnet hesabı** — 1h bot ön-şartı (DMS tüm hesabı flatten'lıyor).
27. **VPS bütçesi** (€5-9/ay) — şimdilik ES GEÇİLDİ (10 Tem talimatın).
28. **.env işleri** — :61-64 ölü DD satırlarını SİLMEK (duyurulu iş; canlı
    daemon'a source ediliyor) + T2-04 ölü risk paramları (PA_RISK_PER_TRADE
    vb.) — repo-dışı canlı dosya, ops batch'i.
29. **strategy_lifecycle active_configs değerleri** — v15p2'ye güncellemek
    curator kapsamını değiştirir (hangi config'ler review'da = karar).
30. **Silme kararları** — D19 .bat kalıntıları, D23 dms_heartbeat_test*.txt,
    B15 yetim ansiklopedi; tek tek davranış-nötr kanıtı ister.

## 4. ⚪ BİLİNÇLİ-AÇIK BIRAKILAN SINIFLAR (dokunma / değmez — kayıt için)

- **Döngüsel fail-safe sargıları** (bildirim-gönderme hatasını bildirmek /
  log-yazma hatasını loglamak): ~30 saha listelendi (futures_daemon ×8,
  scheduler ×2, base, audit_base, p1c, slippage_tracker ×2, breaker, sizing,
  iterate_orchestrator, post_only ×3, _vlog ×2, DMS-log, 15m ×2, bot_monitor,
  orderbook ×1) — yapısal olarak böyle kalmalı.
- **Bilinçli/dokümante yutmalar**: store CHECKPOINT no-op, tmp-cleanup
  guard'ları, opsiyonel SDK import, no-event-loop, test-fixture pool reset,
  sizing dokümante emergency fallback.
- **Tasarım-gereği pooled bağlantılar**: data/store + *_ingest _CONN_POOL
  singleton'ları (Windows lock-safety + RO paralellik) — per-call close'a
  çevirmek tasarım değişikliği.
- **Connection-factory fonksiyonları** (orderbook_logger:264,
  paper_trading_loop:235, paper_status_report:42): ömür çağıran-yönetimli;
  fix çağrı-yeri refactor'ü ister.
- **~300 tek-seferlik araştırma script'i** boilerplate except'leri + **~40**
  kapanmayan RO bağlantısı: canlı yüzey değil, churn'e değmez.
- **Emekli daemon dosyaları** (v13, multitf, testnet_daemon, 5m yolları):
  aynı desenler var ama canlı-dışı; düzenlemek karışıklık riski, fayda sıfır.
- **Düşük-değer log-eksikleri** (graceful-shutdown unlink, phantom-unlink,
  telemetri sargıları): güvenli ama değersiz.
- **risk_forex.yaml anahtar-anahtar ölü-envanteri** (E19): paper-only dosya;
  tam envanter ayrı iş, header şerhi kondu.
- **5 audit_*.md bozuk frontmatter** (pre-existing strict-YAML): ayrı küçük iş.
- **B5/B6 hafıza-playbook temizliği**: B3 consolidation fix'i ön-koşul (P6/P9).
- **W7 README uv-sync talimatı**: lockfile çelişkisi (P8) çözülmeden yazılamaz.

## 5. SIRADAKİ GERÇEK İŞ SEÇENEKLERİ (defter-dışı, üretim)

- **1h raf taraması** — pool hazır (`build_pool_1h.py`, 19-sym × 5.1y parite
  PASS); failed-breakout/trap sınıfı öncelikli → GO çıkarsa 2. hesap + paper bot.
- **XS-carry ilk koşu** — funding.duckdb 115K satır hazır; "kalan tek kaldıraç"
  ailesi hiç test edilmedi; onarılmış istatistik borusunun canlı testi.
- **Maker/slippage izleme** — bugünkü execution fix'lerinin ilk gerçek
  fill'lerde doğrulanması (maker payı %21→? ; slippage artık gerçek ölçülüyor).

---

*Kaynaklar: sayım filosu `wf_c50ca86e` (4 ajan, kod-doğrulamalı) + harita filosu
`wf_6c802f10` + FULL_REVIEW_VE_YOL_HARITASI_2026-07-10.md. Bu dosya kapanış
sprintinin devir noktasıdır; bir kalem kapatıldığında buradan düşülmeli.*
