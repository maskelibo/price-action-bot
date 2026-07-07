# DERİN DENETİM — A'dan Z'ye, Her Katman (v2)

**Tarih:** 2026-07-07 akşam · **Yöntem:** 8 paralel adli denetim ajanı (kod-karar-yolu, agent hafızası, kimlik/persona, iş akışı/cron/skill, konfig, veri katmanı, güvenlik/sır, test/CI) + ana oturumda doğrulama ve canlı fix. **~140 bulgu**, her biri file:line kanıtlı. Sabahki `FULL_AUDIT_2026-07-07.md`'nin derinleştirilmiş hali — o rapor geçerli, bu rapor onu KAPSAR ve aşar.

**Durum lejantı:** ✅ BUGÜN DÜZELTİLDİ (canlı) · 🔴 AÇIK-KRİTİK · 🟠 AÇIK-YÜKSEK · 🟡 AÇIK-ORTA · ⚪ AÇIK-DÜŞÜK

---

## 0. YÖNETİCİ ÖZETİ — En sert 6 gerçek

1. ✅ **Canlı bot saatin bir kısmında HENÜZ KAPANMAMIŞ mumlarla karar veriyordu (F1, CRIT).** Bugün ampirik kanıt: karar barında hacim 9.5, gerçek kapanışta 2450 (260×). İki kök: (a) tarama filtresi `<=` oluşan barı karar barı yapabiliyordu, (b) ingest kapanmamış barı DB'ye yazıyor, saatlik snapshot kesik barı donduruyordu. **Backtest'in hiç görmediği bir veri sınıfıyla trade ediyorduk** — canlı↔backtest beklenti matematiğini tek başına geçersiz kılan bulgu. İki katmanlı fix bugün canlıda (commit 5408dd3, daemon 19:55 TR restart).
2. ✅ **Tek para-dokunur botun kill-kriteri koruması YOKTU.** `bot_kill_criteria.yaml` sadece emekli botları izliyordu; v15p2 %25 DD eşiğini delseydi hiçbir alarm çalmazdı. Bugün bağlandı (36a2479).
3. ✅ **Canlı Telegram token'ı dünya-okunur log'a sızmıştı** (21 Haz ağ kesintisi, exception URL'i). Log'da yerinde maskelendi, kaynak kod sanitize edildi, izinler sıkılaştırıldı. **ROTASYON SENDE** (BotFather) — token 40+ gündür aynı.
4. 🔴 **Canlı çıkış merdiveni doğrulanan model DEĞİL (F2).** TP1 stratejinin doğal hedefine (2-2.5R) konuyor, TP2=1.5R → etiketler ters, doğrulamadaki "1R'de %30 kâr al" canlıda hiç gerçekleşmiyor; 30-bar time-stop çıpası da yanlış olaya bağlı. Ayrıca aylık breaker canlıda ölü kod (F3) ve funding maliyeti hiçbir modelde yok (F6).
5. 🔴 **Bilgi katmanı (hafıza) işlevsel olarak bozuk.** "Tek gerçek kaynağı" `active_state.md` bugünün damgasıyla 5 hafta önce emekli olan botu CANLI gösteriyor; CEO+risk_officer+analyst+lab hafıza pencereleri %100 konsolidasyon-gürültüsü — **risk subayı her boot'ta amneziyle uyanıyor.** Analyst/CEO playbook'ları var olmayan Postgres'e bakıyor.
6. 🟠 **İkinci/üçüncü savunma hattı emekli filoyu denetliyor.** Turnuva şampiyon-baseline'ı hâlâ v14 (yanlış R normalizasyonu ~%32), adversary stres testleri emekli 5m+v11 havuzlarına koşuyor, audit_universe v15p2'yi tanımıyor, drift job'ları boş seriyle "çalışıyor" (tören), read-only ajan sözleşmeleri runtime'da uygulanmıyor (CLI acceptEdits + kısıtsız).

**Bugün canlıya giren 6 commit:** FAZ-2 motor köprüsü (4c585bf) · güvenlik+promise (c701a27) · alt-data yol fix'i (669d712) · F1 forming-bar (5408dd3) · kill-kriteri (36a2479) · [bu rapor].

---

## A. KARAR YOLU — sinyal→backtest→canlı parite (16 bulgu)

Detektör matematiği lookahead-temiz (grimes fractal ufku, VSA pencereleri doğru). Sorun sinyal ÜRETİMİ değil, BESLEME ve ÇIKIŞ katmanları:

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| F1 | CRIT | Karar barı oluşmakta olan mum olabiliyordu (2 mod: forming-bar filtreden geçiyor + snapshot kesik bar donduruyor) | `futures_trade_15m.py:424` `<=`; ingest forming-bar yazımı; 7 Tem ampirik 260× hacim | ✅ 5408dd3 |
| F2 | HIGH | TP merdiveni ters: TP1=strateji hedefi (2-2.5R), TP2=1.5R — doğrulanan 1R/1.5R değil; ts30 çıpası yanlış olaya bağlı | `futures_daemon.py:2881-2889`, `futures_daemon_v13.py:166-191`, `engine.py:425-434` | 🔴 |
| F3 | HIGH | Aylık breaker canlıda ölü: `record_realized_pnl` 0 çağıran; side-cond %12/%4 limitler tetiklenemez, combined bilinçli 0.99 → **canlıda aylık kayıp freni YOK** | `breaker.py:497,331-336`, v15p2.yaml:326-337 | 🔴 |
| F4 | HIGH | -1007 timeout retry: orijinal emri fetch etmeden yeni coid ile resubmit (çift dolum riski) + retry başarısında SL/TP/journal YOK (çıplak pozisyon) | `futures_daemon.py:2661-2703`, `process_pending_entries.py:133-223` | 🔴 |
| F5 | HIGH | SL paritesi: backtest gap-through'da bile stop fiyatından doldurur; canlı STOP_MARKET mark-price + derinlik — haber mumunda canlı kayıp sistematik daha kötü, stres terimi yok | `engine.py:460-464`, `futures_daemon_v13.py:193-198` | 🟠 |
| F6 | MED | Funding maliyeti hiçbir modelde yok; tüm çıkışlar taker ama fee modeli ayırmıyor | `engine.py:664`, `lab.py:761-779` | 🟡 |
| F7 | MED | Canlı sizing cüzdan bakiyesiyle compound; doğrulama fixed-fraction non-compounding — sapma PnL ile büyür | `risk_integration.py:383` vs `lab.py:338-343` | 🟡 |
| F8 | MED | Breaker halt süresi kayan `blocked_until` ile fiilen 2×'e uzuyor (backtest 1 gün, canlı ~2 gün) | `breaker.py:419-430` vs `lab.py:897-901` | 🟡 |
| F9 | MED | dd_throttle zirve state'i v14 DOSYASI (peak 5099 vs v15p2 anchor 4963) → risk yarılanması −%6 yerine −%3.4'te. Muhafazakâr yönde ama "temiz başlangıç" bozuk. **Config değişikliği = Principal onayı** | v15p2.yaml:243 | 🟡 KARAR |
| F10 | MED | VSA onayı penceredeki HER yeşil barda ateşliyor (docstring "ilk bar" diyor) → aynı olaydan 3 sinyale kadar; manifest `confirmation_max_wait: 5` ölü (kod 3 hardcode) | `vsa_climax_test.py:167-179,537` | 🟡 |
| F11 | MED | VSA risk geometrisi OPEN'a çıpalı ama giriş ~CLOSE'ta → gerçek risk > etiketli; WIDESTOP sınır sinyalleri canlı/backtest farklı sınıflanıyor | `vsa_climax_test.py:809-816`, `futures_daemon.py:2437-46` | 🟡 |
| F12 | MED | İdempotency check-then-mark atomik değil → split-brain (tarihte 2×) senaryosunda tam da koruması gereken durumda deliniyor | `futures_daemon.py:2554,2594` | 🟡 |
| F13 | LOW | Aynı-bar TP+SL: backtest hep SL-önce (muhafazakâr ama R dağılımı volatil barda kayar) | `engine.py:460-471` | ⚪ |
| F14 | LOW | Replay-sonu açık pozisyon kapanışı hâlâ 2 Tem öncesi censored pyramid bonusu kullanıyor (pyramid-ON araştırma replayleri için zehir) | `lab.py:1119` vs `:758` | ⚪ |
| F15 | LOW | Engine-yolu RiskOfficer, VSA pattern_id'sini strateji ağırlıklarına eşleyemiyor → engine-bazlı VSA doğrulamaları sessizce farklı config test etti | `regime_filter.py:183-190`, `sizing.py:695-701` | ⚪ |
| F16 | LOW | Borsa-min ön-kontrolü exception'da fail-open (yuvarlanmamış qty gönderilir) | `futures_daemon.py:2588-92` | ⚪ |

**Temiz çıkanlar:** HTF filtresi doğru şekilde kaldırılmış (doğrulamayla uyumlu), regime-cache fail-closed, breaker UTC tutarlı, consec-loss deadlock fix'i sağlam.

---

## B. AGENT HAFIZASI (18 bulgu)

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| B1 | CRIT | `active_state.md` bugünün damgasıyla 6 haftalık dünya: emekli wide-stop bot "canlı", PID 17267, eski config — `update_active_state()` sadece frontmatter günceller, gövdeyi asla; CEO her brief'e enjekte ediyor | `active_state.md:8,25,31`, `ceo.py:421-431,194` | 🔴 |
| B2 | CRIT | 4 ajanın hafıza penceresi %100 oto-üretim gürültüsü: ceo 25/25, analyst 25/25, lab 25/25, risk_officer 17/17 (TÜM learning'i) "recurring-*" stub — CEO 2 ayda tek kalıcı ders yazmış (boot günü) | `store.py:304-314`, learning.md dosyaları | 🔴 |
| B3 | HIGH | `consolidate_weekly` her koşuda know_how'a tag-histogram çöpü APPEND ediyor; risk_officer know_how'ı %100 çöp — **en kritik ajan boş prosedürel hafızayla boot ediyor** | `base.py:1023-1032`, risk_officer/know_how.md | 🔴 |
| B4 | HIGH | Researcher hafıza penceresi %93 seed-abort meta-gürültüsü, 24k cap'i taşıyor (30k char) — 2 Tem falsifikasyon dersleri boğuluyor | learning.md ~1600-1800 | 🟠 |
| B5 | HIGH | Analyst+CEO playbook'ları var olmayan Postgres journal'ına yönlendiriyor; `_query_trades` hatayı yutup [] dönüyor → KPI brief'leri sessizce 0 trade görüyor | analyst/know_how.md:14, `analyst.py:52-70` | 🟠 |
| B6 | HIGH | ops_engineer runbook'ları hayalet altyapı: pg_isready, :8000/health, pg_dump, Redis halt — stack launchd+DuckDB | ops_engineer/know_how.md:14-55 | 🟠 |
| B7 | HIGH | hypotheses/ hijyeni: 381 dosyanın 162'si abort-meta-doc; status serbest-metin kaosu; ~%3'ü koşmuş | hypotheses/ | 🟠 |
| B8 | HIGH | `deploy_queue.json` yetim: 27 May'den kalma READY_FOR_DEPLOY + "annualized 639.77" (yasaklanan compounding-şişkin sınıf) — bir ajan bunu açık emir sanabilir | deploy_queue.json:3-16 | 🟠 |
| B9 | MED | seed_abort_log.jsonl: 196 kayıt, 3 bozuk fragment, şemasız (reason 171/196 eksik) | jsonl satır 1 | 🟡 |
| B10 | MED | SHARED FACTS 280-char kesme = çoğu frontmatter; 8 Mayıs'tan beri statik | `store.py:348-350` | 🟡 |
| B11 | MED | shared/lessons hattı uykuda: Haziran/Temmuz post-mortem'lerinin HİÇBİRİ (çıplak-pozisyon, split-brain, compounding, ro+rw) prompt'a taşınmamış | shared/lessons/ | 🟡 |
| B12 | MED | researcher/learning.md yapısal bozuk: `##` vs `###` karışık (parser sadece `###` tanıyor), kronoloji ters | `store.py:355-370` | 🟡 |
| B13 | MED | `memory/lab/` split-brain yetimi (lab_scientist'in göremediği 3 karar dokümanı) | memory/lab/ | 🟡 |
| B14 | MED | CEO kriz playbook eşiği breaker'a EŞİT (%4 uyarı = %4 halt) — erken uyarı süresi yok | ceo/know_how.md:42 vs yaml:321 | 🟡 |
| B15 | MED | Yetim bilgi: pa_mastery_encyclopedia (697 satır), pattern_crypto_winner_anatomy (309) — hiçbir kod/persona okumuyor | grep 0 referans | 🟡 |
| B16 | LOW | v15p2'nin canlı olduğunu söyleyen TEK hafıza kaydı yok — hafızayla boot eden ajan v13/v14 dünyası kurar | grep | ⚪ |
| B17 | LOW | 11 ajan dizini boş hafızayla boot ediyor (audit ailesi, adversary, bot_monitor, scout, curator) | memory/ | ⚪ |
| B18 | — | SAĞLAM: inbox/audit-register/iterate_targets/sweep_candidates canlı ve temiz | — | ✅n/a |

---

## C. KİMLİK / PERSONA (17 bulgu)

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| C1 | HIGH | **Read-only sözleşmeler runtime'da uygulanmıyor:** CLI `--permission-mode acceptEdits`, `--allowedTools` yok — risk_officer/audit ailesi/adversary fiilen tam Edit/Write/Bash ile koşuyor; izin listesi sadece prompt süsü | `base.py:731-741,346` | 🔴 |
| C2 | HIGH | bot_monitor personası (6 Tem'de yeniden üretilen!) emekli futures5m'i amiral gemisi örneği olarak anlatıyor | agents/bot_monitor.md:33-169 | 🟠 |
| C3 | HIGH | Researcher personası kendisini süren yeni hattan (feature_sweep/sweep_candidates/AILE-*) habersiz — scheduler bildiğini varsayıyor | researcher.md:29-31 vs scheduler:2189-2233 | 🟠 |
| C4 | MED | 3 runtime personası hiçbir kod yüklemiyor (execution_chief/portfolio_manager/signal_chief) — ölü dosyada charter düzenleme riski | token_budget.py:165-167 | 🟡 |
| C5 | MED | `agents/strategy_curator.md` git'te YOK ama 3 zamanlanmış job ona bağlı — restore sessizce lobotomi | git status, scheduler:2100-2330 | 🟡 |
| C6 | MED | strategy_curator çifti farklı verdict mantığı taşıyor (runtime yaml-eşikli, .claude hardcode) | iki dosya diff | 🟡 |
| C7 | MED | lab_scientist personası yanlış hafıza dizininden boot talimatı veriyor (memory/lab/ yok-sayılır) | lab_scientist.md:59-84 | 🟡 |
| C8 | MED | Yazma-görevi vs tool-grant çelişkisi: rapor yazmakla yükümlü read-only ajanlarda Write yok → Bash'e zorluyor (read-only niyetini de bozuyor) | .claude/agents frontmatter | 🟡 |
| C9 | MED | Prompt-injection guard'ı SIFIR personada var — researcher/lab/scout/ceo WebFetch+RAG kullanıyor | grep | 🟡 |
| C10 | MED | CEO brief adım 1: hiç var olmamış `reports/analytics/yesterday.json` | ceo.md:90 | 🟡 |
| C11 | LOW | Ölü yollar: labeled_signals.parquet, ops/incidents/, defer_followups.md | 3 persona | ⚪ |
| C12 | LOW | Frontmatter parse edilmiyor, prompt'a ham enjekte; `model:` alanı model SEÇMİYOR | `base.py:325-330` | ⚪ |
| C13 | LOW | Vadedilen KAYNAK provenance yorumu 9 üretilen personada YOK (bugün md5 eş, yarın drift görünmez) | grep | ⚪ |
| C14 | LOW | data_engineer "deterministic" iddiası ama LLM ajanı | data_engineer.py:25 | ⚪ |
| C15 | LOW | 12 eski çift yapısal drift (sayısal kapılar uyumlu — çelişki değil zenginlik farkı) | diff | ⚪ |
| C16 | LOW | Pulse docstring eski temaları listeliyordu | scheduler | ✅ bugün |
| C17 | LOW | `audit_base` adı var olmayan persona yükler (latent) | audit_base.py:102 | ⚪ |

---

## D. İŞ AKIŞI / CRON / SKILL (23 bulgu; 61 job tam tablosu ajan raporunda)

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| D1 | HIGH | Durdurulan researcher_5batch'in promise'ı saatlik yalancı CRIT üretecekti (benim dünkü değişikliğimin regresyonu) | promises.yaml:33-35 | ✅ c701a27 |
| D2 | HIGH | ceo.stdout.log 48.5/50MB — rotasyonda 3 promise 24h kör kalacak (donmuş-log bug'ının ayna sınıfı: rotate-away) | rotate_launchd_logs.py:20 | 🟠 |
| D3 | HIGH | İzleme tek-nokta-arıza: TÜM monitörler ceo_loop scheduler'ının İÇİNDE; canary'nin Telegram push'u bilinçli kapatılmış — scheduler asılırsa v15p2 sıfır alarmla trade eder | ceo_loop.py:95-113 | 🟠 |
| D4 | HIGH | Turnuva şampiyon baseline'ı v14: risk_usd=37.5 (v15p2=49.6) → post-2Tem R'ler ~%32 şişik + karışık-dönem seri — terfi kapısının karşılaştırma tabanı yanlış | scheduler.py:366-409 | 🟠 |
| D5 | HIGH | Adversary stres emekli filoya koşuyor (futures5m + v11 havuzları, mtime 23 May); v15p2 hiç stres-test edilmiyor; promise ölü bot sayesinde "geçiyor" | scheduler.py:1953-58,2046 | 🟠 |
| D6 | HIGH | bot-status/signal-proximity/resume-write skill'leri ölü botu raporluyor (PID 17267, eski log) | SKILL.md'ler | 🟠 |
| D7 | MED | check_promises düz-metin loglarda mtime tazeyken TÜM dosyayı 24h sayıyor (tarihsiz [HH:MM:SS] format) — degrade daemon yalancı PASS | check_promises.py:102-105 | 🟡 |
| D8 | MED | signal_scan job'ı doğuştan ölü (run_daily_scan hiç var olmamış, sessiz no-op) | scheduler.py:135-143 | 🟡 |
| D9 | MED | execute_orders zombi 1d pipeline'ı her gece koşuyor (tüketicisiz) | scheduler.py:146-189 | 🟡 |
| D10 | MED | Drift tespiti tören: iki job da `drift_detect([], [])` — KS/Welch hiç ateşleyemez | scheduler.py:509,2262 | 🟡 |
| D11 | MED | event_bus_dispatch hiçbir şey dispatch etmiyor (log+dedup, aksiyon yok) | scheduler.py:1065-85 | 🟡 |
| D12 | MED | "Aylık" job'lar ayda 4× ateşliyor (28-31 cron) | scheduler.py:2715-21 | 🟡 |
| D13 | MED | Adversary hook doc_id eşlemesi emekli botlara | scheduler.py:1146-54 | 🟡 |
| D14 | MED | 4 yüklü launchd job'ın repo kopyası yok (dashboard/dbbackup/logrotate/caffeinate) — restore kaybı | ~/Library/LaunchAgents | 🟡 |
| D15 | MED | Emekli bot plist'leri KeepAlive'la repoda; README'nin cp deseni split-brain'i diriltir | ops/launchd/ | 🟡 |
| D16 | MED | dbbackup izlemesiz + %97 diskte; retention env=3d vs yorum 7d | plist | 🟡 |
| D17 | LOW | feature_sweep izleme promise'ı yoktu | — | ✅ c701a27 |
| D18 | LOW | 5 kendine-işaret-eden skill symlink'i (git status gürültüsünün kaynağı) — silinebilir | .claude/skills/*/  | ⚪ |
| D19 | LOW | Windows cron .bat kalıntıları | scripts/cron/ | ⚪ |
| D20 | LOW | ~380 tek-seferlik araştırma script'i operasyonel ~15'le karışık | scripts/ | ⚪ |
| D21 | LOW | weekly_bot_attribution = bot_daily_cards duplikası | scheduler.py:2293 | ⚪ |
| D22 | LOW | ops/launchd/README 2 nesil eski | — | ⚪ |
| D23 | LOW | dms_heartbeat_test*.txt fantomları (test artefaktı) | data/ | ⚪ |

---

## E. KONFİG (20 bulgu)

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| E1 | CRIT | Kill-kriteri canlı bota bağlı değildi | bot_kill_criteria.yaml | ✅ 36a2479 |
| E2 | HIGH | **vol_target her backtest'te uygulanıyor, canlıda HİÇ yok:** sl=0.025'te cap tesadüfen eşitliyor; daha geniş stoplarda canlı risk doğrulanmışın 5×'ine kadar çıkabilir. Ya canlıya ekle ya vol_target'sız yeniden doğrula | v15p2.yaml:293-99, `lab.py:1044-47`, sizing'de yok | 🔴 KARAR |
| E3 | HIGH | Emekli configler iki daemon'ın SESSİZ default'u: env unset → c2v5 (risk %2, pyramid ON, widestop'suz!) veya v14-frontier | futures_daemon.py:94, v14.py:44 | 🟠 |
| E4 | HIGH | promises researcher_5batch yalancı CRIT (D1 ile aynı) | — | ✅ |
| E5 | HIGH | Audit/red-team katmanı emekli filoyu denetliyor; CT-DAT-01 bayat config'e sayı-karşılaştırması yapıyor (yakalamak için var olduğu UNI-cut drift'ini yapısal yakalayamaz) | audit_universe.yaml:176-183, audit_data.py:184 | 🟠 |
| E6 | MED | pyramid_enabled fail-open (eksik anahtar VE exception → True) | futures_daemon.py:143-145 | 🟡 |
| E7 | MED | sl_pct_min anahtarı (dosya değil) kaybolursa filtre sessizce KAPANIR (0.0 + load_ok=True) | futures_daemon.py:2225 | 🟡 |
| E8 | MED | signal_confidence_min 0.25 sadece backtest'te; canlı yol güven kapısız (doğrulamanın reddettiği <0.25 sinyaller canlıda alınabilir) | lab.py:421 | 🟡 |
| E9 | MED | Strateji-seti fallback'i kesilen 3 stratejiyi sessizce geri getirir (yaml hatasında _DEFAULT_4) | futures_trade_15m.py:241-272 | 🟡 |
| E10 | MED | 4 ölü config kendini yürürlükte gösteriyor (conflict_policy, drift_thresholds, notifications, v14p2) | başlık iddiaları | 🟡 |
| E11 | MED | Default≠config sapma tablosu (0.15/0.30 sınıfı): max_notional default 0.0=SINIRSIZ; breaker defaults 0.05/0.10 vs 0.04/0.08; cooldown default 3.0 vs 0.010 (300×); iki farklı max_per_symbol default aynı dosyada | sizing.py:730,743,832; breaker.py:125-43; lab.py:425 | 🟡 |
| E12 | MED | Regime cache-freshness defaults config'in 2-3.5× gevşeği; per_strategy enabled default False (typo=filtreler kapalı, fail-open); PA_REGIME_CACHE_STRICT=0 yaml strict'i undocumented override | regime_filter.py:459-62,225,455 | 🟡 |
| E13 | MED | take_profit/trailing config blokları canlı gerçeği değil (30/30/40+1.5R patch gerçek; F2 ile aynı kök) | sizing.py:881-94 | 🟡 |
| E14 | MED | Env yüzeyi: PA_DUCKDB_READ_ONLY unset→RW (lock sınıfı); PA_RUN_MODE 3 farklı default; kritik PA_* değişkenleri RUNBOOK'ta yok | store.py:148 vd | 🟡 |
| E15 | MED | Sembol evreni çift kaynak: canlı liste hardcode (futures_trade_15m.py:67), yaml ile senkron zorlaması yok (UNI kesimi iki yerde elle yapılmıştı) | — | 🟡 |
| E16 | LOW | Canlı config'te okunmayan iç-içe anahtarlar (kelly_cap, confidence_tiers, size_rounding…) + `method: confidence_dynamic` hiçbir dala uymayıp sessizce fixed_fractional'a düşüyor | sizing.py:713-25 | ⚪ |
| E17 | LOW | regime promise 26h vs 4h kadans — 6 ardışık kaçış sessiz | promises.yaml | ⚪ |
| E18 | LOW | strategy_lifecycle active_configs emekli presetleri "aktif" gösteriyor | — | ⚪ |
| E19 | LOW | risk_forex.yaml ~%80 dekoratif + cooldown from_yaml tuzağı | — | ⚪ |
| E20 | LOW | risk_dynamic.yaml referanslı ama YOK (2 script crash-on-run); c2v5 "pyramid disabled" yorumu değerle çelişiyor | — | ⚪ |

---

## F. VERİ KATMANI (15 bulgu)

| # | Sev | Bulgu | Kanıt | Durum |
|---|---|---|---|---|
| V1 | CRIT | Alt-data DB'leri `parents[4]` off-by-one ile repo DIŞINA yazılıyordu (~/data/) — yedek kapsamı dışı, "dün ilk kez dolduruldu" dediğim veriler de oradaydı | 4 modül :84-243 | ✅ 669d712 (dosyalar taşındı) |
| V2 | HIGH | funding.duckdb 35 gün bayat, hiçbir job yenilemiyor — XS-carry (kalan tek kaldıraç) girdisi donuk | son satır 2 Haz | 🟠 |
| V3 | HIGH | 18 sembolün HEPSİNDE son 30 günde ~110 eksik 15m bar (5 pencere, en büyüğü 26 Haz 12.75h) — backfill edilmemiş | gap sorgusu | 🟠 |
| V4 | HIGH | Yedek rotasyonu kendi kendini kilitliyor: disk<5GB kontrolü prune'dan ÖNCE → ~2 gün içinde yedek durur VE eski dirler silinmez | backup_duckdb.sh | 🟠 |
| V5 | MED | Snapshot copy canlı yazarla koordinasyonsuz (aktif writer lock gözlendi; torn-file riski, .bak+retry hafifletiyor) | ingest_ccxt.py:287-343 | 🟡 |
| V6 | MED | 15m BTC'de 9 bybit satırı binance barlarını duplike ediyor; OHLCVStore.read venue opsiyonel — filtresiz tüketici çift sayar | store.py:420-24 | 🟡 |
| V7 | MED | Ölü veri sıcak dosyaları şişiriyor: 1170 sembol 1d/1w + donuk 5m/1h/4h ≈ 7M bayat satır her saatlik snapshot'ta | market.duckdb | 🟡 |
| V8 | MED | ALGO protection order 'placed' takılı + tp2_id borsada sarkıyor olabilir; orphan-close yolunun koruma emirlerini iptal/işaretleme görevi yok | journal c36e817 | 🟡 |
| V9 | MED | %97 diskte ~7-8G güvenli geri kazanım listesi hazır (rapor-only): 20260706 yedeği 3.5G, market.duckdb.bak 1.5G, pool pkl'leri ~1.3G… | ajan raporu | 🟡 |
| V10 | LOW | Test suite prod data/'ya yazıyor (idempotency.duckdb 22M ×pytest) | mtime eşleşme | ⚪ |
| V11 | LOW | Alt-data dedupe DOĞRU (pozitif kontrol) ama kadans sahipsiz (ad-hoc çağrılar) | — | ⚪ |
| V12 | LOW | RAG index canlı ama haftalık raporu W26'da durmuş | — | ⚪ |
| V13 | LOW | Journal invariant'ları PASS; equity_snapshots+partial_closes 0 satır (DD gözlem boşluğu) | — | ⚪ |
| V14 | LOW | feature_sweep 1h kaynağı doğrulandı: 5.1-6.1y kapsam, 0 NULL — tuzak: donuk native-1h tablosu KULLANILMAMALI | — | ✅n/a |
| V15 | LOW | Snapshot lag 30dk (tasarım içi); daemon girişleri canlı kline'dan | — | ✅n/a |

---

## G. GÜVENLİK / SIR (10 bulgu — değerler asla yazılmadı)

| # | Sev | Bulgu | Durum |
|---|---|---|---|
| G1 | HIGH | Canlı Telegram token'ı world-readable log'da 10 kopya (21 Haz exception URL'i); kaynak `telegram.py:163` | ✅ maskelendi+sanitize+chmod; **ROTASYON SENDE** |
| G2 | MED | Token May rotasyonunda atlanmış; pre-rotate backup'ta aynı token duruyor | 🟡 rotasyonla birlikte backup'ı sil |
| G3 | MED | logs/ world-readable idi | ✅ 700/600 |
| G4 | MED | Canlı kapı tek noktada; router'lar "çağıranın sorumluluğu" diyor. Güçlü hafifletici: **diskte mainnet anahtarı HİÇ YOK** + testnet URL hardcode | 🟡 derinlik için router-assert |
| G5 | LOW | process_pending_entries sandbox fail-direction tersti | ✅ c701a27 |
| G6 | LOW | PA_BINANCE_API_KEY/SECRET hayalet env adları (hiç tanımlı değil — auth'lu reconcile sessiz boş anahtarla) | ⚪ |
| G7 | LOW | Dashboard cdn.plot.ly'den script çekiyor | ⚪ vendor'la |
| G8 | LOW | pandas-ta beta pin + ta-lib-binary (Windows-only, inaktif) | ⚪ |
| G9 | LOW | gitleaks yalnız pre-commit + eski rev; TAM git geçmişi manuel tarandı: TEMİZ (226 commit, 0 sızıntı) | ⚪ |
| G10 | LOW | LLM prompt derleyicisinde .env denylist'i yok (ampirik: 1472 llm_calls kaydında 0 sızıntı) | ⚪ |

**Temiz:** .env 600, plist'lerde sır yok, ps'te token görünmez, 97k dosya tarandı → tek sızıntı G1, Binance testnet anahtarları hiçbir yerde iz bırakmamış, dört kilit fail-closed doğrulandı.

---

## H. TEST / CI (20 bulgu)

| # | Sev | Bulgu | Durum |
|---|---|---|---|
| T1 | CRIT | feature_sweep sıfır test (IC/FDR/OOS-confirm) | 🔴 |
| T2 | CRIT | Canlı v15p2 wrapper'ı sıfır test; emekli v13 wrapper'ında 34 test var — verify-gate tablosundaki bir typo ya daemon'u kilitler ya yanlış config'i kabul eder | 🔴 |
| T3 | HIGH | check_promises + truth_report sıfır test | 🟠 |
| T4 | HIGH | Scheduler job listesi assert eden test yok (CT-OPS-02 sınıfı sessiz düşüş görünmez) | 🟠 |
| T5 | HIGH | hypothesis_runner + iterate_orchestrator sıfır test (otonom sürekli koşan yol) | 🟠 |
| T6 | HIGH | max_notional cap'i (efektif risk %0.39 mekanizması!) hiçbir test doğrudan assert etmiyor — karşılaştırma tersine çevrilse suite yeşil kalır | 🟠 |
| T7 | HIGH | Aynı-bar SL/TP çözüm sırası pinlenmemiş — TP-first'e refactor tüm backtest'leri iyimser şişirir, suite yeşil | 🟠 |
| T8 | HIGH | reconcile_orphan exit-price testsiz; civar testler daemon mantığının DOSYA-İÇİ KOPYALARINI test ediyor (drift yakalanamaz) | 🟠 |
| T9 | HIGH | Dört kilidin her biri ayrı test edilmiyor (2-3. kilidin silinmesini mevcut test fark etmez) | 🟠 |
| T10 | HIGH | **CI'ın blocking kapısı 7 dosya; tests/risk + tests/execution TAMAMI "informational continue-on-error"** — sizing bozulsa CI yeşil | 🟠 |
| T11 | MED | Daemon fingerprint bileşimi testsiz (store'un kendisi test'li) | 🟡 |
| T12 | MED | Emekli sistem testleri: v13 (34), multitf (22), faz14_27 (33)… biri blocking CI'da ve emekli 5m artefaktı okuyor → 5m temizliği CI kırar | 🟡 |
| T13 | MED | `assert True` sahte testler lookahead iddiası koruyor (smc_orderblock:341) | 🟡 |
| T14 | MED | Source-grep testleri (revert-detection, davranış değil) | 🟡 |
| T15 | MED | Canlı 15m daemon "replica" testleri (gerçek import değil kopya) | 🟡 |
| T16 | LOW | İzolasyon: gerçek-yol kullanımı sınırlı ve çoğu read-only (tam liste ajan raporunda) | ⚪ |
| T17 | LOW | Marker hijyeni ince ama tehlikesiz; PA_RUN_LIVE ölü env | ⚪ |
| T18 | LOW | test_audit_findings değişikliği TUTARLI (CT-OPS-03..07 log-pattern testleri; eşik-eşitlik sınırı eksik) | ⚪ |
| T19 | LOW | cap-etkileşimi tek yönlü test'li | ⚪ |
| T20 | LOW | Koruma-watchdog tick'i unit-testsiz (float-None sınıfının evi) | ⚪ |

---

## İ. BİRLEŞTİRİLMİŞ ÖNCELİK LİSTESİ (kalanlar, etki sırasıyla)

| # | İş | Kaynak | Efor |
|---|---|---|---|
| P1 | **F2 çıkış merdiveni**: TP1=1R/TP2=1.5R doğrulanan modele eşitle VEYA mevcut canlı merdiveni backtest'e taşıyıp yeniden doğrula — beklenti bandı bu düzelmeden anlamsız | A/F2+E13 | M |
| P2 | **E2 vol_target kararı** (Principal): canlıya ekle YA DA vol_target'sız yeniden doğrula; F9 dd_throttle state dosyası da aynı pakette | E2,F9 | S-M kod / karar |
| P3 | **F3 aylık breaker**: record_realized_pnl'i journal-close olayına bağla | A/F3 | S |
| P4 | **F4 -1007 retry**: önce fetch_order(orijinal coid); retry başarısında SL/TP+journal | A/F4 | M |
| P5 | **D4 turnuva baseline v15p2'ye** (cutoff 2 Tem + risk_usd 49.63) — terfi kapısı şu an yanlış tabana kıyaslıyor | D4 | S |
| P6 | **D3 dış canlılık bekçisi**: scheduler-dışı minik launchd job (promises dosyası >2h eski → Telegram) | D3 | S |
| P7 | **D2 rotate-aware promises**: gz arşivi de pencereye kat | D2 | S |
| P8 | **T10 CI blocking kapısına tests/risk+execution+audit** | T10 | S |
| P9 | **B1-B3 hafıza onarımı**: active_state gövde-yenileme + konsolidasyon çöpünü know_how/learning'den runtime'a yönlendir + Postgres-çağı playbook'ları DuckDB'ye | B1-6 | M |
| P10 | **D5+E5 ikinci/üçüncü hattı v15p2'ye çevir** (adversary bot listesi+pool, audit_universe, CT-DAT-01 set-karşılaştırma) | D5,E5 | M |
| P11 | **V2 funding günlük job + V3 5 pencere backfill** | V2,V3 | S |
| P12 | **V4 prune-önce-disk-kontrolü** + V9 ~8G temizlik (Principal onayı listede) | V4,V9 | S |
| P13 | **E3 daemon default'ları fail-loud** (env unset → ABORT) | E3 | S |
| P14 | **C1 ajan izinlerini gerçek yap** (--allowedTools/--permission-mode eşlemesi) | C1 | S-M |
| P15 | T2+T6+T7+T9: dört kritik test (v15p2 verify-gate, notional-cap, same-bar, dört-kilit) | H | M |
| P16 | D6 üç skill'i v15p2'ye çevir; D18 symlink temizliği | D | S |
| P17 | E6+E7 fail-open→fail-closed (pyramid, sl_pct_min) | E | S |
| P18 | C2/C3 persona yenileme (bot_monitor, researcher+sweep SOP) + C5 curator'ı commit'le | C | S |
| P19 | B7/B8: hypotheses klasör hijyeni + deploy_queue SUPERSEDED | B | S |
| P20 | Sabahki FULL_AUDIT D1-D10 listesi aynen geçerli (D1 cap-parite doğrulaması hâlâ en öncelikli araştırma işi) | — | — |

## SADECE SENİN VEREBİLECEĞİN KARARLAR

1. **Telegram token rotasyonu** (BotFather) — bugün; sonra `.env.backup-pre-rotate-*` silinecek.
2. **E2 vol_target**: canlı sizing'e eklensin mi, yoksa v15p2 beklenti bandı vol_target'sız yeniden mi doğrulansın? (İkisi de meşru; mevcut durum tutarsız.)
3. **F9 dd_throttle state**: v15p2'ye kendi peak dosyası (risk artar yönde düzeltme — o yüzden sana soruyorum).
4. **V9 disk temizliği**: 20260706 yedeği + market.duckdb.bak + pool pkl'leri (~8G) silinsin mi? Disk %97.
