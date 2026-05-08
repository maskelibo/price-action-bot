"""Notifications package — Telegram ve diğer alert kanalları."""
from .telegram import send_critical, send_telegram

__all__ = ["send_telegram", "send_critical"]
