"""Task-owned background jobs, listener streams, watchdog and wake detection.

Lifecycle rules (see AGENTS.md §4 "Task Lifecycle"):

* All long-running work (extraction, VLM image descriptions, Gemma
  standardisation) runs as an ``asyncio.Task`` owned by the conversion task
  (``task.job``), **never** inside an HTTP response generator. HTTP clients only
  attach a listener queue; a closed browser tab, a frontend ``AbortController``
  or a dropped connection therefore never cancels the work.
* Each job holds its own named macOS sleep assertion (``caffeinate``) from start
  until its ``finally`` block, released exactly once.
* Aborting is explicit (``POST /api/tasks/{id}/abort``) and cancels the job and
  kills its subprocess.
* A heartbeat loop detects system sleep/wake (wall clock vs. monotonic clock),
  marks orphaned "processing" tasks as ``interrupted`` (resumable) and respawns
  ``caffeinate`` should it have died.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterable

from backend.services.task_manager import (
    ACTIVE_STATUSES,
    acquire_sleep_assertion_sync,
    ensure_sleep_assertion_alive,
    release_sleep_assertion_sync,
    sleep_assertion_active,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 5.0
# Wall-clock jump (beyond the monotonic delta) that counts as system sleep.
WAKE_THRESHOLD_SECONDS = 20.0
# An active task without a running job is marked interrupted after this grace period.
ORPHAN_GRACE_SECONDS = 30.0
# Warn (log only) when a running job has not published any event for this long.
STALL_WARNING_SECONDS = 15 * 60
# Number of past log lines replayed to a (re)attaching client.
REPLAY_LOG_LINES = 300

# Strong references so running jobs are never garbage-collected.
_JOBS: set = set()

# Per-event-loop semaphore(1) to serialize heavy conversion jobs and prevent
# simultaneous GPU / Unified-Memory contention.
_GPU_SEMAPHORES: dict[int, asyncio.Semaphore] = {}


def _get_gpu_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    sem = _GPU_SEMAPHORES.get(loop_id)
    if sem is None:
        sem = asyncio.Semaphore(1)
        _GPU_SEMAPHORES[loop_id] = sem
    return sem


def reset_gpu_semaphore_for_tests() -> None:
    """Clear per-loop GPU semaphores (used in unit tests)."""
    _GPU_SEMAPHORES.clear()


# ---------------------------------------------------------------------------
# Events & listeners
# ---------------------------------------------------------------------------

def format_event(event: dict) -> str:
    """Serialize an event as one NDJSON line."""
    return json.dumps(event, ensure_ascii=False) + "\n"


def publish(task, event, *, record_log: bool = True) -> None:
    """Update task state from an event and push it to all attached listeners.

    ``event`` is either a dict or an already serialized NDJSON line (as produced
    by the legacy stream generators). State tracked here is what reattaching
    clients receive as replay: log lines, progress and streamed LLM tokens.
    """
    if isinstance(event, str):
        line = event if event.endswith("\n") else event + "\n"
        try:
            data = json.loads(line)
        except Exception:
            data = {}
    else:
        data = event
        line = format_event(event)

    status = data.get("status")
    task.last_event_at = time.time()
    task.stall_warned = False
    if status == "log" and record_log:
        msg = data.get("message")
        if msg and (not task.logs or task.logs[-1] != msg):
            task.logs.append(msg)
    elif status == "progress":
        progress = dict(task.progress or {})
        for key in ("percent", "phase", "current", "total"):
            if key in data:
                progress[key] = data[key]
        task.progress = progress
    elif status == "token":
        task.stream_text += data.get("delta") or ""

    for queue in list(task.listeners):
        try:
            queue.put_nowait(line)
        except Exception:
            pass


def close_listeners(task) -> None:
    """Signal end-of-stream to every attached listener."""
    for queue in list(task.listeners):
        try:
            queue.put_nowait(None)
        except Exception:
            pass


def terminal_event(task) -> dict:
    """Final event for a client attaching to a task without a running job."""
    status = task.status
    if status == "completed":
        if task.standardised_markdown:
            return {"status": "completed", "stage": "standardisation", "markdown": task.standardised_markdown}
        return {"status": "completed", "stage": "extraction", "markdown": task.raw_markdown or "",
                "image_count": len(task.images or [])}
    if status == "failed":
        return {"status": "error", "message": task.logs[-1] if task.logs else "Verarbeitung fehlgeschlagen."}
    if status == "aborted":
        return {"status": "aborted", "message": "Konvertierung wurde auf Benutzerwunsch abgebrochen."}
    if status == "interrupted":
        return {"status": "interrupted", "message": task.progress.get("phase") or "Verarbeitung unterbrochen.",
                "resumable": True}
    return {"status": "idle", "task_status": status}


def attach_listener(task, replay: bool = True) -> asyncio.Queue:
    """Create a listener queue for a client, optionally replaying the current state.

    If the task has neither a running job nor an active status, the queue
    immediately receives the terminal event and end-of-stream.
    """
    queue: asyncio.Queue = asyncio.Queue()
    if replay:
        for msg in task.logs[-REPLAY_LOG_LINES:]:
            queue.put_nowait(format_event({"status": "log", "message": msg, "replay": True}))
        progress = task.progress or {}
        queue.put_nowait(format_event({
            "status": "progress",
            "percent": progress.get("percent", 0),
            "phase": progress.get("phase", ""),
            "current": progress.get("current", 0),
            "total": progress.get("total", 0),
            "stage": task.job_kind,
        }))
        if task.stream_text:
            queue.put_nowait(format_event({"status": "stream_snapshot", "text": task.stream_text}))

    if task.job_running() or task.status in ACTIVE_STATUSES:
        task.listeners.append(queue)
    else:
        queue.put_nowait(format_event(terminal_event(task)))
        queue.put_nowait(None)
    return queue


async def listener_stream(task, queue: asyncio.Queue):
    """Async generator yielding NDJSON lines until end-of-stream.

    Closing / cancelling this generator (client disconnect) only detaches the
    listener – the job keeps running.
    """
    try:
        while True:
            msg = await queue.get()
            if msg is None:
                break
            yield msg
    finally:
        if queue in task.listeners:
            task.listeners.remove(queue)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _kill_process(task) -> None:
    proc = getattr(task, "process", None)
    if proc is None:
        return
    try:
        proc.kill()
    except Exception:
        pass


def start_task_job(
    task,
    kind: str,
    coro,
    *,
    close_listeners_on_finish: bool = True,
    serialize_gpu: bool = True,
) -> asyncio.Task:
    """Run ``coro`` as the task-owned background job.

    The job holds a uniquely named sleep assertion for its whole lifetime, so an
    explicit abort plus the job's own cleanup never double-release it.
    When ``serialize_gpu=True``, concurrent jobs wait on the per-loop GPU
    semaphore (``status="queued"``) so only one heavy extraction/standardisation
    job occupies GPU / Unified Memory at a time.
    """
    owner = f"{task.task_id}:{kind}:{uuid.uuid4().hex[:8]}"

    async def runner():
        acquire_sleep_assertion_sync(owner)
        sem = _get_gpu_semaphore() if serialize_gpu else None
        acquired = False
        try:
            if sem is not None:
                if sem.locked():
                    task.status = "queued"
                    prev_phase = (task.progress or {}).get("phase") or ""
                    publish(
                        task,
                        {
                            "status": "log",
                            "message": "⏳ Auftrag in Warteschlange – warte auf freie GPU-Ressource...",
                        },
                    )
                    publish(
                        task,
                        {
                            "status": "progress",
                            "percent": (task.progress or {}).get("percent", 0),
                            "phase": "Warteschlange (warte auf freie GPU-Ressource...)",
                        },
                    )
                    task.save_meta()
                else:
                    prev_phase = None
                await sem.acquire()
                acquired = True
                if task.status == "queued":
                    task.status = "processing"
                    if prev_phase:
                        publish(
                            task,
                            {
                                "status": "progress",
                                "percent": (task.progress or {}).get("percent", 0),
                                "phase": prev_phase,
                            },
                        )
                    task.save_meta()

            logger.info(f"▶️ Job gestartet: task={task.task_id} kind={kind}")
            await coro
        except asyncio.CancelledError:
            coro.close()  # no-op if it already ran; avoids "never awaited" warnings
            logger.info(f"⏹ Job abgebrochen: task={task.task_id} kind={kind}")
            _kill_process(task)
            if task.status in ACTIVE_STATUSES:
                task.status = "aborted"
                task.finished_at = time.time()
                task.save_meta()
        except Exception as e:  # defensive: job bodies normally handle their own errors
            logger.exception(f"Job failed: task={task.task_id} kind={kind}")
            task.status = "failed"
            task.finished_at = time.time()
            task.save_meta()
            publish(task, {"status": "error", "message": f"Verarbeitung fehlgeschlagen: {e}"})
        finally:
            if acquired and sem is not None:
                sem.release()
            task.process = None
            release_sleep_assertion_sync(owner)
            if task.job is asyncio.current_task():
                task.job = None
                if close_listeners_on_finish:
                    close_listeners(task)
            logger.info(f"⏏ Job beendet: task={task.task_id} kind={kind} status={task.status}")

    job = asyncio.create_task(runner(), name=f"task-{task.task_id}-{kind}")
    task.job = job
    task.job_kind = kind
    task.orphan_since = None
    _JOBS.add(job)
    job.add_done_callback(_JOBS.discard)
    return job


def cancel_task_job(task) -> asyncio.Task | None:
    """Explicit abort: kill the subprocess and cancel the job (if running)."""
    _kill_process(task)
    job = task.job
    if job is not None and not job.done():
        job.cancel()
        return job
    return None


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

def mark_interrupted(task, reason: str) -> None:
    """Mark an orphaned task as interrupted (resumable) and notify listeners."""
    phase = task.progress.get("phase") or ""
    task.status = "interrupted"
    task.progress = {**task.progress, "phase": f"Unterbrochen – {phase}".rstrip(" –")}
    msg = f"⚠️ Verarbeitung unterbrochen: {reason}. Über „Fortsetzen“ kann sie wieder aufgenommen werden."
    logger.warning(f"Task {task.task_id}: {msg}")
    publish(task, {"status": "log", "message": msg})
    publish(task, {"status": "interrupted", "message": msg, "resumable": True})
    close_listeners(task)
    task.save_meta()


def detect_orphaned_tasks(tasks: Iterable, now: float, grace_seconds: float = ORPHAN_GRACE_SECONDS) -> list:
    """Mark tasks that are 'active' but have no running job for ``grace_seconds``."""
    marked = []
    for task in tasks:
        if task.status not in ACTIVE_STATUSES or task.job_running():
            task.orphan_since = None
            continue
        if task.orphan_since is None:
            task.orphan_since = now
            continue
        if now - task.orphan_since >= grace_seconds:
            task.orphan_since = None
            mark_interrupted(task, "kein laufender Hintergrundprozess mehr")
            marked.append(task)
    return marked


# ---------------------------------------------------------------------------
# Wake detection & heartbeat
# ---------------------------------------------------------------------------

class WakeDetector:
    """Detects system sleep by comparing wall-clock and monotonic progress.

    On macOS ``time.monotonic()`` does not advance while the system sleeps,
    whereas ``time.time()`` does – the difference is the sleep duration.
    """

    def __init__(self, threshold_seconds: float = WAKE_THRESHOLD_SECONDS,
                 wall: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic):
        self.threshold = threshold_seconds
        self._wall = wall
        self._mono = mono
        self._last_wall = wall()
        self._last_mono = mono()

    def check(self) -> float | None:
        """Return the slept seconds since the last check, or None."""
        wall, mono = self._wall(), self._mono()
        gap = (wall - self._last_wall) - (mono - self._last_mono)
        self._last_wall, self._last_mono = wall, mono
        return gap if gap >= self.threshold else None


def _fmt_duration(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def run_heartbeat_once(tasks: Iterable, detector: WakeDetector | None, now: float | None = None,
                       orphan_grace_seconds: float = ORPHAN_GRACE_SECONDS,
                       stall_seconds: float = STALL_WARNING_SECONDS) -> float | None:
    """One heartbeat: wake logging, orphan watchdog, stall warning, caffeinate health."""
    now = time.time() if now is None else now
    tasks = list(tasks)
    active = [t for t in tasks if t.status in ACTIVE_STATUSES]

    slept = detector.check() if detector else None
    if slept:
        start = time.strftime("%H:%M", time.localtime(now - slept))
        end = time.strftime("%H:%M", time.localtime(now))
        note = (" trotz aktiver Schlafsperre (z. B. Deckel geschlossen oder Akkubetrieb)"
                if sleep_assertion_active() else "")
        msg = (f"⏸ System war {_fmt_duration(slept)} im Ruhezustand ({start}–{end}){note} – "
               f"Verarbeitung läuft weiter.")
        logger.warning(f"{msg} Aktive Tasks: {[t.task_id for t in active]}")
        for task in active:
            publish(task, {"status": "log", "message": msg})

    detect_orphaned_tasks(tasks, now, orphan_grace_seconds)

    for task in active:
        if task.job_running() and task.last_event_at and not task.stall_warned:
            idle = now - task.last_event_at
            if idle >= stall_seconds:
                publish(task, {"status": "log",
                               "message": f"⏳ Seit {_fmt_duration(idle)} keine Fortschrittsmeldung – Job läuft noch."})
                task.stall_warned = True

    if any(t.job_running() for t in tasks) and ensure_sleep_assertion_alive():
        for task in active:
            publish(task, {"status": "log", "message": "☕ Schlafsperre (caffeinate) wurde neu gestartet."})
    return slept


async def heartbeat_loop(list_tasks: Callable[[], Iterable], interval: float = HEARTBEAT_INTERVAL_SECONDS):
    """Background loop started in the FastAPI lifespan."""
    detector = WakeDetector()
    while True:
        await asyncio.sleep(interval)
        try:
            run_heartbeat_once(list_tasks(), detector)
        except Exception:
            logger.exception("Heartbeat failed")
