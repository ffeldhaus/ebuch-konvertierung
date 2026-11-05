"""Custom multi-engine benchmark evaluation service for user-uploaded PDFs and ground truths."""

import asyncio
import json
import logging
import os
import re
import time
import uuid
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


def _generate_developer_feedback_report(
    std_md: str,
    ground_truth_md: str,
    existing_transfer: dict[str, Any],
    ruleset_key: str,
    task: Any | None = None,
) -> dict[str, Any]:
    """Generates and persists a Gemma 4 developer feedback report comparing an existing transfer to Ground Truth.

    Args:
        std_md: Standardised (or raw) Markdown from the existing conversion task.
        ground_truth_md: Reference Ground Truth Markdown.
        existing_transfer: Metadata and content dictionary of the existing conversion task.
        ruleset_key: Active benchmark ruleset key (``"raw"`` or ``"uebertragungsregeln_09_2025"``).
        task: Optional ``BenchmarkTask`` instance for live progress and log updates.

    Returns:
        Dictionary containing ``feedback_id``, ``source_task_id``, ``feedback_report``,
        ``open_questions``, ``change_summary``, and ``lint_comparison``.
    """
    from backend.services import feedback_service as fs
    from backend.services.prompts import build_analysis_prompt

    change_summary = fs.compute_change_summary(std_md, ground_truth_md)
    lint_cmp = fs.compare_lint_reports(std_md, ground_truth_md)
    if task:
        task.add_log(
            f"{change_summary['hunk_count']} Änderungsblöcke erkannt "
            f"(Ähnlichkeit {change_summary['similarity']:.1%})."
        )

    engine_name = str(existing_transfer.get("engine") or "infinity")
    task_meta = {
        "Quelldokument": existing_transfer.get("original_name") or "Unbekannt",
        "Engine": engine_name,
        "Standardisierungs-Backend": existing_transfer.get("standardisation_backend") or "gemma",
        "Seitenauswahl": existing_transfer.get("pages") or "alle",
        "Regelsatz": "Roh-Extraktion (Ohne LLM)"
        if ruleset_key == "raw"
        else "Übertragungsregeln FIBS (September 2025)",
    }
    final_prompt = build_analysis_prompt(change_summary, lint_cmp, "", task_meta, 0)

    source_task_id = str(existing_transfer.get("source_task_id") or (task.task_id if task else "bench"))
    feedback_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    work_dir = os.path.join(PROJECT_ROOT, "assets", "feedback", source_task_id, feedback_id)
    os.makedirs(work_dir, exist_ok=True)

    with open(os.path.join(work_dir, "original.md"), "w", encoding="utf-8") as f:
        f.write(std_md)
    with open(os.path.join(work_dir, "revised.md"), "w", encoding="utf-8") as f:
        f.write(ground_truth_md)

    if task:
        task.update_progress("Erstelle Gemma 4 Entwickler-Feedback-Bericht...", 0, engine_name, 0.9)

    if os.environ.get("E2E_MOCK") == "true":
        raw_report = fs.generate_mock_report(change_summary, "", [])
    else:
        release_gpu_memory()

        def _on_event(kind: str, data: dict[str, Any]) -> None:
            if task and kind == "log" and data.get("message"):
                task.add_log(str(data["message"]))

        try:
            analysis_res = asyncio.run(
                fs.run_gemma_feedback_analysis(final_prompt, [], work_dir, _on_event)
            )
            raw_report = str(analysis_res.get("report") or "")
        except Exception as exc:
            logger.warning("Gemma feedback analysis failed, using heuristic fallback report: %s", exc)
            raw_report = ""
        finally:
            release_gpu_memory()

        if not raw_report.strip():
            if task:
                task.add_log("Gemma lieferte keine Antwort – heuristischer Fallback-Bericht wird erstellt.")
            raw_report = fs.generate_mock_report(change_summary, "", [])

    report = fs.redact_long_passages(fs.normalize_report_markdown(raw_report), [std_md, ground_truth_md])
    report = report.rstrip() + "\n" + fs.build_statistics_appendix(change_summary, lint_cmp, task_meta)

    clean_change_summary = {k: v for k, v in change_summary.items() if k != "hunks"}
    with open(os.path.join(work_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    with open(os.path.join(work_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "feedback_id": feedback_id,
                "task_id": source_task_id,
                "created_at": time.time(),
                "original_name": existing_transfer.get("original_name") or "Unbekannt",
                "revised_filename": existing_transfer.get("ground_truth_filename") or "ground_truth.md",
                "region_count": 0,
                "regions": [],
                "region_findings": [],
                "change_summary": clean_change_summary,
                "lint_comparison": lint_cmp,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    open_questions = [q.model_dump() for q in fs.extract_open_questions(report)]
    return {
        "feedback_id": feedback_id,
        "source_task_id": source_task_id,
        "feedback_report": report,
        "open_questions": open_questions,
        "change_summary": clean_change_summary,
        "lint_comparison": lint_cmp,
    }


def evaluate_custom_submission(
    source_pdf_path: str,
    ground_truth_md: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    engines: list[str] | None = None,
    task_id: str | None = None,
    pages: str | None = None,
    existing_transfer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluates one or more layout extraction engines or an existing conversion against Ground Truth.

    Args:
        source_pdf_path: Path to the (optionally cropped) source PDF document.
        ground_truth_md: Reference Ground Truth Markdown text.
        ruleset_key: Active benchmark ruleset key (``"raw"`` or ``"uebertragungsregeln_09_2025"``).
        engines: List of OCR engine identifiers to benchmark.
        task_id: Benchmark task identifier for state and progress persistence.
        pages: Optional page selection string.
        existing_transfer: Optional dictionary with pre-existing conversion Markdown and metadata;
            when provided, skips re-extraction/re-standardisation and also generates a Gemma 4
            developer feedback report.

    Returns:
        Final evaluation dictionary containing rankings, metrics, and optional feedback report data.
    """
    from backend.services.benchmark_task_manager import benchmark_task_manager
    from backend.services.diff_service import strip_ground_truth_preamble
    from backend.services.extraction_service import detect_physical_start_page

    ground_truth_md = strip_ground_truth_preamble(ground_truth_md)
    task = benchmark_task_manager.get_task(task_id) if task_id else None

    if pages:
        m = re.search(r"(\d+)", pages)
        physical_start_page = int(m.group(1)) if m else 1
    elif os.path.exists(source_pdf_path):
        physical_start_page = detect_physical_start_page(source_pdf_path)
    else:
        physical_start_page = 1

    if existing_transfer:
        engines = [str(existing_transfer.get("engine") or (engines[0] if engines else "infinity")).strip().lower()]
    elif not engines:
        engines = ["docling", "infinity", "lightonocr"]

    import pypdfium2
    try:
        pdf = pypdfium2.PdfDocument(source_pdf_path)
        page_count = len(pdf)
    except Exception:
        gt_page_markers = list(dict.fromkeys(re.findall(r"\(\((\d+)\)\)", ground_truth_md)))
        page_count = max(1, len(gt_page_markers))

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
    feedback_data: dict[str, Any] = {}
    license_tags = {
        "lightonocr": "Apache 2.0 (Commercial)",
        "infinity": "Apache 2.0 (Commercial)",
        "docling": "Apache 2.0 (Commercial)",
    }

    if task:
        task.status = "running"
        task.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        if existing_transfer:
            task.add_log(
                f"Direkt-Vergleich & Entwickler-Feedback für bestehende Übertragung [{engines[0]}] auf {page_count} Seite(n) gestartet."
            )
        else:
            task.add_log(f"Benchmark gestartet über {len(engines)} Engine(s) auf {page_count} Seite(n).")

    for idx, engine in enumerate(engines):
        # 0. Check abort before engine starts
        if task and task.is_abort_requested():
            task.add_log(f"Benchmark bei Engine [{engine}] abgebrochen.", level="warning")
            break

        eng_out_dir = os.path.join(temp_base, engine)
        os.makedirs(eng_out_dir, exist_ok=True)

        if existing_transfer:
            if task:
                task.reset_skip_flag()
                task.update_progress(f"Übernehme bestehende Übertragung [{engine}]...", idx, engine, 0.25)
                task.add_log("Übernehme bestehende Übertragung aus Aufgabe (keine Neu-Extraktion erforderlich).")
            raw_md = str(existing_transfer.get("raw_markdown") or existing_transfer.get("standardised_markdown") or "")
            std_md = (
                str(existing_transfer.get("standardised_markdown") or raw_md)
                if ruleset_key != "raw"
                else raw_md
            )
            duration = max(0.1, float(existing_transfer.get("duration_seconds") or 1.0))
            base_name = os.path.splitext(os.path.basename(source_pdf_path))[0] or engine
            try:
                with open(os.path.join(eng_out_dir, f"{base_name}.md"), "w", encoding="utf-8") as rf:
                    rf.write(raw_md)
                with open(os.path.join(eng_out_dir, f"{engine}_standardised.md"), "w", encoding="utf-8") as sf:
                    sf.write(std_md)
            except Exception as e:
                logger.warning("Could not persist existing transfer markdown: %s", e)
        else:
            if task:
                task.reset_skip_flag()
                task.update_progress(f"Extrahiere Layout mit [{engine}]...", idx, engine, 0.1)

            logger.info(f"--> Benchmarking [{engine}] on custom source PDF ({page_count} pages)...")

            # 1. Extraction (reusing already extracted Docling / Infinity / LightOnOCR if cached)
            try:
                raw_md, duration = run_single_engine_extraction(
                    engine, source_pdf_path, eng_out_dir, extracted_cache=extracted_cache, task=task
                )
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
                    std_md = standardise_markdown(
                        raw_md, ruleset_key=ruleset_key, task_id=task_id, physical_start_page=physical_start_page
                    )
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
        if existing_transfer:
            ext_img_dir = str(existing_transfer.get("image_dir") or "")
            if ext_img_dir and os.path.isdir(ext_img_dir):
                i_img_dir = ext_img_dir
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

        result_item: dict[str, Any] = {
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
        if existing_transfer:
            feedback_data = _generate_developer_feedback_report(
                std_md=std_md,
                ground_truth_md=ground_truth_md,
                existing_transfer=existing_transfer,
                ruleset_key=ruleset_key,
                task=task,
            )
            result_item.update(feedback_data)
        engine_results.append(result_item)
        if task:
            task.add_log(f"Engine [{engine}] abgeschlossen: Gesamt-Score {round(composite, 1)}/100 ({round(duration, 1)}s)")

    # Sort descending by composite score
    engine_results.sort(key=lambda x: x["composite_score"], reverse=True)

    final_evaluation: dict[str, Any] = {
        "task_id": task_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "existing_transfer" if existing_transfer else "multi_engine_benchmark",
        "ruleset": ruleset_key,
        "page_count": page_count,
        "rankings": engine_results
    }
    if existing_transfer and feedback_data:
        final_evaluation.update(feedback_data)

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
    ruleset_key = task_data.get("ruleset") or "uebertragungsregeln_09_2025"
    for item in old_rankings:
        engine = item.get("engine", "unknown")
        raw_md = item.get("raw_markdown", "")
        std_md = item.get("extracted_markdown", "")
        eng_out_dir = item.get("output_dir") or os.path.join(task_dir, engine)
        if not std_md and ruleset_key != "raw":
            std_cand = os.path.join(eng_out_dir, f"{engine}_standardised.md")
            if os.path.exists(std_cand):
                try:
                    with open(std_cand, encoding="utf-8") as sf:
                        std_md = sf.read()
                except Exception:
                    pass
        std_md = std_md or raw_md

        # Re-evaluate all metrics against cleaned ground truth
        i_img_dir = os.path.join(eng_out_dir, "images") if os.path.isdir(os.path.join(eng_out_dir, "images")) else None
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
            ruleset_key=ruleset_key,
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

    results_data: dict[str, Any] = {
        "task_id": task_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": old_eval.get("mode", "multi_engine_benchmark"),
        "ruleset": task_data.get("ruleset", "uebertragungsregeln_09_2025"),
        "page_count": old_eval.get("page_count", 1),
        "rankings": updated_rankings,
    }
    for key in (
        "feedback_id",
        "source_task_id",
        "feedback_report",
        "open_questions",
        "change_summary",
        "lint_comparison",
    ):
        if key in old_eval:
            results_data[key] = old_eval[key]

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
