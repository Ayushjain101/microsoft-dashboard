"""Temp artifact context manager — guarantees cleanup even on crash."""

import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TempArtifact:
    """Context manager that tracks temp files and cleans them up."""

    def __init__(self, db: Session | None = None, job_id: uuid.UUID | str | None = None):
        self.db = db
        self.job_id = uuid.UUID(str(job_id)) if job_id else None
        self._files: list[str] = []

    def create_temp_file(self, suffix: str = "", prefix: str = "tmp", data: bytes | None = None) -> str:
        """Create a temp file, optionally writing data to it. Returns path."""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix)
        if data:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        else:
            os.close(fd)
        self._files.append(path)

        # Track in DB if session available
        if self.db and self.job_id:
            from app.models import TempArtifactRecord
            self.db.add(TempArtifactRecord(
                job_id=self.job_id,
                file_path=path,
                artifact_type=suffix.lstrip(".") or "unknown",
                created_at=datetime.now(timezone.utc),
            ))
            try:
                self.db.flush()
            except Exception:
                pass  # Non-critical

        return path

    def cleanup(self):
        """Remove all tracked temp files."""
        for path in self._files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
                    logger.debug(f"Cleaned up temp file: {path}")
            except OSError as e:
                logger.warning(f"Failed to clean up temp file {path}: {e}")

        # Mark as cleaned in DB
        if self.db and self.job_id:
            try:
                from app.models import TempArtifactRecord
                from sqlalchemy import update
                self.db.execute(
                    update(TempArtifactRecord)
                    .where(
                        TempArtifactRecord.job_id == self.job_id,
                        TempArtifactRecord.cleaned_at.is_(None),
                    )
                    .values(cleaned_at=datetime.now(timezone.utc))
                )
                self.db.flush()
            except Exception:
                pass

        self._files.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False
