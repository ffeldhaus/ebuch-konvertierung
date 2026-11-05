"""Feedback Service – analyses user corrections of an E-Buch transfer ("Übertragung").

Workflow (all strictly offline / local):
  1. The user selects a finished job (or creates one from an MD/DOCX export),
     uploads the manually revised transfer, optional free-text feedback and
     optional PNG crops of source-PDF regions that were transferred incorrectly.
  2. This module computes a programmatic comparison between the original and
     revised transfer (diff hunks with very short snippets, category counts,
     accessibility linter deltas).
  3. Gemma 4 (local MLX weights, see ``feedback_analyzer.py``) first describes
     each marked region in an isolated prompt (no multi-image batching), then
     synthesises a detailed, pattern-oriented report for a coding assistant.
  4. A copyright guard (``redact_long_passages``) removes any longer verbatim
     passages from the report, because textbook content is usually protected.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from backend.services import fibs_constants as fc
from backend.services.models import DiffHunk, OpenQuestion
from backend.services.prompts import REGION_FINDINGS_PLACEHOLDER

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def load_transfer_document(path: str) -> str:
    """Load an E-Buch transfer from Markdown/Text or DOCX and return Markdown.

    Args:
        path: Filesystem path to a ``.md``, ``.txt``, or ``.docx`` transfer file.

    Returns:
        Extracted Markdown string.

    Raises:
        ValueError: If the file extension is not in ``TRANSFER_EXTENSIONS``.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in fc.TRANSFER_EXTENSIONS:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {ext}")
    if ext == ".docx":
        from backend.services.docx_service import extract_markdown_from_docx

        return extract_markdown_from_docx(path)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def load_feedback_document(path: str) -> str:
    """Load a free-form feedback document (``.txt``, ``.md``, ``.docx``, ``.pdf``) as plain text.

    Args:
        path: Filesystem path to the feedback document.

    Returns:
        Extracted plain-text or Markdown string.

    Raises:
        ValueError: If the file extension is not in ``FEEDBACK_EXTENSIONS``.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in fc.FEEDBACK_EXTENSIONS:
        raise ValueError(f"Nicht unterstütztes Feedback-Format: {ext}")
    if ext == ".pdf":
        import pypdfium2

        doc = pypdfium2.PdfDocument(path)
        try:
            return "\n\n".join(page.get_textpage().get_text_range() for page in doc).strip()
        finally:
            doc.close()
    return load_transfer_document(path)


# ---------------------------------------------------------------------------
# Change summary
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS = [
    ("heading", re.compile(r"^\s{0,3}#{1,6}\s")),
    ("page_marker", re.compile(r"\(\(\s*[\divxlcdmIVXLCDM]+\s*\)\)")),
    ("image", re.compile(r"</?Bild>|!\[[^\]]*\]\(")),
    ("list", re.compile(r"^\s*(?:[-*+•]|\d+[.)]|[a-z][.)])(?:\t|\s)")),
    ("math", re.compile(r"</?L>|\$[^$]+\$|\\\(|\\\[|\\frac|\^\{")),
    ("table", re.compile(r"</?Tabelle>|^\s*\|.*\|\s*$")),
    ("frame", re.compile(r"</?Rahmen>")),
    ("annotation", re.compile(r"</?Anmerkung>")),
    ("footnote", re.compile(r"\{\d+\}")),
    ("emphasis", re.compile(r"(?<![*\w])\*[^*\s][^*]*\*(?!\*)|%[^%\s][^%]*%|(?<!\w)_[^_\s][^_]*_(?!\w)")),
]


def classify_segment(text: str) -> list[str]:
    """Return the E-Buch structure categories present in a text segment.

    Args:
        text: Diff segment text to classify.

    Returns:
        Ordered list of detected category identifiers (defaults to ``["text"]`` or ``["whitespace"]``).
    """
    if not text.strip():
        return ["whitespace"]
    cats: list[str] = []
    for line in text.splitlines() or [text]:
        for name, pattern in _CATEGORY_PATTERNS:
            if name not in cats and pattern.search(line):
                cats.append(name)
    return cats or ["text"]


def _shorten(text: str, max_chars: int) -> str:
    r"""Collapse whitespace (tabs kept visible as ``\\t``) and truncate with an ellipsis.

    Args:
        text: Input string to shorten.
        max_chars: Maximum character length before truncation.

    Returns:
        Shortened single-line string.
    """
    clean = text.replace("\t", "\\t")
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "…"


def _select_representative_hunks(all_hunks: list[DiffHunk], max_hunks: int) -> list[DiffHunk]:
    """Select a stratified, representative subset of diff hunks in document order.

    Combines:
      1. Largest anomalous hunks by line delta (``removed_line_count + added_line_count``),
      2. At least one hunk per distinct category,
      3. Evenly spaced hunks across the entire document from start to end.

    Args:
        all_hunks: Complete list of non-empty ``DiffHunk`` instances in document order.
        max_hunks: Maximum number of hunks to return.

    Returns:
        Subset of at most ``max_hunks`` hunks sorted by ascending ``original_line``.
    """
    if max_hunks <= 0:
        return []
    if len(all_hunks) <= max_hunks:
        return all_hunks

    selected: set[int] = set()
    top_k = min(15, max(1, max_hunks // 3))
    by_size = sorted(
        range(len(all_hunks)),
        key=lambda idx: (-(all_hunks[idx].removed_line_count + all_hunks[idx].added_line_count), idx),
    )
    for idx in by_size[:top_k]:
        selected.add(idx)

    seen_cats: set[str] = {c for idx in selected for c in all_hunks[idx].categories}
    for idx in by_size:
        if len(selected) >= max_hunks:
            break
        new_cats = set(all_hunks[idx].categories) - seen_cats
        if new_cats:
            selected.add(idx)
            seen_cats.update(new_cats)

    remaining = [idx for idx in range(len(all_hunks)) if idx not in selected]
    needed = max_hunks - len(selected)
    if needed > 0 and remaining:
        if needed >= len(remaining):
            selected.update(remaining)
        elif needed == 1:
            selected.add(remaining[len(remaining) // 2])
        else:
            for step in range(needed):
                pos = int(round(step * (len(remaining) - 1) / (needed - 1)))
                selected.add(remaining[pos])
            if len(selected) < max_hunks:
                for idx in remaining:
                    if idx not in selected:
                        selected.add(idx)
                        if len(selected) >= max_hunks:
                            break

    return [all_hunks[idx] for idx in sorted(selected)[:max_hunks]]


def _compute_structural_anomalies(original: str, revised: str) -> tuple[list[str], dict[str, Any]]:
    """Compute full-document structural anomalies and element count deltas between transfers.

    Audits page markers (including heading-merged ``#### ((n))``, duplicates, and out-of-range
    pages), degenerate OCR/VLM repetition loops, heading hierarchy distributions, bullet
    subheadings, table resolutions, ``<Bild>`` blocks (including ``n. ü.``), and LaTeX math.

    Args:
        original: Automatic E-Buch transfer Markdown (``ALT``).
        revised: Human reference transfer Markdown (``NEU``).

    Returns:
        Tuple ``(structural_anomalies, page_summary)``.
    """
    anomalies: list[str] = []

    heading_merged_pages = [
        m.group(1).strip()
        for m in re.finditer(r"(?m)^[ \t]*#{1,6}[ \t]+\(\(([^)\n]+)\)\)", original)
    ]
    if heading_merged_pages:
        anomalies.append(
            f"Seitenmarker als Überschrift formatiert in ALT ({len(heading_merged_pages)}×, "
            f"z. B. `#### (({heading_merged_pages[0]}))`): Seitenmarker müssen freistehend als `((n))` ohne `#` stehen."
        )

    orig_pages = [m.strip() for m in re.findall(r"\(\(\s*(\d+|[IVXLCDMivxlcdm]+)\s*\)\)", original)]
    rev_pages = [m.strip() for m in re.findall(r"\(\(\s*(\d+|[IVXLCDMivxlcdm]+)\s*\)\)", revised)]
    orig_pg_counts = Counter(orig_pages)
    rev_pg_counts = Counter(rev_pages)

    dup_pages = [
        f"`(({p}))` ({c}×)"
        for p, c in orig_pg_counts.items()
        if c > max(1, rev_pg_counts.get(p, 0))
    ]
    if dup_pages:
        anomalies.append(f"Doppelte Seitenmarker in ALT: {', '.join(dup_pages[:8])}.")

    rev_pg_set = {p.lower() for p in rev_pages}
    orig_pg_set = {p.lower() for p in orig_pages}
    extra_pages = list(dict.fromkeys(p for p in orig_pages if p.lower() not in rev_pg_set))
    if extra_pages and rev_pages:
        anomalies.append(
            f"Überzählige Seitenmarker in ALT außerhalb des Zielbereichs von NEU: "
            f"{', '.join(f'`(({p}))`' for p in extra_pages[:8])} "
            f"(NEU umfasst `(({rev_pages[0]}))` bis `(({rev_pages[-1]}))`)."
        )
    missing_pages = list(dict.fromkeys(p for p in rev_pages if p.lower() not in orig_pg_set))
    if missing_pages:
        anomalies.append(
            f"Fehlende Seitenmarker in ALT (in NEU vorhanden): "
            f"{', '.join(f'`(({p}))`' for p in missing_pages[:8])}."
        )

    # Degenerate repetition loop audit (>= 15 consecutive short/repetitive non-empty lines in ALT)
    current_page = "?"
    run_items: list[tuple[int, str, str]] = []
    loops_found: list[tuple[int, int, int, str, str]] = []

    def _flush_run(items: list[tuple[int, str, str]]) -> None:
        if len(items) >= 15:
            sample = ", ".join(f"`{x[1]}`" for x in items[:3])
            loops_found.append((len(items), items[0][0], items[-1][0], items[0][2], sample))

    for ln_no, raw_ln in enumerate(original.splitlines(), 1):
        stripped = raw_ln.strip()
        if not stripped:
            continue
        m_pg = re.search(r"\(\(\s*(\d+|[IVXLCDMivxlcdm]+)\s*\)\)", stripped)
        if m_pg:
            current_page = m_pg.group(1)
        is_short_candidate = bool(re.match(r"^#{1,6}\s+\S{1,15}$", stripped)) or (
            len(stripped) <= 12
            and not re.match(r"^\(\([^)]+\)\)$", stripped)
            and not re.match(
                r"^</?(?:Bild|Tabelle|Rahmen|Anmerkung|Lückentext)\b",
                stripped,
                re.IGNORECASE,
            )
        )
        if is_short_candidate:
            run_items.append((ln_no, stripped, current_page))
        else:
            _flush_run(run_items)
            run_items = []
    _flush_run(run_items)

    for count, start_ln, end_ln, pg, sample in loops_found:
        anomalies.append(
            f"Degenerierte Wiederholungsschleife (OCR/VLM-Halluzination) in ALT: "
            f"{count} aufeinanderfolgende Kurzzeilen/Überschriften in Zeilen {start_ln}–{end_ln} "
            f"(ab Seite `(({pg}))`, z. B. {sample}), die in NEU nicht existieren."
        )

    orig_h = {
        f"H{lvl}": len(re.findall(rf"(?m)^[ \t]*#{{{lvl}}}[ \t]+\S", original))
        for lvl in range(1, 7)
    }
    rev_h = {
        f"H{lvl}": len(re.findall(rf"(?m)^[ \t]*#{{{lvl}}}[ \t]+\S", revised))
        for lvl in range(1, 7)
    }
    if orig_h != rev_h:
        orig_h_str = ", ".join(f"{k}={v}" for k, v in orig_h.items() if v) or "keine"
        rev_h_str = ", ".join(f"{k}={v}" for k, v in rev_h.items() if v) or "keine"
        anomalies.append(
            f"Überschriften-Hierarchie (ALT vs. NEU): ALT ({orig_h_str}) vs. NEU ({rev_h_str})."
        )

    orig_bullets = len(re.findall(r"(?m)^[ \t]*•[ \t]+", original))
    rev_bullets = len(re.findall(r"(?m)^[ \t]*•[ \t]+", revised))
    if orig_bullets != rev_bullets and (orig_bullets >= 2 or rev_bullets >= 2):
        anomalies.append(
            f"Spitzmarken/Aufzählungen mit `•` (ALT vs. NEU): ALT hat {orig_bullets} Zeilen mit `•`, "
            f"NEU hat {rev_bullets} (in NEU als Überschriften `####`/`#####` oder `-\\t`-Listen formatiert)."
        )

    orig_tabs = len(re.findall(r"<Tabelle\b", original, re.IGNORECASE))
    rev_tabs = len(re.findall(r"<Tabelle\b", revised, re.IGNORECASE))
    orig_res_tabs = len(re.findall(r"Tabelle wurde aufgelöst", original, re.IGNORECASE))
    rev_res_tabs = len(re.findall(r"Tabelle wurde aufgelöst", revised, re.IGNORECASE))
    if (orig_tabs, orig_res_tabs) != (rev_tabs, rev_res_tabs):
        anomalies.append(
            f"Tabellen-Bilanz (ALT vs. NEU): ALT hat {orig_tabs} `<Tabelle>`-Blöcke und "
            f"{orig_res_tabs} aufgelöste Tabellen; NEU hat {rev_tabs} `<Tabelle>`-Blöcke und "
            f"{rev_res_tabs} aufgelöste Tabellen."
        )

    orig_bild_blocks = re.findall(r"<Bild\b[^>]*>(.*?)</Bild>", original, re.DOTALL | re.IGNORECASE)
    rev_bild_blocks = re.findall(r"<Bild\b[^>]*>(.*?)</Bild>", revised, re.DOTALL | re.IGNORECASE)
    orig_nue = sum(
        1 for b in orig_bild_blocks if re.search(r"\bn\.\s*ü\.|\bnicht übertragen\b", b, re.IGNORECASE)
    )
    rev_nue = sum(
        1 for b in rev_bild_blocks if re.search(r"\bn\.\s*ü\.|\bnicht übertragen\b", b, re.IGNORECASE)
    )
    if (len(orig_bild_blocks), orig_nue) != (len(rev_bild_blocks), rev_nue):
        anomalies.append(
            f"Bildblöcke `<Bild>` (ALT vs. NEU): ALT hat {len(orig_bild_blocks)} `<Bild>`-Blöcke "
            f"(davon {orig_nue}× `n. ü.`); NEU hat {len(rev_bild_blocks)} `<Bild>`-Blöcke "
            f"(davon {rev_nue}× `n. ü.`)."
        )

    orig_latex = len(re.findall(r"\$+[^$\n]+\$+", original))
    rev_latex = len(re.findall(r"\$+[^$\n]+\$+", revised))
    if orig_latex != rev_latex and abs(orig_latex - rev_latex) >= 2:
        anomalies.append(
            f"Formel-Notation (ALT vs. NEU): ALT nutzt {orig_latex}× LaTeX `$...$`, "
            f"NEU nutzt {rev_latex}× LaTeX `$...$` (NEU bevorzugt direkte FIBS-Inline-Schreibweise "
            f"wie `^`, `_`, `\\to`, `\\xra` ohne `$`)."
        )

    page_summary: dict[str, Any] = {
        "pages_original": orig_pages,
        "pages_revised": rev_pages,
        "heading_merged_pages_original": heading_merged_pages,
        "extra_pages_original": extra_pages,
        "missing_pages_original": missing_pages,
        "headings_original": {k: v for k, v in orig_h.items() if v},
        "headings_revised": {k: v for k, v in rev_h.items() if v},
        "tables_original": orig_tabs,
        "tables_revised": rev_tabs,
        "resolved_tables_original": orig_res_tabs,
        "resolved_tables_revised": rev_res_tabs,
        "images_original": len(orig_bild_blocks),
        "images_revised": len(rev_bild_blocks),
        "images_nue_original": orig_nue,
        "images_nue_revised": rev_nue,
        "latex_blocks_original": orig_latex,
        "latex_blocks_revised": rev_latex,
    }
    return anomalies, page_summary


def compute_change_summary(
    original: str,
    revised: str,
    max_hunks: int = 60,
    snippet_chars: int = 100,
    max_lines_per_side: int = 4,
) -> dict[str, Any]:
    """Compute a line-based diff summary between original and revised transfers.

    Only very short snippets (``snippet_chars``) and at most ``max_lines_per_side``
    lines per hunk side are retained so that the result can be sent to the LLM
    and shown in the report without reproducing protected textbook passages.
    When more than ``max_hunks`` hunks exist, a stratified representative sample
    covering the largest line-delta anomalies, all categories, and the full
    document span is selected.

    Args:
        original: Automatic E-Buch transfer Markdown.
        revised: Manually corrected E-Buch transfer Markdown.
        max_hunks: Maximum number of diff hunks to retain in the summary list.
        snippet_chars: Maximum characters per snippet line.
        max_lines_per_side: Maximum lines per hunk side.

    Returns:
        Dictionary with similarity ratio, hunk counts, categorized hunks, line deltas,
        ``structural_anomalies``, and ``page_summary``.
    """
    orig_lines = original.splitlines()
    rev_lines = revised.splitlines()
    matcher = difflib.SequenceMatcher(None, orig_lines, rev_lines, autojunk=False)

    all_hunks: list[DiffHunk] = []
    category_counts: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    lines_added = lines_removed = 0
    total_hunks = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = orig_lines[i1:i2]
        added = rev_lines[j1:j2]
        removed_text = "\n".join(removed)
        added_text = "\n".join(added)
        if not removed_text.strip() and not added_text.strip():
            continue
        total_hunks += 1
        lines_removed += len(removed)
        lines_added += len(added)

        cats_removed = classify_segment(removed_text) if removed else []
        cats_added = classify_segment(added_text) if added else []
        categories = sorted(set(cats_removed) | set(cats_added))
        category_counts.update(categories)
        if cats_removed and cats_added and cats_removed != cats_added:
            transitions[f"{'+'.join(cats_removed)} → {'+'.join(cats_added)}"] += 1

        all_hunks.append(
            DiffHunk(
                op=tag,
                original_line=i1 + 1,
                revised_line=j1 + 1,
                removed=[_shorten(ln, snippet_chars) for ln in removed[:max_lines_per_side] if ln.strip()],
                added=[_shorten(ln, snippet_chars) for ln in added[:max_lines_per_side] if ln.strip()],
                removed_line_count=len(removed),
                added_line_count=len(added),
                categories=categories,
            )
        )

    hunks = _select_representative_hunks(all_hunks, max_hunks)
    structural_anomalies, page_summary = _compute_structural_anomalies(original, revised)

    return {
        "similarity": round(matcher.ratio(), 4),
        "hunk_count": total_hunks,
        "hunks": hunks,
        "truncated": total_hunks > len(hunks),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "category_counts": dict(category_counts),
        "category_transitions": dict(transitions.most_common(15)),
        "original_line_count": len(orig_lines),
        "revised_line_count": len(rev_lines),
        "structural_anomalies": structural_anomalies,
        "page_summary": page_summary,
    }


def compare_lint_reports(original: str, revised: str) -> dict[str, Any]:
    """Compare E-Buch accessibility linter results of original vs. revised transfer.

    Args:
        original: Automatic E-Buch transfer Markdown.
        revised: Manually corrected E-Buch transfer Markdown.

    Returns:
        Dictionary containing original/revised scores and fixed/introduced rule counts.
    """
    from backend.services.a11y_linter import lint_markdown

    rep_o = lint_markdown(original)
    rep_r = lint_markdown(revised)
    rules_o = Counter(i.rule for i in rep_o.issues)
    rules_r = Counter(i.rule for i in rep_r.issues)
    fixed = {rule: cnt - rules_r.get(rule, 0) for rule, cnt in rules_o.items() if cnt > rules_r.get(rule, 0)}
    introduced = {rule: cnt - rules_o.get(rule, 0) for rule, cnt in rules_r.items() if cnt > rules_o.get(rule, 0)}
    return {
        "score_original": rep_o.score,
        "score_revised": rep_r.score,
        "rules_original": dict(rules_o),
        "rules_revised": dict(rules_r),
        "rules_fixed_in_revision": fixed,
        "rules_introduced_in_revision": introduced,
    }


# ---------------------------------------------------------------------------
# Copyright guard
# ---------------------------------------------------------------------------

_WORD_STRIP = re.compile(r"^[^\wÄÖÜäöüß]+|[^\wÄÖÜäöüß]+$")


def _normalize_word(token: str) -> str:
    """Normalize a word token for case- and punctuation-insensitive n-gram matching."""
    return _WORD_STRIP.sub("", token).lower()


def redact_long_passages(report: str, sources: Iterable[str], max_words: int = fc.MAX_VERBATIM_WORDS) -> str:
    """Replace verbatim runs of ``max_words`` or more words from ``sources`` with ``[…]``.

    Comparison is case-insensitive and ignores surrounding punctuation, so copied
    passages are detected even when quoted or re-punctuated.

    Args:
        report: Generated Markdown report to sanitize.
        sources: Iterable of protected source texts to check against.
        max_words: Maximum allowed consecutive verbatim words.

    Returns:
        Redacted report string.
    """
    source_list = [s for s in sources if s]
    if not source_list or max_words < 2:
        return report

    ngrams: set[tuple[str, ...]] = set()
    for src in source_list:
        words = [w for w in (_normalize_word(t) for t in src.split()) if w]
        for i in range(len(words) - max_words + 1):
            ngrams.add(tuple(words[i : i + max_words]))
    if not ngrams:
        return report

    tokens = [(m.start(), m.end(), _normalize_word(m.group())) for m in re.finditer(r"\S+", report)]
    word_idx = [k for k, t in enumerate(tokens) if t[2]]
    covered = [False] * len(tokens)
    for i in range(len(word_idx) - max_words + 1):
        window = tuple(tokens[word_idx[i + k]][2] for k in range(max_words))
        if window in ngrams:
            for k in range(max_words):
                covered[word_idx[i + k]] = True

    runs: list[tuple[int, int]] = []
    k = 0
    while k < len(tokens):
        if covered[k]:
            start = k
            while k + 1 < len(tokens) and covered[k + 1]:
                k += 1
            runs.append((start, k))
        k += 1

    keep_words = 4
    result = report
    for start, end in reversed(runs):
        span_start = tokens[start][0]
        span_end = tokens[end][1]
        kept = " ".join(
            report[tokens[t][0] : tokens[t][1]] for t in range(start, min(start + keep_words, end + 1))
        )
        result = result[:span_start] + f"{kept} […]" + result[span_end:]
    return result


# ---------------------------------------------------------------------------
# Deterministic report parts
# ---------------------------------------------------------------------------


def build_statistics_appendix(
    change_summary: dict[str, Any],
    lint_comparison: dict[str, Any],
    task_meta: dict[str, Any],
) -> str:
    """Build the programmatic statistics appendix attached to every feedback report.

    Args:
        change_summary: Output of ``compute_change_summary``.
        lint_comparison: Output of ``compare_lint_reports``.
        task_meta: Metadata dictionary describing the conversion job.

    Returns:
        Markdown string for the statistics appendix.
    """
    rows = (
        "\n".join(
            f"| {fc.CATEGORY_LABELS.get(c, c)} (`{c}`) | {n} |"
            for c, n in sorted(change_summary["category_counts"].items(), key=lambda x: -x[1])
        )
        or "| – | 0 |"
    )
    meta_rows = "\n".join(f"| {k} | {v} |" for k, v in task_meta.items() if v not in (None, ""))
    fixed = ", ".join(f"`{r}` ({n})" for r, n in lint_comparison["rules_fixed_in_revision"].items()) or "–"
    introduced = (
        ", ".join(f"`{r}` ({n})" for r, n in lint_comparison["rules_introduced_in_revision"].items()) or "–"
    )
    std_backend = str(
        task_meta.get("Standardisierungs-Backend")
        or task_meta.get("Standardisierung")
        or task_meta.get("standardisation_backend")
        or ""
    ).lower()
    fallback_warning = ""
    if "fallback" in std_backend or "regelbasier" in std_backend:
        fallback_warning = (
            "\n> [!WARNING]\n"
            "> Die automatische Übertragung dieses Auftrags stammt aus der **regelbasierten Ersatzlösung** "
            "(`rule_based_fallback`, ohne Gemma-Standardisierung). Viele Abweichungen sind darauf zurückzuführen, "
            "dass der LLM-Server während der Übertragung nicht verfügbar war.\n"
        )
    anomalies = change_summary.get("structural_anomalies") or []
    anomalies_block = ""
    if anomalies:
        bullet_lines = "\n".join(f"- {a}" for a in anomalies)
        anomalies_block = f"\n### Automatisch erkannte Struktur-Anomalien & Mengenvergleiche\n{bullet_lines}\n"
    return f"""
---

## Anhang: Automatisch ermittelte Kennzahlen
{fallback_warning}
| Auftrag | Wert |
| :--- | :--- |
{meta_rows}

| Kennzahl | Wert |
| :--- | :--- |
| Ähnlichkeit (Original ↔ Korrektur) | {change_summary['similarity']:.1%} |
| Änderungsblöcke | {change_summary['hunk_count']} |
| Zeilen hinzugefügt / entfernt | +{change_summary['lines_added']} / -{change_summary['lines_removed']} |
| Linter-Score Original → Korrektur | {lint_comparison['score_original']} → {lint_comparison['score_revised']} |
| Durch Korrektur behobene Linter-Regeln | {fixed} |
| In Korrektur neu auftretende Linter-Regeln | {introduced} |
{anomalies_block}
| Kategorie | Änderungen |
| :--- | :--- |
{rows}
"""


def generate_mock_report(
    change_summary: dict[str, Any],
    feedback_text: str,
    region_findings: list[str],
) -> str:
    """Generate a deterministic report used in ``E2E_MOCK`` mode or when Gemma is unavailable.

    Follows the exact section structure requested by ``build_analysis_prompt``.

    Args:
        change_summary: Output of ``compute_change_summary``.
        feedback_text: Optional user free-text feedback.
        region_findings: List of per-region visual findings.

    Returns:
        Structured Markdown feedback report.
    """
    top = sorted(change_summary["category_counts"].items(), key=lambda x: -x[1])[:5]
    patterns, overview, test_rows = [], [], []
    for n, (cat, cnt) in enumerate(top, 1):
        label = fc.CATEGORY_LABELS.get(cat, cat)
        example = next((h for h in change_summary["hunks"] if cat in h.categories), None)
        ex_old = _shorten(example.removed[0], 40) if example and example.removed else "–"
        ex_new = _shorten(example.added[0], 40) if example and example.added else "–"
        priority = "hoch" if n == 1 else ("mittel" if n <= 3 else "niedrig")
        overview.append(f"| {n} | {label} | `{cat}` | zu prüfen | {cnt} | {priority} | Nachbearbeitung (zu prüfen) |")
        test_rows.append(
            f"| {label}: Regression | Unit-Test-Snippet | synthetisches Markdown mit `{cat}`-Elementen | "
            f"korrigierte E-Buch-Syntax | Muster {n} |"
        )
        patterns.append(
            f"### Muster {n}: {label}\n"
            f"- **Kategorie:** `{cat}`\n"
            f"- **Häufigkeit:** {cnt} Änderungsblöcke\n"
            f"- **Beispiel:** `{ex_old}` → `{ex_new}`\n"
            f"- **Wahrscheinliche Ursache / Pipeline-Stufe:** Nachbearbeitung bzw. Standardisierung (automatische Heuristik)\n"
            f"- **Lösungsvorschlag:** Generische Regel für `{cat}` in `post_process_structure` prüfen und Regressionstest ergänzen.\n"
            f"- **Benötigte Testdaten:** Synthetisches Markdown-Snippet mit `{cat}`-Elementen (ALT → erwartet); "
            f"für E2E eine OER-PDF-Seite mit vergleichbarem Layout (siehe testdata/ATTRIBUTIONS.md)."
        )
    regions = "\n".join(f"- Stelle {i}: {_shorten(f, 160)}" for i, f in enumerate(region_findings, 1)) or "- keine"
    fb = _shorten(feedback_text, 200) if feedback_text else "kein Feedback"
    questions = []
    if top:
        questions.append(
            f"Ist die häufigste Korrektur ({fc.CATEGORY_LABELS.get(top[0][0], top[0][0])}) durch eine "
            "Übertragungsregel gedeckt oder eine Stilpräferenz?"
        )
    questions += [
        f"Welche Übertragungsregel gilt für die markierte Stelle {i}?" for i in range(1, len(region_findings) + 1)
    ]
    if not questions:
        questions.append("Gibt es Korrekturen, die nicht durch die Übertragungsregeln gedeckt sind?")
    question_list = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    overview_table = (
        (
            "| # | Muster | Kategorie | Typ (Fehler/Stil) | Häufigkeit | Priorität | Pipeline-Stufe |\n"
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n" + "\n".join(overview)
        )
        if overview
        else "Keine Unterschiede gefunden."
    )
    test_table = (
        (
            "| Testfall | Art | Erforderliche Merkmale | Erwartete Ausgabe | Prüft Muster |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n" + "\n".join(test_rows)
        )
        if test_rows
        else "Keine zusätzlichen Testdaten erforderlich."
    )
    return (
        "## Zusammenfassung\n"
        f"Automatische Heuristik-Auswertung (ohne Gemma). {change_summary['hunk_count']} Änderungsblöcke, "
        f"Ähnlichkeit {change_summary['similarity']:.1%}. Nutzer-Feedback: {fb}\n\n"
        f"Markierte Stellen:\n{regions}\n\n"
        f"## Übersicht\n{overview_table}\n\n"
        "## Fehlermuster\n" + ("\n\n".join(patterns) or "Keine Unterschiede gefunden.") + "\n\n"
        "## Maßnahmen für den Coding Assistant\n"
        "1. Häufigste Kategorien oben generisch in der Nachbearbeitung behandeln.\n"
        "2. Für jedes Muster einen pytest-Regressionstest mit synthetischem Beispiel ergänzen.\n\n"
        f"## Benötigte Testdaten\n{test_table}\n\n"
        "## Offene Fragen\n"
        f"{question_list}\n"
    )


# ---------------------------------------------------------------------------
# Open questions ("## Offene Fragen"): parse, answer, write back
# ---------------------------------------------------------------------------

_OPEN_Q_HEADING = re.compile(r"^#{2,3}\s*(?:\d+[.)]\s*)?Offene Fragen\b.*$", re.IGNORECASE)
_SECTION_END = re.compile(r"^(#{1,2}\s|-{3,}\s*$)")
_Q_ITEM = re.compile(r"^([ \t]*)(?:[-*+•]|\d+[.)])\s+(.*)$")
_ANSWER_LINE = re.compile(r"^\s*(?:[-*+]\s+)?\*\*Antwort:?\*\*:?\s*(.*)$")
_NO_QUESTIONS = re.compile(r"^(keine|–|-|n/a)(\s+offenen?\s+fragen)?[.!]?$", re.IGNORECASE)


def _open_questions_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(heading_index, end_index_exclusive)`` of the ``Offene Fragen`` section, or ``None``."""
    start = None
    for i, line in enumerate(lines):
        if start is None:
            if _OPEN_Q_HEADING.match(line.strip()):
                start = i
        elif _SECTION_END.match(line):
            return start, i
    return (start, len(lines)) if start is not None else None


def extract_open_questions(report: str) -> list[OpenQuestion]:
    """Parse the ``## Offene Fragen`` section into ``OpenQuestion`` objects.

    * Top-level list items (``-``, ``*``, ``1.``) are questions; indented plain
      lines continue the previous question.
    * Nested ``**Antwort:**`` lines (written by ``apply_question_answers``) are
      parsed back as answers; skipped questions yield ``None``.
    * Without list items, plain lines ending in ``?`` are used.
    * Placeholders like ``Keine`` are ignored.

    Args:
        report: Markdown feedback report text.

    Returns:
        List of ``OpenQuestion`` Pydantic models.
    """
    lines = report.split("\n")
    bounds = _open_questions_bounds(lines)
    if not bounds:
        return []
    items: list[OpenQuestion] = []
    plain: list[str] = []
    current: OpenQuestion | None = None
    for raw in lines[bounds[0] + 1 : bounds[1]]:
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _ANSWER_LINE.match(line)
        if m and current is not None:
            ans = m.group(1).strip()
            current.answer = None if not ans or ans == fc.SKIPPED_ANSWER else ans
            continue
        m = _Q_ITEM.match(line)
        if m and len(m.group(1).replace("\t", "    ")) <= 3:
            current = OpenQuestion(question=m.group(2).strip(), answer=None)
            items.append(current)
            continue
        if current is not None and raw[:1].isspace():
            current.question = f"{current.question} {line.strip()}"
            continue
        current = None
        plain.append(line.strip())
    if not items:
        items = [OpenQuestion(question=p, answer=None) for p in plain if p.endswith("?")]
    return [q for q in items if q.question and not _NO_QUESTIONS.match(q.question.strip("* ").strip())]


def apply_question_answers(report: str, answers: list[str | None]) -> str:
    """Rewrite the ``## Offene Fragen`` section with the user's answers.

    Args:
        report: Markdown feedback report containing an ``## Offene Fragen`` section.
        answers: List of user answers (one per parsed question; ``None`` or empty means skipped).

    Returns:
        Updated Markdown report with embedded ``- **Antwort:**`` lines.

    Raises:
        ValueError: If the report has no open questions or ``len(answers)`` mismatches.
    """
    lines = report.split("\n")
    bounds = _open_questions_bounds(lines)
    questions = extract_open_questions(report)
    if not bounds or not questions:
        raise ValueError("Der Bericht enthält keine offenen Fragen.")
    if len(answers) != len(questions):
        raise ValueError(f"Erwartet {len(questions)} Antworten, erhalten {len(answers)}.")
    body = []
    for i, (q, a) in enumerate(zip(questions, answers), 1):
        text = " ".join((a or "").split())[:fc.MAX_ANSWER_CHARS]
        body.append(f"{i}. {q.question}")
        body.append(f"   - **Antwort:** {text or fc.SKIPPED_ANSWER}")
    new_lines = lines[: bounds[0] + 1] + [""] + body + [""] + lines[bounds[1] :]
    return "\n".join(new_lines)


# ---------------------------------------------------------------------------
# Deterministic report post-processing (readability)
# ---------------------------------------------------------------------------

_LATEX_ARROWS = [
    (re.compile(r"\$\s*\\(?:to|rightarrow|longrightarrow|Rightarrow|Longrightarrow)\s*\$"), "→"),
    (re.compile(r"\$\s*\\(?:leftarrow|longleftarrow|Leftarrow)\s*\$"), "←"),
    (re.compile(r"\$\s*\\(?:leftrightarrow|Leftrightarrow)\s*\$"), "↔"),
]
_FIELD_LINE = re.compile(r"^(\s*)(?:[-*+]\s+)?\*\*([^*\n]{1,60}?)\s*(:?)\*\*\s*(:?)\s*(.*)$")


def normalize_report_markdown(report: str) -> str:
    r"""Repair common formatting slips of the model so the report renders cleanly.

    * ``**Feld**: Wert`` lines become bullet points ``- **Feld:** Wert``.
    * Inline-LaTeX arrows (``$\\to$``) in prose become Unicode arrows (``→``).
    * Code fences and tables are left untouched.

    Args:
        report: Raw Markdown report string.

    Returns:
        Normalized Markdown report string.
    """
    out = []
    in_code = False
    for line in report.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        for pattern, repl in _LATEX_ARROWS:
            line = pattern.sub(repl, line)
        m = _FIELD_LINE.match(line)
        if m and (m.group(3) or m.group(4)):
            indent, label, rest = m.group(1), m.group(2).strip(), m.group(5)
            line = f"{indent}- **{label}:** {rest}".rstrip()
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Gemma execution (subprocess, sequential & memory-safe)
# ---------------------------------------------------------------------------

ANALYZER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback_analyzer.py")

AnalyzerEventCallback = Callable[[str, dict[str, Any]], None]

_PROGRESS_RE = re.compile(r"^\[PROGRESS\]\s+(\d+)/(\d+)\s*(.*)$")
_SECTION_RE = re.compile(r"^\[SECTION\]\s+(\w+)(?:\s+(\d+))?\s*$")


def parse_analyzer_line(line: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one stderr protocol line emitted by ``feedback_analyzer.py``.

    Args:
        line: Raw stderr line from the analyzer subprocess.

    Returns:
        A tuple ``(event_kind, payload_dict)`` where ``event_kind`` is one of
        ``"progress"``, ``"section"``, ``"token"``, or ``"log"``, or ``None`` for blank lines.
    """
    text = line.rstrip("\r\n")
    if text.startswith("[TOKEN] "):
        try:
            delta = json.loads(text[len("[TOKEN] ") :])
            if isinstance(delta, str):
                return "token", {"delta": delta}
        except json.JSONDecodeError:
            pass
        return "log", {"message": text.strip()}
    text = text.strip()
    if not text:
        return None
    m = _PROGRESS_RE.match(text)
    if m:
        return "progress", {"step": int(m.group(1)), "total": int(m.group(2)), "label": m.group(3)}
    m = _SECTION_RE.match(text)
    if m:
        return "section", {"section": m.group(1), "index": int(m.group(2)) if m.group(2) else None}
    return "log", {"message": text}


async def run_gemma_feedback_analysis(
    final_prompt: str,
    regions: list[dict[str, Any]],
    work_dir: str,
    on_event: AnalyzerEventCallback | None = None,
) -> dict[str, Any]:
    """Run ``feedback_analyzer.py`` in an isolated subprocess and stream events.

    Args:
        final_prompt: Final synthesis prompt containing ``REGION_FINDINGS_PLACEHOLDER``.
        regions: List of ``{"path": str, "prompt": str}`` dicts processed sequentially.
        work_dir: Temporary working directory for IPC JSON files.
        on_event: Optional callback invoked for each parsed stderr event.

    Returns:
        Dictionary ``{"region_findings": List[str], "report": str}``.
    """
    import asyncio
    import sys

    input_json = os.path.join(work_dir, "analyzer_input.json")
    output_json = os.path.join(work_dir, "analyzer_output.json")
    with open(input_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "final_prompt": final_prompt,
                "regions": regions,
                "placeholder": REGION_FINDINGS_PLACEHOLDER,
            },
            f,
            ensure_ascii=False,
        )

    proc = await asyncio.create_subprocess_exec(
        sys.executable or "python",
        ANALYZER_SCRIPT,
        "--input-json",
        input_json,
        "--output-json",
        output_json,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,
    )
    assert proc.stderr is not None
    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        parsed = parse_analyzer_line(line.decode("utf-8", errors="ignore"))
        if not parsed:
            continue
        kind, data = parsed
        if kind == "log":
            logger.info("[Gemma Feedback] %s", data["message"])
        if on_event:
            try:
                on_event(kind, data)
            except Exception as ex:
                logger.warning("Feedback event listener failed: %s", ex)
    await proc.wait()
    if proc.returncode not in (0, None) and on_event:
        on_event("log", {"message": f"Gemma-Prozess beendet mit Code {proc.returncode}"})

    result: dict[str, Any] = {"region_findings": [], "report": ""}
    if os.path.exists(output_json):
        try:
            with open(output_json, encoding="utf-8") as f:
                result.update(json.load(f))
        except Exception as ex:
            logger.error("Failed to read feedback analyzer output: %s", ex)
    for p in (input_json, output_json):
        try:
            os.remove(p)
        except OSError:
            pass
    return result
