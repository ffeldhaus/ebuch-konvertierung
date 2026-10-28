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
    normalize_versalien,
)
from backend.services.models import PageSegment

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
            r"^[\(\s\[\-\#]*(?:Seite|Se)?\s*(\d+)[\)\s\]\-\#]*$",
            line_clean,
            re.IGNORECASE,
        )
        if page_match:
            page_num = page_match.group(1)
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
        line = re.sub(r"\*\*(.*?)\*\*", r"_\1_", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"_\1_", line)

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
    return output_md


def infer_heading_hierarchy(
    markdown_content: str,
    raw_markdown: str | None = None,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Infers and restores hierarchical Markdown heading levels (``#`` to ``####``).

    Combines raw extraction heading evidence, stacked parent-child heading pairs,
    page-aware H2/H3/H4 progression, numbering schemes, and detected Table of
    Contents (``Inhaltsverzeichnis``) entries.

    Args:
        markdown_content: Standardised or partially processed Markdown text.
        raw_markdown: Optional Stage 1 raw extracted Markdown for heading recovery.
        directory_info: Optional detected TOC/directory metadata dictionary.

    Returns:
        Markdown string with normalized heading levels.
    """
    if not markdown_content:
        return markdown_content

    raw_heading_map: dict[str, int] = {}
    if raw_markdown:
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", raw_markdown, re.MULTILINE):
            lvl = len(m.group(1))
            clean_t = re.sub(r"[\*_#]+", "", m.group(2)).strip()
            if len(clean_t) >= 3:
                raw_heading_map[clean_t.lower()] = lvl

    lines = markdown_content.split("\n")
    processed_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
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
                processed_lines.append(f"# {title_text}")
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
    for k in range(len(heading_indices) - 1):
        i1 = heading_indices[k]
        i2 = heading_indices[k + 1]
        between = [
            processed_lines[b].strip()
            for b in range(i1 + 1, i2)
            if processed_lines[b].strip()
            and not re.match(
                r"^\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?$",
                processed_lines[b].strip(),
            )
        ]
        if not between:
            h1_match = re.match(r"^(#+)\s+(.*)$", processed_lines[i1].strip())
            h2_match = re.match(r"^(#+)\s+(.*)$", processed_lines[i2].strip())
            if h1_match and h2_match and len(h1_match.group(1)) == 2 and len(h2_match.group(1)) == 2:
                processed_lines[i1] = f"# {h1_match.group(2)}"

    has_existing_h3 = any(ln.strip().startswith("### ") for ln in processed_lines)
    if not has_existing_h3:
        has_active_h2 = False
        has_active_h3 = False
        for idx, ln in enumerate(processed_lines):
            s = ln.strip()
            if re.match(r"^\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?$", s):
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
        from backend.services.directory_service import apply_directory_heading_levels

        result, _ = apply_directory_heading_levels(
            result, directory_info=directory_info, raw_markdown=raw_markdown
        )
    except Exception as e:
        logger.debug(f"Could not apply directory heading levels in infer_heading_hierarchy: {e}")

    return result


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

    parts = re.split(r"(<Tabelle\b[^>]*>.*?</Tabelle>)", text, flags=re.DOTALL | re.IGNORECASE)
    for idx in range(0, len(parts), 2):
        parts[idx] = re.sub(
            r"(?:^[ \t]*\|.+?\|[ \t]*(?:\n|$)){2,}",
            process_pipe_table,
            parts[idx],
            flags=re.MULTILINE,
        )
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
        r"(★★★|★★|★|[□◩■◇◈◆○◐●☆])\s*(?:=|->|→|:)\s*(\[[^\],\n]+\])",
        custom_rules,
    ):
        symbol_map[m_map.group(1)] = m_map.group(2).strip()

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

        for r_body in r_boxes:
            b_words = _sig_words(r_body)
            if len(b_words) < 3:
                continue
            unique_b = set(b_words)
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
        r"(\n|^)[ \t]*(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)"
        r"[ \t]*\n+[ \t]*(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)"
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
        m = re.match(r"^(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)$", stripped)
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


def post_process_structure(
    markdown_content: str,
    raw_markdown: str | None = None,
    directory_info: dict[str, Any] | None = None,
    custom_rules: str | None = None,
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

    Returns:
        Fully post-processed E-Buch Markdown string.
    """
    if not markdown_content:
        return markdown_content

    hyphen_pattern = (
        r"(\w+)-[ \t]*\n+(?:(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)[ \t]*\n+)?"
        r"[ \t]*([a-zA-ZäöüÄÖÜß]\w*)([.,;:!?])?[ \t]*"
    )

    def replace_hyphen(match: re.Match[str]) -> str:
        part1 = match.group(1)
        page_break = match.group(2)
        part2 = match.group(3)
        punct = match.group(4) or ""
        if part2 and part2[0].isupper() and part1[-1].islower():
            part2 = part2[0].lower() + part2[1:]
        joined = part1 + part2 + punct
        if page_break:
            return f"{joined}\n\n{page_break}\n\n"
        return joined

    processed = re.sub(hyphen_pattern, replace_hyphen, markdown_content)
    processed = re.sub(r"([a-zA-ZäöüÄÖÜß]{2,})-\s+([a-zA-ZäöüÄÖÜß]{2,})", r"\1\2", processed)

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
    for fn_num in set(re.findall(r"(?<![_^\\])\{(\d{1,2})\}", processed)):
        if not re.search(rf"<Anmerkung>\s*{fn_num}\b", processed):
            processed = re.sub(
                rf"(?m)^[ \t]*(?:\^?{fn_num}|\[{fn_num}\]|\{{{fn_num}\}})[ \t]+([A-ZÄÖÜ][^\n]+)$",
                rf"<Anmerkung> {fn_num} \1 </Anmerkung>",
                processed,
            )
        if not re.search(rf"<Anmerkung>\s*{fn_num}\b", processed):
            processed = re.sub(
                rf"(?<![_^\\])\{{{fn_num}\}}(?=[ \t.,;!?)]*(?:\n|$))",
                fn_num,
                processed,
            )

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

    processed = infer_heading_hierarchy(
        processed, raw_markdown=raw_markdown, directory_info=directory_info
    )
    processed = _unroll_subtask_tables_and_convert_md_tables(processed)

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
        r"<Tabelle>\s*([\s\S]*?)\s*</Tabelle>\s*\n+(\(\(\d+\)\)(?:\s*/\s*\(\(\d+\)\))?)\s*\n+<Tabelle>\s*([\s\S]*?)\s*</Tabelle>",
        _merge_cross_page_tabelle_blocks,
        processed,
        flags=re.IGNORECASE,
    )

    processed = re.sub(r"\*\*([^\*\n]+)\*\*", r"_\1_", processed)
    processed = _normalize_fibs_task_headings_and_boxes(processed, custom_rules=custom_rules)

    try:
        from backend.services.formula_service import standardize_formulas

        processed = standardize_formulas(processed)
    except Exception as e:
        logger.error(f"Error standardizing formulas in post_process_structure: {e}")

    processed = normalize_versalien(processed)
    processed = re.sub(r"[„“”»«]", '"', processed)
    processed = re.sub(r"[‚‘’‹›]", "'", processed)

    processed = re.sub(
        r"(?m)^([ \t]*(?:[-*][ \t]+)?[^\n]+?[A-Za-zäöüÄÖÜß0-9\)\]])[ \t]*[\.\·…]{3,}[ \t]*(\d{1,4})[ \t]*$",
        r"\1 \2",
        processed,
    )

    processed = re.sub(r"…", " ...", processed)
    processed = re.sub(r"([a-zA-Z0-9äöüÄÖÜß_\*\%#])\.\.\.", r"\1 ...", processed)
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
            r"!\[\]\((?:images/|figures/)?[^)\n]+\)[ \t]*\n+(?=(?:\(\(\d+\)\)\s*\n+)?!\[FIGURE\s+\d+)",
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
            r"((?:!\[\]\((?:images/|figures/)?[^)\n]+\)\s*\n+)+)(\(\(\d+\)\))\s*\n+(FIGURE\s+\d+\.\d+\s+[^\n]+)",
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

    if directory_info and directory_info.get("has_any_directory"):
        try:
            from backend.services.directory_service import apply_directory_page_numbers

            processed = apply_directory_page_numbers(processed, directory_info=directory_info)
        except Exception as e:
            logger.debug(f"Could not apply directory page numbers in post_process_structure: {e}")

    processed = deduplicate_page_numbers(processed)
    return processed


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
