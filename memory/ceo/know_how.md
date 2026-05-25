---
agent: ceo
type: know_how
created: 2026-05-08
---

# CEO Know-How (Playbook)

> Tekrarlanan iş akışları. Yeni playbook çıktığında alta ekle, eskisini silme.

---

## Playbook: Günlük Morning Brief

**Tetikleyici:** Her sabah 06:00 UTC scheduler.
**Adımlar:**
1. Analyst günlük raporunu oku (`reports/analytics/<dün>.md`).
2. Açık pozisyon snapshot al (Postgres `positions` view).
3. Bekleyen sinyalleri Risk + Portfolio onaylı/reddedilmiş olarak ayır.
4. Önemli takvim: FOMC/CPI bugün mü? (`memory/shared/facts/crypto_calendar.md`)
5. Direktif yaz: SOP-1.
6. Telegram'a 280 karakter özet, dosyaya tam metin.

---

## Playbook: Haftalık Executive Summary

**Tetikleyici:** Her Pazartesi 09:00 UTC.
**Adımlar:**
1. Haftalık net P&L, Sharpe, MaxDD, profit factor.
2. Researcher'dan gelen yeni hipotez raporlarını özetle.
3. Lab tournament + drift sonuçlarını özetle.
4. Risk: bu hafta kaç defa size kısıldı? Korelasyon kapısı?
5. Aday parametre değişikliklerini insan onayına paketle.
6. Önümüzdeki haftaya 3 watch-item.

---

## Playbook: Kriz Protokolü

**Tetikleyici:** Aşağıdakilerden biri:
- Günlük DD > %4 (breaker %5).
- 3 ardışık gün net negatif.
- Korelasyon matrisi 0.85+ kümeye sıkışmış.
- Sembol bazlı flash crash > %15 / 30dk.

**Adımlar:**
1. Telegram CRIT alert (insan principal'a).
2. Tüm yeni pozisyon önerilerini durdur (`HALT_TRADING` öner — uygulama insan onayıyla).
3. Risk Officer'dan exposure raporu çağır.
4. Mevcut açıklarda partial-close veya SL sıkıştırma önerisi (öneri, otomatik değil).
5. Sebep analizi: data anomali / strateji rejim / exchange?
6. Postmortem'i Lab'e devret.

---

## Playbook: Departman Çatışması Çözümü

**Tetikleyici:** Researcher "X stratejisini terfi" / Lab "X için drift uyarısı" gibi.
**Adımlar:**
1. Her tarafın sayısal gerekçesini özetle.
2. Ortak metrik var mı? (genelde OOS Sharpe + DD).
3. Conservative bias: çatışmada Risk/Lab tarafı.
4. Kararı `decisions/`'a ADR + 4 hafta sonra revisit ajanda.

---

> Yeni playbook çıktığında alta ekle.

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:10, brief:6, daily:6

---
