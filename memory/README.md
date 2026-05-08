# Memory Layer

Bu klasör tüm departmanların kalıcı hafızasıdır. Memory **dolduruldukça** sistem akıllanır; her hafta Lab konsolide eder.

## Yapı

```
memory/
├── shared/                       # tüm agent'lara açık
│   ├── facts/                    # değişmez/yarı-değişmez gerçekler
│   ├── lessons/                  # post-mortem'den ekosistem dersleri
│   ├── decisions/                # ADR — sistem geneli kararlar
│   └── glossary.md               # ortak terimler
│
└── <agent_name>/                 # her LLM agent için:
    ├── identity.md               # statik persona + rules + KPI
    ├── know_how.md               # tekrarlanan iş akışları
    ├── learning.md               # öğrenilen dersler
    ├── decisions/                # bu agent'ın aldığı kararlar
    └── runtime/                  # JSONL kısa vadeli (gitignore)
```

## Tipler

| Tip | Açıklama | Yazım Sıklığı |
|---|---|---|
| **identity** | Kim olduğun, ne için varsın, hangi kural setiyle. Statik. | Çok nadir |
| **know_how** | Playbook: "X durumda Y adımları." | Yeni iş akışı çıktığında |
| **learning** | "Şu hatayı yaptım çünkü..." / "Bu işe yaradı çünkü..." | Hafta sonu |
| **decisions** | ADR: bağlam, seçenekler, seçim, sonuç. | Her büyük karar |
| **runtime** | Kısa vadeli scratch JSONL. Lab konsolide eder. | Sürekli |

## Konsolidasyon Döngüsü (Lab tarafından)

Her Pazar:
1. Tüm `runtime/episodic.jsonl` dosyaları okunur.
2. Tekrar eden başarısızlıklar → `learning.md`'ye.
3. Tekrar eden başarılar → `know_how.md`'ye.
4. Sistem geneli dersler → `memory/shared/lessons/`.
5. Runtime arşivlenir (`runtime/archive/YYYY-WW/`).

## Kurallar

- Identity dışında her dosya append-only kabul edilir; eski entry'ler silinmez (revize edilirse "(revised: ...)" notu).
- Tarih + agent + slug + confidence (low/med/high) zorunlu.
- Memory dosyaları MARKDOWN; runtime JSONL.
- Hassas bilgi (API key, kullanıcı verisi) memory'de YASAK.
