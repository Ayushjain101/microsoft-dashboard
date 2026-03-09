"""Distributed locking via PostgreSQL advisory locks."""

import hashlib
import logging
import struct

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.exceptions import LockError

logger = logging.getLogger(__name__)


def _job_id_to_lock_key(job_id: str) -> int:
    """Convert a UUID string to a 64-bit integer for pg_advisory_lock."""
    h = hashlib.sha256(job_id.encode()).digest()
    return struct.unpack(">q", h[:8])[0]


def acquire_advisory_lock(db: Session, job_id: str) -> bool:
    """Try to acquire a PostgreSQL advisory lock for the given job.

    Returns True if lock was acquired, False if already held by another session.
    Uses pg_try_advisory_lock (non-blocking).
    """
    lock_key = _job_id_to_lock_key(job_id)
    result = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
    acquired = result.scalar()
    if acquired:
        logger.debug(f"Acquired advisory lock for job {job_id} (key={lock_key})")
    else:
        logger.debug(f"Failed to acquire lock for job {job_id} — already held")
    return bool(acquired)


def release_advisory_lock(db: Session, job_id: str):
    """Release the advisory lock for a job."""
    lock_key = _job_id_to_lock_key(job_id)
    db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
    logger.debug(f"Released advisory lock for job {job_id} (key={lock_key})")
