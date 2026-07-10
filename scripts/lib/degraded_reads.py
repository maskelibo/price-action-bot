"""KALAN_ISLER #8 (2026-07-10): borsa okumalarında "başarı-şekilli boş dönüş" görünürlüğü.

Sorun: canlı yoldaki borsa-okuma sarmalayıcıları (fetch_positions / open-orders /
algo-orders / ticker / balance) exception yakalayıp []/{}/None/0 döndürüyor —
loglarda "0 pozisyon" ile "okuma çöktü" AYIRT EDİLEMİYOR.

Tasarım kısıtı (Principal: yeni hata yaratma): kontrol akışı DEĞİŞMEZ — çağıran
sarmalayıcıların dönüş tipleri/değerleri birebir aynı kalır. Bu modül yalnız
gözlemlenebilirlik ekler: modül-seviye hafif sayaç ``_DEGRADED_READS``
(kaynak → sayaç + son-hata-ts) + tek satır ``DEGRADED_READ:`` log işareti.
``record_degraded_read`` ASLA exception yükseltmez (davranış-parite kutsal).

Kullanım (exception dalında TEK satır):

    except Exception as exc:
        record_degraded_read("fetch_futures_state.fetch_positions", exc)
        active_pos = []          # dönüş ESKİYLE birebir aynı

Halihazırda kendi log satırı olan sahalarda yalnız sayaç: ``emit_log=False``.
Daemon sahalarında marker'ı futures_daemon.log'a düşürmek için ``log_fn=log``.

POS_CHECK özeti ``total_degraded_reads()`` delta'sıyla ``[DEGRADED:n]`` eki basar
(bkz. scripts/futures_daemon.py position_check).
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from typing import Any

_LOCK = threading.Lock()

# kaynak → {"count": toplam hata sayısı, "last_error_ts": epoch saniye (UTC)}
_DEGRADED_READS: dict[str, dict[str, float]] = {}

# Hızlı delta-snapshot için toplam sayaç (POS_CHECK [DEGRADED:n] eki).
_TOTAL_COUNT: int = 0

_MARKER = "DEGRADED_READ"


def record_degraded_read(
    source: str,
    err: BaseException | None = None,
    *,
    log_fn: Callable[[str], Any] | None = None,
    emit_log: bool = True,
) -> None:
    """Borsa-okuma exception dalından çağrılır: sayaç artır + log işareti üret.

    Args:
        source: saha adı (örn. "fetch_futures_state.fetch_positions").
        err: yakalanan exception (marker'a tip+ilk 80 karakter eklenir).
        log_fn: marker'ın basılacağı logger (örn. daemon ``log``); None → stderr
            (launchd stderr log'una düşer — _emit_read_fail_summary ile aynı kanal).
        emit_log: False → yalnız sayaç (sahada zaten kendi log satırı varsa).

    ASLA raise etmez; dönüş değeri yok — çağıranın akışı/dönüşü değişmez.
    """
    global _TOTAL_COUNT
    try:
        with _LOCK:
            rec = _DEGRADED_READS.setdefault(
                str(source), {"count": 0.0, "last_error_ts": 0.0}
            )
            rec["count"] += 1
            rec["last_error_ts"] = time.time()
            _TOTAL_COUNT += 1
        if not emit_log:
            return
        msg = f"{_MARKER}: {source} — boş dönüş HATA kaynaklı"
        if err is not None:
            msg += f" ({type(err).__name__}: {str(err)[:80]})"
        if log_fn is not None:
            log_fn(msg)
        else:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
    except Exception:
        # Gözlemlenebilirlik yolu canlı akışı ASLA bozamaz.
        pass


def total_degraded_reads() -> int:
    """Toplam degraded-read sayısı (tüm kaynaklar; process ömrü boyunca)."""
    with _LOCK:
        return _TOTAL_COUNT


def degraded_reads_snapshot() -> dict[str, dict[str, float]]:
    """Kaynak-bazlı kopya: {kaynak: {"count": n, "last_error_ts": epoch}}."""
    with _LOCK:
        return {k: dict(v) for k, v in _DEGRADED_READS.items()}


def reset_degraded_reads() -> None:
    """Testler için: sayaç + kayıtları sıfırla."""
    global _TOTAL_COUNT
    with _LOCK:
        _DEGRADED_READS.clear()
        _TOTAL_COUNT = 0
