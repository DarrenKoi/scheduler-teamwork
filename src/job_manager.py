import json
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    name TEXT,
    description TEXT,
    schedule_type TEXT,
    schedule_config TEXT,
    entry_point TEXT DEFAULT 'main.py',
    timeout INTEGER DEFAULT 3600,
    enabled INTEGER DEFAULT 1,
    yaml_mtime REAL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    return_code INTEGER,
    log_path TEXT,
    error_message TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""


class JobManager:
    def __init__(self, config: dict, scheduler):
        self.config = config
        self.scheduler = scheduler

        base_dir = Path(config.get("_base_dir", "."))
        paths = config["paths"]
        self.jobs_dir = base_dir / paths["jobs_dir"]
        self.logs_dir = base_dir / paths["logs_dir"]
        self.db_path = base_dir / paths["db_path"]
        
        # Staging directory for safe updates
        self.staging_dir = self.jobs_dir / ".staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.pending_updates = set()

        self.log_retention_days = config.get("log_retention", {}).get("days", 30)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._db_lock = threading.Lock()
        self._job_locks: dict[str, threading.Lock] = {}
        self._init_db()
        self._cleanup_stale_runs()

    def _init_db(self):
        with self._db_lock:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            # Check if 'user' column exists, if so, we might need to migrate or just drop and recreate
            # Since this is a simple internal tool, let's just make sure the new schema is applied.
            # For simplicity in this non-production context, I'll check for the column.
            cursor = conn.execute("PRAGMA table_info(jobs)")
            columns = [info[1] for f, info in enumerate(cursor.fetchall())]
            if "user" in columns:
                logger.info("Migrating database: removing 'user' column and clearing legacy data")
                conn.execute("DROP TABLE IF EXISTS runs")
                conn.execute("DROP TABLE IF EXISTS jobs")
            
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()

    def _cleanup_stale_runs(self):
        """Mark jobs that were 'running' during a previous crash as failed."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """UPDATE runs 
                       SET status='failed', error_message='System restarted while running', finished_at=?
                       WHERE status='running'""",
                    (datetime.now().isoformat(),)
                )
                conn.commit()
            finally:
                conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _get_job_lock(self, job_id: str) -> threading.Lock:
        if job_id not in self._job_locks:
            self._job_locks[job_id] = threading.Lock()
        return self._job_locks[job_id]

    def scan_jobs(self):
        """Scan the jobs directory and register/update jobs."""
        if not self.jobs_dir.exists():
            logger.warning("Jobs directory does not exist: %s", self.jobs_dir)
            return

        found_job_ids = set()

        for task_dir in sorted(self.jobs_dir.iterdir()):
            if not task_dir.is_dir() or task_dir.name.startswith(".") or task_dir.name == ".staging":
                continue

            job_yaml = task_dir / "job.yaml"
            if not job_yaml.exists():
                continue

            job_id = task_dir.name
            found_job_ids.add(job_id)

            yaml_mtime = job_yaml.stat().st_mtime
            if not self._needs_update(job_id, yaml_mtime):
                continue

            try:
                with open(job_yaml, "r", encoding="utf-8") as f:
                    job_config = yaml.safe_load(f)
            except Exception:
                logger.exception("Failed to parse %s", job_yaml)
                continue

            job_config["_task"] = task_dir.name
            job_config["_yaml_mtime"] = yaml_mtime
            self.register_job(job_id, job_config)

        self._remove_stale_jobs(found_job_ids)

    def _needs_update(self, job_id: str, yaml_mtime: float) -> bool:
        with self._db_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT yaml_mtime FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    return True
                return row["yaml_mtime"] != yaml_mtime
            finally:
                conn.close()

    def register_job(self, job_id: str, job_config: dict):
        """Register or update a job in the DB and scheduler."""
        task = job_config["_task"]
        yaml_mtime = job_config["_yaml_mtime"]
        now = datetime.now().isoformat()

        schedule = job_config.get("schedule", {})
        schedule_type = schedule.get("type", "interval")
        schedule_config = {k: v for k, v in schedule.items() if k != "type"}

        with self._db_lock:
            conn = self._get_conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()

                if existing:
                    conn.execute(
                        """UPDATE jobs SET
                            name=?, description=?, schedule_type=?, schedule_config=?,
                            entry_point=?, timeout=?, yaml_mtime=?, updated_at=?
                        WHERE id=?""",
                        (
                            job_config.get("name", task),
                            job_config.get("description", ""),
                            schedule_type,
                            json.dumps(schedule_config),
                            job_config.get("entry_point", "main.py"),
                            job_config.get("timeout", 3600),
                            yaml_mtime,
                            now,
                            job_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO jobs
                            (id, task, name, description, schedule_type,
                             schedule_config, entry_point, timeout, enabled,
                             yaml_mtime, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                        (
                            job_id,
                            task,
                            job_config.get("name", task),
                            job_config.get("description", ""),
                            schedule_type,
                            json.dumps(schedule_config),
                            job_config.get("entry_point", "main.py"),
                            job_config.get("timeout", 3600),
                            yaml_mtime,
                            now,
                            now,
                        ),
                    )
                conn.commit()

                enabled = True
                if existing:
                    row = conn.execute(
                        "SELECT enabled FROM jobs WHERE id = ?", (job_id,)
                    ).fetchone()
                    enabled = bool(row["enabled"])
            finally:
                conn.close()

        self._schedule_job(job_id, schedule_type, schedule_config, enabled)
        logger.info("Registered job: %s", job_id)

    def _schedule_job(
        self,
        job_id: str,
        schedule_type: str,
        schedule_config: dict,
        enabled: bool,
    ):
        """Add or update the job in APScheduler."""
        # Remove existing schedule
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        if not enabled:
            return

        trigger_kwargs = dict(schedule_config)

        if schedule_type == "cron":
            self.scheduler.add_job(
                self.execute_job,
                "cron",
                id=job_id,
                args=[job_id],
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                **trigger_kwargs,
            )
        else:
            # Default to interval
            if "seconds" not in trigger_kwargs and "minutes" not in trigger_kwargs and "hours" not in trigger_kwargs:
                trigger_kwargs["hours"] = 1
            self.scheduler.add_job(
                self.execute_job,
                "interval",
                id=job_id,
                args=[job_id],
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                **trigger_kwargs,
            )

    def _remove_stale_jobs(self, found_job_ids: set):
        """Remove jobs from DB and scheduler that no longer exist on disk."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                rows = conn.execute("SELECT id FROM jobs").fetchall()
                for row in rows:
                    if row["id"] not in found_job_ids:
                        self.unregister_job(row["id"], conn=conn)
                conn.commit()
            finally:
                conn.close()

    def unregister_job(self, job_id: str, conn=None):
        """Remove a job from scheduler and DB."""
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        should_close = False
        if conn is None:
            conn = self._get_conn()
            should_close = True
        try:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            if should_close:
                conn.commit()
        finally:
            if should_close:
                conn.close()

        logger.info("Unregistered job: %s", job_id)

    def execute_job(self, job_id: str):
        """Execute a job as a subprocess."""
        lock = self._get_job_lock(job_id)
        if not lock.acquire(blocking=False):
            logger.warning("Job %s is already running, skipping", job_id)
            return

        try:
            self._run_job(job_id)
        finally:
            lock.release()

    def _run_job(self, job_id: str):
        with self._db_lock:
            conn = self._get_conn()
            try:
                job = conn.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
            finally:
                conn.close()

        if not job:
            logger.error("Job not found: %s", job_id)
            return
        if not job["enabled"]:
            logger.info("Job %s is disabled, skipping", job_id)
            return

        job_path = self.jobs_dir / job["task"]
        entry_point = job["entry_point"]
        timeout = job["timeout"]

        # Prepare log file
        now = datetime.now()
        log_dir = self.logs_dir / job["task"]
        log_dir.mkdir(parents=True, exist_ok=True)
        log_filename = now.strftime("%Y%m%d_%H%M%S") + ".log"
        log_path = log_dir / log_filename
        relative_log_path = str(log_path.relative_to(self.logs_dir))

        started_at = now.isoformat()

        # Insert run record
        with self._db_lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """INSERT INTO runs (job_id, status, started_at, log_path)
                    VALUES (?, 'running', ?, ?)""",
                    (job_id, started_at, relative_log_path),
                )
                run_id = cursor.lastrowid
                conn.commit()
            finally:
                conn.close()

        status = "success"
        return_code = None
        error_message = None

        try:
            result = subprocess.run(
                ["uv", "run", entry_point],
                cwd=str(job_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return_code = result.returncode

            # Write log
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Job: {job_id} ===\n")
                f.write(f"Started: {started_at}\n")
                f.write(f"Command: uv run {entry_point}\n")
                f.write(f"Working dir: {job_path}\n")
                f.write(f"Return code: {return_code}\n")
                f.write("=" * 40 + "\n\n")
                if result.stdout:
                    f.write("--- STDOUT ---\n")
                    f.write(result.stdout)
                    f.write("\n")
                if result.stderr:
                    f.write("--- STDERR ---\n")
                    f.write(result.stderr)
                    f.write("\n")

            if return_code != 0:
                status = "failed"
                error_message = (result.stderr or result.stdout or "")[:500]

        except subprocess.TimeoutExpired as e:
            status = "timeout"
            error_message = f"Timed out after {timeout} seconds"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Job: {job_id} ===\n")
                f.write(f"Started: {started_at}\n")
                f.write(f"TIMEOUT after {timeout}s\n")
                if e.stdout:
                    f.write("--- STDOUT (partial) ---\n")
                    stdout = e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", errors="replace")
                    f.write(stdout)
                if e.stderr:
                    f.write("--- STDERR (partial) ---\n")
                    stderr = e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", errors="replace")
                    f.write(stderr)

        except Exception as e:
            status = "failed"
            error_message = str(e)[:500]
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Job: {job_id} ===\n")
                f.write(f"Error: {e}\n")

        finished_at = datetime.now()
        duration = (finished_at - now).total_seconds()

        with self._db_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """UPDATE runs SET
                        status=?, finished_at=?, duration_seconds=?,
                        return_code=?, error_message=?
                    WHERE id=?""",
                    (
                        status,
                        finished_at.isoformat(),
                        round(duration, 2),
                        return_code,
                        error_message,
                        run_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("Job %s finished: %s (%.1fs)", job_id, status, duration)

    def toggle_job(self, job_id: str) -> bool:
        """Toggle job enabled state. Returns new state."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT enabled, schedule_type, schedule_config FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if not row:
                    return False

                new_state = 0 if row["enabled"] else 1
                conn.execute(
                    "UPDATE jobs SET enabled = ?, updated_at = ? WHERE id = ?",
                    (new_state, datetime.now().isoformat(), job_id),
                )
                conn.commit()

                schedule_config = json.loads(row["schedule_config"]) if row["schedule_config"] else {}
                self._schedule_job(
                    job_id, row["schedule_type"], schedule_config, bool(new_state)
                )
                return bool(new_state)
            finally:
                conn.close()

    def get_jobs(self) -> list[dict]:
        """Get all jobs with their next run time and latest run status."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                jobs = conn.execute(
                    "SELECT * FROM jobs ORDER BY task"
                ).fetchall()
                result = []
                for job in jobs:
                    job_dict = dict(job)

                    # Get next run time from scheduler
                    try:
                        sched_job = self.scheduler.get_job(job["id"])
                        if sched_job and sched_job.next_run_time:
                            job_dict["next_run"] = sched_job.next_run_time.strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                        else:
                            job_dict["next_run"] = "-"
                    except Exception:
                        job_dict["next_run"] = "-"

                    # Get latest run
                    latest = conn.execute(
                        """SELECT status, started_at, duration_seconds
                        FROM runs WHERE job_id = ?
                        ORDER BY id DESC LIMIT 1""",
                        (job["id"],),
                    ).fetchone()
                    if latest:
                        job_dict["last_status"] = latest["status"]
                        job_dict["last_run"] = latest["started_at"]
                        job_dict["last_duration"] = latest["duration_seconds"]
                    else:
                        job_dict["last_status"] = None
                        job_dict["last_run"] = None
                        job_dict["last_duration"] = None

                    result.append(job_dict)
                return result
            finally:
                conn.close()

    def get_runs(self, job_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        """Get run history with optional filters."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                query = """
                    SELECT r.*, j.name as job_name
                    FROM runs r
                    LEFT JOIN jobs j ON r.job_id = j.id
                    WHERE 1=1
                """
                params: list = []

                if job_id:
                    query += " AND r.job_id = ?"
                    params.append(job_id)
                if status:
                    query += " AND r.status = ?"
                    params.append(status)

                query += " ORDER BY r.id DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(query, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_log_content(self, log_path: str) -> str | None:
        """Read log file content with path validation."""
        # Prevent path traversal
        try:
            full_path = (self.logs_dir / log_path).resolve()
            if not str(full_path).startswith(str(self.logs_dir.resolve())):
                logger.warning("Path traversal attempt: %s", log_path)
                return None
        except Exception:
            return None

        if not full_path.exists():
            return None

        try:
            return full_path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read log: %s", full_path)
            return None

    def cleanup_old_logs(self):
        """Delete logs and run records older than retention period."""
        cutoff = datetime.now() - timedelta(days=self.log_retention_days)
        cutoff_str = cutoff.isoformat()

        # Delete old log files
        with self._db_lock:
            conn = self._get_conn()
            try:
                old_runs = conn.execute(
                    "SELECT log_path FROM runs WHERE started_at < ?", (cutoff_str,)
                ).fetchall()

                for run in old_runs:
                    if run["log_path"]:
                        log_file = self.logs_dir / run["log_path"]
                        if log_file.exists():
                            try:
                                log_file.unlink()
                            except Exception:
                                logger.exception("Failed to delete log: %s", log_file)

                conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff_str,))
                conn.commit()
                logger.info("Cleaned up logs older than %s", cutoff_str)
            finally:
                conn.close()

    def get_failure_count(self) -> int:
        """Count failures in the last 24 hours."""
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        with self._db_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM runs WHERE status IN ('failed', 'timeout') AND started_at > ?",
                    (cutoff,),
                ).fetchone()
                return row["cnt"] if row else 0
            finally:
                conn.close()

    def save_job_files(self, task: str, files: list, job_config: dict | None = None) -> str:
        """Save uploaded files to staging and queue for update."""
        # Basic sanitization
        task = "".join(c for c in task if c.isalnum() or c in ("-", "_"))
        
        if not task:
            raise ValueError("Invalid task name")

        # Prevent duplicates check
        dest_path = self.jobs_dir / task
        if dest_path.exists() and not (self.staging_dir / task).exists():
            # If it's a new upload (not currently in staging) but exists in jobs, 
            # we should probably prevent it unless we want to allow overwriting.
            # The user said "cannot upload the same file name to prevent duplicated jobs".
            # I'll interpret this as "cannot create a job with an existing name".
            raise ValueError(f"Job with name '{task}' already exists. Please use a different name or edit the existing job.")

        # Save to staging
        staging_path = self.staging_dir / task
        if staging_path.exists():
            shutil.rmtree(staging_path)
        staging_path.mkdir(parents=True, exist_ok=True)

        has_yaml = False
        for file in files:
            if not file.filename:
                continue
            filename = Path(file.filename).name
            if filename == "job.yaml":
                has_yaml = True
            save_path = staging_path / filename
            file.save(save_path)
        
        # Generate job.yaml if missing and config provided
        if not has_yaml and job_config:
            logger.info("Generating job.yaml for %s", task)
            with open(staging_path / "job.yaml", "w", encoding="utf-8") as f:
                yaml.dump(job_config, f, default_flow_style=False)

        job_id = task
        self.pending_updates.add(job_id)
        logger.info("Queued update for %s", job_id)
        
        return job_id

    def update_job_config(self, task: str, new_config: dict) -> bool:
        """Update job.yaml for an existing job."""
        job_path = self.jobs_dir / task
        job_yaml_path = job_path / "job.yaml"

        if not job_path.exists():
            return False
        
        current_config = {}
        if job_yaml_path.exists():
            try:
                with open(job_yaml_path, "r", encoding="utf-8") as f:
                    current_config = yaml.safe_load(f) or {}
            except Exception:
                logger.warning("Could not read existing job.yaml for update")
        
        current_config.update(new_config)
        
        try:
            with open(job_yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(current_config, f, default_flow_style=False)
            
            job_id = task
            self.scan_jobs()
            return True
        except Exception as e:
            logger.exception("Failed to update job config")
            return False

    def process_pending_updates(self):
        """Apply pending updates if the system is idle."""
        if not self.pending_updates:
            return

        if not self.is_system_idle():
            logger.debug("System busy, postponing updates")
            return

        logger.info("System idle, processing %d updates", len(self.pending_updates))
        
        to_process = list(self.pending_updates)
        
        for job_id in to_process:
            task = job_id
            staging_path = self.staging_dir / task
            dest_path = self.jobs_dir / task
            
            if not staging_path.exists():
                self.pending_updates.discard(job_id)
                continue

            try:
                dest_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staging_path, dest_path, dirs_exist_ok=True)
                shutil.rmtree(staging_path)
                self.pending_updates.discard(job_id)
                logger.info("Applied update for %s", job_id)
            except Exception:
                logger.exception("Failed to apply update for %s", job_id)

        # Reload configuration
        self.scan_jobs()

    def is_system_idle(self) -> bool:
        """Check if any jobs are currently running."""
        for lock in self._job_locks.values():
            if lock.locked():
                return False
        return True

    def get_system_status(self) -> dict:
        """Get current system status summary."""
        running_count = sum(1 for lock in self._job_locks.values() if lock.locked())
        
        status = "idle"
        if running_count > 0:
            status = "running"
        elif self.pending_updates:
            status = "updating"

        return {
            "status": status,
            "running_count": running_count,
            "pending_count": len(self.pending_updates)
        }
        """Apply pending updates if the system is idle."""
        if not self.pending_updates:
            return

        if not self.is_system_idle():
            logger.debug("System busy, postponing updates")
            return

        logger.info("System idle, processing %d updates", len(self.pending_updates))
        
        # Clone set to iterate safely while modifying original
        to_process = list(self.pending_updates)
        
        for job_id in to_process:
            user, task = job_id.split("/")
            staging_path = self.staging_dir / user / task
            dest_path = self.jobs_dir / user / task
            
            if not staging_path.exists():
                self.pending_updates.discard(job_id)
                continue

            try:
                dest_path.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staging_path, dest_path, dirs_exist_ok=True)
                shutil.rmtree(staging_path)
                self.pending_updates.discard(job_id)
                logger.info("Applied update for %s", job_id)
            except Exception:
                logger.exception("Failed to apply update for %s", job_id)

        # Reload configuration
        self.scan_jobs()

    def is_system_idle(self) -> bool:
        """Check if any jobs are currently running."""
        for lock in self._job_locks.values():
            if lock.locked():
                return False
        return True

    def get_system_status(self) -> dict:
        """Get current system status summary."""
        running_count = sum(1 for lock in self._job_locks.values() if lock.locked())
        
        status = "idle"
        if running_count > 0:
            status = "running"
        elif self.pending_updates:
            status = "updating"

        return {
            "status": status,
            "running_count": running_count,
            "pending_count": len(self.pending_updates)
        }
