"""Task manager for tracking active document conversion tasks.

Replaces the raw ``active_tasks`` dict with a thread-safe manager
that provides typed access and automatic TTL-based cleanup.
"""
import asyncio
import logging
import os as _os
import subprocess as _subprocess
import threading as _threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Tasks are automatically cleaned up after this many seconds of inactivity
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# Statuses during which a background job must be running for the task.
ACTIVE_STATUSES = ("processing", "queued")
# Statuses from which a task can be resumed via POST /api/tasks/{id}/resume.
RESUMABLE_STATUSES = ("interrupted", "failed", "aborted")
# Number of log lines persisted in task_info.json (shown after a backend restart).
PERSISTED_LOG_TAIL = 200


def _project_root() -> str:
    """Workspace root (resolved dynamically, monkeypatched in tests)."""
    import os
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Task:
    """Represents a single document conversion task."""

    task_id: str
    original_name: str
    input_path: str
    extension: str
    status: str = "pending"
    progress: dict = field(default_factory=lambda: {
        "percent": 0, "current": 0, "total": 0,
        "phase": "Bereite Extraktion vor..."
    })
    logs: list = field(default_factory=list)
    listeners: list = field(default_factory=list)
    process: Any = None
    raw_markdown: str | None = None
    standardised_markdown: str | None = None
    page_count: int = 0
    image_dir: str | None = None
    images: list = field(default_factory=list)
    output_path: str | None = None
    pages: str | None = None
    method: str | None = None
    lang: str | None = None
    engine: str | None = "infinity"
    physical_start_page: int = 1
    directory_info: dict | None = None
    is_abort_requested: bool = False
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    last_accessed: float = field(default_factory=time.time)
    # --- Background job lifecycle (see backend/services/task_jobs.py) ---
    job: Any = None                    # asyncio.Task owning the current work
    job_kind: str | None = None     # "extraction" | "standardisation" | "pipeline"
    orphan_since: float | None = None  # watchdog: first time seen active without job
    last_event_at: float | None = None  # last published event (stall detection)
    stall_warned: bool = False
    stream_text: str = ""              # accumulated LLM tokens for reattaching clients
    ruleset: str | None = None      # parameters needed to resume standardisation
    describe_images: bool = True
    standardisation_backend: str | None = None  # "gemma" | "rule_based_fallback"


    def job_running(self) -> bool:
        """True while the task's background job is alive."""
        return self.job is not None and not self.job.done()

    def touch(self) -> None:
        """Update last_accessed timestamp."""
        self.last_accessed = time.time()

    def request_abort(self) -> None:
        """Request immediate abort of task."""
        self.is_abort_requested = True
        self.status = "aborted"
        self.finished_at = time.time()
        self.progress["phase"] = "Konvertierung abgebrochen"
        if self.process is not None:
            try:
                self.process.kill()
            except Exception:
                pass
        if self.job_running():
            self.job.cancel()
        self.save_meta()

    def reset_for_new_extraction(self) -> None:
        """Resets task state so a new extraction can run cleanly with updated parameters."""
        self.is_abort_requested = False
        self.status = "pending"
        self.started_at = None
        self.finished_at = None
        self.process = None
        self.raw_markdown = None
        self.standardised_markdown = None
        self.images = []
        self.logs = []
        self.listeners = []
        self.stream_text = ""
        self.orphan_since = None
        self.stall_warned = False
        self.progress = {
            "percent": 0, "current": 0, "total": 0,
            "phase": "Bereite Extraktion vor..."
        }
        self.touch()
        self.save_meta()

    def to_summary_dict(self) -> dict:
        """Return a minimal dict for the task list endpoint."""
        return {
            "task_id": self.task_id,
            "original_name": self.original_name,
            "status": self.status,
            "progress": self.progress,
            "extension": self.extension,
            "engine": self.engine,
            "pages": self.pages,
            "method": self.method,
            "lang": self.lang,
            "physical_start_page": self.physical_start_page,
            "directories": self.directory_info,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "job_kind": self.job_kind,
            "resumable": self.status in RESUMABLE_STATUSES and not self.job_running(),
        }

    def save_meta(self):
        """Persist metadata to task_info.json in assets/output/<task_id>/."""
        import os
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            import json
            base_dir = _project_root()
            task_out_dir = os.path.join(base_dir, "assets", "output", self.task_id)
            os.makedirs(task_out_dir, exist_ok=True)
            meta_path = os.path.join(task_out_dir, "task_info.json")
            meta = {
                "task_id": self.task_id,
                "original_name": self.original_name,
                "status": self.status,
                "input_path": self.input_path,
                "extension": self.extension,
                "engine": self.engine,
                "pages": self.pages,
                "method": self.method,
                "lang": self.lang,
                "page_count": self.page_count,
                "physical_start_page": self.physical_start_page,
                "directory_info": self.directory_info,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "progress": self.progress,
                "job_kind": self.job_kind,
                "ruleset": self.ruleset,
                "describe_images": self.describe_images,
                "standardisation_backend": self.standardisation_backend,
                "logs_tail": list(self.logs[-PERSISTED_LOG_TAIL:]),
            }
            tmp_path = meta_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, meta_path)  # atomic: never leaves a half-written file
        except Exception:
            pass

    def to_state_dict(self) -> dict:
        """Return full state dict for task reattach endpoint."""
        raw_md = self.raw_markdown
        if not raw_md:
            import glob
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            task_out_dir = os.path.join(base_dir, "assets", "output", self.task_id)
            if os.path.exists(task_out_dir):
                md_files = glob.glob(os.path.join(task_out_dir, "**", "*.md"), recursive=True)
                for f in md_files:
                    if not f.endswith("_standardised.md") and not f.endswith("ground_truth.md"):
                        try:
                            with open(f, encoding="utf-8") as mdf:
                                content = mdf.read()
                                if content:
                                    raw_md = content
                                    self.raw_markdown = content
                                    break
                        except Exception:
                            pass

                std_file = os.path.join(task_out_dir, f"{self.task_id}_standardised.md")
                if os.path.exists(std_file):
                    try:
                        with open(std_file, encoding="utf-8") as sf:
                            self.standardised_markdown = sf.read()
                    except Exception:
                        pass

        def _sanitize(txt):
            if not txt:
                return txt
            from backend.services.extraction_postprocess import sanitize_runaway_repetitions
            return sanitize_runaway_repetitions(txt)

        clean_raw = _sanitize(raw_md)
        clean_std = _sanitize(self.standardised_markdown)

        return {
            "task_id": self.task_id,
            "original_name": self.original_name,
            "status": self.status,
            "progress": self.progress,
            "raw_markdown": clean_raw,
            "standardised_markdown": clean_std,
            "page_count": self.page_count,
            "engine": self.engine,
            "pages": self.pages,
            "method": self.method,
            "lang": self.lang,
            "physical_start_page": self.physical_start_page,
            "directories": self.directory_info,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "extension": self.extension,
            "job_kind": self.job_kind,
            "resumable": self.status in RESUMABLE_STATUSES and not self.job_running(),
        }

    def as_dict(self) -> dict:
        """Legacy compatibility: return a mutable dict view.

        The extraction_service still mutates task dicts directly,
        so this provides a bridge. Each ``as_dict`` call returns
        a reference to the same internal ``__dict__``.
        """
        return self.__dict__


class TaskManager:
    """Thread-safe manager for document conversion tasks.

    Provides CRUD operations with ``asyncio.Lock`` protection and
    automatic TTL-based cleanup of stale tasks.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, discover_disk: bool = False):
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._discover_disk = discover_disk

    async def create(
        self,
        task_id: str,
        original_name: str,
        input_path: str,
        extension: str,
        page_count: int = 0,
    ) -> Task:
        """Create and register a new task."""
        task = Task(
            task_id=task_id,
            original_name=original_name,
            input_path=input_path,
            extension=extension,
            page_count=page_count,
        )
        if self._discover_disk:
            task.save_meta()
        async with self._lock:
            self._tasks[task_id] = task
        return task

    def _recover_from_disk(self, task_id: str) -> Task | None:
        import glob
        import json
        import os
        base_dir = _project_root()
        task_out_dir = os.path.join(base_dir, "assets", "output", task_id)
        if not os.path.exists(task_out_dir):
            return None

        # Check for task_info.json or task_status.json
        meta_file = os.path.join(task_out_dir, "task_info.json")
        if not os.path.exists(meta_file):
            meta_file = os.path.join(task_out_dir, "task_status.json")
        
        meta = {}
        if os.path.exists(meta_file):
            try:
                with open(meta_file, encoding="utf-8") as mf:
                    meta = json.load(mf)
            except Exception:
                pass

        uploads_dir = os.path.join(base_dir, "assets", "uploads")
        input_path = meta.get("input_path") or os.path.join(uploads_dir, f"{task_id}.pdf")
        extension = meta.get("extension") or ".pdf"
        original_name = meta.get("original_name") or f"{task_id}{extension}"
        
        raw_md = None
        std_md = None
        md_files = glob.glob(os.path.join(task_out_dir, "**", "*.md"), recursive=True)
        for f in md_files:
            if f.endswith("_standardised.md"):
                try:
                    with open(f, encoding="utf-8") as sf:
                        std_md = sf.read()
                except Exception:
                    pass
            elif not f.endswith("ground_truth.md"):
                try:
                    with open(f, encoding="utf-8") as rf:
                        raw_md = rf.read()
                except Exception:
                    pass

        status = meta.get("status")
        if std_md:
            status = "completed"
        elif not status:
            status = "completed" if raw_md else "pending"
        elif status in ACTIVE_STATUSES:
            # Tasks are only recovered from disk when they are not owned by this
            # backend process, so an "active" status means the previous process
            # died (restart, crash) while the job was running.
            status = "interrupted"

        created_at = meta.get("created_at") or time.time()
        started_at = meta.get("started_at")
        finished_at = meta.get("finished_at")
        if status == "completed" and not finished_at:
            finished_at = started_at or created_at

        dir_info = meta.get("directory_info")
        if not dir_info:
            try:
                from backend.services.directory_service import load_directory_info
                dir_info = load_directory_info(task_out_dir)
            except Exception:
                pass

        task = Task(
            task_id=task_id,
            original_name=original_name,
            input_path=input_path,
            extension=extension,
            status=status,
            raw_markdown=raw_md,
            standardised_markdown=std_md,
            pages=meta.get("pages"),
            method=meta.get("method"),
            lang=meta.get("lang"),
            engine=meta.get("engine", "infinity"),
            page_count=meta.get("page_count", 0),
            physical_start_page=meta.get("physical_start_page", 1),
            directory_info=dir_info,
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            job_kind=meta.get("job_kind"),
            ruleset=meta.get("ruleset"),
            describe_images=meta.get("describe_images", True),
            standardisation_backend=meta.get("standardisation_backend"),
            logs=list(meta.get("logs_tail") or []),
        )
        if isinstance(meta.get("progress"), dict):
            task.progress = dict(meta["progress"])
        if status == "interrupted" and meta.get("status") in ACTIVE_STATUSES:
            phase = task.progress.get("phase") or ""
            task.progress["phase"] = f"Unterbrochen (Backend neu gestartet) – {phase}".rstrip(" –")
            task.logs.append("⚠️ Verarbeitung wurde unterbrochen (Backend-Neustart). "
                             "Über „Fortsetzen“ kann sie wieder aufgenommen werden.")
            task.save_meta()
        return task

    async def get(self, task_id: str) -> Task | None:
        """Retrieve a task by ID, updating its last-accessed time."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                task = self._recover_from_disk(task_id)
                if task:
                    self._tasks[task_id] = task
        if task:
            task.touch()
        return task

    def get_sync(self, task_id: str) -> Task | None:
        """Synchronous get for use in non-async contexts (e.g. tests).
        Not protected by the async lock — use only from single-threaded code.
        """
        task = self._tasks.get(task_id)
        if not task:
            task = self._recover_from_disk(task_id)
            if task:
                self._tasks[task_id] = task
        if task:
            task.touch()
        return task

    async def contains(self, task_id: str) -> bool:
        """Check if a task exists."""
        async with self._lock:
            if task_id in self._tasks:
                return True
            task = self._recover_from_disk(task_id)
            if task:
                self._tasks[task_id] = task
                return True
            return False

    def contains_sync(self, task_id: str) -> bool:
        """Synchronous contains check."""
        if task_id in self._tasks:
            return True
        task = self._recover_from_disk(task_id)
        if task:
            self._tasks[task_id] = task
            return True
        return False

    async def delete(self, task_id: str) -> Task | None:
        """Remove and return a task."""
        async with self._lock:
            return self._tasks.pop(task_id, None)

    async def list_all(self) -> list[Task]:
        """Return all active tasks."""
        if self._discover_disk:
            import glob
            import os
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            meta_files = glob.glob(os.path.join(base_dir, "assets", "output", "*", "task_info.json"))
            async with self._lock:
                for mf in meta_files:
                    tid = os.path.basename(os.path.dirname(mf))
                    if tid not in self._tasks:
                        recovered = self._recover_from_disk(tid)
                        if recovered:
                            self._tasks[tid] = recovered
                return list(self._tasks.values())
        async with self._lock:
            return list(self._tasks.values())

    async def cleanup_stale(self) -> int:
        """Remove tasks that haven't been accessed within the TTL window.
        Returns the number of removed tasks.
        """
        now = time.time()
        to_remove = []
        async with self._lock:
            for task_id, task in self._tasks.items():
                if now - task.last_accessed > self._ttl:
                    to_remove.append(task_id)
            for task_id in to_remove:
                del self._tasks[task_id]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} stale tasks: {to_remove}")
        return len(to_remove)

    @property
    def count(self) -> int:
        """Number of active tasks."""
        return len(self._tasks)


# ---------------------------------------------------------------------------
# macOS sleep prevention (caffeinate)
# ---------------------------------------------------------------------------
# A single ``caffeinate`` process is kept alive while at least one holder exists.
#
# * Named holders (``owner`` = unique job id) are idempotent: acquiring twice or
#   releasing twice (e.g. explicit abort + the job's own ``finally``) never
#   corrupts the count. Background jobs always use named holders.
# * Anonymous holders (``owner=None``) are classic ref counts for short,
#   request-scoped work (``/api/optimize``, ruleset PDF extraction).
#
# ``caffeinate -i -s -w <pid>``:
#   -i  prevent idle sleep, -s  prevent system sleep on AC power,
#   -w  exit automatically when the backend process dies (no orphaned assertion).
# The plain state is guarded by a ``threading.Lock`` so it is safe from any
# event loop or worker thread.
_CAFFEINATE_PROCESS = None
_SLEEP_OWNERS: set = set()
_ANON_HOLDS = 0
_SLEEP_LOCK = _threading.Lock()


def caffeinate_command() -> list:
    """Command used to hold the macOS power assertion while tasks run."""
    return ["caffeinate", "-i", "-s", "-w", str(_os.getpid())]


def _spawn_caffeinate():
    """Spawn OS sleep-prevention helper (caffeinate on macOS, systemd-inhibit on Linux).
    Monkeypatched in tests. Returns a Popen-like object or None.
    """
    import shutil
    if shutil.which("caffeinate"):
        return _subprocess.Popen(
            caffeinate_command(), stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL
        )
    if shutil.which("systemd-inhibit") and shutil.which("tail"):
        cmd = [
            "systemd-inhibit",
            "--what=idle:sleep",
            "--who=ebuch-konvertierung",
            "--why=Document conversion in progress",
            "tail",
            "-f",
            f"--pid={_os.getpid()}",
            "/dev/null",
        ]
        return _subprocess.Popen(cmd, stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
    logger.debug("No sleep-inhibition binary (caffeinate / systemd-inhibit) found on this platform.")
    return None


def _holders_count() -> int:
    return len(_SLEEP_OWNERS) + _ANON_HOLDS


def _start_caffeinate_locked() -> bool:
    """(Re)start caffeinate if needed. Caller holds ``_SLEEP_LOCK``. Returns True if spawned."""
    global _CAFFEINATE_PROCESS
    if _CAFFEINATE_PROCESS is not None and _CAFFEINATE_PROCESS.poll() is None:
        return False
    try:
        _CAFFEINATE_PROCESS = _spawn_caffeinate()
        if _CAFFEINATE_PROCESS is not None:
            logger.info("☕ caffeinate gestartet (%s) – Ruhezustand während der Verarbeitung blockiert",
                        " ".join(caffeinate_command()))
            return True
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Failed to start caffeinate process: {e}")
        _CAFFEINATE_PROCESS = None
    return False


def _stop_caffeinate_locked() -> None:
    global _CAFFEINATE_PROCESS
    if _CAFFEINATE_PROCESS is None:
        return
    try:
        logger.info("☕ caffeinate beendet – keine laufenden Verarbeitungen mehr")
        _CAFFEINATE_PROCESS.terminate()
        try:
            _CAFFEINATE_PROCESS.wait(timeout=2)
        except Exception:
            _CAFFEINATE_PROCESS.kill()
    except Exception as e:
        logger.error(f"Error terminating caffeinate process: {e}")
    finally:
        _CAFFEINATE_PROCESS = None


def acquire_sleep_assertion_sync(owner: str | None = None) -> None:
    """Register a holder of the sleep assertion (idempotent for named owners)."""
    global _ANON_HOLDS
    with _SLEEP_LOCK:
        if owner is None:
            _ANON_HOLDS += 1
        elif owner in _SLEEP_OWNERS:
            return
        else:
            _SLEEP_OWNERS.add(owner)
        _start_caffeinate_locked()


def release_sleep_assertion_sync(owner: str | None = None) -> None:
    """Release a holder; caffeinate stops when no holder remains. Unknown owners are a no-op."""
    global _ANON_HOLDS
    with _SLEEP_LOCK:
        if owner is None:
            if _ANON_HOLDS == 0:
                return
            _ANON_HOLDS -= 1
        elif owner in _SLEEP_OWNERS:
            _SLEEP_OWNERS.discard(owner)
        else:
            return
        if _holders_count() == 0:
            _stop_caffeinate_locked()


def sleep_assertion_active() -> bool:
    """True while at least one holder keeps the Mac awake."""
    with _SLEEP_LOCK:
        return _holders_count() > 0


def ensure_sleep_assertion_alive() -> bool:
    """Respawn caffeinate if it died while holders exist. Returns True if it was respawned."""
    with _SLEEP_LOCK:
        if _holders_count() == 0:
            return False
        if _CAFFEINATE_PROCESS is None or _CAFFEINATE_PROCESS.poll() is None:
            # Never started (caffeinate unavailable) or still healthy.
            return False
        logger.warning("caffeinate lief nicht mehr, obwohl Tasks aktiv sind – starte neu")
        return _start_caffeinate_locked()


def _reset_sleep_state_for_tests() -> None:
    """Drop all holders and stop caffeinate (test helper)."""
    global _ANON_HOLDS
    with _SLEEP_LOCK:
        _SLEEP_OWNERS.clear()
        _ANON_HOLDS = 0
        _stop_caffeinate_locked()
