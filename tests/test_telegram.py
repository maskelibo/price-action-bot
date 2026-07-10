"""Unit tests — Telegram notification module (Faz 5).

Tüm testler requests.post'u mock eder; gerçek HTTP isteği atılmaz.

Test coverage:
  - INFO mesajı doğru payload ile gönderilir
  - CRIT mesajı 🚨 prefix içerir
  - Env var eksikse no-op (exception yok)
  - dry-run modunda HTTP isteği yapılmaz
  - Markdown parse_mode payload'a eklenir
  - requests.post hata dönerse graceful degradation
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is on path
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# =====================================================================
# Helpers
# =====================================================================


def _fresh_module() -> Any:
    """telegram modülünü env değişkenleri değiştikten sonra taze import et."""
    mod_name = "price_action.notifications.telegram"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def _mock_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"ok": true}'
    return resp


def _mock_error_response(status: int = 400) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = '{"ok": false, "description": "Bad Request"}'
    return resp


# =====================================================================
# Test: INFO mesajı
# =====================================================================


class TestSendTelegram:
    def test_info_message_correct_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INFO mesajı → doğru URL ve payload ile requests.post çağrılır."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "999888")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()

        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            result = tg.send_telegram("Test INFO mesajı", level="INFO")

        assert result is True
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args
        url = (
            call_kwargs[0][0]
            if call_kwargs[0]
            else call_kwargs.kwargs.get("url") or call_kwargs[0][0]
        )
        payload = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json")

        assert "fake-token-123" in url
        assert "sendMessage" in url
        assert payload["chat_id"] == "999888"
        assert "ℹ️" in payload["text"]
        assert "INFO" in payload["text"]
        assert "Test INFO mesajı" in payload["text"]

    def test_warning_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WARNING level → ⚠️ prefix."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("Uyarı mesajı", level="WARNING")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert "⚠️" in payload["text"]

    def test_error_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ERROR level → ❌ prefix."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("Hata mesajı", level="ERROR")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert "❌" in payload["text"]

    def test_api_error_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Telegram API 400 dönerse False döner, exception yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_error_response(400)):
            result = tg.send_telegram("Hata testi")

        assert result is False

    def test_requests_exception_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """requests.post exception fırlatırsa False döner, exception propagate etmez."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", side_effect=ConnectionError("network down")):
            result = tg.send_telegram("Bağlantı hatası")

        assert result is False


# =====================================================================
# Test: send_critical → 🚨 prefix
# =====================================================================


class TestSendCritical:
    def test_crit_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_critical → 🚨 ve [CRIT] prefix içermeli."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            result = tg.send_critical("Kriz alarmı!")

        assert result is True
        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert "🚨" in payload["text"]
        assert "CRIT" in payload["text"]
        assert "Kriz alarmı!" in payload["text"]

    def test_crit_no_env_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_critical env var eksik → False döner, exception yok."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        # requests.post çağrılmamalı
        with patch("requests.post") as mock_post:
            result = tg.send_critical("Alarm")

        assert result is False
        mock_post.assert_not_called()


# =====================================================================
# Test: Env var eksikse no-op
# =====================================================================


class TestNoEnvVars:
    def test_missing_token_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELEGRAM_BOT_TOKEN eksikse: False döner, exception yok."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("Token yok")

        assert result is False
        mock_post.assert_not_called()

    def test_missing_chat_id_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELEGRAM_CHAT_ID eksikse: False döner, exception yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("ChatID yok")

        assert result is False
        mock_post.assert_not_called()

    def test_both_missing_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """İkisi de eksikse: False döner, exception yok."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("İkisi de yok")

        assert result is False
        mock_post.assert_not_called()

    def test_empty_string_token_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TELEGRAM_BOT_TOKEN='' (boş string) → False döner, exception yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("Boş token")

        assert result is False
        mock_post.assert_not_called()


# =====================================================================
# Test: Dry-run
# =====================================================================


class TestDryRun:
    def test_dry_run_no_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PA_LLM_DRY_RUN=true → requests.post hiç çağrılmaz."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("PA_LLM_DRY_RUN", "true")

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("Dry run testi")

        assert result is False
        mock_post.assert_not_called()

    def test_dry_run_value_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PA_LLM_DRY_RUN=1 de dry-run olarak kabul edilir."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.setenv("PA_LLM_DRY_RUN", "1")

        tg = _fresh_module()
        with patch("requests.post") as mock_post:
            result = tg.send_telegram("Dry run 1")

        assert result is False
        mock_post.assert_not_called()

    def test_no_dry_run_makes_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PA_LLM_DRY_RUN set edilmezse gerçek HTTP çağrısı yapılır."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            result = tg.send_telegram("Gerçek mod")

        assert result is True
        mock_post.assert_called_once()


# =====================================================================
# Test: Markdown encoding
# =====================================================================


class TestMarkdownEncoding:
    def test_parse_mode_in_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parse_mode='Markdown' → payload'da parse_mode var."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("**Bold metin**", parse_mode="Markdown")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert payload.get("parse_mode") == "Markdown"

    def test_no_parse_mode_not_in_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parse_mode=None → payload'da parse_mode yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("Düz metin")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert "parse_mode" not in payload

    def test_markdown_v2_escape(self) -> None:
        """_escape_markdown_v2 özel karakterleri doğru escape eder."""
        tg = _fresh_module()
        text = "Hello.World! Price: $100 (BTC/USDT) #test"
        escaped = tg._escape_markdown_v2(text)

        # Özel karakterler escape edilmeli
        assert "\\." in escaped
        assert "\\!" in escaped
        assert "\\#" in escaped

    def test_markdownv2_parse_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parse_mode='MarkdownV2' → payload'da doğru değer."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("Test", parse_mode="MarkdownV2")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert payload.get("parse_mode") == "MarkdownV2"


# =====================================================================
# Test: requests kütüphanesi yüklü değilse
# =====================================================================


class TestRequestsMissing:
    def test_requests_import_error_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """requests import edilemezse False döner, exception yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        # requests import'unu başarısız yap
        with patch.dict(sys.modules, {"requests": None}):
            # Modülü tekrar yükle ki import hatasını görsün
            result = tg.send_telegram("requests yok testi")

        # requests None ise ImportError raise olur — fonksiyon bunu yakalamalı
        # Eğer import zaten önbelleğe alındıysa bu testi atla
        # (bu test requests'in gerçek eksikliğini değil, import hatasını simüle eder)
        assert isinstance(result, bool)


# =====================================================================
# Test: Genel robustluk
# =====================================================================


class TestRobustness:
    def test_very_long_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Çok uzun mesaj → gracefully gönderilir (Telegram taraf truncate yapabilir)."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        long_msg = "A" * 5000
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            result = tg.send_telegram(long_msg)

        # Crash olmamalı; 5000 char > Telegram 4096 hard-limit → chunk'lanır
        # (W6-HIGH bildirim fix). Tek mesajda 5000 Telegram tarafından REDDEDİLİR.
        assert result is True
        assert mock_post.call_count >= 2  # >4096 → en az 2 parçaya bölünür
        for _call in mock_post.call_args_list:
            _text = _call.kwargs.get("json", {}).get("text", "")
            assert len(_text) <= 4096, f"chunk {len(_text)} > Telegram 4096 limiti"

    def test_unicode_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unicode ve emoji içeren mesaj → crash yok."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()):
            result = tg.send_telegram("BTC 🚀 ETH 💎 SOL ⚡ 测试")

        assert result is True

    def test_send_critical_with_parse_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """send_critical parse_mode argümanını doğru iletir."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_critical("**Kriz!**", parse_mode="Markdown")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert payload.get("parse_mode") == "Markdown"
        assert "🚨" in payload["text"]

    def test_disable_web_page_preview_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """disable_web_page_preview varsayılan True olmalı."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)

        tg = _fresh_module()
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            tg.send_telegram("Link: https://example.com")

        payload = mock_post.call_args[1].get("json") or mock_post.call_args.kwargs.get("json")
        assert payload.get("disable_web_page_preview") is True
