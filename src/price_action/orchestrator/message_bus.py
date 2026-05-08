"""Asenkron in-process message bus.

Topic bazlı pub/sub. Her topic bir ``asyncio.Queue`` ve aboneler bir async
iterator alır. Test edilebilirliğe öncelik verir; tek süreçte çalışır
(birden çok süreç gerekirse Redis ile değiştirilir — ileride).
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import AsyncIterator

from price_action.contracts import AgentMessage
from price_action.logging_config import logger


class MessageBus:
    """Topic bazlı asenkron pub/sub."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[AgentMessage]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, msg: AgentMessage) -> None:
        async with self._lock:
            queues = list(self._subs.get(msg.topic, []))
        for q in queues:
            await q.put(msg)
        logger.debug(
            "bus.publish",
            extra={
                "topic": msg.topic,
                "sender": msg.sender,
                "recipient": msg.recipient,
                "subs": len(queues),
            },
        )

    @asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator[asyncio.Queue[AgentMessage]]:
        q: asyncio.Queue[AgentMessage] = asyncio.Queue()
        async with self._lock:
            self._subs[topic].append(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subs[topic].remove(q)

    async def stream(self, topic: str) -> AsyncIterator[AgentMessage]:
        """Topic'i tek seferlik async iterator olarak yayınlar."""
        async with self.subscribe(topic) as q:
            while True:
                msg = await q.get()
                yield msg
