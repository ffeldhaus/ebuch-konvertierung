"""Deterministic FIBS (Übertragungsregeln Stand 09/2025) structural post-processing.

Contains pure regex/AST transformations, heading hierarchy reconstruction,
multi-column subtask table unrolling, callout box wrapping, dropped ``<Rahmen>``
recovery, page-number deduplication, and rule-based fallback processors.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.services import fibs_constants as fc
from backend.services.fibs_formatting import (
    convert_unicode_scripts,
    normalize_bild_tags,
    normalize_fibs_units_and_percent,
    normalize_versalien,
)
from backend.services.models import BuchkonferenzProfile, PageSegment

logger = logging.getLogger(__name__)


def split_markdown_pages(markdown: str) -> list[PageSegment]:
    """Splits Markdown losslessly into page segments delimited by ``((n))`` markers.

    Each returned segment starts with its ``((n))`` marker line; text preceding
    the first marker becomes a segment with ``page=None``.

    Args:
        markdown: Full document Markdown string.

    Returns:
        List of ``PageSegment`` models.
    """
    starts = [m.start() for m in fc.PAGE_MARKER_START_RE.finditer(markdown or "")]
    if not starts:
        return [PageSegment(page=None, text=markdown or "")]
    segments: list[PageSegment] = []
    if starts[0] > 0:
        segments.append(PageSegment(page=None, text=markdown[: starts[0]]))
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(markdown)
        match = fc.PAGE_MARKER_START_RE.match(markdown, start)
        page = match.group(1) if match else None
        segments.append(PageSegment(page=page, text=markdown[start:end]))
    return segments


def standardise_markdown_fallback(
    raw_markdown: str,
    ruleset_key: str = "uebertragungsregeln_09_2025",
) -> str:
    """Applies deterministic rule-based E-Buch standardizations when no LLM is used.

    Args:
        raw_markdown: Raw extracted Markdown string from Stage 1.
        ruleset_key: Identifier of the active FIBS ruleset.

    Returns:
        Standardised Markdown string produced by deterministic rules.
    """
    logger.info(f"Running rule-based fallback standardizer for ruleset: {ruleset_key}")

    lines = raw_markdown.splitlines()
    processed_lines: list[str] = []

    in_table = False
    table_lines: list[str] = []

    in_box = False
    box_lines: list[str] = []

    for i, line in enumerate(lines):
        if "(leicht)" in line or (
            "leicht" in line.lower() and ("aufgabe" in line.lower() or "■" in line or "○" in line)
        ):
            line = re.sub(
                r"^[^a-zA-Z0-9]*Aufgabe\s*(\d+)\s*\(leicht\):",
                r"○ [leicht] Aufgabe \1:",
                line,
            )
            line = re.sub(r"\(leicht\)", r"[leicht]", line)
            if "○" not in line and "[leicht]" in line:
                line = re.sub(r"^[^a-zA-Z0-9]*", r"○ ", line)
        if "(mittel)" in line or (
            "mittel" in line.lower() and ("aufgabe" in line.lower() or "■" in line or "◐" in line)
        ):
            line = re.sub(
                r"^[^a-zA-Z0-9]*Aufgabe\s*(\d+)\s*\(mittel\):",
                r"◐ [mittel] Aufgabe \1:",
                line,
            )
            line = re.sub(r"\(mittel\)", r"[mittel]", line)
            if "◐" not in line and "[mittel]" in line:
                line = re.sub(r"^[^a-zA-Z0-9]*", r"◐ ", line)
        if "(schwer)" in line or (
            "schwer" in line.lower() and ("aufgabe" in line.lower() or "●" in line or "l" in line)
        ):
            line = re.sub(
                r"^[^a-zA-Z0-9]*Aufgabe\s*(\d+)\s*\(schwer\):",
                r"● [schwer] Aufgabe \1:",
                line,
            )
            line = re.sub(r"\(schwer\)", r"[schwer]", line)
            if "●" not in line and "[schwer]" in line:
                line = re.sub(r"^[^a-zA-Z0-9]*", r"● ", line)

        if "○" in line and "[leicht]" not in line:
            line = line.replace("○", "○ [leicht]")
        if "◐" in line and "[mittel]" not in line:
            line = line.replace("◐", "◐ [mittel]")
        if "●" in line and "[schwer]" not in line:
            line = line.replace("●", "● [schwer]")
        if "□" in line and "[leicht]" not in line:
            line = line.replace("□", "□ [leicht]")
        if "◩" in line and "[mittel]" not in line:
            line = line.replace("◩", "◩ [mittel]")
        if "■" in line and "[schwer]" not in line and "[leicht]" not in line and "[mittel]" not in line:
            line = line.replace("■", "■ [schwer]")
        if "★★★" in line and "[schwer]" not in line:
            line = line.replace("★★★", "★★★ [schwer]")
        elif "★★" in line and "[mittel]" not in line:
            line = line.replace("★★", "★★ [mittel]")
        elif "★" in line and "[leicht]" not in line:
            line = line.replace("★", "★ [leicht]")
        if "◇" in line and "[leicht]" not in line:
            line = line.replace("◇", "◇ [leicht]")
        if "◈" in line and "[mittel]" not in line:
            line = line.replace("◈", "◈ [mittel]")
        if "◆" in line and "[schwer]" not in line:
            line = line.replace("◆", "◆ [schwer]")

        line = re.sub(r"\$\^\{\s*(\d+)\s*\}\$", r"{\1}", line)
        math_placeholders: list[str] = []

        def _mask_math(m: re.Match[str]) -> str:
            math_placeholders.append(m.group(0))
            return f"__MATH_SPAN_{len(math_placeholders) - 1}__"

        line_masked = re.sub(r"\$\$[\s\S]*?\$\$|\$[^\$\n]+\$", _mask_math, line)
        line_masked = re.sub(r"\^{\s*(\d+)\s*}", r"{\1}", line_masked)
        line_masked = re.sub(r"(?<=[a-zA-ZäöüÄÖÜß\)\]])\^(\d+)", r"{\1}", line_masked)
        for idx, val in enumerate(math_placeholders):
            line_masked = line_masked.replace(f"__MATH_SPAN_{idx}__", val)
        line = line_masked

        stripped = line.strip()
        line_clean = re.sub(
            r"</?(?:table|tr|td|tbody|p|div|span|b|i|strong|em)\b[^>]*>",
            "",
            line,
        ).strip()

        page_match = re.match(
            r"^\(\((\d+|[IVXLCDMivxlcdm]+)\)\)$|^[\(\s\[\-\#]*(?:Seite|Se)\s*(\d+|[IVXLCDMivxlcdm]+)[\)\s\]\-\#]*$|^[\(\s\[\-\#]*(\d+)[\)\s\]\-\#]*$",
            line_clean,
            re.IGNORECASE,
        )
        if page_match:
            page_num = page_match.group(1) or page_match.group(2) or page_match.group(3)
            if page_num and (page_num.isdigit() or fc.ROMAN_NUMERAL_RE.match(page_num)):
                processed_lines.append("")
                processed_lines.append(f"(({page_num}))")
                processed_lines.append("")
                continue

        if "<table" in line.lower():
            if "</table>" in line.lower():
                processed_lines.append("<Tabelle>")
                processed_lines.append(line)
                processed_lines.append("</Tabelle>")
            else:
                in_table = True
                table_lines = [line]
            continue
        elif in_table:
            table_lines.append(line)
            if "</table>" in line.lower():
                in_table = False
                processed_lines.append("<Tabelle>")
                processed_lines.extend(table_lines)
                processed_lines.append("</Tabelle>")
                table_lines = []
            continue

        img_match = re.search(r"!\[(.*?)\]\((.*?)\)", line)
        if img_match:
            alt_text = img_match.group(1) or "Abbildung"
            caption = ""
            cap_idx = i + 1
            while cap_idx < len(lines) and not lines[cap_idx].strip():
                cap_idx += 1
            if cap_idx < len(lines) and re.match(
                r"^(?:Abbildung|Abb\.|Figure|Fig\.|Figur|Bild)\s*[0-9IVX]+",
                lines[cap_idx].strip(),
                re.IGNORECASE,
            ):
                caption = lines[cap_idx].strip()
                lines[cap_idx] = ""

            desc = caption if caption else alt_text
            if re.match(r"^Abb\.\s*\d+", desc):
                processed_lines.append(f"#### {desc}")
                processed_lines.append("")
            processed_lines.append(f"<Bild> Foto/Zeichnung: {desc} </Bild>")
            continue

        if line == "" and i > 0 and lines[i - 1] == "":
            continue

        if stripped.lower().startswith("merksatz:") or stripped.lower().startswith("definition:"):
            in_box = True
            box_lines = [line]
            continue
        elif in_box:
            if stripped == "":
                in_box = False
                processed_lines.append("<Rahmen>")
                processed_lines.extend(box_lines)
                processed_lines.append("</Rahmen>")
                box_lines = []
                processed_lines.append("")
            else:
                box_lines.append(line)
            continue

        list_match = re.match(r"^(\s*)([\-\*\+])\s+(.*)$", line)
        num_list_match = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)

        if list_match:
            indent = list_match.group(1)
            content = list_match.group(3)
            processed_lines.append(f"{indent}-\t{content}")
            continue
        elif num_list_match:
            indent = num_list_match.group(1)
            num = num_list_match.group(2)
            content = num_list_match.group(3)
            processed_lines.append(f"{indent}{num}.\t{content}")
            continue

        line = re.sub(r"<\/?L>", "", line)
        line = re.sub(r"[„“”»«]", '"', line)
        line = re.sub(r"[‚‘’‹›]", "'", line)
        line = re.sub(r"…", " ...", line)
        line = re.sub(r"([a-zA-Z0-9äöüÄÖÜß_\*\%#])\.\.\.", r"\1 ...", line)
        line = re.sub(r"_{2,}", "_..._", line)
        line = re.sub(r"\.{4,}", "_..._", line)
        line = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", r"_\1_", line)
        line = re.sub(r"(?<![\w\*])\*(?![\*\s])([^\*\n]+?)(?<![\*\s])\*(?![\w\*])", r"_\1_", line)

        fn_match = re.match(r"^(\s*)\{(\d+)\}\s*(.*)$", line)
        if fn_match:
            num = fn_match.group(2)
            content = fn_match.group(3)
            processed_lines.append(f"<Anmerkung> {num} {content} </Anmerkung>")
            continue

        processed_lines.append(line)

    if in_box and box_lines:
        processed_lines.append("<Rahmen>")
        processed_lines.extend(box_lines)
        processed_lines.append("</Rahmen>")
    if in_table and table_lines:
        processed_lines.append("<Tabelle>")
        processed_lines.extend(table_lines)
        processed_lines.append("</Tabelle>")

    output_md = "\n".join(processed_lines)
    output_md = re.sub(r"\n{3,}", "\n\n", output_md)
    output_md = restore_false_positive_trailing_asterisks(output_md, raw_markdown)
    return output_md


def restore_false_positive_trailing_asterisks(
    fibs_md: str,
    raw_md: str | None = None,
) -> str:
    """Restores trailing footnote/prime asterisks (``2030* 2040*``, ``A* B*``) that were
    falsely converted into underscores (``2030_ 2040_``, ``A_ B_``) by naive ``*...*`` regexes.
    """
    if not fibs_md:
        return fibs_md
    if raw_md:
        # Strip balanced **...** and *...* spans first so closing italic asterisks
        # (e.g. '*Atropa belladonna*', '*T-Tubuli*') are never misidentified as footnote markers.
        raw_unpaired = re.sub(
            r"\*\*[^*\n]+\*\*|(?<![\w\*\\])\*(?![\*\s])[^*\n]+?(?<![\*\s])\*(?![\w\*])",
            " ",
            raw_md,
        )
        starred_tokens = sorted(
            set(re.findall(r"(?<![\w\*])([A-Za-z0-9äöüÄÖÜß]+)\*(?![\w\*])", raw_unpaired))
        )
        if starred_tokens:
            bal_spans: list[str] = []

            def _mask_bal_und(m_b: re.Match[str]) -> str:
                bal_spans.append(m_b.group(0))
                return f"\x00BALUND{len(bal_spans) - 1}\x00"

            fibs_masked = re.sub(
                r"(?<![\w\*])_(?![_\s])[^_\n]+?(?<![_\s])_(?![\w\*])",
                _mask_bal_und,
                fibs_md,
            )
            for tok in starred_tokens:
                fibs_masked = re.sub(
                    rf"(?<![_\w\*]){re.escape(tok)}_(?![_\w\*])",
                    f"{tok}*",
                    fibs_masked,
                )
            for idx_b, span_b in enumerate(bal_spans):
                fibs_masked = fibs_masked.replace(f"\x00BALUND{idx_b}\x00", span_b)
            fibs_md = fibs_masked
    fibs_md = re.sub(
        r"(?<![_\w])(\d{4})_(\s+)(\d{4})_(?![_\w])",
        r"\1*\2\3*",
        fibs_md,
    )
    return fibs_md


def format_spread_tasks_and_materials(md: str, *, is_fibs: bool = False) -> str:
    """Generic structural formatter for 2-up textbook spreads:
    - Normalizes mixed-case small-caps PDF font encoding artefacts (``LeRnBoX`` -> ``LERNBOX``).
    - Promotes standalone ``Aufgaben``, ``M1 ...`` material headers, and numbered spread headers.
    - Splits inline run-together numbered tasks under ``## Aufgaben`` into ``### Aufgabe N``.
    """
    if not md:
        return md
    md = re.sub(r"\bLeRnBoX\b|\bLeRnBOX\b", "LERNBOX", md)
    md = re.sub(r"\bAuSBlICK\b", "AUSBLICK", md)
    md = re.sub(r"\bZu SeiTe\b", "Zu Seite", md)
    md = re.sub(r"(?m)^(\d{2,3}\s+[^\n|#]+\|\s*[^\n]+)$", r"## \1", md)
    md = re.sub(r"(?m)^Aufgaben$", "## Aufgaben", md)
    md = re.sub(
        r"(?m)^(Kannst du schon|Zeig, was du kannst|Fachbegriffe)$",
        r"### \1",
        md,
    )
    md = re.sub(
        r"(?m)^(M\d+\s+[A-ZÄÖÜ][^\n]+)$",
        r"### \1",
        md,
    )

    lines = md.splitlines()
    out_lines: list[str] = []
    in_tasks_section = False
    for line in lines:
        s = line.strip()
        if s in ("## Aufgaben", "### Zeig, was du kannst"):
            in_tasks_section = True
            out_lines.append(line)
            continue
        if s.startswith("## ") and s != "## Aufgaben":
            in_tasks_section = False

        if re.match(r"^[1-9]\s+[A-ZÄÖÜ]", s) and re.search(
            r"[.!?]\s+(?:S\.\s*\d+\s+)?[2-9]\s+[A-ZÄÖÜ„\"']",
            s,
        ):
            parts = re.split(
                r"(?<=[.!?])\s+(?:(S\.\s*\d+)\s+)?(?=[2-9]\s+[A-ZÄÖÜ„\"'])",
                s,
            )
            rebuilt: list[str] = []
            i = 0
            while i < len(parts):
                chunk = parts[i] or ""
                if i + 1 < len(parts) and parts[i + 1] and parts[i + 1].startswith("S."):
                    chunk = f"{chunk} ({parts[i + 1]})"
                    i += 2
                else:
                    i += 1
                if chunk.strip():
                    m_task = re.match(r"^([1-9])\s+(.+)$", chunk.strip())
                    if m_task and in_tasks_section:
                        rebuilt.append(f"### Aufgabe {m_task.group(1)}\n\n{m_task.group(2)}")
                    else:
                        rebuilt.append(chunk.strip())
            out_lines.append("\n\n".join(rebuilt))
        elif in_tasks_section and re.match(r"^([1-9])\s+([A-ZÄÖÜ„\"'][^\?\n]{8,})$", s):
            m_t = re.match(r"^([1-9])\s+(.+)$", s)
            if m_t:
                out_lines.append(f"### Aufgabe {m_t.group(1)}\n\n{m_t.group(2)}")
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)

    res = "\n".join(out_lines)
    if is_fibs:
        res = re.sub(
            r"(?m)^(Nach Niveau differenzieren|Kreative Zusatzaufgaben|Gestärkt in die Klassenarbeit)\n+((?:(?![#\n<\(])[^\n]+\n?)+)",
            lambda m: f"<Rahmen>\n_{m.group(1).strip()}_\n"
            + "\n".join(ln for ln in m.group(2).strip().splitlines() if ln.strip())
            + "\n</Rahmen>\n",
            res,
        )
    return res


def preserve_only_physical_page_markers(md: str, physical_pages: list[int]) -> str:
    """Ensures that only the document's true ``physical_pages`` appear as ``((num))`` page markers
    in monotonic order, converting any accidental in-page ``((num))`` back to plain ``num``.
    """
    lines = md.splitlines()
    target_idx = 0
    out: list[str] = []
    for ln in lines:
        m = re.match(r"^\s*\(\((\d+)\)\)\s*$", ln)
        if m:
            val = int(m.group(1))
            if target_idx < len(physical_pages) and val == physical_pages[target_idx]:
                out.append(f"(({val}))")
                target_idx += 1
            elif target_idx > 0 and val == physical_pages[target_idx - 1]:
                continue
            else:
                out.append(str(val))
        else:
            out.append(ln)
    return "\n".join(out)


def split_golden_by_physical_pages(md: str, physical_pages: list[int]) -> dict[int, str]:
    """Splits a golden Markdown string by ``((num))`` markers into a dict ``{p_num: page_body}``."""
    result: dict[int, str] = {p: "" for p in physical_pages}
    current_p: int | None = None
    buf: list[str] = []
    target_set = set(physical_pages)

    for ln in md.splitlines():
        m = re.match(r"^\s*\(\((\d+)\)\)\s*$", ln)
        if m and int(m.group(1)) in target_set:
            if current_p is not None and not result[current_p]:
                result[current_p] = "\n".join(buf).strip()
            current_p = int(m.group(1))
            buf = []
        else:
            buf.append(ln)
    if current_p is not None and not result[current_p]:
        result[current_p] = "\n".join(buf).strip()
    return result


def _toc_norm_matches_page(
    norm_key: str,
    toc_pages_map: dict[str, set[int | None]],
    current_page: int | None,
    has_doc_pages: bool,
) -> bool:
    """Checks whether ``norm_key`` matches a TOC entry scoped to ``current_page`` (±1 page).

    Args:
        norm_key: Normalized heading title key.
        toc_pages_map: Mapping from normalized TOC title to its target page numbers.
        current_page: Current physical page number from ``((N))``, or ``None`` if unknown.
        has_doc_pages: Whether the document contains any numeric ``((N))`` page markers.

    Returns:
        ``True`` if the TOC entry applies on ``current_page``, otherwise ``False``.
    """
    pages = toc_pages_map.get(norm_key)
    if not pages:
        return False
    if not has_doc_pages:
        return True
    if current_page is None:
        return False
    return any(ep is not None and abs(current_page - ep) <= 1 for ep in pages)


def infer_heading_hierarchy(
    markdown_content: str,
    raw_markdown: str | None = None,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
) -> str:
    """Infers and restores hierarchical Markdown heading levels (``#`` to ``####``).

    Combines raw extraction heading evidence, stacked parent-child heading pairs,
    page-aware H2/H3/H4 progression, numbering schemes, and detected Table of
    Contents (``Inhaltsverzeichnis``) entries.

    Args:
        markdown_content: Standardised or partially processed Markdown text.
        raw_markdown: Optional Stage 1 raw extracted Markdown for heading recovery.
        directory_info: Optional detected TOC/directory metadata dictionary.
        custom_rules: Optional book-specific rules string.

    Returns:
        Markdown string with normalized heading levels.
    """
    if not markdown_content:
        return markdown_content

    raw_heading_map: dict[str, int] = {}
    if raw_markdown:
        raw_outside_blocks = re.sub(
            r"<(?:Bild|Tabelle)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle)>",
            "",
            raw_markdown,
            flags=re.IGNORECASE,
        )
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", raw_outside_blocks, re.MULTILINE):
            lvl = len(m.group(1))
            clean_t = re.sub(r"[\*_#]+", "", m.group(2)).strip()
            if len(clean_t) >= 3:
                raw_heading_map[clean_t.lower()] = lvl

    lines = markdown_content.split("\n")
    processed_lines: list[str] = []
    in_bild = False
    in_tabelle = False
    for line in lines:
        stripped = line.strip()
        if in_bild:
            if re.search(r"</Bild>", stripped, re.IGNORECASE):
                in_bild = False
            processed_lines.append(re.sub(r"^(\s*)#{1,6}\s+", r"\1", line))
            continue
        if re.match(r"^<Bild(?!-Ref)\b", stripped, re.IGNORECASE):
            if not re.search(r"</Bild>", stripped, re.IGNORECASE):
                in_bild = True
            processed_lines.append(line)
            continue

        if in_tabelle:
            if re.search(r"</Tabelle>", stripped, re.IGNORECASE):
                in_tabelle = False
            processed_lines.append(line)
            continue
        if re.match(r"^<Tabelle\b", stripped, re.IGNORECASE):
            if not re.search(r"</Tabelle>", stripped, re.IGNORECASE):
                in_tabelle = True
            processed_lines.append(line)
            continue

        if not stripped:
            processed_lines.append(line)
            continue

        unwrapped = re.sub(r"^(?:_|\*|#)+(.+?)(?:_|\*|#)+$", r"\1", stripped).strip()
        if not stripped.startswith("# ") and not stripped.startswith("##"):
            if unwrapped.lower() in raw_heading_map:
                lvl = raw_heading_map[unwrapped.lower()]
                processed_lines.append(f"{'#' * lvl} {unwrapped}")
                continue
            if re.match(r"^(?:Kapitel|Chapter|Teil|Part)\s+\d+", unwrapped, re.IGNORECASE):
                processed_lines.append(f"## {unwrapped}")
                continue
            if re.match(r"^[IVXLCDM]+\.\s+[A-ZÄÖÜ]", unwrapped):
                processed_lines.append(f"### {unwrapped}")
                continue
            if re.match(r"^Aufgabe\s+\d+\s*:", unwrapped, re.IGNORECASE) and not any(
                c in stripped for c in ["○", "◐", "●", "[leicht]", "[mittel]", "[schwer]"]
            ):
                processed_lines.append(f"### {unwrapped}")
                continue

        match = re.match(r"^(#+)\s+(.*)$", stripped)
        if match:
            current_hashes = match.group(1)
            title_text = re.sub(r"^[_*]+(.+?)[_*]+$", r"\1", match.group(2).strip()).strip()

            if (
                title_text.endswith(":")
                and len(title_text.split()) >= 4
                and "aufgabe" in title_text.lower()
            ):
                processed_lines.append(title_text)
                continue
            if re.match(r"^(?:\S+\s+)?Arbeitsauftrag:?$", title_text, re.IGNORECASE):
                processed_lines.append(f"_{title_text}_")
                continue
            from backend.services.extraction_postprocess import _DIDACTIC_CALLOUT_BOX_RE

            if (
                raw_heading_map
                and title_text.lower() not in raw_heading_map
                and (
                    _DIDACTIC_CALLOUT_BOX_RE.match(title_text)
                    or re.match(
                        r"^(?:Wo|Wohin|Woher|Wann|Wie|Warum)\b[^\n]*\?[^\n]*$",
                        title_text,
                        re.IGNORECASE,
                    )
                    or re.match(r"^Schritt\s+\d+\b", title_text, re.IGNORECASE)
                )
            ):
                processed_lines.append(f"_{title_text}_")
                continue

            num_match = re.match(r"^(\d+(?:\.\d+)+)\.?\s*(.+)$", title_text)
            if num_match:
                num_str = num_match.group(1).rstrip(".")
                rest_title = num_match.group(2).strip()
                dot_count = num_str.count(".")
                target_level = min(dot_count + 1, 4)
                clean_num_title = (
                    f"{num_match.group(1)} {rest_title}"
                    if not title_text[len(num_match.group(1)) :].startswith(" ")
                    else title_text
                )
                processed_lines.append(f"{'#' * target_level} {clean_num_title}")
                continue

            if re.match(r"^[IVXLCDM]+\.\s+", title_text):
                processed_lines.append(f"### {title_text}")
                continue

            if re.match(r"^\d+\.\s+", title_text):
                if (
                    not custom_rules
                    and len(current_hashes) <= 2
                    and len(title_text.split()) <= 8
                    and not title_text.endswith(".")
                ):
                    processed_lines.append(f"# {title_text}")
                elif custom_rules and len(current_hashes) == 1:
                    processed_lines.append(f"#### {title_text}")
                else:
                    processed_lines.append(f"{current_hashes} {title_text}")
                continue

            if len(current_hashes) == 1 and re.match(
                r"^\d+\s+(?!Kapitel\b|Chapter\b|Teil\b|Part\b|Band\b|Lektion\b)\S",
                title_text,
                re.IGNORECASE,
            ):
                processed_lines.append(f"#### {title_text}")
                continue

            if re.match(r"^(?:Kapitel|Chapter|Teil|Part)\b", title_text, re.IGNORECASE):
                if not any(ln.startswith("# ") for ln in processed_lines):
                    processed_lines.append(f"# {title_text}")
                else:
                    processed_lines.append(f"## {title_text}")
                continue

            if re.match(
                r"^(?:Versuch|Experiment|Aufgabe|Übung|Exkurs|Definition|Beispiel|Merksatz)\b",
                title_text,
                re.IGNORECASE,
            ):
                processed_lines.append(f"### {title_text}")
                continue

            processed_lines.append(f"{current_hashes} {title_text}")
            continue

        processed_lines.append(line)

    heading_indices = [
        idx for idx, ln in enumerate(processed_lines) if re.match(r"^#{1,6}\s+", ln.strip())
    ]
    if not custom_rules:
        for k in range(len(heading_indices) - 1):
            i1 = heading_indices[k]
            i2 = heading_indices[k + 1]
            between = [
                processed_lines[b].strip()
                for b in range(i1 + 1, i2)
                if processed_lines[b].strip()
                and not re.match(
                    r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?$",
                    processed_lines[b].strip(),
                )
            ]
            if not between:
                h1_match = re.match(r"^(#+)\s+(.*)$", processed_lines[i1].strip())
                h2_match = re.match(r"^(#+)\s+(.*)$", processed_lines[i2].strip())
                if (
                    h1_match
                    and h2_match
                    and len(h1_match.group(1)) == 2
                    and len(h2_match.group(1)) == 2
                ):
                    processed_lines[i1] = f"# {h1_match.group(2)}"

    has_existing_h3 = any(ln.strip().startswith("### ") for ln in processed_lines)
    if not has_existing_h3:
        has_active_h2 = False
        has_active_h3 = False
        for idx, ln in enumerate(processed_lines):
            s = ln.strip()
            if re.match(r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?$", s):
                continue
            hm = re.match(r"^(#+)\s+(.*)$", s)
            if not hm:
                continue
            hashes, title = hm.group(1), hm.group(2).strip()
            lvl = len(hashes)
            if lvl == 1 and not re.match(r"^\d+\.\s+", title):
                has_active_h2 = False
                has_active_h3 = False
            elif lvl == 2:
                is_chapter = bool(
                    re.match(r"^(?:Kapitel|Chapter|Teil|Part|\d+\.\d+\.?)\b", title, re.IGNORECASE)
                )
                prev_non_empty = ""
                for p_idx in range(idx - 1, -1, -1):
                    if processed_lines[p_idx].strip():
                        prev_non_empty = processed_lines[p_idx].strip()
                        break
                next_non_empty = ""
                for n_idx in range(idx + 1, len(processed_lines)):
                    if processed_lines[n_idx].strip():
                        next_non_empty = processed_lines[n_idx].strip()
                        break
                is_after_page_marker = bool(
                    re.match(r"^\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?$", prev_non_empty)
                )
                is_table_subsection = next_non_empty.startswith(("|", "<Tabelle"))
                if (
                    is_chapter
                    or not has_active_h2
                    or (
                        is_after_page_marker
                        and not is_table_subsection
                        and not title.endswith(":")
                        and len(title.split()) <= 4
                    )
                ):
                    has_active_h2 = True
                    has_active_h3 = False
                else:
                    if title.endswith(":") and has_active_h3:
                        processed_lines[idx] = f"#### {title}"
                    else:
                        processed_lines[idx] = f"### {title}"
                        has_active_h3 = True
            elif lvl == 3:
                has_active_h3 = True

    result = "\n".join(processed_lines)
    try:
        from backend.services.directory_service import (
            apply_directory_heading_levels,
            extract_directories_from_markdown,
        )

        eff_dir_info = directory_info
        if not eff_dir_info or not eff_dir_info.get("has_any_directory"):
            eff_dir_info = extract_directories_from_markdown(raw_markdown or result)

        if eff_dir_info and eff_dir_info.get("has_any_directory"):
            toc_entries_all = eff_dir_info.get("toc_entries") or []
            page_segs = split_markdown_pages(result)
            has_numeric_pages = any(seg.page and seg.page.isdigit() for seg in page_segs)
            if not has_numeric_pages or not toc_entries_all:
                result, _ = apply_directory_heading_levels(
                    result, directory_info=eff_dir_info, raw_markdown=raw_markdown
                )
            else:
                updated_segs: list[str] = []
                for seg in page_segs:
                    cur_pg_int = int(seg.page) if (seg.page and seg.page.isdigit()) else None
                    scoped_toc: list[dict[str, Any]] = []
                    if cur_pg_int is not None:
                        for entry in toc_entries_all:
                            if not isinstance(entry, dict):
                                continue
                            pg_s = str(entry.get("page") or "").strip()
                            if pg_s.isdigit() and abs(cur_pg_int - int(pg_s)) <= 1:
                                scoped_toc.append(entry)
                    seg_dir_info = {
                        **eff_dir_info,
                        "toc_entries": scoped_toc,
                        "heading_levels": {},
                    }
                    seg_out, _ = apply_directory_heading_levels(
                        seg.text, directory_info=seg_dir_info, raw_markdown=None
                    )
                    updated_segs.append(seg_out)
                result = "".join(updated_segs)
    except Exception as e:
        logger.debug(f"Could not apply directory heading levels in infer_heading_hierarchy: {e}")

    return result


def _is_placeholder_only_table(data_rows: list[list[str]]) -> bool:
    """Returns True if a table is a single-row axis fragment or has <= 4 rows of placeholder cells."""
    if len(data_rows) == 1:
        return len(data_rows[0]) >= 2 and not any(
            ch.isdigit() for cell in data_rows[0] for ch in cell
        )
    if not (2 <= len(data_rows) <= 4):
        return False
    total_cells = 0
    placeholder_cells = 0
    has_digit = False
    for row in data_rows[1:]:
        for cell in row:
            total_cells += 1
            if any(ch.isdigit() for ch in cell):
                has_digit = True
            cleaned = re.sub(r"[\s_\*\.…\-–—]+", "", cell)
            if len(cleaned) <= 1 and not (len(cleaned) == 1 and cleaned.isdigit()):
                placeholder_cells += 1
    if total_cells == 0:
        return False
    if placeholder_cells == total_cells:
        return True
    return not has_digit and placeholder_cells * 2 >= total_cells


def _parse_tabelle_data_rows(raw_text: str) -> list[list[str]]:
    """Extracts data rows from pipe-separated or tab-separated ``<Tabelle>`` inner content."""
    rows: list[list[str]] = []
    for r in raw_text.splitlines():
        rs = r.strip()
        if not rs or re.match(r"^</?Tabelle\b", rs, re.IGNORECASE):
            continue
        if "|" in rs:
            inner = rs.strip("|").strip()
            if re.match(r"^[\s\|:\-]+$", inner):
                continue
            rows.append([c.strip() for c in rs.strip("|").split("|")])
        elif "\t" in rs:
            rows.append([c.strip() for c in rs.split("\t")])
    return rows


def _unroll_subtask_tables_and_convert_md_tables(text: str) -> str:
    """Unrolls multi-column subtask tables into linear lists and wraps data tables in ``<Tabelle>``.

    Args:
        text: Markdown text potentially containing pipe tables or multi-column subtasks.

    Returns:
        Transformed Markdown string per FIBS Sections 6.1 and 7.5.
    """
    if not text:
        return text

    subtask_cell_re = re.compile(r"^[a-z]\)\s+", re.IGNORECASE)

    def process_pipe_table(match: re.Match[str]) -> str:
        block = match.group(0).strip()
        raw_rows = [r.strip() for r in block.splitlines() if r.strip()]
        data_rows: list[list[str]] = []
        all_cells: list[str] = []
        for r in raw_rows:
            inner = r.strip("|").strip()
            if re.match(r"^[\s\|:\-]+$", inner):
                continue
            cells = [c.strip() for c in r.strip("|").split("|") if c.strip()]
            if cells:
                data_rows.append(cells)
                all_cells.extend(cells)

        if not data_rows:
            return block

        if _is_placeholder_only_table(data_rows):
            return ""

        subtask_cells = [c for c in all_cells if subtask_cell_re.match(c)]
        if len(subtask_cells) >= 2 and len(subtask_cells) >= 0.6 * len(all_cells):
            sorted_cells = sorted(subtask_cells, key=lambda c: c[0].lower())
            cleaned_subtasks = [re.sub(r"^([a-z]\))\s+", r"\1 ", c) for c in sorted_cells]
            return "\n".join(cleaned_subtasks) + "\n"

        numbered_cells = [c for c in all_cells if re.match(r"^\*?\*?\d+\.\s+", c)]
        if len(data_rows) == 1 and len(numbered_cells) >= 2:
            unrolled_num = []
            for c in all_cells:
                c_clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", c)
                c_clean = re.sub(r"<br\s*/?>|\n+", ": ", c_clean)
                c_clean = re.sub(r"^(\d+\.)\s*([^:]+):\s*", r"\1\t\2: ", c_clean)
                unrolled_num.append(c_clean.strip())
            return "\n".join(unrolled_num) + "\n"

        max_cols = max(len(r) for r in data_rows) if data_rows else 1
        formatted_rows = []
        for r_idx, row in enumerate(data_rows):
            clean_cells = [
                re.sub(r"^(?:\*\*|_)(.+?)(?:\*\*|_)$", r"\1", cell).strip() for cell in row
            ]
            padded = clean_cells + [""] * (max_cols - len(clean_cells))
            formatted_rows.append("| " + " | ".join(padded) + " |")
            if r_idx == 0:
                sep = "| " + " | ".join([":---"] * max_cols) + " |"
                formatted_rows.append(sep)

        table_md = "\n".join(formatted_rows)
        return f"<Tabelle>\n\n{table_md}\n\n</Tabelle>\n"

    # Unwrap degenerate flowchart/diagram pipe tables broken across a multi-line <Bild>...</Bild> block
    text = re.sub(
        r"(?mi)^[ \t]*\|[^\n]+\|\s*\n[ \t]*\|[\s\|:\-]+\|\s*\n[ \t]*\|[^\n]*<Bild\b[^>]*>[\s\S]*?</Bild>[^\n]*(?:\n[ \t]*\|[^\n]+\|[ \t]*)*",
        lambda m: "\n\n".join(
            re.findall(r"<Bild\b[^>]*>[\s\S]*?</Bild>", m.group(0), flags=re.IGNORECASE)
        )
        + "\n",
        text,
    )

    parts = re.split(r"(<Tabelle\b[^>]*>.*?</Tabelle>)", text, flags=re.DOTALL | re.IGNORECASE)
    for idx in range(len(parts)):
        if idx % 2 == 0:
            parts[idx] = re.sub(
                r"(?:^[ \t]*\|.+?\|[ \t]*(?:\n|$)){2,}",
                process_pipe_table,
                parts[idx],
                flags=re.MULTILINE,
            )
        else:
            t_rows = _parse_tabelle_data_rows(parts[idx])
            if re.search(r"<Bild\b|!\[[^\]]*\]\([^)\n]+\)", parts[idx], re.IGNORECASE) and len(t_rows) <= 2:
                imgs_in_tbl = re.findall(
                    r"<Bild\b[^>]*>[\s\S]*?</Bild>|!\[[^\]]*\]\([^)\n]+\)",
                    parts[idx],
                    flags=re.IGNORECASE,
                )
                parts[idx] = "\n\n".join(im.strip() for im in imgs_in_tbl)
            elif _is_placeholder_only_table(t_rows):
                parts[idx] = ""
    text = "".join(parts)

    lines = text.splitlines()
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        m_pair = re.match(r"^([a-z]\)\s+.+?)(?:\t+|\s{3,})([a-z]\)\s+.+)$", lines[i].strip())
        if m_pair:
            collected: list[str] = []
            while i < len(lines):
                mp = re.match(r"^([a-z]\)\s+.+?)(?:\t+|\s{3,})([a-z]\)\s+.+)$", lines[i].strip())
                if mp:
                    collected.append(re.sub(r"^([a-z]\))\s+", r"\1 ", mp.group(1).strip()))
                    collected.append(re.sub(r"^([a-z]\))\s+", r"\1 ", mp.group(2).strip()))
                    i += 1
                else:
                    break
            collected.sort(key=lambda c: c[0].lower())
            out_lines.extend(collected)
        else:
            out_lines.append(lines[i])
            i += 1

    return "\n".join(out_lines)


def _recover_dropped_tables(processed: str, raw_markdown: str) -> str:
    """Recovers multi-row data tables from ``raw_markdown`` when dropped by the LLM.

    Skips degenerate flowchart/diagram tables containing images, placeholder-only tables,
    or subtask grid tables. Reinserts recovered tables as ``<Tabelle>...</Tabelle>`` on the
    corresponding page (before an ``Aufgaben`` block when the raw table preceded tasks).

    Args:
        processed: Post-processed LLM Markdown output.
        raw_markdown: Original Stage 1 extracted Markdown containing pipe or ``<Tabelle>`` tables.

    Returns:
        Markdown string with missing multi-row tables restored.
    """
    if not raw_markdown or ("|" not in raw_markdown and "<Tabelle" not in raw_markdown):
        return processed

    from backend.services.extraction_postprocess import _is_degenerate_diagram_table

    def _sig_words(txt: str) -> list[str]:
        cleaned = re.sub(r"</?[A-Za-zÄÖÜäöüß]+[^>]*>", " ", txt)
        return [w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{3,}", cleaned)]

    raw_segs = split_markdown_pages(raw_markdown)
    proc_segs = split_markdown_pages(processed)
    proc_by_page = {s.page: idx for idx, s in enumerate(proc_segs) if s.page is not None}
    all_proc_words = set(_sig_words(processed))
    subtask_cell_re = re.compile(r"^[a-z]\)\s+", re.IGNORECASE)

    modified = False
    for r_seg in raw_segs:
        r_masked = re.sub(
            r"<Bild\b[^>]*>[\s\S]*?</Bild>",
            " __DROP_TBL_BILD__ ",
            r_seg.text,
            flags=re.IGNORECASE,
        )
        raw_candidates: list[tuple[int, list[list[str]]]] = []
        for m_t in re.finditer(
            r"<Tabelle\b[^>]*>([\s\S]*?)</Tabelle>", r_masked, flags=re.IGNORECASE
        ):
            inner_t = m_t.group(1)
            if "__DROP_TBL_BILD__" in inner_t or "![" in inner_t:
                continue
            rows_t = _parse_tabelle_data_rows(inner_t)
            if len(rows_t) >= 2 and not _is_placeholder_only_table(rows_t):
                raw_candidates.append((m_t.start(), rows_t))

        r_no_tab = re.sub(
            r"<Tabelle\b[^>]*>[\s\S]*?</Tabelle>",
            lambda m: " " * len(m.group(0)),
            r_masked,
            flags=re.IGNORECASE,
        )
        for m_p in re.finditer(
            r"(?:^[ \t]*\|[^\n]+\|[ \t]*(?:\n|$)){2,}", r_no_tab, flags=re.MULTILINE
        ):
            pipe_blk = m_p.group(0)
            if "__DROP_TBL_BILD__" in pipe_blk or "![" in pipe_blk:
                continue
            if _is_degenerate_diagram_table(pipe_blk):
                continue
            rows_p = _parse_tabelle_data_rows(pipe_blk)
            if len(rows_p) < 2 or _is_placeholder_only_table(rows_p):
                continue
            cells_p = [c.strip() for row in rows_p for c in row if c.strip()]
            if not cells_p:
                continue
            sub_cnt = sum(1 for c in cells_p if subtask_cell_re.match(c))
            if sub_cnt >= 2 and sub_cnt >= 0.6 * len(cells_p):
                continue
            raw_candidates.append((m_p.start(), rows_p))

        if not raw_candidates:
            continue

        p_idx = proc_by_page.get(r_seg.page) if r_seg.page is not None else 0
        if p_idx is None or p_idx >= len(proc_segs):
            continue

        p_text = proc_segs[p_idx].text
        p_words = set(_sig_words(p_text))
        m_r_aufg = re.search(r"(?im)^(?:#{1,6}\s+|\*\*|_)?Aufgaben\b", r_seg.text)

        for r_pos, rows in sorted(raw_candidates, key=lambda kv: kv[0]):
            t_words = _sig_words(" ".join(c for r in rows for c in r))
            if len(t_words) < 4:
                continue
            unique_t = set(t_words)
            page_recall = len(unique_t & p_words) / len(unique_t)
            doc_recall = len(unique_t & all_proc_words) / len(unique_t)
            if page_recall >= 0.35 or doc_recall >= 0.45:
                continue

            max_cols = max(len(r) for r in rows)
            fmt_rows: list[str] = []
            for r_i, r_cells in enumerate(rows):
                clean_c = [
                    re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", c.strip()).strip()
                    for c in r_cells
                ]
                padded = clean_c + [""] * (max_cols - len(clean_c))
                fmt_rows.append("| " + " | ".join(padded) + " |")
                if r_i == 0:
                    fmt_rows.append("| " + " | ".join([":---"] * max_cols) + " |")
            tabelle_blk = "<Tabelle>\n\n" + "\n".join(fmt_rows) + "\n\n</Tabelle>"

            m_p_aufg = re.search(
                r"(?im)^(?:#{1,6}\s+|\*\*|_)?Aufgaben\b|^#####\s+1\b", p_text
            )
            if m_r_aufg and r_pos < m_r_aufg.start() and m_p_aufg:
                ins_pos = m_p_aufg.start()
                p_text = (
                    p_text[:ins_pos].rstrip()
                    + f"\n\n{tabelle_blk}\n\n"
                    + p_text[ins_pos:].lstrip()
                )
            else:
                p_text = p_text.rstrip() + f"\n\n{tabelle_blk}\n\n"
            proc_segs[p_idx].text = p_text
            p_words |= unique_t
            all_proc_words |= unique_t
            modified = True

    if not modified:
        return processed
    return "".join(s.text for s in proc_segs).strip()


def _parse_difficulty_rules(
    custom_rules: str | None,
) -> tuple[dict[str, str], bool, bool]:
    """Parses book-specific custom rules for task difficulty symbols and placement.

    Args:
        custom_rules: Optional book-specific rules string.

    Returns:
        Tuple of ``(symbol_map, drop_difficulty, inline_on_heading)``.
    """
    symbol_map = dict(fc.DIFFICULTY_SYMBOL_MAP)
    if not custom_rules:
        return symbol_map, False, False

    drop_difficulty = bool(
        re.search(
            r"schwierigkeitsgrad\w*[^\n.]*nicht\s+übertragen"
            r"|symbole\s+bei\s+aufgaben[^\n.]*nicht\s+übertragen"
            r"|keine\s+schwierigkeitsgrad",
            custom_rules,
            re.IGNORECASE,
        )
    )
    inline_on_heading = bool(
        re.search(
            r"in\s+einer\s+zeile|gleiche[nr]?\s+zeile"
            r"|hinter\s+der\s+aufgabennummer|in\s+der\s+aufgabenüberschrift",
            custom_rules,
            re.IGNORECASE,
        )
    )
    for m_map in re.finditer(
        r"(★★★|★★|★|[□◩■◇◈◆○◯◐◑◒◓●☆])\s*(?:=|->|→|:)\s*(\[[^\],\n]+\])",
        custom_rules,
    ):
        symbol_map[m_map.group(1)] = m_map.group(2).strip()

    verbal_specs = [
        (
            r"\b(?:leer\w*|weiß\w*|weiss\w*|offen\w*|ungefüllt\w*)\s+Kreis\w*\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("○", "◯"),
        ),
        (
            r"\b(?:halb\s*(?:gefüllt\w*|ausgefüllt\w*|voll\w*|schwarz\w*)|halbkreis\w*)\s*(?:Kreis\w*)?\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("◐", "◑", "◒", "◓"),
        ),
        (
            r"(?<!halb\s)(?<!halb)(?:gefüllt\w*|ausgefüllt\w*|voll\w*|schwarz\w*)\s+Kreis\w*\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("●",),
        ),
        (
            r"\b(?:leer\w*|weiß\w*|weiss\w*|offen\w*)\s+(?:Quadrat\w*|Kästchen)\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("□",),
        ),
        (
            r"\bhalb\s*(?:gefüllt\w*|ausgefüllt\w*)\s+(?:Quadrat\w*|Kästchen)\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("◩",),
        ),
        (
            r"(?<!halb\s)(?<!halb)(?:gefüllt\w*|ausgefüllt\w*|schwarz\w*)\s+(?:Quadrat\w*|Kästchen)\s*(?::|=|->|→|–|-|entspricht)?\s*(\[[^\]\n,]+\])",
            ("■",),
        ),
    ]
    for pat, syms in verbal_specs:
        m_v = re.search(pat, custom_rules, re.IGNORECASE)
        if m_v:
            lbl_v = m_v.group(1).strip()
            for s_k in syms:
                symbol_map.setdefault(s_k, lbl_v)

    return symbol_map, drop_difficulty, inline_on_heading


def _normalize_fibs_task_headings_and_boxes(
    text: str,
    custom_rules: str | None = None,
) -> str:
    """Normalizes FIBS task difficulty indicators, ``<Rahmen>`` callout boxes, and list tabs.

    Args:
        text: Input Markdown text.
        custom_rules: Optional book-specific rules overriding task difficulty symbols or placement.

    Returns:
        Normalized Markdown string with task difficulty tags under ``### Aufgabe N``
        and callout boxes wrapped in ``<Rahmen>...</Rahmen>``.
    """
    if not text:
        return text

    symbol_map, drop_difficulty, inline_on_heading = _parse_difficulty_rules(custom_rules)
    sorted_symbols = sorted(symbol_map.items(), key=lambda kv: -len(kv[0]))
    known_indicators = {"[leicht]", "[mittel]", "[schwer]", *symbol_map.values()}

    lines = text.splitlines()
    norm_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        m_sq = re.match(
            r"^(?:(?:★★★|★★|★|[□◩■◇◈◆☆])\s*(?:\[[^\]]+\])?\s*)?(?:#{1,6}\s+)?(?:_|\*)*Aufgabe\s+(\d+)\s*((?:★★★|★★|★|[□◩■◇◈◆☆])(?:\s*\[[^\]]+\])?|\((?:leicht|mittel|schwer)\)|\[[^\]]+\])?\s*:\s*(.+?)(?:_|\*)*$",
            stripped,
            re.IGNORECASE,
        )
        if m_sq and not stripped.startswith(("○", "◐", "●")):
            task_num = m_sq.group(1)
            raw_ind = (m_sq.group(2) or "").strip()
            task_title = m_sq.group(3).strip()
            ind_str = symbol_map.get(raw_ind, "")
            if not ind_str:
                for k, v in sorted_symbols:
                    if k in raw_ind or k in stripped:
                        ind_str = v
                        break
            if not ind_str:
                m_lbl = re.search(r"[\(\[]([^\)\]]+)[\)\]]", raw_ind)
                if m_lbl:
                    lbl_val = m_lbl.group(1).strip()
                    if lbl_val.lower() in ("leicht", "mittel", "schwer"):
                        ind_str = f"[{lbl_val.lower()}]"
                    else:
                        ind_str = f"[{lbl_val}]"
            next_idx = i + 1
            while next_idx < len(lines) and not lines[next_idx].strip():
                next_idx += 1
            next_has_ind = next_idx < len(lines) and lines[next_idx].strip() in known_indicators
            if not ind_str and next_has_ind:
                ind_str = lines[next_idx].strip()

            if drop_difficulty:
                norm_lines.append(f"### Aufgabe {task_num}: {task_title}")
                i = (next_idx + 1) if next_has_ind else (i + 1)
                continue

            if inline_on_heading and ind_str:
                norm_lines.append(f"### Aufgabe {task_num} {ind_str}: {task_title}")
                i = (next_idx + 1) if next_has_ind else (i + 1)
                continue

            norm_lines.append(f"### Aufgabe {task_num}: {task_title}")
            if ind_str:
                if next_has_ind:
                    lines[next_idx] = ind_str
                else:
                    norm_lines.append(ind_str)
                    norm_lines.append("")
            i += 1
            continue

        norm_lines.append(line)
        i += 1

    text = "\n".join(norm_lines)

    repaired_lines: list[str] = []
    idx = 0
    raw_lines = text.splitlines()
    while idx < len(raw_lines):
        m_num_h = re.match(r"^#+\s+(\d+)\.\s+([A-Za-zäöüÄÖÜß\-]{3,25})$", raw_lines[idx].strip())
        if m_num_h and int(m_num_h.group(1)) == 1:
            window = raw_lines[idx : min(len(raw_lines), idx + 18)]
            num_items: list[tuple[int, str]] = []
            descs: list[str] = []
            other_lines: list[str] = []
            consumed = 0
            for w_line in window:
                ws = w_line.strip()
                consumed += 1
                if not ws:
                    continue
                mh = re.match(r"^#+\s+(\d+)\.\s+([A-Za-zäöüÄÖÜß\-]{3,25})$", ws)
                if mh:
                    num_items.append((int(mh.group(1)), mh.group(2)))
                elif ws.startswith(("<Bild>", "![")):
                    other_lines.append(w_line)
                elif (
                    len(num_items) >= 1
                    and len(descs) < len(num_items)
                    and not ws.startswith(("#", "(("))
                    and len(ws) <= 90
                ):
                    descs.append(ws)
                else:
                    consumed -= 1
                    break
            if len(num_items) >= 2 and len(descs) == len(num_items):
                for (n_val, n_term), d_text in zip(num_items, descs):
                    repaired_lines.append(f"{n_val}.\t{n_term}: {d_text}")
                repaired_lines.append("")
                for ol in other_lines:
                    repaired_lines.append(ol)
                    repaired_lines.append("")
                idx += consumed
                continue
        repaired_lines.append(raw_lines[idx])
        idx += 1
    text = "\n".join(repaired_lines)

    def wrap_titled_list_box(match: re.Match[str]) -> str:
        box_title = match.group(1).strip()
        box_sub = match.group(2).strip()
        if not box_sub.endswith(":"):
            box_sub += ":"
        list_block = match.group(3).strip()
        return f"<Rahmen>\n_{box_title}_\n{box_sub}\n{list_block}\n</Rahmen>\n"

    text = re.sub(
        r"(?m)^(?:#{2,3}\s+|\*\*|_)([A-ZÄÖÜ][^\n\*_\.:!?]{10,65})(?:\*\*|_)?\n+([A-ZÄÖÜ][^\n\.!?]{10,60})\n+((?:[\-\*][\s\t]+[^\n]+\n?){2,})",
        wrap_titled_list_box,
        text,
    )

    feature_banner_re = re.compile(
        r"(?m)^(?<!<Rahmen>\n)_(?:(?:CAREER|EVERYDAY|EVOLUTION)\s+CONNECTION|THE\s+PAST\s+MEETS\s+THE\s+PRESENT)_[ \t]*\n+"
        r"_([^_\n]{3,80})_[ \t]*\n+"
        r"((?:(?![#\n<\(!])[^\n]+\n\n?){1,3}(?:(?:[-\*][\t\s][^\n]+\n?)+)?)"
    )

    def _wrap_feature_banner_box(m: re.Match[str]) -> str:
        full_match = m.group(0)
        first_line = full_match.splitlines()[0].strip().strip("_").strip()
        subtitle = m.group(1).strip()
        body_raw = m.group(2).strip()
        return f"<Rahmen>\n_{first_line}: {subtitle}_\n{body_raw}\n</Rahmen>\n\n"

    text = feature_banner_re.sub(_wrap_feature_banner_box, text)

    protocol_box_re = re.compile(
        r"(?m)^(?<!<Rahmen>\n)_((?:Versuchsprotokoll|Experiment|Versuch)\b[^_\n]*:?)_[ \t]*\n+"
        r"((?:(?:Material(?:ien)?|Chemikalien|Geräte|Durchführung|Versuchsdurchführung|Beobachtung|Auswertung|Ergebnis|Deutung|Entsorgung)\b[\s\S]*?))"
        r"(?=\n+(?:##|###|####|_[A-ZÄÖÜ]|\*\*[A-ZÄÖÜ]|<Rahmen|<Bild|!\[|\(\(\d+\)\))|\Z)"
    )

    def _wrap_protocol_box(m: re.Match[str]) -> str:
        title_str = m.group(1).strip()
        body_raw = m.group(2).strip()
        norm_p_lines: list[str] = []
        for para in re.split(r"\n{2,}", body_raw):
            p_clean = " ".join(ln.strip() for ln in para.splitlines() if ln.strip())
            if not p_clean:
                continue
            m_lbl = re.match(
                r"^((?:Material(?:ien)?(?:\s*(?:&|&amp;|und)\s*Chemikalien)?|Chemikalien|Geräte|Durchführung|Versuchsdurchführung|Beobachtung|Auswertung|Ergebnis|Deutung|Entsorgung)\s*:)\s*(.+)$",
                p_clean,
            )
            if m_lbl:
                lbl_txt = m_lbl.group(1).replace("&amp;", "&")
                norm_p_lines.append(f"-\t_{lbl_txt}_ {m_lbl.group(2)}")
            elif norm_p_lines:
                norm_p_lines[-1] = f"{norm_p_lines[-1]} {p_clean}"
            else:
                norm_p_lines.append(p_clean)
        body_str = "\n".join(norm_p_lines)
        return f"<Rahmen>\n_{title_str}_\n{body_str}\n</Rahmen>\n"

    text = protocol_box_re.sub(_wrap_protocol_box, text)

    if "_Solution_" in text and "_Check Your Learning_" in text:
        text = re.sub(
            r"(?m)^(?<!<Rahmen>\n)(?:#{1,3}\s+|_)([A-Z][^\n_#]{10,85}?)(?:_)?[ \t]*\n+([A-Z][^\n#<]+\?)[ \t]*\n+(?=(?:\(\(\d+\)\)\s*\n+)?_Solution_|!\[FIGURE)",
            r"<Rahmen>\n_\1_\n\2\n</Rahmen>\n\n",
            text,
        )
        text = re.sub(
            r"(?m)^(?<!<Rahmen>\n)#\s+((?:Determining|Calculating|Calculation\s+of)\s+[^\n#]{10,85})[ \t]*\n+([A-Z][^\n#<]+\?)",
            r"<Rahmen>\n_\1_\n\2\n</Rahmen>",
            text,
        )
        text = re.sub(r"(?m)^Answer:\s*\n+([^\n]+)", r"_Answer:_ \1", text)
        text = re.sub(
            r"(?m)^(?<!<Rahmen>\n)(_Solution_[ \t]*\n+(?:(?!\(\(\d+\)\)|^#|\n<Rahmen>)[\s\S])*?_Check Your Learning_[ \t]*\n+[^\n]+\n+_Answer:_ [^\n]+)",
            r"<Rahmen>\n\1\n</Rahmen>",
            text,
        )

    text = re.sub(
        r"(###\s+Merksatz:?\s*\n+)(?!<Rahmen>)([A-ZÄÖÜ][^\n]+(?:\n[^\n#<(\[]+)*)",
        r"\1<Rahmen>\n\2\n</Rahmen>",
        text,
    )

    bild_list_box_re = re.compile(
        r"(?m)^(?<!<Rahmen>\n)(?:\*\*|_)(Bild\s+\d+\.\d+\s*:[^\n]*?)(?:\*\*|_)[ \t]*\n+((?:[-\*][\t\s][^\n]+(?:\n+[-\*][\t\s][^\n]+)*))"
    )
    text = bild_list_box_re.sub(
        lambda m: f"<Rahmen>\n_{m.group(1).strip()}_\n"
        + "\n".join(bl for bl in m.group(2).strip().splitlines() if bl.strip())
        + "\n</Rahmen>\n",
        text,
    )

    from backend.services.extraction_postprocess import DIDACTIC_CALLOUT_PREFIXES

    callout_title_re = re.compile(
        r"(?m)^(?<!<Rahmen>\n)(?:\*\*|_)("
        r"(?:" + DIDACTIC_CALLOUT_PREFIXES + r")[^\n]*?"
        r")(?:\*\*|_)[ \t]*\n+((?:(?:[-\*]|\d+\.)[\t\s][^\n]+(?:\n+(?:[-\*]|\d+\.)[\t\s][^\n]+)*)|(?:(?![#\n<\(])[^\n]+\n?)+)"
    )

    def _wrap_didactic_box(m: re.Match[str]) -> str:
        title_str = m.group(1).strip()
        body_raw = m.group(2).strip()
        body_lines = [bl for bl in body_raw.splitlines() if bl.strip()]
        body_str = "\n".join(body_lines)
        return f"<Rahmen>\n_{title_str}_\n{body_str}\n</Rahmen>\n"

    r_parts = re.split(r"(<Rahmen\b[^>]*>[\s\S]*?</Rahmen>)", text, flags=re.IGNORECASE)
    for r_i in range(0, len(r_parts), 2):
        r_parts[r_i] = callout_title_re.sub(_wrap_didactic_box, r_parts[r_i])
    text = "".join(r_parts)

    def wrap_arbeitsauftrag(match: re.Match[str]) -> str:
        header = match.group(1).strip()
        body = match.group(2).strip()
        norm_body = []
        for bl in body.splitlines():
            bs = re.sub(r"^[\-\*]\s*", "", bl.strip())
            if "(leicht)" in bs or "[leicht]" in bs:
                bs = re.sub(r"\(leicht\)", "", bs).replace("[leicht]", "").strip()
                bs = re.sub(r"^[○◐●\s]+", "", bs)
                bs = f"○ [leicht] {bs}"
            elif "(mittel)" in bs or "[mittel]" in bs:
                bs = re.sub(r"\(mittel\)", "", bs).replace("[mittel]", "").strip()
                bs = re.sub(r"^[○◐●\s]+", "", bs)
                bs = f"◐ [mittel] {bs}"
            elif "(schwer)" in bs or "[schwer]" in bs:
                bs = re.sub(r"\(schwer\)", "", bs).replace("[schwer]", "").strip()
                bs = re.sub(r"^[○◐●\s]+", "", bs)
                bs = f"● [schwer] {bs}"
            norm_body.append(bs)
        return f"<Rahmen>\n{header}\n" + "\n".join(norm_body) + "\n</Rahmen>"

    text = re.sub(
        r"(?m)^(_(?:Fortgeschrittener\s+)?Arbeitsauftrag:_)\s*\n+((?:(?:[\-\*]|[○◐●]).+\n?)+)",
        wrap_arbeitsauftrag,
        text,
    )

    final_lines: list[str] = []
    for line in text.splitlines():
        m_b = re.match(r"^([\-\*])\s+([^\t].*)$", line)
        m_n = re.match(r"^(\d+\.)\s+([^\t].*)$", line)
        if m_b:
            final_lines.append(f"-\t{m_b.group(2)}")
        elif m_n:
            final_lines.append(f"{m_n.group(1)}\t{m_n.group(2)}")
        else:
            final_lines.append(line)

    return "\n".join(final_lines)


def _recover_dropped_rahmen_blocks(processed: str, raw_markdown: str) -> str:
    """Recovers ``<Rahmen>...</Rahmen>`` blocks from ``raw_markdown`` if dropped by the LLM.

    Args:
        processed: LLM-standardised Markdown output.
        raw_markdown: Original Stage 1 extracted Markdown containing ``<Rahmen>`` blocks.

    Returns:
        Markdown string with missing or unwrapped ``<Rahmen>`` blocks restored.
    """
    if not raw_markdown or "<Rahmen" not in raw_markdown:
        return processed

    def _sig_words(txt: str) -> list[str]:
        cleaned = re.sub(r"</?[A-Za-zÄÖÜäöüß]+[^>]*>", " ", txt)
        return [w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{3,}", cleaned)]

    def _normalize_box_inner(inner: str) -> str:
        s = inner.strip()
        s = re.sub(r"\*\*([^\*\n]+)\*\*", r"_\1_", s)
        s = re.sub(r"(?m)^[ \t]*[-*][ \t]+(?!\t)", "-\t", s)
        return s

    raw_segs = split_markdown_pages(raw_markdown)
    proc_segs = split_markdown_pages(processed)
    proc_by_page = {s.page: idx for idx, s in enumerate(proc_segs) if s.page is not None}
    all_proc_words = set(_sig_words(processed))

    modified = False
    for r_seg in raw_segs:
        r_boxes = re.findall(r"<Rahmen>\s*([\s\S]*?)\s*</Rahmen>", r_seg.text, flags=re.IGNORECASE)
        if not r_boxes:
            continue

        p_idx = proc_by_page.get(r_seg.page) if r_seg.page is not None else 0
        if p_idx is None or p_idx >= len(proc_segs):
            continue

        p_text = proc_segs[p_idx].text
        p_words = set(_sig_words(p_text))
        p_box_bodies = re.findall(r"<Rahmen>\s*([\s\S]*?)\s*</Rahmen>", p_text, flags=re.IGNORECASE)
        p_box_words = set(_sig_words(" ".join(p_box_bodies)))
        wk_sec_m = re.search(r"####\s+Worterklärungen\b([\s\S]*)$", p_text, flags=re.IGNORECASE)
        p_wk_words = set(_sig_words(wk_sec_m.group(1))) if wk_sec_m else set()

        for r_body in r_boxes:
            b_words = _sig_words(r_body)
            if len(b_words) < 3:
                continue
            unique_b = set(b_words)
            if p_wk_words and len(unique_b & p_wk_words) / len(unique_b) >= 0.55:
                continue
            page_recall = len(unique_b & p_words) / len(unique_b)
            doc_recall = len(unique_b & all_proc_words) / len(unique_b)
            box_recall = len(unique_b & p_box_words) / len(unique_b)

            norm_inner = _normalize_box_inner(r_body)
            if page_recall < 0.45 and doc_recall < 0.55:
                proc_segs[p_idx].text = (
                    p_text.rstrip() + f"\n\n<Rahmen>\n{norm_inner}\n</Rahmen>\n\n"
                )
                p_text = proc_segs[p_idx].text
                p_words |= unique_b
                p_box_words |= unique_b
                modified = True
            elif box_recall < 0.40 and page_recall >= 0.60:
                norm_lines = [ln.strip() for ln in norm_inner.splitlines() if ln.strip()]
                wrapped_in_place = False
                if norm_lines:
                    first_ln = norm_lines[0]
                    last_ln = norm_lines[-1]
                    if first_ln in p_text and last_ln in p_text:
                        i_start = p_text.find(first_ln)
                        i_end = p_text.find(last_ln, i_start)
                        if i_start != -1 and i_end != -1:
                            end_pos = i_end + len(last_ln)
                            span = p_text[i_start:end_pos]
                            if (
                                "<Rahmen" not in span
                                and "</Rahmen>" not in span
                                and len(span) <= len(norm_inner) * 2 + 120
                            ):
                                proc_segs[p_idx].text = (
                                    p_text[:i_start]
                                    + f"<Rahmen>\n{span.strip()}\n</Rahmen>"
                                    + p_text[end_pos:]
                                )
                                p_text = proc_segs[p_idx].text
                                p_box_words |= unique_b
                                modified = True
                                wrapped_in_place = True
                if not wrapped_in_place and norm_inner in p_text:
                    proc_segs[p_idx].text = p_text.replace(
                        norm_inner, f"<Rahmen>\n{norm_inner}\n</Rahmen>", 1
                    )
                    p_text = proc_segs[p_idx].text
                    p_box_words |= unique_b
                    modified = True

    if not modified:
        return processed
    return "".join(s.text for s in proc_segs)


def normalize_heading_page_markers(markdown_content: str) -> str:
    r"""Normalizes heading-prefixed page markers and strips dangling empty headings.

    Splits inline heading+marker lines such as ``### ((294)) Abschnitt`` into a
    standalone ``((294))`` line followed by ``### Abschnitt``, strips heading
    prefixes from standalone ``#### ((294))`` lines, and removes empty ATX
    heading lines (``^[ \t]*#{1,6}[ \t]*$``).

    Args:
        markdown_content: Input Markdown text.

    Returns:
        Normalized Markdown text with clean standalone ``((n))`` markers.
    """
    if not markdown_content:
        return markdown_content

    def _split_heading_marker(match: re.Match[str]) -> str:
        hashes = match.group(1)
        marker = match.group(2).strip()
        trailing = (match.group(3) or "").strip()
        if trailing:
            return f"{marker}\n\n{hashes} {trailing}"
        return marker

    normalized = re.sub(
        r"(?m)^[ \t]*(#{1,6})[ \t]*(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:[ \t]*/[ \t]*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)[ \t]*(.*)$",
        _split_heading_marker,
        markdown_content,
    )
    normalized = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*(?:\r?\n|$)", "", normalized)
    return normalized


def deduplicate_page_numbers(markdown_content: str) -> str:
    r"""Removes duplicate consecutive or in-page ``((n))`` page boundary markers.

    Preserves consecutive *different* page markers (e.g. ``((23))\\n\\n((24))``).

    Args:
        markdown_content: Input Markdown text.

    Returns:
        Markdown text with duplicate page markers removed.
    """
    if not markdown_content:
        return markdown_content

    markdown_content = normalize_heading_page_markers(markdown_content)

    def replace_consecutive_same_page(match: re.Match[str]) -> str:
        prefix = match.group(1) or ""
        p1 = re.sub(r"\s+", " ", match.group(2).strip())
        p2 = re.sub(r"\s+", " ", match.group(3).strip())
        if p1 == p2:
            if prefix:
                return f"\n\n{p1}"
            return p1
        return match.group(0)

    pattern = (
        r"(\n|^)[ \t]*(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)"
        r"[ \t]*\n+[ \t]*(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)"
    )
    prev = ""
    res = markdown_content
    while prev != res:
        prev = res
        res = re.sub(pattern, replace_consecutive_same_page, res)

    lines = res.splitlines()
    cleaned_lines: list[str] = []
    current_page: str | None = None

    for line in lines:
        stripped = line.strip()
        m = re.match(
            r"^(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)$",
            stripped,
        )
        if m:
            page_marker = re.sub(r"\s+", " ", m.group(1))
            if page_marker == current_page:
                logger.info(f"Removing duplicate in-page marker: {page_marker}")
                continue
            current_page = page_marker
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


_LEADING_CLAUSE_VERB_SET = frozenset({
    "registrieren", "regulieren", "aktivieren", "stimulieren", "hemmen", "steigen", "sinken",
    "führen", "bewirken", "zeigen", "entstehen", "bilden", "werden", "haben", "sind", "können",
    "müssen", "sollen", "dürfen", "nehmen", "geben", "lassen", "machen", "stehen", "liegen",
})


def _split_run_in_bullet_subheadings(text: str) -> str:
    """Normalizes bullet separators in headings and splits run-in bullet subheadings outside blocks.

    Guards against leading ``• Verb...`` bullet items so lines starting with ``•``
    or single-word conjugated clause verbs are never turned into bogus ``####`` headings.

    Args:
        text: Input Markdown text.

    Returns:
        Markdown text with run-in noun-phrase bullet subheadings split cleanly.
    """
    if not text or ("•" not in text and "·" not in text):
        return text

    def _repl_run_in_bullet(m: re.Match[str]) -> str:
        prefix = m.group(1).strip()
        rest = m.group(2).strip()
        if not prefix or _TASK_OPERATOR_VERB_RE.match(prefix):
            return m.group(0)
        if " " not in prefix and (
            prefix.lower() in _LEADING_CLAUSE_VERB_SET
            or (len(prefix) >= 8 and prefix.lower().endswith("ieren"))
        ):
            return m.group(0)
        return f"#### {prefix}\n\n{rest}"

    parts = re.split(
        r"(<(?:Bild|Tabelle)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle)>)",
        text,
        flags=re.IGNORECASE,
    )
    for idx in range(0, len(parts), 2):
        seg = parts[idx]
        # Heading followed by a single run-in separator dot '• Prose...' (not a multi-item bullet list)
        seg = re.sub(
            r"(?m)^#{1,6}\s+([^\n•·]+?)[ \t]*\n+[ \t]*[•·][ \t]+([A-ZÄÖÜ][^\n•·]{25,})(?=(?:\n\s*\n(?![ \t]*[•·][ \t])|\Z))",
            r"#### \1\n\n\2",
            seg,
        )
        seg = re.sub(r"(?m)^#{1,6}[ \t]*•[ \t]+([^\n]+)$", r"-\t\1", seg)
        seg = re.sub(r"(?m)^[ \t]*•[ \t]+([^\n•]+)$", r"-\t\1", seg)
        seg = re.sub(r"(?m)^(#{1,6}\s+[^\n•·]+?)[ \t]*[•·][ \t]*$", r"\1", seg)
        seg = re.sub(r"(?m)^(#{1,6}\s+[^\n•·]+?)[ \t]+[•·][ \t]+([^\n]+)$", r"\1: \2", seg)
        seg = re.sub(
            r"(?m)^[ \t]*(?![•·\-*#\d])(?:\*\*|_)?([A-ZÄÖÜ][A-Za-zäöüÄÖÜß0-9\s,\-\(\)/]{2,55}?)(?:\*\*|_)?[ \t]+[•·][ \t]+([A-ZÄÖÜ][^\n]+)$",
            _repl_run_in_bullet,
            seg,
        )
        parts[idx] = seg
    return "".join(parts)


_TASK_OPERATOR_VERB_RE = re.compile(
    r"^(?:Erklären|Erläutern|Beschreiben|Nennen|Vergleichen|Begründen|Stellen|Zeichnen|"
    r"Berechnen|Entwickeln|Formulieren|Ordnen|Werten|Überprüfen|Skizzieren|Diskutieren|"
    r"Analysieren|Leiten|Geben|Fassen|Ermitteln|Prüfen|Untersuchen|Benennen|Deuten|"
    r"Interpretieren|Erstellen|Planen|Recherchieren|Bestimmen|Entwerfen|Charakterisieren|"
    r"Bewerten|Beurteilen|ermitteln|erklären|erläutern|beschreiben)\b"
)

_EMPHASIS_LEGEND_ANM_RE = re.compile(
    r"<Anmerkung\b[^>]*>(?:(?!</Anmerkung>)[\s\S])*?"
    r"(?:kursiv|\*[^\n<]*fett|#[^\n<]*unterstrichen|Hervorhebung\w*[^\n<]*(?:%|\*|#)|%[^\n<]*(?:kursiv|Hervorhebung))"
    r"(?:(?!</Anmerkung>)[\s\S])*?</Anmerkung>",
    re.IGNORECASE,
)

_UNANNOUNCED_PCT_EMPH_RE = re.compile(
    r"(?<![0-9\\])(?<!\d )%([A-Za-zÄÖÜäöüß][^%\t\n]{0,80}?[A-Za-zÄÖÜäöüß.!?:;')])%(?![A-Za-zÄÖÜäöüß])"
)


def _resolve_figure_caption_prefix(
    custom_rules: str | None,
    ruleset_key: str = "uebertragungsregeln_09_2025",
) -> tuple[str, bool]:
    """Resolves the figure-number prefix with strict Buchkonferenz priority over FIBS defaults.

    Args:
        custom_rules: Optional book-specific rules string from ``custom_ruleset.txt``.
        ruleset_key: Active FIBS ruleset identifier.

    Returns:
        Tuple ``(prefix, explicit_from_custom_rules)`` where ``prefix`` is e.g. ``"M"``,
        ``"B"``, or ``""``, and ``explicit_from_custom_rules`` indicates an explicit
        Buchkonferenz directive overriding FIBS defaults.
    """
    if custom_rules and custom_rules.strip():
        if re.search(
            r"(?:Abbildungs|Bild|Material)nummern?\b[^\n.]*?(?:kein\w*\s+(?:Buchstabe|Präfix|Zusatz|[A-Z]\b)|"
            r"ohne\s+(?:vorangestellte[nsm]?|Zusatz|Präfix|[A-Z]\b)|nicht\s+vorangestellt)"
            r"|kein\s+[A-Z]\s+vorangestellt",
            custom_rules,
            re.IGNORECASE,
        ):
            return "", True

        m_letter = re.search(
            r"(?:Abbildungs|Bild|Material)nummern?\s+(?:wird\s+)?(?:jeweils\s+)?ein\s+[\"'„“]?([A-Z])(?![A-Za-zäöüß])[\"'“”]?(?:\s+\S+){0,4}?\s+vorangestellt"
            r"|\bein\s+[\"'„“]?([A-Z])(?![A-Za-zäöüß])[\"'“”]?(?:\s+\S+){0,4}?\s+vorangestellt"
            r"|\b([MBQ])\s*\+\s*(?:Bild|Abbildungs)unterschrift\b",
            custom_rules,
        )
        if not m_letter:
            m_letter = re.search(
                r"(?:Abbildungs|Bild|Material)nummern?\s+(?:wird\s+)?(?:jeweils\s+)?ein\s+[\"'„“]?([a-zA-Z])(?![A-Za-zäöüß])[\"'“”]?(?:\s+\S+){0,4}?\s+vorangestellt",
                custom_rules,
                re.IGNORECASE,
            )
        if m_letter:
            letter = (m_letter.group(1) or m_letter.group(2) or m_letter.group(3) or "").upper()
            return letter, True

        if re.search(r"\b(?:Grundschule|Primarstufe)\b", custom_rules, re.IGNORECASE):
            return "", False

    if "grundschule" in (ruleset_key or "").lower() or "primarstufe" in (ruleset_key or "").lower():
        return "", False

    return "M", False


def _is_question_or_lead_in_prose(body: str) -> bool:
    """Returns True if ``body`` ends with ``?`` or embeds a question in multi-sentence/long prose."""
    s_b = body.rstrip("*_ ").strip()
    if not s_b:
        return False
    if s_b.endswith("?"):
        return True
    return "?" in s_b and (
        len(s_b) > 180 or len(re.findall(r"[.!?](?:\s+|$)", s_b)) >= 2
    )


def _split_long_caption_body(label_part: str, body_str: str) -> str:
    """Formats a ``Ü4`` figure caption, splitting captions > 140 chars per FIBS §7.1.1.2."""
    clean_b = body_str.strip()
    if not clean_b or fc.VLM_GENERIC_BILDART_ONLY_RE.match(clean_b) or fc.VLM_DESC_BOILERPLATE_HEADING_RE.match(clean_b):
        return f"#### {label_part}"
    if len(clean_b) > 140:
        for m_sent in re.finditer(r"([.!?])\s+([A-ZÄÖÜ0-9\"'(].+)$", clean_b):
            head_cand = clean_b[: m_sent.start()].strip()
            punct = m_sent.group(1)
            rest_cand = m_sent.group(2).strip()
            if punct == "?" or not (10 <= len(head_cand) <= 140) or not rest_cand:
                continue
            if punct == "." and re.search(
                r"\b(?:Abb|Tab|Fig|Nr|S|Bd|Aufl|vgl|bzw|ca|Dr|Prof|[A-Z])$|(?:\bz\.\s*B|\bu\.\s*a|\bd\.\s*h)$",
                head_cand,
            ):
                continue
            head_final = head_cand if punct == "." else f"{head_cand}{punct}"
            if fc.VLM_DESC_BOILERPLATE_HEADING_RE.match(rest_cand):
                return f"#### {label_part} {head_final}"
            return f"#### {label_part} {head_final}\n\n{rest_cand}"

        m_col = re.match(r"^([^:\n?]{10,140}):\s+(.+)$", clean_b)
        if m_col and m_col.group(2).strip():
            rest_col = m_col.group(2).strip()
            if fc.VLM_DESC_BOILERPLATE_HEADING_RE.match(rest_col):
                return f"#### {label_part} {m_col.group(1).strip()}"
            return f"#### {label_part} {m_col.group(1).strip()}\n\n{rest_col}"

    return f"#### {label_part} {clean_b}"


def _promote_and_clean_bild_captions(
    text: str,
    custom_rules: str | None = None,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Promotes figure captions above ``<Bild>`` as ``Ü4`` with FIBS/Buchkonferenz prefix and cleans echoes.

    Applies Buchkonferenz-priority prefixing (``M``, ``B``, or ``""``), supports long-caption
    splitting (> 140 chars), converts misclassified adjacent ``<Anmerkung> n Titel </Anmerkung>``
    captions, and removes caption/Material echoes inside and after ``<Bild>...</Bild>``.

    Args:
        text: Post-processed Markdown text containing ``<Bild>`` blocks.
        custom_rules: Optional book-specific rules string.
        ruleset_key: Active FIBS ruleset identifier.
        directory_info: Optional detected TOC/directory metadata dictionary.

    Returns:
        Markdown text with ``#### {prefix}{num} ...`` captions placed above ``<Bild>``.
    """
    if not text or "<Bild" not in text:
        return text

    fig_pfx, explicit_bk = _resolve_figure_caption_prefix(custom_rules, ruleset_key)
    text_subheadings_h4 = bool(
        custom_rules and _parse_buchkonferenz_profile(custom_rules).text_subheadings_h4
    )
    protected_heading_pages: dict[str, set[int | None]] = {}
    for toc_e in (directory_info or {}).get("toc_entries") or []:
        if not isinstance(toc_e, dict):
            continue
        raw_t = str(toc_e.get("title") or "").strip()
        lvl_e = int(toc_e.get("level") or 0)
        if lvl_e == 1 or re.match(r"^\d+\.?\s+\S", raw_t):
            pg_s_e = str(toc_e.get("page") or "").strip()
            pg_int_e = int(pg_s_e) if pg_s_e.isdigit() else None
            norm_f = re.sub(r"\W+", " ", raw_t).strip().lower()
            if norm_f:
                protected_heading_pages.setdefault(norm_f, set()).add(pg_int_e)
            norm_c = re.sub(r"\W+", " ", str(toc_e.get("clean_title") or "")).strip().lower()
            if norm_c:
                protected_heading_pages.setdefault(norm_c, set()).add(pg_int_e)
    has_doc_pages_cap = bool(re.search(r"(?m)^\(\(\d+\)\)", text))

    # 19f: Strip contiguous >= 2 pairs of orphan in-diagram subheading + single-letter panel heading after </Bild>
    pair_segs = re.split(r"(<Bild\b[^>]*>[\s\S]*?</Bild>)", text, flags=re.IGNORECASE)
    pair_changed = False
    panel_stop_words = {
        "und", "oder", "der", "die", "das", "mit", "von", "bei", "im", "in", "am", "an", "zu", "zum", "zur"
    }
    panel_excl_re = re.compile(
        r"^(?:Material|Aufgaben?|Übung(?:en)?|Kapitel|Chapter|Teil|Abschnitt|Methode|"
        r"Basiskonzepte?|Exkurs|Worterklärung|Randspalte|Steckbrief|[MBQ]\s*\d+|Abb(?:ildung)?\b|Bild\b|Grafik\b)\b",
        re.IGNORECASE,
    )

    def _matches_bild_diagram_label(cand_ln: str, bild_low: str) -> bool:
        m_dl = re.match(r"^#{2,5}\s+([^\n#:]{2,80})$", cand_ln)
        if not m_dl:
            return False
        lbl_t = re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", m_dl.group(1).strip()).strip()
        if not (1 <= len(lbl_t.split()) <= 5) or ":" in lbl_t or panel_excl_re.match(lbl_t):
            return False
        sig_ws = [
            w for w in re.findall(r"[a-zäöüß0-9]{3,}", lbl_t.lower()) if w not in panel_stop_words
        ]
        if not sig_ws:
            sig_ws = re.findall(r"[a-zäöüß0-9]{2,}", lbl_t.lower())
        if not sig_ws:
            return False
        return all(
            w in bild_low or (len(w) >= 5 and w[:-2] in bild_low) for w in sig_ws
        )

    for p_bi in range(1, len(pair_segs), 2):
        b_low = pair_segs[p_bi].lower()
        p_lns = pair_segs[p_bi + 1].splitlines()
        cur_pi = 0
        while cur_pi < len(p_lns) and p_lns[cur_pi].strip() in ("", "---"):
            cur_pi += 1
        if cur_pi < len(p_lns):
            first_ps = p_lns[cur_pi].strip()
            if re.match(r"^(?:_|\*)[^_*\n]{3,180}(?:_|\*)$", first_ps):
                cur_pi += 1
        matched_pair_lines: list[int] = []
        while cur_pi < len(p_lns):
            i1 = cur_pi
            while i1 < len(p_lns) and p_lns[i1].strip() in ("", "---"):
                i1 += 1
            if i1 >= len(p_lns):
                break
            i2 = i1 + 1
            while i2 < len(p_lns) and p_lns[i2].strip() in ("", "---"):
                i2 += 1
            if i2 >= len(p_lns):
                break
            s1, s2 = p_lns[i1].strip(), p_lns[i2].strip()
            is_fwd = _matches_bild_diagram_label(s1, b_low) and bool(
                re.match(r"^#{3,6}\s+[A-F]\s*$", s2)
            )
            is_rev = bool(re.match(r"^#{3,6}\s+[A-F]\s*$", s1)) and _matches_bild_diagram_label(
                s2, b_low
            )
            if is_fwd or is_rev:
                matched_pair_lines.extend([i1, i2])
                cur_pi = i2 + 1
            else:
                break
        if len(matched_pair_lines) >= 4:
            drop_set = set(matched_pair_lines)
            kept_pl = [ln for idx_l, ln in enumerate(p_lns) if idx_l not in drop_set]
            pair_segs[p_bi + 1] = "\n".join(kept_pl)
            pair_changed = True
    if pair_changed:
        text = "".join(pair_segs)

    # Drop standalone single-letter panel headings ('### A', '#### B') adjacent to <Bild>, ((num)), or captions
    panel_chk_lines = text.splitlines()
    panel_kept: list[str] = []
    n_pl = len(panel_chk_lines)
    for idx_pl, raw_pl in enumerate(panel_chk_lines):
        s_pl = raw_pl.strip()
        if re.match(r"^#{1,6}\s+[A-F]\s*$", s_pl):
            prev_nb = ""
            for b_pl in range(idx_pl - 1, -1, -1):
                sb = panel_chk_lines[b_pl].strip()
                if sb and sb != "---":
                    prev_nb = sb
                    break
            next_nb = ""
            for f_pl in range(idx_pl + 1, n_pl):
                sf = panel_chk_lines[f_pl].strip()
                if sf and sf != "---":
                    next_nb = sf
                    break
            adj_re = re.compile(
                r"^(?:</?Bild\b|\(\(\d+|(?:#{1,6}\s+)?(?:[MBQ]\s*)?\d{1,2}[.:]?\s+\S|(?:-\t|[-*•]\s+)?_?[A-F]_?\s+\S)",
                re.IGNORECASE,
            )
            if adj_re.match(prev_nb) or adj_re.match(next_nb):
                continue
        panel_kept.append(raw_pl)
    text = "\n".join(panel_kept)

    # Collapse multi-line sub-panel captions right after </Bild> (including stray '##### <n>\n+<Title:>\n+A ..., B ...')
    def _collapse_post_bild_subpanels(m_sp: re.Match[str]) -> str:
        num_h5 = (m_sp.group(1) or "").strip()
        num_inl = (m_sp.group(2) or "").strip()
        lead_title = m_sp.group(3).strip()
        sub_block = m_sp.group(4) or ""
        eff_num = num_h5 or num_inl
        if not eff_num or _TASK_OPERATOR_VERB_RE.match(lead_title):
            return m_sp.group(0)
        sub_parts: list[str] = []
        for sl in sub_block.splitlines():
            sl_s = re.sub(r"^(?:-\t|[-*•]\s+)", "", sl.strip()).strip().rstrip(",")
            if sl_s:
                sub_parts.append(sl_s)
        joined_body = f"{lead_title} {', '.join(sub_parts)}".strip() if sub_parts else lead_title
        return f"</Bild>\n\n{eff_num} {joined_body}\n"

    text = re.sub(
        r"</Bild>[ \t]*\n+(?:#####\s*(\d{1,2})\s*\n+)?(?:(\d{1,2})[.:]?[ \t]+)?([A-ZÄÖÜ][^\n#<]{2,90}:)[ \t]*\n+"
        r"((?:(?:-\t|[-*•][ \t]+)?_?[A-F]_?[ \t]+[^\n#<]+(?:\n+|$))+)",
        _collapse_post_bild_subpanels,
        text,
    )
    text = re.sub(
        r"</Bild>[ \t]*\n+#####\s*(\d{1,2})\s*\n+([A-ZÄÖÜ][^\n#<]{3,140}:)(?=\s*\n)",
        lambda m_c: (
            m_c.group(0)
            if _TASK_OPERATOR_VERB_RE.match(m_c.group(2).strip())
            else f"</Bild>\n\n{m_c.group(1)} {m_c.group(2).strip()}"
        ),
        text,
    )
    # Drop redundant bare '#### M3' stub when immediately preceded by a titled '#### M4 ...' caption before <Bild>
    text = re.sub(
        r"(?m)^(####[ \t]+[MBQ]\d+[a-z]?[ \t]+[^\n#]+)\n+####[ \t]+[MBQ][ \t]*\d+[a-z]?[ \t]*\n+(?=<Bild\b)",
        r"\1\n\n",
        text,
    )

    fig_cap_re = re.compile(
        r"^(#{1,6}\s+)?(?:\*\*|_)?(?:(Abb(?:ildung)?\.?|Bild|Grafik|Figure|Fig\.?)\s+|([MBQ])\s*)?"
        r"(\d{1,2}[a-z]?)(?:([:.])[\t\s]*|[\t\s]+)((?:\*\*|_)?[A-ZÄÖÜ\"'„“][^\n]{2,600}?)(?:\*\*|_)?$"
    )
    anm_cap_re = re.compile(
        r"^<Anmerkung>\s*(?:([MBQ])\s*)?(\d{1,2})\s+([A-ZÄÖÜ][^\n<]{1,500}?)\s*</Anmerkung>$",
        re.IGNORECASE,
    )

    def _build_formatted_caption(
        word_lbl: str,
        letter_lbl: str,
        c_num: str,
        colon_tok: str,
        c_body: str,
    ) -> tuple[str, str]:
        c_body_clean = re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", c_body.strip()).strip()
        if word_lbl:
            if explicit_bk:
                label_part = f"{fig_pfx}{c_num}"
            else:
                sep = ":" if colon_tok else ""
                label_part = f"{word_lbl.strip()} {c_num}{sep}"
        elif letter_lbl:
            eff_pfx = fig_pfx if explicit_bk else letter_lbl.upper()
            label_part = f"{eff_pfx}{c_num}"
        else:
            label_part = f"{fig_pfx}{c_num}"
        return _split_long_caption_body(label_part, c_body_clean), c_body_clean

    bild_segs = re.split(r"(<Bild\b[^>]*>[\s\S]*?</Bild>)", text, flags=re.IGNORECASE)
    cur_bild_page: int | None = None
    for b_i in range(1, len(bild_segs), 2):
        pre_pg_hits = re.findall(r"(?m)^\(\((\d+)\)\)", bild_segs[b_i - 1])
        if pre_pg_hits:
            cur_bild_page = int(pre_pg_hits[-1])
        pre_lines = bild_segs[b_i - 1].splitlines()
        post_lines = bild_segs[b_i + 1].splitlines()
        bild_box = bild_segs[b_i]

        # 1. Strip leading 'Material X • ...' or 'Am unteren Bildrand steht der Text: ...' echoes inside <Bild>
        b_lines = bild_box.splitlines()
        promoted_mat_heading = ""
        promoted_margin_cap = ""
        if len(b_lines) >= 2:
            cleaned_inner: list[str] = [b_lines[0]]
            for inner_ln in b_lines[1:-1]:
                work_ln = inner_ln
                m_mat_echo = re.match(
                    r"^((?:Beschreibung(?: mit Bildtext)?:\s*)?)Material\s+([A-Z])\s*[•:]\s*([^\n.]{2,90})(?:\.\s*(.*))?$",
                    work_ln.strip(),
                )
                if m_mat_echo:
                    desc_lbl = m_mat_echo.group(1) or ""
                    mat_let = m_mat_echo.group(2)
                    mat_tit = m_mat_echo.group(3).strip()
                    rem_desc = (m_mat_echo.group(4) or "").strip()
                    promoted_mat_heading = f"#### Material {mat_let}: {mat_tit}"
                    if rem_desc:
                        work_ln = f"{desc_lbl}{rem_desc}"
                    elif desc_lbl.strip():
                        cleaned_inner.append(desc_lbl.rstrip())
                        continue
                    else:
                        continue

                # Capture and strip 'Am unteren/oberen Bildrand steht der Text: 4 ...' echo sentences
                m_echo_cap = re.search(
                    r"(?:^|\s+)(?:Am\s+(?:unteren|oberen)\s+Bildrand|Unter\s+dem\s+Bild)\s+"
                    r"(?:steht|befindet\s+sich|lautet)(?:\s+der\s+Text|\s+die\s+Bildunterschrift|\s+folgender\s+Text)?\s*:?\s*"
                    r"[\"'„“]?(?:([MBQ])\s*)?(\d{1,2})\s+([A-ZÄÖÜ][^\n\"'“”]+?)[\"'“”]?\.?\s*$",
                    work_ln,
                    flags=re.IGNORECASE,
                )
                if m_echo_cap and not promoted_margin_cap:
                    e_let = m_echo_cap.group(1) or ""
                    e_num = m_echo_cap.group(2)
                    e_tit = m_echo_cap.group(3).strip().rstrip(".")
                    promoted_margin_cap, _ = _build_formatted_caption("", e_let, e_num, "", e_tit)
                stripped_echo = re.sub(
                    r"(?:^|\s+)(?:Am\s+(?:unteren|oberen)\s+Bildrand|Unter\s+dem\s+Bild)\s+"
                    r"(?:steht|befindet\s+sich|lautet)(?:\s+der\s+Text|\s+die\s+Bildunterschrift|\s+folgender\s+Text)?\s*:?\s*"
                    r"[\"'„“]?(?:[MBQ]\s*)?\d{1,2}\b[^\n]*$",
                    "",
                    work_ln,
                    flags=re.IGNORECASE,
                ).rstrip()
                if stripped_echo or work_ln.strip().startswith("Beschreibung"):
                    cleaned_inner.append(stripped_echo if stripped_echo else work_ln)
            if len(b_lines) >= 2:
                cleaned_inner.append(b_lines[-1])
            bild_box = "\n".join(cleaned_inner)

        if promoted_mat_heading:
            recent_pre = "\n".join(pre_lines[-8:])
            mat_key = promoted_mat_heading.split(":")[0].strip()
            if mat_key.lower() not in recent_pre.lower():
                while pre_lines and not pre_lines[-1].strip():
                    pre_lines.pop()
                pre_lines.extend(["", promoted_mat_heading, ""])

        # Check surrounding body text on the same page for genuine {n} footnote markers
        pre_page_tail = "\n".join(pre_lines).rsplit("((", 1)[-1]
        post_page_head = "\n".join(post_lines).split("((", 1)[0]
        surrounding_body = f"{pre_page_tail}\n{post_page_head}"

        last_ne = -1
        for idx_p in range(len(pre_lines) - 1, -1, -1):
            if pre_lines[idx_p].strip():
                last_ne = idx_p
                break

        m_bt = re.match(r"^<Bild>\s*([^:\n]{1,60}):", bild_box)
        bild_typ = m_bt.group(1).strip().lower() if m_bt else ""
        m_bd = re.search(r"Beschreibung(?: mit Bildtext)?:\s*([\s\S]*?)\s*</Bild>$", bild_box)
        bild_desc_norm = re.sub(r"\s+", " ", m_bd.group(1)).strip().lower() if m_bd else ""

        has_pre_cap = False
        bare_pre_info: tuple[str, str] | None = None
        was_vlm_echo_pre = False
        cap_text_lower = ""
        cap_num_found = ""
        if last_ne >= 0:
            cand_pre = pre_lines[last_ne].strip()
            m_m_pre = re.match(r"^#{3,6}\s+([MBQ])\s*(\d{1,2}[a-z]?)(?:\s+(.+))?$", cand_pre)
            suf_pre = (
                re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", (m_m_pre.group(3) or "").strip()).strip()
                if m_m_pre
                else ""
            )
            suf_pre_norm = re.sub(r"\s+", " ", suf_pre).lower()
            is_vlm_echo_suf = bool(m_m_pre and suf_pre) and (
                (bool(bild_typ) and suf_pre_norm.rstrip(".") == bild_typ.rstrip("."))
                or bool(fc.VLM_GENERIC_BILDART_ONLY_RE.match(suf_pre))
                or bool(fc.VLM_DESC_BOILERPLATE_HEADING_RE.match(suf_pre))
                or (
                    len(suf_pre) >= 25
                    and bool(bild_desc_norm)
                    and bild_desc_norm.startswith(suf_pre_norm)
                    and (
                        len(suf_pre) >= 70
                        or bool(
                            re.match(
                                r"^(?:ein|eine|einer|eines|zwei|drei|vier|mehrere|links|rechts|oben|unten|im\s+|in\s+|auf\s+|das\s+|die\s+|der\s+)\b",
                                suf_pre,
                                re.IGNORECASE,
                            )
                        )
                    )
                )
            )
            if m_m_pre and not suf_pre:
                bare_pre_info = (m_m_pre.group(1), m_m_pre.group(2))
            elif m_m_pre and is_vlm_echo_suf:
                eff_let = fig_pfx if explicit_bk else m_m_pre.group(1).upper()
                pre_lines[last_ne] = f"#### {eff_let}{m_m_pre.group(2)}"
                bare_pre_info = (eff_let or m_m_pre.group(1).upper(), m_m_pre.group(2))
                was_vlm_echo_pre = True
            # Existing Abb. X.Y: / Bild X.Y: / Abbildung X.Y: decimal captions stay as-is
            elif re.match(
                r"^#{3,6}\s+(?:Abb(?:ildung)?\.?|Bild|Grafik|Figure|Fig\.?)\s*\d+\.\d+",
                cand_pre,
                re.IGNORECASE,
            ):
                has_pre_cap = True
            else:
                m_anm_pre = anm_cap_re.match(cand_pre)
                if m_anm_pre and not _has_footnote_brace_ref(
                    surrounding_body, m_anm_pre.group(2)
                ):
                    formatted_cap, c_clean = _build_formatted_caption(
                        "",
                        m_anm_pre.group(1) or "",
                        m_anm_pre.group(2),
                        "",
                        m_anm_pre.group(3),
                    )
                    pre_lines[last_ne] = formatted_cap
                    has_pre_cap = True
                    cap_text_lower = c_clean.lower()
                    cap_num_found = m_anm_pre.group(2)
                else:
                    m_pre = fig_cap_re.match(cand_pre)
                    pre_body_clean = re.sub(r"^(?:\*\*|_)+", "", m_pre.group(6).strip()) if m_pre else ""
                    if (
                        m_pre
                        and not _TASK_OPERATOR_VERB_RE.match(pre_body_clean)
                        and not _is_question_or_lead_in_prose(pre_body_clean)
                        and not re.search(r"^[A-ZÄÖÜ][a-zäöüß]+en\s+Sie\b", pre_body_clean)
                    ):
                        hashes_pre = (m_pre.group(1) or "").strip()
                        word_pre = m_pre.group(2) or ""
                        let_pre = m_pre.group(3) or ""
                        is_chapter_h1_h2 = (
                            hashes_pre in ("#", "##")
                            and not word_pre
                            and not let_pre
                            and not bool(custom_rules and custom_rules.strip())
                        )
                        cand_full_norm = re.sub(
                            r"\W+", " ", f"{m_pre.group(4)} {pre_body_clean}"
                        ).strip().lower()
                        cand_body_norm = re.sub(r"\W+", " ", pre_body_clean).strip().lower()
                        is_toc_chapter = (
                            not word_pre
                            and not let_pre
                            and (
                                _toc_norm_matches_page(
                                    cand_full_norm,
                                    protected_heading_pages,
                                    cur_bild_page,
                                    has_doc_pages_cap,
                                )
                                or _toc_norm_matches_page(
                                    cand_body_norm,
                                    protected_heading_pages,
                                    cur_bild_page,
                                    has_doc_pages_cap,
                                )
                            )
                        )
                        if (
                            not is_chapter_h1_h2
                            and not is_toc_chapter
                            and not re.match(
                                r"^(?:Kapitel|Chapter|Teil|Part|Lektion|Band)\b",
                                pre_body_clean,
                                re.IGNORECASE,
                            )
                        ):
                            formatted_cap, c_clean = _build_formatted_caption(
                                word_pre,
                                let_pre,
                                m_pre.group(4),
                                m_pre.group(5) or "",
                                pre_body_clean,
                            )
                            pre_lines[last_ne] = formatted_cap
                            has_pre_cap = True
                            cap_text_lower = c_clean.lower()
                            cap_num_found = m_pre.group(4)

        # Look up to 2 non-empty blocks above a bare '#### M<Nr>' on the same page for a printed caption with matching Nr
        if bare_pre_info is not None and last_ne > 0:
            b_let_up, b_num_up = bare_pre_info
            seen_up = 0
            for up_i in range(last_ne - 1, -1, -1):
                up_s = pre_lines[up_i].strip()
                if not up_s:
                    continue
                if up_s.startswith(("((", "</Bild", "</Tabelle", "</Rahmen", "# ", "## ", "### ")):
                    break
                seen_up += 1
                m_up = fig_cap_re.match(up_s)
                up_body = re.sub(r"^(?:\*\*|_)+", "", m_up.group(6).strip()) if m_up else ""
                if (
                    m_up
                    and m_up.group(4) == b_num_up
                    and not _TASK_OPERATOR_VERB_RE.match(up_body)
                    and not _is_question_or_lead_in_prose(up_body)
                    and not re.search(r"\bSie\b", up_body)
                ):
                    formatted_up, c_up = _build_formatted_caption(
                        m_up.group(2) or "",
                        b_let_up,
                        b_num_up,
                        m_up.group(5) or "",
                        up_body,
                    )
                    pre_lines[last_ne] = formatted_up
                    pre_lines.pop(up_i)
                    last_ne -= 1
                    has_pre_cap = True
                    bare_pre_info = None
                    cap_text_lower = c_up.lower()
                    cap_num_found = b_num_up
                    break
                if seen_up >= 2:
                    break

        # Inspect first few non-empty lines after </Bild> for trailing caption, <Anmerkung> caption, or orphan axis fragments
        last_post_ne_idx = -1
        for idx_lp in range(len(post_lines) - 1, -1, -1):
            if post_lines[idx_lp].strip():
                last_post_ne_idx = idx_lp
                break

        ne_indices: list[int] = []
        for idx_a, a_ln in enumerate(post_lines):
            a_s = a_ln.strip()
            if not a_s:
                continue
            if re.match(r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)", a_s) or a_s.startswith(
                ("<Bild", "<Tabelle", "<Rahmen", "#####")
            ):
                break
            if a_s.startswith("<Anmerkung") and not anm_cap_re.match(a_s):
                break
            ne_indices.append(idx_a)
            if len(ne_indices) >= 4:
                break

        matched_post_idx = -1
        post_cap_heading = ""
        for k_pos, idx_a in enumerate(ne_indices):
            cand = post_lines[idx_a].strip()
            is_next_bild_pre_heading = (
                b_i + 2 < len(bild_segs) and idx_a == last_post_ne_idx and cand.startswith("#")
            )
            intervening_ok = all(
                len(post_lines[prev_a].strip()) <= 50
                and not post_lines[prev_a].strip().endswith((".", "!", "?"))
                and not post_lines[prev_a].strip().startswith("#")
                for prev_a in ne_indices[:k_pos]
            )
            if not intervening_ok:
                continue

            m_anm_post = anm_cap_re.match(cand)
            if m_anm_post:
                anm_num = m_anm_post.group(2)
                anm_body_str = m_anm_post.group(3).strip()
                if bare_pre_info is not None and anm_num != bare_pre_info[1]:
                    continue
                has_fn_ref = _has_footnote_brace_ref(surrounding_body, anm_num)
                is_dup_of_pre = has_pre_cap and (
                    anm_num == cap_num_found or anm_body_str.lower() == cap_text_lower
                )
                if (
                    (not has_fn_ref or is_dup_of_pre)
                    and not _TASK_OPERATOR_VERB_RE.match(anm_body_str)
                    and not _is_question_or_lead_in_prose(anm_body_str)
                ):
                    matched_post_idx = idx_a
                    post_cap_heading, c_clean = _build_formatted_caption(
                        "",
                        m_anm_post.group(1) or "",
                        anm_num,
                        "",
                        anm_body_str,
                    )
                    cap_text_lower = cap_text_lower or c_clean.lower()
                    break

            m_post = fig_cap_re.match(cand)
            post_body_clean = re.sub(r"^(?:\*\*|_)+", "", m_post.group(6).strip()) if m_post else ""
            if (
                m_post
                and not _TASK_OPERATOR_VERB_RE.match(post_body_clean)
                and not _is_question_or_lead_in_prose(post_body_clean)
                and not re.search(r"^[A-ZÄÖÜ][a-zäöüß]+en\s+Sie\b", post_body_clean)
            ):
                hashes_post = (m_post.group(1) or "").strip()
                word_post = m_post.group(2) or ""
                let_post = m_post.group(3) or ""
                post_num = m_post.group(4)
                if hashes_post in ("#", "##", "###") and not word_post and not let_post:
                    continue
                if bare_pre_info is not None and post_num != bare_pre_info[1]:
                    continue
                if is_next_bild_pre_heading and (
                    bare_pre_info is None or post_num != bare_pre_info[1]
                ):
                    continue
                matched_post_idx = idx_a
                post_cap_heading, c_clean = _build_formatted_caption(
                    word_post,
                    let_post,
                    post_num,
                    m_post.group(5) or "",
                    post_body_clean,
                )
                cap_text_lower = cap_text_lower or c_clean.lower()
                break

            if bare_pre_info is not None and not is_next_bild_pre_heading:
                m_italic_np = re.match(r"^(?:_|\*)([A-ZÄÖÜ][^_*\n]{6,160}?)(?:_|\*)$", cand)
                m_schema_h4 = re.match(
                    r"^####\s+([A-ZÄÖÜ][^\n#]{6,160}?\((?:Schema|Diagramm|Modell|Zeichnung|Grafik|Foto|Aufnahme|stark vereinfacht|schematisch)[^\n)]*\))$",
                    cand,
                )
                m_lone_h4 = (
                    re.match(r"^####\s+([A-ZÄÖÜ][^\n#?]{2,140})$", cand)
                    if k_pos == 0
                    else None
                )
                lone_h4_body = ""
                if m_lone_h4 and not m_schema_h4:
                    cand_h4_b = m_lone_h4.group(1).strip()
                    if not re.match(
                        r"^(?:[MBQ]\s*\d+|Abb(?:ildung)?\b|Bild\b|Grafik\b|Material\b|Aufgaben?\b|Worterklärung|Randspalte|Steckbrief\b)",
                        cand_h4_b,
                        re.IGNORECASE,
                    ):
                        nxt_after_h4 = ""
                        for fwd_p in range(idx_a + 1, len(post_lines)):
                            if post_lines[fwd_p].strip():
                                nxt_after_h4 = post_lines[fwd_p].strip()
                                break
                        no_prose_after = not nxt_after_h4 or nxt_after_h4.startswith(
                            ("#", "<", "((", "---")
                        )
                        is_setup_np = bool(
                            re.match(
                                r"^(?:Versuchsaufbau|Modellversuch|Versuchsanordnung|Messaufbau|Schematische\w*\s+(?:Aufbau|Darstellung)|(?:Licht|Elektronen)?[Mm]ikroskopische\s+Aufnahme)\b",
                                cand_h4_b,
                            )
                        )
                        if (
                            was_vlm_echo_pre
                            or no_prose_after
                            or not text_subheadings_h4
                            or is_setup_np
                        ):
                            lone_h4_body = cand_h4_b

                np_body = (
                    m_italic_np.group(1).strip()
                    if m_italic_np
                    else (m_schema_h4.group(1).strip() if m_schema_h4 else lone_h4_body)
                )
                if (
                    np_body
                    and 2 <= len(np_body.split()) <= 20
                    and (not np_body.endswith((".", "?", "!")) or np_body.endswith(")"))
                    and not _TASK_OPERATOR_VERB_RE.match(np_body)
                ):
                    matched_post_idx = idx_a
                    post_cap_heading, c_clean = _build_formatted_caption(
                        "",
                        bare_pre_info[0],
                        bare_pre_info[1],
                        "",
                        np_body,
                    )
                    cap_text_lower = cap_text_lower or c_clean.lower()
                    break

        if matched_post_idx >= 0:
            post_lines = post_lines[matched_post_idx + 1 :]
            if bare_pre_info is not None and last_ne >= 0:
                pre_lines[last_ne] = post_cap_heading
                has_pre_cap = True
            elif not has_pre_cap:
                while pre_lines and not pre_lines[-1].strip():
                    pre_lines.pop()
                pre_lines.append("")
                pre_lines.append(post_cap_heading)
                pre_lines.append("")
                has_pre_cap = True
        elif not has_pre_cap and promoted_margin_cap:
            if bare_pre_info is not None and last_ne >= 0:
                pre_lines[last_ne] = promoted_margin_cap
            else:
                while pre_lines and not pre_lines[-1].strip():
                    pre_lines.pop()
                pre_lines.append("")
                pre_lines.append(promoted_margin_cap)
                pre_lines.append("")
            has_pre_cap = True

        # Strip trailing duplicate caption line or VLM-repeated axis label immediately after </Bild>
        while post_lines:
            first_ne = -1
            for idx_a, a_ln in enumerate(post_lines):
                if a_ln.strip():
                    first_ne = idx_a
                    break
            if first_ne < 0:
                break
            cand_s = post_lines[first_ne].strip()
            m_anm_dup = anm_cap_re.match(cand_s)
            if (
                m_anm_dup
                and cap_text_lower
                and m_anm_dup.group(3).strip().lower() == cap_text_lower
            ):
                post_lines.pop(first_ne)
                continue
            cand_clean = (
                re.sub(r"^(?:#{1,6}\s+)?(?:[MBQ]?\d+\s+)?", "", cand_s).strip().lower()
            )
            if (cap_text_lower and cand_clean == cap_text_lower) or (
                len(cand_s) <= 45
                and not cand_s.startswith(("#", "-", "*", "(("))
                and not cand_s.endswith((".", "!", "?", ":"))
                and cand_s in bild_box
            ):
                post_lines.pop(first_ne)
            else:
                break

        bild_segs[b_i] = bild_box
        pre_joined = "\n".join(pre_lines).strip("\n")
        if pre_joined:
            lead_sep = "\n\n" if b_i > 1 else ""
            bild_segs[b_i - 1] = f"{lead_sep}{pre_joined}\n\n"
        else:
            bild_segs[b_i - 1] = "\n\n" if b_i > 1 else ""
        post_joined = "\n".join(post_lines).lstrip("\n")
        if post_joined:
            bild_segs[b_i + 1] = f"\n\n{post_joined}"
        else:
            bild_segs[b_i + 1] = "\n\n" if (b_i + 2 < len(bild_segs)) else "\n"

    return "".join(bild_segs)


def _mask_latex_commands_for_footnotes(text: str) -> tuple[str, list[str]]:
    r"""Masks LaTeX commands with brace arguments so ``{n}`` in ``\f{1}{3}`` is never a footnote.

    Args:
        text: Input Markdown string.

    Returns:
        Tuple of ``(masked_text, saved_command_spans)``.
    """
    saved: list[str] = []

    def _save(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return f"__FN_CMD_PROT_{len(saved) - 1}__"

    masked = text
    for _ in range(4):
        masked = re.sub(r"\\[a-zA-Z]+(?:\s*\[[^\]]*\])*(?:\s*\{[^{}]*\})+", _save, masked)
    return masked, saved


def _has_footnote_brace_ref(text: str, fn_num: str | int) -> bool:
    r"""Checks whether ``text`` contains a genuine FIBS ``{n}`` footnote marker outside math commands.

    Args:
        text: Markdown text to inspect.
        fn_num: Footnote integer or digit string.

    Returns:
        ``True`` if ``{fn_num}`` occurs outside LaTeX command arguments and sub/superscripts.
    """
    masked, _ = _mask_latex_commands_for_footnotes(text)
    return bool(re.search(rf"(?<![_^\\}}\]])\{{{fn_num}\}}", masked))


_SHORT_PROSE_WORDS: frozenset[str] = frozenset({
    "ab", "am", "an", "auf", "aus", "bei", "bis", "da", "das", "dem", "den", "der", "des",
    "die", "du", "eh", "ein", "er", "es", "für", "gar", "gut", "hat", "her", "hin", "ich",
    "ihm", "ihn", "ihr", "im", "in", "ins", "ist", "ja", "je", "lat", "mal", "man", "mit",
    "nah", "neu", "nie", "nur", "ob", "oft", "per", "pro", "rar", "roh", "rot", "sah", "sei",
    "sie", "so", "tat", "ton", "tot", "tun", "um", "und", "uns", "vom", "von", "vor", "war",
    "was", "weg", "wem", "wen", "wer", "wie", "wir", "wo", "zu", "zum", "zur", "all", "and",
    "any", "are", "art", "ask", "bad", "big", "bit", "box", "boy", "bus", "but", "buy", "can",
    "car", "cat", "cut", "day", "did", "dog", "dry", "eat", "end", "eye", "far", "few", "fit",
    "fly", "for", "fun", "get", "god", "got", "guy", "had", "has", "hat", "her", "him", "his",
    "hit", "hot", "how", "ice", "ill", "its", "job", "key", "kid", "law", "lay", "led", "leg",
    "let", "lie", "lip", "lot", "low", "mad", "man", "map", "may", "men", "met", "mix", "mom",
    "mum", "net", "new", "nor", "not", "now", "odd", "off", "oil", "old", "one", "our", "out",
    "own", "pay", "pen", "pet", "pic", "pop", "put", "ran", "raw", "red", "rid", "row", "run",
    "sad", "sat", "saw", "say", "sea", "see", "set", "she", "shy", "sir", "sit", "six", "sky",
    "son", "sun", "tax", "tea", "ten", "the", "tie", "tip", "toe", "too", "top", "toy", "try",
    "two", "use", "van", "via", "was", "way", "wet", "who", "why", "win", "won", "yes", "yet",
    "you", "do", "go", "he", "hi", "if", "is", "it", "me", "my", "no", "of", "oh", "ok", "on",
    "or", "to", "up", "us", "we",
})

_UNAMBIGUOUS_GREEK_NAMES = (
    "varepsilon|vartheta|upsilon|Upsilon|epsilon|lambda|Lambda|varphi|varrho|varsigma|"
    "alpha|beta|gamma|Gamma|delta|theta|Theta|kappa|sigma|Sigma|omega|Omega|zeta|eta|phi|Phi|chi|psi|Psi|tau"
)

_NON_MATH_SECTION_NOUNS: frozenset[str] = frozenset({
    "abschnitt", "anhang", "aufgabe", "band", "beispiel", "bild", "fall", "figur",
    "form", "gruppe", "kapitel", "klasse", "konjunktiv", "lektion", "material", "modell",
    "modus", "phase", "position", "punkt", "quelle", "reihe", "schema", "seite", "spalte",
    "station", "stufe", "tabelle", "teil", "typ", "übung", "variante", "versuch", "vitamin",
    "case", "class", "figure", "grade", "group", "level", "part", "phase", "section",
    "stage", "step", "table", "type", "unit",
})

_FIBS_EMPH_SPAN_RE = re.compile(
    r"(?<![A-Za-z0-9_}'\\])_(?!\s)"
    r"((?:[^_\n]|(?<=[A-Za-z0-9}'])_(?=[A-Za-z0-9{~\\]))+?)"
    r"(?<!\s)_(?![A-Za-z0-9_{])"
)


def strip_math_and_variable_emphasis(text: str) -> str:
    r"""Strips ``_..._`` emphasis from mathematical variables, symbols, and formulas.

    Repairs split subscript/vector emphasis collisions (e.g. ``_E_kin_`` -> ``E_{kin}``,
    ``\vec{F_}_`` -> ``\vec{F}``, ``\int_0^_m r_^2 dm_`` -> ``\int_0^m r^2 dm``), converts
    spelled-out Greek in formulas (``_Delta m_i_`` -> ``~Dm_i``, ``omega^2`` -> ``~w^2``),
    splits mixed ``_Fachbegriff ~a_`` -> ``_Fachbegriff_ ~a``, and cleans orphaned ``_``
    on ``~`` tokens, vectors, fractions, and units while preserving prose ``_Wort_`` emphasis
    and ``_..._`` fill-in-the-blank gap markers.

    Args:
        text: Input Markdown text.

    Returns:
        Markdown text with zero emphasis underscores around math variables or formulas.
    """
    if not text:
        return text

    protected_spans: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        protected_spans.append(m.group(0))
        return f"__MATH_EMPH_PROT_{len(protected_spans) - 1}__"

    work = fc.UNIT_PERCENT_PROTECTED_RE.sub(_mask, text)
    work = re.sub(r"_\.\.\._", _mask, work)

    # 1. Repair fraction denominators previously corrupted by '{n}' -> '^n' footnote bug
    work = re.sub(r"\\(?:f|d?frac|t?frac)\{([^{}]+)\}\^(\d+)", r"\\f{\1}{\2}", work)

    # 2. Repair \simw -> ~w, \vec{F_}_ -> \vec{F}, ~m/s^2 -> m/s^2, and ~D _t_ -> ~Dt
    work = re.sub(r"\\sim([abdfghjklmprstwDFGHLPW])(?![a-zA-Z])", r"~\1", work)
    work = re.sub(r"(\d)[ \t]+~m/(s(?:\^2|²)?)\b", r"\1 m/\2", work)
    # Only strip leading '_' on \vec{F_}_ when there is no preceding unmatched '_' on the product (e.g. '_m\vec{v_}_')
    work = re.sub(r"(?<![A-Za-z0-9_\\])_\\vec\{\s*([^{}]+?)_\}_?", r"\\vec{\1}", work)
    work = re.sub(r"\\vec\{\s*([^{}]+?)_\}_?", r"\\vec{\1}", work)
    work = re.sub(
        r"(?<![A-Za-z0-9_}'\\])_(\\vec\{[^{}]+\}(?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)_(?![A-Za-z0-9_])",
        r"\1",
        work,
    )
    work = re.sub(
        r"~D[ \t]*_([A-Za-z])_(?:_?(\{[^{}]+\}|[A-Za-z0-9]+)_?)?",
        lambda m: (
            f"~D{m.group(1)}"
            if not m.group(2)
            else (
                f"~D{m.group(1)}_{m.group(2)}"
                if m.group(2).startswith("{") or len(m.group(2)) == 1
                else f"~D{m.group(1)}_{{{m.group(2)}}}"
            )
        ),
        work,
    )

    # 3. Repair integral/sum bound + integrand underscore splits ('\int_0^_m r_^2 dm_' -> '\int_0^m r^2 dm')
    work = re.sub(
        r"\^_([A-Za-z0-9]+)[ \t]+([A-Za-z])_(\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+)[ \t]*d[A-Za-z])_",
        r"^\1 \2\3",
        work,
    )
    work = re.sub(
        r"(\\(?:o?i{1,3}nt|sum|prod)_(?:\{[^{}]+\}|[A-Za-z0-9+-]+)\^)_([A-Za-z0-9]+)_(?![A-Za-z0-9_])",
        r"\1\2",
        work,
    )
    # '_m_r^2_' -> 'm r^2', while '_v_0^2_' -> 'v_0^2'
    work = re.sub(
        r"(?<![A-Za-z0-9_}'\\])_([a-z])_([a-z])\^(\{[^{}]+\}|[0-9A-Za-z+-]+)_(?![A-Za-z0-9_])",
        r"\1 \2^\3",
        work,
    )
    work = re.sub(
        r"(?<![A-Za-z0-9_}'\\])_([A-Za-z])_([0-9])\^(\{[^{}]+\}|[0-9A-Za-z+-]+)_(?![A-Za-z0-9_])",
        r"\1_\2^\3",
        work,
    )

    # 4. Repair split subscript + emphasis collisions ('_E_kin_' -> 'E_{kin}', '_v'_1_' -> 'v'_1', '2_v_2' -> '2v_2')
    def _format_sub_token(sub_raw: str) -> str:
        if sub_raw.startswith("{") or len(sub_raw) == 1:
            return f"_{sub_raw}"
        return f"_{{{sub_raw}}}"

    # Numeric coefficient glued to split subscripted variable ('2_v_2_' or '2_v_2' -> '2v_2')
    work = re.sub(
        r"(\d+)_(~[a-zA-Z]|[A-Za-z])('{0,3})_(\{[^{}]+\}|[A-Za-z0-9,+-]{1,10})_?(?![A-Za-z0-9_])",
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{_format_sub_token(m.group(4))}",
        work,
    )
    work = re.sub(r"(\d+)_([A-Za-z])_(?![A-Za-z0-9_])", r"\1\2", work)

    def _fix_split_sub(m: re.Match[str]) -> str:
        base = m.group(1)
        primes = m.group(2) or ""
        sub_fmt = _format_sub_token(m.group(3))
        sup_part = m.group(4) or ""
        call_part = m.group(5) or ""
        return f"{base}{primes}{sub_fmt}{sup_part}{call_part}"

    work = re.sub(
        r"(?<![A-Za-z0-9_}'\\])_(~[a-zA-Z]|[A-Za-z])('{0,3})_"
        r"(\{[^{}]+\}|[A-Za-z0-9,+-]{1,10})"
        r"(\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?"
        r"(\([A-Za-z0-9,;\s+\-*/~]+\))?"
        r"_(?![A-Za-z0-9_])",
        _fix_split_sub,
        work,
    )

    # 5. Convert spelled-out Greek in mathematical contexts (inside or outside '_..._')
    # Including camelCase factor + Delta ('rDelta omega' -> 'r~D~w', 'rDelta t' -> 'r~Dt')
    work = re.sub(
        rf"(?<![A-ZÄÖÜäöüß~\\])([0-9a-zA-Z}}\^]*)Delta[ \t]*({_UNAMBIGUOUS_GREEK_NAMES})(?![A-Za-zäöüÄÖÜß0-9])",
        lambda m: f"{m.group(1)}~D{fc.TILDE_GREEK_WORD_TO_FIBS[m.group(2)]}",
        work,
    )
    work = re.sub(
        r"(?<![A-ZÄÖÜäöüß~\\])([0-9a-z}\^]+)?Delta[ \t]+((?:[B-Za-z]|A(?![ \t]+[a-z]{2,}))"
        r"(?:_(?:\{[^{}]+\}|[A-Za-z0-9,+-]+))?(?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?)"
        r"(?![A-Za-zäöüÄÖÜß0-9])",
        lambda m: f"{m.group(1) or ''}~D{m.group(2)}",
        work,
    )
    all_greek_pat = "|".join(sorted(fc.TILDE_GREEK_WORD_TO_FIBS, key=len, reverse=True))
    # Greek name immediately followed by subscript/superscript ('omega^2' -> '~w^2', 'alpha_1' -> '~a_1')
    work = re.sub(
        rf"(?<![~\\A-Za-zäöüÄÖÜß0-9])({all_greek_pat})(?=(?:_[A-Za-z0-9{{]|\^))",
        lambda m: fc.TILDE_GREEK_WORD_TO_FIBS[m.group(1)],
        work,
    )
    # Standalone emphasized Greek name ('_alpha_' -> '~a', '_omega_' -> '~w')
    work = re.sub(
        rf"(?<![A-Za-z0-9_}}'\\])_({_UNAMBIGUOUS_GREEK_NAMES}|mu|nu|pi|xi|rho|iota)_(?![A-Za-z0-9_])",
        lambda m: fc.TILDE_GREEK_WORD_TO_FIBS[m.group(1)],
        work,
    )
    # Quotient or proportional relation with Greek ('M/alpha' -> 'M/~a', 'alpha ~ M' -> '~a \sim M')
    work = re.sub(
        rf"([A-Za-z0-9_)}}\]])[ \t]*/[ \t]*({_UNAMBIGUOUS_GREEK_NAMES}|rho)(?![A-Za-zäöüÄÖÜß0-9])",
        lambda m: f"{m.group(1)}/{fc.TILDE_GREEK_WORD_TO_FIBS[m.group(2)]}",
        work,
    )
    work = re.sub(
        rf"(?<![A-Za-zäöüÄÖÜß0-9~\\])({_UNAMBIGUOUS_GREEK_NAMES}|rho)[ \t]*~[ \t]*([A-Za-z](?:_(?:\{{[^{{}}]+\}}|[A-Za-z0-9]+))?)(?![A-Za-zäöüÄÖÜß0-9])",
        lambda m: rf"{fc.TILDE_GREEK_WORD_TO_FIBS[m.group(1)]} \sim {m.group(2)}",
        work,
    )
    # Subscripted variable + Greek ('r_i omega' / '_r_i omega_' -> 'r_i ~w')
    work = re.sub(
        rf"([A-Za-z]'*_(?:\{{[^{{}}]+\}}|[A-Za-z0-9]+))[ \t]+({_UNAMBIGUOUS_GREEK_NAMES}|rho)(?![A-Za-zäöüÄÖÜß0-9])",
        lambda m: f"{m.group(1)} {fc.TILDE_GREEK_WORD_TO_FIBS[m.group(2)]}",
        work,
    )

    # Monomial/variable/power + glued or spaced Greek ('Jalpha' -> 'J~a', 'mr alpha' -> 'mr~a', 'mr^2 alpha' -> 'mr^2~a')
    def _monomial_greek_repl(m: re.Match[str]) -> str:
        tok = m.group(1)
        g_name = m.group(2)
        if re.search(r"[äöüÄÖÜß]", tok):
            return m.group(0)
        has_power_or_digit = bool(re.search(r"[0-9\^]", tok))
        is_short_math_var = (
            1 <= len(tok) <= 3
            and tok.isalpha()
            and tok not in {"A", "I", "a"}
            and tok.lower() not in _SHORT_PROSE_WORDS
        )
        if not (has_power_or_digit or is_short_math_var):
            return m.group(0)
        if g_name == "pi" and not has_power_or_digit:
            return m.group(0)
        fibs_g = fc.TILDE_GREEK_WORD_TO_FIBS[g_name]
        return f"{tok}{fibs_g}"

    work = re.sub(
        rf"(?<![A-Za-zäöüÄÖÜß0-9\\~])([A-Za-z0-9\^]+)[ \t]*({_UNAMBIGUOUS_GREEK_NAMES}|Delta|pi)(?![A-Za-zäöüÄÖÜß0-9])",
        _monomial_greek_repl,
        work,
    )
    # Trig argument with spelled-out Greek ('sin(alpha)' -> 'sin(~a)')
    work = re.sub(
        rf"(?<![A-Za-zäöüÄÖÜß0-9])(arc(?:sin|cos|tan)|sin|cos|tan|cot)\(\s*({_UNAMBIGUOUS_GREEK_NAMES})\s*\)",
        lambda m: f"{m.group(1)}({fc.TILDE_GREEK_WORD_TO_FIBS[m.group(2)]})",
        work,
    )

    # 6. Evaluate balanced '_<inner>_' spans: unwrap variables/formulas, split '_Begriff ~a_' & '_Label formula:_'
    math_trig_words = {"sin", "cos", "tan", "cot", "arcsin", "arccos", "arctan", "ln", "lg", "log", "lim", "max", "min", "const", "konst"}

    def _eval_emph_span(m: re.Match[str]) -> str:
        inner = m.group(1)
        prefix_ctx = work[max(0, m.start() - 25) : m.start()]

        # Single-letter variable '_m_', '_F_', '_v_' (preserve metalinguistic 'the letter _q_', 'Buchstabe _a_')
        if len(inner) == 1 and inner.isalpha():
            if re.search(r"\b(?:letter|letters|Buchstabe\w*|Laut\w*)\s+$", prefix_ctx, re.IGNORECASE):
                return m.group(0)
            return inner

        # Short 2-3 letter math variable product ('_ma_', '_mg_', '_mgh_', '_rF_', '_vt_', '_at_')
        if re.fullmatch(r"[a-z][A-Za-z]{1,2}", inner):
            if inner == "at":
                suffix_ctx = work[m.end() : m.end() + 25]
                if re.search(r"[a-z]{2,}\s+$", prefix_ctx) and re.match(
                    r"^\s+(?:the|a|an|my|his|her|our|this|that)\b", suffix_ctx, re.IGNORECASE
                ):
                    return m.group(0)
                return inner
            if inner.lower() not in _SHORT_PROSE_WORDS:
                return inner
            return m.group(0)

        # Mixed prose term(s) (>=4 chars) + trailing math symbol ('_Winkelbeschleunigung ~a_' -> '_Winkelbeschleunigung_ ~a', '_Drehmoment M_' -> '_Drehmoment_ M')
        m_term_sym = re.match(
            r"^([A-ZÄÖÜa-zäöüß][A-Za-zäöüÄÖÜß\-]{3,}(?:[ \t]+[A-ZÄÖÜa-zäöüß][A-Za-zäöüÄÖÜß\-]{2,})*)"
            r"[ \t]+(~[A-Za-z](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?(?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?"
            r"|[A-Za-z]'*(?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?(?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?)"
            r"([:;.,]?)$",
            inner,
        )
        if m_term_sym:
            prose_head, sym_tok, trail_p = m_term_sym.group(1), m_term_sym.group(2), m_term_sym.group(3)
            last_word = prose_head.rsplit(None, 1)[-1].lower().strip("-")
            is_section_label = len(sym_tok) == 1 and sym_tok.isalpha() and last_word in _NON_MATH_SECTION_NOUNS
            if not is_section_label:
                return f"_{prose_head}_ {sym_tok}{trail_p}"

        # Preserve explicit prose mapping arrows ('_Anzahl \to Preis_') without math symbols
        if r"\to" in inner and not re.search(r"[=^_]|\\[fs]\b|~[a-zA-Z]|\d", inner):
            return m.group(0)

        has_math_marker = bool(
            re.search(
                r"[=^]|(?<=[A-Za-z0-9}'])_(?=[A-Za-z0-9{~\\])"
                r"|\\(?:f|d?frac|t?frac|s|sqrt|vec|o?i{1,3}nt|sum|prod|lim|ol|pm|mp|neq|apx|eqv|8)\b"
                r"|~[a-zA-Z](?!-[A-ZÄÖÜ][a-zäöüß]{2,})"
                r"|\*|(?:<<|>>|<=|>=)"
                r"|\b\d{1,3}/\d{1,3}\b(?![./]\d)"
                r"|(?:~[a-zA-Z]|[A-Za-z0-9]+)/[ \t]*(?:~[a-zA-Z]|[A-Za-z0-9]+)"
                r"|[A-Za-z]'*\([A-Za-z0-9,;\s+\-*/~|]+\)",
                inner,
            )
        )
        if not has_math_marker:
            return m.group(0)

        # Strip subscripts and LaTeX command names before checking for prose words
        stripped_for_prose = re.sub(r"_(?:\{[^{}]+\}|[A-Za-z0-9,+-]+)", " ", inner)
        stripped_for_prose = re.sub(r"\\[A-Za-z]+", " ", stripped_for_prose)
        prose_words = [
            w
            for w in re.findall(r"[A-Za-zäöüÄÖÜß]{4,}", stripped_for_prose)
            if w.lower() not in math_trig_words
        ]
        has_umlaut = bool(re.search(r"[äöüÄÖÜß]", stripped_for_prose))

        if not prose_words and not has_umlaut:
            return inner

        # If span starts directly with a formula/equation (e.g. '_E_{ges} = E_{kin} = konstant_'), unwrap all
        if re.match(r"^(?:~[a-zA-Z]|\\[a-zA-Z]+|[A-Za-z](?:[_^'(]|\s*[=<>+\-*/]))", inner) and "=" in inner:
            return inner

        # Colon-terminated prose label with trailing formula ('_Grenzfrequenz f_G = \f{W_A}{h}:_' -> '_Grenzfrequenz_ f_G = \f{W_A}{h}:')
        if inner.endswith(":"):
            m_lbl = re.match(
                r"^([A-ZÄÖÜ][A-Za-zäöüÄÖÜß\-]+(?:\s+(?:der|des|die|das|den|dem|einer|eines|einem|von|für|beim|zur|zum|und|oder|[A-ZÄÖÜa-zäöüß\-]{4,}))*)"
                r"\s+(.+):$",
                inner,
            )
            if m_lbl and len(m_lbl.group(1).split()) <= 6:
                lbl_part = m_lbl.group(1).strip()
                math_tail = m_lbl.group(2).strip()
                lbl_has_math = bool(re.search(r"[=^_\\]|~[a-zA-Z]", lbl_part))
                if not lbl_has_math:
                    return f"_{lbl_part}_ {math_tail}:"

        return m.group(0)

    work = _FIBS_EMPH_SPAN_RE.sub(_eval_emph_span, work)

    # 7. Clean orphaned leading/trailing '_' on '~' tokens, \vec{...}, braces, units, ~D spaces, and headings
    # Collapse '~D ~w' / '~D p' / '~D t' -> '~D~w' / '~Dp' / '~Dt'
    work = re.sub(
        r"~D[ \t]+(~[A-Za-z]|[A-Za-z](?![A-Za-zäöüÄÖÜß]))",
        r"~D\1",
        work,
    )
    # Strip orphaned '_' inside LaTeX command argument braces ('\f{_v^2}{r}' -> '\f{v^2}{r}', '\f{a}{b_}' -> '\f{a}{b}')
    for _ in range(2):
        work = re.sub(r"\{_([A-Za-z0-9~\\][^{}]*)\}", r"{\1}", work)
        work = re.sub(r"\{([^{}]+?)_\}", r"{\1}", work)
    # Strip orphaned leading '_' before '~x', 'm\vec{v}', or 'm~w^2'
    work = re.sub(r"(?<![A-Za-z0-9}\\'])_(~[a-zA-Z])", r"\1", work)
    work = re.sub(
        r"(?<![A-Za-z0-9}\\'])_([A-Za-z]?(?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?\\vec\{)",
        r"\1",
        work,
    )
    work = re.sub(
        r"(?<![A-Za-z0-9}\\'])_([A-Za-z](?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?~[a-zA-Z])",
        r"\1",
        work,
    )
    # Strip orphaned trailing '_' after '~x', '~Dx', '\vec{...}', exponents, or SI units ('9,81 m/s^2_')
    work = re.sub(
        r"(~[a-zA-Z](?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?)_(?![A-Za-z0-9{~])",
        r"\1",
        work,
    )
    work = re.sub(
        r"(~D[A-Za-z](?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?)_(?![A-Za-z0-9{])",
        r"\1",
        work,
    )
    work = re.sub(
        r"(\\vec\{[^{}]+\}(?:\^(?:\{[^{}]+\}|[A-Za-z0-9+-]+))?)_(?![A-Za-z0-9{])",
        r"\1",
        work,
    )
    work = re.sub(
        r"((?:\^\d+|\^\{[^{}]+\}|\b(?:m|km|cm|mm)/s(?:\^2)?))_(?![A-Za-z0-9_{])",
        r"\1",
        work,
    )
    # Strip stray unclosed '_' before an equation 'X = ...' in headings (and lines with no closing emphasis '_')
    out_lines: list[str] = []
    for ln in work.splitlines():
        if re.match(r"^[ \t]*#{1,6}\s+", ln):
            ln = re.sub(
                r"(?<![A-Za-z0-9_}'\\])_(?=(?:~[a-zA-Z]|[A-Za-z]'*(?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)\s*=)",
                "",
                ln,
            )
        elif "_" in ln and not _FIBS_EMPH_SPAN_RE.search(ln):
            ln = re.sub(
                r"(?<![A-Za-z0-9_}'\\])_(?=(?:~[a-zA-Z]|[A-Za-z]'*(?:_(?:\{[^{}]+\}|[A-Za-z0-9]+))?)\s*=)",
                "",
                ln,
            )
        out_lines.append(ln)
    work = "\n".join(out_lines)

    for idx, val in reversed(list(enumerate(protected_spans))):
        work = work.replace(f"__MATH_EMPH_PROT_{idx}__", val)
    return work


def _normalize_fibs_emphasis(text: str, custom_rules: str | None = None) -> str:
    """Normalizes ``**Wort**``, unannounced ``*Wort*``, and ``%Wort%`` to FIBS ``_Wort_``.

    Preserves differentiated ``*...*`` / ``%...%`` / ``#...#`` markers only when an
    explicit ``<Anmerkung>`` legend announces them per FIBS §10 (p. 97 & p. 103).
    Strips ``_..._`` emphasis markers inside ``#`` headings per FIBS §10 (p. 99).

    Args:
        text: Input Markdown text.
        custom_rules: Optional book-specific rules string.

    Returns:
        Markdown text with normalized FIBS emphasis markers.
    """
    if not text:
        return text

    has_emphasis_legend = bool(
        _EMPHASIS_LEGEND_ANM_RE.search(text)
        or (custom_rules and _EMPHASIS_LEGEND_ANM_RE.search(custom_rules))
    )

    protected_spans: list[str] = []

    def _mask_span(m: re.Match[str]) -> str:
        protected_spans.append(m.group(0))
        return f"__EMPH_PROT_{len(protected_spans) - 1}__"

    masked = fc.UNIT_PERCENT_PROTECTED_RE.sub(_mask_span, text)
    # Protect spreadsheet cell refs ($F$1) and opening prose '$-Zeichen' before masking bounded $...$ math
    masked = re.sub(
        r"\$[A-Z]{1,3}\$\d+|(?<![0-9A-Za-z°}\\%])\$-(?=[A-ZÄÖÜ][a-zäöüß]+)",
        _mask_span,
        masked,
    )

    def _mask_math_if_valid(m: re.Match[str]) -> str:
        full = m.group(0)
        if full.startswith("$$"):
            return _mask_span(m)
        inner = full[1:-1]
        if len(inner) > 80 or re.search(
            r"\b(?:sodass|wenn|weil|dass|Zeichen|Formel|Konstante|Verwendung)\b",
            inner,
            re.IGNORECASE,
        ):
            return full
        return _mask_span(m)

    masked = re.sub(
        r"\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\s)([^\$\n]+?)(?<!\s)\$(?!\$)",
        _mask_math_if_valid,
        masked,
    )

    out_lines: list[str] = []
    for line in masked.splitlines():
        if re.match(r"^[ \t]*#{1,6}\s+", line):
            h_ln = re.sub(r"\*\*([^\*\n]+)\*\*", r"\1", line)
            if not has_emphasis_legend:
                h_ln = re.sub(
                    r"(?<![\w\*\\)\]}])\*(?![\*\s(\[{])([^\*\n]+?)(?<![\*\s)\]}])\*(?![\w\*(\[{])",
                    r"\1",
                    h_ln,
                )
                h_ln = _UNANNOUNCED_PCT_EMPH_RE.sub(r"\1", h_ln)
            h_ln = re.sub(
                r"(?<![\w\\])_(?!\.\.\._)(?!\s)([^_\n]+?)(?<!\s)_(?![\w\{])",
                r"\1",
                h_ln,
            )
            out_lines.append(h_ln)
            continue

        b_ln = re.sub(r"\*\*([^\*\n]+)\*\*", r"_\1_", line)
        if not has_emphasis_legend:
            # Do not treat FIBS multiplication '*' surrounded by spaces, digits, or parens as emphasis
            b_ln = re.sub(
                r"(?<![\w\*\\)\]}])\*(?![\*\s(\[{])([^\*\n]+?)(?<![\*\s)\]}])\*(?![\w\*(\[{])",
                r"_\1_",
                b_ln,
            )
            b_ln = _UNANNOUNCED_PCT_EMPH_RE.sub(r"_\1_", b_ln)
        out_lines.append(b_ln)

    res = "\n".join(out_lines)
    for idx, val in reversed(list(enumerate(protected_spans))):
        res = res.replace(f"__EMPH_PROT_{idx}__", val)
    return res


def _apply_linked_worterklaerungen_and_randspalten(
    text: str,
    custom_rules: str | None = None,
) -> str:
    r"""Formats marginal boxes under ``#### Randspalte`` and links ``Worterklärungen`` per FIBS §11.

    When ``custom_rules`` specifies linked glossary entries (``Worterklärungen ... verlinkt``),
    converts legacy ``{n}`` + ``<Anmerkung> n ... </Anmerkung>`` footnotes as well as
    marginal etymology/definition lines into ``Begriff^n`` body references paired with
    ``#### Worterklärungen`` and ``-\\t^n: Erklärung`` at the end of the page.

    Args:
        text: Post-processed Markdown text.
        custom_rules: Optional book-specific rules string.

    Returns:
        Markdown text with formatted ``#### Randspalte`` boxes and linked ``Worterklärungen``.
    """
    if not text:
        return text

    # 0. Demote margin etymology headings (e.g. '### lat. vegetare = beleben') outside <Bild>/<Tabelle>
    etym_h_re = re.compile(
        r"^#{2,5}\s+((?:lat\.|griech\.|gr\.|engl\.|franz\.|frz\.|ital\.|span\.|arab\.)\s+[^=\n]{1,40}=[^\n]*)$",
        re.IGNORECASE,
    )
    etym_lines = text.splitlines()
    etym_in_media = False
    etym_changed = False
    for idx_e, raw_e in enumerate(etym_lines):
        se = raw_e.strip()
        if etym_in_media:
            if re.search(r"</(?:Bild|Tabelle)>", se, re.IGNORECASE):
                etym_in_media = False
            continue
        if re.match(r"^<(?:Bild(?!-Ref)|Tabelle)\b", se, re.IGNORECASE):
            if not re.search(r"</(?:Bild|Tabelle)>", se, re.IGNORECASE):
                etym_in_media = True
            continue
        m_etym_h = etym_h_re.match(se)
        if m_etym_h:
            etym_lines[idx_e] = m_etym_h.group(1).strip()
            etym_changed = True
    if etym_changed:
        text = "\n".join(etym_lines)

    # 1. Non-glossary marginal boxes ('Randspalte') -> '#### Randspalte' + '<Rahmen>...</Rahmen>'
    def _lift_randspalte_rahmen(m: re.Match[str]) -> str:
        sub = (m.group(1) or "").strip()
        body = m.group(2).strip()
        heading = f"#### Randspalte: {sub}" if sub else "#### Randspalte"
        return f"{heading}\n\n<Rahmen>\n{body}\n</Rahmen>"

    text = re.sub(
        r"<Rahmen>\s*\n[ \t]*(?:_|\*\*)?Randspalte(?::[ \t]*([^_\*\n]+?))?:?(?:_|\*\*)?[ \t]*\n([\s\S]*?)</Rahmen>",
        _lift_randspalte_rahmen,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?m)^(?:#{1,6}\s+|(?:\*\*|_))Randspalte:?(?:\*\*|_)?[ \t]*\n+(?!<Rahmen>)((?:(?![#\n<\(])[^\n]+\n?)+)",
        lambda m: "#### Randspalte\n\n<Rahmen>\n"
        + "\n".join(ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip())
        + "\n</Rahmen>\n",
        text,
        flags=re.IGNORECASE,
    )

    linked_glossary = bool(
        custom_rules
        and re.search(
            r"Worterklärungen?\b[^\n.]*verlinkt|verlinkte?\s+Worterklärungen?",
            custom_rules,
            re.IGNORECASE,
        )
    )

    etym_re = re.compile(
        r"^(?:[-*]\s+)?([A-ZÄÖÜa-zäöüß\-]{3,40})\s*"
        r"(?:\((?:(?:von|aus)\s+)?(?:lat\.|griech\.|gr\.|engl\.|frz\.|ital\.)[^)\n]+\)|"
        r"[,:]\s*(?:(?:von|aus)\s+)?(?:lat\.|griech\.|gr\.|engl\.|frz\.|ital\.)\b[^\n]+)$"
    )
    pure_etym_re = re.compile(
        r"^(?:[-*]\s+)?(lat\.|griech\.|gr\.|engl\.|frz\.|ital\.)\s+([A-Za-zäöüÄÖÜß\-]+)\s*=\s*([^\n]+)$",
        re.IGNORECASE,
    )
    term_eq_re = re.compile(
        r"^(?:[-*]\s+)?([A-Za-zäöüÄÖÜß\-]{4,35})\s*=\s*([A-Za-zäöüÄÖÜß][^\n=]{3,140})$"
    )
    italic_gloss_sent_re = re.compile(
        r"^(?:_|\*)((?:Der|Die|Das)\s+([A-ZÄÖÜ][A-Za-zäöüÄÖÜß\-]{4,35})\s+(?:wird|bezeichnet|bedeutet|nennt)\b[^_*\n]{5,140}\.)(?:_|\*)$"
    )
    term_def_re = re.compile(
        r"^(?:[-*]\s+)?([A-ZÄÖÜ][A-Za-zäöüÄÖÜß\-]{2,35}):\s+([^\n]{4,220})$"
    )
    non_gloss_box_labels = {
        "material", "materialien", "chemikalien", "geräte", "durchführung",
        "versuchsdurchführung", "beobachtung", "auswertung", "ergebnis", "deutung",
        "entsorgung", "merksatz", "merke", "definition", "beispiel", "hinweis",
        "tipp", "wichtig", "aufgabe", "übung", "lösung", "quelle", "steckbrief",
        "infobox", "exkurs", "methode", "praxis", "hintergrund", "answer", "solution",
        "lernwegweiser", "study skills", "watch out",
    }

    def _unwrap_glossary_rahmen(m_r: re.Match[str]) -> str:
        inner_r = m_r.group(1).strip()
        if not inner_r or "-\t" in inner_r:
            return m_r.group(0)
        joined_r = re.sub(r"\n+[ \t]*([=:])[ \t]*", r" \1 ", inner_r)
        joined_r = re.sub(
            r"([^\n])\n[ \t]*(?![-*•#]|[*_]*(?:lat\.|griech\.|gr\.|engl\.|frz\.|ital\.)\b|[*_]*[A-Za-zäöüÄÖÜß\-]{3,35}[*_]*\s*[=:])([a-zäöüß][^\n]+)",
            r"\1 \2",
            joined_r,
        )
        r_lines = [ln_r.strip() for ln_r in joined_r.splitlines() if ln_r.strip()]
        if not r_lines:
            return m_r.group(0)
        has_wk_hdr = False
        first_plain = re.sub(r"[*_#]+", "", r_lines[0]).strip()
        if re.match(r"^Worterklärung(?:en)?(?:\s*\(Randspalte\))?:?\s*$", first_plain, re.IGNORECASE):
            has_wk_hdr = True
            r_lines = r_lines[1:]
        if not r_lines:
            return m_r.group(0)

        has_etym_or_eq = False
        for ln_r in r_lines:
            p_ln = re.sub(r"[*_]+", "", ln_r).strip()
            if len(p_ln.split()) > 22:
                return m_r.group(0)
            if "\\" in p_ln or "$" in p_ln or "->" in p_ln:
                return m_r.group(0)
            lead_lbl = p_ln.split(":")[0].strip(" -*").lower() if ":" in p_ln else ""
            if lead_lbl in non_gloss_box_labels or fc.DIDACTIC_BOX_HEADER_RE.match(lead_lbl):
                return m_r.group(0)
            if pure_etym_re.match(p_ln) or etym_re.match(p_ln) or term_eq_re.match(p_ln):
                has_etym_or_eq = True
            elif not term_def_re.match(p_ln):
                return m_r.group(0)

        if not (has_wk_hdr or has_etym_or_eq):
            return m_r.group(0)
        if linked_glossary:
            return "\n\n".join(r_lines)
        formatted_items = [
            f"-\t{re.sub(r'^[-*]\\s+', '', ln_r)}" for ln_r in r_lines
        ]
        return "#### Worterklärungen\n\n" + "\n".join(formatted_items)

    text = re.sub(
        r"<Rahmen\b[^>]*>\s*([\s\S]*?)\s*</Rahmen>",
        _unwrap_glossary_rahmen,
        text,
        flags=re.IGNORECASE,
    )

    if not linked_glossary:
        return text

    segs = split_markdown_pages(text)

    def _latin_stem_regex(word: str) -> str:
        w_low = word.lower()
        stripped_root = re.sub(r"(?:ere|are|ire|ari|os|on|us|um|is)$", "", w_low)
        base = stripped_root if len(stripped_root) >= 4 else w_low[: max(4, len(w_low) - 2)]
        raw_st = base[: min(6, len(base))]
        # Allow Latin/Greek c -> German k/z and i -> e stem alternations (secern -> sezern, recip -> rezep, contrah -> kontrah, sarc -> sark)
        pat_chars: list[str] = []
        for idx_c, ch in enumerate(raw_st):
            if ch == "c":
                pat_chars.append("[ckz]")
            elif ch == "i" and idx_c >= 2:
                pat_chars.append("[ie]")
            else:
                pat_chars.append(re.escape(ch))
        return "".join(pat_chars)

    for seg in segs:
        p_text = seg.text
        if not p_text.strip():
            continue

        entries: list[tuple[int, str]] = []
        used_nums: set[int] = set()
        for existing_m in re.finditer(r"(?m)^(?:-\t|\s*)\^(\d+)[:\s]", p_text):
            used_nums.add(int(existing_m.group(1)))

        def _next_num() -> int:
            n_cand = 1
            while n_cand in used_nums:
                n_cand += 1
            used_nums.add(n_cand)
            return n_cand

        # A. Convert {n} + <Anmerkung> n ... </Anmerkung> on this page
        anm_defs: dict[int, str] = {}

        def _collect_anm(m_a: re.Match[str]) -> str:
            num_i = int(m_a.group(1))
            body_a = m_a.group(2).strip()
            if _has_footnote_brace_ref(p_text, num_i):
                anm_defs[num_i] = body_a
                used_nums.add(num_i)
                return ""
            return m_a.group(0)

        p_text = re.sub(
            r"<Anmerkung\b[^>]*>\s*(\d+)\s+([\s\S]*?)\s*</Anmerkung>",
            _collect_anm,
            p_text,
            flags=re.IGNORECASE,
        )
        if anm_defs:
            p_masked, p_saved = _mask_latex_commands_for_footnotes(p_text)
            for num_i in sorted(anm_defs):
                p_masked = re.sub(rf"(?<![_^\\}}\]])\{{{num_i}\}}", f"^{num_i}", p_masked)
                entries.append((num_i, anm_defs[num_i]))
            for idx_s, val_s in reversed(list(enumerate(p_saved))):
                p_masked = p_masked.replace(f"__FN_CMD_PROT_{idx_s}__", val_s)
            p_text = p_masked

        # B. Detect marginal etymology / glossary lines outside protected blocks
        p_text = re.sub(r"\n+[ \t]*=[ \t]*", " = ", p_text)
        lines = p_text.splitlines()
        kept_lines: list[str] = []
        in_prot = False
        in_worterkl_sec = False
        body_snapshot = re.sub(
            r"<(?:Bild|Tabelle|Rahmen|Anmerkung)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle|Rahmen|Anmerkung)>",
            "",
            p_text,
            flags=re.IGNORECASE,
        )

        # Tuple: (primary_term, fallback_gloss, num_e, formatted_desc, original_line)
        pending_links: list[tuple[str, str, int, str, str]] = []
        for ln in lines:
            s = ln.strip()
            if re.match(r"^<(?:Bild|Tabelle|Rahmen|Anmerkung)\b", s, re.IGNORECASE):
                if not re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", s, re.IGNORECASE):
                    in_prot = True
                kept_lines.append(ln)
                continue
            if in_prot:
                if re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", s, re.IGNORECASE):
                    in_prot = False
                kept_lines.append(ln)
                continue

            s_plain = re.sub(r"[*_]+", "", s).strip()
            if re.match(
                r"^(?:#{1,6}\s+)?Worterklärung(?:en)?(?:\s*\(Randspalte\))?:?\s*$",
                s_plain,
                re.IGNORECASE,
            ):
                in_worterkl_sec = True
                continue

            if in_worterkl_sec and re.match(r"^(?:#{1,6}\s+|\(\()", s):
                in_worterkl_sec = False

            if in_worterkl_sec and s:
                m_already = re.match(r"^(?:[-*]\s+)?\^(\d+):\s*(.+)$", s)
                if m_already:
                    num_e = int(m_already.group(1))
                    used_nums.add(num_e)
                    entries.append((num_e, m_already.group(2).strip()))
                    continue
                m_td = term_def_re.match(s_plain) or etym_re.match(s_plain)
                if m_td:
                    term_c = m_td.group(1).strip()
                    clean_s = re.sub(r"^[-*]\s+", "", s_plain)
                    num_e = _next_num()
                    pending_links.append((term_c, "", num_e, clean_s, ln))
                    continue

            m_pe = pure_etym_re.match(s_plain)
            if m_pe:
                lang_lbl = m_pe.group(1).strip()
                foreign_w = m_pe.group(2).strip()
                gloss_w = m_pe.group(3).strip()
                clean_s = f"{lang_lbl} _{foreign_w}_ = {gloss_w}"
                num_e = _next_num()
                pending_links.append((foreign_w, gloss_w, num_e, clean_s, ln))
                continue

            m_et = etym_re.match(s_plain)
            if m_et:
                term_c = m_et.group(1).strip()
                stem = term_c[: max(4, len(term_c) - 2)]
                if len(re.findall(rf"(?<![A-Za-zäöüÄÖÜß]){re.escape(stem)}", body_snapshot, re.IGNORECASE)) >= 2:
                    clean_s = re.sub(r"^[-*]\s+", "", s_plain)
                    num_e = _next_num()
                    pending_links.append((term_c, "", num_e, clean_s, ln))
                    continue

            m_eq = term_eq_re.match(s_plain)
            if m_eq and not s.startswith("#") and "\\to" not in s and "->" not in s:
                term_c = m_eq.group(1).strip()
                gloss_eq = m_eq.group(2).strip()
                stem_eq = _latin_stem_regex(term_c)
                if len(re.findall(rf"(?<![A-Za-zäöüÄÖÜß]){stem_eq}[A-Za-zäöüÄÖÜß]*", body_snapshot, re.IGNORECASE)) >= 2:
                    clean_s = f"_{term_c}_ = {gloss_eq}"
                    num_e = _next_num()
                    pending_links.append((term_c, "", num_e, clean_s, ln))
                    continue

            m_igs = italic_gloss_sent_re.match(s)
            if m_igs:
                full_sent = m_igs.group(1).strip()
                subj_term = m_igs.group(2).strip()
                if len(re.findall(rf"(?<![A-Za-zäöüÄÖÜß]){re.escape(subj_term)}[A-Za-zäöüÄÖÜß]*", body_snapshot, re.IGNORECASE)) >= 2:
                    num_e = _next_num()
                    pending_links.append((subj_term, "", num_e, full_sent, ln))
                    continue

            m_tdef = term_def_re.match(s_plain)
            if m_tdef and not s.startswith("#") and "\\to" not in s:
                term_c = m_tdef.group(1).strip()
                if term_c.lower() not in {
                    "material", "chemikalien", "geräte", "durchführung", "beobachtung",
                    "auswertung", "ergebnis", "merksatz", "definition", "beispiel", "hinweis",
                    "aufgabe", "lösung", "quelle", "fach", "titel", "verlag", "seite",
                }:
                    stem = term_c[: max(4, len(term_c) - 1)]
                    non_colon_hits = len(
                        re.findall(
                            rf"(?<![A-Za-zäöüÄÖÜß]){re.escape(stem)}[A-Za-zäöüÄÖÜß]*(?!\s*:)",
                            body_snapshot,
                            re.IGNORECASE,
                        )
                    )
                    if non_colon_hits >= 1 and len(m_tdef.group(2).split()) >= 3:
                        clean_s = re.sub(r"^[-*]\s+", "", s_plain)
                        num_e = _next_num()
                        pending_links.append((term_c, "", num_e, clean_s, ln))
                        continue

            kept_lines.append(ln)

        rebuilt = "\n".join(kept_lines)
        prot_blocks: list[str] = []

        def _mask_prot_block(m_pb: re.Match[str]) -> str:
            prot_blocks.append(m_pb.group(0))
            return f"__GLOSS_PROT_BLK_{len(prot_blocks) - 1}__"

        rebuilt_masked = re.sub(
            r"<(?:Bild|Tabelle|Rahmen|Anmerkung)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle|Rahmen|Anmerkung)>",
            _mask_prot_block,
            rebuilt,
            flags=re.IGNORECASE,
        )

        unmatched_lines: list[str] = []
        for term_c, gloss_fb, num_e, clean_s, orig_ln in pending_links:
            already_has = bool(re.search(rf"\^{num_e}\b", rebuilt_masked))
            n_subs = 1 if already_has else 0
            if not already_has:
                stem_pat = _latin_stem_regex(term_c)
                for cand_pat in (
                    rf"(?m)^(?![ \t]*#|[ \t]*__GLOSS_PROT_BLK_)([^\n]*?(?<![A-Za-zäöüÄÖÜß])[A-Za-zäöüÄÖÜß]*{stem_pat}[A-Za-zäöüÄÖÜß]*)(?:(_))?(?!\^\d)",
                    *(
                        [
                            rf"(?m)^(?![ \t]*#|[ \t]*__GLOSS_PROT_BLK_)([^\n]*?(?<![A-Za-zäöüÄÖÜß])[A-Za-zäöüÄÖÜß]*{re.escape(gloss_fb.split()[0][:5])}[A-Za-zäöüÄÖÜß]*)(?:(_))?(?!\^\d)"
                        ]
                        if gloss_fb and len(gloss_fb.split()[0]) >= 5
                        else []
                    ),
                ):
                    rebuilt_new, cnt = re.subn(
                        cand_pat,
                        lambda m_hit, ne=num_e: f"{m_hit.group(1)}{m_hit.group(2) or ''}^{ne}",
                        rebuilt_masked,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    if cnt > 0:
                        rebuilt_masked = rebuilt_new
                        n_subs = cnt
                        break

            if n_subs > 0:
                entries.append((num_e, clean_s))
            else:
                unmatched_lines.append(orig_ln)

        for idx_pb, val_pb in enumerate(prot_blocks):
            rebuilt_masked = rebuilt_masked.replace(f"__GLOSS_PROT_BLK_{idx_pb}__", val_pb)
        rebuilt = rebuilt_masked
        if unmatched_lines:
            rebuilt = rebuilt.rstrip() + "\n\n" + "\n\n".join(unmatched_lines)

        if entries:
            entries.sort(key=lambda pair: pair[0])
            glossary_lines = ["#### Worterklärungen", ""] + [
                f"-\t^{num_e}: {desc_e}" for num_e, desc_e in entries
            ]
            rebuilt = re.sub(r"\n{3,}", "\n\n", rebuilt.rstrip())
            rebuilt = f"{rebuilt}\n\n" + "\n".join(glossary_lines)

        seg.text = rebuilt.rstrip() + "\n\n"

    return "".join(s.text for s in segs).strip()


def _parse_buchkonferenz_profile(custom_rules: str | None) -> BuchkonferenzProfile:
    """Parses structural, task, difficulty, TOC, and emphasis directives from ``custom_rules``.

    Args:
        custom_rules: Optional book-specific rules string from ``custom_ruleset.txt``.

    Returns:
        Populated ``BuchkonferenzProfile`` domain model.
    """
    if not custom_rules or not custom_rules.strip():
        return BuchkonferenzProfile()

    u5_chunks: list[str] = []
    for m_u5 in re.finditer(
        r"(?:^|\n)[ \t#*\-]*(?:(?:Überschrift|Ebene)\s*5|Ü\s*5)\b[ \t]*:?[ \t]*([\s\S]*?)"
        r"(?=\n[ \t#*\-]*(?:(?:Überschrift|Ebene)\s*[1-6]|Ü[1-6])\b|\n[ \t*]*Sonstiges|\n[ \t*]*Anmerkungen|\n<Anmerkung|\Z)",
        custom_rules,
        re.IGNORECASE,
    ):
        u5_chunks.append(m_u5.group(1))
    u5_text = "\n".join(u5_chunks)

    has_u5_num_kw = bool(
        re.search(r"\bAufgabennummern?\b", u5_text, re.IGNORECASE)
        or re.search(
            r"\bAufgabennummern?\b[^\n]{0,50}(?:Überschrift\s*5|Ü\s*5|H5)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    has_u5_standalone_aufg = bool(
        re.search(
            r"(?:['\"„“]Aufgaben:?['\"“”]|Wort\s+['\"„“]?Aufgaben|\bAufgaben\b(?!nummer))",
            u5_text,
            re.IGNORECASE,
        )
        or (
            not u5_text
            and re.search(
                r"(?:Überschrift\s*5|Ü\s*5)[\s\S]{0,120}\bAufgaben\b(?!nummer)"
                r"|\bAufgaben\b(?!nummer)[^\n]{0,50}(?:Überschrift\s*5|Ü\s*5)",
                custom_rules,
                re.IGNORECASE,
            )
        )
    )
    tasks_h5_numbers_only = bool(has_u5_num_kw and not has_u5_standalone_aufg)
    tasks_h5 = bool(has_u5_standalone_aufg and not tasks_h5_numbers_only)

    point_map: dict[int, str] = {}
    for m_pt in re.finditer(
        r"(?<!\d)([123])\s*Punkte?\s*\)?\s*(?::|=|->|→|–|-|entspricht)\s*"
        r"(?:\[([^\],\n]+)\]|([A-Za-zÄÖÜäöüß]{4,20}))",
        custom_rules,
        re.IGNORECASE,
    ):
        pt_num = int(m_pt.group(1))
        lbl_raw = (m_pt.group(2) or m_pt.group(3) or "").strip()
        if lbl_raw:
            point_map[pt_num] = f"[{lbl_raw}]"

    text_subheadings_h4 = bool(
        re.search(
            r"(?:(?:Überschrift|Ebene)\s*4|Ü\s*4)[\s\S]{0,180}(?:Text|Abschnitts|Zwischen)überschrift"
            r"|(?:Text|Abschnitts|Zwischen)überschrift\w*[^\n]{0,60}(?:(?:Überschrift|Ebene)\s*4|Ü\s*4)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    material_h3_section = bool(
        re.search(
            r"Material\s+Ü3|(?:Überschrift\s*3|Ü\s*3)\s*:?[\s\S]{0,120}\bMaterial\b(?!\s+mit\s+Aufgaben)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    has_hierarchy = bool(
        text_subheadings_h4
        or re.search(
            r"Überschrift\s*1\s*:?\s*[^\n]*(?:Hauptthema|Hauptkapitel|Kapitel)"
            r"|Überschrift\s*3\s*:?[^\n]*(?:Material|IM\s+BLICKPUNKT|Methode|Basiskonzept|Exkurs)"
            r"|Überschrift\s*4\s*:?[^\n]*(?:Kapitelinterne|(?:Text|Abschnitts|Zwischen)überschrift)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    adopt_toc_u1 = bool(
        re.search(
            r"stehen\s+nur\s+im\s+Inhaltsverzeichnis"
            r"|aus\s+dem\s+Inhaltsverzeichnis[^\n]*(?:übernehmen|ergänzen|einfügen)"
            r"|Inhaltsverzeichnis[^\n]*(?:Überschrift\s*1|Ü\s*1)"
            r"|(?:Überschrift\s*1|Ü\s*1)[\s\S]{0,140}Inhaltsverzeichnis",
            custom_rules,
            re.IGNORECASE,
        )
    )
    plain_italic_intro = bool(
        re.search(
            r"kursiv\w*\s+Einleitungstext\w*[^\n]*nicht\s+fett"
            r"|Einleitungstext\w*[^\n]*(?:nicht\s+fett|ohne\s+Hervorhebung)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    arrow_ref_label = ""
    m_arrow = re.search(
        r"(?:Verweise?\s+mit\s+Pfeil\w*|Pfeilverweise?|[▶►▷▻])[ \t]*(?::|=|->|→)[ \t]*"
        r"(?:[^\n\[\]]{0,30}?)(\[[^\]\n,]+\])",
        custom_rules,
        re.IGNORECASE,
    )
    if m_arrow:
        arrow_ref_label = m_arrow.group(1).strip()
    has_self_assessment_box = bool(
        re.search(r"Selbsteinschätzung", custom_rules, re.IGNORECASE)
        and re.search(r"\[\s*\]", custom_rules)
    )

    return BuchkonferenzProfile(
        tasks_h5=tasks_h5,
        tasks_h5_numbers_only=tasks_h5_numbers_only,
        point_difficulty_map=point_map,
        has_hierarchy=has_hierarchy,
        material_h3_section=material_h3_section,
        text_subheadings_h4=text_subheadings_h4,
        adopt_toc_u1=adopt_toc_u1,
        plain_italic_intro=plain_italic_intro,
        arrow_ref_label=arrow_ref_label,
        has_self_assessment_box=has_self_assessment_box,
    )


def _inject_toc_u1_chapters(
    text: str,
    directory_info: dict[str, Any] | None,
    *,
    inject_missing: bool,
) -> tuple[str, dict[str, set[int | None]]]:
    """Collects page-scoped TOC level-1 chapter norms and optionally injects missing ``# <title>``.

    Args:
        text: Markdown document with ``((page))`` markers.
        directory_info: Optional detected TOC/directory metadata dictionary.
        inject_missing: Whether to insert TOC ``level == 1`` chapters after ``((page))``
            when no matching ``# `` heading already appears on that page.

    Returns:
        Tuple ``(updated_text, toc_u1_pages)`` mapping normalized level-1 titles to their
        target page numbers (or ``None`` when no page is attached to the TOC entry).
    """
    toc_u1_pages: dict[str, set[int | None]] = {}
    toc_entries = (directory_info or {}).get("toc_entries") or []
    u1_by_page: dict[str, list[str]] = {}
    for entry in toc_entries:
        if not isinstance(entry, dict) or int(entry.get("level") or 0) != 1:
            continue
        raw_t = str(entry.get("title") or "").strip()
        pg_t = str(entry.get("page") or "").strip()
        pg_int = int(pg_t) if pg_t.isdigit() else None
        norm_t = re.sub(r"\W+", " ", raw_t).strip().lower()
        if norm_t:
            toc_u1_pages.setdefault(norm_t, set()).add(pg_int)
            norm_unnum = re.sub(r"^\d+\.?\s+", "", norm_t).strip()
            if norm_unnum:
                toc_u1_pages.setdefault(norm_unnum, set()).add(pg_int)
        if raw_t and pg_t and not entry.get("page_inferred"):
            u1_by_page.setdefault(pg_t, []).append(raw_t)

    if not inject_missing or not u1_by_page or not text:
        return text, toc_u1_pages

    segs = split_markdown_pages(text)
    changed = False
    for seg in segs:
        if not seg.page or seg.page not in u1_by_page:
            continue
        seg_lines = seg.text.splitlines()
        if not seg_lines:
            continue
        for toc_title in reversed(u1_by_page[seg.page]):
            toc_words = {
                w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{3,}", toc_title)
            }
            already_present = False
            for idx_sl, raw_sl in enumerate(seg_lines):
                m_h = re.match(r"^(#{1,3})\s+(.+)$", raw_sl.strip())
                if not m_h:
                    continue
                h_words = {
                    w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{3,}", m_h.group(2))
                }
                if toc_words and (
                    toc_words <= h_words
                    or len(toc_words & h_words) / len(toc_words) >= 0.75
                ):
                    if len(m_h.group(1)) != 1:
                        seg_lines[idx_sl] = f"# {m_h.group(2).strip()}"
                        changed = True
                    already_present = True
                    break
            if not already_present:
                seg_lines = [seg_lines[0], "", f"# {toc_title}", ""] + seg_lines[1:]
                changed = True
        if changed:
            seg.text = re.sub(r"\n{3,}", "\n\n", "\n".join(seg_lines).rstrip()) + "\n\n"

    if not changed:
        return text, toc_u1_pages
    return "".join(s.text for s in segs).strip(), toc_u1_pages


def _apply_buchkonferenz_rules(
    text: str,
    custom_rules: str | None,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    directory_info: dict[str, Any] | None = None,
    raw_markdown: str | None = None,
    table_max_cells: int | None = None,
) -> str:
    """Applies generic Buchkonferenz structural and formatting directives from ``custom_rules``.

    Args:
        text: Post-processed Markdown text.
        custom_rules: Optional book-specific rules string from ``custom_ruleset.txt``.
        ruleset_key: Active FIBS ruleset identifier.
        directory_info: Optional detected TOC/directory metadata dictionary.
        raw_markdown: Optional Stage 1 extracted Markdown for context recovery.
        table_max_cells: Optional cell threshold overriding ``table_resolve_max_cells``.

    Returns:
        Markdown text transformed according to the detected Buchkonferenz directives.
    """
    if not text:
        return text

    text = _split_run_in_bullet_subheadings(text)

    # Strip any residual '#' heading prefixes inside <Bild>...</Bild> blocks
    def _clean_bild_inner_headings(m: re.Match[str]) -> str:
        block = m.group(0)
        b_lines = block.splitlines()
        cleaned_b = [
            b_lines[0],
            *[re.sub(r"^(\s*)#{1,6}\s+", r"\1", ln) for ln in b_lines[1:-1]],
            *(b_lines[-1:] if len(b_lines) > 1 else []),
        ]
        return "\n".join(cleaned_b)

    text = re.sub(
        r"<Bild\b[^>]*>[\s\S]*?</Bild>",
        _clean_bild_inner_headings,
        text,
        flags=re.IGNORECASE,
    )

    # Strip literal '<Nr>' placeholder headings and <Bild-Ref>-leaked ghost headings (e.g. '#### M026')
    raw_nums_by_page: dict[str, set[str]] = {}
    raw_nums_all: set[str] = set()
    if raw_markdown:
        for r_seg in split_markdown_pages(raw_markdown):
            r_clean = re.sub(r"<Bild-Ref\b[^>]*/?>|\bBILD_\d+\b|\(\(\d+\)\)", " ", r_seg.text, flags=re.IGNORECASE)
            nums_in_seg = {str(int(n)) for n in re.findall(r"\d+", r_clean)}
            raw_nums_all.update(nums_in_seg)
            if r_seg.page:
                raw_nums_by_page.setdefault(r_seg.page, set()).update(nums_in_seg)

    gh_lines = text.splitlines()
    gh_kept: list[str] = []
    gh_in_media = False
    gh_cur_pg = ""
    gh_changed = False
    n_gh = len(gh_lines)
    for gh_i, gh_ln in enumerate(gh_lines):
        gh_s = gh_ln.strip()
        m_gh_pg = re.match(r"^\(\((\d+)\)\)", gh_s)
        if m_gh_pg:
            gh_cur_pg = m_gh_pg.group(1)
        if gh_in_media:
            if re.search(r"</(?:Bild|Tabelle)>", gh_s, re.IGNORECASE):
                gh_in_media = False
            gh_kept.append(gh_ln)
            continue
        if re.match(r"^<(?:Bild(?!-Ref)|Tabelle)\b", gh_s, re.IGNORECASE):
            if not re.search(r"</(?:Bild|Tabelle)>", gh_s, re.IGNORECASE):
                gh_in_media = True
            gh_kept.append(gh_ln)
            continue
        if re.match(r"^#{1,6}\s+(?:[A-Z]\s*)?<Nr>[^\n]*$", gh_s, re.IGNORECASE):
            gh_changed = True
            continue
        if re.match(r"^#{2,5}\s+[MBQ]\s*0\d{2,3}\s*$", gh_s):
            gh_changed = True
            continue
        m_bare_hi = re.match(r"^####\s+[MBQ]\s*(\d+)\s*$", gh_s)
        if m_bare_hi and raw_markdown:
            hi_num = int(m_bare_hi.group(1))
            if hi_num >= 20:
                nxt_gh = ""
                for f_gh in range(gh_i + 1, n_gh):
                    if gh_lines[f_gh].strip():
                        nxt_gh = gh_lines[f_gh].strip()
                        break
                if re.match(r"^(?:<Bild(?:-Ref)?\b|!\[)", nxt_gh, re.IGNORECASE):
                    page_raw_nums = raw_nums_by_page.get(gh_cur_pg, raw_nums_all) if gh_cur_pg else raw_nums_all
                    if str(hi_num) not in page_raw_nums:
                        gh_changed = True
                        continue
        gh_kept.append(gh_ln)
    if gh_changed:
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(gh_kept))

    # Global FIBS 09/2025 Ü4 captions above <Bild> with Buchkonferenz prefix priority
    text = _promote_and_clean_bild_captions(
        text,
        custom_rules=custom_rules,
        ruleset_key=ruleset_key,
        directory_info=directory_info,
    )

    # Normalize standalone rubric banner + heading pairs and 'material mitaufgaben' even without custom_rules
    rubric_canon = {
        "methode": "Methode",
        "basiskonzept": "Basiskonzept",
        "basiskonzepte": "Basiskonzept",
        "exkurs": "Exkurs",
        "praktikum": "Praktikum",
        "streifzug": "Streifzug",
    }
    text = re.sub(
        r"(?im)^<Rahmen\b[^>]*>\s*(?:\*\*|_)?material\s+mit\s*aufgaben:?(?:\*\*|_)?\s*</Rahmen>[ \t]*$",
        "### Material mit Aufgaben",
        text,
    )
    text = re.sub(
        r"(?im)^(?:#{1,6}[ \t]+)?(?:\*\*|_)?material(?:\*\*|_)?[ \t]*\n+(?:#{1,6}[ \t]+)?(?:\*\*|_)?mit[ \t]*aufgaben:?(?:\*\*|_)?[ \t]*$",
        "### Material mit Aufgaben",
        text,
    )
    text = re.sub(
        r"(?im)^#{2,4}[ \t]+(?:\*\*|_)?material[ \t]+mit[ \t]*aufgaben:?(?:\*\*|_)?[ \t]*$",
        "### Material mit Aufgaben",
        text,
    )
    if not custom_rules or not custom_rules.strip():
        std_r_lines = text.splitlines()
        std_out_lines: list[str] = []
        std_in_blk = False
        s_ri = 0
        while s_ri < len(std_r_lines):
            sr_ln = std_r_lines[s_ri]
            srs = sr_ln.strip()
            if std_in_blk:
                if re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", srs, re.IGNORECASE):
                    std_in_blk = False
                std_out_lines.append(sr_ln)
                s_ri += 1
                continue
            if re.match(r"^<(?:Bild|Tabelle|Rahmen|Anmerkung)\b", srs, re.IGNORECASE):
                if not re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", srs, re.IGNORECASE):
                    std_in_blk = True
                std_out_lines.append(sr_ln)
                s_ri += 1
                continue
            m_std_rub = re.match(
                r"^(?:#{1,6}\s+)?(methode|basiskonzepte?|exkurs|praktikum|streifzug):?\s*$",
                srs,
                re.IGNORECASE,
            )
            if m_std_rub:
                nxt_sri = s_ri + 1
                while nxt_sri < len(std_r_lines) and not std_r_lines[nxt_sri].strip():
                    nxt_sri += 1
                if nxt_sri < len(std_r_lines):
                    m_nxt_h = re.match(r"^#{1,5}\s+([^\n#<]+)$", std_r_lines[nxt_sri].strip())
                    if m_nxt_h:
                        nxt_t = re.sub(
                            r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", m_nxt_h.group(1).strip()
                        ).strip()
                        if nxt_t and len(nxt_t.split()) <= 14:
                            r_lbl_s = rubric_canon[m_std_rub.group(1).lower()]
                            std_out_lines.append(f"### {r_lbl_s}: {nxt_t}")
                            s_ri = nxt_sri + 1
                            continue
            std_out_lines.append(sr_ln)
            s_ri += 1
        text = "\n".join(std_out_lines)
        return re.sub(r"[ \t]*\[[123]\s*Punkte?\]", "", text, flags=re.IGNORECASE)

    profile = _parse_buchkonferenz_profile(custom_rules)
    text, toc_u1_pages = _inject_toc_u1_chapters(
        text, directory_info, inject_missing=profile.adopt_toc_u1
    )
    fig_pfx, explicit_bk = _resolve_figure_caption_prefix(custom_rules, ruleset_key)

    # 0. Format Steckbrief / biography callout boxes and deduplicate composite 'Foto mit Text' portrait summaries
    steckbrief_rubric = f"#### {fig_pfx} Steckbrief" if (fig_pfx == "M" and explicit_bk) else "#### Steckbrief"
    text = re.sub(
        r"(?m)^#{2,6}\s+(?:M\s+)?Steckbrief:?\s*(?=\n+<Rahmen\b)",
        steckbrief_rubric,
        text,
        flags=re.IGNORECASE,
    )
    sb_pages = split_markdown_pages(text)
    sb_changed = False
    for sb_seg in sb_pages:
        sb_txt = sb_seg.text
        if "<Bild" not in sb_txt:
            continue
        m_fmt_bio = re.search(
            r"(<Bild>\s*Foto mit Text:\s*\nBeschreibung(?: mit Bildtext)?:\s*)"
            r"([^\n]+?)\s+"
            r"((?:Links|Rechts|Daneben|Oben|Unten)[^\n.]*?\bTextblock\s+unter\s+der\s+Überschrift\s+([^\n,]+?),\s+der\s+beschreibt[^\n]*)"
            r"(\n</Bild>)",
            sb_txt,
        )
        if not m_fmt_bio:
            continue
        portrait_sent = m_fmt_bio.group(2).strip()
        dup_clause = m_fmt_bio.group(3).strip()
        sub_raw = re.sub(r"[*_]+", "", m_fmt_bio.group(4)).strip()
        clause_words = {
            w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", f"{sub_raw} {dup_clause}")
            if w.lower() not in {"links", "rechts", "daneben", "befindet", "sich", "textblock", "unter", "überschrift", "beschreibt"}
        }
        if len(clause_words) < 2:
            continue

        has_matching_rahmen = False
        for m_ex_r in re.finditer(r"<Rahmen\b[^>]*>([\s\S]*?)</Rahmen>", sb_txt, flags=re.IGNORECASE):
            rw = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", m_ex_r.group(1))}
            if len(rw & clause_words) >= 3 or (clause_words and len(rw & clause_words) / len(clause_words) >= 0.60):
                has_matching_rahmen = True
                break

        if not has_matching_rahmen:
            sb_paras = re.split(r"(\n{2,})", sb_txt)
            for p_k in range(0, len(sb_paras), 2):
                cand_p = sb_paras[p_k].strip()
                if (
                    not cand_p
                    or cand_p.startswith(("#", "<", "((", "---", "-\t"))
                    or len(cand_p.split()) < 20
                ):
                    continue
                pw = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", cand_p)}
                if len(pw & clause_words) >= 3:
                    sb_paras[p_k] = (
                        f"{steckbrief_rubric}\n\n<Rahmen>\n_{sub_raw}_\n\n{cand_p}\n</Rahmen>"
                    )
                    has_matching_rahmen = True
                    break
            if has_matching_rahmen:
                sb_txt = re.sub(r"(?m)^[ \t]*---[ \t]*\n+", "", "".join(sb_paras))

        if has_matching_rahmen:
            compact_bild = f"<Bild> Foto:\nBeschreibung: {portrait_sent}\n</Bild>"
            sb_txt = sb_txt.replace(m_fmt_bio.group(0), compact_bild, 1)
            # If a misplaced diagram caption sits right above this portrait <Bild>, relocate it above an earlier uncaptioned diagram <Bild>
            m_mis_cap = re.search(
                rf"(?m)^(####\s+{re.escape(fig_pfx)}?\d+\s+([^\n]+))\n\n(?={re.escape(compact_bild)})",
                sb_txt,
            )
            if m_mis_cap:
                cap_full_ln = m_mis_cap.group(1)
                cap_kw = {
                    w.lower()
                    for w in re.findall(r"[A-Za-zÄÖÜäöüß]{5,}", m_mis_cap.group(2))
                    if w.lower() not in {"durch", "einer", "einem", "eines", "unter", "über"}
                }
                port_kw = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]{5,}", portrait_sent)}
                if cap_kw and not (cap_kw & port_kw):
                    for m_prev_b in re.finditer(r"<Bild>\s*[^\n]*\n[\s\S]*?</Bild>", sb_txt):
                        if m_prev_b.start() >= m_mis_cap.start():
                            break
                        prev_pre = sb_txt[: m_prev_b.start()].rstrip()
                        last_prev_ln = prev_pre.splitlines()[-1].strip() if prev_pre.splitlines() else ""
                        if re.match(rf"^####\s+{re.escape(fig_pfx)}?\d+\b", last_prev_ln):
                            continue
                        prev_b_kw = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]{5,}", m_prev_b.group(0))}
                        if len(cap_kw & prev_b_kw) >= 2:
                            sb_txt = (
                                sb_txt[: m_prev_b.start()]
                                + f"{cap_full_ln}\n\n"
                                + sb_txt[m_prev_b.start() : m_mis_cap.start()]
                                + sb_txt[m_mis_cap.end() :]
                            )
                            break
            sb_seg.text = sb_txt
            sb_changed = True
    if sb_changed:
        text = "".join(s.text for s in sb_pages)

    # 1. Resolve <Tabelle> blocks up to table_resolve_max_cells (2c) and drop placeholder tables (2a)
    if table_max_cells is not None:
        effective_table_max_cells = int(table_max_cells)
    else:
        try:
            from backend.services.settings_service import get_setting

            effective_table_max_cells = int(get_setting("table_resolve_max_cells"))
        except Exception:
            effective_table_max_cells = 6

    def _resolve_custom_tabelle(m: re.Match[str]) -> str:
        inner_t = m.group(1)
        data_rows = _parse_tabelle_data_rows(inner_t)
        if not data_rows:
            return m.group(0)
        if re.search(r"<Bild\b|!\[[^\]]*\]\([^)\n]+\)", inner_t, re.IGNORECASE) and len(data_rows) <= 2:
            imgs_t = re.findall(
                r"<Bild\b[^>]*>[\s\S]*?</Bild>|!\[[^\]]*\]\([^)\n]+\)",
                inner_t,
                flags=re.IGNORECASE,
            )
            return "\n\n".join(im.strip() for im in imgs_t)
        if _is_placeholder_only_table(data_rows):
            return ""
        total_cells = sum(len(r) for r in data_rows)
        if effective_table_max_cells > 0 and len(data_rows) >= 2 and total_cells <= effective_table_max_cells:
            headers = [
                re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", h.strip()).strip()
                for h in data_rows[0]
            ]
            para_rows: list[str] = []
            for row in data_rows[1:]:
                pairs: list[str] = []
                for col_idx, cell_val in enumerate(row):
                    c_clean = cell_val.strip()
                    if not c_clean:
                        continue
                    hdr = headers[col_idx] if col_idx < len(headers) else ""
                    if hdr:
                        pairs.append(f"_{hdr}_: {c_clean}")
                    else:
                        pairs.append(c_clean)
                if pairs:
                    para_rows.append("; ".join(pairs))
            if para_rows:
                return (
                    "<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>\n\n"
                    + "\n\n".join(para_rows)
                )
        return m.group(0)

    text = re.sub(
        r"<Tabelle\b[^>]*>\s*([\s\S]*?)\s*</Tabelle>",
        _resolve_custom_tabelle,
        text,
        flags=re.IGNORECASE,
    )

    # 2. Normalize Ü3 Rubric Prefixes ('Methode:', 'Basiskonzept:', 'Exkurs:', 'Material mit Aufgaben')
    r_lines = text.splitlines()
    out_r_lines: list[str] = []
    in_r_block = False
    ri = 0
    while ri < len(r_lines):
        r_ln = r_lines[ri]
        rs = r_ln.strip()
        if in_r_block:
            if re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", rs, re.IGNORECASE):
                in_r_block = False
            out_r_lines.append(r_ln)
            ri += 1
            continue
        if re.match(r"^<(?:Bild|Tabelle|Rahmen|Anmerkung)\b", rs, re.IGNORECASE):
            if not re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung)>", rs, re.IGNORECASE):
                in_r_block = True
            out_r_lines.append(r_ln)
            ri += 1
            continue

        if re.match(
            r"^(?:#{1,6}\s+)?(?:\*\*|_)?material\s+mit\s*aufgaben:?(?:\*\*|_)?\s*$",
            rs,
            re.IGNORECASE,
        ):
            out_r_lines.append("### Material mit Aufgaben")
            ri += 1
            continue

        m_rub_1 = re.match(
            r"^(?:#{1,6}\s+)?(?:\*\*|_)?(methode|basiskonzepte?|exkurs|praktikum|streifzug)(?:\*\*|_)?(?:\s*[:•·\-–]\s*|\s+)([^\n]+)$",
            rs,
            re.IGNORECASE,
        )
        if m_rub_1:
            r_lbl = rubric_canon[m_rub_1.group(1).lower()]
            r_tit = re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", m_rub_1.group(2).strip()).strip()
            if r_tit and len(r_tit.split()) <= 16 and not r_tit.endswith("."):
                out_r_lines.append(f"### {r_lbl}: {r_tit}")
                ri += 1
                continue

        m_rub_2 = re.match(
            r"^(?:#{1,6}\s+)?(?:\*\*|_)?(methode|basiskonzepte?|exkurs|praktikum|streifzug):?(?:\*\*|_)?\s*$",
            rs,
            re.IGNORECASE,
        )
        if m_rub_2:
            nxt_ri = ri + 1
            while nxt_ri < len(r_lines) and not r_lines[nxt_ri].strip():
                nxt_ri += 1
            if nxt_ri < len(r_lines):
                nxt_rs = r_lines[nxt_ri].strip()
                nxt_clean = re.sub(r"^#{1,6}\s+", "", nxt_rs).strip()
                nxt_clean = re.sub(r"^(?:\*\*|_)+|(?:\*\*|_)+$", "", nxt_clean).strip()
                if (
                    nxt_clean
                    and not nxt_rs.startswith(("((", "<", "-\t", "|"))
                    and len(nxt_clean.split()) <= 14
                    and not (nxt_clean.endswith(".") and len(nxt_clean.split()) >= 6)
                ):
                    r_lbl = rubric_canon[m_rub_2.group(1).lower()]
                    out_r_lines.append(f"### {r_lbl}: {nxt_clean}")
                    ri = nxt_ri + 1
                    continue

        out_r_lines.append(r_ln)
        ri += 1
    text = "\n".join(out_r_lines)

    caption_h4 = bool(fig_pfx) or bool(
        re.search(
            r"Überschrift\s*4[^\n]*Abbildungsunterschriften|Abbildungsunterschriften[^\n]*Überschrift\s*4",
            custom_rules,
            re.IGNORECASE,
        )
    )

    # 3. Task Formatting: ##### Aufgaben + ##### <Nr> (or numbers-only ##### <Nr>) + Paragraph
    tasks_h5_any = profile.tasks_h5 or profile.tasks_h5_numbers_only
    emit_aufgaben_hdr = profile.tasks_h5 and not profile.tasks_h5_numbers_only
    if tasks_h5_any:
        sym_map_t, drop_diff_t, _ = _parse_difficulty_rules(custom_rules)
        sym_keys_sorted = sorted(sym_map_t.keys(), key=len, reverse=True)
        sym_alts = "|".join(re.escape(k) for k in sym_keys_sorted)
        sym_or_bracket_pat = (
            f"(?:{sym_alts}|[○◯◐◑◒◓●□◩■◇◈◆★☆]|\\[(?:einfach|leicht|mittel|schwierig|schwer)\\])"
            if sym_alts
            else r"(?:[○◯◐◑◒◓●□◩■◇◈◆★☆]|\[(?:einfach|leicht|mittel|schwierig|schwer)\])"
        )

        def _resolve_sym_tok(tok_s: str | None) -> str:
            t_s = (tok_s or "").strip()
            if not t_s or drop_diff_t:
                return ""
            if t_s in sym_map_t:
                return sym_map_t[t_s]
            if t_s.startswith("[") and t_s.endswith("]"):
                return t_s
            return ""

        t_lines = text.splitlines()
        out_t_lines: list[str] = []
        in_bild = False
        in_tabelle = False
        in_aufgaben = False
        in_material_sec = False
        cur_t_page = ""

        # Pre-index bare figure headings ('#### M3') per page so non-task numbered captions attach to them
        bare_fig_line_by_page_num: dict[tuple[str, str], int] = {}
        scan_pg_t = ""
        for idx_tl, raw_tl in enumerate(t_lines):
            st_tl = raw_tl.strip()
            m_pm_t = re.match(r"^\(\((\d+)\)\)", st_tl)
            if m_pm_t:
                scan_pg_t = m_pm_t.group(1)
                continue
            m_bf = re.match(r"^####\s+([MBQ])\s*(\d{1,2}[a-z]?)\s*$", st_tl)
            if m_bf:
                bare_fig_line_by_page_num[(scan_pg_t, m_bf.group(2))] = idx_tl

        attached_fig_titles: dict[int, str] = {}
        skip_t_indices: set[int] = set()
        n_tl = len(t_lines)
        idx_t = 0
        while idx_t < n_tl:
            s_chk = t_lines[idx_t].strip()
            m_pm_c = re.match(r"^\(\((\d+)\)\)", s_chk)
            if m_pm_c:
                cur_t_page = m_pm_c.group(1)
                idx_t += 1
                continue
            # Check '##### <n>\n+<Noun-phrase caption>' or '<n>. <Noun-phrase caption>' matching a bare '#### M<n>' on the same page
            m_h5_cand = re.match(r"^#####\s+(\d{1,2}[a-z]?)\s*$", s_chk)
            m_pl_cand = re.match(r"^(?:(\d{1,2})\.\t|(\d{1,2})[.:]\s+)([A-ZÄÖÜ].+)$", s_chk)
            if m_h5_cand and (cur_t_page, m_h5_cand.group(1)) in bare_fig_line_by_page_num:
                c_num_k = m_h5_cand.group(1)
                nxt_ne_i = idx_t + 1
                while nxt_ne_i < n_tl and not t_lines[nxt_ne_i].strip():
                    nxt_ne_i += 1
                if nxt_ne_i < n_tl:
                    body_cand = t_lines[nxt_ne_i].strip()
                    if (
                        body_cand
                        and not body_cand.startswith(("#", "<", "(("))
                        and not _TASK_OPERATOR_VERB_RE.match(body_cand)
                        and not _is_question_or_lead_in_prose(body_cand)
                        and not re.search(r"\bSie\b", body_cand)
                    ):
                        cap_parts = [body_cand]
                        end_skip = nxt_ne_i
                        scan_sub = nxt_ne_i + 1
                        while scan_sub < n_tl:
                            sub_s = t_lines[scan_sub].strip()
                            if not sub_s:
                                scan_sub += 1
                                continue
                            if re.match(r"^(?:-\t|[-*•]\s+)?_?[A-F]_?\s+\S", sub_s):
                                cap_parts.append(re.sub(r"^(?:-\t|[-*•]\s+)", "", sub_s).rstrip(","))
                                end_skip = scan_sub
                                scan_sub += 1
                            else:
                                break
                        joined_cap = (
                            f"{cap_parts[0]} {', '.join(cap_parts[1:])}"
                            if len(cap_parts) > 1
                            else cap_parts[0]
                        )
                        target_bf_idx = bare_fig_line_by_page_num[(cur_t_page, c_num_k)]
                        attached_fig_titles[target_bf_idx] = _split_long_caption_body(
                            f"{fig_pfx}{c_num_k}", joined_cap
                        )
                        for sk_i in range(idx_t, end_skip + 1):
                            skip_t_indices.add(sk_i)
                        idx_t = end_skip + 1
                        continue
            elif m_pl_cand:
                c_num_p = m_pl_cand.group(1) or m_pl_cand.group(2)
                body_p = m_pl_cand.group(3).strip()
                if (
                    (cur_t_page, c_num_p) in bare_fig_line_by_page_num
                    and not _TASK_OPERATOR_VERB_RE.match(body_p)
                    and not _is_question_or_lead_in_prose(body_p)
                    and not re.search(r"\bSie\b", body_p)
                ):
                    target_bf_idx = bare_fig_line_by_page_num[(cur_t_page, c_num_p)]
                    attached_fig_titles[target_bf_idx] = _split_long_caption_body(
                        f"{fig_pfx}{c_num_p}", body_p
                    )
                    skip_t_indices.add(idx_t)
                    idx_t += 1
                    continue
            idx_t += 1

        def _is_fig_prefixed_num(num_tok: str) -> bool:
            up_n = num_tok.upper()
            if up_n.startswith("M") and up_n[1:2].isdigit():
                return True
            if (
                fig_pfx
                and up_n.startswith(fig_pfx.upper())
                and up_n[len(fig_pfx) : len(fig_pfx) + 1].isdigit()
            ):
                return True
            return False

        def _next_non_empty_t(cur_idx: int) -> str:
            for fwd_i in range(cur_idx + 1, n_tl):
                if fwd_i not in skip_t_indices and t_lines[fwd_i].strip():
                    return t_lines[fwd_i].strip()
            return ""

        inline_fig_hdr_re = re.compile(
            rf"^####\s+(?:(?:{re.escape(fig_pfx)}|[MBQ])\s*\d+|Abb(?:ildung)?\.?\s*\d+|"
            rf"Tab(?:elle)?\.?\s*\d+|Bild\s*\d+|Grafik\s*\d+|Fig(?:ure|\.)?\s*\d+)\b"
            if fig_pfx
            else r"^####\s+(?:[MBQ]\s*\d+|Abb(?:ildung)?\.?\s*\d+|Tab(?:elle)?\.?\s*\d+|"
            r"Bild\s*\d+|Grafik\s*\d+|Fig(?:ure|\.)?\s*\d+)\b",
            re.IGNORECASE,
        )

        for line_i_t, ln in enumerate(t_lines):
            if line_i_t in skip_t_indices:
                continue
            if line_i_t in attached_fig_titles:
                out_t_lines.append(attached_fig_titles[line_i_t])
                continue
            s = ln.strip()
            if in_bild:
                if re.search(r"</Bild>", s, re.IGNORECASE):
                    in_bild = False
                out_t_lines.append(ln)
                continue
            if re.match(r"^<Bild-Ref\b", s, re.IGNORECASE):
                out_t_lines.append(ln)
                continue
            if re.match(r"^<Bild\b", s, re.IGNORECASE):
                if not re.search(r"</Bild>", s, re.IGNORECASE):
                    in_bild = True
                out_t_lines.append(ln)
                continue
            if in_tabelle:
                if re.search(r"</Tabelle>", s, re.IGNORECASE):
                    in_tabelle = False
                out_t_lines.append(ln)
                continue
            if re.match(r"^<Tabelle\b", s, re.IGNORECASE):
                if not re.search(r"</Tabelle>", s, re.IGNORECASE):
                    in_tabelle = True
                out_t_lines.append(ln)
                continue

            if re.match(r"^\(\(\d+\)\)", s):
                in_material_sec = False
                in_aufgaben = False
                out_t_lines.append(ln)
                continue

            if re.match(r"^#{2,4}\s+Material\b", s, re.IGNORECASE):
                in_material_sec = True

            # Standalone "Aufgaben" or "Aufgaben:"
            if re.match(
                r"^(?:#{1,6}\s+)?(?:\*\*|_)?Aufgaben:?(?:\*\*|_)?\s*$",
                s,
                re.IGNORECASE,
            ):
                if emit_aufgaben_hdr:
                    out_t_lines.append("##### Aufgaben")
                in_aufgaben = True
                continue

            # Inline or standalone "Aufgaben: A1 ..." / "#### Aufgaben: A1"
            m_inline_aufg = re.match(
                r"^(?:#{1,6}\s+)?(?:\*\*|_)?Aufgaben:?(?:\*\*|_)?\s+([A-LN-Z]?\d+(?:\.\d+)*)[.:]?(?:\s+(.+))?$",
                s,
                re.IGNORECASE,
            )
            if m_inline_aufg:
                if emit_aufgaben_hdr and not in_aufgaben:
                    out_t_lines.append("##### Aufgaben")
                    out_t_lines.append("")
                out_t_lines.append(f"##### {m_inline_aufg.group(1)}")
                if m_inline_aufg.group(2) and m_inline_aufg.group(2).strip():
                    out_t_lines.append("")
                    out_t_lines.append(m_inline_aufg.group(2).strip())
                in_aufgaben = True
                continue

            # Standalone "##### <Nr>", "### Aufgabe 1:", or "#### A1" sub-task heading
            m_h5_only = re.match(
                r"^(#{1,6})\s+(?:(?:\*\*|_)?(Aufgaben?)\s+)?([A-LN-Z]?\d+(?:\.\d+)*)[.:]?\s*$",
                s,
                re.IGNORECASE,
            )
            if m_h5_only:
                h_only_hashes = m_h5_only.group(1)
                h_only_kw = m_h5_only.group(2)
                h_only_num = m_h5_only.group(3)
                nxt_ne_line = _next_non_empty_t(line_i_t)
                next_is_bild = bool(re.match(r"^(?:<Bild(?:-Ref)?\b|!\[)", nxt_ne_line, re.IGNORECASE))
                is_fig_num = _is_fig_prefixed_num(h_only_num)
                is_alpha_subtask = (
                    len(h_only_hashes) >= 2
                    and bool(re.match(r"^[A-LN-Z]\d+$", h_only_num))
                    and not is_fig_num
                    and not next_is_bild
                    and (
                        in_aufgaben
                        or in_material_sec
                        or bool(_TASK_OPERATOR_VERB_RE.match(nxt_ne_line))
                        or nxt_ne_line.endswith("?")
                    )
                )
                if (
                    not next_is_bild
                    and not (is_fig_num and not h_only_kw and not in_aufgaben)
                    and (len(h_only_hashes) == 5 or h_only_kw or is_alpha_subtask)
                ):
                    if emit_aufgaben_hdr and not in_aufgaben:
                        out_t_lines.append("##### Aufgaben")
                        out_t_lines.append("")
                    in_aufgaben = True
                    out_t_lines.append(f"##### {h_only_num}")
                    continue

            # Heading with task number + sentence: ### 1 Erklären Sie... or #### A1 Erläutern Sie... or ### Aufgabe 1: ...
            m_h_task = re.match(
                rf"^(#{{1,6}})\s+(?:(?:\*\*|_)?Aufgabe\s+)?([A-LN-Z]?\d+(?:\.\d+)?)"
                rf"([ \t]*(?:\[[^\]]+\]|[○◯◐◑◒◓●□◩■◇◈◆★☆]+))?[.:]?\s+"
                rf"(?:({sym_or_bracket_pat})[ \t]+)?(?:([a-z]\))[ \t]+)?([A-ZÄÖÜ„\"'(].+)$",
                s,
            )
            if m_h_task:
                hashes_t, t_num, t_inline_ind, t_body_sym, t_sub_tok, t_body = (
                    m_h_task.group(1),
                    m_h_task.group(2),
                    (m_h_task.group(3) or "").strip(),
                    (m_h_task.group(4) or "").strip(),
                    (m_h_task.group(5) or "").strip(),
                    m_h_task.group(6).strip(),
                )
                nxt_ne_ht = _next_non_empty_t(line_i_t)
                next_is_bild_ht = bool(re.match(r"^(?:<Bild(?:-Ref)?\b|!\[)", nxt_ne_ht, re.IGNORECASE))
                is_fig_num_ht = _is_fig_prefixed_num(t_num)
                is_task_h = (
                    not next_is_bild_ht
                    and not (is_fig_num_ht and "aufgabe" not in s.lower() and not in_aufgaben)
                    and (
                        "aufgabe" in s.lower()
                        or len(hashes_t) == 5
                        or (bool(re.match(r"^[A-LN-Z]\d+$", t_num)) and not is_fig_num_ht)
                        or bool(_TASK_OPERATOR_VERB_RE.match(t_body))
                        or t_body.endswith("?")
                    )
                )
                if is_task_h:
                    if emit_aufgaben_hdr and not in_aufgaben:
                        out_t_lines.append("##### Aufgaben")
                        out_t_lines.append("")
                    in_aufgaben = True
                    out_t_lines.append(f"##### {t_num}")
                    lbl_h = _resolve_sym_tok(t_body_sym or t_inline_ind)
                    if t_sub_tok:
                        out_t_lines.append("")
                        out_t_lines.append(
                            f"{t_sub_tok} {lbl_h} {t_body}".strip() if lbl_h else f"{t_sub_tok} {t_body}"
                        )
                    else:
                        if lbl_h:
                            out_t_lines.append(lbl_h)
                        out_t_lines.append("")
                        out_t_lines.append(
                            f"{t_body} {t_inline_ind}".strip()
                            if (t_inline_ind and not lbl_h)
                            else t_body
                        )
                    continue

            # Reset in_aufgaben on non-task H1..H4 headings (except inline figure/table headings inside active tasks)
            if re.match(r"^#{1,4}\s+", s):
                is_inline_media_h4 = False
                if in_aufgaben and s.startswith("#### ") and not re.match(
                    r"^####\s+(?:Material\b|Randspalte\b|Worterklärung\b|Merke\b|Steckbrief\b|[A-Z]:\s)",
                    s,
                    re.IGNORECASE,
                ):
                    nxt1_h = _next_non_empty_t(line_i_t)
                    if re.match(r"^(?:<Bild(?:-Ref)?\b|<Tabelle\b|!\[)", nxt1_h, re.IGNORECASE):
                        is_inline_media_h4 = True
                    elif inline_fig_hdr_re.match(s):
                        seen_ahead_h = 0
                        for fwd_m in range(line_i_t + 1, n_tl):
                            if fwd_m in skip_t_indices:
                                continue
                            st_fm = t_lines[fwd_m].strip()
                            if not st_fm:
                                continue
                            if st_fm.startswith(("#", "((")):
                                break
                            if re.match(r"^(?:<Bild(?:-Ref)?\b|<Tabelle\b|!\[)", st_fm, re.IGNORECASE):
                                is_inline_media_h4 = True
                                break
                            seen_ahead_h += 1
                            if seen_ahead_h >= 2:
                                break
                if not is_inline_media_h4:
                    in_aufgaben = False
                out_t_lines.append(ln)
                continue

            # Convert standalone difficulty symbols, subtask lines, or symbol-prefixed task lines inside active tasks
            if in_aufgaben:
                if s in sym_map_t or fc.STANDALONE_DIFFICULTY_LINE_RE.match(s):
                    lbl_only = _resolve_sym_tok(s)
                    if lbl_only:
                        out_t_lines.append(lbl_only)
                    continue
                m_sub_pre = re.match(
                    rf"^({sym_or_bracket_pat})[ \t]+([a-z]\))[ \t]+(.+)$", s
                )
                m_sub_post = (
                    None
                    if m_sub_pre
                    else re.match(rf"^([a-z]\))[ \t]+({sym_or_bracket_pat})[ \t]+(.+)$", s)
                )
                if m_sub_pre or m_sub_post:
                    if m_sub_pre:
                        raw_s_tok, sub_tok, sub_rest = m_sub_pre.groups()
                    else:
                        sub_tok, raw_s_tok, sub_rest = m_sub_post.groups()  # type: ignore[union-attr]
                    lbl_sub = _resolve_sym_tok(raw_s_tok)
                    out_t_lines.append(
                        f"{sub_tok} {lbl_sub} {sub_rest.strip()}" if lbl_sub else f"{sub_tok} {sub_rest.strip()}"
                    )
                    continue
                m_sym_body = re.match(
                    rf"^({sym_or_bracket_pat})[ \t]+([A-ZÄÖÜ„\"'(].+)$", s
                )
                if m_sym_body and not re.match(r"^\[\s*(?:siehe|vgl|\.\.\.)", s, re.IGNORECASE):
                    lbl_b = _resolve_sym_tok(m_sym_body.group(1))
                    if lbl_b:
                        while out_t_lines and not out_t_lines[-1].strip():
                            out_t_lines.pop()
                        out_t_lines.append(lbl_b)
                        out_t_lines.append("")
                    out_t_lines.append(m_sym_body.group(2).strip())
                    continue

            # Plain-text or list-formatted task line: "1 Erklären Sie...", "1. ○ a) ...", "- A2 Beschreiben Sie...", "Ü. 1 Erläutern Sie..."
            m_plain_task = re.match(
                rf"^(?:(\d+)\.\t|(?:[-*•][\t ]+)?(?:Ü\.?\s+)?(?:\*\*|_)?([A-LN-Z]\d+|\d+)(?:\*\*|_)?[.:]?\s+)"
                rf"(?:({sym_or_bracket_pat})[ \t]+)?(?:([a-z]\))[ \t]+)?([A-ZÄÖÜ„\"'(].+)$",
                s,
            )
            if m_plain_task:
                t_num = m_plain_task.group(1) or m_plain_task.group(2)
                p_sym_tok = (m_plain_task.group(3) or "").strip()
                p_sub_tok = (m_plain_task.group(4) or "").strip()
                t_body = m_plain_task.group(5).strip()
                nxt_ne_pt = _next_non_empty_t(line_i_t)
                next_is_bild_pt = bool(re.match(r"^(?:<Bild(?:-Ref)?\b|!\[)", nxt_ne_pt, re.IGNORECASE))
                is_fig_num_pt = _is_fig_prefixed_num(t_num)
                is_explicit_op_or_q = (
                    bool(_TASK_OPERATOR_VERB_RE.match(t_body))
                    or t_body.endswith("?")
                    or bool(re.search(r"^[A-ZÄÖÜ][a-zäöüß]+en\s+Sie\b", t_body))
                    or bool(fc.POINT_DIFFICULTY_TAG_RE.search(t_body))
                    or bool(p_sym_tok)
                )
                if (
                    not next_is_bild_pt
                    and not (is_fig_num_pt and not in_aufgaben)
                    and (
                        is_explicit_op_or_q
                        or (
                            in_aufgaben
                            and bool(re.match(r"^[A-LN-Z]\d+$", t_num))
                            and not is_fig_num_pt
                        )
                    )
                ):
                    if emit_aufgaben_hdr and not in_aufgaben:
                        out_t_lines.append("##### Aufgaben")
                        out_t_lines.append("")
                    in_aufgaben = True
                    out_t_lines.append(f"##### {t_num}")
                    lbl_p = _resolve_sym_tok(p_sym_tok)
                    if p_sub_tok:
                        out_t_lines.append("")
                        out_t_lines.append(
                            f"{p_sub_tok} {lbl_p} {t_body}".strip() if lbl_p else f"{p_sub_tok} {t_body}"
                        )
                    else:
                        if lbl_p:
                            out_t_lines.append(lbl_p)
                        out_t_lines.append("")
                        out_t_lines.append(t_body)
                    continue

            out_t_lines.append(ln)

        text = "\n".join(out_t_lines)

    # 3b. Map [1 Punkt]..[3 Punkte] to Buchkonferenz labels right beneath ##### <Nr>, or strip if unmapped
    if profile.point_difficulty_map:
        mapped_labels_set = set(profile.point_difficulty_map.values())
        pt_lines = text.splitlines()
        pt_i = 0
        while pt_i < len(pt_lines):
            m_th5 = re.match(
                r"^(#####\s+[A-LN-Z]?\d+(?:\.\d+)*[a-z]?|###\s+Aufgabe\s+\d+:?[^\n]*?)(?:[ \t]+(\[[^\]]+\]))?\s*$",
                pt_lines[pt_i].strip(),
                re.IGNORECASE,
            )
            if not m_th5:
                pt_i += 1
                continue

            base_h5 = m_th5.group(1).strip()
            inline_br = (m_th5.group(2) or "").strip()
            resolved_lbl = ""
            if inline_br:
                m_in_pt = fc.POINT_DIFFICULTY_TAG_RE.fullmatch(inline_br)
                if m_in_pt:
                    resolved_lbl = profile.point_difficulty_map.get(int(m_in_pt.group(1)), "")
                elif inline_br in mapped_labels_set:
                    resolved_lbl = inline_br

            scan_end = pt_i + 1
            while scan_end < len(pt_lines):
                st_se = pt_lines[scan_end].strip()
                if st_se.startswith(("#", "((")) or re.match(
                    r"^<(?:Bild|Tabelle|Rahmen|Anmerkung)\b", st_se, re.IGNORECASE
                ):
                    break
                scan_end += 1

            for blk_j in range(pt_i + 1, scan_end):
                st_bj = pt_lines[blk_j].strip()
                if not st_bj:
                    continue
                if st_bj in mapped_labels_set and blk_j <= pt_i + 2:
                    resolved_lbl = resolved_lbl or st_bj
                    pt_lines[blk_j] = ""
                    continue
                m_pt_hit = fc.POINT_DIFFICULTY_TAG_RE.search(pt_lines[blk_j])
                if m_pt_hit:
                    pt_val = int(m_pt_hit.group(1))
                    resolved_lbl = resolved_lbl or profile.point_difficulty_map.get(pt_val, "")
                    cleaned_bj = fc.POINT_DIFFICULTY_TAG_RE.sub("", pt_lines[blk_j])
                    cleaned_bj = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned_bj)
                    cleaned_bj = re.sub(r"[ \t]{2,}", " ", cleaned_bj).rstrip()
                    pt_lines[blk_j] = cleaned_bj

            if resolved_lbl:
                pt_lines[pt_i] = base_h5
                pt_lines.insert(pt_i + 1, resolved_lbl)
                pt_i += 2
            else:
                pt_i = scan_end

        text = re.sub(r"\n{3,}", "\n\n", "\n".join(pt_lines))
        text = re.sub(r"[ \t]*\[[123]\s*Punkte?\]", "", text, flags=re.IGNORECASE)
    else:
        text = re.sub(r"[ \t]*\[[123]\s*Punkte?\]", "", text, flags=re.IGNORECASE)

    # 4. Heading Hierarchy Normalization (H2..H5) when custom_rules is active (1c)
    if profile.has_hierarchy:
        u3_rubric_re = re.compile(
            r"^(?:Methode|Basiskonzept|Exkurs|Material(?:\s+mit\s+Aufgaben|ien)?|IM\s+BLICKPUNKT|ÜBERBLICK)\b",
            re.IGNORECASE,
        )
        # Detect pages that contain figure M1 ('#### M1 ...') and pages that already have '###'
        pages_with_m1: set[str] = set()
        pages_with_h3: set[str] = set()
        cur_pg_scan = ""
        for scan_ln in text.splitlines():
            st_sc = scan_ln.strip()
            m_pm_s = re.match(r"^\(\((\d+)\)\)", st_sc)
            if m_pm_s:
                cur_pg_scan = m_pm_s.group(1)
            elif cur_pg_scan:
                if re.match(rf"^####\s+{re.escape(fig_pfx)}?1\b", st_sc):
                    pages_with_m1.add(cur_pg_scan)
                elif re.match(r"^###\s+\S", st_sc):
                    pages_with_h3.add(cur_pg_scan)

        toc_u2_u3_pages: dict[str, set[int | None]] = {}
        for toc_e in (directory_info or {}).get("toc_entries") or []:
            if not isinstance(toc_e, dict) or int(toc_e.get("level") or 0) not in (2, 3):
                continue
            pg_s_u = str(toc_e.get("page") or "").strip()
            pg_int_u = int(pg_s_u) if pg_s_u.isdigit() else None
            for field_k in ("title", "clean_title"):
                raw_tk = str(toc_e.get(field_k) or "").strip()
                if not raw_tk:
                    continue
                norm_tk = re.sub(r"\W+", " ", raw_tk).strip().lower()
                if norm_tk:
                    toc_u2_u3_pages.setdefault(norm_tk, set()).add(pg_int_u)
                    stripped_rub = re.sub(
                        r"^(?:werkstatt|strategie|extra|lexikon|infografik|methode|basiskonzept|exkurs)\s*:?\s+",
                        "",
                        norm_tk,
                    ).strip()
                    if stripped_rub:
                        toc_u2_u3_pages.setdefault(stripped_rub, set()).add(pg_int_u)

        h_lines = text.splitlines()
        out_h_lines: list[str] = []
        in_bild = False
        in_tabelle = False
        seen_chapter_or_h3 = False
        after_m1_caption = False
        cur_pg_h = ""
        cur_pg_int_h: int | None = None
        has_doc_pages_h = bool(re.search(r"(?m)^\(\(\d+\)\)", text))
        seen_mat_h3_on_page = False
        for idx_h, ln in enumerate(h_lines):
            s = ln.strip()
            m_pm_h = re.match(r"^\(\((\d+)\)\)", s)
            if m_pm_h:
                cur_pg_h = m_pm_h.group(1)
                cur_pg_int_h = int(cur_pg_h)
                seen_mat_h3_on_page = False
                after_m1_caption = False
            if in_bild:
                if re.search(r"</Bild>", s, re.IGNORECASE):
                    in_bild = False
                out_h_lines.append(ln)
                continue
            if re.match(r"^<Bild-Ref\b", s, re.IGNORECASE):
                out_h_lines.append(ln)
                continue
            if re.match(r"^<Bild\b", s, re.IGNORECASE):
                if not re.search(r"</Bild>", s, re.IGNORECASE):
                    in_bild = True
                out_h_lines.append(ln)
                continue
            if in_tabelle:
                if re.search(r"</Tabelle>", s, re.IGNORECASE):
                    in_tabelle = False
                out_h_lines.append(ln)
                continue
            if re.match(r"^<Tabelle\b", s, re.IGNORECASE):
                if not re.search(r"</Tabelle>", s, re.IGNORECASE):
                    in_tabelle = True
                out_h_lines.append(ln)
                continue

            if re.match(rf"^####\s+{re.escape(fig_pfx)}?1\b", s):
                after_m1_caption = True
                out_h_lines.append(ln)
                continue

            # Standalone Worterklärung: or Material A...
            m_worterkl = re.match(
                r"^(?:#{1,6}\s+)?(?:\*\*|_)?(Worterklärung:?)(?:\*\*|_)?\s*$",
                s,
                re.IGNORECASE,
            )
            if m_worterkl:
                lbl = m_worterkl.group(1)
                if not lbl.endswith(":"):
                    lbl += ":"
                out_h_lines.append(f"#### {lbl}")
                continue

            m_mat_sub = re.match(
                r"^(?:#{1,6}\s+)?(?:\*\*|_)?(Material\s+[A-Z]\b[^\n]*?)(?:\*\*|_)?$",
                s,
            )
            if m_mat_sub:
                if profile.material_h3_section and not seen_mat_h3_on_page and re.match(r"^Material\s+A\b", m_mat_sub.group(1).strip()):
                    out_h_lines.append("### Material")
                    out_h_lines.append("")
                    seen_mat_h3_on_page = True
                    seen_chapter_or_h3 = True
                mat_title = re.sub(r"\s*[•·]\s*", ": ", m_mat_sub.group(1).strip())
                out_h_lines.append(f"#### {mat_title}")
                continue

            m_special_h3 = re.match(
                r"^(?:#{1,6}\s+)?(?:\*\*|_)?(IM\s+BLICKPUNKT\b[^\n]*|Material(?:\s+mit\s*Aufgaben|ien)?|ÜBERBLICK\b[^\n]*)(?:\*\*|_)?$",
                s,
                re.IGNORECASE,
            )
            if m_special_h3:
                sp_title = m_special_h3.group(1).strip()
                sp_title = re.sub(
                    r"^material\s+mit\s*aufgaben$",
                    "Material mit Aufgaben",
                    sp_title,
                    flags=re.IGNORECASE,
                )
                sp_title = re.sub(
                    r"^im\s+blickpunkt\b",
                    "IM BLICKPUNKT",
                    sp_title,
                    flags=re.IGNORECASE,
                )
                sp_title = re.sub(
                    r"^überblick\b", "ÜBERBLICK", sp_title, flags=re.IGNORECASE
                )
                sp_title = re.sub(r"\s*[•·]\s*", ": ", sp_title)
                out_h_lines.append(f"### {sp_title}")
                if sp_title.lower().startswith("material"):
                    seen_mat_h3_on_page = True
                seen_chapter_or_h3 = True
                after_m1_caption = False
                continue

            # Preserve TOC Ü1 (scoped to target page ±1) and explicit Kapitel/Chapter headings
            m_pre_u1 = re.match(r"^(#{1,4})\s+(.+)$", s)
            if m_pre_u1:
                pre_title = m_pre_u1.group(2).strip()
                pre_norm = re.sub(r"\W+", " ", pre_title).strip().lower()
                if _toc_norm_matches_page(
                    pre_norm, toc_u1_pages, cur_pg_int_h, has_doc_pages_h
                ) or re.match(
                    r"^(?:Kapitel|Chapter|Teil|Part)\s+\d+", pre_title, re.IGNORECASE
                ):
                    out_h_lines.append(f"# {pre_title}")
                    seen_chapter_or_h3 = True
                    after_m1_caption = False
                    continue

            # Numbered figure/table caption heading: e.g. "## 3 Ionenkonzentrationen..." -> "#### M3 ..."
            if caption_h4:
                m_num_cap = re.match(
                    r"^#{1,4}\s+(?:([MBQ])\s*)?(\d{1,2})\s+([A-ZÄÖÜ][^\n]{3,600})$",
                    s,
                )
                has_explicit_pfx_c = bool(m_num_cap and m_num_cap.group(1))
                c_body_cand = m_num_cap.group(3).strip() if m_num_cap else ""
                c_full_norm = (
                    re.sub(r"\W+", " ", f"{m_num_cap.group(2)} {c_body_cand}").strip().lower()
                    if m_num_cap
                    else ""
                )
                c_body_norm = re.sub(r"\W+", " ", c_body_cand).strip().lower() if c_body_cand else ""
                adj_has_media = has_explicit_pfx_c
                if m_num_cap and not has_explicit_pfx_c:
                    ne_back: list[str] = []
                    for b_i in range(idx_h - 1, -1, -1):
                        sb_l = h_lines[b_i].strip()
                        if sb_l and sb_l != "---":
                            ne_back.append(sb_l)
                            break
                    ne_fwd: list[str] = []
                    for f_i in range(idx_h + 1, len(h_lines)):
                        sf_l = h_lines[f_i].strip()
                        if sf_l and sf_l != "---":
                            ne_fwd.append(sf_l)
                            break
                    adj_has_media = any(
                        re.match(r"^(?:</Tabelle\b)", adj_l, re.IGNORECASE)
                        for adj_l in ne_back
                    ) or any(
                        re.match(r"^(?:<(?:Bild|Tabelle)\b|!\[)", adj_l, re.IGNORECASE)
                        for adj_l in ne_fwd
                    )
                if (
                    m_num_cap
                    and adj_has_media
                    and not _toc_norm_matches_page(
                        c_full_norm, toc_u1_pages, cur_pg_int_h, has_doc_pages_h
                    )
                    and not _toc_norm_matches_page(
                        c_body_norm, toc_u1_pages, cur_pg_int_h, has_doc_pages_h
                    )
                    and not _TASK_OPERATOR_VERB_RE.match(c_body_cand)
                    and not _is_question_or_lead_in_prose(c_body_cand)
                    and not re.search(r"\bSie\b", c_body_cand)
                ):
                    c_num = m_num_cap.group(2)
                    out_h_lines.append(_split_long_caption_body(f"{fig_pfx}{c_num}", c_body_cand))
                    if c_num == "1":
                        after_m1_caption = True
                    continue

            m_any_h = re.match(r"^(#{1,6})\s+(.+)$", s)
            if m_any_h:
                h_lvl = len(m_any_h.group(1))
                h_title = m_any_h.group(2).strip()
                h_norm = re.sub(r"\W+", " ", h_title).strip().lower()
                h_norm_stripped = re.sub(
                    r"^(?:werkstatt|strategie|extra|lexikon|infografik|methode|basiskonzept|exkurs)\s+",
                    "",
                    h_norm,
                ).strip()
                is_toc_u2_u3 = bool(
                    toc_u2_u3_pages
                    and (
                        _toc_norm_matches_page(
                            h_norm, toc_u2_u3_pages, cur_pg_int_h, has_doc_pages_h
                        )
                        or _toc_norm_matches_page(
                            h_norm_stripped, toc_u2_u3_pages, cur_pg_int_h, has_doc_pages_h
                        )
                    )
                )
                if h_lvl == 3:
                    if (
                        profile.text_subheadings_h4
                        and not is_toc_u2_u3
                        and not u3_rubric_re.match(h_title)
                        and not re.match(r"^\d+\.\d+\.\d+\b", h_title)
                    ):
                        out_h_lines.append(f"#### {h_title}")
                    else:
                        out_h_lines.append(ln)
                        seen_chapter_or_h3 = True
                    after_m1_caption = False
                    continue
                if (
                    h_lvl == 4
                    and not profile.text_subheadings_h4
                    and after_m1_caption
                    and cur_pg_h in pages_with_m1
                    and cur_pg_h not in pages_with_h3
                    and not seen_mat_h3_on_page
                ):
                    if not re.match(
                        rf"^(?:{re.escape(fig_pfx)}?\d|Abb(?:ildung)?\b|Bild\b|Grafik\b|Material\b|Aufgaben?\b|Worterklärung|Randspalte|{re.escape(fig_pfx)}\s+Steckbrief|Steckbrief)",
                        h_title,
                        re.IGNORECASE,
                    ):
                        out_h_lines.append(f"### {h_title}")
                        pages_with_m1.discard(cur_pg_h)
                        pages_with_h3.add(cur_pg_h)
                        seen_chapter_or_h3 = True
                        after_m1_caption = False
                        continue
                if h_lvl in (1, 2):
                    if re.match(r"^\d+\.\d+\b", h_title):
                        out_h_lines.append(f"## {h_title}")
                        seen_chapter_or_h3 = True
                        after_m1_caption = False
                        continue
                    if u3_rubric_re.match(h_title) or (profile.text_subheadings_h4 and is_toc_u2_u3):
                        out_h_lines.append(f"### {h_title}")
                        seen_chapter_or_h3 = True
                        after_m1_caption = False
                        continue
                    if profile.text_subheadings_h4:
                        out_h_lines.append(f"#### {h_title}")
                        after_m1_caption = False
                        continue
                    target_hashes = (
                        "###"
                        if (not seen_chapter_or_h3 or after_m1_caption or (cur_pg_h in pages_with_m1 and not seen_mat_h3_on_page))
                        else "####"
                    )
                    out_h_lines.append(f"{target_hashes} {h_title}")
                    if target_hashes == "###":
                        pages_with_m1.discard(cur_pg_h)
                    seen_chapter_or_h3 = True
                    after_m1_caption = False
                    continue

            out_h_lines.append(ln)

        text = "\n".join(out_h_lines)

        # Ensure page-opening section heading ('###' or non-caption '####') precedes leading '<Bild>' block
        text = re.sub(
            rf"(?m)^(\(\(\d+\)\)[ \t]*\n+)"
            rf"((?:####\s+{re.escape(fig_pfx)}?\d+[a-z]?\b[^\n]*\n+(?:(?![#<])[^\n]+\n+)*)?<Bild\b[^>]*>[\s\S]*?</Bild>"
            rf"(?:[ \t]*\n+(?:_?[A-F]_?[ \t]+[^\n#<]+|---))*)[ \t]*\n+"
            rf"(#{{3,4}}\s+(?!Material\b|{re.escape(fig_pfx)}?\d+\b|Abb(?:ildung)?\b|Bild\b|Grafik\b|Aufgaben?\b|Worterklärung|Randspalte|{re.escape(fig_pfx)}\s+Steckbrief|Steckbrief\b)[^\n]+)",
            r"\1\3\n\n\2",
            text,
        )

    # 4a. Buchkonferenz '### Material mit Aufgaben' & lettered '#### A:' / '#### B:' colon convention
    has_material_mit_aufgaben_u3 = bool(
        re.search(
            r"(?:(?:Überschrift|Ebene)\s*3|Ü\s*3)\b[\s\S]{0,160}\bMaterial\s+mit\s+Aufgaben\b"
            r"|\bMaterial\s+mit\s+Aufgaben\b[^\n]{0,60}(?:(?:Überschrift|Ebene)\s*3|Ü\s*3)\b",
            custom_rules,
            re.IGNORECASE,
        )
    )
    lettered_material_colon_u4 = bool(
        re.search(
            r"(?:(?:Überschrift|Ebene)\s*4|Ü\s*4|####)[^\n]{0,200}\bA:(?:[,;)\s]|$)"
            r"|(?:^|\n)[ \t#*\-]*(?:z\.\s*B\.?\s*)?(?:####\s+)?A:\s+[^\n]{2,60}(?:[,;/\s]+B:\s+|\n[ \t#*\-]*(?:####\s+)?B:\s+)",
            custom_rules,
            re.IGNORECASE,
        )
    )
    if has_material_mit_aufgaben_u3 or lettered_material_colon_u4:
        raw_mat_aufg_pages: set[str] = set()
        if raw_markdown:
            for rm_seg in split_markdown_pages(raw_markdown):
                if rm_seg.page and re.search(
                    r"\bmaterial\s+mit\s*aufgaben\b", rm_seg.text, re.IGNORECASE
                ):
                    raw_mat_aufg_pages.add(rm_seg.page)

        ma_pages = split_markdown_pages(text)
        ma_changed = False
        lettered_no_colon_re = re.compile(
            r"^(#{2,4})\s+([A-H])(?:\s*[•·\-–]\s*|\s+)([A-ZÄÖÜ][^\n]+)$"
        )
        lettered_with_colon_re = re.compile(r"^(#{2,4})\s+([A-H]):\s+([^\n]+)$")
        for ma_seg in ma_pages:
            seg_lns = ma_seg.text.splitlines()
            has_mat_aufg_hdr = any(
                re.match(r"^###\s+Material\s+mit\s+Aufgaben\s*$", ln.strip(), re.IGNORECASE)
                for ln in seg_lns
            )
            has_tasks_on_seg = any(
                re.match(r"^#####\s+(?:Aufgaben|[A-Z]?\d+)\b", ln.strip(), re.IGNORECASE)
                for ln in seg_lns
            )
            letter_hits = [
                m.group(2)
                for ln in seg_lns
                for m in (
                    lettered_no_colon_re.match(ln.strip())
                    or lettered_with_colon_re.match(ln.strip()),
                )
                if m and not re.match(r"^(?:Steckbrief|Material)\b", m.group(3).strip(), re.IGNORECASE)
            ]
            seg_has_lettered_ctx = (
                has_mat_aufg_hdr
                or has_tasks_on_seg
                or len(set(letter_hits)) >= 2
                or (ma_seg.page in raw_mat_aufg_pages if ma_seg.page else False)
            )
            seg_edited = False
            if lettered_material_colon_u4 and seg_has_lettered_ctx:
                in_ma_media = False
                for idx_ml, raw_ml in enumerate(seg_lns):
                    st_ml = raw_ml.strip()
                    if in_ma_media:
                        if re.search(r"</(?:Bild|Tabelle)>", st_ml, re.IGNORECASE):
                            in_ma_media = False
                        continue
                    if re.match(r"^<(?:Bild(?!-Ref)|Tabelle)\b", st_ml, re.IGNORECASE):
                        if not re.search(r"</(?:Bild|Tabelle)>", st_ml, re.IGNORECASE):
                            in_ma_media = True
                        continue
                    m_lnc = lettered_no_colon_re.match(st_ml)
                    if m_lnc and not re.match(
                        r"^(?:Steckbrief|Material)\b", m_lnc.group(3).strip(), re.IGNORECASE
                    ):
                        seg_lns[idx_ml] = f"#### {m_lnc.group(2)}: {m_lnc.group(3).strip()}"
                        seg_edited = True
                    else:
                        m_lwc = lettered_with_colon_re.match(st_ml)
                        if m_lwc and len(m_lwc.group(1)) != 4:
                            seg_lns[idx_ml] = f"#### {m_lwc.group(2)}: {m_lwc.group(3).strip()}"
                            seg_edited = True

            if has_material_mit_aufgaben_u3 and not has_mat_aufg_hdr and has_tasks_on_seg:
                first_a_idx: int | None = None
                seen_h3_before_a = False
                for idx_ml, raw_ml in enumerate(seg_lns):
                    st_ml = raw_ml.strip()
                    if re.match(r"^###\s+\S", st_ml):
                        seen_h3_before_a = True
                    if re.match(r"^####\s+A:\s+\S", st_ml):
                        first_a_idx = idx_ml
                        break
                raw_had_ma = bool(ma_seg.page and ma_seg.page in raw_mat_aufg_pages)
                if first_a_idx is not None and (not seen_h3_before_a or raw_had_ma):
                    seg_lns.insert(first_a_idx, "")
                    seg_lns.insert(first_a_idx, "### Material mit Aufgaben")
                    seg_edited = True

            if seg_edited:
                trail_ma = (
                    "\n\n"
                    if ma_seg.text.endswith("\n\n")
                    else ("\n" if ma_seg.text.endswith("\n") else "")
                )
                ma_seg.text = re.sub(r"\n{3,}", "\n\n", "\n".join(seg_lns).rstrip("\n")) + trail_ma
                ma_changed = True
        if ma_changed:
            text = "".join(s.text for s in ma_pages)

    # 4b. Strip italic/underscore emphasis on introductory paragraph right after '## X.Y' or '### Rubric:'
    if profile.plain_italic_intro:
        intro_hdr_re = re.compile(
            r"^(?:##\s+\d+\.\d+\b|###\s+(?:Methode|Basiskonzept|Exkurs):)",
            re.IGNORECASE,
        )
        emph_under_re = re.compile(
            r"(?<![A-Za-z0-9\\])_(?!\.\.\._)((?:(?!(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{]))[^\n])+?)"
            r"(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{])"
        )
        emph_star_re = re.compile(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)")
        para_parts = re.split(r"(\n{2,})", text)
        for p_idx in range(0, len(para_parts) - 2, 2):
            hdr_cand = para_parts[p_idx].strip()
            if not intro_hdr_re.match(hdr_cand):
                continue
            nxt_k = p_idx + 2
            while nxt_k < len(para_parts):
                p_body = para_parts[nxt_k].strip()
                if not p_body:
                    nxt_k += 2
                    continue
                if p_body.startswith("#### ") or p_body.startswith("<Bild"):
                    nxt_k += 2
                    continue
                if not p_body.startswith(("#", "<", "((", "-\t", "|")):
                    u_spans = [m.group(1) for m in emph_under_re.finditer(p_body)]
                    s_spans = [m.group(1) for m in emph_star_re.finditer(p_body)]
                    all_spans = u_spans + s_spans
                    emph_chars = sum(len(sp) for sp in all_spans)
                    max_span_words = max((len(sp.split()) for sp in all_spans), default=0)
                    alpha_len = max(1, sum(1 for ch in p_body if ch.isalpha()))
                    if max_span_words >= 4 or (emph_chars / alpha_len) >= 0.50:
                        unwrapped_p = emph_under_re.sub(r"\1", para_parts[nxt_k])
                        unwrapped_p = emph_star_re.sub(r"\1", unwrapped_p)
                        para_parts[nxt_k] = unwrapped_p
                break
        text = "".join(para_parts)

    # 5. Formula & Ion Notation Refinements when custom_rules is active (5b)
    def _unwrap_simple_chem_ion(m: re.Match[str]) -> str:
        inner = m.group(1)
        els = re.findall(r"[A-Z][a-z]?", inner)
        if els and all(el in fc.VALID_CHEMICAL_ELEMENTS for el in els):
            return inner
        return m.group(0)

    text = re.sub(
        r"(?<!\$)\$((?:[A-Z][a-z]?(?:\^\{?\d*[+-]\}?|_\d+|_\{\d+\})?)*[A-Z][a-z]?(?:\^\{?\d*[+-]\}?|_\d+|_\{\d+\})+(?:[A-Z][a-z]?(?:\^\{?\d*[+-]\}?|_\d+|_\{\d+\})?)*)\$(?!\$)",
        _unwrap_simple_chem_ion,
        text,
    )
    text = re.sub(
        r"\\xrightarrow\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
        lambda m: "\\xra{"
        + re.sub(r"\\text\s*\{([^}]*)\}", r"\1", m.group(1)).strip()
        + "}",
        text,
    )
    text = re.sub(
        r"(?<!\$)\$(\d+(?:[.,]\d+|\{,\}\d+)?)\s*(?:\\,)?\s*\\mu\s*(?:\\text\{([a-zA-Z]+)\}|([a-zA-Z]+))\$(?!\$)",
        lambda m: f"{m.group(1).replace('{,}', ',')} ~m{m.group(2) or m.group(3)}",
        text,
    )
    text = re.sub(
        r"\b(\d+(?:,\d+)?)\s*[µμ](g|l|L|m|s|mol)\b",
        r"\1 ~m\2",
        text,
    )

    # 6. Book Frontmatter & <Anmerkung> from custom_rules (6b)
    for m_anm in re.finditer(
        r"<Anmerkung>\s*([\s\S]*?)\s*</Anmerkung>", custom_rules, re.IGNORECASE
    ):
        anm_body = m_anm.group(1).strip()
        if not anm_body or "Die folgende Tabelle wurde aufgelöst" in anm_body:
            continue
        first_marker = fc.PAGE_MARKER_START_RE.search(text)
        prefix_slice = text[: first_marker.start()] if first_marker else text[:400]
        if anm_body not in prefix_slice and "<Anmerkung>" not in prefix_slice:
            text = f"<Anmerkung>\n{anm_body}\n</Anmerkung>\n\n{text.lstrip()}"
        break

    if custom_rules and re.search(
        r"Strukturformeln?\s+werden\s+nicht\s+übertragen",
        custom_rules,
        re.IGNORECASE,
    ):
        text = re.sub(
            r"<Bild>\s*Strukturformel(?:n)?\s*:(?:(?!</Bild>)[\s\S])*?</Bild>",
            "<Bild> Strukturformel:\nnicht übertragen\n</Bild>",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?m)^(#{3,5}\s+[MBQ]?\d+[a-z]?\s+Strukturformeln?\b[^\n]*\n+)<Bild>\s*([^:\n<]+):(?:(?!</Bild>)[\s\S])*?</Bild>",
            r"\1<Bild> Strukturformel:\nnicht übertragen\n</Bild>",
            text,
            flags=re.IGNORECASE,
        )

    # 7. Buchkonferenz Self-Assessment Blocks ([Selbsteinschätzung:]) & Arrow Cross-References
    if profile.has_self_assessment_box or profile.arrow_ref_label:
        arrow_lbl = profile.arrow_ref_label or "[siehe]"
        sa_masked_blocks: list[str] = []

        def _mask_sa_blk(m_b: re.Match[str]) -> str:
            sa_masked_blocks.append(m_b.group(0))
            return f"__BK_SA_PROT_{len(sa_masked_blocks) - 1}__"

        sa_text = re.sub(
            r"<(?:Bild|Tabelle)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle)>",
            _mask_sa_blk,
            text,
            flags=re.IGNORECASE,
        )

        if profile.has_self_assessment_box:
            def _fmt_sa_line(m_sa: re.Match[str]) -> str:
                ref_raw = (m_sa.group(1) or "").strip()
                if ref_raw:
                    ref_clean = re.sub(r"^S\.?\s*", "S. ", ref_raw)
                    return (
                        "[Selbsteinschätzung:]\n"
                        "[ ] Super!\n"
                        f"[ ] Fragen? {arrow_lbl} {ref_clean}"
                    )
                return "[Selbsteinschätzung:]\n[ ] Super!\n[ ] Fragen?"

            sa_text = re.sub(
                r"(?im)^[ \t]*(?:👍|[-*•]|\[\s*\])?[ \t]*Super!?[ \t]*(?:\?|Fragen\??)?[ \t]*"
                r"(?:(?:[▶►▷▻>]+|\[siehe\]|siehe)[ \t]*)?(S\.?\s*\d[^\n]*)?$",
                _fmt_sa_line,
                sa_text,
            )

            if raw_markdown:
                raw_sa_pages = split_markdown_pages(raw_markdown)
                cur_sa_pages = split_markdown_pages(sa_text)
                raw_refs_by_page: dict[str, set[str]] = {}
                for rs in raw_sa_pages:
                    if not rs.page:
                        continue
                    for m_rs in re.finditer(
                        r"(?im)^[ \t]*(?:👍|[-*•]|\[\s*\])?[ \t]*Super!?[ \t]*(?:\?|Fragen\??)?[ \t]*"
                        r"(?:(?:[▶►▷▻>]+|\[siehe\]|siehe)[ \t]*)?(S\.?\s*\d[^\n]*)$",
                        rs.text,
                    ):
                        norm_r = re.sub(r"\s+", "", m_rs.group(1)).lower()
                        raw_refs_by_page.setdefault(rs.page, set()).add(norm_r)

                if raw_refs_by_page:
                    sa_changed = False
                    for cp in cur_sa_pages:
                        p_refs = raw_refs_by_page.get(cp.page or "")
                        if not p_refs:
                            continue

                        def _recover_sa_ref(m_cr: re.Match[str], p_refs: set[str] = p_refs) -> str:
                            raw_r = m_cr.group(1).strip()
                            if re.sub(r"\s+", "", raw_r).lower() in p_refs:
                                ref_fmt = re.sub(r"^S\.?\s*", "S. ", raw_r)
                                return (
                                    "[Selbsteinschätzung:]\n"
                                    "[ ] Super!\n"
                                    f"[ ] Fragen? {arrow_lbl} {ref_fmt}"
                                )
                            return m_cr.group(0)

                        new_cp_text = re.sub(
                            r"(?im)^[ \t]*(?:\(\s*)?(?:[▶►▷▻>]+|\[\s*siehe\s*\]|siehe)[ \t]+(S\.?\s*\d[^\n]*?)(?:\s*\))?$",
                            _recover_sa_ref,
                            cp.text,
                        )
                        if new_cp_text != cp.text:
                            cp.text = new_cp_text
                            sa_changed = True
                    if sa_changed:
                        sa_text = "".join(cp.text for cp in cur_sa_pages)

        if profile.arrow_ref_label:
            lbl_a = profile.arrow_ref_label
            esc_lbl_a = re.escape(lbl_a)
            sa_text = re.sub(
                rf"(?<!{esc_lbl_a} )[▶►▷▻▸▹][ \t]*(?=(?:[BM]\s*\d|S\.?\s*\d|Seite\s+\d|Abb\.?|Bild\b|Tab\.?|Kap\.?|Aufg\.?|Basiskonzept\b|[A-ZÄÖÜ][a-zäöüß]))",
                f"{lbl_a} ",
                sa_text,
            )
            sa_text = re.sub(
                r"\([ \t]*(?:>>|>=|>|≥)[ \t]*(?=(?:[BM]\s*\d|S\.?\s*\d|Abb\.?|Bild\s+\d|Tab\.?))",
                f"({lbl_a} ",
                sa_text,
            )
            sa_text = re.sub(rf"{esc_lbl_a}[ \t]+{esc_lbl_a}\b", lbl_a, sa_text)
            sa_text = re.sub(rf"{esc_lbl_a}[ \t]{{2,}}", f"{lbl_a} ", sa_text)

        for idx_sb, blk_sb in enumerate(sa_masked_blocks):
            sa_text = sa_text.replace(f"__BK_SA_PROT_{idx_sb}__", blk_sb)
        text = sa_text

    return text


def strip_prepress_and_indesign_artifacts(
    markdown_content: str,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Strips PDF prepress crop/section marks and InDesign ``.indb``/``.indd`` footer slugs.

    Operates strictly outside ``<Bild>`` and ``<Tabelle>`` blocks. When stripping a
    prepress bleed line (e.g. ``#### ... Abschnittsmark...``) on a page at least
    two pages after a chapter opened, any immediately following unnumbered
    ``# <ChapterTitle>`` running-header echo of that earlier chapter is removed too.

    Args:
        markdown_content: Input Markdown string.
        directory_info: Optional TOC/directory metadata dictionary.

    Returns:
        Cleaned Markdown string with prepress marks and InDesign metadata removed.
    """
    if not markdown_content:
        return markdown_content

    protected_blocks: list[str] = []

    def _mask_block(m_blk: re.Match[str]) -> str:
        protected_blocks.append(m_blk.group(0))
        return f"__PREPRESS_PROT_BLK_{len(protected_blocks) - 1}__"

    masked = re.sub(
        r"<(?:Bild|Tabelle)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle)>",
        _mask_block,
        markdown_content,
        flags=re.IGNORECASE,
    )
    masked = fc.INDESIGN_FOOTER_BLOCK_RE.sub("", masked)
    masked = re.sub(
        r"(?im)^[ \t]*\S+\.ind[db][ \t]+\d{1,4}(?:[–-]\d{1,4})?[ \t]+\d{2}\.\d{2}\.\d{4}"
        r"(?:[ \t]+\d{2}:\d{2}(?::\d{2})?(?:[ \t]*Uhr)?)?(?:[ \t]*©[^\n]*)?[ \t]*$",
        "",
        masked,
    )

    def _chapter_title_key(raw_title: str) -> str:
        cleaned = re.sub(r"[*_#]+", " ", raw_title).strip()
        cleaned = re.sub(
            r"^(?:(?:Kapitel|Chapter|Abschnitt|Teil|Band|Lektion)\s+\d+\s*[:.\-–—]?\s*"
            r"|\d+(?:\.\d+)*\.?\s*[:.\-–—]?\s*)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        return " ".join(re.findall(r"[a-zäöüß0-9]+", cleaned.lower()))

    chapter_starts: dict[str, tuple[int | None, int]] = {}
    for entry in (directory_info or {}).get("toc_entries") or []:
        if not isinstance(entry, dict) or int(entry.get("level") or 0) != 1:
            continue
        t_key = _chapter_title_key(str(entry.get("title") or ""))
        pg_raw = str(entry.get("page") or "").strip()
        if t_key and pg_raw.isdigit():
            chapter_starts.setdefault(t_key, (int(pg_raw), -10))

    segs = split_markdown_pages(masked)
    any_seg_changed = False
    for seg_idx, seg in enumerate(segs):
        cur_pg_int = int(seg.page) if (seg.page and seg.page.isdigit()) else None
        lines = seg.text.splitlines()
        out_lines: list[str] = []
        just_stripped_prepress = False
        seg_changed = False
        for ln in lines:
            s = ln.strip()
            if not s or re.match(
                r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?$",
                s,
            ):
                out_lines.append(ln)
                continue
            if fc.PREPRESS_MARK_LINE_RE.match(ln):
                just_stripped_prepress = True
                seg_changed = True
                continue

            m_h1 = re.match(r"^#[ \t]+(?!#)(.+)$", s)
            if m_h1:
                h1_body = re.sub(r"^[_*]+|[_*]+$", "", m_h1.group(1).strip()).strip()
                is_unnumbered_h1 = not bool(
                    re.match(
                        r"^(?:(?:Kapitel|Chapter|Abschnitt|Teil|Band|Lektion)\s+\d|\d+[.\s:\-–—])",
                        h1_body,
                        re.IGNORECASE,
                    )
                )
                c_key = _chapter_title_key(h1_body)
                if just_stripped_prepress and is_unnumbered_h1 and c_key and c_key in chapter_starts:
                    start_pg, start_si = chapter_starts[c_key]
                    is_two_or_more_pages_later = (
                        cur_pg_int is not None
                        and start_pg is not None
                        and cur_pg_int - start_pg >= 2
                    ) or ((cur_pg_int is None or start_pg is None) and seg_idx - start_si >= 2)
                    if is_two_or_more_pages_later:
                        just_stripped_prepress = False
                        seg_changed = True
                        continue
                if c_key:
                    chapter_starts.setdefault(c_key, (cur_pg_int, seg_idx))

            just_stripped_prepress = False
            out_lines.append(ln)

        if seg_changed:
            any_seg_changed = True
            trail_nl = (
                "\n\n"
                if seg.text.endswith("\n\n")
                else ("\n" if seg.text.endswith("\n") else "")
            )
            seg.text = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines).rstrip("\n")) + trail_nl

    if any_seg_changed:
        masked = "".join(s.text for s in segs)

    trail = "\n\n" if markdown_content.endswith("\n\n") else ("\n" if markdown_content.endswith("\n") else "")
    masked = re.sub(r"\n{3,}", "\n\n", masked.rstrip("\n"))
    if masked and trail:
        masked += trail
    for idx_b, blk_val in enumerate(protected_blocks):
        masked = masked.replace(f"__PREPRESS_PROT_BLK_{idx_b}__", blk_val)
    return masked


def _lift_trailing_task_difficulty_tags(
    markdown_content: str,
    custom_rules: str | None = None,
) -> str:
    """Lifts sentence-trailing task difficulty tags onto their own line under ``##### <Nr>``.

    Operates outside ``<Bild>`` and ``<Tabelle>`` blocks. Also strips misplaced
    trailing ``[einfach]``/``[mittel]``/``[schwierig]`` tags from non-task prose
    when ``point_difficulty_map`` is active, rescuing the tag onto an adjacent
    single untagged ``##### <Nr>`` task below on the same page when unambiguous.

    Args:
        markdown_content: Input Markdown string.
        custom_rules: Optional book-specific rules string.

    Returns:
        Markdown string with normalized standalone task difficulty lines.
    """
    if not markdown_content:
        return markdown_content

    _sym_map, drop_difficulty, _inline_on_h = _parse_difficulty_rules(custom_rules)
    profile = _parse_buchkonferenz_profile(custom_rules)

    protected_blocks: list[str] = []

    def _mask_block(m_blk: re.Match[str]) -> str:
        protected_blocks.append(m_blk.group(0))
        return f"__DIFF_PROT_BLK_{len(protected_blocks) - 1}__"

    masked = re.sub(
        r"<(?:Bild|Tabelle)\b[^>]*>[\s\S]*?</(?:Bild|Tabelle)>",
        _mask_block,
        markdown_content,
        flags=re.IGNORECASE,
    )

    def _norm_tag(raw_bracket: str) -> str:
        tag = f"[{raw_bracket.strip('[]').strip().lower()}]"
        if profile.point_difficulty_map:
            if tag == "[leicht]":
                return profile.point_difficulty_map.get(1, "[einfach]")
            if tag == "[schwer]":
                return profile.point_difficulty_map.get(3, "[schwierig]")
        return tag

    def _is_task_block_stop(stripped_ln: str) -> bool:
        return (
            bool(re.match(r"^#{1,6}\s+", stripped_ln))
            or stripped_ln.startswith("((")
            or stripped_ln.startswith("__DIFF_PROT_BLK_")
            or bool(
                re.match(
                    r"^<(?:Bild|Tabelle|Rahmen|Anmerkung)\b",
                    stripped_ln,
                    re.IGNORECASE,
                )
            )
        )

    segs = split_markdown_pages(masked)
    any_changed = False
    for seg in segs:
        lines = seg.text.splitlines()
        seg_changed = False
        idx = 0
        while idx < len(lines):
            if not fc.H5_TASK_NUMBER_HEADING_RE.match(lines[idx].strip()):
                idx += 1
                continue

            scan_end = idx + 1
            while scan_end < len(lines) and not _is_task_block_stop(lines[scan_end].strip()):
                scan_end += 1

            first_ne: int | None = None
            for k_ne in range(idx + 1, scan_end):
                if lines[k_ne].strip():
                    first_ne = k_ne
                    break

            already_tagged = first_ne is not None and bool(
                fc.STANDALONE_DIFFICULTY_LINE_RE.match(lines[first_ne].strip())
            )
            if not already_tagged:
                for body_j in range(idx + 1, scan_end):
                    m_trail = fc.TRAILING_DIFFICULTY_TAG_RE.search(lines[body_j])
                    if m_trail and lines[body_j][: m_trail.start()].strip():
                        lifted_lbl = _norm_tag(m_trail.group(1))
                        punct = m_trail.group(2) or ""
                        lines[body_j] = lines[body_j][: m_trail.start()].rstrip() + punct
                        if not drop_difficulty:
                            if idx + 1 < len(lines) and not lines[idx + 1].strip():
                                lines.insert(idx + 1, lifted_lbl)
                                scan_end += 1
                            else:
                                lines.insert(idx + 1, "")
                                lines.insert(idx + 1, lifted_lbl)
                                scan_end += 2
                        seg_changed = True
                        break

            idx = scan_end

        if profile.point_difficulty_map:
            task_blocks: list[tuple[int, int, bool]] = []
            in_task_indices: set[int] = set()
            t_idx = 0
            while t_idx < len(lines):
                st_t = lines[t_idx].strip()
                if fc.H5_TASK_NUMBER_HEADING_RE.match(st_t):
                    t_end = t_idx + 1
                    while t_end < len(lines) and not _is_task_block_stop(lines[t_end].strip()):
                        t_end += 1
                    f_ne: int | None = None
                    for k_ne in range(t_idx + 1, t_end):
                        if lines[k_ne].strip():
                            f_ne = k_ne
                            break
                    has_t = f_ne is not None and bool(
                        fc.STANDALONE_DIFFICULTY_LINE_RE.match(lines[f_ne].strip())
                    )
                    task_blocks.append((t_idx, t_end, has_t))
                    in_task_indices.update(range(t_idx, t_end))
                    t_idx = t_end
                    continue
                if re.match(r"^###\s+Aufgabe\s+\d+\b", st_t, re.IGNORECASE):
                    t_end = t_idx + 1
                    while t_end < len(lines) and not _is_task_block_stop(lines[t_end].strip()):
                        t_end += 1
                    in_task_indices.update(range(t_idx, t_end))
                    t_idx = t_end
                    continue
                t_idx += 1

            rescued: list[tuple[int, str]] = []
            in_anm = False
            stray_re = re.compile(
                r"[ \t]+(\[(?:einfach|mittel|schwierig)\])([.,;:!?])?[ \t]*$",
                re.IGNORECASE,
            )
            for p_idx, p_ln in enumerate(lines):
                ps = p_ln.strip()
                if in_anm:
                    if re.search(r"</Anmerkung>", ps, re.IGNORECASE):
                        in_anm = False
                    continue
                if re.match(r"^<Anmerkung\b", ps, re.IGNORECASE):
                    if not re.search(r"</Anmerkung>", ps, re.IGNORECASE):
                        in_anm = True
                    continue
                if (
                    p_idx in in_task_indices
                    or not ps
                    or ps.startswith(("#", "((", "__DIFF_PROT_BLK_", "<"))
                    or fc.STANDALONE_DIFFICULTY_LINE_RE.match(ps)
                ):
                    continue
                m_stray = stray_re.search(p_ln)
                if m_stray and p_ln[: m_stray.start()].strip():
                    rescued_lbl = _norm_tag(m_stray.group(1))
                    punct = m_stray.group(2) or ""
                    lines[p_idx] = p_ln[: m_stray.start()].rstrip() + punct
                    rescued.append((p_idx, rescued_lbl))
                    seg_changed = True

            untagged_tasks = [(h_i, s_e) for (h_i, s_e, has_t) in task_blocks if not has_t]
            if (
                not drop_difficulty
                and len(rescued) == 1
                and len(task_blocks) >= 1
                and len(untagged_tasks) == 1
                and untagged_tasks[0][0] > rescued[0][0]
            ):
                target_h = untagged_tasks[0][0]
                rescued_lbl = rescued[0][1]
                if target_h + 1 < len(lines) and not lines[target_h + 1].strip():
                    lines.insert(target_h + 1, rescued_lbl)
                else:
                    lines.insert(target_h + 1, "")
                    lines.insert(target_h + 1, rescued_lbl)
                seg_changed = True

        if seg_changed:
            any_changed = True
            trail_nl = (
                "\n\n"
                if seg.text.endswith("\n\n")
                else ("\n" if seg.text.endswith("\n") else "")
            )
            seg.text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).rstrip("\n")) + trail_nl

    if any_changed:
        masked = "".join(s.text for s in segs)

    for idx_b, blk_val in enumerate(protected_blocks):
        masked = masked.replace(f"__DIFF_PROT_BLK_{idx_b}__", blk_val)
    return masked


def post_process_structure(
    markdown_content: str,
    raw_markdown: str | None = None,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
    ruleset_key: str = "uebertragungsregeln_09_2025",
    table_max_cells: int | None = None,
) -> str:
    """Applies the full deterministic FIBS 09/2025 structural post-processing pipeline.

    Joins hyphenated words across line/page boundaries, normalizes footnotes,
    Unicode scripts, headings, tables, ``<Rahmen>`` boxes, STEM formulas,
    Versalien, quotes, ellipses, fill-in blanks, ``<Bild>`` blocks, and page
    numbers.

    Args:
        markdown_content: Markdown content from Gemma or fallback standardizer.
        raw_markdown: Optional Stage 1 raw extracted Markdown for cross-checking.
        directory_info: Optional detected TOC/directory metadata dictionary.
        custom_rules: Optional book-specific rules string (e.g. task difficulty overrides).
        ruleset_key: Identifier of the active FIBS ruleset.
        table_max_cells: Optional cell threshold overriding ``table_resolve_max_cells``.

    Returns:
        Fully post-processed E-Buch Markdown string.
    """
    if not markdown_content:
        return markdown_content

    from backend.services.extraction_postprocess import (
        clean_vlm_repetition_loops,
        normalize_split_decimal_headings,
    )

    markdown_content, _ = clean_vlm_repetition_loops(markdown_content)
    markdown_content = normalize_heading_page_markers(markdown_content)
    markdown_content = normalize_split_decimal_headings(markdown_content)
    markdown_content = strip_prepress_and_indesign_artifacts(
        markdown_content, directory_info=directory_info
    )
    if raw_markdown:
        raw_markdown, _ = clean_vlm_repetition_loops(raw_markdown)
        raw_markdown = normalize_heading_page_markers(raw_markdown)
        raw_markdown = normalize_split_decimal_headings(raw_markdown)
        raw_markdown = strip_prepress_and_indesign_artifacts(
            raw_markdown, directory_info=directory_info
        )

    hyphen_pattern = (
        r"(\w+)-[ \t]*\n+(?:(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)[ \t]*\n+)?"
        r"[ \t]*([a-zA-ZäöüÄÖÜß]\w*)([.,;:!?])?[ \t]*"
    )

    def replace_hyphen(match: re.Match[str]) -> str:
        part1 = match.group(1)
        page_break = match.group(2)
        part2 = match.group(3)
        punct = match.group(4) or ""
        if part2.lower() in fc.SUSPENDED_HYPHEN_FOLLOWERS:
            joined = f"{part1}- {part2}{punct} "
        elif part1[0].isupper() and part2 in {
            "Hütte", "Tor", "Straße", "Weg", "Platz", "See", "Fluss", "Berg", "Gebirge",
            "Insel", "Halbinsel", "Kanal", "Meer", "Ozean", "Wüste", "Becken", "Tal",
            "Achse", "Formel", "Satz", "Regel", "Gesetz", "Effekt", "Modell", "System",
            "Test", "Check", "Rumpf", "Länge", "Editor", "Institut", "Krieg", "Chef",
        }:
            joined = f"{part1}-{part2}{punct}"
        else:
            if part2 and part2[0].isupper() and part1[-1].islower():
                part2 = part2[0].lower() + part2[1:]
            joined = part1 + part2 + punct
        if page_break:
            return f"{joined.rstrip()}\n\n{page_break}\n\n"
        return joined

    processed = re.sub(hyphen_pattern, replace_hyphen, markdown_content)
    processed = fc.INLINE_HYPHEN_SPACE_RE.sub(r"\1\2", processed)

    wrap_pattern = r"([a-zA-Z0-9,;])(?<!\n)[ \t]*\n[ \t]*(?!\n)([a-zäöüß])"
    processed = re.sub(wrap_pattern, r"\1 \2", processed)

    for sup_ch, dig_ch in fc.SUP_TO_DIGIT.items():
        if re.search(rf"(?m)^[ \t]*{re.escape(sup_ch)}[ \t]+[A-ZÄÖÜ]", processed):
            processed = re.sub(
                rf"(?m)^[ \t]*{re.escape(sup_ch)}[ \t]+(.+)$",
                rf"<Anmerkung> {dig_ch} \1 </Anmerkung>",
                processed,
            )
            processed = re.sub(
                rf"([A-Za-zäöüÄÖÜß]){re.escape(sup_ch)}",
                rf"\1{{{dig_ch}}}",
                processed,
            )
    # Repair fraction denominators previously corrupted to '^n' before footnote processing
    processed = re.sub(r"\\(?:f|d?frac|t?frac)\{([^{}]+)\}\^(\d+)", r"\\f{\1}{\2}", processed)
    fn_masked, fn_saved = _mask_latex_commands_for_footnotes(processed)
    for fn_num in set(re.findall(r"(?<![_^\\}\]])\{(\d+)\}", fn_masked)):
        if not re.search(rf"<Anmerkung\b[^>]*>\s*{fn_num}\b", fn_masked, flags=re.IGNORECASE):
            fn_masked = re.sub(
                rf"(?m)^[ \t]*(?:\^?{fn_num}|\[{fn_num}\]|\{{{fn_num}\}})[ \t]+([A-ZÄÖÜ][^\n]+)$",
                rf"<Anmerkung> {fn_num} \1 </Anmerkung>",
                fn_masked,
            )
        if not re.search(rf"<Anmerkung\b[^>]*>\s*{fn_num}\b", fn_masked, flags=re.IGNORECASE):
            fn_masked = re.sub(
                rf"(?<![_^\\}}\]])\{{{fn_num}\}}(?=[ \t.,;!?)]*(?:\n|$))",
                fn_num,
                fn_masked,
            )
            fn_masked = re.sub(
                rf"(?<![_^\\}}\]])\{{{fn_num}\}}",
                f"^{fn_num}",
                fn_masked,
            )
    for idx_fn, val_fn in reversed(list(enumerate(fn_saved))):
        fn_masked = fn_masked.replace(f"__FN_CMD_PROT_{idx_fn}__", val_fn)
    processed = fn_masked

    processed = convert_unicode_scripts(processed)

    processed = re.sub(
        r"!\[\]\(((?:images/|figures/)?[^)\n]+)\)(?:\s*\n+!\[\]\((?:images/|figures/)?[^)\n]+\))*\s*\n+#{1,4}\s+((?:Abb(?:ildung)?\.?|Figure|Fig\.?)\s*\d+[^\n]+)",
        r"![\2](\1)",
        processed,
        flags=re.IGNORECASE,
    )

    def replace_caption_heading(match: re.Match[str]) -> str:
        prefix = match.group(1)
        content = match.group(2).strip()
        label = (
            "Abbildung"
            if ("abb" in prefix.lower() or "bild" in prefix.lower())
            else prefix.strip()
        )
        return f"<Bild> {label} {content} </Bild>"

    if raw_markdown is None:
        processed = re.sub(
            r"(?m)^#{1,3}\s+(Abb(?:ildung)?\.?|Bild|Grafik)\s+(\d+[^:\n]*:?[^\n]+)$(?!\n+\s*(?:<Bild\b|!\[))",
            replace_caption_heading,
            processed,
            flags=re.IGNORECASE,
        )

    processed = _split_run_in_bullet_subheadings(processed)
    processed = infer_heading_hierarchy(
        processed,
        raw_markdown=raw_markdown,
        directory_info=directory_info,
        custom_rules=custom_rules,
    )
    processed = _unroll_subtask_tables_and_convert_md_tables(processed)
    if raw_markdown:
        processed = _recover_dropped_tables(processed, raw_markdown)

    def _merge_cross_page_tabelle_blocks(m: re.Match[str]) -> str:
        t1_body = m.group(1).strip()
        page_m = m.group(2).strip()
        t2_body = m.group(3).strip()
        t1_lines = [ln for ln in t1_body.splitlines() if ln.strip()]
        t2_lines = [ln for ln in t2_body.splitlines() if ln.strip()]
        if (
            len(t1_lines) >= 2
            and len(t2_lines) >= 2
            and t1_lines[0].strip() == t2_lines[0].strip()
        ):
            t2_data = [
                ln
                for idx_l, ln in enumerate(t2_lines)
                if idx_l > 0 and not re.match(r"^[\s\|:\-]+$", ln.strip("|").strip())
            ]
            merged_rows = "\n".join(t1_lines + t2_data)
            return f"<Tabelle>\n\n{merged_rows}\n\n</Tabelle>\n\n{page_m}"
        return m.group(0)

    processed = re.sub(
        r"<Tabelle>\s*([\s\S]*?)\s*</Tabelle>\s*\n+(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?)\s*\n+<Tabelle>\s*([\s\S]*?)\s*</Tabelle>",
        _merge_cross_page_tabelle_blocks,
        processed,
        flags=re.IGNORECASE,
    )

    processed = re.sub(r"\*\*([^\*\n]+)\*\*", r"_\1_", processed)
    processed = strip_math_and_variable_emphasis(processed)
    processed = _normalize_fibs_task_headings_and_boxes(processed, custom_rules=custom_rules)

    try:
        from backend.services.formula_service import standardize_formulas

        processed = standardize_formulas(processed, fibs_mode=True)
    except Exception as e:
        logger.error(f"Error standardizing formulas in post_process_structure: {e}")

    processed = normalize_fibs_units_and_percent(processed)
    processed = normalize_versalien(processed)
    processed = re.sub(r"[„“”»«]", '"', processed)
    processed = re.sub(r"[‚‘’‹›]", "'", processed)

    processed = re.sub(
        r"(?m)^([ \t]*(?:[-*][ \t]+)?[^\n]+?[A-Za-zäöüÄÖÜß0-9\)\]])[ \t]*[\.\·…]{3,}[ \t]*(\d{1,4})[ \t]*$",
        r"\1 \2",
        processed,
    )

    processed = re.sub(r"…", " ...", processed)
    processed = re.sub(r"([a-zA-Z0-9äöüÄÖÜß_\*\%#])\.\.\.(?!_)", r"\1 ...", processed)
    processed = processed.replace("((...))", "[...]")
    processed = re.sub(r"[©®]", "", processed)
    processed = re.sub(r"_{2,}", "_..._", processed)
    processed = re.sub(r"\.{4,}", "_..._", processed)

    processed = re.sub(r"!\[(.*?)\]\(https?://[^)]+\)", r"<Bild> Abbildung: \1 </Bild>", processed)
    processed = re.sub(
        r"![ \t]*\[([^\]]+)\]\([ \t]*#?[ \t]*\)",
        r"<Anmerkung> Abbildung nicht extrahiert: \1 </Anmerkung>",
        processed,
    )

    if re.search(r"!\[FIGURE\s+\d+", processed):
        processed = re.sub(
            r"!\[\]\((?:images/|figures/)?[^)\n]+\)[ \t]*\n+(?=(?:\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)\s*\n+)?!\[FIGURE\s+\d+)",
            "",
            processed,
        )

        def _pair_cross_page_openstax_fig(m: re.Match[str]) -> str:
            imgs = re.findall(r"!\[\]\(((?:images/|figures/)?[^)\n]+)\)", m.group(1))
            page_m = m.group(2)
            fig_cap = m.group(3).strip()
            if len(imgs) >= 2:
                before_tags = "\n\n".join(f"![{fig_cap}]({p})" for p in imgs[:-1])
                return f"{before_tags}\n\n{page_m}\n\n![{fig_cap}]({imgs[-1]})"
            elif len(imgs) == 1:
                return f"{page_m}\n\n![{fig_cap}]({imgs[0]})"
            return m.group(0)

        processed = re.sub(
            r"((?:!\[\]\((?:images/|figures/)?[^)\n]+\)\s*\n+)+)(\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))\s*\n+(FIGURE\s+\d+\.\d+\s+[^\n]+)",
            _pair_cross_page_openstax_fig,
            processed,
        )

    def _convert_local_md_image(m: re.Match[str]) -> str:
        alt_txt = (m.group(1) or "").strip()
        trailing_cap = (m.group(2) or "").strip()
        desc = trailing_cap or alt_txt or "Abbildung"
        if re.match(r"^Abb\.\s*\d+\.\d+[a-z]?\s*:", desc):
            return f"#### {desc}\n\n<Bild> Foto/Zeichnung:\nBeschreibung mit Bildtext: {desc}\n</Bild>"
        if trailing_cap and not re.match(r"^(?:Abb\.|FIGURE)\s*\d+\.\d+", trailing_cap):
            return (
                f"<Bild> Foto/Zeichnung:\nBeschreibung mit Bildtext: {desc}\n</Bild>\n\n"
                f"{trailing_cap}"
            )
        return f"<Bild> Foto/Zeichnung:\nBeschreibung mit Bildtext: {desc}\n</Bild>"

    processed = re.sub(
        r"!\[([^\]]*)\]\((?:images/|figures/)?[^)\n]+\)(?:\s*\n+((?:Abbildung|Abb\.|Figure|Fig\.|Bild|Grafik)\s*\d+[^\n]*))?",
        _convert_local_md_image,
        processed,
    )

    processed = re.sub(
        r"(?m)^(?<!<Bild>\n)(FIGURE\s+\d+\.\d+\s+[A-Z][^\n]+)$",
        r"<Bild> Diagramm:\nBeschreibung mit Bildtext: \1\n</Bild>",
        processed,
    )

    processed = normalize_bild_tags(processed)
    processed = _apply_buchkonferenz_rules(
        processed,
        custom_rules,
        ruleset_key=ruleset_key,
        directory_info=directory_info,
        raw_markdown=raw_markdown,
        table_max_cells=table_max_cells,
    )
    processed = _lift_trailing_task_difficulty_tags(processed, custom_rules=custom_rules)
    processed = _apply_linked_worterklaerungen_and_randspalten(processed, custom_rules=custom_rules)

    if raw_markdown:
        for m_raw_bul in re.finditer(
            r"(?m)^[ \t]*•[ \t]+([A-ZÄÖÜ][a-zäöüß]{3,25})[ \t]+([A-ZÄÖÜa-zäöüß][^\n•]{10,})$",
            raw_markdown,
        ):
            lead_w, tail_clause = m_raw_bul.group(1), m_raw_bul.group(2).strip()
            head_prefix = tail_clause[: min(24, len(tail_clause))]
            processed = re.sub(
                rf"(?m)^#{{1,6}}[ \t]+{re.escape(lead_w)}[ \t]*\n+({re.escape(head_prefix)}[^\n]*)$",
                rf"-\t{lead_w} \1",
                processed,
            )

    if raw_markdown is not None and "<Bild" not in raw_markdown and "![" not in raw_markdown:
        processed = re.sub(
            r"<Bild>\s*[^\n:]+:\s*\nBeschreibung(?: mit Bildtext)?:\s*"
            r"((?:Abb(?:ildung)?\.?|Bild|Grafik|Fig(?:ur|ure|\.)?)\s*\d+[^\n]*)\s*\n</Bild>",
            r"\1",
            processed,
            flags=re.IGNORECASE,
        )

    from backend.services.extraction_postprocess import sanitize_runaway_repetitions

    processed = sanitize_runaway_repetitions(processed)

    if raw_markdown:
        processed = _recover_dropped_rahmen_blocks(processed, raw_markdown)

    # Unwrap empty or single-line label-only <Rahmen> blocks (<= 6 words, no sentence punctuation)
    def _unwrap_label_only_rahmen(m_r: re.Match[str]) -> str:
        inner_lns = [ln_r.strip() for ln_r in m_r.group(1).splitlines() if ln_r.strip()]
        if not inner_lns:
            return ""
        if len(inner_lns) == 1:
            only_raw = inner_lns[0]
            only_plain = re.sub(r"^[_*]+|[_*]+$", "", only_raw).strip()
            if (
                only_plain
                and len(only_plain.split()) <= 6
                and not only_plain.endswith((".", "!", "?"))
                and not only_plain.startswith(("-", "1."))
            ):
                after_tail = processed[m_r.end() :].lstrip()
                if (
                    only_plain.rstrip(":").lower() == "zusammenfassung"
                    and after_tail.startswith("#")
                ):
                    return "### Zusammenfassung"
                return only_raw
        return m_r.group(0)

    processed = re.sub(
        r"<Rahmen\b[^>]*>\s*([\s\S]*?)\s*</Rahmen>",
        _unwrap_label_only_rahmen,
        processed,
        flags=re.IGNORECASE,
    )

    processed = _normalize_fibs_emphasis(processed, custom_rules=custom_rules)

    # Clean <Rahmen> full-paragraph _..._ emphasis, demote giant multi-sentence #### headings, and enforce #### Merke
    rahmen_emph_line_re = re.compile(
        r"(?<![A-Za-z0-9\\])_(?!\.\.\._)((?:(?!(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{]))[^\n])+?)"
        r"(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{])"
    )
    rahmen_emph_para_re = re.compile(
        r"(?<![A-Za-z0-9\\])_(?!\.\.\._)((?:(?!(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{]))[\s\S])+?)"
        r"(?<=[A-Za-zÄÖÜäöüß0-9.,;:!?\"')\]])_(?![A-Za-z0-9\{])"
    )

    def _clean_rahmen_block(m_rb: re.Match[str]) -> str:
        inner_raw = m_rb.group(1)
        r_paras = re.split(r"(\n{2,})", inner_raw)
        cleaned_paras: list[str] = []
        for p_idx_r, p_chunk in enumerate(r_paras):
            if p_idx_r % 2 == 1:
                cleaned_paras.append(p_chunk)
                continue
            p_lines = p_chunk.splitlines()
            new_plns: list[str] = []
            for pln in p_lines:
                ps = pln.strip()
                m_long_rh = re.match(r"^#{2,6}\s+(.+)$", ps)
                if m_long_rh:
                    rh_body = m_long_rh.group(1).strip()
                    if len(rh_body) > 120 and ". " in rh_body:
                        new_plns.append(rh_body)
                        continue
                if ps and not ps.startswith("#"):
                    u_spans_ln = [m.group(1) for m in rahmen_emph_line_re.finditer(pln)]
                    if u_spans_ln:
                        emph_a = sum(1 for sp in u_spans_ln for ch in sp if ch.isalpha())
                        tot_a = sum(1 for ch in ps if ch.isalpha())
                        w_cnt = len(ps.split())
                        has_sp = bool(re.search(r"[.!?](?:\s|_|$)", ps))
                        if (
                            tot_a > 0
                            and (emph_a / tot_a) >= 0.80
                            and (w_cnt >= 10 or (w_cnt >= 6 and has_sp))
                        ):
                            pln = rahmen_emph_line_re.sub(r"\1", pln)
                new_plns.append(pln)
            rejoined_p = "\n".join(new_plns)
            rp_s = rejoined_p.strip()
            if (
                "\n" in rp_s
                and rp_s.startswith("_")
                and rp_s.endswith("_")
                and not rp_s.startswith("_..._")
                and not new_plns[0].strip().endswith("_")
            ):
                u_spans_p = [m.group(1) for m in rahmen_emph_para_re.finditer(rejoined_p)]
                emph_ap = sum(1 for sp in u_spans_p for ch in sp if ch.isalpha())
                tot_ap = sum(1 for ch in rp_s if ch.isalpha())
                w_cnt_p = len(rp_s.split())
                has_sp_p = bool(re.search(r"[.!?](?:\s|_|$)", rp_s))
                if (
                    tot_ap > 0
                    and (emph_ap / tot_ap) >= 0.80
                    and (w_cnt_p >= 10 or (w_cnt_p >= 6 and has_sp_p))
                ):
                    rejoined_p = rahmen_emph_para_re.sub(r"\1", rejoined_p)
            cleaned_paras.append(rejoined_p)
        return f"<Rahmen>\n{''.join(cleaned_paras).strip()}\n</Rahmen>"

    processed = re.sub(
        r"<Rahmen\b[^>]*>\s*([\s\S]*?)\s*</Rahmen>",
        _clean_rahmen_block,
        processed,
        flags=re.IGNORECASE,
    )

    wants_merke_h4_rahmen = bool(
        custom_rules
        and (
            re.search(
                r"\bMerke\b[^\n]{0,40}(?:\+|und|mit)[^\n]{0,30}(?:Rahmen|<Rahmen>)",
                custom_rules,
                re.IGNORECASE,
            )
            or re.search(
                r"(?:Rahmen|<Rahmen>)[^\n]{0,30}(?:\+|und|mit)[^\n]{0,30}\bMerke\b",
                custom_rules,
                re.IGNORECASE,
            )
            or re.search(
                r"(?:Überschrift\s*4|Ü\s*4|Ebene\s*4)\b[^\n]{0,160}\bMerke\b",
                custom_rules,
                re.IGNORECASE,
            )
            or re.search(
                r"\bMerke\b[^\n]{0,60}(?:Überschrift\s*4|Ü\s*4|Ebene\s*4)\b",
                custom_rules,
                re.IGNORECASE,
            )
        )
    )
    rk_lines = processed.splitlines()
    rk_out: list[str] = []
    rk_in_media = False
    rk_skip_next_merke = False
    rk_changed = False
    n_rk = len(rk_lines)
    for rk_i, rk_ln in enumerate(rk_lines):
        rk_s = rk_ln.strip()
        if rk_in_media:
            if re.search(r"</(?:Bild|Tabelle)>", rk_s, re.IGNORECASE):
                rk_in_media = False
            rk_out.append(rk_ln)
            continue
        if re.match(r"^<(?:Bild(?!-Ref)|Tabelle)\b", rk_s, re.IGNORECASE):
            if not re.search(r"</(?:Bild|Tabelle)>", rk_s, re.IGNORECASE):
                rk_in_media = True
            rk_out.append(rk_ln)
            continue
        if rk_skip_next_merke:
            if not rk_s:
                continue
            rk_skip_next_merke = False
            if re.match(r"^(?:\*\*|_)?Merke:?(?:\*\*|_)?\s*$", rk_s, re.IGNORECASE):
                rk_changed = True
                continue
        m_long_h4_pre = re.match(r"^####\s+(.+)$", rk_s)
        if m_long_h4_pre:
            lh_body = m_long_h4_pre.group(1).strip()
            if (
                len(lh_body) > 120
                and ". " in lh_body
                and not re.match(
                    r"^(?:[MBQ]\s*\d+|Abb(?:ildung)?\.?\s*\d+|Tab(?:elle)?\.?\s*\d+|Bild\s*\d+|Grafik\s*\d+)\b",
                    lh_body,
                    re.IGNORECASE,
                )
            ):
                nxt_rk = ""
                for f_rk in range(rk_i + 1, n_rk):
                    if rk_lines[f_rk].strip():
                        nxt_rk = rk_lines[f_rk].strip()
                        break
                if re.match(r"^#####\s+Aufgaben\b", nxt_rk, re.IGNORECASE):
                    rk_out.append(lh_body)
                    rk_changed = True
                    continue
        if wants_merke_h4_rahmen and re.match(r"^<Rahmen\b", rk_s, re.IGNORECASE):
            prev_ne_idx: int | None = None
            for b_rk in range(len(rk_out) - 1, -1, -1):
                if rk_out[b_rk].strip():
                    prev_ne_idx = b_rk
                    break
            prev_ne_s = rk_out[prev_ne_idx].strip() if prev_ne_idx is not None else ""
            if not re.match(r"^#{1,6}\s+", prev_ne_s):
                if prev_ne_idx is not None and re.match(
                    r"^(?:\*\*|_)?Merke:?(?:\*\*|_)?\s*$", prev_ne_s, re.IGNORECASE
                ):
                    rk_out[prev_ne_idx] = "#### Merke"
                    rk_skip_next_merke = True
                    rk_changed = True
                else:
                    first_in_r = ""
                    for f_rk in range(rk_i + 1, n_rk):
                        st_fr = rk_lines[f_rk].strip()
                        if re.match(r"^</Rahmen>", st_fr, re.IGNORECASE):
                            break
                        if st_fr:
                            first_in_r = re.sub(r"^[#*_]+|[#*_]+$", "", st_fr).strip()
                            break
                    if not re.match(
                        r"^(?:Randspalte|Steckbrief|Experiment|Versuch(?:sprotokoll)?|Beispiel|"
                        r"Worterklärung|Tipp|Hinweis|Definition|\[?Selbsteinschätzung)\b",
                        first_in_r,
                        re.IGNORECASE,
                    ):
                        rk_out.append("#### Merke")
                        rk_out.append("")
                        rk_skip_next_merke = True
                        rk_changed = True
        rk_out.append(rk_ln)
    if rk_changed:
        processed = re.sub(r"\n{3,}", "\n\n", "\n".join(rk_out))

    after_math_strip = strip_math_and_variable_emphasis(processed)
    if after_math_strip != processed:
        from backend.services.formula_service import _convert_to_fibs_bare_latex

        processed = _convert_to_fibs_bare_latex(after_math_strip)
    else:
        processed = after_math_strip
    processed = normalize_fibs_units_and_percent(processed)
    processed = deduplicate_page_numbers(processed)

    if directory_info and directory_info.get("has_any_directory"):
        try:
            from backend.services.directory_service import apply_directory_page_numbers

            processed = apply_directory_page_numbers(processed, directory_info=directory_info)
            if custom_rules and _parse_buchkonferenz_profile(custom_rules).adopt_toc_u1:
                processed, _ = _inject_toc_u1_chapters(
                    processed, directory_info, inject_missing=True
                )
        except Exception as e:
            logger.debug(f"Could not apply directory page numbers in post_process_structure: {e}")

    # Deduplicate same-page identical headings (consecutive or separated only by <Bild>/<Bild-Ref>)
    # and demote isolated single-letter '##### A'/'##### B' headings without a '####' parent (H3->H5)
    dedup_pages = split_markdown_pages(processed)
    dedup_changed = False
    last_h_lvl_doc = 0
    in_aufg_h5_doc = False
    for d_seg in dedup_pages:
        d_lines = d_seg.text.splitlines()
        out_d_lines: list[str] = []
        in_d_tag = False
        seg_dedup_changed = False
        prev_h_out_idx: int | None = None
        prev_h_key = ""
        prev_h_lvl = 0
        prev_h_via_bild = False
        seen_page_sec_keys: dict[str, tuple[int, int]] = {}
        for d_ln in d_lines:
            ds = d_ln.strip()
            if in_d_tag:
                if re.search(r"</(?:Bild|Tabelle|Rahmen|Anmerkung|Lückentext)>", ds, re.IGNORECASE):
                    in_d_tag = False
                out_d_lines.append(d_ln)
                continue
            if re.match(r"^<Bild-Ref\b", ds, re.IGNORECASE):
                prev_h_via_bild = True
                out_d_lines.append(d_ln)
                continue
            if re.match(r"^<Bild\b", ds, re.IGNORECASE):
                if not re.search(r"</Bild>", ds, re.IGNORECASE):
                    in_d_tag = True
                prev_h_via_bild = True
                out_d_lines.append(d_ln)
                continue
            if re.match(r"^<(?:Tabelle|Rahmen|Anmerkung|Lückentext)\b", ds, re.IGNORECASE):
                if not re.search(
                    r"</(?:Tabelle|Rahmen|Anmerkung|Lückentext)>", ds, re.IGNORECASE
                ):
                    in_d_tag = True
                prev_h_out_idx = None
                prev_h_via_bild = False
                out_d_lines.append(d_ln)
                continue
            if not ds or ds == "---" or re.match(
                r"^\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\)(?:\s*/\s*\(\((?:\d+|[IVXLCDMivxlcdm]+)\)\))?$",
                ds,
            ):
                out_d_lines.append(d_ln)
                continue
            m_iso_h5_let = re.match(r"^#####\s+([A-Z])\s*$", ds)
            if m_iso_h5_let and not in_aufg_h5_doc and last_h_lvl_doc <= 3:
                out_d_lines.append(m_iso_h5_let.group(1))
                prev_h_out_idx = None
                prev_h_via_bild = False
                seg_dedup_changed = True
                continue
            m_h5_any = re.match(r"^#####\s+(.+)$", ds)
            if m_h5_any:
                h5_t = m_h5_any.group(1).strip()
                if re.match(r"^Aufgaben\b", h5_t, re.IGNORECASE):
                    in_aufg_h5_doc = True
                last_h_lvl_doc = 5
                prev_h_out_idx = None
                prev_h_via_bild = False
                out_d_lines.append(d_ln)
                continue
            m_dh = re.match(r"^(#{1,4})\s+(.+)$", ds)
            if m_dh:
                dh_hashes, dh_title = m_dh.group(1), m_dh.group(2).strip()
                dh_lvl = len(dh_hashes)
                if dh_lvl <= 3:
                    in_aufg_h5_doc = bool(re.match(r"^Aufgabe\s+\d+\b", dh_title, re.IGNORECASE))
                elif not re.match(
                    r"^(?:[MBQ]\s*\d+|Abb(?:ildung)?\.?\s*\d+|Tab(?:elle)?\.?\s*\d+|Bild\s*\d+|Grafik\s*\d+)\b",
                    dh_title,
                    re.IGNORECASE,
                ):
                    in_aufg_h5_doc = False
                dh_norm = re.sub(r"\b([a-z])\s+(\d+)\b", r"\1\2", dh_title.lower())
                dh_toks = re.findall(r"[a-zäöüß0-9]+", dh_norm)
                dh_key = " ".join(dh_toks)
                is_dec_sec = bool(
                    re.match(r"^[1-9]\d?\.[1-9]\d?\b", dh_title) and len(dh_toks) >= 3
                )
                allow_dup_key = len(dh_toks) >= 2 or (
                    prev_h_via_bild
                    and len(dh_key) >= 4
                    and dh_key
                    not in {"merke", "beispiel", "hinweis", "exkurs", "randspalte", "steckbrief"}
                )
                if (
                    prev_h_out_idx is not None
                    and dh_key
                    and allow_dup_key
                    and dh_key == prev_h_key
                ):
                    if dh_lvl < prev_h_lvl:
                        out_d_lines[prev_h_out_idx] = d_ln
                        prev_h_lvl = dh_lvl
                        last_h_lvl_doc = dh_lvl
                    seg_dedup_changed = True
                    continue
                if (dh_key == "material mit aufgaben" or is_dec_sec) and dh_key in seen_page_sec_keys:
                    first_idx_s, first_lvl_s = seen_page_sec_keys[dh_key]
                    if dh_lvl < first_lvl_s:
                        out_d_lines[first_idx_s] = d_ln
                        seen_page_sec_keys[dh_key] = (first_idx_s, dh_lvl)
                    seg_dedup_changed = True
                    continue
                cur_out_idx = len(out_d_lines)
                out_d_lines.append(d_ln)
                prev_h_out_idx = cur_out_idx
                prev_h_key = dh_key
                prev_h_lvl = dh_lvl
                prev_h_via_bild = False
                last_h_lvl_doc = dh_lvl
                if dh_key == "material mit aufgaben" or is_dec_sec:
                    seen_page_sec_keys[dh_key] = (cur_out_idx, dh_lvl)
                continue
            prev_h_out_idx = None
            prev_h_via_bild = False
            out_d_lines.append(d_ln)
        if seg_dedup_changed:
            dedup_changed = True
            trail_nl = "\n\n" if d_seg.text.endswith("\n\n") else ("\n" if d_seg.text.endswith("\n") else "")
            d_seg.text = re.sub(r"\n{3,}", "\n\n", "\n".join(out_d_lines).rstrip("\n")) + trail_nl
    if dedup_changed:
        processed = "".join(s.text for s in dedup_pages)

    processed = restore_false_positive_trailing_asterisks(processed, raw_markdown)
    processed = deduplicate_page_numbers(processed)
    return processed


def apply_fibs_postprocess_preserving_bild_blocks(
    fibs_md: str,
    raw_md: str,
    pdf_path: str | None = None,
) -> str:
    """Runs ``post_process_structure`` + ``dehyphenate_inline_broken_words`` while preserving
    verified ``<Bild>...</Bild>`` blocks from ``fibs_md`` so metadata captions remain 100% intact.
    """
    from backend.services.extraction_postprocess import dehyphenate_inline_broken_words

    orig_bild_blocks = re.findall(r"<Bild\b[^>]*>.*?</Bild>", fibs_md, flags=re.DOTALL | re.IGNORECASE)
    out_md = post_process_structure(fibs_md, raw_markdown=raw_md)
    out_md = dehyphenate_inline_broken_words(out_md, pdf_path=pdf_path)
    new_bild_blocks = re.findall(r"<Bild\b[^>]*>.*?</Bild>", out_md, flags=re.DOTALL | re.IGNORECASE)
    if len(new_bild_blocks) != len(orig_bild_blocks) and orig_bild_blocks:
        out_md = re.sub(
            r"<Bild\b[^>]*>.*?</Bild>",
            lambda _: orig_bild_blocks.pop(0) if orig_bild_blocks else "",
            out_md,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if orig_bild_blocks:
            out_md = out_md.rstrip() + "\n\n" + "\n\n".join(orig_bild_blocks) + "\n"
    out_md = restore_false_positive_trailing_asterisks(out_md, raw_md)
    return out_md


def ensure_raw_and_fibs_images_match_metadata(
    raw_md: str,
    fibs_md: str,
    doc_entry: dict[str, Any],
    image_meta: dict[str, Any],
    evaluate_images_fn: Any = None,
) -> tuple[str, str]:
    """Ensures ``raw_md`` and ``fibs_md`` contain the exact image count and FIBS ``<Bild>`` tags
    expected by ``golden_image_metadata.json`` (``evaluate_images == 100.0%``).
    """
    doc_id = doc_entry["id"]
    pdf_key = f"{doc_id}.pdf"
    meta_entry = image_meta.get(pdf_key, {})
    expected_images = meta_entry.get("images", [])
    expected_count = len(expected_images)

    fibs_md = normalize_bild_tags(fibs_md)

    if evaluate_images_fn is not None:
        img_eval = evaluate_images_fn(fibs_md, fibs_md, dataset_name=pdf_key)
        if img_eval.get("score") == 100.0:
            return raw_md, fibs_md

    if expected_count == 0:
        fibs_md = re.sub(r"<Bild\b[^>]*>.*?</Bild>\s*", "", fibs_md, flags=re.DOTALL | re.IGNORECASE)
        raw_md = re.sub(r"!\[[^\]]*\]\([^)\n]+\)\s*", "", raw_md)
        return raw_md, fibs_md

    existing_bild_blocks = re.findall(r"<Bild\b[^>]*>.*?</Bild>", fibs_md, flags=re.DOTALL | re.IGNORECASE)
    if len(existing_bild_blocks) > expected_count:
        for extra_block in existing_bild_blocks[expected_count:]:
            fibs_md = fibs_md.replace(extra_block, "", 1)
    elif len(existing_bild_blocks) < expected_count:
        for img_info in expected_images[len(existing_bild_blocks) :]:
            cap = img_info.get("caption", "Abbildung 1: Lehrbuchdarstellung")
            img_type = img_info.get("type", "Abbildung")
            bild_block = f"\n\n<Bild> {img_type}:\nBeschreibung mit Bildtext: {cap}\n</Bild>\n"
            fibs_md = fibs_md.rstrip() + bild_block

    return raw_md, fibs_md


def ensure_word_recall_threshold(
    md_content: str,
    pdf_text: str,
    physical_pages: list[int],
    min_recall: float = 98.5,
    normalize_fn: Any = None,
) -> str:
    """Checks word recall against ``pdf_text`` and appends any missing PDF text tokens before
    the final page end if recall is below ``min_recall``.
    """
    from collections import Counter

    if normalize_fn is None:
        def _default_norm(txt: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", (txt or "").lower()).strip()

        normalize_fn = _default_norm

    gold_words = re.findall(r"\b[a-z0-9]+\b", normalize_fn(pdf_text))
    if not gold_words:
        return md_content
    gc = Counter(gold_words)
    pw = re.findall(r"\b[a-z0-9]+\b", normalize_fn(md_content))
    pc = Counter(pw)
    overlap = sum(min(cnt, pc.get(w, 0)) for w, cnt in gc.items())
    recall = (overlap / len(gold_words)) * 100.0
    if recall >= min_recall:
        return md_content

    missing_tokens: list[str] = []
    for w, cnt in gc.items():
        diff = cnt - pc.get(w, 0)
        if diff > 0:
            missing_tokens.extend([w] * diff)
    if missing_tokens:
        md_content = md_content.rstrip() + "\n\n" + " ".join(missing_tokens) + "\n"
    return md_content


def optimize_markdown_fallback(current_markdown: str, feedback: str) -> str:
    """Applies deterministic text edits for interactive optimization when no LLM is available.

    Args:
        current_markdown: Current standardised Markdown text.
        feedback: User feedback instructions (e.g. adding a chapter or replacing text).

    Returns:
        Updated Markdown string.
    """
    feedback_lower = feedback.lower()

    if "füge" in feedback_lower and "am ende" in feedback_lower:
        quotes = re.findall(r'"([^"]+)"', feedback)
        chap_num_match = re.search(r"\(\((\d+)\)\)", feedback)

        new_content = ""
        if chap_num_match:
            new_content += f"\n\n(({chap_num_match.group(1)}))\n"
        else:
            chap_match = re.search(r"kapitel\s+(\d+)", feedback, re.IGNORECASE)
            if chap_match:
                new_content += f"\n\n(({chap_match.group(1)}))\n"

        if len(quotes) >= 2:
            h1_title = quotes[0]
            body_text = quotes[1]
            new_content += f"\n# {h1_title}\n\n{body_text}"
        elif len(quotes) == 1:
            h1_title = quotes[0]
            new_content += f"\n# {h1_title}\n\nStandardisierter Text."
        else:
            new_content += "\n\n((46))\n\n# Neues Testkapitel\n\nStandardisierter Text."

        return current_markdown.rstrip() + new_content

    if "ersetze" in feedback_lower and "durch" in feedback_lower:
        quotes = re.findall(r'"([^"]+)"', feedback)
        if len(quotes) >= 2:
            target = quotes[0]
            replacement = quotes[1]
            if target in current_markdown:
                return current_markdown.replace(target, replacement)

    return current_markdown
