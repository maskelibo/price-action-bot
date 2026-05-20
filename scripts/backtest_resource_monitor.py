#!/usr/bin/env python3
"""Backtest resource monitor — CPU/RAM/disk telemetry for long-running backtests.

Outputs JSON lines to logs/compute_telemetry.jsonl for scalp 15m/5m/1m replays
(and any future compute-heavy task).

Usage:
  python scripts/backtest_resource_monitor.py --start-pid 12345 --duration 3600 --output logs/compute_telemetry.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import psutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def setup_logger(output_path: Path | None = None) -> logging.Logger:
    """Setup logger."""
    log = logging.getLogger("backtest_resource_monitor")
    log.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)

    return log


def get_process_metrics(pid: int) -> dict[str, Any] | None:
    """Get metrics for a single process.

    Parameters
    ----------
    pid : int
        Process ID to monitor.

    Returns
    -------
    dict or None
        Metrics dict with cpu_percent, memory_mb, io_read_mb, io_write_mb,
        num_threads, or None if process not found.
    """
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            # CPU percent (blocking 1 second sample)
            cpu_pct = p.cpu_percent(interval=None)

            # Memory
            mem_info = p.memory_info()
            memory_mb = mem_info.rss / (1024 * 1024)

            # I/O counters (platform-dependent)
            try:
                io_counters = p.io_counters()
                io_read_mb = io_counters.read_bytes / (1024 * 1024)
                io_write_mb = io_counters.write_bytes / (1024 * 1024)
            except (AttributeError, psutil.AccessDenied):
                io_read_mb = 0.0
                io_write_mb = 0.0

            num_threads = p.num_threads()

            return {
                "pid": pid,
                "cpu_percent": cpu_pct,
                "memory_mb": memory_mb,
                "io_read_mb": io_read_mb,
                "io_write_mb": io_write_mb,
                "num_threads": num_threads,
            }
    except psutil.NoSuchProcess:
        return None
    except Exception as exc:
        logging.warning(f"Error sampling PID {pid}: {exc}")
        return None


def get_disk_metrics(path: str | None = None) -> dict[str, Any]:
    """Get disk usage metrics.

    Parameters
    ----------
    path : str, optional
        Path to measure. If None, uses root or current directory.

    Returns
    -------
    dict
        Disk metrics with total_gb, used_gb, free_gb, percent.
    """
    if path is None:
        path = "/"

    try:
        usage = psutil.disk_usage(path)
        return {
            "disk_path": path,
            "total_gb": usage.total / (1024 ** 3),
            "used_gb": usage.used / (1024 ** 3),
            "free_gb": usage.free / (1024 ** 3),
            "percent_used": usage.percent,
        }
    except Exception as exc:
        logging.warning(f"Error sampling disk {path}: {exc}")
        return {
            "disk_path": path,
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "percent_used": 0,
        }


def monitor_process(
    pid: int,
    duration_seconds: int,
    sample_interval: float = 5.0,
    output_file: Path | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Monitor a process for a duration, sample at intervals.

    Parameters
    ----------
    pid : int
        Process ID to monitor.
    duration_seconds : int
        Total monitoring duration.
    sample_interval : float
        Interval between samples (seconds).
    output_file : Path, optional
        JSONL output file. If None, writes to stdout.
    log : logging.Logger, optional
        Logger instance.
    """
    if log is None:
        log = setup_logger()

    if output_file is None:
        output_file = Path("logs") / "compute_telemetry.jsonl"

    output_file.parent.mkdir(parents=True, exist_ok=True)

    log.info(f"Starting monitor for PID {pid}, duration {duration_seconds}s, "
             f"sample interval {sample_interval}s")

    start_time = time.time()
    sample_count = 0

    with open(output_file, "a") as f:
        while time.time() - start_time < duration_seconds:
            ts = datetime.now(timezone.utc).isoformat()
            metrics = get_process_metrics(pid)
            disk = get_disk_metrics()

            if metrics is None:
                log.warning(f"Process {pid} no longer exists, stopping monitor")
                break

            record = {
                "timestamp": ts,
                "elapsed_seconds": time.time() - start_time,
                "process": metrics,
                "disk": disk,
            }

            # Write JSONL
            f.write(json.dumps(record) + "\n")
            f.flush()

            sample_count += 1
            if sample_count % 20 == 0:
                log.info(f"Sample {sample_count}: CPU {metrics['cpu_percent']:.1f}%, "
                        f"Memory {metrics['memory_mb']:.0f} MB")

            time.sleep(sample_interval)

    log.info(f"Monitor completed: {sample_count} samples written to {output_file}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor backtest process CPU/RAM/disk usage."
    )
    parser.add_argument(
        "--start-pid",
        type=int,
        required=True,
        help="Process ID to monitor",
    )
    parser.add_argument(
        "--duration",
        type=int,
        required=True,
        help="Duration to monitor (seconds)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Sample interval (seconds, default 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs") / "compute_telemetry.jsonl",
        help="Output JSONL file",
    )

    args = parser.parse_args()
    log = setup_logger(args.output)

    try:
        monitor_process(
            pid=args.start_pid,
            duration_seconds=args.duration,
            sample_interval=args.interval,
            output_file=args.output,
            log=log,
        )
    except KeyboardInterrupt:
        log.info("Monitor interrupted by user")
        sys.exit(0)
    except Exception as exc:
        log.error(f"Monitor error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
