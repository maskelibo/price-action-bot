---
agent: lab_scientist
type: know_how
created: 2026-05-08
---

# Lab Scientist Know-How

---

## Playbook: Haftalık Tournament

1. Champion listesi.
2. Challenger listesi (Researcher'ın son 4 hafta terfi adayları).
3. Hepsi son 6ay walk-forward.
4. Welch's t-test, DSR p-value.
5. Terfi şartı: aday OOS Sharpe ≥ champion ×1.15, DSR < 0.05, MaxDD ≤ champion +%5 mutlak.
6. CEO brief'e öneriler.

---

## Playbook: Drift Detection

1. Canlı son 30g returns.
2. Backtest eşdeğer 30g dilimleri (bootstrap 1000).
3. KS / Welch t / Levene testleri.
4. p < 0.01 → uyarı.
5. Sebep tespiti: data / slippage / rejim / edge erozyonu.
6. CEO + Researcher'a rapor.

---

## Playbook: RAG Refresh

Kaynaklar (`knowledge/seeds.yaml`):
- Brooks, Wyckoff, Volman, ICT, Adam Grimes
- arXiv quant-finance feed
- SSRN finance feed
- Trading firma blog'ları
- YouTube kanal/playlist'ler

Akış:
1. Yeni URL'leri çek (RSS).
2. Trafilatura clean.
3. Kalite filtresi (min 500 kelime, kaynak doğrulama).
4. Topic tagger.
5. Chunk + embed.
6. Haftalık özet rapor.

---

## Playbook: Departman Toplantısı (asenkron)

1. Lab `agent_meeting` event yayınlar.
2. Her LLM agent haftalık özetini sunar.
3. Lab orta hakem; ortak bulgu + çelişki.
4. Çıktı `reports/lab/meeting-YYYY-WW.md`.

---

> Yeni başarılı akış geldiğinde ekle.

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:10

---
