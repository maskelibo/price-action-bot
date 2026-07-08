"""Bildirim paketi fix'leri — kapanış sprinti 2026-07-08.

Kapsam (DERIN_DENETIM W5/W6-HIGH "bildirim paketi"):
  N1) push_report çok-parça imhası: her chunk AYNI alert_type ile throttle'a
      giriyordu → 1. chunk gönderilir, 2+ buffer'a düşer (Daily Truth Report'un
      gövdesi kayboluyordu). Fix: rapor-bazlı TEK throttle kararı
      (TelegramThrottle.send_report) — izin varsa TÜM parçalar gider.
  N2) Buffer imhası: pencere bitince gelen yeni mesaj, buffer'daki eskileri
      GÖNDERMEDEN siliyordu. Fix: drain — buffer içeriği giden mesaja mini-digest
      olarak eklenir (hiçbir alarm kanıtsız ölmez).
  N3) CRIT buffer'da kaybolabiliyordu: level'e bakılmadan pencere uygulanıyordu.
      Fix: CRIT için pencere tabanı crit_floor_seconds (120s) — CRIT en fazla
      2dk gecikir, asla saatlik pencereye takılmaz.
  N4) flush_digest hiç çağrılmıyordu → scheduler'a saatlik job (source-pin test).
  N5) send_telegram 4096 üstünü bölmüyordu → Telegram 400, mesaj komple ölür
      (uzun CRIT sınıfı). Fix: alt-katman chunk'lama.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.ops.telegram_throttle import TelegramThrottle  # noqa: E402

# ═════════════════════════════════════════════════════════════════════════════
# N1 — send_report: çok parçalı rapor TEK throttle kararıyla
# ═════════════════════════════════════════════════════════════════════════════


class TestSendReportMultipart:
    def test_all_chunks_delivered_on_first_send(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            ok = throttle.send_report("daily_truth", ["parça1", "parça2", "parça3"])
        assert ok is True
        assert mock_send.call_count == 3  # ESKİ bug: 1 gider, 2 kaybolurdu
        sent_texts = [c.args[0] for c in mock_send.call_args_list]
        assert sent_texts == ["parça1", "parça2", "parça3"]

    def test_second_report_within_window_fully_throttled(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            throttle.send_report("daily_truth", ["a", "b"])
            ok2 = throttle.send_report("daily_truth", ["c", "d"])
        assert ok2 is False
        assert mock_send.call_count == 2  # yalnız ilk raporun 2 parçası
        # throttle'lanan rapor kanıt olarak buffer'da
        assert "daily_truth" in throttle.digest_buffer

    def test_different_report_types_independent(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            throttle.send_report("daily_truth", ["a"])
            ok = throttle.send_report("weekly_exec", ["b", "c"])
        assert ok is True
        assert mock_send.call_count == 3

    def test_crit_report_uses_send_critical(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_critical") as mock_crit:
            mock_crit.return_value = True
            ok = throttle.send_report("halt_report", ["p1", "p2"], level="CRITICAL")
        assert ok is True
        assert mock_crit.call_count == 2


# ═════════════════════════════════════════════════════════════════════════════
# N2 — buffer drain: silme yok, mini-digest ile teslim
# ═════════════════════════════════════════════════════════════════════════════


class TestBufferDrainNotDelete:
    def test_buffered_messages_attached_to_next_send(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            throttle.send_throttled("risk_warn", "mesaj-1")
            throttle.send_throttled("risk_warn", "mesaj-2-buffer")  # pencere içi → buffer
            # pencereyi bitir
            throttle.last_sent["risk_warn"] = datetime.now(UTC) - timedelta(seconds=700)
            throttle.send_throttled("risk_warn", "mesaj-3")
        assert mock_send.call_count == 2
        last_text = mock_send.call_args_list[-1].args[0]
        assert "mesaj-3" in last_text
        # ESKİ bug: mesaj-2 sessizce silinirdi; artık mini-digest içinde
        assert "mesaj-2-buffer" in last_text

    def test_drain_caps_at_three_plus_counter(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            throttle.send_throttled("x", "ilk")
            for i in range(6):
                throttle.send_throttled("x", f"buf-{i}")
            throttle.last_sent["x"] = datetime.now(UTC) - timedelta(seconds=700)
            throttle.send_throttled("x", "yeni")
        last_text = mock_send.call_args_list[-1].args[0]
        assert "buf-0" in last_text and "buf-2" in last_text
        assert "+3" in last_text  # 6 buffer → 3 gösterildi, +3 sayaç
        assert "buf-5" not in last_text

    def test_buffer_emptied_after_drain(self):
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            throttle.send_throttled("x", "ilk")
            throttle.send_throttled("x", "buf")
            throttle.last_sent["x"] = datetime.now(UTC) - timedelta(seconds=700)
            throttle.send_throttled("x", "yeni")
        assert throttle.digest_buffer.get("x") in (None, [])


# ═════════════════════════════════════════════════════════════════════════════
# N3 — CRIT pencere tabanı: CRIT asla saatlik pencereye takılmaz
# ═════════════════════════════════════════════════════════════════════════════


class TestCritFloor:
    def test_crit_bypasses_long_window(self):
        """INFO penceresi 600s doluyken (300s geçmiş) CRIT GÖNDERİLMELİ."""
        throttle = TelegramThrottle(window_seconds=600)
        with (
            patch("price_action.ops.telegram_throttle.send_telegram") as mock_send,
            patch("price_action.ops.telegram_throttle.send_critical") as mock_crit,
        ):
            mock_send.return_value = True
            mock_crit.return_value = True
            throttle.send_throttled("dms_alarm", "info-1")  # pencere başlar
            throttle.last_sent["dms_alarm"] = datetime.now(UTC) - timedelta(seconds=300)
            info_ok = throttle.send_throttled("dms_alarm", "info-2")  # 300<600 → buffer
            crit_ok = throttle.send_throttled("dms_alarm", "KRİTİK", level="CRITICAL")
        assert info_ok is False  # INFO throttle davranışı DEĞİŞMEDİ
        assert crit_ok is True  # CRIT floor (120s) < 300s geçmiş → gitti
        assert mock_crit.call_count == 1

    def test_crit_still_floored_against_rapid_spam(self):
        """Aynı CRIT tipi 2sn arayla → floor içinde, buffer (fırtına koruması)."""
        throttle = TelegramThrottle(window_seconds=600)
        with patch("price_action.ops.telegram_throttle.send_critical") as mock_crit:
            mock_crit.return_value = True
            ok1 = throttle.send_throttled("ks_fail", "crit-1", level="CRITICAL")
            ok2 = throttle.send_throttled("ks_fail", "crit-2", level="CRITICAL")
        assert ok1 is True
        assert ok2 is False  # 0s < floor 120s → buffer (sonraki send'de drain)
        assert mock_crit.call_count == 1


# ═════════════════════════════════════════════════════════════════════════════
# N4 — flush_digest scheduler'a bağlı (source-pin)
# ═════════════════════════════════════════════════════════════════════════════


class TestFlushDigestWired:
    def test_scheduler_has_hourly_flush_job(self):
        src = (ROOT / "src/price_action/orchestrator/scheduler.py").read_text(encoding="utf-8")
        assert '"telegram_digest_flush"' in src
        assert "_job_telegram_digest_flush" in src
        assert "flush_digest()" in src


# ═════════════════════════════════════════════════════════════════════════════
# N5 — send_telegram 4096 üstünü bölerek gönderir (uzun CRIT ölmez)
# ═════════════════════════════════════════════════════════════════════════════


class TestTelegramLowLevelChunking:
    def _run(self, message: str, level: str = "CRIT"):
        import price_action.notifications.telegram as tg

        posts = []

        def fake_post(url, json=None, timeout=None):
            posts.append(json["text"])
            resp = MagicMock()
            resp.status_code = 200
            return resp

        with (
            patch.object(tg, "_is_dry_run", return_value=False),
            patch.object(tg, "_get_credentials", return_value=("tok", "chat")),
            patch("requests.post", side_effect=fake_post),
        ):
            ok = tg.send_telegram(message, level=level)
        return ok, posts

    def test_short_message_single_post(self):
        ok, posts = self._run("kısa mesaj")
        assert ok is True
        assert len(posts) == 1

    def test_long_crit_split_not_dropped(self):
        """ESKİ bug: >4096 → Telegram 400 → mesaj KOMPLE kaybolurdu."""
        long_msg = "satır çok uzun bir kritik alarm içeriği\n" * 200  # ~8000 char
        ok, posts = self._run(long_msg, level="CRIT")
        assert ok is True
        assert len(posts) >= 2  # bölündü
        for p in posts:
            assert len(p) <= 4096  # Telegram hard limit
        # içerik kaybolmadı (ilk ve son satır bir parçada mevcut)
        joined = "".join(posts)
        assert joined.count("kritik alarm") >= 190


# ═════════════════════════════════════════════════════════════════════════════
# N1 entegrasyonu — push_report rapor-bazlı throttle kullanıyor
# ═════════════════════════════════════════════════════════════════════════════


class TestPushReportIntegration:
    def test_push_report_delivers_all_chunks(self, tmp_path, monkeypatch):
        import price_action.orchestrator.notifications as notif
        from price_action.ops import telegram_throttle as tt

        monkeypatch.setenv("PA_CEO_PUSH_TELEGRAM", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
        monkeypatch.delenv("PA_LLM_DRY_RUN", raising=False)
        tt.reset_telegram_throttle()
        report = tmp_path / "truth.md"
        report.write_text("satır içeriği uzun rapor\n" * 300, encoding="utf-8")  # ~7500c → 3+ chunk

        with patch("price_action.ops.telegram_throttle.send_telegram") as mock_send:
            mock_send.return_value = True
            ok = notif.push_report(report, caption="Daily Truth", alert_type="daily_truth")
        tt.reset_telegram_throttle()
        assert ok is True
        assert mock_send.call_count >= 3  # ESKİ bug: 1 çağrı (gerisi buffer'a)
