---
agent: researcher
type: know_how
created: 2026-05-08
---

# Researcher Know-How

> Tekrarlanan araştırma akışları.

---

## Playbook: Yeni Hipotez Üretim

1. RAG retrieve (k=10 chunk, ilgili kalıp/teknik).
2. Tema sentezle, somut iddiaya dönüştür.
3. Pre-registration: `hypotheses/<date>-<slug>.md` yaz.
4. Backtest config'i hipotezden türet.
5. Backtest çalıştır.
6. Robustness suite (zorunlu).
7. Karar yaz: terfi adayı / red.

---

## Playbook: Walk-Forward

- 3y train + 6m test, step 3m.
- Optuna n_trials = 100 (TPE + Median pruner).
- Objective: OOS Sharpe (default).
- Sonra Bonferroni / Benjamini-Hochberg düzeltmesi.

---

## Playbook: Stress Test Periyodları

Her aday için zorunlu:
- 2022-05 (LUNA çöküşü)
- 2022-11 (FTX iflası)
- 2023-03 (USDC depeg)
- 2024-08 (Yen carry unwind)

Bu dilimlerde yıkıcı kayıp yoksa OK.

---

## Playbook: Survivorship Kontrolü

- Sembol evrenini delisting'leri DAHİL ederek kur.
- Backtest'in başlangıcında listede olup sonra delist olanları, delisting'e kadar dahil et.
- Yeni listing'leri listing tarihinden itibaren dahil et.

---

> Yeni başarılı akış çıktığında alta ekle.

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:6, hypothesis:5

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:7, hypothesis:6

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:8, hypothesis:7

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:35, hypothesis:34

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:41, hypothesis:40

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:47, hypothesis:46

---

### 2026-05-25 — weekly-tag-snapshot-20260525 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:54, hypothesis:53

---

### 2026-05-26 — weekly-tag-snapshot-20260526 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:69, hypothesis:68

---

### 2026-05-26 — weekly-tag-snapshot-20260526 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:76, hypothesis:75

---

### 2026-05-26 — weekly-tag-snapshot-20260526 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:83, hypothesis:82

---

### 2026-05-26 — weekly-tag-snapshot-20260526 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:90, hypothesis:89

---

### 2026-05-26 — weekly-tag-snapshot-20260526 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:97, hypothesis:96

---

### 2026-05-31 — weekly-tag-snapshot-20260531 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:144, hypothesis:143

---

### 2026-06-07 — weekly-tag-snapshot-20260607 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:71, hypothesis:71

---

### 2026-06-14 — weekly-tag-snapshot-20260614 (med)
- tags: consolidation

Haftalık episodic tag dağılımı: llm_call:75, hypothesis:75

---
