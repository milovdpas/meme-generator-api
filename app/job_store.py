"""SQLite-backed render job queue, shared between the API and the worker.

The database lives in DATA_DIR (a shared volume in production) and uses WAL
mode so the web workers can read statuses while the render worker writes.
"""
import os
import sqlite3
import time
from contextlib import closing

DATA_DIR = os.path.abspath(os.environ.get('DATA_DIR', 'data'))
DB_PATH = os.path.join(DATA_DIR, 'renders.db')

MAX_ATTEMPTS = 2  # a job interrupted by a restart is retried once

_SCHEMA = """
CREATE TABLE IF NOT EXISTS renders (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',      -- queued|processing|finished|failed
    stage TEXT NOT NULL DEFAULT 'queued',       -- queued|removing_background|rendering
    progress REAL NOT NULL DEFAULT 0,           -- 0..100
    template TEXT NOT NULL,
    image_path TEXT NOT NULL,
    intro_mode TEXT NOT NULL DEFAULT 'default', -- default|custom|none
    intro_path TEXT,
    remove_bg INTEGER NOT NULL DEFAULT 0,
    cutout_file TEXT,
    output_file TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_renders_status_created ON renders(status, created_at);
"""


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA busy_timeout=5000')
    return con


def init_db():
    with closing(_connect()) as con:
        con.executescript(_SCHEMA)


def create_job(job_id, template, image_path, remove_bg=False,
               intro_mode='default', intro_path=None):
    with closing(_connect()) as con:
        con.execute(
            'INSERT INTO renders (id, template, image_path, remove_bg,'
            '                     intro_mode, intro_path, created_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            (job_id, template, image_path, int(remove_bg),
             intro_mode, intro_path, time.time()))
    return job_id


def get_job(job_id):
    """Return the job as a dict, with queue_position when still queued."""
    with closing(_connect()) as con:
        row = con.execute('SELECT * FROM renders WHERE id = ?',
                          (job_id,)).fetchone()
        if row is None:
            return None
        job = dict(row)
        if job['status'] == 'queued':
            ahead = con.execute(
                "SELECT COUNT(*) FROM renders WHERE status = 'processing'"
                " OR (status = 'queued' AND created_at < ?)",
                (job['created_at'],)).fetchone()[0]
            job['queue_position'] = ahead
        return job


def claim_next_job():
    """Atomically claim the oldest queued job. Returns it, or None."""
    with closing(_connect()) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            row = con.execute(
                "SELECT * FROM renders WHERE status = 'queued'"
                ' ORDER BY created_at LIMIT 1').fetchone()
            if row is None:
                con.execute('COMMIT')
                return None
            con.execute(
                "UPDATE renders SET status = 'processing', stage = 'rendering',"
                '  started_at = ?, attempts = attempts + 1 WHERE id = ?',
                (time.time(), row['id']))
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
        return get_job(row['id'])


def set_progress(job_id, progress, stage=None):
    with closing(_connect()) as con:
        con.execute(
            'UPDATE renders SET progress = MAX(progress, ?),'
            '  stage = COALESCE(?, stage) WHERE id = ?',
            (float(progress), stage, job_id))


def set_cutout(job_id, cutout_file):
    with closing(_connect()) as con:
        con.execute('UPDATE renders SET cutout_file = ? WHERE id = ?',
                    (cutout_file, job_id))


def finish_job(job_id, output_file):
    with closing(_connect()) as con:
        con.execute(
            "UPDATE renders SET status = 'finished', progress = 100,"
            '  output_file = ?, finished_at = ? WHERE id = ?',
            (output_file, time.time(), job_id))


def fail_job(job_id, error):
    with closing(_connect()) as con:
        con.execute(
            "UPDATE renders SET status = 'failed', error = ?, finished_at = ?"
            ' WHERE id = ?',
            (str(error)[:500], time.time(), job_id))


def recover_interrupted_jobs():
    """Re-queue jobs left 'processing' by a crashed/restarted worker.

    Jobs that already used up their attempts are failed instead.
    Returns (requeued, failed) counts.
    """
    with closing(_connect()) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            requeued = con.execute(
                "UPDATE renders SET status = 'queued', stage = 'queued', progress = 0"
                " WHERE status = 'processing' AND attempts < ?",
                (MAX_ATTEMPTS,)).rowcount
            failed = con.execute(
                "UPDATE renders SET status = 'failed', finished_at = ?,"
                "  error = 'The renderer was interrupted while processing this job.'"
                " WHERE status = 'processing'",
                (time.time(),)).rowcount
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
        return requeued, failed


def active_input_files(output_folder):
    """Absolute paths of files that queued/processing jobs still need.

    Used by the cleanup job so it never deletes the input of a job that is
    still waiting in the queue.
    """
    keep = set()
    with closing(_connect()) as con:
        rows = con.execute(
            "SELECT image_path, intro_path, cutout_file FROM renders"
            " WHERE status IN ('queued', 'processing')").fetchall()
    for row in rows:
        keep.add(os.path.abspath(row['image_path']))
        if row['intro_path']:
            keep.add(os.path.abspath(row['intro_path']))
        if row['cutout_file']:
            keep.add(os.path.abspath(os.path.join(output_folder, row['cutout_file'])))
    return keep


def cleanup_old_jobs(max_age_hours=24):
    """Delete finished/failed job rows older than max_age_hours."""
    cutoff = time.time() - max_age_hours * 3600
    with closing(_connect()) as con:
        return con.execute(
            "DELETE FROM renders WHERE status IN ('finished', 'failed')"
            ' AND created_at < ?',
            (cutoff,)).rowcount
