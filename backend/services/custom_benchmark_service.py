"""Custom multi-engine benchmark evaluation service for user-uploaded PDFs and ground truths."""

import json
import logging
import os
import re
import time
from typing import Any

from backend.services.diff_service import get_diff_highlighting
from backend.services.llm_service import release_gpu_memory, standardise_markdown
from scripts.run_benchmark import (
    compute_doc_composite,
    evaluate_a11y,
    evaluate_boxes,
    evaluate_formulas,
    evaluate_headings,
    evaluate_images,
    evaluate_tables,
    evaluate_text_and_continuity,
    evaluate_with_gemma_judge,
    get_engine_version,
    run_docling_extraction,
    run_infinity_extraction,
    run_lightonocr_extraction,
)

logger = logging.getLogger("custom_benchmark_service")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _score_candidate_against_ground_truth(
    std_md: str,
    ground_truth_md: str,
    ruleset_key: str,
    dataset_name: str,
    image_dir: str | None = None,
    task: Any | None = None,
    idx: int = 0,
    engine: str = "",
    raw_markdown: str | None = None,
    expected_pages: int | None = None,
) -> tuple[float, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Computes programmatic metrics, Gemma 4 LLM Judge score, and composite score for one engine output."""
    if task:
        task.update_progress("Berechne AST-, Tabellen-, Bild- und STEM-Metriken...", idx, engine, 0.75)
    h_metric = evaluate_headings(std_md, ground_truth_md)
    f_metric = evaluate_formulas(std_md, ground_truth_md)
    t_metric = evaluate_tables(std_md, ground_truth_md)
    i_metric = evaluate_images(std_md, ground_truth_md, dataset_name=dataset_name, image_dir=image_dir)
    b_metric = evaluate_boxes(std_md, ground_truth_md)
    c_metric = evaluate_text_and_continuity(std_md, ground_truth_md)
    gt_pages = len(list(dict.fromkeys(re.findall(r"\(\((\d+)\)\)", ground_truth_md))))
    a_metric = evaluate_a11y(
        std_md,
        raw_markdown=raw_markdown,
        expected_pages=expected_pages or (gt_pages if gt_pages > 0 else None),
    )

    if task:
        task.update_progress("Gemma 4 LLM-Judge Qualitäts-Analyse...", idx, engine, 0.85)
    judge_profile = "raw" if ruleset_key == "raw" else "uebertragungsregeln_09_2025"
    prog_metrics = {
        "headings": h_metric,
        "formulas": f_metric,
        "tables": t_metric,
        "continuity": c_metric,
        "images": i_metric,
        "boxes": b_metric,
        "a11y": a_metric,
    }
    j_metric = evaluate_with_gemma_judge(
        std_md,
        ground_truth_md,
        profile=judge_profile,
        programmatic_metrics=prog_metrics,
    )
    composite = compute_doc_composite(
        {**prog_metrics, "judge": j_metric},
        include_boxes=(judge_profile != "raw"),
    )
    return composite, h_metric, f_metric, t_metric, i_metric, c_metric, a_metric, j_metric


def run_single_engine_extraction(
    engine: str,
    pdf_path: str,
    output_dir: str,
    extracted_cache: dict[str, tuple[str, float]] | None = None,
    task: Any | None = None
) -> tuple[str, float]:
    """Runs extraction for a single specified engine, utilizing cache if available."""
    if extracted_cache is None:
        extracted_cache = {}

    if engine in extracted_cache:
        if task:
            task.add_log(f"Wiederverwendung vorhandener Extraktion für [{engine}].")
        return extracted_cache[engine]

    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    cached_md_file = os.path.join(output_dir, f"{base_name}.md")
    if os.path.exists(cached_md_file):
        try:
            with open(cached_md_file, encoding="utf-8") as cf:
                cached_md = cf.read()
            if cached_md.strip():
                if task:
                    task.add_log(f"⚡ Wiederverwendung bestehender Extraktion für [{engine}] von Festplatte.")
                return cached_md, 0.1
        except Exception:
            pass
    
    if engine == "docling":
        if task:
            task.add_log("Starte Docling Layout-Extraktions-Prozess...")
        res = run_docling_extraction(pdf_path, output_dir, task=task)
        if task:
            task.add_log(f"Docling Extraktion abgeschlossen ({res[1]}s).")
        return res
        
    elif engine in ("infinity", "infinity_parser"):
        if task:
            task.add_log("Starte Infinity-Parser2-Flash Extraktions-Prozess...")
        res = run_infinity_extraction(pdf_path, output_dir, task=task)
        if task:
            task.add_log(f"Infinity-Parser2 Extraktion abgeschlossen ({res[1]}s).")
        return res

    elif engine in ("lightonocr", "lightonocr3"):
        if task:
            task.add_log("Starte LightOnOCR-3 Extraktions-Prozess...")
        res = run_lightonocr_extraction(pdf_path, output_dir, task=task)
        if task:
            task.add_log(f"LightOnOCR-3 Extraktion abgeschlossen ({res[1]}s).")
        return res

    else:
        raise ValueError(f"Unknown extraction engine: {engine}")


def evaluate_custom_submission(
    source_pdf_path: str,
    ground_truth_md: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    engines: list[str] | None = None,
    task_id: str | None = None,
    pages: str | None = None
) -> dict[str, Any]:
    """Evaluates one or more layout extraction engines on a user-uploaded PDF
    directly against a user-provided ground truth Markdown document.
    Integrates with BenchmarkTaskManager for progress updates, live logging, abort, and skip.
    """
    from backend.services.benchmark_task_manager import benchmark_task_manager
    from backend.services.diff_service import strip_ground_truth_preamble
    from backend.services.extraction_service import detect_physical_start_page

    ground_truth_md = strip_ground_truth_preamble(ground_truth_md)
    task = benchmark_task_manager.get_task(task_id) if task_id else None
    
    if pages:
        m = re.search(r"(\d+)", pages)
        physical_start_page = int(m.group(1)) if m else 1
    else:
        physical_start_page = detect_physical_start_page(source_pdf_path)

    if not engines:
        engines = ["docling", "infinity", "lightonocr"]

    import pypdfium2
    try:
        pdf = pypdfium2.PdfDocument(source_pdf_path)
        page_count = len(pdf)
    except Exception:
        page_count = 1

    temp_base = os.path.join(PROJECT_ROOT, "assets", "output", task_id or f"custom_bench_{int(time.time())}")
    os.makedirs(temp_base, exist_ok=True)

    # Persist ground truth markdown to task directory for re-evaluation
    try:
        gt_save_path = os.path.join(temp_base, "ground_truth.md")
        with open(gt_save_path, "w", encoding="utf-8") as f:
            f.write(ground_truth_md)
    except Exception as e:
        logger.warning(f"Could not persist ground_truth.md: {e}")

    extracted_cache: dict[str, tuple[str, float]] = {}
    engine_results = []
    license_tags = {
        "lightonocr": "Apache 2.0 (Commercial)",
        "infinity": "Apache 2.0 (Commercial)",
        "docling": "Apache 2.0 (Commercial)",
    }

    if task:
        task.status = "running"
        task.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        task.add_log(f"Benchmark gestartet über {len(engines)} Engine(s) auf {page_count} Seite(n).")

    for idx, engine in enumerate(engines):
        # 0. Check abort before engine starts
        if task and task.is_abort_requested():
            task.add_log(f"Benchmark bei Engine [{engine}] abgebrochen.", level="warning")
            break

        if task:
            task.reset_skip_flag()
            task.update_progress(f"Extrahiere Layout mit [{engine}]...", idx, engine, 0.1)

        eng_out_dir = os.path.join(temp_base, engine)
        logger.info(f"--> Benchmarking [{engine}] on custom source PDF ({page_count} pages)...")
        
        # 1. Extraction (reusing already extracted Docling / Infinity / LightOnOCR if cached)
        try:
            raw_md, duration = run_single_engine_extraction(engine, source_pdf_path, eng_out_dir, extracted_cache=extracted_cache, task=task)
            extracted_cache[engine] = (raw_md, duration)
        except Exception as e:
            logger.error(f"Extraction failed for {engine}: {e}")
            if task:
                task.add_log(f"Fehler bei Extraktion mit {engine}: {str(e)}", level="error")
            raw_md = f"# Extraktionsfehler ({engine})\n{str(e)}"
            duration = 1.0

        # Check skip/abort after extraction
        if task and task.is_abort_requested():
            break
        if task and task.should_skip_engine():
            task.add_log(f"Engine [{engine}] nach Extraktion übersprungen.")
            continue

        # 2. Sequential GPU release
        if task:
            task.update_progress("Bereinige Apple Silicon GPU Cache...", idx, engine, 0.35)
        release_gpu_memory()

        # 3. Gemma standardization if ruleset requested (with document-specific custom_ruleset.txt support)
        if ruleset_key != "raw" and raw_md and not raw_md.startswith("# Extraktionsfehler"):
            if task:
                task.update_progress(f"Gemma 4 12B Standardisierung ({ruleset_key})...", idx, engine, 0.5)
            logger.info(f"Applying Gemma standardization [{ruleset_key}] for {engine}...")
            try:
                std_md = standardise_markdown(raw_md, ruleset_key=ruleset_key, task_id=task_id, physical_start_page=physical_start_page)
            except Exception as e:
                logger.error(f"Standardization failed for {engine}: {e}")
                std_md = raw_md
        else:
            std_md = raw_md

        # Check skip/abort after standardization
        if task and task.is_abort_requested():
            break
        if task and task.should_skip_engine():
            task.add_log(f"Engine [{engine}] nach Standardisierung übersprungen.")
            continue

        # 4. Evaluation against uploaded ground truth
        i_img_dir = os.path.join(eng_out_dir, "images")
        (
            composite,
            h_metric,
            f_metric,
            t_metric,
            i_metric,
            c_metric,
            a_metric,
            j_metric,
        ) = _score_candidate_against_ground_truth(
            std_md=std_md,
            ground_truth_md=ground_truth_md,
            ruleset_key=ruleset_key,
            dataset_name=os.path.basename(source_pdf_path),
            image_dir=i_img_dir,
            task=task,
            idx=idx,
            engine=engine,
            raw_markdown=raw_md,
            expected_pages=page_count,
        )

        # 5. Side-by-side diff against ground truth
        diff_html = get_diff_highlighting(ground_truth_md, std_md)

        # 6. Generate candidate DOCX for comparison and download
        if task:
            task.update_progress("Erstelle barrierefreies Word DOCX...", idx, engine, 0.95)
        from backend.services.docx_service import convert_markdown_to_docx
        engine_docx_path = os.path.join(eng_out_dir, f"{engine}_output.docx")
        has_docx = False
        try:
            convert_markdown_to_docx(std_md, engine_docx_path)
            has_docx = True
        except Exception as e:
            logger.error(f"Failed to generate candidate DOCX for {engine}: {e}")

        result_item = {
            "engine": engine,
            "version": get_engine_version(engine),
            "license": license_tags.get(engine, "Open Source"),
            "composite_score": round(composite, 1),
            "headings_score": h_metric["score"],
            "formulas_score": f_metric["score"],
            "tables_score": t_metric["score"],
            "images_score": i_metric["score"],
            "continuity_score": c_metric["score"],
            "a11y_score": a_metric["score"],
            "judge_score": j_metric.get("overall_judge_score", 0.0),
            "judge_feedback": j_metric.get("judge_feedback") or j_metric.get("comment") or "LLM-as-a-Judge übersprungen (Offline/Timeout).",
            "speed_sec_per_page": round(duration / page_count, 2),
            "total_duration_seconds": round(duration, 2),
            "raw_markdown": raw_md,
            "extracted_markdown": std_md,
            "has_docx": has_docx,
            "docx_url": f"/api/benchmark/download-docx/{task_id}/{engine}" if task_id else None,
            "diff_html": diff_html
        }
        engine_results.append(result_item)
        if task:
            task.add_log(f"Engine [{engine}] abgeschlossen: Gesamt-Score {round(composite, 1)}/100 ({round(duration, 1)}s)")

    # Sort descending by composite score
    engine_results.sort(key=lambda x: x["composite_score"], reverse=True)

    final_evaluation = {
        "task_id": task_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ruleset": ruleset_key,
        "page_count": page_count,
        "rankings": engine_results
    }

    if task:
        task.results = final_evaluation
        task.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if task.status != "aborted":
            task.status = "completed"
            task.progress_percent = 100.0
            task.current_phase = "Benchmark erfolgreich abgeschlossen!"
            task.add_log("✅ Alle Benchmark-Evaluierungen erfolgreich abgeschlossen.")

    # Save state to task directory for persistence across restarts
    try:
        state_file = os.path.join(temp_base, "benchmark_state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "status": task.status if task else "completed",
                "evaluation": final_evaluation
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save benchmark_state.json: {e}")

    return final_evaluation


def re_evaluate_submission(task_id: str) -> dict[str, Any]:
    """Re-evaluates an existing extraction run against ground truth:
    recalculates headings, formulas, tables, continuity, accessibility,
    queries Gemma 4 for a fresh LLM-as-a-Judge assessment,
    recalculates composite score, and regenerates side-by-side visual diffs.
    """
    from backend.services.benchmark_task_manager import benchmark_task_manager
    from backend.services.diff_service import get_diff_highlighting, strip_ground_truth_preamble
    from scripts.run_benchmark import (
        get_engine_version,
    )

    output_dir = os.path.join(PROJECT_ROOT, "assets", "output")
    task_dir = os.path.join(output_dir, task_id)
    if not os.path.exists(task_dir):
        raise FileNotFoundError(f"Task directory {task_id} not found.")

    # 1. Load existing task status or benchmark state
    task_st_file = os.path.join(task_dir, "task_status.json")
    st_file = os.path.join(task_dir, "benchmark_state.json")
    task_data = {}
    if os.path.exists(task_st_file):
        try:
            with open(task_st_file, encoding="utf-8") as f:
                task_data = json.load(f)
        except Exception as e:
            logger.warning(f"Error reading {task_st_file}: {e}")

    if not task_data and os.path.exists(st_file):
        try:
            with open(st_file, encoding="utf-8") as f:
                task_data = json.load(f)
        except Exception as e:
            logger.warning(f"Error reading {st_file}: {e}")

    # 2. Find ground truth markdown
    gt_md = ""
    for gt_name in ["ground_truth_extracted.md", "ground_truth.md"]:
        gt_candidate = os.path.join(task_dir, gt_name)
        if os.path.exists(gt_candidate):
            with open(gt_candidate, encoding="utf-8") as f:
                gt_md = f.read()
            break

    if not gt_md and os.path.exists(task_dir):
        # Look for any reference markdown file that is not an engine output
        for f in os.listdir(task_dir):
            if f.endswith(".md") and not any(f.startswith(pfx) for pfx in ["docling", "infinity", "lightonocr"]):
                try:
                    with open(os.path.join(task_dir, f), encoding="utf-8") as gtf:
                        candidate_text = gtf.read()
                        if candidate_text:
                            gt_md = candidate_text
                            break
                except Exception:
                    pass
            
    if not gt_md:
        # Check if there is a DOCX reference file that can be extracted
        for f in os.listdir(task_dir):
            if f.endswith(".docx") and not f.endswith("_output.docx"):
                try:
                    from backend.services.docx_service import extract_markdown_from_docx
                    gt_md = extract_markdown_from_docx(os.path.join(task_dir, f))
                    if gt_md:
                        break
                except Exception:
                    pass

    if not gt_md:
        raise ValueError("Ground truth reference markdown not found for this task.")

    gt_md_clean = strip_ground_truth_preamble(gt_md)

    # 3. Retrieve rankings / engine outputs to re-evaluate
    old_eval = task_data.get("results") or task_data.get("evaluation") or {}
    old_rankings = old_eval.get("rankings", [])
    if not old_rankings:
        raise ValueError("No engine rankings found to re-evaluate.")

    task = benchmark_task_manager.get_task(task_id)
    if task:
        task.add_log("🔄 Starte Neu-Evaluierung aller Extraktionen mit aktuellen Metriken & neuem LLM-Judge...")

    license_tags = {
        "lightonocr": "Apache 2.0 (Commercial)",
        "infinity": "Apache 2.0 (Commercial)",
        "docling": "Apache 2.0 (Commercial)",
    }
    source_filename = task_data.get("source_filename", "")

    updated_rankings = []
    for item in old_rankings:
        engine = item.get("engine", "unknown")
        raw_md = item.get("raw_markdown", "")
        std_md = item.get("extracted_markdown", "") or raw_md

        # Re-evaluate all metrics against cleaned ground truth
        i_img_dir = os.path.join(item.get("output_dir", ""), "images") if item.get("output_dir") else None
        (
            composite,
            h_metric,
            f_metric,
            t_metric,
            i_metric,
            c_metric,
            a_metric,
            j_metric,
        ) = _score_candidate_against_ground_truth(
            std_md=std_md,
            ground_truth_md=gt_md_clean,
            ruleset_key=task_data.get("ruleset") or "uebertragungsregeln_09_2025",
            dataset_name=source_filename,
            image_dir=i_img_dir,
            raw_markdown=raw_md,
            expected_pages=old_eval.get("page_count") or None,
        )

        diff_html = get_diff_highlighting(gt_md_clean, std_md)

        updated_item = dict(item)
        updated_item.update({
            "version": get_engine_version(engine),
            "license": license_tags.get(engine, item.get("license", "Open Source")),
            "composite_score": round(composite, 1),
            "headings_score": h_metric["score"],
            "formulas_score": f_metric["score"],
            "tables_score": t_metric["score"],
            "images_score": i_metric["score"],
            "continuity_score": c_metric["score"],
            "a11y_score": a_metric["score"],
            "judge_score": j_metric.get("overall_judge_score", 0.0),
            "judge_feedback": j_metric.get("judge_feedback") or j_metric.get("comment") or "LLM-as-a-Judge aktualisiert.",
            "diff_html": diff_html
        })
        updated_rankings.append(updated_item)
        if task:
            task.add_log(f"Engine [{engine}] neu evaluiert: Gesamt-Score {round(composite, 1)}/100 (Judge: {round(j_metric.get('overall_judge_score', 0.0), 1)})")

    # Sort descending by composite score
    updated_rankings.sort(key=lambda x: x["composite_score"], reverse=True)

    results_data = {
        "task_id": task_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ruleset": task_data.get("ruleset", "uebertragungsregeln_09_2025"),
        "page_count": old_eval.get("page_count", 1),
        "rankings": updated_rankings
    }

    # Update in-memory task
    if task:
        task.results = results_data
        task.add_log("✅ Neu-Evaluierung erfolgreich abgeschlossen.")
        task.save_status_to_disk()

    # Save to task_status.json
    task_data["results"] = results_data
    task_data["status"] = "completed"
    try:
        with open(task_st_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving updated task_status.json: {e}")

    # Save to benchmark_state.json
    try:
        state_payload = {
            "task_id": task_id,
            "status": "completed",
            "evaluation": results_data
        }
        with open(st_file, "w", encoding="utf-8") as f:
            json.dump(state_payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving updated benchmark_state.json: {e}")

    return {
        "task_id": task_id,
        "status": "completed",
        "results": results_data,
        "evaluation": results_data,
        "logs": [entry.to_dict() if hasattr(entry, "to_dict") else entry for entry in task.logs] if task else task_data.get("logs", [])
    }
