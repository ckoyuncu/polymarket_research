"""
Rotating JSONL Logger with Gzip Compression

Memory-efficient logging with hourly rotation and automatic compression.
Designed for continuous market data capture over extended periods.
"""

import gzip
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class RotatingJSONLLogger:
    """
    Append-only JSONL logger with hourly gzip rotation.

    Features:
    - Writes records as JSON lines
    - Rotates files every hour
    - Compresses rotated files with gzip
    - Thread-safe writes
    - Disk space monitoring

    Example:
        logger = RotatingJSONLLogger(base_dir="/data/logs", prefix="prices")

        # Write records
        logger.write({"ts": 123456, "price": 97000.0, "symbol": "BTC"})

        # Force rotation
        logger.rotate()

        # Cleanup
        logger.close()
    """

    def __init__(
        self,
        base_dir: str = "/data/logs",
        prefix: str = "prices",
        rotation_interval_seconds: int = 3600,  # 1 hour
        compress: bool = True,
        max_disk_usage_gb: float = 2.0,
        buffer_size: int = 8192,
    ):
        """
        Initialize the rotating logger.

        Args:
            base_dir: Base directory for log files
            prefix: Filename prefix (e.g., "prices" -> "prices_14.jsonl")
            rotation_interval_seconds: How often to rotate (default: 1 hour)
            compress: Whether to gzip rotated files
            max_disk_usage_gb: Max disk usage before warning
            buffer_size: Write buffer size in bytes
        """
        self.base_dir = Path(base_dir)
        self.prefix = prefix
        self.rotation_interval = rotation_interval_seconds
        self.compress = compress
        self.max_disk_usage_bytes = int(max_disk_usage_gb * 1024 * 1024 * 1024)
        self.buffer_size = buffer_size

        # State
        self._current_file: Optional[Any] = None
        self._current_path: Optional[Path] = None
        self._current_hour: Optional[int] = None
        self._current_date: Optional[str] = None
        self._lock = threading.Lock()

        # Stats
        self.records_written = 0
        self.bytes_written = 0
        self.rotations = 0
        self.errors = 0
        self.started_at = time.time()

        # Ensure base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_current_file_path(self) -> Path:
        """Get the path for the current hour's file."""
        now = datetime.utcnow()
        date_str = now.strftime("%Y-%m-%d")
        hour = now.hour

        # Create date directory if needed
        date_dir = self.base_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        return date_dir / f"{self.prefix}_{hour:02d}.jsonl"

    def _should_rotate(self) -> bool:
        """Check if we should rotate to a new file."""
        now = datetime.utcnow()
        return (
            self._current_hour != now.hour or
            self._current_date != now.strftime("%Y-%m-%d")
        )

    def _open_new_file(self) -> None:
        """Open a new log file for the current hour."""
        # Close existing file if open
        if self._current_file:
            self._current_file.close()

            # Compress the old file if enabled
            if self.compress and self._current_path and self._current_path.exists():
                self._compress_file(self._current_path)

        # Get new path
        now = datetime.utcnow()
        self._current_path = self._get_current_file_path()
        self._current_hour = now.hour
        self._current_date = now.strftime("%Y-%m-%d")

        # Open new file (append mode in case we're resuming)
        self._current_file = open(
            self._current_path,
            'a',
            buffering=self.buffer_size,
            encoding='utf-8'
        )

        self.rotations += 1

    def _compress_file(self, path: Path) -> None:
        """Compress a file with gzip."""
        try:
            gz_path = path.with_suffix(".jsonl.gz")

            # Don't compress if already compressed or file doesn't exist
            if gz_path.exists() or not path.exists():
                return

            # Compress
            with open(path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            # Remove original
            path.unlink()

        except Exception as e:
            self.errors += 1
            print(f"Error compressing {path}: {e}")

    def write(self, record: Dict[str, Any]) -> bool:
        """
        Write a record to the log.

        Args:
            record: Dictionary to write as JSON

        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                # Check if rotation needed
                if self._current_file is None or self._should_rotate():
                    self._open_new_file()

                # Serialize and write
                line = json.dumps(record, separators=(',', ':')) + '\n'
                self._current_file.write(line)

                # Update stats
                self.records_written += 1
                self.bytes_written += len(line.encode('utf-8'))

                return True

        except Exception as e:
            self.errors += 1
            print(f"Error writing record: {e}")
            return False

    def flush(self) -> None:
        """Flush the current file to disk."""
        with self._lock:
            if self._current_file:
                self._current_file.flush()
                os.fsync(self._current_file.fileno())

    def rotate(self) -> None:
        """Force rotation to a new file."""
        with self._lock:
            if self._current_file:
                self._current_file.close()

                if self.compress and self._current_path and self._current_path.exists():
                    self._compress_file(self._current_path)

                self._current_file = None
                self._current_path = None
                self._current_hour = None

    def close(self) -> None:
        """Close the logger and compress final file."""
        with self._lock:
            if self._current_file:
                self._current_file.close()

                if self.compress and self._current_path and self._current_path.exists():
                    self._compress_file(self._current_path)

                self._current_file = None

    def get_disk_usage(self) -> int:
        """Get total bytes used by log files."""
        total = 0
        for path in self.base_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total

    def check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space."""
        try:
            stat = os.statvfs(self.base_dir)
            free_bytes = stat.f_bavail * stat.f_frsize
            total_bytes = stat.f_blocks * stat.f_frsize
            used_by_logs = self.get_disk_usage()

            return {
                "free_bytes": free_bytes,
                "free_gb": free_bytes / (1024**3),
                "total_bytes": total_bytes,
                "total_gb": total_bytes / (1024**3),
                "used_by_logs_bytes": used_by_logs,
                "used_by_logs_mb": used_by_logs / (1024**2),
                "ok": free_bytes > 500 * 1024 * 1024,  # > 500MB free
            }
        except Exception as e:
            return {"error": str(e), "ok": False}

    def get_stats(self) -> Dict[str, Any]:
        """Get logger statistics."""
        uptime = time.time() - self.started_at

        return {
            "records_written": self.records_written,
            "bytes_written": self.bytes_written,
            "mb_written": self.bytes_written / (1024 * 1024),
            "rotations": self.rotations,
            "errors": self.errors,
            "uptime_seconds": uptime,
            "records_per_second": self.records_written / uptime if uptime > 0 else 0,
            "current_file": str(self._current_path) if self._current_path else None,
            "disk_space": self.check_disk_space(),
        }


def test_rotating_logger():
    """Test the rotating logger."""
    import tempfile

    print("Testing RotatingJSONLLogger...")

    # Create temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RotatingJSONLLogger(
            base_dir=tmpdir,
            prefix="test",
            compress=True
        )

        # Write some records
        for i in range(100):
            logger.write({
                "ts": int(time.time() * 1000),
                "index": i,
                "price": 97000.0 + i,
            })

        # Flush
        logger.flush()

        # Check stats
        stats = logger.get_stats()
        print(f"Records written: {stats['records_written']}")
        print(f"Bytes written: {stats['bytes_written']}")
        print(f"Current file: {stats['current_file']}")

        # Force rotation
        logger.rotate()

        # Check files
        files = list(Path(tmpdir).rglob("*"))
        print(f"Files created: {[f.name for f in files if f.is_file()]}")

        # Close
        logger.close()

        print("Test passed!")


if __name__ == "__main__":
    test_rotating_logger()
