"""Task state and persistence manager for custom and official benchmark runs."""

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("benchmark_task_manager")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCHMARK_RUNS_DIR = os.path.join(PROJECT_ROOT, "benchmarks", "runs")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "assets", "output")


class BenchmarkTask:
    """Thread-safe state container for a multi-engine benchmark evaluation task."""

    def __init__(
        self,
        task_id: str,
        source_filename: str,
        ground_truth_filename: str,
        ruleset: str,
        engines: list[str],
        has_custom_rules: bool = False
    ):
        self.task_id = task_id
        self.source_filename = source_filename
        self.ground_truth_filename = ground_truth_filename
        self.ruleset = ruleset
        self.engines = engines
        self.has_custom_rules = has_custom_rules
        
        self.status = "queued"  # "queued", "running", "completed", "aborted", "failed"
        self.current_engine_idx = 0
        self.current_engine = engines[0] if engines else ""
        self.total_engines = len(engines)
        self.progress_percent = 0.0
        self.current_phase = "Initialisiere Benchmark..."
        self.error_message: str | None = None
        
        self.logs: list[dict[str, Any]] = []
        self.results: dict[str, Any] | None = None
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.started_at: str | None = None
        self.finished_at: str | None = None
        
        self._abort_requested = False
        self._skip_current_engine = False
        self._lock = threading.RLock()

    def save_status_to_disk(self):
        """Persist the current task status dictionary to task_status.json."""
        try:
            task_dir = os.path.join(OUTPUT_DIR, self.task_id)
            os.makedirs(task_dir, exist_ok=True)
            status_file = os.path.join(task_dir, "task_status.json")
            data = self.to_dict()
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed writing status file for {self.task_id}: {e}")

    def add_log(self, message: str, level: str = "info"):
        """Append a timestamped log entry and persist task status to disk."""
        with self._lock:
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "level": level,
                "message": message
            }
            self.logs.append(entry)
            if len(self.logs) > 200:
                self.logs.pop(0)
        self.save_status_to_disk()

    def update_progress(self, phase: str, engine_idx: int | None = None, engine_name: str | None = None, sub_percent: float = 0.0):
        """Update the active engine progress percentage, phase label, and log history."""
        with self._lock:
            self.current_phase = phase
            if engine_idx is not None:
                self.current_engine_idx = engine_idx
            if engine_name is not None:
                self.current_engine = engine_name
            
            if self.total_engines > 0:
                base_pct = (self.current_engine_idx / self.total_engines) * 100.0
                step_pct = (1.0 / self.total_engines) * sub_percent * 100.0
                self.progress_percent = min(round(base_pct + step_pct, 1), 99.0)
            
            entry = {
                "time": time.strftime("%H:%M:%S"),
                "level": "info",
                "message": f"[{self.current_engine or 'System'}] {phase}"
            }
            self.logs.append(entry)
            if len(self.logs) > 200:
                self.logs.pop(0)
        self.save_status_to_disk()

    def request_abort(self):
        """Mark the benchmark task as aborted by user request."""
        with self._lock:
            self._abort_requested = True
            self.status = "aborted"
            self.add_log("🛑 Abbruch durch Benutzer angefordert.", level="warning")

    def request_skip_engine(self):
        """Signal that the currently running OCR engine should be skipped."""
        with self._lock:
            self._skip_current_engine = True
            self.add_log(f"⏭️ Überspringen der Engine [{self.current_engine}] angefordert.", level="warning")

    def is_abort_requested(self) -> bool:
        """Return whether an abort has been requested for this task."""
        with self._lock:
            return self._abort_requested

    def should_skip_engine(self) -> bool:
        """Return whether the current engine should be skipped."""
        with self._lock:
            return self._skip_current_engine

    def reset_skip_flag(self):
        """Clear the skip-current-engine flag before starting the next engine."""
        with self._lock:
            self._skip_current_engine = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the benchmark task state to a JSON-compatible dictionary."""
        with self._lock:
            return {
                "task_id": self.task_id,
                "source_filename": self.source_filename,
                "ground_truth_filename": self.ground_truth_filename,
                "ruleset": self.ruleset,
                "engines": self.engines,
                "has_custom_rules": self.has_custom_rules,
                "status": self.status,
                "current_engine_idx": self.current_engine_idx,
                "current_engine": self.current_engine,
                "total_engines": self.total_engines,
                "progress_percent": self.progress_percent,
                "current_phase": self.current_phase,
                "error_message": self.error_message,
                "logs": list(self.logs),
                "results": self.results,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at
            }


class BenchmarkTaskManager:
    """Registry and disk history loader for benchmark tasks."""

    def __init__(self):
        self._tasks: dict[str, BenchmarkTask] = {}
        self._active_task_id: str | None = None
        self._lock = threading.RLock()

    def create_task(
        self,
        task_id: str,
        source_filename: str,
        ground_truth_filename: str,
        ruleset: str,
        engines: list[str],
        has_custom_rules: bool = False
    ) -> BenchmarkTask:
        """Create, register, and activate a new BenchmarkTask instance."""
        with self._lock:
            task = BenchmarkTask(
                task_id=task_id,
                source_filename=source_filename,
                ground_truth_filename=ground_truth_filename,
                ruleset=ruleset,
                engines=engines,
                has_custom_rules=has_custom_rules
            )
            self._tasks[task_id] = task
            self._active_task_id = task_id
            return task

    def get_task(self, task_id: str) -> BenchmarkTask | None:
        """Look up a registered BenchmarkTask by its task ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_task(self) -> BenchmarkTask | None:
        """Return the currently queued or running benchmark task, if any."""
        with self._lock:
            if not self._active_task_id:
                return None
            task = self._tasks.get(self._active_task_id)
            if task and task.status in ("queued", "running"):
                return task
            return None

    def delete_run(self, run_id: str) -> bool:
        """Delete a benchmark run from memory and remove its persisted disk artifacts."""
        import shutil
        deleted = False
        with self._lock:
            if run_id in self._tasks:
                del self._tasks[run_id]
                deleted = True
            if self._active_task_id == run_id:
                self._active_task_id = None

        # 1. Delete custom benchmark output directory from assets/output/
        folder_path = os.path.join(OUTPUT_DIR, run_id)
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            try:
                shutil.rmtree(folder_path)
                logger.info(f"Deleted custom benchmark directory from disk: {folder_path}")
                deleted = True
            except Exception as e:
                logger.error(f"Failed to delete benchmark run directory {folder_path}: {e}")

        # 2. Delete official benchmark run JSON file from benchmarks/runs/
        if os.path.exists(BENCHMARK_RUNS_DIR):
            for candidate in (f"{run_id}.json", f"run_{run_id}.json", run_id):
                file_path = os.path.join(BENCHMARK_RUNS_DIR, candidate)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted official benchmark record file from disk: {file_path}")
                        deleted = True
                    except Exception as e:
                        logger.error(f"Failed to delete official benchmark record {file_path}: {e}")

        return deleted

    def resume_unfinished_tasks(self, _executor=None, _evaluate_func=None) -> list[str]:
        """Scans assets/output/ on startup and marks any benchmark tasks interrupted by a server restart."""
        resumed_task_ids: list[str] = []
        if not os.path.exists(OUTPUT_DIR):
            return resumed_task_ids

        for folder in os.listdir(OUTPUT_DIR):
            if folder.startswith("test_") or folder.startswith("custom_bench_"):
                continue
            folder_path = os.path.join(OUTPUT_DIR, folder)
            if not os.path.isdir(folder_path):
                continue

            state_file = os.path.join(folder_path, "benchmark_state.json")
            status_file = os.path.join(folder_path, "task_status.json")

            # If benchmark_state.json exists, the task completed successfully
            if os.path.exists(state_file):
                continue

            if os.path.exists(status_file):
                try:
                    with open(status_file, encoding="utf-8") as f:
                        st_data = json.load(f)

                    status = st_data.get("status")
                    if status in ("running", "queued"):
                        task_id = folder
                        source_filename = st_data.get("source_filename")
                        ground_truth_filename = st_data.get("ground_truth_filename")
                        ruleset = st_data.get("ruleset", "uebertragungsregeln_09_2025")
                        engines = st_data.get("engines", ["lightonocr", "infinity", "docling"])
                        has_custom_rules = st_data.get("has_custom_rules", False)

                        source_path = os.path.join(folder_path, source_filename) if source_filename else None

                        if source_path and os.path.exists(source_path):
                            # Mark orphaned task as interrupted on startup to prevent unbounded concurrent GPU extractions
                            task = self.create_task(
                                task_id=task_id,
                                source_filename=source_filename or "document.pdf",
                                ground_truth_filename=ground_truth_filename or "reference.md",
                                ruleset=ruleset,
                                engines=engines,
                                has_custom_rules=has_custom_rules
                            )
                            task.status = "failed"
                            task.error_message = "Benchmark-Task wurde durch einen vorherigen Server-Neustart unterbrochen."
                            task.add_log("🛑 Benchmark-Task wurde durch einen Server-Neustart unterbrochen.", level="warning")
                            task.save_status_to_disk()
                            logger.info(f"Marked orphaned benchmark task {task_id} as interrupted after restart.")
                except Exception as e:
                    logger.error(f"Failed handling orphaned task {folder}: {e}")

        return resumed_task_ids

    def get_history(self) -> list[dict[str, Any]]:
        """Return a chronological list of custom and official benchmark runs."""
        history_items = []
        
        # 1. Include all in-memory custom benchmark runs (running, completed, failed - excluding aborted & test tasks)
        with self._lock:
            for t_id, task in self._tasks.items():
                if task.status == "aborted":
                    continue
                if t_id.startswith("test_") or t_id.startswith("custom_bench_") or task.source_filename in ("sample.pdf", "test.pdf"):
                    continue
                
                status_suffix = " (Läuft...)" if task.status in ("running", "queued") else (" (Fehlgeschlagen)" if task.status == "failed" else "")
                history_items.append({
                    "run_id": t_id,
                    "type": "custom",
                    "title": f"{task.source_filename}{status_suffix}",
                    "date": task.started_at or task.created_at,
                    "ruleset": task.ruleset,
                    "status": task.status,
                    "engines": task.engines,
                    "rankings_count": len(task.results.get("rankings", [])) if task.results else 0,
                    "top_score": task.results.get("rankings", [{}])[0].get("composite_score", 0.0) if task.results and task.results.get("rankings") else 0.0,
                    "top_engine": task.results.get("rankings", [{}])[0].get("engine", "-") if task.results and task.results.get("rankings") else "-"
                })

        seen_task_ids = {item["run_id"] for item in history_items}

        # 2. Include persistent custom runs from assets/output/ (excluding aborted & automated test tasks)
        if os.path.exists(OUTPUT_DIR):
            for folder in os.listdir(OUTPUT_DIR):
                if folder.startswith("test_") or folder.startswith("custom_bench_"):
                    continue
                folder_path = os.path.join(OUTPUT_DIR, folder)
                if os.path.isdir(folder_path) and folder not in seen_task_ids:
                    task_st_file = os.path.join(folder_path, "task_status.json")
                    st_file = os.path.join(folder_path, "benchmark_state.json")
                    target_file = task_st_file if os.path.exists(task_st_file) else (st_file if os.path.exists(st_file) else None)

                    if target_file:
                        try:
                            with open(target_file, encoding="utf-8") as f:
                                st_data = json.load(f)
                            
                            status = st_data.get("status", "completed")
                            if status == "aborted":
                                continue

                            src_filename = st_data.get("source_filename")
                            if not src_filename and os.path.exists(task_st_file) and target_file != task_st_file:
                                try:
                                    with open(task_st_file, encoding="utf-8") as tf:
                                        src_filename = json.load(tf).get("source_filename")
                                except Exception:
                                    pass

                            if not src_filename:
                                continue
                            if src_filename.lower() in ("sample.pdf", "test.pdf", "dummy.pdf", "dokument", "document.pdf") or src_filename.lower().startswith("test_") or src_filename.lower().startswith("dummy_"):
                                continue

                            eval_data = st_data.get("results") or st_data.get("evaluation") or {}
                            if not eval_data and os.path.exists(task_st_file) and target_file != task_st_file:
                                try:
                                    with open(task_st_file, encoding="utf-8") as tf:
                                        eval_data = json.load(tf).get("results", {})
                                except Exception:
                                    pass

                            rankings = eval_data.get("rankings", []) if isinstance(eval_data, dict) else []
                            top_score = rankings[0].get("composite_score", 0.0) if rankings else 0.0
                            top_engine = rankings[0].get("engine", "-") if rankings else "-"
                            
                            date_val = (
                                st_data.get("created_at") or
                                st_data.get("started_at") or
                                st_data.get("finished_at") or
                                (eval_data.get("timestamp") if isinstance(eval_data, dict) else None) or
                                st_data.get("timestamp") or
                                ""
                            )
                            status_suffix = " (Läuft...)" if status in ("running", "queued") else (" (Fehlgeschlagen)" if status == "failed" else "")
                            history_items.append({
                                "run_id": folder,
                                "type": "custom",
                                "title": f"{src_filename}{status_suffix}",
                                "date": date_val,
                                "ruleset": st_data.get("ruleset", "uebertragungsregeln_09_2025"),
                                "status": status,
                                "engines": st_data.get("engines", []),
                                "rankings_count": len(rankings),
                                "top_score": top_score,
                                "top_engine": top_engine
                            })
                            seen_task_ids.add(folder)
                        except Exception as e:
                            logger.error(f"Failed to read custom benchmark state for {folder}: {e}")

        # 3. Include persistent official runs from benchmarks/runs/
        if os.path.exists(BENCHMARK_RUNS_DIR):
            for file in sorted(os.listdir(BENCHMARK_RUNS_DIR), reverse=True):
                if file.startswith("run_") and file.endswith(".json"):
                    filepath = os.path.join(BENCHMARK_RUNS_DIR, file)
                    try:
                        with open(filepath, encoding="utf-8") as f:
                            run_data = json.load(f)
                        
                        run_id = run_data.get("run_id", file.replace(".json", ""))
                        timestamp = run_data.get("timestamp", "")
                        engines = run_data.get("engines", [])
                        datasets = run_data.get("datasets", [])
                        summary = run_data.get("summary_digital") or run_data.get("summary") or []
                        if isinstance(summary, dict):
                            summary = summary.get("digital", [])
                        
                        top_score = 0.0
                        top_engine = "-"
                        if isinstance(summary, list) and len(summary) > 0:
                            first_item = summary[0]
                            if isinstance(first_item, dict):
                                top_score = first_item.get("composite_uebertragung_2025") or first_item.get("composite_raw") or first_item.get("uebertragungsregeln_09_2025", 0.0)
                                top_engine = first_item.get("engine", "-")
                        
                        history_items.append({
                            "run_id": run_id,
                            "type": "official",
                            "title": f"Leaderboard Run ({len(datasets)} Dokumente)",
                            "date": timestamp,
                            "ruleset": "uebertragungsregeln_09_2025",
                            "status": "completed",
                            "engines": engines,
                            "rankings_count": len(summary) if isinstance(summary, list) else 0,
                            "top_score": top_score,
                            "top_engine": top_engine,
                            "filepath": filepath
                        })
                    except Exception as e:
                        logger.error(f"Failed to read run record {file}: {e}")

        # Sort newest first
        history_items.sort(key=lambda x: x.get("date", ""), reverse=True)
        return history_items

    def get_run_details(self, run_id: str) -> dict[str, Any] | None:
        """Load detailed evaluation results and logs for a specific benchmark run ID."""
        # 1. Check custom in-memory task
        with self._lock:
            task = self._tasks.get(run_id)
            if task and task.results:
                return {
                    "run_id": run_id,
                    "type": "custom",
                    "source_filename": task.source_filename,
                    "ground_truth_filename": task.ground_truth_filename,
                    "has_custom_rules": task.has_custom_rules,
                    "status": task.status,
                    "logs": [entry.to_dict() if hasattr(entry, "to_dict") else entry for entry in task.logs],
                    "evaluation": task.results
                }

        # 2. Check disk fallback for custom task (task_status.json or benchmark_state.json)
        task_dir = os.path.join(OUTPUT_DIR, run_id)
        status_file = os.path.join(task_dir, "task_status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file, encoding="utf-8") as f:
                    st_data = json.load(f)
                return {
                    "run_id": run_id,
                    "type": "custom",
                    "source_filename": st_data.get("source_filename", "Custom Document"),
                    "ground_truth_filename": st_data.get("ground_truth_filename", "Reference"),
                    "has_custom_rules": st_data.get("has_custom_rules", False),
                    "status": st_data.get("status", "completed"),
                    "logs": st_data.get("logs", []),
                    "evaluation": st_data.get("results") or st_data.get("evaluation")
                }
            except Exception as e:
                logger.error(f"Failed to read custom task_status.json for {run_id}: {e}")

        state_file = os.path.join(task_dir, "benchmark_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, encoding="utf-8") as f:
                    st_data = json.load(f)
                return {
                    "run_id": run_id,
                    "type": "custom",
                    "source_filename": st_data.get("source_filename", "Custom Document"),
                    "ground_truth_filename": st_data.get("ground_truth_filename", "Reference"),
                    "has_custom_rules": st_data.get("has_custom_rules", False),
                    "status": st_data.get("status", "completed"),
                    "logs": st_data.get("logs", []),
                    "evaluation": st_data.get("evaluation") or st_data.get("results")
                }
            except Exception as e:
                logger.error(f"Failed to read custom benchmark state for {run_id}: {e}")

        # 3. Check benchmarks/runs/
        if os.path.exists(BENCHMARK_RUNS_DIR):
            for file in os.listdir(BENCHMARK_RUNS_DIR):
                if (file == f"{run_id}.json" or file == f"run_{run_id}.json" or file == run_id) and file.endswith(".json"):
                    filepath = os.path.join(BENCHMARK_RUNS_DIR, file)
                    try:
                        with open(filepath, encoding="utf-8") as f:
                            run_data = json.load(f)
                        return {
                            "run_id": run_id,
                            "type": "official",
                            "run_data": run_data
                        }
                    except Exception as e:
                        logger.error(f"Failed reading run details {file}: {e}")

        return None


# Global Singleton Instance
benchmark_task_manager = BenchmarkTaskManager()
