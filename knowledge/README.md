# Knowledge Layer (RAG Corpus)

Price action literatürü, akademik makaleler, trading firma blog'ları ve YouTube transkriptlerinin lokal RAG store'u. ChromaDB persistent.

## Yapı

```
knowledge/
├── seeds.yaml                    # canonical kaynak listesi
├── articles/
│   ├── raw/                      # ham HTML/PDF (gitignore)
│   └── clean/                    # markdown'a normalize
├── transcripts/                  # YouTube transkript markdown'ları
├── books/                        # referans özet (telif sebebiyle full text yok)
├── papers/                       # arXiv / SSRN PDF özetleri
├── index/                        # ChromaDB persistent (gitignore)
└── cache/                        # crawl cache (gitignore)
```

## Akış

1. **Seed:** `seeds.yaml` doldurulu — canonical kaynaklar.
2. **Ingest:** `pa-rag ingest` — yeni kaynakları çek, temizle, embed et.
3. **Refresh:** Lab haftalık çalıştırır.
4. **Sorgu:** Researcher `rag.retrieve(query, k=8)`.

## Embedding Modeli

- **Default:** `sentence-transformers/all-MiniLM-L6-v2` (lokal, hızlı, 384 dim).
- **Yüksek kalite:** `BAAI/bge-large-en-v1.5` (1024 dim, daha yavaş — Researcher detaylı sorgu için).

## Chunk Stratejisi

- 512 token chunk, 64 overlap.
- Markdown başlık hiyerarşisi metadata olarak.
- Hash dedup.

## Metadata Şeması

```yaml
source_id: <slug>
source_type: book | article | paper | transcript | blog | rss
author: ...
url: ...
published_date: YYYY-MM-DD
ingested_date: YYYY-MM-DD
language: en | tr
topic_tags: [pattern, structure, risk, ml, microstructure, behavioral, ...]
quality_score: 1..5  # Lab değerlendirir
content_hash: sha256
```

## Yasaklar

- ❌ Telif ihlali: kitap full text yok, özet/notlar OK.
- ❌ Düşük kalite içerik: clickbait, "secret indicator" videoları otomatik elenir (kaynak otoritesi + kelime sayısı + Lab onayı).
- ❌ Trading sinyali hizmeti / paylı grup içerikleri.
