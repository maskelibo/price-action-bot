# Operasyon ve karar kaydı — 2026-07-11

## Bağlayıcı kararlar

| Konu | Karar | Gerekçe / yeniden açılma kapısı |
|---|---|---|
| Aktif bot | `v15p2` korunur; yeni bot açılmaz | Yeni TF ve XS-carry adayları RED. Canlı performans da `%10+` kapısını kanıtlamadı. |
| Trade daemon restartı | Açık NEAR/ZEC pozisyonları varken **yasak** | Diskteki execution/rate düzeltmelerini yüklemek için korumalı pozisyonların lifecycle'ı kesilmez. |
| Binance private REST sahibi | Yalnız trade daemon | Dashboard/E13 yerel kanıt kullanır. CEO process kapısı credential/client/network öncesi private erişimi reddeder. |
| CEO scheduler | Şimdilik unloaded | Eski trade PID'i ortak cooldown'u okumuyor; ikinci private okuyucu eklenmez. Güvenli daemon restartı ve ilk sağlıklı bar sonrası guarded CEO ayrıca doğrulanır. |
| Pyramid | Hard-disabled | Ayrı pyramid execution yolu crash-complete değil; config değişikliği bu kapıyı açamaz. |
| Legacy 1d execution | Retired / non-dry yasak | Crash-complete WAL/protection sözleşmesi yok. Yalnız dry-run/scan yüzeyi kalır. |
| E13 ATR trail | Shadow `HOLD`, auto-promotion yok | Temiz prospective paired kapanış `0/40`; 40 örnek tamamlanmadan karar değişmez. |
| Vol target | Mevcut v15p2 config-gated yol korunur | Strict finite/bounds kontrolleri ve focused regresyon geçmeden değer değişmez. |
| Forex | Kalıcı paper-only, operasyonel `DEFER` | Yerel feed 2025-12-31'de donuk ve observed spread yok. Credential/order/network yolu eklenmez. |
| TF/feature adayları | Descriptive-only | Preregister edilmiş gelecekteki bağımsız OOS olmadan shadow/deploy yok. |
| Backup retention | Yerelde newest-3 | 39/39 doğrulanmış yerel backup var; off-site olmadığı için DR yine `DEGRADED`. |
| VPS / ikinci testnet hesap | Defer | Yeni bot kararı yok; ayrı hesap/process ihtiyacı bugün doğmadı. |

## Güvenli deploy sırası

1. Açık pozisyonlar exchange korumalarıyla doğal olarak kapanır. Bu bekleme
   sırasında manuel PnL/reconcile/order-check private sorgusu yapılmaz; CEO
   kapalı, dashboard ve Bybit liquidation collector açık kalır.
2. Yerel log/journal ile flat durumu kanıtlanır; son protection/execution
   evidence bütünlüğü doğrulanır.
3. Commit edilmiş v15p2 kodu güvenli bakım penceresinde tek kez yeniden
   başlatılır. Startup'ta config paritesi, DMS `external_main_loop`, background
   REST `OFF`, shared cooldown ve protection rebuild kanıtı aranır.
4. İlk sağlıklı kapanmış barda `POS_CHECK`, breaker/equity snapshot ve DMS
   heartbeat doğrulanır. Hata varsa rollback yapılır; yeni entry açılmaz.
5. CEO yalnız `PA_DISABLE_PRIVATE_EXCHANGE_API=1` yüklü plist/wrapper ile açılır.
   Private exchange isteyen CEO işleri fail-closed kalırken araştırma/rapor
   işleri devam eder.
6. Restart sınırından itibaren 48 saat yeni 418/`-1003` olmaması, yaklaşık dört
   ana-loop heartbeat/saat ve tutarlı protection sayısı saha kapanış kapısıdır.

## Rollback

- Yeni daemon startup/parite/koruma rebuild kapılarından biri geçmezse önceki
  launchd label/config değiştirilmez; process yeniden başlatma döngüsüne
  sokulmaz ve CRIT görünür bırakılır.
- CEO private-access kapısı kaldırılmaz. Rate kanıtı temiz olsa bile private
  exchange sahipliği ayrıca tasarım kararı olmadan genişletilemez.
- E13, Forex, TF shadow veya feature sonuçları hiçbir rollback senaryosunda
  emir yetkisi kazanmaz.

## Kodla kapatılamayan dış bağımlılıklar

- `HEALTHCHECKS_PING_URL` ve gerçek dış alarm teslim drill'i;
- credential'lı, client-side şifreli off-site backup hedefi ve yalnız off-site
  kaynaktan restore drill'i;
- 48 saatlik post-restart rate-limit saha penceresi;
- E13 için 40 temiz prospective paired kapanış;
- Forex için güncel point-in-time feed ve observed spread.

Bu dış kapılar için sahte URL, sentetik veri, uydurma kapanış veya geçmişe dönük
kanıt üretilmez.

## Kapanış doğrulaması

- Bütün repo: `3059 passed, 136 expected skip`.
- Execution/rate/ingest/ops kritik seçki: `783 passed`.
- Faz 3–6 roadmap seçkisi: `208 passed, 1 optional-dependency skip`.
- Runtime-safety Ruff, Python compileall, shell syntax, 15 launchd plist,
  28 YAML, 6 JSON, 21 TOML, Bandit HIGH ve `git diff --check`: PASS.
- `pip-audit`: fix sürümü yayımlanmamış 3 advisory / 2 package; Chroma server
  dışa açılmıyor, güvenilmeyen Torch PT2/JIT artifact'i kabul edilmiyor. Risk
  `docs/SECURITY.md` içinde açık tutulur; “temiz audit” diye sunulmaz.
- Repo-geneli Ruff tarihsel araştırma/watch yüzeyinde 307 informational baseline
  bulgusu taşır; CI runtime-safety Ruff kapısı ayrıdır ve temizdir.
