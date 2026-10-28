import os
import shutil
import pytest

# Ensure E2E_MOCK is set so tests don't try to load heavy weights or spawn VLM servers
os.environ["E2E_MOCK"] = "true"

from backend.services.benchmark_task_manager import benchmark_task_manager, OUTPUT_DIR

def _purge_test_artifacts():
    with benchmark_task_manager._lock:
        # Clear only test tasks from manager
        test_ids = [tid for tid in benchmark_task_manager._tasks if tid.startswith("test_") or tid.startswith("dummy_") or tid.startswith("custom_bench_")]
        for tid in test_ids:
            del benchmark_task_manager._tasks[tid]

    if os.path.exists(OUTPUT_DIR):
        for item in os.listdir(OUTPUT_DIR):
            # Only delete test directories, never real user benchmark runs
            if item.startswith("test_") or item.startswith("dummy_") or item.startswith("custom_bench_"):
                item_path = os.path.join(OUTPUT_DIR, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)

@pytest.fixture(autouse=True)
def clean_benchmark_test_artifacts():
    """
    Autouse fixture that purges test-specific benchmark task outputs
    before and after every test.
    """
    _purge_test_artifacts()
    yield
    _purge_test_artifacts()

def pytest_sessionfinish(session, exitstatus):
    """Guarantees test cleanup at the end of the test session."""
    _purge_test_artifacts()
