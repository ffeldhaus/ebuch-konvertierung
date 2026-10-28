#!/usr/bin/env python3
import os
import sys
import time
import json
import re
import difflib
import glob
import argparse
import logging
import tempfile
import zipfile
try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Enforce strict offline inference during benchmark execution (AGENTS.md §2)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.extraction_postprocess import apply_extraction_postprocess
from backend.services.a11y_linter import lint_markdown
from backend.services.formula_service import standardize_formulas
from backend.services.diff_service import strip_ground_truth_preamble, extract_document_components
from backend.services.llm_service import release_gpu_memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("benchmark_runner")

GOLDEN_DIR = os.path.join(PROJECT_ROOT, "testdata", "golden")
RUNS_DIR = os.path.join(PROJECT_ROOT, "benchmarks", "runs")
LEADERBOARD_PATH = os.path.join(PROJECT_ROOT, "benchmarks", "LEADERBOARD.md")

os.makedirs(RUNS_DIR, exist_ok=True)
os.makedirs(GOLDEN_DIR, exist_ok=True)


# -------------------------------------------------------------
# 1. Programmatic Evaluation Metrics
# -------------------------------------------------------------

def evaluate_headings(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """
    Calculates precision, recall, and hierarchical structure accuracy for headings.
    Rather than requiring rigid absolute heading numbers (e.g. H2 vs H3), it evaluates:
    1. Text F1 (precision & recall of heading text titles using 1-to-1 matching).
    2. Hierarchy Consistency: Subheadings in gold remain strictly deeper than their parent
       headings in prediction (P_child > P_parent), and sibling headings retain equal levels.
    """
    gold_md = strip_ground_truth_preamble(gold_md)
    pred_headings = [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#+)\s+(.+)$", pred_md, re.MULTILINE)]
    gold_headings = [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#+)\s+(.+)$", gold_md, re.MULTILINE)]

    if not gold_headings:
        return {"score": 100.0, "f1": 100.0, "hierarchy_accuracy": 100.0, "pred_count": len(pred_headings), "gold_count": 0, "matched_count": 0}

    gold_texts = [h[1] for h in gold_headings]
    candidates = []
    for p_idx, (p_level, p_text) in enumerate(pred_headings):
        for g_idx, g_text in enumerate(gold_texts):
            ratio = difflib.SequenceMatcher(None, p_text.lower(), g_text.lower(), autojunk=False).ratio()
            if ratio >= 0.7:
                candidates.append((ratio, -abs(p_idx - g_idx), p_idx, g_idx))

    candidates.sort(reverse=True)
    used_p = set()
    used_g = set()
    matched_by_p = []
    for _ratio, _dist, p_idx, g_idx in candidates:
        if p_idx not in used_p and g_idx not in used_g:
            used_p.add(p_idx)
            used_g.add(g_idx)
            p_level, p_text = pred_headings[p_idx]
            matched_by_p.append((p_idx, g_idx, gold_headings[g_idx][0], p_level, p_text))

    matched_by_p.sort(key=lambda x: x[0])
    matches = [(g_idx, g_lvl, p_lvl, p_txt) for (_p_idx, g_idx, g_lvl, p_lvl, p_txt) in matched_by_p]

    precision = (len(matches) / len(pred_headings)) if pred_headings else 0.0
    recall = (len(matches) / len(gold_headings)) if gold_headings else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Evaluate relative hierarchy consistency across all matched pairs
    pairs_correct = 0
    total_pairs = 0
    for i in range(len(matches)):
        for j in range(i + 1, len(matches)):
            g_i, g_level_i, p_level_i, _ = matches[i]
            g_j, g_level_j, p_level_j, _ = matches[j]
            if g_i == g_j:
                continue
            total_pairs += 1
            if g_level_i < g_level_j and p_level_i < p_level_j:
                pairs_correct += 1
            elif g_level_i > g_level_j and p_level_i > p_level_j:
                pairs_correct += 1
            elif g_level_i == g_level_j and p_level_i == p_level_j:
                pairs_correct += 1

    hierarchy_acc = (pairs_correct / total_pairs) if total_pairs > 0 else (1.0 if matches else 0.0)
    score = round(min(100.0, (f1 * 0.6 + hierarchy_acc * 0.4) * 100), 1)

    return {
        "score": score,
        "f1": round(f1 * 100, 1),
        "hierarchy_accuracy": round(hierarchy_acc * 100, 1),
        "pred_count": len(pred_headings),
        "gold_count": len(gold_headings),
        "matched_count": len(matches)
    }


def _normalize_formula_for_comparison(f_str: str) -> str:
    """Normalizes LaTeX wrappers (\\text{...}, \\mathrm{...}, <L>, spacing, decimal commas) for semantic formula comparison."""
    s = re.sub(r"<\/?L>", "", f_str)
    s = re.sub(r"\\(?:text|mathrm)\s*\{\s*([^\}]*?)\s*\}", r"\1", s)
    s = s.replace("{,}", ",").replace("\\,", "").replace("\\;", "").replace("\\quad", "").replace("\\qquad", "")
    s = re.sub(r"([_\^])\{\s*([a-zA-Z0-9])\s*\}", r"\1\2", s)
    s = re.sub(r"\s+", "", s)
    return s


def evaluate_formulas(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """Calculates STEM formula extraction accuracy and LaTeX math precision."""
    gold_md = strip_ground_truth_preamble(gold_md)
    # Strip legacy <L> tags and find all formula blocks in pred (<L>...</L>, $$...$$, $...$)
    pred_formulas = re.findall(r"<L>(.*?)</L>|\$\$(.*?)\$\$|\$([^\$\n]+)\$", pred_md, re.DOTALL)
    pred_f_texts = [("".join(f)).strip() for f in pred_formulas if ("".join(f)).strip()]
    
    # Strip legacy <L> tags and find all formula blocks in gold (<L>...</L>, $$...$$, $...$)
    gold_formulas = re.findall(r"<L>(.*?)</L>|\$\$(.*?)\$\$|\$([^\$\n]+)\$", gold_md, re.DOTALL)
    gold_f_texts = [("".join(f)).strip() for f in gold_formulas if ("".join(f)).strip()]
    
    if not gold_f_texts:
        return {"score": 100.0 if not pred_f_texts else 95.0, "f1": 100.0, "gold_count": 0, "pred_count": len(pred_f_texts)}
    
    matches = 0
    for gf in gold_f_texts:
        gf_clean = _normalize_formula_for_comparison(gf)
        for pf in pred_f_texts:
            pf_clean = _normalize_formula_for_comparison(pf)
            if difflib.SequenceMatcher(None, gf_clean, pf_clean, autojunk=False).ratio() >= 0.75:
                matches += 1
                break
                
    recall = matches / len(gold_f_texts)
    precision = (matches / len(pred_f_texts)) if pred_f_texts else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    
    score = round(f1 * 100, 1)
    return {
        "score": score,
        "f1": round(f1 * 100, 1),
        "pred_count": len(pred_f_texts),
        "gold_count": len(gold_f_texts)
    }


def evaluate_tables(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """Calculates table detection and structural cell content recovery across extracted tables."""
    gold_md = strip_ground_truth_preamble(gold_md)
    comp_gold = extract_document_components(gold_md)
    comp_pred = extract_document_components(pred_md)
    
    gold_tables = comp_gold["tables"]
    pred_tables = comp_pred["tables"]
    
    if not gold_tables:
        return {"score": 100.0, "detected": bool(pred_tables), "has_tables": False, "cell_recall": 100.0, "gold_count": 0, "pred_count": len(pred_tables)}
    
    if not pred_tables:
        return {"score": 0.0, "detected": False, "has_tables": True, "cell_recall": 0.0, "gold_count": len(gold_tables), "pred_count": 0}
    
    def _clean_table_blob(blob: str) -> str:
        s = re.sub(r"<Anmerkung>\s*Die folgende Tabelle wurde aufgelöst\.\s*</Anmerkung>", " ", blob, flags=re.IGNORECASE)
        s = re.sub(r"</?(?:Tabelle|table|tr|td|th|thead|tbody)\b[^>]*>", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"\\(?:text|mathrm)\b", " ", s)
        return s

    # Extract cell words across tables
    gold_text_blob = _clean_table_blob("\n".join(gold_tables))
    pred_text_blob = _clean_table_blob("\n".join(pred_tables))
    gold_cells = set(re.findall(r"\b[A-Za-z0-9_äöüÄÖÜß]{2,}\b", gold_text_blob))
    pred_cells = set(re.findall(r"\b[A-Za-z0-9_äöüÄÖÜß]{2,}\b", pred_text_blob))
    
    overlap = len(gold_cells.intersection(pred_cells))
    recall = (overlap / len(gold_cells)) if gold_cells else 1.0
    precision = (overlap / len(pred_cells)) if pred_cells else 1.0
    cell_f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    
    # Table count ratio
    count_ratio = min(len(pred_tables), len(gold_tables)) / max(len(pred_tables), len(gold_tables))
    score = round((cell_f1 * 0.7 + count_ratio * 0.3) * 100, 1)
    
    return {
        "score": score,
        "detected": True,
        "has_tables": True,
        "cell_recall": round(recall * 100, 1),
        "cell_precision": round(precision * 100, 1),
        "gold_count": len(gold_tables),
        "pred_count": len(pred_tables)
    }


def load_golden_image_metadata(external_data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Loads ground truth image metadata containing bounding boxes, dimensions, and captions."""
    merged: Dict[str, Any] = {}
    cand_dirs = [os.path.join(PROJECT_ROOT, "testdata", "golden")]
    ext_dir = external_data_dir or os.environ.get("EBUCH_TESTDATEN_DIR") or os.path.abspath(os.path.join(PROJECT_ROOT, "..", "ebuch-testdaten"))
    if ext_dir and os.path.isdir(ext_dir):
        cand_dirs.append(os.path.join(ext_dir, "testdata", "golden"))
    for gdir in cand_dirs:
        meta_path = os.path.join(gdir, "golden_image_metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    merged.update(json.load(f))
            except Exception:
                pass
    return merged


def evaluate_images(
    pred_md: str,
    gold_md: str,
    dataset_name: Optional[str] = None,
    image_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Calculates image detection count, presence, aspect ratio / dimension accuracy,
    and E-Buch standard compliance against golden ground truth metadata without requiring slow VLM execution.
    """
    gold_md = strip_ground_truth_preamble(gold_md)
    comp_gold = extract_document_components(gold_md)
    comp_pred = extract_document_components(pred_md)
    
    gold_imgs = comp_gold.get("images", [])
    pred_imgs = comp_pred.get("images", [])
    
    # Check if dataset metadata exists in golden_image_metadata.json
    meta = load_golden_image_metadata()
    doc_meta = None
    if dataset_name:
        doc_key = os.path.basename(dataset_name)
        doc_meta = meta.get(doc_key) or meta.get(f"{doc_key}.pdf") or meta.get(doc_key.replace("_scanned", ""))
    
    if doc_meta is not None:
        gold_count = max(len(doc_meta.get("images", [])), len(gold_imgs))
        expected_aspect_ratios = [img.get("aspect_ratio", 1.5) for img in doc_meta.get("images", [])]
    else:
        gold_count = len(gold_imgs)
        expected_aspect_ratios = []

    pred_count = len(pred_imgs)
    
    # Check physical extracted image files on disk if image_dir provided
    extracted_aspect_ratios = []
    if image_dir and os.path.exists(image_dir):
        try:
            from PIL import Image
            for f in os.listdir(image_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    try:
                        with Image.open(os.path.join(image_dir, f)) as im:
                            w, h = im.size
                            if h > 0:
                                extracted_aspect_ratios.append(round(w / h, 2))
                    except Exception:
                        pass
        except ImportError:
            pass
    
    if gold_count == 0:
        score = 100.0 if pred_count == 0 else max(0.0, 100.0 - pred_count * 20.0)
        return {
            "score": score,
            "f1": 100.0 if pred_count == 0 else 0.0,
            "dimension_match": 100.0,
            "tag_compliance": 100.0,
            "gold_count": 0,
            "pred_count": pred_count,
            "matched_count": 0
        }
        
    if pred_count == 0:
        return {
            "score": 0.0,
            "f1": 0.0,
            "dimension_match": 0.0,
            "tag_compliance": 0.0,
            "gold_count": gold_count,
            "pred_count": 0,
            "matched_count": 0
        }
        
    # Detection count matching (Precision, Recall, F1)
    matched_count = min(gold_count, pred_count)
    recall = matched_count / gold_count
    precision = matched_count / pred_count
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Dimension & aspect ratio verification
    dim_match_score = 1.0
    if expected_aspect_ratios and extracted_aspect_ratios:
        # Check how many extracted aspect ratios match expected within 25% tolerance
        matches = 0
        for exp_ar in expected_aspect_ratios:
            if any(abs(ext_ar - exp_ar) / exp_ar <= 0.25 for ext_ar in extracted_aspect_ratios):
                matches += 1
        dim_match_score = matches / len(expected_aspect_ratios)
    elif expected_aspect_ratios:
        dim_match_score = f1

    # E-Buch tag compliance (<Bild> Bildart: ... </Bild> incl. multi-line FIBS format, or ![alt](...))
    proper_tagged = sum(1 for p in pred_imgs if re.search(r"<Bild\b[^>]*>\s*[^\n:<]{1,40}:\s*.+?</Bild>", p, re.DOTALL | re.IGNORECASE) or p.startswith("!["))
    tag_compliance = proper_tagged / pred_count if pred_count else 1.0

    score = round((f1 * 0.5 + dim_match_score * 0.3 + tag_compliance * 0.2) * 100, 1)
    return {
        "score": score,
        "f1": round(f1 * 100, 1),
        "dimension_match": round(dim_match_score * 100, 1),
        "tag_compliance": round(tag_compliance * 100, 1),
        "gold_count": gold_count,
        "pred_count": pred_count,
        "matched_count": matched_count
    }


def evaluate_boxes(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """Calculates <Rahmen> callout box detection and content recovery."""
    gold_md = strip_ground_truth_preamble(gold_md)
    comp_gold = extract_document_components(gold_md)
    comp_pred = extract_document_components(pred_md)
    
    gold_boxes = comp_gold["boxes"]
    pred_boxes = comp_pred["boxes"]
    
    if not gold_boxes:
        return {"score": 100.0 if not pred_boxes else 95.0, "gold_count": 0, "pred_count": len(pred_boxes)}
    if not pred_boxes:
        return {"score": 0.0, "gold_count": len(gold_boxes), "pred_count": 0}
        
    def _clean_box(b: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[_*]+", "", re.sub(r"<[^>]+>", "", b))).strip().lower()

    clean_gold = [_clean_box(b) for b in gold_boxes if _clean_box(b)]
    clean_pred = [_clean_box(b) for b in pred_boxes if _clean_box(b)]

    gold_blob = "\n".join(clean_gold)
    pred_blob = "\n".join(clean_pred)

    sim_order = difflib.SequenceMatcher(None, gold_blob, pred_blob, autojunk=False).ratio()
    sim_sorted = difflib.SequenceMatcher(
        None, "\n".join(sorted(clean_gold)), "\n".join(sorted(clean_pred)), autojunk=False
    ).ratio()
    sim = max(sim_order, sim_sorted)
    score = round(sim * 100, 1)
    return {
        "score": score,
        "gold_count": len(gold_boxes),
        "pred_count": len(pred_boxes),
        "similarity": score
    }


def normalize_text_for_word_eval(text: str) -> str:
    """Normalizes German umlauts/transliterations, LaTeX command wrappers, and underscore emphasis/fill-in blank runs for robust word recall evaluation."""
    t = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|mathsf|frac|sqrt|rightleftharpoons|xrightarrow|longrightarrow|leftarrow|rightarrow|leftrightarrow|overset|underset|quad|qquad|approx|cdot|times|pm|mp|leq|geq|neq|Delta|alpha|beta|gamma|delta|lambda|mu|nu|pi|sigma|omega|circ|left|right)\b",
        " ",
        text,
    )
    t = t.lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = re.sub(r"_+", " ", t)
    # Split adjacent letters and digits so chemical tokens like ch3cooh match ch_3cooh / \text{CH}_3\text{COOH}
    t = re.sub(r"([a-z])([0-9])", r"\1 \2", t)
    t = re.sub(r"([0-9])([a-z])", r"\1 \2", t)
    return t


def _strip_images_and_tag_markers_for_text_eval(md: str) -> str:
    """
    Strips variable image blocks (<Bild>...</Bild>, ![...](...)) and structural tag markers
    (<Rahmen>, </Rahmen>, <Tabelle>, </Tabelle>, table resolution boilerplate) while keeping
    all textbook text inside boxes and tables so word_recall and reading-flow continuity
    are never falsely penalized when a box/table tag differs between raw and FIBS profiles.
    """
    if not md:
        return ""
    s = re.sub(r"<Bild\b[^>]*>.*?</Bild>", "\n", md, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"!\[.*?\]\([^)]+\)", "\n", s)
    s = re.sub(
        r"<Anmerkung>\s*Die folgende Tabelle wurde aufgelöst\.\s*</Anmerkung>",
        "\n",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"</?(?:Rahmen|Tabelle|Anmerkung|Lückentext|table|tr|td|th|thead|tbody)\b[^>]*>",
        " ",
        s,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def evaluate_text_and_continuity(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """
    Evaluates pure text body fidelity, word recall (completeness / missing content detection),
    character similarity, and page boundary continuity with variable image descriptions isolated.
    """
    from collections import Counter
    gold_md = strip_ground_truth_preamble(gold_md)
    gold_body = _strip_images_and_tag_markers_for_text_eval(gold_md)
    pred_body = _strip_images_and_tag_markers_for_text_eval(pred_md)
    
    # 1. Character-level Sequence Matcher Similarity
    matcher = difflib.SequenceMatcher(None, pred_body, gold_body, autojunk=False)
    char_similarity = matcher.ratio()
    
    # 2. Word-level Recall & Completeness with German transliteration & fill-in blank normalization
    gold_norm = normalize_text_for_word_eval(gold_body)
    pred_norm = normalize_text_for_word_eval(pred_body)
    gold_words = re.findall(r"\b[a-z0-9]+\b", gold_norm)
    pred_words = re.findall(r"\b[a-z0-9]+\b", pred_norm)
    
    if not gold_words:
        word_recall = 1.0
        word_precision = 1.0 if not pred_words else 0.95
        word_f1 = 1.0
    else:
        gold_counts = Counter(gold_words)
        pred_counts = Counter(pred_words)
        
        overlap_count = sum(min(count, pred_counts.get(word, 0)) for word, count in gold_counts.items())
        word_recall = overlap_count / len(gold_words)
        word_precision = (overlap_count / len(pred_words)) if pred_words else 0.0
        word_f1 = (2 * word_precision * word_recall / (word_precision + word_recall)) if (word_precision + word_recall) > 0 else 0.0

    # 3. Missing Block Detection (Contiguous chunks of >= 6 words in gold dropped from pred)
    word_matcher = difflib.SequenceMatcher(None, pred_words, gold_words, autojunk=False)
    missing_chunks = []
    missing_words_count = 0
    for tag, i1, i2, j1, j2 in word_matcher.get_opcodes():
        if tag in ('delete', 'replace'):
            dropped = gold_words[j1:j2]
            if len(dropped) >= 6:
                missing_chunks.append(" ".join(dropped[:10]) + ("..." if len(dropped) > 10 else ""))
                missing_words_count += len(dropped)
                
    # 4. Page boundary marker check
    gold_pages = re.findall(r"\(\((\d+)\)\)", gold_md)
    pred_pages = re.findall(r"\(\((\d+)\)\)", pred_md)
    
    if gold_pages:
        matched_pages = sum(1 for p in gold_pages if p in pred_pages)
        page_recall = matched_pages / len(gold_pages)
    else:
        page_recall = 1.0

    # Missing text penalty: if significant text is omitted, apply proportional deduction
    missing_penalty = min(0.35, (missing_words_count / max(len(gold_words), 1)) * 0.6)
    
    raw_text_score = (char_similarity * 0.35 + word_recall * 0.35 + word_f1 * 0.15 + page_recall * 0.15)
    adjusted_score = max(0.0, raw_text_score - missing_penalty)
    score = round(adjusted_score * 100, 1)
    
    return {
        "score": score,
        "char_similarity": round(char_similarity * 100, 1),
        "word_recall": round(word_recall * 100, 1),
        "word_f1": round(word_f1 * 100, 1),
        "page_marker_recall": round(page_recall * 100, 1),
        "missing_chunks_count": len(missing_chunks),
        "missing_chunks": missing_chunks[:5],
        "gold_pages": gold_pages,
        "pred_pages": pred_pages
    }


def evaluate_a11y(
    pred_md: str,
    *,
    raw_markdown: Optional[str] = None,
    expected_pages: Optional[int] = None,
    table_max_cells: Optional[int] = None,
) -> Dict[str, Any]:
    """Runs the FIBS 09/2025 accessibility & source-aware completeness linter on predicted markdown."""
    report = lint_markdown(
        pred_md,
        raw_markdown=raw_markdown,
        expected_pages=expected_pages,
        table_max_cells=table_max_cells,
    )
    return report.model_dump()


def evaluate_page_monotonicity(pred_md: str, gold_md: str) -> Dict[str, Any]:
    """
    Evaluates whether extracted ((num)) page boundary markers form a strictly
    increasing, step-consistent monotonic sequence matching the document's pages.
    """
    gold_md = strip_ground_truth_preamble(gold_md)
    pred_pages = [int(p) for p in re.findall(r"\(\((\d+)\)\)", pred_md)]
    gold_pages = [int(p) for p in re.findall(r"\(\((\d+)\)\)", gold_md)]

    if not gold_pages:
        return {
            "score": 100.0,
            "is_monotonic": True,
            "pred_pages": pred_pages,
            "gold_pages": [],
        }
    if not pred_pages:
        return {
            "score": 0.0,
            "is_monotonic": False,
            "pred_pages": [],
            "gold_pages": gold_pages,
        }

    max_gold_step = max(
        (gold_pages[i + 1] - gold_pages[i] for i in range(len(gold_pages) - 1)),
        default=1,
    )
    allowed_max_step = max(2, max_gold_step)

    if len(pred_pages) == 1:
        is_monotonic = True
        valid_transitions_ratio = 1.0
    else:
        valid_steps = sum(
            1
            for i in range(len(pred_pages) - 1)
            if 0 < (pred_pages[i + 1] - pred_pages[i]) <= allowed_max_step
        )
        valid_transitions_ratio = valid_steps / (len(pred_pages) - 1)
        is_monotonic = valid_steps == (len(pred_pages) - 1)

    matched = sum(1 for p in gold_pages if p in pred_pages)
    recall = matched / len(gold_pages)
    score = round((recall * 0.5 + valid_transitions_ratio * 0.5) * 100, 1)
    return {
        "score": score,
        "is_monotonic": is_monotonic,
        "pred_pages": pred_pages,
        "gold_pages": gold_pages,
    }


def evaluate_docx_bookmarks(pred_md: str) -> Dict[str, Any]:
    """
    Converts predicted Markdown to a native Word DOCX via `convert_markdown_to_docx`
    and verifies that every `((num))` page boundary is enclosed in a `page_{num}`
    OpenXML bookmark (`w:bookmarkStart`) for screen readers (NVDA, JAWS).
    """
    from backend.services.docx_service import convert_markdown_to_docx

    pages = list(dict.fromkeys(re.findall(r"\(\((\d+)\)\)", pred_md)))
    expected_bookmarks = [f"page_{p}" for p in pages]
    if not expected_bookmarks:
        return {
            "score": 100.0,
            "expected_bookmarks": [],
            "found_bookmarks": [],
        }

    # Ensure inline ((num)) markers also appear as standalone lines if needed by DOCX converter
    normalized_md = re.sub(r"(?<!\n)\s*(\(\(\d+\)\))\s*(?!\n)", r"\n\n\1\n\n", pred_md)

    found_bookmarks: List[str] = []
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_docx = os.path.join(tmp_dir, "bench_verify.docx")
            convert_markdown_to_docx(normalized_md, out_docx)
            if os.path.exists(out_docx):
                with zipfile.ZipFile(out_docx, "r") as zf:
                    xml_str = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                found_bookmarks = list(
                    dict.fromkeys(
                        re.findall(r'w:bookmarkStart[^>]*w:name="(page_[^"]+)"', xml_str)
                    )
                )
    except Exception as e:
        logger.warning(f"DOCX bookmark verification failed: {e}")

    matched = sum(1 for bm in expected_bookmarks if bm in found_bookmarks)
    score = round((matched / len(expected_bookmarks)) * 100, 1)
    return {
        "score": score,
        "expected_bookmarks": expected_bookmarks,
        "found_bookmarks": found_bookmarks,
    }


def strip_catalog_title_from_golden(gold_md: str, catalog_title: Optional[str] = None) -> str:
    """
    Strips synthetic `# {catalog_title}` H1 headers prepended in external catalog
    ground-truth files immediately after the first `((num))` page marker.
    """
    if not gold_md or not catalog_title:
        return gold_md
    escaped_title = re.escape(catalog_title.strip())
    # Match after initial ((num)) marker
    cleaned = re.sub(
        rf"^(\s*\(\(\d+\)\)\s*\n+)#\s+{escaped_title}\s*\n+",
        r"\1",
        gold_md,
        count=1,
    )
    # Also match if at very start before any ((num))
    cleaned = re.sub(
        rf"^\s*#\s+{escaped_title}\s*\n+",
        "",
        cleaned,
        count=1,
    )
    return cleaned


def slice_golden_markdown_to_pages(gold_md: str, physical_pages: List[int]) -> str:
    """
    Slices a multi-page golden ground-truth Markdown document to retain only the
    sections corresponding to `physical_pages` (`((num))` markers).
    """
    if not gold_md or not physical_pages:
        return gold_md
    target_set = {int(p) for p in physical_pages}
    parts = re.split(r"(?m)^(\s*\(\(\d+\)\)\s*)$", gold_md)
    if len(parts) <= 1:
        return gold_md

    preamble = parts[0]
    kept_chunks: List[str] = []
    for idx in range(1, len(parts), 2):
        marker_line = parts[idx]
        body = parts[idx + 1] if (idx + 1) < len(parts) else ""
        m = re.search(r"\(\((\d+)\)\)", marker_line)
        if m and int(m.group(1)) in target_set:
            if not kept_chunks and preamble.strip():
                kept_chunks.append(preamble.rstrip() + "\n\n")
            kept_chunks.append(marker_line.strip() + "\n" + body.lstrip("\n"))

    if not kept_chunks:
        return gold_md
    return "\n\n".join(c.strip() for c in kept_chunks if c.strip()) + "\n"


def get_peak_memory_mb() -> float:
    """Returns peak resident set size (RSS) of the current process in MB."""
    try:
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return round(usage / (1024 * 1024), 1)
            return round(usage / 1024, 1)
    except Exception:
        pass
    return 0.0


# -------------------------------------------------------------
# 2. Execution Pipelines
# -------------------------------------------------------------

def run_docling_extraction(
    pdf_path: str,
    output_dir: str,
    task: Optional[Any] = None,
    in_process: bool = False,
) -> tuple[str, float]:
    """
    Runs Docling extractor (either in-process reusing cached DocumentConverter when
    `in_process=True` and `task is None`, or as a subprocess streaming live output)
    and returns (markdown, duration).
    """
    os.makedirs(output_dir, exist_ok=True)
    start_time = time.time()

    if in_process and task is None:
        from backend.services import docling_extractor

        logger.info(f"Running Docling (in-process cached converter): {pdf_path}")
        docling_extractor.main(["--input", pdf_path, "--output-dir", output_dir])
        duration = round(time.time() - start_time, 2)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        md_file = os.path.join(output_dir, f"{base_name}.md")
        with open(md_file, "r", encoding="utf-8") as f:
            content = f.read()
        return content, duration

    python_exe = sys.executable or "python"

    import subprocess
    cmd = [python_exe, "-m", "backend.services.docling_extractor", "--input", pdf_path, "--output-dir", output_dir]
    logger.info(f"Running Docling: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=PROJECT_ROOT,
    )

    if proc.stdout:
        for line in iter(proc.stdout.readline, ''):
            line_str = line.strip()
            if line_str:
                logger.info(f"[Docling] {line_str}")
                if task:
                    task.add_log(line_str)
        proc.stdout.close()

    return_code = proc.wait()
    duration = round(time.time() - start_time, 2)

    if return_code != 0:
        logger.error(f"Docling failed with return code {return_code}")
        raise RuntimeError(f"Docling error (code {return_code})")

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    md_file = os.path.join(output_dir, f"{base_name}.md")
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    return content, duration


def run_infinity_extraction(pdf_path: str, output_dir: str, task: Optional[Any] = None) -> tuple[str, float]:
    """Runs Infinity-Parser2-Flash extractor subprocess, streaming live output to task if provided, and returns (markdown, duration)."""
    os.makedirs(output_dir, exist_ok=True)
    python_exe = sys.executable or "python"

    start_time = time.time()
    import subprocess
    cmd = [python_exe, "-m", "backend.services.infinity_parser_extractor", "--input", pdf_path, "--output-dir", output_dir]
    logger.info(f"Running Infinity-Parser2-Flash: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=PROJECT_ROOT,
    )
    
    if proc.stdout:
        in_stream_page = False
        for line in iter(proc.stdout.readline, ''):
            line_str = line.strip()
            if line_str == "---STREAM_PAGE_START---":
                in_stream_page = True
                continue
            if line_str == "---STREAM_PAGE_END---":
                in_stream_page = False
                continue
            if in_stream_page:
                continue
            if line_str:
                logger.info(f"[Infinity] {line_str}")
                if task:
                    task.add_log(line_str)
        proc.stdout.close()
        
    return_code = proc.wait()
    duration = round(time.time() - start_time, 2)
    
    if return_code != 0:
        logger.error(f"Infinity-Parser failed with return code {return_code}")
        raise RuntimeError(f"Infinity-Parser error (code {return_code})")
        
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    md_file = os.path.join(output_dir, f"{base_name}.md")
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    return content, duration


def run_lightonocr_extraction(pdf_path: str, output_dir: str, task: Optional[Any] = None) -> tuple[str, float]:
    """Runs LightOnOCR-3 extractor subprocess, streaming live output to task if provided, and returns (markdown, duration)."""
    os.makedirs(output_dir, exist_ok=True)
    python_exe = sys.executable or "python"

    start_time = time.time()
    import subprocess
    cmd = [python_exe, "-m", "backend.services.lightonocr_extractor", "--input", pdf_path, "--output-dir", output_dir]
    logger.info(f"Running LightOnOCR-3: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=PROJECT_ROOT,
    )

    if proc.stdout:
        in_stream_page = False
        for line in iter(proc.stdout.readline, ""):
            line_str = line.strip()
            if line_str == "---STREAM_PAGE_START---":
                in_stream_page = True
                continue
            if line_str == "---STREAM_PAGE_END---":
                in_stream_page = False
                continue
            if in_stream_page:
                continue
            if line_str:
                logger.info(f"[LightOnOCR-3] {line_str}")
                if task:
                    task.add_log(line_str)
        proc.stdout.close()

    return_code = proc.wait()
    duration = round(time.time() - start_time, 2)

    if return_code != 0:
        logger.error(f"LightOnOCR-3 failed with return code {return_code}")
        raise RuntimeError(f"LightOnOCR-3 error (code {return_code})")

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    md_file = os.path.join(output_dir, f"{base_name}.md")
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    return content, duration


def _parse_judge_json_robustly(content: str) -> Optional[Dict[str, Any]]:
    """Parses LLM judge JSON output robustly, sanitizing unescaped control characters and markdown fences."""
    if not content:
        return None
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content.strip(), flags=re.IGNORECASE)
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not json_match:
        return None
    raw_json = json_match.group(0)
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError:
        # Sanitize raw control characters (\n, \r, \t, \x00-\x1f) inside JSON string values
        sanitized = re.sub(r"[\x00-\x1f]+", " ", raw_json)
        try:
            return json.loads(sanitized)
        except json.JSONDecodeError:
            return None


# -------------------------------------------------------------
# 3. LLM Qualitative Judge Evaluator (Gemma 4 12B)
# -------------------------------------------------------------

def _compute_programmatic_reference_for_judge(
    pred_md: str,
    gold_md: str,
    programmatic_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Builds or normalizes objective programmatic reference metrics for LLM-as-a-Judge grounding and calibration."""
    if programmatic_metrics:
        return programmatic_metrics
    return {
        "headings": evaluate_headings(pred_md, gold_md),
        "formulas": evaluate_formulas(pred_md, gold_md),
        "tables": evaluate_tables(pred_md, gold_md),
        "continuity": evaluate_text_and_continuity(pred_md, gold_md),
        "images": evaluate_images(pred_md, gold_md),
        "boxes": evaluate_boxes(pred_md, gold_md),
        "a11y": evaluate_a11y(pred_md),
        "page_monotonicity": evaluate_page_monotonicity(pred_md, gold_md),
    }


def build_judge_prompt(
    pred_md: str,
    gold_md: str,
    profile: str = "uebertragungsregeln_09_2025",
    programmatic_metrics: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Constructs a profile-aware, rubric-anchored prompt for the Gemma 4 12B LLM-as-a-Judge
    with multi-page sampling (head + middle + tail) and objective programmatic reference metrics.
    """
    gold_md = strip_ground_truth_preamble(gold_md)
    comp_gold = extract_document_components(gold_md)
    comp_pred = extract_document_components(pred_md)
    ref = _compute_programmatic_reference_for_judge(pred_md, gold_md, programmatic_metrics)

    def _sample_window(text: str, budget: int = 9000) -> str:
        if len(text) <= budget:
            return text
        part = budget // 3
        mid_start = max(0, (len(text) // 2) - (part // 2))
        return (
            text[:part]
            + "\n...[MITTELTEIL]...\n"
            + text[mid_start : mid_start + part]
            + "\n...[ENDTEIL]...\n"
            + text[-part:]
        )

    gold_tabs = "\n\n".join(comp_gold["tables"]) if comp_gold["tables"] else "Keine Tabellen vorhanden."
    pred_tabs = "\n\n".join(comp_pred["tables"]) if comp_pred["tables"] else "Keine Tabellen vorhanden."
    gold_imgs = "\n\n".join(comp_gold["images"]) if comp_gold["images"] else "Keine Abbildungen vorhanden."
    pred_imgs = "\n\n".join(comp_pred["images"]) if comp_pred["images"] else "Keine Abbildungen vorhanden."
    gold_boxes = "\n\n".join(comp_gold["boxes"]) if comp_gold["boxes"] else "Keine Rahmen vorhanden."
    pred_boxes = "\n\n".join(comp_pred["boxes"]) if comp_pred["boxes"] else "Keine Rahmen vorhanden."

    c_info = ref.get("continuity", {})
    h_info = ref.get("headings", {})
    f_info = ref.get("formulas", {})
    t_info = ref.get("tables", {})
    i_info = ref.get("images", {})
    b_info = ref.get("boxes", {})
    m_info = ref.get("page_monotonicity", {})
    a_info = ref.get("a11y", {})

    ref_summary = (
        f"- Word Recall (Vollständigkeit): {c_info.get('word_recall', c_info.get('score', 0.0))}%\n"
        f"- Text & Lesefluss Score: {c_info.get('score', 0.0)}%\n"
        f"- Überschriften F1 Score: {h_info.get('score', 0.0)}% (Gold={h_info.get('gold_count', 0)}, Pred={h_info.get('pred_count', 0)})\n"
        f"- Formeln Score: {f_info.get('score', 0.0)}% (Gold={f_info.get('gold_count', 0)}, Pred={f_info.get('pred_count', 0)})\n"
        f"- Tabellen Score: {t_info.get('score', 0.0)}% (Gold={t_info.get('gold_count', 0)}, Pred={t_info.get('pred_count', 0)})\n"
        f"- Abbildungen Score: {i_info.get('score', 0.0)}% (Gold={i_info.get('gold_count', 0)}, Pred={i_info.get('pred_count', 0)})\n"
        f"- Rahmen Score: {b_info.get('score', 0.0)}% (Gold={b_info.get('gold_count', 0)}, Pred={b_info.get('pred_count', 0)})\n"
        f"- Seitenmonotonie ((num)): {m_info.get('score', 0.0)}% (Gold={m_info.get('gold_pages', [])}, Pred={m_info.get('extracted_pages', [])})\n"
        f"- A11y Linter Score: {a_info.get('score', 0.0)}%"
    )

    if profile == "raw":
        profile_instructions = (
            "MODUS: Stage 1 ROH-EXTRAKTION (Raw Markdown OCR/Layout Extraction vor FIBS-Standardisierung).\n"
            "WICHTIG FÜR RAW-MODUS: In Stage 1 sind Standard-Markdown-Tabellen (Pipe-Syntax `| ... |`) und Markdown-Bildlinks "
            "(`![Alt](images/...)`) der erwartete Zielstandard! Kein Abzug für fehlende <Bild>-Blöcke oder fehlende <Tabelle>-Tags."
        )
    else:
        profile_instructions = (
            "MODUS: Stage 2 Übertragungsregeln Stand 09/2025 (FIBS-Standard).\n"
            "Prüfe die Einhaltung der Übertragungsregeln: `<Bild> {Bildart}:` mit `Beschreibung:` / `Beschreibung mit Bildtext:` "
            "(oder `#### Abb. X.Y:` davor), `<Tabelle>` bzw. aufgelöste Kleintabellen mit `<Anmerkung>Die folgende Tabelle wurde aufgelöst.</Anmerkung>`, "
            "`<Rahmen>` für echte semantische Infokästen/Merksätze, `\\t` nach Aufzählungszeichen, LaTeX `$...$`/`$$...$$` "
            "(Äquivalenz von `$CH_3COOH$` und `$\\text{CH}_3\\text{COOH}$` gilt als 100% korrekt!) und exakte `((num))` Seitenmarker."
        )

    return f"""Du bist ein präziser, objektiv kalibrierter Experten-Gutachter für barrierefreie Schulbuchkonvertierung.
{profile_instructions}

[OBJEKTIVE PROGRAMMATISCHE REFERENZ-METRIKEN (Messung über das Gesamtdokument)]:
{ref_summary}

[BEWERTUNGSANKER (0-100 Skala - orientiere deine Teilscores eng an den objektiven Messwerten)]:
- 95-100: Nahezu deckungsgleich zum Golden Ground Truth (Word Recall >= 96%, Struktur & Tags vollständig).
- 85-94: Hohe Qualität; nur geringfügige Abweichungen in Formatierung oder einzelnen Wörtern.
- 70-84: Solide Basis, aber erkennbare strukturelle Defizite (einzelne fehlende Überschriften/Boxen oder Formatfehler).
- 40-69: Deutliche Mängel (fehlende Absätze, beschädigte Tabellen oder falsche Tag-Struktur).
- 0-39: Schwere Ausfälle oder unvollständiger Text.
Hinweis: Wenn eine Kategorie im Golden Ground Truth nicht vorkommt (Gold=0 und Pred=0), vergib 100 Punkte.

[GOLDEN GROUND TRUTH - FLIESSTEXT & STRUKTUR]:
{_sample_window(comp_gold["clean_body"], 8400)}

[EXTRACTION PREDICTION - FLIESSTEXT & STRUKTUR]:
{_sample_window(comp_pred["clean_body"], 8400)}

[GOLDEN GROUND TRUTH - TABELLEN]:
{gold_tabs[:2500]}

[EXTRACTION PREDICTION - TABELLEN]:
{pred_tabs[:2500]}

[GOLDEN GROUND TRUTH - ABBILDUNGEN]:
{gold_imgs[:2000]}

[EXTRACTION PREDICTION - ABBILDUNGEN]:
{pred_imgs[:2000]}

[GOLDEN GROUND TRUTH - INFOKÄSTEN (<Rahmen>)]:
{gold_boxes[:1800]}

[EXTRACTION PREDICTION - INFOKÄSTEN (<Rahmen>)]:
{pred_boxes[:1800]}

Antworte ausschließlich in einer einzigen einzeiligen JSON-Struktur ohne Zeilenumbrüche im String:
{{"completeness_score": 95, "headings_score": 95, "formulas_score": 95, "tables_score": 95, "continuity_score": 95, "images_score": 95, "overall_judge_score": 95, "judge_feedback": "Präzise fachliche Begründung"}}
"""


def calibrate_judge_scores_with_programmatic_reference(
    raw_judge: Dict[str, Any],
    programmatic_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Calibrates raw LLM judge scores against objective programmatic reference metrics so the LLM judge
    cannot hallucinate extreme penalties (e.g. scoring 20% when objective recall/F1 is 100%) or
    unbounded score inflation when content is missing.
    """
    c_metric = programmatic_metrics.get("continuity", {})
    c_ref = float(c_metric.get("score", 85.0))
    w_rec = float(c_metric.get("word_recall", c_ref))
    h_ref = float(programmatic_metrics.get("headings", {}).get("score", 85.0))
    f_ref = float(programmatic_metrics.get("formulas", {}).get("score", 85.0))
    t_ref = float(programmatic_metrics.get("tables", {}).get("score", 85.0))
    i_ref = float(programmatic_metrics.get("images", {}).get("score", 85.0))
    b_ref = float(programmatic_metrics.get("boxes", {}).get("score", 85.0))
    m_ref = float(programmatic_metrics.get("page_monotonicity", {}).get("score", 100.0))

    def _anchor(llm_val: Any, ref_val: float, max_drift: float = 12.0) -> float:
        try:
            v = float(llm_val)
        except (TypeError, ValueError):
            v = ref_val
        v = max(0.0, min(100.0, v))
        # Clamp maximum drift from objective programmatic measurement and blend 55% objective / 45% LLM
        clamped = max(ref_val - max_drift, min(ref_val + max_drift, v))
        return round(0.55 * ref_val + 0.45 * clamped, 1)

    completeness_s = _anchor(raw_judge.get("completeness_score"), w_rec)
    headings_s = _anchor(raw_judge.get("headings_score"), h_ref)
    formulas_s = _anchor(raw_judge.get("formulas_score"), f_ref)
    tables_s = _anchor(raw_judge.get("tables_score"), t_ref)
    continuity_ref = round(0.75 * c_ref + 0.25 * m_ref, 1)
    continuity_s = _anchor(raw_judge.get("continuity_score"), continuity_ref)
    images_s = _anchor(raw_judge.get("images_score"), i_ref)

    weighted_ref = (
        0.25 * completeness_s
        + 0.18 * continuity_s
        + 0.16 * headings_s
        + 0.14 * tables_s
        + 0.14 * formulas_s
        + 0.13 * images_s
    )
    # Incorporate box fidelity gently if boxes are present
    if programmatic_metrics.get("boxes", {}).get("gold_count", 0) > 0 or programmatic_metrics.get("boxes", {}).get("pred_count", 0) > 0:
        weighted_ref = 0.90 * weighted_ref + 0.10 * b_ref

    overall_s = _anchor(raw_judge.get("overall_judge_score"), weighted_ref, max_drift=10.0)

    calibrated = dict(raw_judge)
    calibrated.update({
        "completeness_score": completeness_s,
        "headings_score": headings_s,
        "formulas_score": formulas_s,
        "tables_score": tables_s,
        "continuity_score": continuity_s,
        "images_score": images_s,
        "overall_judge_score": overall_s,
    })
    if "comment" in calibrated and "judge_feedback" not in calibrated:
        calibrated["judge_feedback"] = calibrated["comment"]
    elif "judge_feedback" in calibrated and "comment" not in calibrated:
        calibrated["comment"] = calibrated["judge_feedback"]
    return calibrated


def evaluate_with_gemma_judge(
    pred_md: str,
    gold_md: str,
    profile: str = "uebertragungsregeln_09_2025",
    programmatic_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates output against golden truth using local Gemma 4 (via rapid-mlx if available),
    with full document multi-page context, profile-aware rubrics (`raw` vs `uebertragungsregeln_09_2025`),
    and objective programmatic reference calibration.
    """
    ref_metrics = _compute_programmatic_reference_for_judge(pred_md, gold_md, programmatic_metrics)
    prompt = build_judge_prompt(
        pred_md,
        gold_md,
        profile=profile,
        programmatic_metrics=ref_metrics,
    )

    if os.environ.get("E2E_MOCK") == "true":
        h_s = ref_metrics["headings"]["score"]
        f_s = ref_metrics["formulas"]["score"]
        t_s = ref_metrics["tables"]["score"]
        c_s = ref_metrics["continuity"]["score"]
        i_s = ref_metrics["images"]["score"]
        return {
            "completeness_score": c_s,
            "headings_score": h_s,
            "formulas_score": f_s,
            "tables_score": t_s,
            "continuity_score": c_s,
            "images_score": i_s,
            "overall_judge_score": round((h_s + f_s + t_s + c_s + i_s) / 5.0, 1),
            "judge_feedback": "Evaluated via composite programmatic metric judge (E2E Mock)",
            "comment": "Evaluated via composite programmatic metric judge (E2E Mock)"
        }

    try:
        from backend.services.llm_service import start_rapid_mlx, get_model_path, reset_idle_timer, _run_torch_cuda_llm
        client = start_rapid_mlx()
        content = ""
        if client:
            model_path = get_model_path()
            response = client.chat.completions.create(
                model=model_path,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )
            content = response.choices[0].message.content or ""
            reset_idle_timer()
        else:
            content = _run_torch_cuda_llm("Du bist ein präziser JSON-Gutachter für E-Buch Dokumentenkonvertierung.", prompt, max_tokens=1024) or ""
        if content:
            res_data = _parse_judge_json_robustly(content)
            if res_data is not None:
                return calibrate_judge_scores_with_programmatic_reference(res_data, ref_metrics)
    except Exception as e:
        logger.warning(f"Gemma LLM Judge call skipped / timed out: {e}")
        
    # Fallback heuristic judge score
    h_s = ref_metrics["headings"]["score"]
    f_s = ref_metrics["formulas"]["score"]
    t_s = ref_metrics["tables"]["score"]
    c_s = ref_metrics["continuity"]["score"]
    i_s = ref_metrics["images"]["score"]
    return {
        "completeness_score": c_s,
        "headings_score": h_s,
        "formulas_score": f_s,
        "tables_score": t_s,
        "continuity_score": c_s,
        "images_score": i_s,
        "overall_judge_score": round((h_s + f_s + t_s + c_s + i_s) / 5.0, 1),
        "judge_feedback": "Evaluated via composite programmatic metric judge",
        "comment": "Evaluated via composite programmatic metric judge"
    }


# -------------------------------------------------------------
# 4. Main Benchmark Orchestrator & Leaderboard Updater
# -------------------------------------------------------------

DEFAULT_EXTERNAL_DATA_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "ebuch-testdaten"))


def resolve_external_data_dir(external_data_dir: Optional[str] = None) -> Optional[str]:
    """Resolves the companion private publisher repository (`../ebuch-testdaten`) if available and readable on disk."""
    cand = external_data_dir or os.environ.get("EBUCH_TESTDATEN_DIR") or DEFAULT_EXTERNAL_DATA_DIR
    if cand and os.path.isdir(cand):
        cat_file = os.path.join(cand, "catalog.json")
        try:
            if os.path.exists(cat_file) and os.access(cat_file, os.R_OK):
                with open(cat_file, "r", encoding="utf-8") as f:
                    f.read(16)
                return os.path.abspath(cand)
        except Exception:
            return None
    return None


def load_external_catalog(external_data_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    Loads `catalog.json` from `../ebuch-testdaten` and returns a mapping keyed by
    both `<id>.pdf` and `<id>` -> catalog entry dict.
    """
    ext_root = resolve_external_data_dir(external_data_dir)
    if not ext_root:
        return {}
    cat_path = os.path.join(ext_root, "catalog.json")
    if not os.path.exists(cat_path):
        return {}
    try:
        with open(cat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mapping: Dict[str, Dict[str, Any]] = {}
        for doc in data.get("documents", []):
            doc_id = doc.get("id", "")
            pdf_fn = os.path.basename(doc.get("pdf_filename", f"{doc_id}.pdf"))
            if doc_id:
                mapping[doc_id] = doc
                mapping[f"{doc_id}.pdf"] = doc
            if pdf_fn:
                mapping[pdf_fn] = doc
        return mapping
    except Exception as e:
        logger.warning(f"Could not load external catalog.json from {cat_path}: {e}")
        return {}


def prepare_cropped_pdf_for_indices(
    pdf_path: str, page_indices: List[int], output_pdf_path: str
) -> Tuple[str, List[int]]:
    """
    Extracts 0-based `page_indices` from `pdf_path` into `output_pdf_path` using `pypdfium2`
    so long publisher samples can be benchmarked on their designated `benchmark_page_indices`.
    Returns `(cropped_pdf_path, valid_0_based_indices)`.
    """
    if not page_indices or not os.path.exists(pdf_path):
        return pdf_path, []
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_path)
        total = len(doc)
        valid = [int(i) for i in page_indices if 0 <= int(i) < total]
        if not valid or len(valid) == total:
            doc.close()
            return pdf_path, list(range(total))
        new_doc = pdfium.PdfDocument.new()
        new_doc.import_pages(doc, valid)
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
        new_doc.save(output_pdf_path)
        new_doc.close()
        doc.close()
        return output_pdf_path, valid
    except Exception as e:
        logger.warning(f"Could not crop PDF {pdf_path} to indices {page_indices}: {e}")
        return pdf_path, []


def run_vlm_descriptions_for_benchmark(
    markdown_text: str,
    image_dir: str,
    cache_json_path: Optional[str] = None,
) -> str:
    """
    Runs the production VLM image description stage (`vlm_describer.py` + `fibs_formatting`)
    on extracted `![](images/...)` links, converting them into multi-line FIBS `<Bild>` tags
    and dropping purely decorative images without caption context.
    """
    if not markdown_text or not image_dir or not os.path.isdir(image_dir):
        return markdown_text

    pattern = r"(?s)!\[(.*?)\]\((?:images/)?([^)]+)\)"
    wrapped_pattern = r"(?s)<Bild>\s*!\[(.*?)\]\((?:images/)?([^)]+)\)\s*</Bild>"
    wrapped_matches = list(re.finditer(wrapped_pattern, markdown_text))
    plain_matches = list(re.finditer(pattern, markdown_text))
    wrapped_spans = [m.span() for m in wrapped_matches]
    unique_matches = list(wrapped_matches)
    for pm in plain_matches:
        p_start, p_end = pm.span()
        if not any(w_start <= p_start and p_end <= w_end for w_start, w_end in wrapped_spans):
            unique_matches.append(pm)

    if not unique_matches:
        return markdown_text

    image_paths_list: List[str] = []
    matched_file_map: Dict[str, str] = {}
    for match in unique_matches:
        img_filename = os.path.basename(match.group(2))
        candidate_path = os.path.join(image_dir, img_filename)
        matched_file_map[match.group(0)] = candidate_path
        if os.path.exists(candidate_path) and candidate_path not in image_paths_list:
            image_paths_list.append(candidate_path)

    json_data: Dict[str, str] = {}
    if os.environ.get("E2E_MOCK") == "true":
        json_data = {
            p: "BILDART: Abbildung\nTEXT_IM_BILD: –\nDEKORATIV: nein\nBESCHREIBUNG:\nLehrbuchabbildung zum Abschnitt."
            for p in image_paths_list
        }
    elif image_paths_list:
        release_gpu_memory()
        try:
            import subprocess
            from backend.services.fibs_formatting import image_contexts_for_markdown

            vlm_contexts = image_contexts_for_markdown(markdown_text, matched_file_map)
            parent_dir = os.path.dirname(image_dir)
            contexts_path = os.path.join(parent_dir, "vlm_contexts.json")
            out_json_path = os.path.join(parent_dir, "vlm_descriptions.json")
            cache_path = cache_json_path or os.path.join(parent_dir, "vlm_cache.json")
            with open(contexts_path, "w", encoding="utf-8") as cf:
                json.dump(vlm_contexts, cf, ensure_ascii=False, indent=2)

            python_exe = sys.executable or "python"
            cmd = [
                python_exe,
                "-m",
                "backend.services.vlm_describer",
                "--images",
                ",".join(image_paths_list),
                "--output-json",
                out_json_path,
                "--cache-json",
                cache_path,
                "--contexts-json",
                contexts_path,
            ]
            logger.info(f"Running VLM image describer for {len(image_paths_list)} image(s)...")
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False, cwd=PROJECT_ROOT)
            if os.path.exists(out_json_path):
                from backend.services.vlm_describer import load_vlm_results

                vlm_results = load_vlm_results(out_json_path)
        except Exception as e:
            logger.warning(f"VLM image description subprocess failed in benchmark: {e}")
        finally:
            release_gpu_memory()

    from backend.services.fibs_formatting import bild_tag_from_vlm, format_bild_tag, has_caption_context
    from backend.services.vlm_describer import parse_vlm_description

    updated = markdown_text
    for match in unique_matches:
        alt_text = match.group(1)
        resolved_img_path = matched_file_map.get(match.group(0), "")
        vlm_res = vlm_results.get(resolved_img_path) if "vlm_results" in locals() else None
        if vlm_res is None and resolved_img_path in json_data:
            raw_val = json_data[resolved_img_path]
            vlm_res = parse_vlm_description(raw_val) if isinstance(raw_val, str) and raw_val else None
        if vlm_res:
            has_caption = has_caption_context(markdown_text, match.start(), match.end(), alt_text)
            tag = bild_tag_from_vlm(vlm_res, has_caption=has_caption, alt_text=alt_text)
        else:
            tag = format_bild_tag("", alt_text, has_text=False)
        updated = updated.replace(match.group(0), tag)

    updated = re.sub(r"\n{3,}", "\n\n", updated)
    return updated


def inject_benchmark_page_numbers(
    pred_md: str,
    pdf_path: str,
    output_dir: str,
    physical_pages_override: Optional[List[int]] = None,
    directory_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Injects page boundary markers ((num)) based on metadata, catalog physical pages, or physical page offset."""
    pages_str = ",".join(str(p) for p in physical_pages_override) if physical_pages_override else ""
    if re.search(r"\(\(\d+\)\)", pred_md) and not physical_pages_override:
        return pred_md

    try:
        from backend.services.extraction_service import insert_page_numbers_from_metadata, detect_physical_start_page
        import glob
        json_files = glob.glob(os.path.join(output_dir, "**", "*content_list*.json"), recursive=True)
        if json_files and os.path.exists(json_files[0]):
            return insert_page_numbers_from_metadata(
                pred_md,
                json_files[0],
                pages_str=pages_str,
                pdf_path=pdf_path,
                directory_info=directory_info,
            )

        phys_start = (
            physical_pages_override[0]
            if physical_pages_override
            else detect_physical_start_page(pdf_path, directory_info=directory_info)
        )
        if f"(({phys_start}))" not in pred_md:
            return f"(({phys_start}))\n\n" + pred_md
    except Exception as e:
        logger.warning(f"Could not inject benchmark page numbers: {e}")
    return pred_md


def _empty_engine_result_bucket(engine: str) -> Dict[str, Any]:
    return {
        "engine": engine,
        "total_duration": 0.0,
        "total_pages": 0,
        "raw_heading_scores": [],
        "raw_formula_scores": [],
        "raw_table_scores": [],
        "raw_continuity_scores": [],
        "raw_image_scores": [],
        "raw_box_scores": [],
        "raw_a11y_scores": [],
        "raw_judge_scores": [],
        "ueb_heading_scores": [],
        "ueb_formula_scores": [],
        "ueb_table_scores": [],
        "ueb_continuity_scores": [],
        "ueb_image_scores": [],
        "ueb_box_scores": [],
        "ueb_a11y_scores": [],
        "ueb_judge_scores": [],
        "details_by_doc": {},
    }


def _recompute_engine_score_lists(eng_data: Dict[str, Any]) -> None:
    """Rebuilds aggregate score lists and totals from `details_by_doc` (used when resuming checkpoints)."""
    eng_data["total_duration"] = 0.0
    eng_data["total_pages"] = 0
    for key in (
        "raw_heading_scores", "raw_formula_scores", "raw_table_scores", "raw_continuity_scores",
        "raw_image_scores", "raw_box_scores", "raw_a11y_scores", "raw_judge_scores",
        "ueb_heading_scores", "ueb_formula_scores", "ueb_table_scores", "ueb_continuity_scores",
        "ueb_image_scores", "ueb_box_scores", "ueb_a11y_scores", "ueb_judge_scores",
    ):
        eng_data[key] = []

    for _doc, drec in eng_data.get("details_by_doc", {}).items():
        eng_data["total_duration"] += float(drec.get("duration_seconds", 0.0))
        eng_data["total_pages"] += int(drec.get("pages", 0))
        rm = drec.get("raw_metrics", {})
        um = drec.get("uebertragung_metrics", {})
        if rm:
            eng_data["raw_heading_scores"].append(rm.get("headings", {}).get("score", 0.0))
            eng_data["raw_formula_scores"].append(rm.get("formulas", {}).get("score", 0.0))
            eng_data["raw_table_scores"].append(rm.get("tables", {}).get("score", 0.0))
            eng_data["raw_continuity_scores"].append(rm.get("continuity", {}).get("score", 0.0))
            eng_data["raw_image_scores"].append(rm.get("images", {}).get("score", 0.0))
            eng_data["raw_box_scores"].append(rm.get("boxes", {}).get("score", 100.0))
            eng_data["raw_a11y_scores"].append(rm.get("a11y", {}).get("score", 0.0))
            eng_data["raw_judge_scores"].append(rm.get("judge", {}).get("overall_judge_score", 0.0))
        if um:
            eng_data["ueb_heading_scores"].append(um.get("headings", {}).get("score", 0.0))
            eng_data["ueb_formula_scores"].append(um.get("formulas", {}).get("score", 0.0))
            eng_data["ueb_table_scores"].append(um.get("tables", {}).get("score", 0.0))
            eng_data["ueb_continuity_scores"].append(um.get("continuity", {}).get("score", 0.0))
            eng_data["ueb_image_scores"].append(um.get("images", {}).get("score", 0.0))
            eng_data["ueb_box_scores"].append(um.get("boxes", {}).get("score", 100.0))
            eng_data["ueb_a11y_scores"].append(um.get("a11y", {}).get("score", 0.0))
            eng_data["ueb_judge_scores"].append(um.get("judge", {}).get("overall_judge_score", 0.0))


def load_checkpoint_state(checkpoint_path: str) -> Optional[Dict[str, Any]]:
    """Loads an existing benchmark checkpoint or `run_{id}.json` record from disk."""
    if not checkpoint_path or not os.path.exists(checkpoint_path):
        return None
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load checkpoint from {checkpoint_path}: {e}")
        return None


def slice_datasets_for_batch(
    datasets: List[str],
    batch_size: Optional[int] = None,
    batch_index: int = 0,
) -> List[str]:
    """
    Returns the slice of `datasets` for the requested batch (`batch_index` is 0-based).
    If `batch_size` is None or <= 0, returns all datasets.
    """
    if not batch_size or batch_size <= 0:
        return list(datasets)
    start = max(0, batch_index) * batch_size
    end = start + batch_size
    return list(datasets[start:end])


def run_comprehensive_benchmark(
    engines: List[str],
    datasets: List[str],
    keep_temp: bool = False,
    reuse_extractions: bool = False,
    external_data_dir: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    resume: bool = False,
    batch_size: Optional[int] = None,
    batch_index: int = 0,
    max_docs: Optional[int] = None,
    skip_standardisation: bool = False,
    describe_images: bool = False,
    allow_fallback: bool = True,
    use_catalog_page_slice: bool = True,
) -> Dict[str, Any]:
    from backend.services.task_manager import acquire_sleep_assertion_sync, release_sleep_assertion_sync

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    start_bench_time = time.time()

    ext_root = resolve_external_data_dir(external_data_dir)
    catalog_map = load_external_catalog(ext_root)
    has_external_docs = any(
        not os.path.exists(os.path.join(PROJECT_ROOT, "testdata", d))
        and ext_root is not None
        and os.path.exists(os.path.join(ext_root, "testdata", d))
        for d in datasets
    )

    # Apply batching and optional max_docs limit
    active_datasets = slice_datasets_for_batch(datasets, batch_size=batch_size, batch_index=batch_index)
    if max_docs is not None and max_docs > 0:
        active_datasets = active_datasets[:max_docs]

    # Load checkpoint if resuming or appending to an existing checkpoint file
    results: Dict[str, Dict[str, Any]] = {}
    target_runs_dir = os.path.join(ext_root, "benchmarks", "runs") if (has_external_docs and ext_root) else RUNS_DIR
    os.makedirs(target_runs_dir, exist_ok=True)

    loaded_ckpt = None
    if checkpoint_file and os.path.exists(checkpoint_file):
        loaded_ckpt = load_checkpoint_state(checkpoint_file)
    elif resume and not checkpoint_file:
        import glob
        cand_runs = sorted(glob.glob(os.path.join(target_runs_dir, "run_*.json")))
        if cand_runs:
            checkpoint_file = cand_runs[-1]
            loaded_ckpt = load_checkpoint_state(checkpoint_file)

    if loaded_ckpt and isinstance(loaded_ckpt.get("details"), dict):
        run_id = loaded_ckpt.get("run_id", run_id)
        timestamp = loaded_ckpt.get("timestamp", timestamp)
        for eng, edata in loaded_ckpt["details"].items():
            bucket = _empty_engine_result_dbd(eng, edata)
            results[eng] = bucket
        logger.info(f"Resumed benchmark state from checkpoint (run_id={run_id})")

    sleep_owner = f"benchmark_{run_id}"
    acquire_sleep_assertion_sync(sleep_owner)
    try:
        logger.info(f"=== STARTING BENCHMARK RUN {run_id} ===")
        logger.info(
            f"Engines: {engines} | Datasets ({len(active_datasets)}/{len(datasets)}): {active_datasets} | "
            f"Reuse Extractions: {reuse_extractions} | Skip Standardisation: {skip_standardisation} | "
            f"Describe Images (VLM): {describe_images}"
        )

        for engine in engines:
            if engine not in results:
                results[engine] = _empty_engine_result_bucket(engine)

            for doc_name in active_datasets:
                # Skip already completed (engine, doc_name) pairs when resuming
                if (resume or checkpoint_file) and doc_name in results[engine].get("details_by_doc", {}):
                    logger.info(f"[Checkpoint] Skipping already completed [{engine}] on [{doc_name}]")
                    continue

                pdf_path = os.path.join(PROJECT_ROOT, "testdata", doc_name)
                active_golden_dir = GOLDEN_DIR
                active_runs_dir = RUNS_DIR
                active_test_data_dir = os.path.join(PROJECT_ROOT, "testdata")
                is_external_doc = False
                if not os.path.exists(pdf_path) and ext_root:
                    ext_pdf = os.path.join(ext_root, "testdata", doc_name)
                    if os.path.exists(ext_pdf):
                        pdf_path = ext_pdf
                        active_golden_dir = os.path.join(ext_root, "testdata", "golden")
                        active_runs_dir = os.path.join(ext_root, "benchmarks", "runs")
                        active_test_data_dir = os.path.join(ext_root, "testdata")
                        os.makedirs(active_runs_dir, exist_ok=True)
                        has_external_docs = True
                        is_external_doc = True

                base_name = os.path.splitext(doc_name)[0]
                clean_base = base_name
                for suffix in ["_scanned", "_image", "_raster"]:
                    if base_name.endswith(suffix):
                        clean_base = base_name.removesuffix(suffix)
                        break

                raw_golden_path = os.path.join(active_golden_dir, f"{clean_base}.raw.golden.md")
                raw_alt_path = os.path.join(active_golden_dir, f"{clean_base}_raw.md")
                ueb_golden_path = os.path.join(active_golden_dir, f"{clean_base}.uebertragungsregeln_09_2025.golden.md")
                ueb_alt_path = os.path.join(active_golden_dir, f"{clean_base}_uebertragungsregeln_09_2025.md")
                fallback_golden_path = os.path.join(active_golden_dir, f"{clean_base}.golden.md")

                if not os.path.exists(pdf_path):
                    logger.warning(f"PDF not found: {pdf_path}. Skipping.")
                    continue

                # Load Raw Golden Truth
                if os.path.exists(raw_golden_path):
                    with open(raw_golden_path, "r", encoding="utf-8") as f:
                        raw_gold_md = f.read()
                elif os.path.exists(raw_alt_path):
                    with open(raw_alt_path, "r", encoding="utf-8") as f:
                        raw_gold_md = f.read()
                elif os.path.exists(fallback_golden_path):
                    with open(fallback_golden_path, "r", encoding="utf-8") as f:
                        raw_gold_md = f.read()
                else:
                    logger.warning(f"Golden truth not found for {clean_base}. Skipping.")
                    continue

                # Load Übertragungsregeln 09/2025 Golden Truth
                if os.path.exists(ueb_golden_path):
                    with open(ueb_golden_path, "r", encoding="utf-8") as f:
                        ueb_gold_md = f.read()
                elif os.path.exists(ueb_alt_path):
                    with open(ueb_alt_path, "r", encoding="utf-8") as f:
                        ueb_gold_md = f.read()
                elif os.path.exists(fallback_golden_path):
                    with open(fallback_golden_path, "r", encoding="utf-8") as f:
                        ueb_gold_md = f.read()
                else:
                    ueb_gold_md = raw_gold_md

                out_dir = os.path.join(active_runs_dir, f"run_{run_id}_{engine}_{os.path.splitext(doc_name)[0]}")

                # Check external catalog metadata for title stripping and 4-page benchmark slicing
                cat_entry = catalog_map.get(clean_base) or catalog_map.get(f"{clean_base}.pdf")
                physical_pages_override: Optional[List[int]] = None
                effective_pdf_path = pdf_path
                if cat_entry:
                    cat_title = cat_entry.get("title")
                    raw_gold_md = strip_catalog_title_from_golden(raw_gold_md, cat_title)
                    ueb_gold_md = strip_catalog_title_from_golden(ueb_gold_md, cat_title)
                    bench_indices = cat_entry.get("benchmark_page_indices")
                    all_phys_pages = cat_entry.get("physical_pages") or []
                    if use_catalog_page_slice and bench_indices and isinstance(bench_indices, list):
                        cropped_pdf = os.path.join(out_dir, f"_cropped_{doc_name}")
                        effective_pdf_path, valid_idx = prepare_cropped_pdf_for_indices(
                            pdf_path, bench_indices, cropped_pdf
                        )
                        if valid_idx and all_phys_pages:
                            physical_pages_override = [
                                int(all_phys_pages[i]) for i in valid_idx if i < len(all_phys_pages)
                            ]
                            if physical_pages_override:
                                raw_gold_md = slice_golden_markdown_to_pages(raw_gold_md, physical_pages_override)
                                ueb_gold_md = slice_golden_markdown_to_pages(ueb_gold_md, physical_pages_override)
                    elif all_phys_pages:
                        physical_pages_override = [int(p) for p in all_phys_pages]

                # Determine page count
                try:
                    import pypdfium2
                    pdf = pypdfium2.PdfDocument(effective_pdf_path)
                    page_count = len(pdf)
                    pdf.close()
                except Exception:
                    page_count = len(physical_pages_override) if physical_pages_override else 4

                logger.info(f"--> Benchmarking [{engine}] on [{doc_name}] ({page_count} pages)...")

                # Execute extraction or reuse existing extraction
                pred_md = None
                duration = 0.0
                if reuse_extractions:
                    import glob
                    import shutil
                    doc_stem = os.path.splitext(doc_name)[0]
                    search_json_dirs = list(dict.fromkeys([active_runs_dir, RUNS_DIR]))
                    candidate_jsons: List[str] = []
                    for sdir in search_json_dirs:
                        candidate_jsons.extend(glob.glob(os.path.join(sdir, "checkpoint_*.json")))
                        candidate_jsons.extend(glob.glob(os.path.join(sdir, "run_2*.json")))
                    candidate_jsons = sorted(
                        set(candidate_jsons),
                        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0,
                        reverse=True,
                    )
                    if checkpoint_file and os.path.exists(checkpoint_file):
                        candidate_jsons.insert(0, checkpoint_file)
                    for rj_path in candidate_jsons:
                        if os.path.basename(rj_path) == f"run_{run_id}.json":
                            continue
                        try:
                            with open(rj_path, "r", encoding="utf-8") as rjf:
                                rj_data = json.load(rjf)
                            doc_rec = rj_data.get("details", {}).get(engine, {}).get("details_by_doc", {}).get(doc_name)
                            if doc_rec and doc_rec.get("raw_md") and "formula-not-decoded" not in doc_rec["raw_md"]:
                                logger.info(f"Reusing cached {engine} extraction for {doc_name} from {os.path.basename(rj_path)}")
                                pred_md = apply_extraction_postprocess(
                                    doc_rec["raw_md"],
                                    pdf_path=effective_pdf_path,
                                )
                                duration = float(doc_rec.get("duration_seconds", 1.0))
                                os.makedirs(out_dir, exist_ok=True)
                                break
                        except Exception:
                            pass

                    if pred_md is None:
                        matched_files: List[str] = []
                        for sdir in search_json_dirs:
                            matched_files.extend(
                                glob.glob(os.path.join(sdir, f"run_*_{engine}_{doc_stem}", f"{doc_stem}.md"))
                            )
                            matched_files.extend(
                                glob.glob(os.path.join(sdir, f"run_*_{engine}_{doc_stem}", f"_cropped_{doc_stem}.md"))
                            )
                        matched_files = sorted(set(matched_files))
                        if matched_files:
                            latest_file = matched_files[-1]
                            src_dir = os.path.dirname(latest_file)
                            logger.info(f"Reusing existing raw extraction from {latest_file}")
                            with open(latest_file, "r", encoding="utf-8") as rf:
                                raw_content = rf.read()
                            from backend.services.extraction_postprocess import clean_markdown_fences
                            pred_md = clean_markdown_fences(raw_content)
                            for cand_md in reversed(matched_files):
                                dur_file = os.path.join(os.path.dirname(cand_md), ".duration.txt")
                                if os.path.exists(dur_file):
                                    try:
                                        with open(dur_file, "r", encoding="utf-8") as df:
                                            val = float(df.read().strip())
                                        if val > 0:
                                            duration = val
                                            break
                                    except Exception:
                                        pass
                            os.makedirs(out_dir, exist_ok=True)
                            if duration > 0:
                                with open(os.path.join(out_dir, ".duration.txt"), "w", encoding="utf-8") as df:
                                    df.write(str(duration))
                            eff_stem = os.path.splitext(os.path.basename(effective_pdf_path))[0]
                            for stem_cand in (doc_stem, eff_stem):
                                src_cl = os.path.join(src_dir, f"{stem_cand}_content_list.json")
                                dst_cl = os.path.join(out_dir, f"{eff_stem}_content_list.json")
                                if os.path.exists(src_cl) and src_cl != dst_cl:
                                    shutil.copy2(src_cl, dst_cl)
                                    break
                            src_imgs = os.path.join(src_dir, "images")
                            dst_imgs = os.path.join(out_dir, "images")
                            if os.path.isdir(src_imgs) and src_imgs != dst_imgs:
                                shutil.copytree(src_imgs, dst_imgs, dirs_exist_ok=True)
                            dst_cl = os.path.join(out_dir, f"{eff_stem}_content_list.json")
                            pred_md = apply_extraction_postprocess(
                                pred_md,
                                content_list_path=dst_cl if os.path.exists(dst_cl) else None,
                                pdf_path=effective_pdf_path,
                            )
                            with open(os.path.join(out_dir, f"{doc_stem}.md"), "w", encoding="utf-8") as wf:
                                wf.write(pred_md)

                if pred_md is None:
                    try:
                        release_gpu_memory()
                        if engine == "docling":
                            pred_md, duration = run_docling_extraction(effective_pdf_path, out_dir, in_process=True)
                        elif engine in ("infinity", "infinity_parser"):
                            pred_md, duration = run_infinity_extraction(effective_pdf_path, out_dir)
                        elif engine in ("lightonocr", "lightonocr3"):
                            pred_md, duration = run_lightonocr_extraction(effective_pdf_path, out_dir)
                        else:
                            raise ValueError(f"Unknown engine: {engine}")
                        os.makedirs(out_dir, exist_ok=True)
                        doc_stem = os.path.splitext(os.path.basename(effective_pdf_path))[0]
                        cl_cand = os.path.join(out_dir, f"{doc_stem}_content_list.json")
                        pred_md = apply_extraction_postprocess(
                            pred_md,
                            content_list_path=cl_cand if os.path.exists(cl_cand) else None,
                            pdf_path=effective_pdf_path,
                        )
                        with open(os.path.join(out_dir, ".duration.txt"), "w", encoding="utf-8") as df:
                            df.write(str(duration))
                    except Exception as e:
                        logger.error(f"Execution failed for {engine} on {doc_name}: {e}")
                        continue
                    finally:
                        release_gpu_memory()

                # Check document directories (TOC, List of Figures/Tables) as in production
                directory_info = None
                try:
                    from backend.services.directory_service import check_document_directories
                    directory_info = check_document_directories(effective_pdf_path, max_pages=20)
                except Exception as e:
                    logger.debug(f"Directory check skipped for {doc_name}: {e}")

                # Standardize formulas and inject physical page numbers
                pred_md = standardize_formulas(pred_md)
                pred_md = inject_benchmark_page_numbers(
                    pred_md,
                    effective_pdf_path,
                    out_dir,
                    physical_pages_override=physical_pages_override,
                    directory_info=directory_info,
                )

                # Stage 1: Evaluate raw extraction deterministically against Raw Golden Truth
                img_dir = os.path.join(out_dir, "images")
                raw_h = evaluate_headings(pred_md, raw_gold_md)
                raw_f = evaluate_formulas(pred_md, raw_gold_md)
                raw_t = evaluate_tables(pred_md, raw_gold_md)
                raw_c = evaluate_text_and_continuity(pred_md, raw_gold_md)
                raw_i = evaluate_images(pred_md, raw_gold_md, dataset_name=doc_name, image_dir=img_dir)
                raw_b = evaluate_boxes(pred_md, raw_gold_md)
                raw_a = evaluate_a11y(pred_md, expected_pages=page_count)
                raw_mono = evaluate_page_monotonicity(pred_md, raw_gold_md)
                raw_j = _programmatic_judge_fallback(raw_h, raw_f, raw_t, raw_c, raw_i)

                # Stage 2: Evaluate Post-Gemma Übertragungsregeln 09/2025 against Übertragungsregeln Golden Truth
                standardisation_backend = "skipped"
                chunk_count = 0
                std_duration = 0.0
                if skip_standardisation:
                    from backend.services.fibs_postprocess import post_process_structure
                    std_ueb = post_process_structure(pred_md, raw_markdown=pred_md, directory_info=directory_info)
                    standardisation_backend = "fast_postprocess_only"
                else:
                    bench_task_dir = None
                    std_start = time.time()
                    try:
                        from backend.services.llm_service import standardise_markdown
                        doc_base = os.path.splitext(doc_name)[0].replace("_scanned", "")
                        doc_rules_path = os.path.join(active_test_data_dir, f"{doc_base}_rules.txt")
                        bench_task_id = f"bench_{engine}_{doc_base}"
                        bench_task_dir = os.path.join(PROJECT_ROOT, "assets", "output", bench_task_id)
                        os.makedirs(bench_task_dir, exist_ok=True)
                        if os.path.exists(doc_rules_path):
                            with open(doc_rules_path, "r", encoding="utf-8") as rf:
                                custom_rules_content = rf.read()
                            with open(os.path.join(bench_task_dir, "custom_ruleset.txt"), "w", encoding="utf-8") as wf:
                                wf.write(custom_rules_content)

                        md_for_std = pred_md
                        if describe_images and os.path.isdir(img_dir):
                            vlm_cache_file = os.path.join(bench_task_dir, "vlm_cache.json")
                            md_for_std = run_vlm_descriptions_for_benchmark(
                                md_for_std, img_dir, cache_json_path=vlm_cache_file
                            )

                        standardisation_backend = "gemma"

                        def _on_std_progress(info: dict):
                            nonlocal standardisation_backend, chunk_count
                            if info.get("event") == "plan":
                                chunk_count = int(info.get("total", 1))
                            elif info.get("event") == "fallback":
                                standardisation_backend = "rule_based_fallback"

                        std_ueb = standardise_markdown(
                            md_for_std,
                            ruleset_key="uebertragungsregeln_09_2025",
                            task_id=bench_task_id,
                            allow_fallback=allow_fallback,
                            on_progress=_on_std_progress,
                            directory_info=directory_info,
                        )
                        std_ueb = inject_benchmark_page_numbers(
                            std_ueb,
                            effective_pdf_path,
                            out_dir,
                            physical_pages_override=physical_pages_override,
                            directory_info=directory_info,
                        )
                    except Exception as e:
                        logger.warning(f"Übertragungsregeln standardization fallback for {engine}: {e}")
                        std_ueb = pred_md
                        standardisation_backend = "error_raw_fallback"
                    finally:
                        std_duration = round(time.time() - std_start, 2)
                        if bench_task_dir and os.path.isdir(bench_task_dir) and not keep_temp:
                            import shutil
                            shutil.rmtree(bench_task_dir, ignore_errors=True)

                ueb_h = evaluate_headings(std_ueb, ueb_gold_md)
                ueb_f = evaluate_formulas(std_ueb, ueb_gold_md)
                ueb_t = evaluate_tables(std_ueb, ueb_gold_md)
                ueb_c = evaluate_text_and_continuity(std_ueb, ueb_gold_md)
                ueb_i = evaluate_images(std_ueb, ueb_gold_md, dataset_name=doc_name, image_dir=img_dir)
                ueb_b = evaluate_boxes(std_ueb, ueb_gold_md)
                ueb_a = evaluate_a11y(
                    std_ueb,
                    raw_markdown=pred_md,
                    expected_pages=page_count,
                )
                ueb_mono = evaluate_page_monotonicity(std_ueb, ueb_gold_md)
                ueb_docx = evaluate_docx_bookmarks(std_ueb)
                ueb_prog_metrics = {
                    "headings": ueb_h,
                    "formulas": ueb_f,
                    "tables": ueb_t,
                    "continuity": ueb_c,
                    "images": ueb_i,
                    "boxes": ueb_b,
                    "a11y": ueb_a,
                    "page_monotonicity": ueb_mono,
                }
                ueb_j = (
                    evaluate_with_gemma_judge(
                        std_ueb,
                        ueb_gold_md,
                        profile="uebertragungsregeln_09_2025",
                        programmatic_metrics=ueb_prog_metrics,
                    )
                    if not skip_standardisation
                    else _programmatic_judge_fallback(ueb_h, ueb_f, ueb_t, ueb_c, ueb_i, ueb_b)
                )

                rel_out_dir = os.path.relpath(out_dir, ext_root if (is_external_doc and ext_root) else PROJECT_ROOT)
                results[engine]["details_by_doc"][doc_name] = {
                    "duration_seconds": round(duration, 2),
                    "standardisation_seconds": std_duration,
                    "standardisation_backend": standardisation_backend,
                    "standardisation_chunks": chunk_count,
                    "peak_memory_mb": get_peak_memory_mb(),
                    "pages": page_count,
                    "output_dir": rel_out_dir,
                    "raw_md": pred_md,
                    "raw_metrics": {
                        "headings": raw_h,
                        "formulas": raw_f,
                        "tables": raw_t,
                        "continuity": raw_c,
                        "images": raw_i,
                        "boxes": raw_b,
                        "a11y": raw_a,
                        "page_monotonicity": raw_mono,
                        "judge": raw_j,
                    },
                    "uebertragung_metrics": {
                        "headings": ueb_h,
                        "formulas": ueb_f,
                        "tables": ueb_t,
                        "continuity": ueb_c,
                        "images": ueb_i,
                        "boxes": ueb_b,
                        "a11y": ueb_a,
                        "page_monotonicity": ueb_mono,
                        "docx_bookmarks": ueb_docx,
                        "judge": ueb_j,
                    },
                }
                _recompute_engine_score_lists(results[engine])

                if not keep_temp and os.path.isdir(out_dir):
                    import shutil
                    shutil.rmtree(out_dir, ignore_errors=True)

                # Incrementally save snapshot to JSON (and checkpoint_file if provided)
                target_runs_dir = os.path.join(ext_root, "benchmarks", "runs") if (has_external_docs and ext_root) else RUNS_DIR
                save_benchmark_snapshot(
                    results,
                    run_id,
                    timestamp,
                    engines,
                    datasets,
                    update_md=True,
                    runs_dir=target_runs_dir,
                    checkpoint_file=checkpoint_file,
                    has_external_docs=has_external_docs,
                    skip_standardisation=skip_standardisation,
                )

        # Final snapshot
        target_runs_dir = os.path.join(ext_root, "benchmarks", "runs") if (has_external_docs and ext_root) else RUNS_DIR
        run_record = save_benchmark_snapshot(
            results,
            run_id,
            timestamp,
            engines,
            datasets,
            update_md=True,
            runs_dir=target_runs_dir,
            checkpoint_file=checkpoint_file,
            has_external_docs=has_external_docs,
            skip_standardisation=skip_standardisation,
        )

        check_recent_crash_reports(start_bench_time)
        return run_record
    finally:
        release_sleep_assertion_sync(sleep_owner)


def _empty_engine_result_dbd(engine: str, existing: Dict[str, Any]) -> Dict[str, Any]:
    bucket = _empty_engine_result_bucket(engine)
    bucket["details_by_doc"] = dict(existing.get("details_by_doc", {}))
    _recompute_engine_score_lists(bucket)
    return bucket


def _is_metric_active(m: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(m, dict):
        return False
    return int(m.get("gold_count", 0) or 0) > 0 or int(m.get("pred_count", 0) or 0) > 0


def compute_doc_composite(doc_metrics: Dict[str, Any], include_boxes: bool = True) -> float:
    """
    Computes the per-document composite score while excluding non-applicable
    structural categories (where both gold_count == 0 and pred_count == 0)
    and re-normalizing the active category weights to 100%.
    """
    cont = doc_metrics.get("continuity", {})
    w_score = float(cont.get("word_recall", cont.get("score", 100.0)))
    c_score = float(cont.get("score", 100.0))
    j_score = float(doc_metrics.get("judge", {}).get("overall_judge_score", c_score))
    a_score = float(doc_metrics.get("a11y", {}).get("score", 100.0))

    weighted_components: List[Tuple[float, float]] = [
        (w_score, 0.15),
        (c_score, 0.10),
        (j_score, 0.18 if include_boxes else 0.20),
        (a_score, 0.05),
    ]

    h_m = doc_metrics.get("headings", {})
    if _is_metric_active(h_m) or ("gold_count" not in h_m and "pred_count" not in h_m):
        weighted_components.append((float(h_m.get("score", 100.0)), 0.10))

    t_m = doc_metrics.get("tables", {})
    if _is_metric_active(t_m):
        weighted_components.append((float(t_m.get("score", 100.0)), 0.12 if include_boxes else 0.15))

    f_m = doc_metrics.get("formulas", {})
    if _is_metric_active(f_m):
        weighted_components.append((float(f_m.get("score", 100.0)), 0.12 if include_boxes else 0.15))

    i_m = doc_metrics.get("images", {})
    if _is_metric_active(i_m):
        weighted_components.append((float(i_m.get("score", 100.0)), 0.10))

    if include_boxes:
        b_m = doc_metrics.get("boxes", {})
        if _is_metric_active(b_m):
            weighted_components.append((float(b_m.get("score", 100.0)), 0.08))

    total_w = sum(w for _, w in weighted_components)
    if total_w <= 0:
        return 100.0
    return round(sum(s * w for s, w in weighted_components) / total_w, 1)


def _programmatic_judge_fallback(
    h_m: Dict[str, Any],
    f_m: Dict[str, Any],
    t_m: Dict[str, Any],
    c_m: Dict[str, Any],
    i_m: Dict[str, Any],
    b_m: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    h_s = h_m["score"]
    f_s = f_m["score"]
    t_s = t_m["score"]
    c_s = c_m["score"]
    i_s = i_m["score"]
    active_scores = [c_s]
    if _is_metric_active(h_m):
        active_scores.append(h_s)
    if _is_metric_active(f_m):
        active_scores.append(f_s)
    if _is_metric_active(t_m):
        active_scores.append(t_s)
    if _is_metric_active(i_m):
        active_scores.append(i_s)
    if b_m is not None and _is_metric_active(b_m):
        active_scores.append(b_m["score"])
    return {
        "completeness_score": c_s,
        "headings_score": h_s,
        "formulas_score": f_s,
        "tables_score": t_s,
        "continuity_score": c_s,
        "images_score": i_s,
        "overall_judge_score": round(sum(active_scores) / len(active_scores), 1),
        "judge_feedback": "Evaluated via composite programmatic metric judge (fast mode)",
        "comment": "Evaluated via composite programmatic metric judge (fast mode)",
    }


OPEN_DOC_CATEGORIES = {
    "Core Baseline (4)": {
        "test_educational.pdf",
        "deutsch_textanalyse.pdf",
        "mathe_grade3.pdf",
        "physik_optik_sample.pdf",
    },
    "OpenStax STEM/Uni (3)": {
        "openstax_biology_sample.pdf",
        "openstax_chemistry_sample.pdf",
        "openstax_history_sample.pdf",
    },
    "Grundschule & Doppelseite (3)": {
        "grundschule_mathematik.pdf",
        "grundschule_sachkunde.pdf",
        "grundschule_lesebuch_doppelseite.pdf",
    },
    "Sekundarstufe I (5)": {
        "sek1_deutsch.pdf",
        "sek1_englisch.pdf",
        "sek1_geographie.pdf",
        "sek1_geschichte.pdf",
        "sek1_informatik.pdf",
    },
    "Sekundarstufe II & Verzeichnisse (4)": {
        "sek2_chemie.pdf",
        "sek2_biologie.pdf",
        "sek2_physik_verzeichnisse.pdf",
        "sek2_mathematik_analysis.pdf",
    },
}


def save_benchmark_snapshot(
    results: Dict[str, Any],
    run_id: str,
    timestamp: str,
    engines: List[str],
    datasets: List[str],
    update_md: bool = True,
    runs_dir: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
    has_external_docs: bool = False,
    skip_standardisation: bool = False,
) -> Dict[str, Any]:
    """Persists intermediate or final benchmark results to disk (run_{run_id}.json) and updates LEADERBOARD.md."""
    def compute_summary_for_docs(doc_filter_fn, label_suffix: str = "") -> List[Dict[str, Any]]:
        sub_summary = []
        for eng, data in results.items():
            matching_docs = [d for d in data["details_by_doc"].keys() if doc_filter_fn(d)]
            if not matching_docs:
                continue

            def _avg_active(metric_key: str, phase: str, default_val: float = 100.0) -> float:
                active_vals = [
                    data["details_by_doc"][d][phase].get(metric_key, {}).get("score", default_val)
                    for d in matching_docs
                    if _is_metric_active(data["details_by_doc"][d][phase].get(metric_key, {}))
                ]
                if active_vals:
                    return sum(active_vals) / len(active_vals)
                all_vals = [
                    data["details_by_doc"][d][phase].get(metric_key, {}).get("score", default_val)
                    for d in matching_docs
                ]
                return sum(all_vals) / len(all_vals) if all_vals else default_val

            raw_w_list = [data["details_by_doc"][d]["raw_metrics"]["continuity"].get("word_recall", data["details_by_doc"][d]["raw_metrics"]["continuity"]["score"]) for d in matching_docs]
            raw_c_list = [data["details_by_doc"][d]["raw_metrics"]["continuity"]["score"] for d in matching_docs]
            raw_a_list = [data["details_by_doc"][d]["raw_metrics"]["a11y"]["score"] for d in matching_docs]
            raw_j_list = [data["details_by_doc"][d]["raw_metrics"]["judge"]["overall_judge_score"] for d in matching_docs]

            ub_w_list = [data["details_by_doc"][d]["uebertragung_metrics"]["continuity"].get("word_recall", data["details_by_doc"][d]["uebertragung_metrics"]["continuity"]["score"]) for d in matching_docs]
            ub_c_list = [data["details_by_doc"][d]["uebertragung_metrics"]["continuity"]["score"] for d in matching_docs]
            ub_a_list = [data["details_by_doc"][d]["uebertragung_metrics"]["a11y"]["score"] for d in matching_docs]
            ub_j_list = [data["details_by_doc"][d]["uebertragung_metrics"]["judge"]["overall_judge_score"] for d in matching_docs]
            ub_m_list = [data["details_by_doc"][d]["uebertragung_metrics"].get("page_monotonicity", {}).get("score", 100.0) for d in matching_docs]
            ub_d_list = [data["details_by_doc"][d]["uebertragung_metrics"].get("docx_bookmarks", {}).get("score", 100.0) for d in matching_docs]
            backends = list(dict.fromkeys(data["details_by_doc"][d].get("standardisation_backend", "gemma") for d in matching_docs))

            tot_dur = sum(data["details_by_doc"][d]["duration_seconds"] for d in matching_docs)
            tot_pg = sum(data["details_by_doc"][d]["pages"] for d in matching_docs)

            avg_raw_h = _avg_active("headings", "raw_metrics")
            avg_raw_f = _avg_active("formulas", "raw_metrics")
            avg_raw_t = _avg_active("tables", "raw_metrics")
            avg_raw_i = _avg_active("images", "raw_metrics")
            avg_raw_b = _avg_active("boxes", "raw_metrics")
            avg_raw_w = sum(raw_w_list) / len(raw_w_list)
            avg_raw_c = sum(raw_c_list) / len(raw_c_list)
            avg_raw_a = sum(raw_a_list) / len(raw_a_list)
            avg_raw_j = sum(raw_j_list) / len(raw_j_list)
            comp_raw = sum(
                compute_doc_composite(data["details_by_doc"][d]["raw_metrics"], include_boxes=False)
                for d in matching_docs
            ) / len(matching_docs)

            avg_ub_h = _avg_active("headings", "uebertragung_metrics")
            avg_ub_f = _avg_active("formulas", "uebertragung_metrics")
            avg_ub_t = _avg_active("tables", "uebertragung_metrics")
            avg_ub_i = _avg_active("images", "uebertragung_metrics")
            avg_ub_b = _avg_active("boxes", "uebertragung_metrics")
            avg_ub_w = sum(ub_w_list) / len(ub_w_list)
            avg_ub_c = sum(ub_c_list) / len(ub_c_list)
            avg_ub_a = sum(ub_a_list) / len(ub_a_list)
            avg_ub_j = sum(ub_j_list) / len(ub_j_list)
            avg_ub_m = sum(ub_m_list) / len(ub_m_list)
            avg_ub_d = sum(ub_d_list) / len(ub_d_list)
            comp_ub = sum(
                compute_doc_composite(data["details_by_doc"][d]["uebertragung_metrics"], include_boxes=True)
                for d in matching_docs
            ) / len(matching_docs)

            sec_pg = round(tot_dur / max(tot_pg, 1), 2)

            sub_summary.append({
                "engine": eng,
                "engine_key": f"{eng}_{label_suffix.lower()}" if label_suffix else eng,
                "source_type": label_suffix or "Overall",
                "version": get_engine_version(eng),
                "docs_evaluated": len(matching_docs),
                "standardisation_backend": "/".join(backends),
                "composite_raw": round(comp_raw, 1),
                "composite_uebertragung_2025": round(comp_ub, 1),
                "raw_headings": round(avg_raw_h, 1),
                "raw_formulas": round(avg_raw_f, 1),
                "raw_tables": round(avg_raw_t, 1),
                "raw_images": round(avg_raw_i, 1),
                "raw_boxes": round(avg_raw_b, 1),
                "raw_word_recall": round(avg_raw_w, 1),
                "raw_continuity": round(avg_raw_c, 1),
                "raw_a11y": round(avg_raw_a, 1),
                "raw_judge": round(avg_raw_j, 1),
                "ueb_headings": round(avg_ub_h, 1),
                "ueb_formulas": round(avg_ub_f, 1),
                "ueb_tables": round(avg_ub_t, 1),
                "ueb_images": round(avg_ub_i, 1),
                "ueb_boxes": round(avg_ub_b, 1),
                "ueb_word_recall": round(avg_ub_w, 1),
                "ueb_continuity": round(avg_ub_c, 1),
                "ueb_a11y": round(avg_ub_a, 1),
                "ueb_judge": round(avg_ub_j, 1),
                "ueb_page_monotonicity": round(avg_ub_m, 1),
                "ueb_docx_bookmarks": round(avg_ub_d, 1),
                "sec_per_page": sec_pg
            })
        return sub_summary

    summary_digital = compute_summary_for_docs(lambda d: not d.endswith("_scanned.pdf"), "Digital")
    summary_scanned = compute_summary_for_docs(lambda d: d.endswith("_scanned.pdf"), "Scanned")
    summary_overall = compute_summary_for_docs(lambda d: True, "Overall")

    category_breakdown: Dict[str, List[Dict[str, Any]]] = {}
    for cat_label, cat_docs in OPEN_DOC_CATEGORIES.items():
        cat_rows = compute_summary_for_docs(lambda d, cd=cat_docs: d in cd, cat_label)
        if cat_rows:
            category_breakdown[cat_label] = cat_rows

    open_all_set = set(SUITE_DATASETS.get("open_all", []))
    ext_rows = compute_summary_for_docs(
        lambda d: not d.endswith("_scanned.pdf") and d not in open_all_set,
        "Publisher Corpus",
    )
    if ext_rows:
        category_breakdown["Publisher Corpus (External)"] = ext_rows

    full_summary = []
    full_summary.extend(summary_digital)
    full_summary.extend(summary_scanned)

    # Classify run tier
    digital_doc_count = max((r.get("docs_evaluated", 0) for r in summary_digital), default=0)
    if skip_standardisation:
        run_tier = "fast"
    elif has_external_docs and digital_doc_count >= 10:
        run_tier = "full_extended"
    elif len(engines) >= 2 and digital_doc_count <= 3:
        run_tier = "smoke"
    elif len(engines) >= 2 and digital_doc_count >= 4:
        run_tier = "open_multi_engine"
    else:
        run_tier = "custom"

    run_record = {
        "run_id": run_id,
        "timestamp": timestamp,
        "run_tier": run_tier,
        "skip_standardisation": skip_standardisation,
        "has_external_docs": has_external_docs,
        "engines_requested": list(engines),
        "datasets_count": len(datasets),
        "summary": full_summary,
        "summary_digital": summary_digital,
        "summary_scanned": summary_scanned,
        "summary_overall": summary_overall,
        "category_breakdown": category_breakdown,
        "details": results
    }

    out_runs_dir = runs_dir or RUNS_DIR
    os.makedirs(out_runs_dir, exist_ok=True)
    run_record_path = os.path.join(out_runs_dir, f"run_{run_id}.json")
    with open(run_record_path, "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2)

    if checkpoint_file and os.path.abspath(checkpoint_file) != os.path.abspath(run_record_path):
        os.makedirs(os.path.dirname(os.path.abspath(checkpoint_file)), exist_ok=True)
        with open(checkpoint_file, "w", encoding="utf-8") as cf:
            json.dump(run_record, cf, indent=2)

    if update_md and (summary_digital or summary_scanned):
        update_leaderboard(run_record, external_runs_dir=out_runs_dir if has_external_docs else None)

    return run_record


def get_engine_version(engine: str) -> str:
    """Retrieves the installed package version of the extraction engine."""
    import importlib.metadata
    pkg_map = {
        "lightonocr": ["mlx-vlm", "mlx", "transformers"],
        "infinity": ["mlx-vlm", "mlx", "transformers"],
        "docling": ["docling"]
    }

    for pkg in pkg_map.get(engine, [engine]):
        try:
            return f"v{importlib.metadata.version(pkg)}"
        except Exception:
            pass
    return "v?.?.?"


def check_recent_crash_reports(start_time: float) -> None:
    """Checks ~/Library/Logs/DiagnosticReports/ (macOS) for any Python crashes during benchmark run."""
    if sys.platform != "darwin":
        return
    import glob
    crash_dir = os.path.expanduser("~/Library/Logs/DiagnosticReports")
    if not os.path.exists(crash_dir):
        return

    ips_files = glob.glob(os.path.join(crash_dir, "Python*.ips"))
    recent_crashes = []
    for f in ips_files:
        try:
            mtime = os.path.getmtime(f)
            if mtime >= start_time:
                recent_crashes.append(f)
        except Exception:
            pass

    if not recent_crashes:
        logger.info("✅ Zero Python crashes detected during benchmark run.")
    else:
        logger.warning(f"⚠️ {len(recent_crashes)} Python crash report(s) detected during benchmark run:")
        for crash_file in recent_crashes:
            logger.warning(f"   • {crash_file}")


BENCHMARK_LICENSE_TAGS = {
    "lightonocr": "Apache 2.0 *(Commercial)*",
    "infinity": "Apache 2.0 *(Commercial)*",
    "docling": "Apache 2.0 *(Commercial)*"
}


def render_standings_table(rows: List[Dict[str, Any]], metric_key: str, is_diff: bool = False) -> str:
    """Renders a formatted Markdown table for a set of benchmark summary rows."""
    if not rows:
        return "*(No documents evaluated for this category in this run. Run with `--include-scanned` to benchmark rasterized image PDFs on-demand.)*\n"

    engine_names = {
        "lightonocr": f"🔥 **LightOnOCR-3-0.8B** (LightOn AI {get_engine_version('lightonocr')})",
        "infinity": f"⚡ **Infinity-Parser2-Flash** (INF Tech {get_engine_version('infinity')})",
        "docling": f"🚀 **Docling** (IBM Research {get_engine_version('docling')})"
    }

    if is_diff:
        table_md = "| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |\n"
    else:
        table_md = "| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (20%) | Tables (15%) | Formulas (15%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` | Page `((N))` | DOCX BM | Speed (s/p) |\n"
    table_md += "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"

    for rank_idx, row in enumerate(rows, 1):
        eng = row['engine']
        eng_label = engine_names.get(eng, eng)
        docs_n = row.get("docs_evaluated", "-")
        src_badge = f"`📄 {row.get('source_type', 'Digital')}`"
        score = row.get(metric_key, 0)

        prefix = "raw" if "raw" in metric_key else "ueb"
        h = row.get(f"{prefix}_headings", 0)
        f_s = row.get(f"{prefix}_formulas", 0)
        t = row.get(f"{prefix}_tables", 0)
        img_s = row.get(f"{prefix}_images", 100.0)
        box_s = row.get(f"{prefix}_boxes", 100.0)
        w = row.get(f"{prefix}_word_recall", row.get(f"{prefix}_continuity", 0))
        c = row.get(f"{prefix}_continuity", 0)
        a = row.get(f"{prefix}_a11y", 0)
        j = row.get(f"{prefix}_judge", 0)
        mono = row.get("ueb_page_monotonicity", 100.0)
        docx_bm = row.get("ueb_docx_bookmarks", 100.0)

        if is_diff:
            diff = round(score - row.get('composite_raw', 0), 1)
            diff_str = f"+{diff} pts" if diff >= 0 else f"{diff} pts"
            table_md += f"| **#{rank_idx}** | {eng_label} | {docs_n} | {src_badge} | **{score}/100** | {w}% | {c}% | {j}% | {t}% | {f_s}% | {h}% | {img_s}% | {a}% | {box_s}% | {mono}% | {docx_bm}% | **{diff_str}** |\n"
        else:
            speed = row.get('sec_per_page', 0)
            table_md += f"| **#{rank_idx}** | {eng_label} | {docs_n} | {src_badge} | **{score}/100** | {w}% | {c}% | {j}% | {t}% | {f_s}% | {h}% | {img_s}% | {a}% | {box_s}% | {mono}% | {docx_bm}% | **{speed} s** |\n"

    return table_md


def _classify_saved_run(rj: Dict[str, Any]) -> str:
    """Classifies a historical run JSON into one of the leaderboard tiers and backfills docs_evaluated."""
    details = rj.get("details", {})
    for list_key in ("summary_digital", "summary_scanned", "summary"):
        for r in rj.get(list_key, []):
            if not r.get("docs_evaluated"):
                eng = r.get("engine", "")
                dbd = details.get(eng, {}).get("details_by_doc", {})
                if list_key == "summary_scanned":
                    cnt = len([d for d in dbd if d.endswith("_scanned.pdf")])
                else:
                    cnt = len([d for d in dbd if not d.endswith("_scanned.pdf")])
                if cnt > 0:
                    r["docs_evaluated"] = cnt

    tier = rj.get("run_tier")
    dig = rj.get("summary_digital", [])
    if not dig:
        return "empty"
    max_docs = max((r.get("docs_evaluated", 0) for r in dig), default=0)
    full_engines = sum(1 for r in dig if r.get("docs_evaluated", 0) >= 4)
    if rj.get("skip_standardisation"):
        if len(dig) >= 2 and full_engines >= 2:
            return "open_multi_engine"
        if len(dig) >= 2 and max_docs <= 3:
            return "smoke"
        return "fast"
    if rj.get("has_external_docs") and max_docs >= 10:
        return "full_extended"
    if len(dig) >= 2 and full_engines >= 2:
        return "open_multi_engine"
    if len(dig) >= 2 and max_docs <= 3:
        return "smoke"
    if tier in ("fast", "smoke", "full_extended"):
        return tier
    return "fast" if len(dig) == 1 else "partial"


def _load_latest_runs_by_tier(
    current_run: Dict[str, Any], external_runs_dir: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Scans `benchmarks/runs/run_*.json` and `checkpoint_*.json` (plus `../ebuch-testdaten/benchmarks/runs/`
    if readable) sorted chronologically by `timestamp` so that `LEADERBOARD.md` always displays the
    latest result for EACH benchmark tier without small/fast runs overwriting large multi-engine standings.
    """
    import glob

    tiers: Dict[str, Dict[str, Any]] = {}
    search_dirs = [RUNS_DIR]
    ext_dir = resolve_external_data_dir()
    if ext_dir:
        ext_rdir = os.path.join(ext_dir, "benchmarks", "runs")
        if os.path.isdir(ext_rdir) and ext_rdir not in search_dirs:
            search_dirs.append(ext_rdir)
    if external_runs_dir and os.path.isdir(external_runs_dir) and external_runs_dir not in search_dirs:
        search_dirs.append(external_runs_dir)

    all_files = []
    for sdir in search_dirs:
        try:
            all_files.extend(glob.glob(os.path.join(sdir, "run_*.json")))
            all_files.extend(glob.glob(os.path.join(sdir, "checkpoint_*.json")))
        except Exception:
            pass

    loaded_records: List[Dict[str, Any]] = []
    for fpath in all_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("summary_digital") and not data.get("summary"):
                continue
            loaded_records.append(data)
        except Exception:
            pass

    loaded_records.sort(key=lambda d: (str(d.get("timestamp", "")), str(d.get("run_id", ""))))

    for data in loaded_records:
        t = _classify_saved_run(data)
        tiers[t] = data
        cb = data.get("category_breakdown") or {}
        if cb:
            prev_cb = (tiers.get("latest_categorized") or {}).get("category_breakdown") or {}
            if len(cb) >= len(prev_cb):
                tiers["latest_categorized"] = data
            if "Publisher Corpus (External)" in cb:
                tiers["latest_external_category"] = cb["Publisher Corpus (External)"]

    curr_tier = _classify_saved_run(current_run)
    tiers[curr_tier] = current_run
    curr_cb = current_run.get("category_breakdown") or {}
    if curr_cb:
        prev_cb = (tiers.get("latest_categorized") or {}).get("category_breakdown") or {}
        if len(curr_cb) >= len(prev_cb):
            tiers["latest_categorized"] = current_run
        if "Publisher Corpus (External)" in curr_cb:
            tiers["latest_external_category"] = curr_cb["Publisher Corpus (External)"]

    if tiers.get("latest_categorized") and tiers.get("latest_external_category"):
        merged_cb = dict(tiers["latest_categorized"].get("category_breakdown") or {})
        if "Publisher Corpus (External)" not in merged_cb:
            merged_cb["Publisher Corpus (External)"] = tiers["latest_external_category"]
            tiers["latest_categorized"] = dict(tiers["latest_categorized"], category_breakdown=merged_cb)
    return tiers


def render_executive_tier_overview(tiers: Dict[str, Dict[str, Any]]) -> str:
    """Renders the top-level Executive Quality Overview comparing Small/Fast and Large/Full benchmark tiers."""
    tier_specs = [
        ("fast", "⚡ **Tier 1: Fast Regression** (`--mode fast`)", "Docling + Deterministic FIBS (`open_all`)"),
        ("smoke", "🧪 **Tier 2: Multi-Engine + Gemma Smoke** (`--mode smoke`)", "All 3 OCR Engines + Gemma 4 12B (Smoke Subset)"),
        ("open_multi_engine", "🏛️ **Tier 3: Comprehensive Open Suite** (`core` / `open_all`)", "All 3 OCR Engines + Gemma 4 12B (Open Textbooks)"),
        ("full_extended", "🔒 **Tier 4: Extended Publisher Suite** (`--mode full`)", "All 3 OCR Engines + Gemma 4 12B (Open + Publisher Corpus)"),
    ]
    md = "| Benchmark Tier | Pipeline Scope | Latest Run | Docs (`N`) | Best Engine | Raw Score | FIBS 09/2025 Score | `<Bild>` | `<Rahmen>` | Page `((N))` | Speed (s/p) |\n"
    md += "| :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    for key, label, scope_desc in tier_specs:
        r = tiers.get(key)
        if not r or not r.get("summary_digital"):
            md += f"| {label} | {scope_desc} | *Pending* | – | – | – | – | – | – | – | – |\n"
            continue
        max_n = max((x.get("docs_evaluated", 0) for x in r["summary_digital"]), default=0)
        full_dig = [x for x in r["summary_digital"] if x.get("docs_evaluated", 0) == max_n] or r["summary_digital"]
        dig = sorted(full_dig, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
        best = dig[0]
        run_id = r.get("run_id", "-")
        docs_n = best.get("docs_evaluated", r.get("datasets_count", "-"))
        eng = best.get("engine", "-")
        raw_s = best.get("composite_raw", 0)
        ueb_s = best.get("composite_uebertragung_2025", 0)
        img_s = best.get("ueb_images", 100.0)
        box_s = best.get("ueb_boxes", 100.0)
        mono_s = best.get("ueb_page_monotonicity", 100.0)
        spd = best.get("sec_per_page", 0)
        md += f"| {label} | {scope_desc} | `{run_id}` | **{docs_n}** | **{eng}** | {raw_s}/100 | **{ueb_s}/100** | {img_s}% | {box_s}% | {mono_s}% | {spd} s |\n"
    return md


def render_category_breakdown_table(cat_run: Optional[Dict[str, Any]], include_external: bool = False) -> str:
    """Renders per-category scores across textbook types (Core, OpenStax, Grundschule, Sek I, Sek II)."""
    if not cat_run or not cat_run.get("category_breakdown"):
        return "*(Run `python scripts/run_benchmark.py` to populate the textbook category breakdown.)*\n"

    cb = cat_run["category_breakdown"]
    md = f"*Source Run: `{cat_run.get('run_id')}` ({cat_run.get('timestamp')})*\n\n"
    md += "| Textbook Category / Format | Engine | Docs (`N`) | Raw Score | FIBS 09/2025 Score | Recall | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Page `((N))` | A11y |\n"
    md += "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    for cat_name, rows in cb.items():
        if "Publisher" in cat_name and not include_external:
            continue
        for row in sorted(rows, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True):
            md += (
                f"| **{cat_name}** | `{row['engine']}` | {row.get('docs_evaluated', '-')} | "
                f"{row.get('composite_raw', 0)}/100 | **{row.get('composite_uebertragung_2025', 0)}/100** | "
                f"{row.get('ueb_word_recall', 0)}% | {row.get('ueb_headings', 0)}% | "
                f"{row.get('ueb_formulas', 0)}% | {row.get('ueb_tables', 0)}% | "
                f"{row.get('ueb_images', 100.0)}% | {row.get('ueb_boxes', 100.0)}% | "
                f"{row.get('ueb_page_monotonicity', 100.0)}% | {row.get('ueb_a11y', 0)}% |\n"
            )
    return md


def update_leaderboard(current_run: Dict[str, Any], external_runs_dir: Optional[str] = None):
    """Updates benchmarks/LEADERBOARD.md as a multi-tier dashboard covering both small/fast and large/full runs."""
    tiers = _load_latest_runs_by_tier(current_run, external_runs_dir=external_runs_dir)

    # Primary multi-engine open run (falls back to current_run if none exists yet)
    primary_run = tiers.get("open_multi_engine") or tiers.get("smoke") or current_run
    timestamp = primary_run["timestamp"]
    run_id = primary_run["run_id"]

    summary_digital = primary_run.get("summary_digital", [])
    summary_scanned = primary_run.get("summary_scanned", [])

    dig_raw_sorted = sorted(summary_digital, key=lambda x: x.get("composite_raw", 0), reverse=True)
    scan_raw_sorted = sorted(summary_scanned, key=lambda x: x.get("composite_raw", 0), reverse=True)

    dig_ueb_sorted = sorted(summary_digital, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
    scan_ueb_sorted = sorted(summary_scanned, key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)

    scanned_raw_section = ""
    scanned_ueb_section = ""
    if summary_scanned:
        scanned_raw_section = f"\n### 📸 Scanned Image PDFs (300 DPI Raster)\n{render_standings_table(scan_raw_sorted, 'composite_raw', is_diff=False)}\n"
        scanned_ueb_section = f"\n### 📸 Scanned Image PDFs (300 DPI Raster)\n{render_standings_table(scan_ueb_sorted, 'composite_uebertragung_2025', is_diff=True)}\n"

    fast_run = tiers.get("fast")
    smoke_run = tiers.get("smoke")
    fast_smoke_section = ""
    if fast_run or smoke_run:
        fast_smoke_section += "\n---\n\n## ⚡ 3. Fast Regression (`--mode fast`) & Multi-Engine Smoke (`--mode smoke`) Standings\n\n"
        if fast_run and fast_run.get("summary_digital"):
            f_dig = sorted(fast_run["summary_digital"], key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
            fast_smoke_section += f"### ⚡ Latest Fast Regression Run (`{fast_run['run_id']}` – {fast_run['timestamp']}, Deterministic FIBS Post-Process)\n"
            fast_smoke_section += render_standings_table(f_dig, "composite_uebertragung_2025", is_diff=True) + "\n"
        if smoke_run and smoke_run.get("summary_digital"):
            s_dig = sorted(smoke_run["summary_digital"], key=lambda x: x.get("composite_uebertragung_2025", 0), reverse=True)
            fast_smoke_section += f"### 🧪 Latest Multi-Engine + Gemma Smoke Run (`{smoke_run['run_id']}` – {smoke_run['timestamp']})\n"
            fast_smoke_section += render_standings_table(s_dig, "composite_uebertragung_2025", is_diff=True) + "\n"

    cat_source_run = tiers.get("latest_categorized") or fast_run or primary_run
    category_section = render_category_breakdown_table(cat_source_run, include_external=False)
    category_section_external = render_category_breakdown_table(cat_source_run, include_external=True)

    leaderboard_content = f"""# E-Buch Document Extraction & Standardization Leaderboard

This leaderboard tracks extraction accuracy, structural integrity, formula transcription fidelity, table reconstruction, image & `<Bild>` fidelity, `<Rahmen>` callout detection, page-number monotonicity (`((N))`), Word DOCX screen-reader bookmarks, and processing speed across integrated layout engines (**LightOnOCR-3-0.8B**, **Infinity-Parser2-Flash**, and **Docling**).

Evaluations are performed against **Golden Ground Truth** references using both multi-dimensional programmatic metrics and **LLM Judge evaluations** (Gemma 4 12B-it).

> **Multi-Tier Leaderboard Design:** Both fast/small regression checks (`--mode fast`, `--mode smoke`) and comprehensive multi-engine evaluations (`--suite core`, `--suite schoolbooks`, `--suite open_all`, `--mode full`) are tracked in dedicated sections below so fast runs never overwrite full multi-engine standings. Detailed per-document records for proprietary publisher textbooks reside exclusively in `../ebuch-testdaten/benchmarks/runs/`.

---

## 📊 0. Executive Quality Overview (Small / Fast vs. Large / Full Tiers)

{render_executive_tier_overview(tiers)}

---

## 🏆 1. Raw Extraction Standings (Before LLM Standardization)

*Measures the native visual/text extraction accuracy of each engine directly from the document.*

**Latest Multi-Engine Run:** {timestamp} (Run: `{run_id}`)

### 📄 Digital Native PDFs
{render_standings_table(dig_raw_sorted, "composite_raw", is_diff=False)}
{scanned_raw_section}
---

## 📜 2. Post-Gemma Übertragungsregeln Standings (`uebertragungsregeln_09_2025`)

*Measures the final document quality after Gemma 4 12B applies the **Übertragungsregeln (Stand September 2025)** profile (`_Hervorhebung_` default, `*fett*`, `%kursiv%`, `#Merkmal#`, `<Tabelle>`, `<Bild>`, `<Rahmen>`, `\\t` list tabs, and `{{n}}` footnotes).*

### 📄 Digital Native PDFs
{render_standings_table(dig_ueb_sorted, "composite_uebertragung_2025", is_diff=True)}
{scanned_ueb_section}{fast_smoke_section}
---

## 📚 4. Textbook Category & Format Breakdown

*Breaks down quality across textbook types and page geometries (DIN A4, B5+, B5-Breitformat, Querformat/Doppelseite `((N)) / ((N+1))`, and University STEM).*

{category_section}
---

## ⚖️ Engine Architecture & Commercial Licensing Matrix

| Engine | Primary Architecture | License | Commercial Usability | Role in Production Pipeline |
| :--- | :--- | :---: | :---: | :--- |
| **LightOnOCR-3-0.8B** | Compact End-to-End Vision-Language Model (~0.8B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary Compact VLM Engine**: High-accuracy formula/table/scan OCR with minimal memory footprint (~1.7 GB BF16) on Apple Silicon & CPU/CUDA. |
| **Infinity-Parser2-Flash** | End-to-End Vision-Language Model (~2B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary High-Capacity VLM Engine**: High-fidelity multimodal extraction for complex STEM formulas, native math LaTeX, Markdown tables, and scanned/raster PDF OCR. |
| **Docling** | Granite-DocLayNet Layout (`RT-DETR-v2`) + `TableFormer` + Unicode Math Normalization | MIT / Apache 2.0 | ✅ Permitted | **High-Speed Layout Engine**: Ultra-fast structural extraction, BBox heading hierarchy clustering, and table parsing. |

---

## 📜 Historical Runs Log

"""
    past_runs = []
    if os.path.exists(LEADERBOARD_PATH):
        try:
            with open(LEADERBOARD_PATH, "r", encoding="utf-8") as f:
                existing_text = f.read()
            hist_match = re.search(r"## 📜 Historical Runs Log\s*\n+(.*)", existing_text, re.DOTALL)
            if hist_match:
                past_runs.append(hist_match.group(1).strip())
        except Exception:
            pass

    curr_tier_label = _classify_saved_run(current_run)
    current_summary = current_run.get("summary_digital", current_run.get("summary", []))
    curr_run_id = current_run["run_id"]
    curr_ts = current_run["timestamp"]
    current_entry = f"### Run `{curr_run_id}` ({curr_ts}) — Tier: `{curr_tier_label}`\n"
    current_entry += "| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |\n"
    current_entry += "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    for r in current_summary:
        ver = r.get("version", get_engine_version(r['engine']))
        lic = BENCHMARK_LICENSE_TAGS.get(r['engine'], "Open Source")
        current_entry += (
            f"| {r['engine']} | {r.get('docs_evaluated', '-')} | {ver} | {lic} | "
            f"{r.get('composite_raw')} | **{r.get('composite_uebertragung_2025')}** | "
            f"{r.get('ueb_headings', r.get('raw_headings'))}% | {r.get('ueb_formulas', r.get('raw_formulas'))}% | "
            f"{r.get('ueb_tables', r.get('raw_tables'))}% | {r.get('ueb_images', r.get('raw_images', 100.0))}% | "
            f"{r.get('ueb_boxes', r.get('raw_boxes', 100.0))}% | {r.get('sec_per_page', 0)} s |\n"
        )

    leaderboard_content += current_entry + "\n\n"
    for p in past_runs:
        for entry in re.split(r"(?m)^(?=### Run `)", p or ""):
            entry = entry.strip()
            if entry and not entry.startswith(f"### Run `{curr_run_id}`"):
                leaderboard_content += entry + "\n\n"

    with open(LEADERBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(leaderboard_content)

    logger.info(f"Updated Leaderboard at {LEADERBOARD_PATH}")

    # If an external runs directory is active, also write a companion LEADERBOARD.md inside ../ebuch-testdaten/benchmarks/
    if external_runs_dir:
        ext_lb_path = os.path.join(os.path.dirname(external_runs_dir), "LEADERBOARD.md")
        ext_content = leaderboard_content.replace(category_section, category_section_external)
        try:
            with open(ext_lb_path, "w", encoding="utf-8") as ef:
                ef.write(ext_content)
            logger.info(f"Updated External Companion Leaderboard at {ext_lb_path}")
        except Exception as e:
            logger.debug(f"Could not write external leaderboard {ext_lb_path}: {e}")


def augment_scanned_page_image(pil_img: Any, page_idx: int, seed: int = 42) -> Any:
    """
    Applies deterministic textbook scan artifacts (warm paper tint, subtle alternating skew,
    spine/gutter shadow along the inner edge, and low-amplitude sensor grain) to a 300-DPI page image.
    """
    import random
    from PIL import Image, ImageEnhance, ImageFilter

    rng = random.Random(seed + page_idx * 17)
    rgb = pil_img.convert("RGB")
    w, h = rgb.size

    # 1. Warm paper tint
    r_ch, g_ch, b_ch = rgb.split()
    r_ch = r_ch.point(lambda v: min(255, int(v * 0.992)))
    g_ch = g_ch.point(lambda v: min(255, int(v * 0.982)))
    b_ch = b_ch.point(lambda v: min(255, int(v * 0.958)))
    tinted = Image.merge("RGB", (r_ch, g_ch, b_ch))

    # 2. Subtle inner-margin spine/gutter shadow (Buchfalz-Abschattung)
    gutter_w = max(24, int(w * 0.025))
    gutter_strip = Image.new("L", (gutter_w, 1))
    on_left = (page_idx % 2 == 0)
    for gx in range(gutter_w):
        t = (gx / max(1, gutter_w - 1)) if on_left else ((gutter_w - 1 - gx) / max(1, gutter_w - 1))
        factor = int(round(238 + 17 * (t ** 0.7)))
        gutter_strip.putpixel((gx, 0), min(255, factor))
    gutter_band = gutter_strip.resize((gutter_w, h), resample=Image.Resampling.BILINEAR).convert("RGB")
    paste_x = 0 if on_left else (w - gutter_w)
    from PIL import ImageChops
    sub_crop = tinted.crop((paste_x, 0, paste_x + gutter_w, h))
    tinted.paste(ImageChops.multiply(sub_crop, gutter_band), (paste_x, 0))

    # 3. Subtle alternating page skew (-0.35° / +0.30°)
    angle = -0.35 if page_idx % 2 == 0 else 0.30
    rotated = tinted.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(248, 245, 238))

    # 4. Deterministic low-amplitude paper grain & slight optical softening
    grain = Image.new("L", (max(1, w // 4), max(1, h // 4)))
    grain_bytes = bytes(rng.randint(244, 255) for _ in range((max(1, w // 4)) * (max(1, h // 4))))
    grain.frombytes(grain_bytes)
    grain_full = grain.resize((w, h), resample=Image.Resampling.BILINEAR).convert("RGB")
    blended = Image.blend(rotated, grain_full, alpha=0.05)
    softened = blended.filter(ImageFilter.GaussianBlur(radius=0.35))
    return ImageEnhance.Contrast(softened).enhance(1.04)


def ensure_scanned_pdfs(force: bool = False):
    """Generates rasterized 300-DPI scan-degraded PDFs from digital PDFs to benchmark scanned document extraction."""
    try:
        import pypdfium2
    except ImportError:
        logger.warning("pypdfium2 or PIL not installed, skipping automatic scanned PDF generation.")
        return

    test_data_dir = os.path.join(PROJECT_ROOT, "testdata")
    digital_files = [
        "test_educational.pdf",
        "deutsch_textanalyse.pdf",
        "mathe_grade3.pdf",
        "physik_optik_sample.pdf",
        "openstax_biology_sample.pdf",
        "openstax_chemistry_sample.pdf",
        "openstax_history_sample.pdf",
        "grundschule_mathematik.pdf",
        "grundschule_sachkunde.pdf",
        "grundschule_lesebuch_doppelseite.pdf",
        "sek1_deutsch.pdf",
        "sek1_englisch.pdf",
        "sek1_geographie.pdf",
        "sek1_geschichte.pdf",
        "sek1_informatik.pdf",
        "sek2_chemie.pdf",
        "sek2_biologie.pdf",
        "sek2_physik_verzeichnisse.pdf",
        "sek2_mathematik_analysis.pdf",
    ]

    for idx, fname in enumerate(digital_files):
        in_path = os.path.join(test_data_dir, fname)
        base = os.path.splitext(fname)[0]
        out_path = os.path.join(test_data_dir, f"{base}_scanned.pdf")

        if (force or not os.path.exists(out_path)) and os.path.exists(in_path):
            try:
                pdf = pypdfium2.PdfDocument(in_path)
                images = []
                for p_i, page in enumerate(pdf):
                    pix = page.render(scale=300.0 / 72.0).to_pil()
                    images.append(augment_scanned_page_image(pix, page_idx=p_i, seed=100 + idx))
                pdf.close()

                if images:
                    images[0].save(out_path, save_all=True, append_images=images[1:], resolution=300.0)
                    logger.info(f"Generated rasterized scanned PDF: {out_path} ({len(images)} pages)")
            except Exception as e:
                logger.warning(f"Could not generate scanned PDF for {fname}: {e}")


SUITE_DATASETS = {
    "smoke": [
        "test_educational.pdf",
        "sek1_informatik.pdf",
    ],
    "core": [
        "test_educational.pdf",
        "deutsch_textanalyse.pdf",
        "mathe_grade3.pdf",
        "physik_optik_sample.pdf",
    ],
    "schoolbooks": [
        "grundschule_mathematik.pdf",
        "grundschule_sachkunde.pdf",
        "grundschule_lesebuch_doppelseite.pdf",
        "sek1_deutsch.pdf",
        "sek1_englisch.pdf",
        "sek1_geographie.pdf",
        "sek1_geschichte.pdf",
        "sek1_informatik.pdf",
        "sek2_chemie.pdf",
        "sek2_biologie.pdf",
        "sek2_physik_verzeichnisse.pdf",
        "sek2_mathematik_analysis.pdf",
    ],
    "open_all": [
        "test_educational.pdf",
        "deutsch_textanalyse.pdf",
        "mathe_grade3.pdf",
        "physik_optik_sample.pdf",
        "openstax_biology_sample.pdf",
        "openstax_chemistry_sample.pdf",
        "openstax_history_sample.pdf",
        "grundschule_mathematik.pdf",
        "grundschule_sachkunde.pdf",
        "grundschule_lesebuch_doppelseite.pdf",
        "sek1_deutsch.pdf",
        "sek1_englisch.pdf",
        "sek1_geographie.pdf",
        "sek1_geschichte.pdf",
        "sek1_informatik.pdf",
        "sek2_chemie.pdf",
        "sek2_biologie.pdf",
        "sek2_physik_verzeichnisse.pdf",
        "sek2_mathematik_analysis.pdf",
    ],
}
# Alias 'all' to 'open_all' for backwards compatibility
SUITE_DATASETS["all"] = list(SUITE_DATASETS["open_all"])


def resolve_suite_datasets(suite: str, external_data_dir: Optional[str] = None) -> List[str]:
    """
    Resolves dataset filenames for a named suite:
      - `smoke`: 1 open doc + 1 multi-format schoolbook (+ 1 external publisher doc if available)
      - `core`: 4 baseline documents
      - `schoolbooks`: 12 multi-format schoolbooks
      - `open_all` / `all`: all 19 open repository documents
      - `external`: all 50 proprietary publisher PDFs from `../ebuch-testdaten/catalog.json`
      - `full`: all 19 open documents + all 50 proprietary publisher PDFs (69 total)
    """
    ext_root = resolve_external_data_dir(external_data_dir)
    cat_map = load_external_catalog(ext_root)
    ext_docs: List[str] = []
    if ext_root and cat_map:
        seen = set()
        for key, entry in cat_map.items():
            if key.endswith(".pdf") and key not in seen:
                seen.add(key)
                ext_docs.append(key)

    if suite == "external":
        return ext_docs
    if suite == "full":
        return list(SUITE_DATASETS["open_all"]) + ext_docs
    if suite == "smoke":
        smoke_list = list(SUITE_DATASETS["smoke"])
        if ext_docs:
            smoke_list.append(ext_docs[0])
        return smoke_list
    return list(SUITE_DATASETS.get(suite, SUITE_DATASETS["open_all"]))


def main(cli_args: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="E-Buch Multi-Engine Benchmarking Suite")
    parser.add_argument(
        "--mode",
        choices=["fast", "ocr", "gemma", "smoke", "full"],
        default="fast",
        help=(
            "Execution profile: "
            "'fast' (default: Docling in-process + deterministic FIBS post-processing across open_all), "
            "'ocr' (Track A: all 3 OCR engines + deterministic FIBS post-processing with 0 LLM calls), "
            "'gemma' (Track B: single canonical engine + Gemma 4 12B standardisation & Judge reusing cached extractions), "
            "'smoke' (all 3 OCR engines + Gemma on a small smoke subset), "
            "'full' (all 3 OCR engines + Gemma + VLM image descriptions with checkpoints & batching)."
        ),
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        default=None,
        help="Engines to benchmark (defaults to ['docling'] in fast mode, or ['docling', 'lightonocr', 'infinity'] in smoke/full mode)",
    )
    parser.add_argument("--datasets", nargs="+", default=None, help="Specific test PDFs to evaluate")
    parser.add_argument(
        "--suite",
        choices=["smoke", "core", "schoolbooks", "open_all", "all", "external", "full"],
        default=None,
        help="Dataset suite (smoke, core=4 docs, schoolbooks=12 docs, open_all/all=19 open docs, external=50 publisher docs, full=all 69 docs)",
    )
    parser.add_argument("--include-scanned", action="store_true", help="Include rasterized scanned image PDFs in evaluation")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate extraction directories")
    parser.add_argument("--reuse-extractions", action="store_true", help="Reuse existing raw extracted .md files to re-evaluate parsing and standardisation quickly")
    parser.add_argument(
        "--external-data-dir",
        default=os.environ.get("EBUCH_TESTDATEN_DIR"),
        help="Path to external private publisher testdata repository (defaults to ../ebuch-testdaten if present)",
    )
    parser.add_argument("--checkpoint-file", default=None, help="Path to JSON checkpoint file for incremental resume across batches")
    parser.add_argument("--resume", action="store_true", help="Resume from latest run JSON / checkpoint file, skipping already completed (engine, doc) pairs")
    parser.add_argument("--batch-size", type=int, default=None, help="Number of documents to process in this batch")
    parser.add_argument("--batch-index", type=int, default=0, help="0-based batch index when running with --batch-size")
    parser.add_argument("--max-docs", type=int, default=None, help="Cap total documents evaluated in this invocation")
    parser.add_argument("--skip-standardisation", action="store_true", help="Skip LLM calls and evaluate fast deterministic post-processing only")
    parser.add_argument("--describe-images", action="store_true", help="Run Gemma 4 VLM image descriptions before text standardisation")
    parser.add_argument("--update-leaderboard-only", action="store_true", help="Refresh benchmarks/LEADERBOARD.md from existing saved run JSONs without running new extractions")
    args = parser.parse_args(cli_args)

    if args.update_leaderboard_only:
        ext_root = resolve_external_data_dir(args.external_data_dir)
        ext_runs = os.path.join(ext_root, "benchmarks", "runs") if ext_root else None
        tiers = _load_latest_runs_by_tier({}, external_runs_dir=ext_runs)
        latest = tiers.get("fast") or tiers.get("smoke") or tiers.get("open_multi_engine") or tiers.get("full_extended")
        if latest:
            update_leaderboard(latest, external_runs_dir=ext_runs)
        return latest or {}

    # Resolve defaults based on --mode when not explicitly overridden
    if args.engines is not None:
        engines = list(args.engines)
    elif args.mode in ("fast", "gemma"):
        engines = ["docling"]
    else:
        engines = ["docling", "lightonocr", "infinity"]

    if args.suite is not None:
        suite_name = args.suite
    elif args.mode in ("smoke", "ocr", "gemma"):
        suite_name = "smoke"
    elif args.mode == "full":
        suite_name = "full" if resolve_external_data_dir(args.external_data_dir) else "open_all"
    else:
        suite_name = "open_all"

    skip_std = args.skip_standardisation or (args.mode in ("fast", "ocr"))
    reuse_ext = args.reuse_extractions or (args.mode == "gemma")
    describe_imgs = args.describe_images or (args.mode == "full")

    datasets = (
        list(args.datasets)
        if args.datasets
        else resolve_suite_datasets(suite_name, external_data_dir=args.external_data_dir)
    )
    if args.include_scanned:
        ensure_scanned_pdfs()
        for ds in list(datasets):
            base = os.path.splitext(ds)[0]
            scanned_name = f"{base}_scanned.pdf"
            if os.path.exists(os.path.join(PROJECT_ROOT, "testdata", scanned_name)) and scanned_name not in datasets:
                datasets.append(scanned_name)

    return run_comprehensive_benchmark(
        engines=engines,
        datasets=datasets,
        keep_temp=args.keep_temp,
        reuse_extractions=reuse_ext,
        external_data_dir=args.external_data_dir,
        checkpoint_file=args.checkpoint_file,
        resume=args.resume,
        batch_size=args.batch_size,
        batch_index=args.batch_index,
        max_docs=args.max_docs,
        skip_standardisation=skip_std,
        describe_images=describe_imgs,
    )


if __name__ == "__main__":
    main()


