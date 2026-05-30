---
agent: audit
type: learning
created: 2026-05-30
---

# İç Denetim — Öğrenme Günlüğü

### 2026-05-30 — Denetim KAÇIRDI: journal↔borsa realized PnL şişmesi (kör-nokta)

**Olay:** Kullanıcı bir soruyla (kapanan pozisyonlar) journal'ın realized PnL'ini
borsa gerçeğiyle karşılaştırmamı tetikledi. Sonuç: **journal +$57.73 vs borsa
−$11.58** (income REALIZED_PNL) — ~$69 sistematik şişme (DOT journal +28.73 vs
borsa −3.52, işaret-ters). İç denetim departmanı (yeni kurulmuştu) bunu **otonom
yakalamamıştı** — kullanıcı buldu.

**KÖK NEDEN (denetim neden kaçırdı):**
- CT-EXE-01 yalnızca **AÇIK pozisyon** drift'ine bakıyordu (journal qty ↔ borsa qty).
- **KAPANAN-trade realized PnL** mutabakatı için HİÇ kontrol-testi yoktu.
- audit_chief `coverage_gap` "süreçte ≥1 kontrol VAR mı" diye bakıyor, "GEREKEN tüm
  kontrol TİPLERİ var mı" diye DEĞİL. execution.reconcile_journal'da CT-EXE-01
  bulunduğu için kapsama "tam" göründü → eksik PnL-recon kontrolü maskelendi.

**DERS (kalıcı kural):**
1. **Kontrolün VARLIĞI ≠ TAMLIĞI.** Bir sürecin bir kontrolü olması, TÜM kritik
   başarısızlık-modlarını kapsadığı anlamına gelmez.
2. **Settlement bütünlüğü = pozisyon mutabakatı VE PnL mutabakatı** (ikisi ayrı
   kör-nokta). Biri diğerini ima etmez.
3. Kritik süreçler için "beklenen kontrol TİPLERİ" tanımlanmalı; audit_chief
   eksik tip'i bulgu olarak işaretlemeli (sadece "hiç kontrol yok"u değil).
4. **Completeness critic** (López de Prado / red-team deseni): her denetim turunda
   "hangi başarısızlık-modunun HİÇ kontrol-testi YOK?" sorusu sorulmalı.

**DÜZELTME (bir daha bulsun):**
- **CT-EXE-02** eklendi: journal realized PnL ↔ borsa REALIZED_PNL income mutabakatı
  (per-symbol + total, işaret-ters tespiti). audit_universe.yaml
  execution.reconcile_journal → [CT-EXE-01, CT-EXE-02].
- Kabul testi: `test_audit_execution_catches_pnl_inflation` (journal +57.73 vs
  borsa −11.58 senaryosunu yakalıyor, severity=critical).

**Açık follow-up:** audit_chief coverage_gap'i "required control types" ile
genişlet (tip-bazlı tamlık denetimi). Şimdilik CT-EXE-02 manuel eklendi.
