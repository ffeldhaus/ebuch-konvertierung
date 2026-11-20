"""
Tests for the end-to-end task lifecycle:

- background jobs owned by the task (survive HTTP client disconnects),
- per-job idempotent macOS sleep assertions (``caffeinate -i -s -w <pid>``),
- watchdog that marks orphaned "processing" tasks as ``interrupted``,
- resume endpoint,
- wake-from-sleep detection with injectable clocks.

All tests are fully offline and never spawn the real ``caffeinate`` binary.
"""
import asyncio
import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.services import task_manager as tm
from backend.services import task_jobs as tj
from backend.services.task_manager import Task


class FakeProc:
    """Minimal stand-in for ``subprocess.Popen`` used for caffeinate."""

    instances: list = []

    def __init__(self, cmd):
        self.cmd = cmd
        self.returncode = None
        self.terminated = False
        FakeProc.instances.append(self)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture(autouse=True)
def fake_caffeinate(monkeypatch):
    """Replace the caffeinate spawner and reset the global assertion state."""
    FakeProc.instances = []
    monkeypatch.setattr(tm, "_spawn_caffeinate", lambda: FakeProc(tm.caffeinate_command()))
    tm._reset_sleep_state_for_tests()
    yield
    tm._reset_sleep_state_for_tests()


def _make_task(task_id="lifecycle-test", status="pending") -> Task:
    return Task(task_id=task_id, original_name="doc.pdf", input_path="/nonexistent.pdf",
                extension=".pdf", status=status)


# ---------------------------------------------------------------------------
# Sleep assertion
# ---------------------------------------------------------------------------

def test_caffeinate_command_watches_backend_pid():
    cmd = tm.caffeinate_command()
    assert cmd[:4] == ["caffeinate", "-i", "-s", "-w"]
    assert cmd[4] == str(os.getpid())


def test_sleep_assertion_is_idempotent_per_owner():
    tm.acquire_sleep_assertion_sync("job-a")
    tm.acquire_sleep_assertion_sync("job-a")  # duplicate acquire must not double count
    tm.acquire_sleep_assertion_sync("job-b")
    assert len(FakeProc.instances) == 1
    assert tm.sleep_assertion_active()

    tm.release_sleep_assertion_sync("job-a")
    tm.release_sleep_assertion_sync("job-a")  # double release (e.g. abort + finally) is a no-op
    assert tm.sleep_assertion_active(), "job-b still holds the assertion"
    assert not FakeProc.instances[0].terminated

    tm.release_sleep_assertion_sync("job-b")
    assert not tm.sleep_assertion_active()
    assert FakeProc.instances[0].terminated


def test_anonymous_assertions_are_ref_counted():
    tm.acquire_sleep_assertion_sync()
    tm.acquire_sleep_assertion_sync()
    tm.release_sleep_assertion_sync()
    assert tm.sleep_assertion_active()
    tm.release_sleep_assertion_sync()
    assert not tm.sleep_assertion_active()
    tm.release_sleep_assertion_sync()  # never goes negative
    assert not tm.sleep_assertion_active()


def test_dead_caffeinate_is_respawned_while_assertion_is_held():
    tm.acquire_sleep_assertion_sync("job-x")
    FakeProc.instances[0].returncode = 1  # caffeinate died unexpectedly
    assert tm.ensure_sleep_assertion_alive() is True
    assert len(FakeProc.instances) == 2
    assert tm.ensure_sleep_assertion_alive() is False  # healthy -> nothing to do
    tm.release_sleep_assertion_sync("job-x")


# ---------------------------------------------------------------------------
# Task-owned background jobs
# ---------------------------------------------------------------------------

def test_job_survives_client_disconnect_and_holds_sleep_assertion():
    async def scenario():
        task = _make_task()
        task.status = "processing"
        gate = asyncio.Event()
        seen_active = []

        async def body():
            tj.publish(task, {"status": "log", "message": "Schritt 1"})
            seen_active.append(tm.sleep_assertion_active())
            await gate.wait()
            tj.publish(task, {"status": "progress", "percent": 50, "phase": "Hälfte"})
            task.status = "completed"
            tj.publish(task, {"status": "completed", "stage": "standardisation", "markdown": "ok"})

        queue = tj.attach_listener(task, replay=False)
        job = tj.start_task_job(task, "standardisation", body())
        stream = tj.listener_stream(task, queue)

        first = await stream.__anext__()
        assert "Schritt 1" in first
        # Simulate the browser going away (tab closed / AbortController / sleep).
        await stream.aclose()
        assert queue not in task.listeners

        gate.set()
        await asyncio.wait_for(job, timeout=2)
        assert task.status == "completed"
        assert seen_active == [True]
        assert not tm.sleep_assertion_active(), "assertion released exactly once after the job"
        assert task.job is None

    asyncio.run(scenario())


def test_reattached_listener_receives_replay_and_completion():
    async def scenario():
        task = _make_task()
        task.status = "processing"
        gate = asyncio.Event()

        async def body():
            tj.publish(task, {"status": "log", "message": "Alt-Log"})
            tj.publish(task, {"status": "token", "delta": "Hallo "})
            await gate.wait()
            tj.publish(task, {"status": "token", "delta": "Welt"})
            task.status = "completed"
            tj.publish(task, {"status": "completed", "stage": "standardisation", "markdown": "Hallo Welt"})

        job = tj.start_task_job(task, "standardisation", body())
        await asyncio.sleep(0.01)

        queue = tj.attach_listener(task)
        gate.set()
        lines = [line async for line in tj.listener_stream(task, queue)]
        events = [json.loads(l) for l in lines]
        assert any(e.get("message") == "Alt-Log" for e in events)
        assert any(e.get("status") == "stream_snapshot" and e.get("text") == "Hallo " for e in events)
        assert events[-1]["status"] == "completed"
        await job

    asyncio.run(scenario())


def test_cancelled_job_kills_subprocess_and_releases_assertion():
    async def scenario():
        task = _make_task()
        task.status = "processing"
        proc = FakeProc(["vlm"])

        async def body():
            task.process = proc
            await asyncio.sleep(10)

        job = tj.start_task_job(task, "standardisation", body())
        await asyncio.sleep(0.01)
        assert tm.sleep_assertion_active()
        tj.cancel_task_job(task)
        await asyncio.gather(job, return_exceptions=True)
        assert proc.terminated
        assert not tm.sleep_assertion_active()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# VLM resume checkpoint
# ---------------------------------------------------------------------------

def test_vlm_checkpoint_roundtrip_and_prompt_binding(tmp_path):
    from backend.services import vlm_describer as vd
    cache = str(tmp_path / "vlm_cache.json")
    vd.save_cache(cache, "PROMPT A", {"/img/1.png": "BILDART: Foto", "/img/2.png": ""})
    loaded = vd.load_cache(cache, "PROMPT A")
    assert loaded == {"/img/1.png": "BILDART: Foto"}, "failed (empty) descriptions are retried"
    assert vd.load_cache(cache, "PROMPT B") == {}, "a changed prompt invalidates the checkpoint"
    assert vd.load_cache(str(tmp_path / "missing.json"), "PROMPT A") == {}


# ---------------------------------------------------------------------------
# Watchdog / interrupted status
# ---------------------------------------------------------------------------

def test_watchdog_marks_orphaned_processing_task_interrupted_after_grace():
    task = _make_task(status="processing")
    task.progress["phase"] = "Analysiere Bild 3/10 (VLM)..."
    marked = tj.detect_orphaned_tasks([task], now=1000.0, grace_seconds=30)
    assert marked == []  # first sighting only starts the grace period
    marked = tj.detect_orphaned_tasks([task], now=1031.0, grace_seconds=30)
    assert marked == [task]
    assert task.status == "interrupted"
    assert "Unterbrochen" in task.progress["phase"]
    assert any("unterbrochen" in log.lower() for log in task.logs)


def test_watchdog_ignores_tasks_with_running_job():
    async def scenario():
        task = _make_task(status="processing")
        gate = asyncio.Event()
        job = tj.start_task_job(task, "standardisation", gate.wait())
        await asyncio.sleep(0)
        assert tj.detect_orphaned_tasks([task], now=0, grace_seconds=0) == []
        assert tj.detect_orphaned_tasks([task], now=100, grace_seconds=0) == []
        gate.set()
        await job

    asyncio.run(scenario())


def test_recovered_processing_task_becomes_interrupted(tmp_path, monkeypatch):
    from backend.services.task_manager import TaskManager
    base = tmp_path
    task_id = "recover-interrupted-test"
    out_dir = base / "assets" / "output" / task_id
    out_dir.mkdir(parents=True)
    (out_dir / "task_info.json").write_text(json.dumps({
        "task_id": task_id, "original_name": "x.pdf", "status": "processing",
        "progress": {"percent": 92, "phase": "Lade Gemma VLM Modell...", "current": 0, "total": 0},
        "ruleset": "uebertragungsregeln_09_2025",
    }), encoding="utf-8")
    monkeypatch.setattr(tm, "_project_root", lambda: str(base))
    task = TaskManager()._recover_from_disk(task_id)
    assert task.status == "interrupted"
    assert task.progress["percent"] == 92
    assert task.to_summary_dict()["resumable"] is True


# ---------------------------------------------------------------------------
# Wake detection
# ---------------------------------------------------------------------------

def test_wake_detector_reports_sleep_gap():
    clock = {"wall": 1000.0, "mono": 50.0}
    det = tj.WakeDetector(threshold_seconds=20, wall=lambda: clock["wall"], mono=lambda: clock["mono"])
    clock["wall"] += 5
    clock["mono"] += 5
    assert det.check() is None  # normal heartbeat
    clock["wall"] += 605  # 10 min of sleep: wall clock advances ...
    clock["mono"] += 5    # ... but the monotonic clock does not (macOS)
    gap = det.check()
    assert gap == pytest.approx(600)


def test_heartbeat_logs_wake_event_to_active_tasks():
    clock = {"wall": 0.0, "mono": 0.0}
    det = tj.WakeDetector(threshold_seconds=20, wall=lambda: clock["wall"], mono=lambda: clock["mono"])
    active = _make_task("active", status="processing")
    done = _make_task("done", status="completed")
    q = asyncio.Queue()
    active.listeners.append(q)
    clock["wall"] += 185
    clock["mono"] += 5
    tj.run_heartbeat_once([active, done], det, now=clock["wall"], orphan_grace_seconds=10_000)
    assert any("Ruhezustand" in log for log in active.logs)
    assert not any("Ruhezustand" in log for log in done.logs)
    assert "Ruhezustand" in q.get_nowait()


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def interrupted_task():
    """Registers an interrupted task with a saved raw extraction on disk."""
    from backend.main import task_manager, OUTPUT_DIR
    task_id = "test_resume_task"
    out_dir = os.path.join(OUTPUT_DIR, task_id)
    os.makedirs(os.path.join(out_dir, task_id), exist_ok=True)
    with open(os.path.join(out_dir, task_id, f"{task_id}.md"), "w", encoding="utf-8") as f:
        f.write("# Titel\n\nEin **fetter** Satz.")
    task = Task(task_id=task_id, original_name="resume.docx", input_path="/nonexistent.docx",
                extension=".docx", status="interrupted")
    task.raw_markdown = "# Titel\n\nEin **fetter** Satz."
    task_manager._tasks[task_id] = task
    yield task
    task_manager._tasks.pop(task_id, None)
    shutil.rmtree(out_dir, ignore_errors=True)


@pytest.fixture
def lifespan_client(monkeypatch):
    """TestClient with a persistent event loop (lifespan) so background jobs keep running
    between requests. Benchmark auto-resume is disabled to never touch real runs."""
    from backend.services.benchmark_task_manager import benchmark_task_manager
    monkeypatch.setattr(benchmark_task_manager, "resume_unfinished_tasks", lambda *a, **k: [])
    from backend.main import app
    with TestClient(app) as client:
        yield client


def test_resume_endpoint_restarts_standardisation(interrupted_task, lifespan_client, monkeypatch):
    monkeypatch.setattr("backend.services.llm_service.start_rapid_mlx", lambda: None)
    client = lifespan_client
    res = client.post(f"/api/tasks/{interrupted_task.task_id}/resume")
    assert res.status_code == 200
    assert res.json()["stage"] == "standardisation"
    with client.stream("GET", f"/api/tasks/{interrupted_task.task_id}/stream") as stream:
        events = [json.loads(l) for l in stream.iter_lines() if l.strip()]
    assert events[-1]["status"] == "completed"
    assert "_fetter_" in events[-1]["markdown"]
    assert interrupted_task.status == "completed"


def test_resume_endpoint_rejects_completed_task(interrupted_task, lifespan_client):
    interrupted_task.status = "completed"
    res = lifespan_client.post(f"/api/tasks/{interrupted_task.task_id}/resume")
    assert res.status_code == 409


def test_gpu_semaphore_queues_concurrent_jobs_sequentially():
    """Tests 4c: concurrent jobs wait on the per-loop GPU semaphore with status='queued'."""
    async def scenario():
        tj.reset_gpu_semaphore_for_tests()
        t1 = _make_task("job-1", status="processing")
        t2 = _make_task("job-2", status="processing")
        gate1 = asyncio.Event()
        order = []

        async def body1():
            order.append("start-1")
            await gate1.wait()
            order.append("end-1")
            t1.status = "completed"

        async def body2():
            order.append("start-2")
            t2.status = "completed"

        j1 = tj.start_task_job(t1, "extraction", body1())
        await asyncio.sleep(0.01)
        assert order == ["start-1"]

        # Starting j2 while j1 holds the GPU slot must place t2 into 'queued'
        j2 = tj.start_task_job(t2, "standardisation", body2())
        await asyncio.sleep(0.01)
        assert t2.status == "queued"
        assert any("Warteschlange" in log for log in t2.logs)
        assert "start-2" not in order

        # Releasing j1 allows j2 to transition to 'processing' and complete
        gate1.set()
        await asyncio.gather(j1, j2)
        assert order == ["start-1", "end-1", "start-2"]
        assert t1.status == "completed"
        assert t2.status == "completed"

    asyncio.run(scenario())


def test_extract_persists_meta_and_chains_standardisation_on_disconnect(
    lifespan_client, tmp_path, monkeypatch
):
    """Verifies /api/extract persists task_info.json and chains Stage 2+3 when chain_standardise=true."""
    import backend.main as main_mod
    from backend.main import task_manager

    out_dir = tmp_path / "assets" / "output"
    up_dir = tmp_path / "assets" / "uploads"
    out_dir.mkdir(parents=True)
    up_dir.mkdir(parents=True)
    monkeypatch.setattr(tm, "_project_root", lambda: str(tmp_path))
    monkeypatch.setattr(main_mod, "OUTPUT_DIR", str(out_dir))
    monkeypatch.setattr(main_mod, "UPLOAD_DIR", str(up_dir))
    monkeypatch.setattr("backend.services.llm_service.start_rapid_mlx", lambda: None)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    async def fake_extraction(*, task, **_kwargs):
        raw_md = "((1))\n\n# 1 Mechanik\n\nEin **wichtiger** Merksatz zur Bewegung."
        task["raw_markdown"] = raw_md
        task["images"] = []
        task["status"] = "completed"
        task["progress"] = {
            "percent": 25,
            "current": 1,
            "total": 1,
            "unit": "Seiten",
            "phase": "Extraktion abgeschlossen",
        }
        task["logs"].append("Mock-Extraktion beendet.")
        completed_line = json.dumps(
            {
                "status": "completed",
                "markdown": raw_md,
                "image_count": 0,
                "progress_percent": 25,
            }
        ) + "\n"
        for q in list(task["listeners"]):
            await q.put(completed_line)
            await q.put(None)

    monkeypatch.setattr(main_mod, "run_background_extraction", fake_extraction)

    # 1. Standalone /api/extract (chain_standardise=False default) persists completed status to task_info.json
    standalone_id = "test-extract-standalone"
    src_file = up_dir / f"{standalone_id}.txt"
    src_file.write_text("Beispiel", encoding="utf-8")
    t_standalone = Task(
        task_id=standalone_id,
        original_name="probe.txt",
        input_path=str(src_file),
        extension=".txt",
        status="pending",
    )
    task_manager._tasks[standalone_id] = t_standalone
    try:
        with lifespan_client.stream(
            "POST", "/api/extract", data={"task_id": standalone_id}
        ) as res:
            assert res.status_code == 200
            events = [json.loads(ln) for ln in res.iter_lines() if ln.strip()]
        assert events[-1]["status"] == "completed"
        meta_file = out_dir / standalone_id / "task_info.json"
        assert meta_file.exists()
        saved_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert saved_meta["status"] == "completed"
        assert "Mock-Extraktion beendet." in saved_meta["logs_tail"]
        assert t_standalone.standardised_markdown is None
    finally:
        task_manager._tasks.pop(standalone_id, None)

    # 2. Chained /api/extract (chain_standardise=true) runs Stage 2+3 server-side without client calling /api/standardise
    chained_id = "test-extract-chained"
    src_file2 = up_dir / f"{chained_id}.txt"
    src_file2.write_text("Beispiel", encoding="utf-8")
    t_chained = Task(
        task_id=chained_id,
        original_name="kapitel.txt",
        input_path=str(src_file2),
        extension=".txt",
        status="pending",
    )
    task_manager._tasks[chained_id] = t_chained
    try:
        with lifespan_client.stream(
            "POST",
            "/api/extract",
            data={
                "task_id": chained_id,
                "ruleset": "uebertragungsregeln_09_2025",
                "chain_standardise": "true",
            },
        ) as res:
            assert res.status_code == 200
            ext_events = [json.loads(ln) for ln in res.iter_lines() if ln.strip()]
        assert ext_events[-1]["status"] == "completed"

        # Client never calls /api/standardise (simulates sleep/disconnect); attach to /stream to await completion
        with lifespan_client.stream("GET", f"/api/tasks/{chained_id}/stream") as stream:
            std_events = [json.loads(ln) for ln in stream.iter_lines() if ln.strip()]
        assert std_events[-1]["status"] == "completed"
        assert std_events[-1].get("stage") == "standardisation"
        assert "_wichtiger_" in (t_chained.standardised_markdown or "")
        assert (out_dir / chained_id / "standardise_request.json").exists()
        chained_meta = json.loads(
            (out_dir / chained_id / "task_info.json").read_text(encoding="utf-8")
        )
        assert chained_meta["status"] == "completed"
        assert not tm.sleep_assertion_active()
    finally:
        task_manager._tasks.pop(chained_id, None)

