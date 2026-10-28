#!/usr/bin/env python3
"""
Benchmark Run Analysis & Diagnostics Tool for E-Buch Standard Converter.
Loads a benchmark run record (JSON) and outputs detailed category diagnostics,
weakness analysis, and comparative diffs against golden ground truth references.
"""

import os
import sys
import json
import glob
import argparse
from typing import Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(PROJECT_ROOT, "benchmarks", "runs")


def get_latest_run_file() -> str:
    """Returns the filepath of the latest benchmark run JSON."""
    if not os.path.exists(RUNS_DIR):
        raise FileNotFoundError(f"Runs directory {RUNS_DIR} does not exist.")
    ts_files = sorted(glob.glob(os.path.join(RUNS_DIR, "run_20*.json")))
    if ts_files:
        return ts_files[-1]
    files = sorted(glob.glob(os.path.join(RUNS_DIR, "run_*.json")), key=os.path.getmtime)
    if not files:
        raise FileNotFoundError("No benchmark run records found in benchmarks/runs/.")
    return files[-1]


def format_score(score: float, threshold_good: float = 80.0, threshold_warn: float = 60.0) -> str:
    """Colorizes or badges score for console rendering."""
    if score >= threshold_good:
        return f"\033[92m{score:5.1f}%\033[0m"
    elif score >= threshold_warn:
        return f"\033[93m{score:5.1f}%\033[0m"
    else:
        return f"\033[91m{score:5.1f}%\033[0m"


def analyze_run(run_data: Dict[str, Any], show_details: bool = False, target_engine: str = None) -> None:
    """Prints comprehensive benchmark run diagnostics to stdout."""
    run_id = run_data.get("run_id", "Unknown")
    timestamp = run_data.get("timestamp", "Unknown")
    summary = run_data.get("summary", [])
    summary_digital = run_data.get("summary_digital", [])
    summary_scanned = run_data.get("summary_scanned", [])
    details = run_data.get("details", {})

    print("=" * 90)
    print(f" 📊 E-BUCH BENCHMARK RUN ANALYSIS: Run {run_id} ({timestamp})")
    print("=" * 90)

    # 1. Digital Standings
    if summary_digital:
        print("\n📄 DIGITAL NATIVE DOCUMENTS STANDINGS:")
        print("-" * 80)
        print(f"{'Rank':<5} {'Engine':<16} {'Raw Score':<14} {'Übertragung 09/25':<22} {'Speed (s/pg)':<12}")
        print("-" * 80)
        dig_sorted = sorted(summary_digital, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
        for idx, row in enumerate(dig_sorted, 1):
            eng = row.get("engine", "")
            raw = f"{row.get('composite_raw', 0):.1f}/100"
            ub = f"{row.get('composite_uebertragung_2025', 0):.1f}/100"
            spd = f"{row.get('sec_per_page', 0):.2f} s"
            print(f"#{idx:<4} {eng:<16} {raw:<14} {ub:<22} {spd:<12}")

    # 2. Scanned Standings
    if summary_scanned:
        print("\n📸 SCANNED IMAGE (300 DPI RASTER) STANDINGS:")
        print("-" * 80)
        print(f"{'Rank':<5} {'Engine':<16} {'Raw Score':<14} {'Übertragung 09/25':<22} {'Speed (s/pg)':<12}")
        print("-" * 80)
        scan_sorted = sorted(summary_scanned, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
        for idx, row in enumerate(scan_sorted, 1):
            eng = row.get("engine", "")
            raw = f"{row.get('composite_raw', 0):.1f}/100"
            ub = f"{row.get('composite_uebertragung_2025', 0):.1f}/100"
            spd = f"{row.get('sec_per_page', 0):.2f} s"
            print(f"#{idx:<4} {eng:<16} {raw:<14} {ub:<22} {spd:<12}")

    # 3. Multi-Dimension Category Matrix
    print("\n🔍 MULTI-DIMENSION CATEGORY BREAKDOWN (Übertragungsregeln Profile):")
    print("-" * 165)
    print(f"{'Engine':<16} {'Source':<10} {'Headings (10%)':<15} {'Formulas (12%)':<15} {'Tables (12%)':<14} {'Images (10%)':<14} {'Boxes (8%)':<13} {'Text Comp (15%)':<16} {'Flow (10%)':<13} {'A11y (5%)':<11} {'LLM Judge (18%)':<16}")
    print("-" * 165)
    for row in summary:
        eng = row.get("engine", "")
        if target_engine and eng != target_engine:
            continue
        src = row.get("source_type", "Overall")
        h = format_score(row.get("ueb_headings", 0))
        f = format_score(row.get("ueb_formulas", 0))
        t = format_score(row.get("ueb_tables", 0))
        img_s = format_score(row.get("ueb_images", row.get("raw_images", 100.0)))
        box_s = format_score(row.get("ueb_boxes", 100.0))
        w = format_score(row.get("ueb_word_recall", row.get("ueb_continuity", 0)))
        c = format_score(row.get("ueb_continuity", 0))
        a = format_score(row.get("ueb_a11y", 0))
        j = format_score(row.get("ueb_judge", 0))
        print(f"{eng:<16} {src:<10} {h:<24} {f:<24} {t:<23} {img_s:<23} {box_s:<22} {w:<25} {c:<22} {a:<20} {j}")

    # 4. Automated Bottlenecks & Diagnostic Insights
    print("\n💡 AUTOMATED ENGINE WEAKNESS & BOTTLENECK DIAGNOSTICS:")
    print("-" * 90)
    diagnostics = []
    for row in summary:
        eng = row.get("engine", "")
        src = row.get("source_type", "Overall")
        prefix = f"[{eng.upper()} - {src}]"
        
        # Check formulas
        if row.get("ueb_formulas", 0) < 70.0:
            diagnostics.append(f"  • {prefix} STEM Formula Score low ({row.get('ueb_formulas')}%) -> Check LaTeX delimiters, formula placeholders, and inline math tag wrapping (<L>).")
        # Check headings
        if row.get("ueb_headings", 0) < 65.0:
            diagnostics.append(f"  • {prefix} Heading Hierarchy F1 low ({row.get('ueb_headings')}%) -> Check H1/H2 decimal numbering or font height bbox clustering.")
        # Check tables
        if row.get("ueb_tables", 0) < 75.0:
            diagnostics.append(f"  • {prefix} Table Structural Recall low ({row.get('ueb_tables')}%) -> Check table header formatting and multi-column row separators.")
        # Check images
        if row.get("ueb_images", 100.0) < 75.0:
            diagnostics.append(f"  • {prefix} Image / <Bild> Score low ({row.get('ueb_images')}%) -> Check layout picture cropping and multi-line FIBS <Bild> formatting.")
        # Check continuity
        if row.get("ueb_continuity", 0) < 40.0:
            diagnostics.append(f"  • {prefix} Reading Flow / Dehyphenation low ({row.get('ueb_continuity')}%) -> Verify ((num)) page boundary insertion and soft hyphen removal.")

    if diagnostics:
        for diag in diagnostics:
            print(diag)
    else:
        print("  ✅ All evaluated metrics are within optimal target bounds (>= 70-80%).")

    # 5. Detailed Document Breakdown (if requested)
    if show_details and details:
        print("\n📋 DOCUMENT-LEVEL METRIC BREAKDOWN:")
        print("-" * 90)
        for eng, data in details.items():
            if target_engine and eng != target_engine:
                continue
            print(f"\n▶ Extraction Engine: {eng.upper()}")
            for doc_name, metrics in data.get("details_by_doc", {}).items():
                std_back = metrics.get("standardisation_backend", "gemma")
                chunks = metrics.get("standardisation_chunks", 0)
                mem_mb = metrics.get("peak_memory_mb", 0.0)
                print(
                    f"  📄 Document: {doc_name} ({metrics.get('pages', 0)} pages, {metrics.get('duration_seconds', 0)}s, "
                    f"std={std_back}, chunks={chunks}, peak_rss={mem_mb} MB)"
                )
                raw_m = metrics.get("raw_metrics", {})
                ueb_m = metrics.get("uebertragung_metrics", {})
                print(
                    f"     Raw:         Headings: {raw_m.get('headings', {}).get('score')}% | Formulas: {raw_m.get('formulas', {}).get('score')}% | "
                    f"Tables: {raw_m.get('tables', {}).get('score')}% | Images: {raw_m.get('images', {}).get('score')}% | "
                    f"Boxes: {raw_m.get('boxes', {}).get('score', 100.0)}% | Monotonicity: {raw_m.get('page_monotonicity', {}).get('score', 100.0)}%"
                )
                print(
                    f"     Übertragung: Headings: {ueb_m.get('headings', {}).get('score')}% | Formulas: {ueb_m.get('formulas', {}).get('score')}% | "
                    f"Tables: {ueb_m.get('tables', {}).get('score')}% | Images: {ueb_m.get('images', {}).get('score')}% | "
                    f"Boxes: {ueb_m.get('boxes', {}).get('score', 100.0)}% | DOCX Bookmarks: {ueb_m.get('docx_bookmarks', {}).get('score', 100.0)}%"
                )

    print("\n" + "=" * 90)


def main():
    parser = argparse.ArgumentParser(description="Analyze and diagnose benchmark runs.")
    parser.add_argument("--run-file", type=str, help="Path to specific run JSON file. Defaults to latest in benchmarks/runs/.")
    parser.add_argument("--run-id", type=str, help="Specific run ID (e.g. 20260819_152103).")
    parser.add_argument("--external-data-dir", type=str, default=None, help="Optional external publisher testdata directory (e.g. ../ebuch-testdaten).")
    parser.add_argument("--details", action="store_true", help="Show document-level breakdown.")
    parser.add_argument("--engine", type=str, help="Filter analysis for a specific engine (lightonocr, infinity, docling).")
    args = parser.parse_args()

    active_runs_dir = (
        os.path.join(os.path.abspath(args.external_data_dir), "benchmarks", "runs")
        if args.external_data_dir
        else RUNS_DIR
    )

    if args.run_file:
        run_file = args.run_file
    elif args.run_id:
        run_file = os.path.join(active_runs_dir, f"run_{args.run_id}.json")
    else:
        if args.external_data_dir:
            ts_files = sorted(glob.glob(os.path.join(active_runs_dir, "run_*.json")))
            if not ts_files:
                print(f"Error: No run files found in {active_runs_dir}.", file=sys.stderr)
                sys.exit(1)
            run_file = ts_files[-1]
        else:
            run_file = get_latest_run_file()

    if not os.path.exists(run_file):
        print(f"Error: Run file {run_file} not found.", file=sys.stderr)
        sys.exit(1)

    with open(run_file, "r", encoding="utf-8") as f:
        run_data = json.load(f)

    analyze_run(run_data, show_details=args.details, target_engine=args.engine)


if __name__ == "__main__":
    main()

