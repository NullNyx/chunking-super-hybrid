"""
Pipeline run logger.

Má»—i láº§n cháº¡y pipeline táº¡o 1 file log riÃªng (theo timestamp) trong thÆ° má»¥c logs/.
Tá»± Ä‘á»™ng lá»c error log vÃ  tá»•ng há»£p danh sÃ¡ch lesson bá»‹ failed.

Usage:
    from src.pipeline_logger import PipelineLogger

    logger = PipelineLogger(subject="toan")
    logger.info("Starting pipeline...")
    logger.step_start("B1", "PDFs -> TXT")
    logger.lesson_ok("Toan_3_Tap_1.pdf", lesson_num=5)
    logger.lesson_failed("Toan_3_Tap_1.pdf", lesson_num=7, error="...")
    logger.step_end("B1")
    logger.finish()  # writes summary + error-only log
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class PipelineLogger:
    """Structured logger for pipeline runs with per-lesson error tracking."""

    def __init__(
        self,
        subject: str = "unknown",
        log_dir: Optional[str] = None,
        level: int = logging.DEBUG,
    ) -> None:
        self.subject = subject
        self.start_time = time.time()
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Log directory
        self.log_dir = Path(log_dir) if log_dir else Path("./logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Main log file (all levels)
        self.log_file = self.log_dir / f"run_{subject}_{self.timestamp}.log"
        # Error-only log file (filtered)
        self.error_log_file = self.log_dir / f"run_{subject}_{self.timestamp}_ERRORS.log"
        # JSON summary
        self.summary_file = self.log_dir / f"run_{subject}_{self.timestamp}_summary.json"

        # Setup Python logger
        self._logger = logging.getLogger(f"pipeline.{subject}.{self.timestamp}")
        self._logger.setLevel(level)
        self._logger.propagate = False

        # File handler: all logs
        fh = logging.FileHandler(str(self.log_file), encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._logger.addHandler(fh)

        # Error file handler: ERROR+ only
        efh = logging.FileHandler(str(self.error_log_file), encoding="utf-8")
        efh.setLevel(logging.ERROR)
        efh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._logger.addHandler(efh)

        # Console handler (WARNING+)
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        self._logger.addHandler(ch)

        # Tracking data
        self._failures: List[Dict[str, Any]] = []
        self._step_stats: Dict[str, Dict[str, Any]] = {}
        self._current_step: Optional[str] = None
        self._step_start_time: float = 0.0

        # Write header
        self._logger.info("=" * 80)
        self._logger.info(f"PIPELINE RUN: {subject}")
        self._logger.info(f"Started: {datetime.now().isoformat()}")
        self._logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Basic logging
    # ------------------------------------------------------------------
    def debug(self, msg: str) -> None:
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        self._logger.info(msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        self._logger.error(msg)

    # ------------------------------------------------------------------
    # Step tracking (B1, B2, B3, B4, B5)
    # ------------------------------------------------------------------
    def step_start(self, step_id: str, description: str = "") -> None:
        """Mark the beginning of a pipeline step."""
        self._current_step = step_id
        self._step_start_time = time.time()
        self._step_stats[step_id] = {
            "description": description,
            "ok": 0,
            "skipped": 0,
            "failed": 0,
            "failures": [],
            "elapsed_seconds": 0.0,
        }
        self._logger.info("-" * 60)
        self._logger.info(f"[{step_id}] START: {description}")
        self._logger.info("-" * 60)

    def step_end(self, step_id: Optional[str] = None) -> None:
        """Mark the end of a pipeline step."""
        step_id = step_id or self._current_step
        if step_id and step_id in self._step_stats:
            elapsed = time.time() - self._step_start_time
            self._step_stats[step_id]["elapsed_seconds"] = round(elapsed, 2)
            stats = self._step_stats[step_id]
            self._logger.info(
                f"[{step_id}] END: ok={stats['ok']} skipped={stats['skipped']} "
                f"failed={stats['failed']} ({elapsed:.1f}s)"
            )
        self._current_step = None

    # ------------------------------------------------------------------
    # Per-PDF / per-lesson tracking
    # ------------------------------------------------------------------
    def pdf_ok(self, pdf_name: str, elapsed: float = 0.0) -> None:
        """Log a successful PDF processing."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["ok"] += 1
        self._logger.info(f"  [OK] {pdf_name} ({elapsed:.1f}s)")

    def pdf_skipped(self, pdf_name: str) -> None:
        """Log a skipped PDF (already exists)."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["skipped"] += 1
        self._logger.debug(f"  [SKIP] {pdf_name}")

    def pdf_failed(self, pdf_name: str, error: str, elapsed: float = 0.0) -> None:
        """Log a failed PDF processing."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["failed"] += 1
            self._step_stats[self._current_step]["failures"].append(pdf_name)

        failure_entry = {
            "step": self._current_step or "unknown",
            "pdf": pdf_name,
            "error": error,
            "elapsed_seconds": round(elapsed, 2),
        }
        self._failures.append(failure_entry)
        self._logger.error(f"  [FAILED] {pdf_name} ({elapsed:.1f}s)")
        self._logger.error(f"    Error: {error[:500]}")

    def lesson_ok(self, pdf_name: str, lesson_num: int, title: str = "") -> None:
        """Log a successful lesson split."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["ok"] += 1
        self._logger.info(f"  [OK] {pdf_name} / lesson{lesson_num}: {title}")

    def lesson_failed(
        self, pdf_name: str, lesson_num: int, error: str, title: str = ""
    ) -> None:
        """Log a failed lesson split â€” key for identifying which lesson broke."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["failed"] += 1
            self._step_stats[self._current_step]["failures"].append(
                f"{pdf_name}/lesson{lesson_num}"
            )

        failure_entry = {
            "step": self._current_step or "unknown",
            "pdf": pdf_name,
            "lesson_num": lesson_num,
            "title": title,
            "error": error,
        }
        self._failures.append(failure_entry)
        self._logger.error(
            f"  [FAILED] {pdf_name} / lesson{lesson_num} ({title})"
        )
        self._logger.error(f"    Error: {error[:500]}")

    def lesson_skipped(self, pdf_name: str, reason: str = "") -> None:
        """Log a skipped lesson (e.g. no raw_text)."""
        if self._current_step and self._current_step in self._step_stats:
            self._step_stats[self._current_step]["skipped"] += 1
        self._logger.warning(f"  [SKIP] {pdf_name}: {reason}")

    # ------------------------------------------------------------------
    # Finish & summary
    # ------------------------------------------------------------------
    def finish(self) -> Path:
        """
        Finalize the run: write summary JSON, return path to error log.
        Call this at the end of the pipeline.
        """
        total_elapsed = time.time() - self.start_time

        self._logger.info("=" * 80)
        self._logger.info(f"PIPELINE FINISHED in {total_elapsed:.1f}s")
        self._logger.info(f"Total failures: {len(self._failures)}")
        self._logger.info("=" * 80)

        # Summary JSON
        summary = {
            "subject": self.subject,
            "timestamp": self.timestamp,
            "total_elapsed_seconds": round(total_elapsed, 2),
            "total_failures": len(self._failures),
            "steps": self._step_stats,
            "failures": self._failures,
        }
        self.summary_file.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Print failure summary to console
        if self._failures:
            print("\n" + "=" * 80)
            print(f"  FAILED LESSONS/PDFs ({len(self._failures)} total):")
            print("=" * 80)
            for f in self._failures:
                lesson_info = ""
                if "lesson_num" in f:
                    lesson_info = f" / lesson{f['lesson_num']}"
                    if f.get("title"):
                        lesson_info += f" ({f['title']})"
                print(f"  [{f['step']}] {f['pdf']}{lesson_info}")
                # Print first line of error
                err_first_line = f["error"].split("\n")[-2] if "\n" in f["error"] else f["error"]
                print(f"         -> {err_first_line[:120]}")
            print("=" * 80)
            print(f"  Error log: {self.error_log_file}")
            print(f"  Summary:   {self.summary_file}")
            print("=" * 80 + "\n")
        else:
            print(f"\n  All OK! Log: {self.log_file}\n")

        # Close handlers first (release file locks)
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)

        # Cleanup: remove error log if empty (after handlers closed)
        if self.error_log_file.exists() and self.error_log_file.stat().st_size == 0:
            self.error_log_file.unlink()

        return self.summary_file
        return self.summary_file

    @property
    def failures(self) -> List[Dict[str, Any]]:
        """Get list of all failures recorded so far."""
        return self._failures

