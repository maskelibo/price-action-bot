"""Markdown chunker.

Bir markdown belgesini başlık hiyerarşisini koruyarak chunk'lara böler.
Hedef boyut 512 "token" (kaba kelime sayımıyla yaklaşık) ve 64 token overlap.
``tiktoken`` mevcutsa gerçek tokenizer kullanılır; yoksa kelime bazlı bir
yaklaşıklık kullanılır.

Her ``Chunk``:
- ``text``: chunk içeriği
- ``heading_path``: bu chunk'ın başlık yolu (örn. "Price Action > Pin Bar")
- ``token_count``: tahmini token sayısı
- ``index``: belge içindeki sıra
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

try:  # pragma: no cover - opsiyonel bağımlılık
    import tiktoken  # type: ignore[import-not-found]

    _ENC = tiktoken.get_encoding("cl100k_base")

    def _token_count(text: str) -> int:
        return len(_ENC.encode(text))

    def _split_by_tokens(text: str, n: int) -> list[str]:
        toks = _ENC.encode(text)
        out: list[str] = []
        for i in range(0, len(toks), n):
            out.append(_ENC.decode(toks[i : i + n]))
        return out

except Exception:  # pragma: no cover - tiktoken yoksa kelime bazlı

    def _token_count(text: str) -> int:
        # Kaba yaklaşıklık: 1 token ~ 0.75 word; biz 1 word = 1 token sayalım.
        return len(text.split())

    def _split_by_tokens(text: str, n: int) -> list[str]:
        words = text.split()
        return [" ".join(words[i : i + n]) for i in range(0, len(words), n)]


DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


@dataclass
class Chunk:
    """Bir markdown chunk'ı."""

    text: str
    heading_path: str
    token_count: int
    index: int
    metadata: dict[str, str] = field(default_factory=dict)


def _walk_sections(markdown: str) -> Iterable[tuple[str, str]]:
    """Markdown'ı `(heading_path, body_text)` çiftleri halinde dolaşır."""
    lines = markdown.splitlines()
    headings: list[tuple[int, str]] = []  # stack: [(level, title), ...]
    buf: list[str] = []
    current_path = ""

    def _path_str(stack: list[tuple[int, str]]) -> str:
        return " > ".join(t for _, t in stack) if stack else "(root)"

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            # Önce mevcut buffer'ı flush et
            if buf:
                yield current_path, "\n".join(buf).strip()
                buf = []
            level = len(m.group(1))
            title = m.group(2).strip()
            # Stack'i bu level'a göre kırp
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            current_path = _path_str(headings)
        else:
            buf.append(line)
    if buf:
        yield current_path, "\n".join(buf).strip()


def chunk_markdown(
    markdown: str,
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    base_metadata: dict[str, str] | None = None,
) -> list[Chunk]:
    """Bir markdown belgesini chunk'lara böler.

    Section bazında dolaşır; section çok uzunsa token-overlap'lı dilimlere
    böler. Boş section'lar atlanır.
    """
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be > 0")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("0 <= overlap_tokens < chunk_tokens olmalı")

    base_md = dict(base_metadata or {})
    out: list[Chunk] = []
    idx = 0
    for path, body in _walk_sections(markdown):
        body = body.strip()
        if not body:
            continue
        n = _token_count(body)
        if n <= chunk_tokens:
            out.append(
                Chunk(
                    text=body,
                    heading_path=path,
                    token_count=n,
                    index=idx,
                    metadata={**base_md, "heading": path},
                )
            )
            idx += 1
            continue
        # Uzun section: overlap'lı dilimle
        # Implementasyon: her dilim chunk_tokens uzunluk; bir sonraki dilim
        # `chunk_tokens - overlap_tokens` adım kaydırılır.
        try:  # pragma: no cover - tiktoken aktifse buradan geçer
            import tiktoken  # type: ignore[import-not-found]  # noqa: F401

            enc = _ENC  # type: ignore[name-defined]
            tokens = enc.encode(body)
            step = chunk_tokens - overlap_tokens
            for i in range(0, len(tokens), step):
                slice_toks = tokens[i : i + chunk_tokens]
                if not slice_toks:
                    break
                text = enc.decode(slice_toks)
                out.append(
                    Chunk(
                        text=text,
                        heading_path=path,
                        token_count=len(slice_toks),
                        index=idx,
                        metadata={**base_md, "heading": path},
                    )
                )
                idx += 1
                if i + chunk_tokens >= len(tokens):
                    break
        except Exception:
            words = body.split()
            step = chunk_tokens - overlap_tokens
            for i in range(0, len(words), step):
                slice_words = words[i : i + chunk_tokens]
                if not slice_words:
                    break
                text = " ".join(slice_words)
                out.append(
                    Chunk(
                        text=text,
                        heading_path=path,
                        token_count=len(slice_words),
                        index=idx,
                        metadata={**base_md, "heading": path},
                    )
                )
                idx += 1
                if i + chunk_tokens >= len(words):
                    break
    return out
