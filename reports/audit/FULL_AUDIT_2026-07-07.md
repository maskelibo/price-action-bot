# TAM SİSTEM DENETİMİ — Hata Kayıt Defteri + Düzeltme Planı

**Tarih:** 2026-07-07 · **Kapsam:** A'dan Z'ye (loglar, journal↔borsa, sizing, scheduler, denetim register'ı, testler) · **Yöntem:** 3 paralel adli analiz + canlı sistem gözlemi. Mimari bağlam: `PROJE_RAPORU.md` (2026-07-06).

## ÖZET HÜKÜM

Sistem **çalışıyor ve kendini koruyor** (DMS bir kez gerçekten tetiklenip hesabı düzleştirdi — 29 May; koruma katmanları görevini yapıyor). Hata envanteri 3 kök nedene iniyor: **(K1) DuckDB tek-yazıcı kilit çakışması** (4 belirti), **(K2) journal↔borsa mutabakat zafiyeti** (reconciler eski dünyaya bakıyor), **(K3) efektif risk ≠ konfigüre risk** (notional cap 5/5 işlemde bağlayıcı). Bugün 6'sı düzeltildi/hafifletildi; kalanlar önceliklendirilmiş listede.

## A) KRİTİK BULGULAR (yeni tespit)

| # | Bulgu | Kanıt | Etki |
|---|---|---|---|
| **A1** | **Efektif risk %0.39, konfigüre %1 DEĞİL** — `max_notional_pct_equity=0.15` capi 5/5 işlemde bağlayıcı; SL mesafesi ~%2.6 iken uncapped notional $1.920 gerekir, cap $744'e kırpıyor → işlem başına risk ~$19.5 | journal notional'ları hepsi ≈$744; SL kayıpları −18/−22 (−50 değil); `sizing.py:730-733` | Canlı $ beklentisi nominalin ~%39'u. Backtest de aynı capi uyguluyor (`lab.py:1052-56`) → yapısal tutarlı AMA... |
| **A2** | **Backtest cap-değeri paritesi TEYİTSİZ** — `lab.py:179` default **0.30**; 0.30→0.15 değişikliği +%16.1/ay manşet raporuyla AYNI GÜN (2 Tem) config'e girdi. Manşet replay 0.30 ile koştuysa canlı $ beklentisi backtest'in ~yarısı | `lab.py:179`, config lineage, `v15_filo_blend:218-224` | GO/NO-GO kriter-3'ü (net>0) etkiler; **DOĞRULANMALI** (D1) |
| **A3** | **Journal exit-price placeholder'ları** — 5 kapanışın 3'ü `reconcile_orphan` ile kapandı: exit_price=entry_price (sahte), realized_r=0.0, PnL income'dan geri-dolduruldu; LINK'te fark $2.84. `futures_partial_closes` BOŞ (ALGO'nun 2 partial-TP bacağı journallanmadı) | journal sorgusu; borsa income karşılaştırması | Trade-analitiği (R dağılımı, exit kalitesi) 3/5 işlemde kör |
| **A4** | **Reconciler eski dünyaya bakıyor** — 14 günde 1.146/1.146 raporda aynı hayalet pozisyonlar (NEAR/DOT/UNI/DOGE), qty_drift %35-40; bunlar v13/v14 dönemi journal kayıtları. Sonuç: AF-EXE-20260605-001 (critical) sonsuza dek açık + gerçek drift sinyali gürültüye gömülü | reports/reconcile 14g taraması | 2. savunma hattının en gürültülü kör noktası |
| **A5** | **K1: DuckDB tek-yazıcı ailesi** — `TRADE_CLOSED_LOOKUP_FAIL`(9), ingest IOException(115), `write_lock_retry_exhausted`(129, bugün dahil), AF-DAT-20260605-001(critical) = AYNI kök neden. Producer/consumer ayrımı yazık ki tüm yazarları kapsamıyor (reconciler+backfill+snapshot çakışıyor) | Agent-A defect #11/25/26/30 | Veri yazım güvenilirliği; test suite'te bile lock-flake üretiyor |

## B) KRONİK/ORTA BULGULAR

| # | Bulgu | Kanıt | Not |
|---|---|---|---|
| B1 | `scan15m.data_stale_auto_refresh` ×73.457 — tarayıcı sık sık bayat barla başlıyor, auto-refresh telafi ediyor | app.log | İngest 5dk / bar 15dk ritmi kaynaklı; sinyal kalitesine etkisi ölçülmeli |
| B2 | `ingest.symbol_fail` ×21.751 + fetch_fail ×12.111 | app.log | Çoğu geçici ağ; fail-loud tasarım gereği gürültülü |
| B3 | `scheduler.dms_stale` ×731 (son 30 Haz) | app.log | v14 döneminde yoğun; v15p2'de temiz |
| B4 | Telegram iletim boşlukları — `crit_no_token` ×12, missing_token ×221 | app.log | Bazı subprocess bağlamlarında env eksik → CRIT alarm sessiz düşebilir |
| B5 | `ceo_loop.canary_dead` ×7 (son 20 Haz) | app.log | Orchestrator canlılık boşlukları; tekrarı izlenmeli |
| B6 | 5 açık denetim bulgusu — hepsi vadesi geçmiş: AF-EXE-0605(**crit**), AF-DAT-0605(**crit**), AF-EXE-0531(high), AF-OPS-0617-002(high), AF-OPS-0702-001(med) | findings_register | A4/A5 çözümü ikisini kapatır |
| B7 | Test suite: 2.243 yeşil; 5 kırmızı+14 error → 2'si pre-existing (paper_gate K3, test_memory bölüm-adı drift'i), kalanı canlı-ingest lock çakışması (izole geçiyor) | 6-7 Tem koşuları | Testler canlı sistemle aynı DB'ye dokunmamalı (fixture izolasyonu) |
| B8 | `llm_calls_audit` promise 6h SLA'sı sessiz gecelerde yalancı WARN | promises son 3 rapor | Eşik 26h yapılmalı veya gece muaf |
| B9 | Küçükler: ALGO protection kaydı `placed`'da takılı; AAVE hayalet fingerprint (filled ama order_id boş); 4 `submitted` fingerprint askıda; stablecoin ingest fetch boş | Agent-B/bootstrap | Kozmetik + veri hijyeni |

## C) BUGÜN DÜZELTİLENLER ✅

| Fix | Ne yapıldı |
|---|---|
| C1 | **Otonom araştırma döngüsü kanıt-temelli hale getirildi** (OTONOMI-1 commit): feature_sweep motoru + kanıt-temelli pulse temaları + 5batch spin-loop durduruldu + tournament boş-tören ön-kontrolü |
| C2 | iterate_orchestrator TF kilidi açıldı + donchian kayda girdi (AİLE-1 başlangıcı) |
| C3 | dominance + sentiment DB'leri İLK KEZ dolduruldu (kod aylardır hazırdı) |
| C4 | feature_sweep funding sembol-varyant düzeltmesi |
| C5 | (Dün, P1) persona birleştirme, artifact izlenebilirliği, token hard-cap, doc-senkron, UNI kararı, risk-config unknown-key WARN |
| C6 | ceo_loop yeni scheduler'la yeniden başlatıldı (53 job; 17:36 TR) |

## D) DÜZELTME PLANI (öncelik sırasıyla, kalanlar)

| # | İş | Neden | Efor | Sahip önerisi |
|---|---|---|---|---|
| **D1** | **A2 doğrulaması:** +16.1/ay manşet replay'inin cap=0.15 ile koştuğunu teyit et (replay driver'ının geçtiği `max_notional_pct_equity` grep'i; gerekirse tek yeniden-koşum). Sonucu GO/NO-GO kriter-3 yorumuna işle | Canlı beklentinin yarıya inip inmediği belirsiz | S-M | researcher + audit_research |
| **D2** | **A4:** reconcile_journal'ı aktif bot journal'ına (v15p2) yönlendir + eski-dönem kayıtlarını `legacy_closed` olarak kapat → AF-EXE-0605 kapanır, gerçek drift sinyali görünür olur | 1.146 gürültülü rapor/14g | S | execution_chief |
| **D3** | **A3:** reconcile_orphan kapanışlarında gerçek exit fill'i income/userTrades'ten çek (fiyat+ts), placeholder yasak; partial-TP bacaklarını `futures_partial_closes`'a yaz | Trade analitiği körlüğü | M | execution_chief |
| **D4** | **A5/K1:** tek-yazıcı disiplinini tamamla — reconciler+heal yazımlarını daemon'ın kendi bağlantı havuzuna taşı VEYA yazma kuyruğu; test fixture'ları canlı DB'lerden izole et (B7) | 2 critical bulgu + test flake | M | data_engineer |
| D5 | B4: telegram env'ini tüm subprocess yollarında garanti et (launchd plist EnvironmentVariables veya .env source) | CRIT alarm kaybı riski | S | ops_engineer |
| D6 | B8: llm_calls_audit SLA 6h→26h | Yalancı WARN | S | ops_engineer |
| D7 | test_memory bölüm-adı düzelt (SHARED FACTS) + paper_gate K3 fixture'ı | 2 kalıcı kırmızı | S | herhangi |
| D8 | Stablecoin ingest fetch fix (CoinGecko endpoint/limit) | AİLE-2 verisi | S | data_engineer |
| D9 | B1: stale-bar oranını izlenebilir metrik yap (kaç taramada refresh gerekti/başarısız) | Sinyal kalitesi görünürlüğü | S | ops_engineer |
| D10 | OI backfill + merge.py path/şema düzeltmesi (PROGRAM_V2 H1-H3 zaten planlıyor) | AİLE-2 | M | data_engineer |

*Bilinçli YAPILMAYACAK:* `futures_daemon.py` god-file refactor'ü (çalışıyor+testli; estetik refactor kötü takas — Principal mutabakatı 6 Tem).
