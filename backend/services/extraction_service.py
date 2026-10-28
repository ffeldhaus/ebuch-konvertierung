"""Extraction service for managing PDF/DOCX extraction (LightOnOCR-3, Infinity-Parser2-Flash, and Docling).

Extracts page validation, PDF page selection, and background extraction
orchestration from main.py into a dedicated service module.
"""
import asyncio
import json
import logging
import os
import re
from typing import Any

import pypdfium2 as pdfium

logger = logging.getLogger(__name__)

# Global lock to serialize layout extractions and prevent GPU memory contention
_EXTRACTION_LOCK = None

def get_extraction_lock():
    """Return the per-process asyncio lock used to serialize GPU layout extractions."""
    global _EXTRACTION_LOCK
    if _EXTRACTION_LOCK is None:
        _EXTRACTION_LOCK = asyncio.Lock()
    return _EXTRACTION_LOCK



def validate_pages_string(
    pages_str: str, total_pages: int, physical_start: int = 1
) -> tuple[bool, str]:
    """Validates page selection string (e.g., '1, 3, 5-10') against boundaries.

    Args:
        pages_str: Comma-separated page numbers and ranges (1-based).
        total_pages: Total number of pages in the document.
        physical_start: Pre-detected physical start page of the PDF (1-based).

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    if not pages_str or not pages_str.strip():
        return True, ""

    if not re.match(r"^[0-9,\-\s]+$", pages_str):
        return False, "Seitenauswahl enthält ungültige Zeichen. Erlaubt sind nur Zahlen, Kommas, Bindestriche und Leerzeichen."

    parts = pages_str.split(",")
    all_pages = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            subparts = part.split("-")
            if len(subparts) != 2:
                return False, f"Ungültiger Seitenbereich: '{part}'."
            try:
                start_val = subparts[0].strip()
                end_val = subparts[1].strip()
                if not start_val or not end_val:
                    return False, f"Ungültiger Seitenbereich: '{part}'."
                start = int(start_val)
                end = int(end_val)
                if start <= 0 or end <= 0:
                    return False, f"Seitenzahlen müssen größer als 0 sein: '{part}'."
                if start > end:
                    return False, f"Der Startwert muss kleiner oder gleich dem Endwert sein: '{part}'."
                all_pages.extend(range(start, end + 1))
            except ValueError:
                return False, f"Ungültiger Seitenbereich: '{part}'."
        else:
            try:
                p = int(part)
                if p <= 0:
                    return False, f"Seitenzahlen müssen größer als 0 sein: '{part}'."
                all_pages.append(p)
            except ValueError:
                return False, f"Ungültige Seitenzahl: '{part}'."

    if not all_pages:
        return True, ""

    min_page = min(all_pages)
    max_page = max(all_pages)
    total_selected = len(all_pages)

    if physical_start > 1:
        # Validate against the detected physical page range
        for p in all_pages:
            if not (physical_start <= p < physical_start + total_pages):
                # Allow fallback validation to relative page bounds if they entered relative pages
                if not (1 <= p <= total_pages):
                    return False, f"Seitenzahl {p} liegt außerhalb des gültigen Bereichs ({physical_start}-{physical_start + total_pages - 1})."
    else:
        # Fallback validation
        # Treat as physical offset if min_page is greater than total_pages + 5
        is_physical_offset = min_page > (total_pages + 5)
        if is_physical_offset:
            if total_selected > total_pages:
                return False, f"Seitenauswahl umfasst {total_selected} Seiten, aber das Dokument hat nur {total_pages} Seiten."
        else:
            if max_page > total_pages:
                return False, f"Seitenauswahl liegt außerhalb des gültigen Bereichs (1-{total_pages})."

    return True, ""



def parse_page_selection(pages_str: str) -> list[int]:
    """Parse a page selection string into a sorted list of 1-based page numbers.

    Args:
        pages_str: E.g. '1, 3, 5-10'

    Returns:
        Sorted list of unique 1-based page numbers.
    """
    if not pages_str or not pages_str.strip():
        return []

    selected = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            subparts = part.split("-")
            if len(subparts) == 2:
                try:
                    start = int(subparts[0].strip())
                    end = int(subparts[1].strip())
                    for p in range(min(start, end), max(start, end) + 1):
                        selected.add(p)
                except ValueError:
                    pass
        else:
            try:
                selected.add(int(part))
            except ValueError:
                pass

    return sorted(selected)


def is_contiguous_range(pages: list[int]) -> bool:
    """Check if a list of 1-based page numbers forms a contiguous range."""
    if not pages:
        return True
    return pages == list(range(pages[0], pages[-1] + 1))


def insert_page_numbers_from_metadata(
    markdown_content: str,
    json_path: str,
    pages_str: str,
    pdf_path: str | None = None,
    directory_info: dict[str, Any] | None = None,
) -> str:
    """Parses content_list.json metadata to match blocks to markdown positions and inject
    page number annotations (e.g. ((45))) at page boundaries as described in rules.
    Also leverages detected directory information (TOC, figures, tables, pictures)
    to ensure accurate printed page numbers.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            blocks = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load content list JSON for page numbers insertion: {e}")
        return markdown_content

    if isinstance(blocks, dict):
        blocks = blocks.get("blocks", blocks.get("content", []))
    elif isinstance(blocks, list) and len(blocks) > 0 and isinstance(blocks[0], list):
        flat_blocks = []
        for p_idx, page_blocks in enumerate(blocks):
            for b in page_blocks:
                if isinstance(b, dict):
                    if "page_idx" not in b:
                        b["page_idx"] = p_idx
                    flat_blocks.append(b)
        blocks = flat_blocks

    if not blocks or not isinstance(blocks, list):
        return markdown_content

    # Ensure every element in blocks is a dict
    blocks = [b for b in blocks if isinstance(b, dict)]
    if not blocks:
        return markdown_content

    # Detect if page_idx in blocks is 0-based or 1-based by checking minimum value
    min_page_idx = min((b.get("page_idx", 1) for b in blocks if "page_idx" in b), default=1)
    is_zero_based = (min_page_idx == 0)

    # Load directory_info from task directory if not passed explicitly
    if directory_info is None and json_path:
        try:
            from backend.services.directory_service import load_directory_info
            cand_dir = os.path.dirname(json_path)
            for _ in range(3):
                if not cand_dir:
                    break
                loaded = load_directory_info(cand_dir)
                if loaded:
                    directory_info = loaded
                    break
                cand_dir = os.path.dirname(cand_dir)
        except Exception:
            pass

    # Parse physical page list if pages_str is provided
    pages_list = parse_page_selection(pages_str)

    # If pages_list has relative 1-based indices (e.g. 1, 2) and directory_info has physical page numbers,
    # map relative page numbers to their physical printed numbers.
    if (
        pages_list
        and directory_info
        and directory_info.get("page_numbers")
        and max(pages_list) <= len(directory_info["page_numbers"])
        and directory_info.get("physical_start_page", 1) > 1
    ):
        dir_pages = directory_info["page_numbers"]
        pages_list = [dir_pages[p - 1] for p in pages_list if 1 <= p <= len(dir_pages)]

    # Detect physical page numbers per-page if pages_str is empty/None
    if not pages_list:
        if directory_info and directory_info.get("page_numbers"):
            pages_list = [int(p) for p in directory_info["page_numbers"]]
        elif pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
            try:
                pages_list = get_physical_page_numbers_for_pdf(pdf_path, directory_info=directory_info)
            except Exception as e:
                logger.warning(f"Error auto-detecting per-page printed numbers sequence: {e}")

        # If PDF had no text-layer page numbers (e.g., scanned PDF returning 1..N), inspect OCR blocks per page
        max_rel_page = max(
            ((b.get("page_idx", 0) + 1 if is_zero_based else b.get("page_idx", 1)) for b in blocks if b.get("page_idx") is not None),
            default=1,
        )
        if not pages_list or pages_list == list(range(1, len(pages_list) + 1)):
            ocr_lines_by_page: dict[int, list[str]] = {}
            furn_lines_by_page: dict[int, list[str]] = {}
            for b in blocks:
                raw_idx = b.get("page_idx")
                if raw_idx is None:
                    continue
                rel_p = raw_idx + 1 if is_zero_based else raw_idx
                txt = (b.get("text") or "").strip()
                if not txt:
                    continue
                if str(b.get("type", "")).lower() in ("header", "footer", "page_header", "page_footer"):
                    furn_lines_by_page.setdefault(rel_p, []).append(txt)
                else:
                    ocr_lines_by_page.setdefault(rel_p, []).append(txt)

            total_p = max(len(pages_list), max_rel_page)
            detected_from_blocks: list[int | None] = []
            for rel_p in range(1, total_p + 1):
                f_lines = furn_lines_by_page.get(rel_p, [])
                b_lines = ocr_lines_by_page.get(rel_p, [])
                cand_num = detect_page_number_from_text_lines(f_lines) if f_lines else None
                if cand_num is None and b_lines:
                    cand_num = detect_page_number_from_text_lines(b_lines[:3] + b_lines[-3:])
                detected_from_blocks.append(cand_num)

            if any(d is not None for d in detected_from_blocks):
                pages_list = _resolve_page_sequence(detected_from_blocks, fallback_start_page=1)

    # Pre-calculate physical page number for each block index
    block_page_nums = []
    for b in blocks:
        raw_idx = b.get("page_idx")
        if raw_idx is None:
            block_page_nums.append(None)
            continue
        
        # Convert to 1-based relative index
        relative_idx = raw_idx + 1 if is_zero_based else raw_idx

        if pages_list:
            if 1 <= relative_idx <= len(pages_list):
                phys_num = pages_list[relative_idx - 1]
            else:
                phys_num = pages_list[-1] + (relative_idx - len(pages_list))
        else:
            phys_num = relative_idx
        
        block_page_nums.append(phys_num)

    # Collect ordered candidate body text blocks for each page (excluding furniture, images, and footnotes)
    page_to_candidates: dict[int, list[tuple[int, str]]] = {}
    for i, b in enumerate(blocks):
        phys_num = block_page_nums[i]
        if phys_num is None:
            continue

        b_type = str(b.get("type", "")).lower()
        if b_type in ("header", "footer", "page_header", "page_footer", "image", "footnote"):
            continue

        txt = b.get("text", "").strip()
        if txt and len(txt) > 3:
            page_to_candidates.setdefault(phys_num, []).append((i, txt))

    if not page_to_candidates:
        return markdown_content

    # Sort pages to process in order
    sorted_pages = sorted(page_to_candidates.keys())

    # Check if the PDF uses landscape double-page spreads with paired page numbers ((N)) / ((N+1))
    spread_markers_by_phys: dict[int, str] = {}
    if pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        try:
            doc_sp = pdfium.PdfDocument(pdf_path)
            for p_i in range(len(doc_sp)):
                sp_pair = detect_spread_page_pair_for_pdf_page(pdf_path, p_i)
                if sp_pair is not None and p_i < len(sorted_pages):
                    spread_markers_by_phys[sorted_pages[p_i]] = f"(({sp_pair[0]})) / (({sp_pair[1]}))"
            doc_sp.close()
        except Exception:
            pass

    # If the extractor already emitted standalone ((num)) markers (e.g. one per page),
    # replace or strip any markers that do not match the resolved sorted_pages sequence
    existing_marker_matches = list(re.finditer(r"(?m)^[ \t]*\(\((\d+)\)\)[ \t]*$", markdown_content))
    if existing_marker_matches and sorted_pages:
        existing_nums = [int(m.group(1)) for m in existing_marker_matches]
        if existing_nums != sorted_pages:
            if len(existing_marker_matches) == len(sorted_pages):
                # 1-to-1 replacement of per-page markers with authoritative sorted_pages
                rebuilt = []
                last_end = 0
                for m_obj, phys_num in zip(existing_marker_matches, sorted_pages):
                    rebuilt.append(markdown_content[last_end:m_obj.start()])
                    rebuilt.append(spread_markers_by_phys.get(phys_num, f"(({phys_num}))"))
                    last_end = m_obj.end()
                rebuilt.append(markdown_content[last_end:])
                markdown_content = "".join(rebuilt)
            else:
                valid_set = set(sorted_pages)
                markdown_content = re.sub(
                    r"(?m)^[ \t]*\(\((\d+)\)\)[ \t]*\n*",
                    lambda m: m.group(0) if int(m.group(1)) in valid_set else "",
                    markdown_content,
                )

    current_pos = 0
    modified_markdown = markdown_content
    offset = 0
    inserted_pages = set()


    for phys_num in sorted_pages:
        if phys_num in inserted_pages:
            continue

        marker_token = spread_markers_by_phys.get(phys_num, f"(({phys_num}))")
        matched_this_page = False
        for _block_idx, block_text in page_to_candidates[phys_num]:
            # Build a regex matching signature (first 15 alphanumeric characters)
            cleaned_block = re.sub(r"\W+", "", block_text)
            if not cleaned_block:
                continue

            sig = cleaned_block[:15]
            if len(sig) < 4:
                continue

            block_has_dots = bool(re.search(r"[\.\·…]{2,}\s*\d{1,4}\s*$", block_text.strip()))
            block_ends_with_num = bool(re.search(r"\b\d{1,4}\s*\|?$", block_text.strip()))
            block_is_table_row = block_text.strip().startswith("|")
            pattern = r"[^\w]*".join(re.escape(c) for c in sig)
            chosen_match = None
            for m_cand in re.finditer(pattern, markdown_content[current_pos:]):
                cand_start = current_pos + m_cand.start()
                line_s = markdown_content.rfind("\n", 0, cand_start) + 1
                line_e = markdown_content.find("\n", cand_start)
                if line_e == -1:
                    line_e = len(markdown_content)
                cand_line = markdown_content[line_s:line_e].strip()
                # Never match a TOC/directory entry line (with leader dots or trailing page number) or pipe table row for a body heading
                if not block_has_dots and re.search(r"[\.\·…]{2,}\s*\d{1,4}\s*$", cand_line):
                    continue
                if not block_is_table_row and cand_line.startswith("|"):
                    continue
                if not block_ends_with_num and re.search(r"(?:[\.\·…]{2,}|\s{2,}|^-\s+[^\n]+)\s+\d{1,4}\s*\|?$", cand_line):
                    continue
                chosen_match = m_cand
                break

            if chosen_match:
                match_start_in_original = current_pos + chosen_match.start()

                # Check window before insertion point in modified markdown to prevent duplicates
                check_start = max(0, match_start_in_original + offset - 60)
                check_end = match_start_in_original + offset
                window = modified_markdown[check_start:check_end]

                already_has_marker = (
                    marker_token in modified_markdown
                    if phys_num in spread_markers_by_phys
                    else bool(re.search(rf"(?m)^[ \t]*\(\({phys_num}\)\)[ \t]*$", modified_markdown))
                )
                if (
                    already_has_marker
                    or marker_token in window
                    or f"Seite {phys_num}" in window
                    or f"[{phys_num}]" in window
                ):
                    current_pos = match_start_in_original + min(len(block_text), 40)
                    inserted_pages.add(phys_num)
                    matched_this_page = True
                    break

                # Scan backwards in original to find paragraph beginning
                insert_idx_original = match_start_in_original
                while insert_idx_original > current_pos and markdown_content[insert_idx_original - 1] not in ('\r', '\n'):
                    insert_idx_original -= 1

                insert_idx_modified = insert_idx_original + offset
                marker = f"\n\n{marker_token}\n\n"

                modified_markdown = modified_markdown[:insert_idx_modified] + marker + modified_markdown[insert_idx_modified:]
                offset += len(marker)

                current_pos = match_start_in_original + min(len(block_text), 40)
                # Advance current_pos past subsequent blocks belonging to this same page if they are directory lines
                for _b_i, later_txt in page_to_candidates[phys_num]:
                    if re.search(r"[\.\·…]{2,}\s*\d{1,4}\s*$", later_txt.strip()):
                        c_lat = re.sub(r"\W+", "", later_txt)[:15]
                        if len(c_lat) >= 4:
                            p_lat = r"[^\w]*".join(re.escape(c) for c in c_lat)
                            m_lat = re.search(p_lat, markdown_content[current_pos:])
                            if m_lat and m_lat.start() < 1500:
                                current_pos = current_pos + m_lat.end()
                inserted_pages.add(phys_num)
                matched_this_page = True
                break

        if not matched_this_page:
            # If first page cannot be matched inside text, prepend to start of document only if not already present
            if phys_num == sorted_pages[0] and phys_num not in inserted_pages and f"(({phys_num}))" not in modified_markdown:
                marker = f"{marker_token}\n\n"
                modified_markdown = marker + modified_markdown
                offset += len(marker)
                inserted_pages.add(phys_num)

    if directory_info and directory_info.get("has_any_directory"):
        try:
            from backend.services.directory_service import apply_directory_page_numbers
            modified_markdown = apply_directory_page_numbers(modified_markdown, directory_info)
        except Exception as ex:
            logger.warning(f"Error applying directory page numbers: {ex}")

    try:
        from backend.services.fibs_postprocess import deduplicate_page_numbers
        modified_markdown = deduplicate_page_numbers(modified_markdown)
    except Exception as ex:
        logger.warning(f"Error deduplicating page numbers: {ex}")

    return modified_markdown


def extract_pdf_pages(input_path: str, pages_str: str, output_path: str) -> bool:
    """Parses comma-separated pages/ranges and extracts them from input_path PDF
    to output_path PDF using pypdfium2.

    Returns True if pages were extracted, False if all pages should be used.
    """
    if not pages_str or not pages_str.strip():
        return False

    selected_pages = set()
    parts = pages_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            subparts = part.split("-")
            if len(subparts) == 2:
                try:
                    start = int(subparts[0].strip())
                    end = int(subparts[1].strip())
                    for p in range(min(start, end), max(start, end) + 1):
                        selected_pages.add(p - 1)  # Convert to 0-based
                except ValueError:
                    logger.warning(f"Invalid page range: {part}")
        else:
            try:
                p = int(part)
                selected_pages.add(p - 1)  # Convert to 0-based
            except ValueError:
                logger.warning(f"Invalid page number: {part}")

    if not selected_pages:
        return False

    try:
        doc = pdfium.PdfDocument(input_path)
        total_pages = len(doc)

        valid_indices = sorted([p for p in selected_pages if 0 <= p < total_pages])

        if not valid_indices:
            doc.close()
            logger.warning(
                f"No valid page indices found within [1, {total_pages}] for: {pages_str}"
            )
            return False

        new_doc = pdfium.PdfDocument.new()
        new_doc.import_pages(doc, valid_indices)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        new_doc.save(output_path)
        new_doc.close()
        doc.close()

        logger.info(f"Extracted pages {valid_indices} to {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error extracting PDF pages: {str(e)}")
        return False


def get_pdf_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF file."""
    try:
        doc = pdfium.PdfDocument(pdf_path)
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        logger.warning(f"Error counting PDF pages: {e}")
        return 0


def detect_page_number_from_text_lines(lines: list[str]) -> int | None:
    """Extract a printed page number from header/footer/boundary lines of a single page."""
    raw_clean_lines = [ln.strip() for ln in lines if ln and ln.strip()]
    if not raw_clean_lines:
        return None

    # Exclude InDesign print-production slug lines (e.g. 'DO01_...indd 18 14.10.2025 09:42:15')
    slug_re = re.compile(r"\S+\.indd\s+(\d{1,4})\s+\d{2}\.\d{2}\.\d{4}", re.IGNORECASE)
    clean_lines = [ln for ln in raw_clean_lines if not slug_re.search(ln)]
    if not clean_lines:
        clean_lines = raw_clean_lines

    joined_text = "\n".join(clean_lines)
    is_directory_page = bool(
        re.search(
            r"\b(?:Inhaltsverzeichnis|Abbildungsverzeichnis|Tabellenverzeichnis|Bildverzeichnis)\b",
            joined_text,
            re.IGNORECASE,
        )
    )
    dotted_lines = sum(1 for ln in clean_lines if re.search(r"[\.\·…]{3,}\s*\d{1,4}\s*$", ln))
    if dotted_lines >= 3:
        is_directory_page = True

    # 1. Search for "Seite/Page X" in header or footer boundary lines (skip dotted directory lines and cross-references)
    boundary_candidates = list(reversed(clean_lines[-2:])) + clean_lines[:2]
    for line in boundary_candidates:
        if re.search(r"[\.\·…]{2,}", line):
            continue
        if is_directory_page and re.match(r"^(?:Abb|Tab|Bild|Kapitel|\d+\.\d+)", line, re.IGNORECASE):
            continue
        # Strip parenthetical cross-references like '(Nachlesen: S. 18)' or '(siehe Seite 18)'
        line_no_parens = re.sub(r"\([^\)]*\)", "", line)
        m = re.search(r"\b(?:[sS]eite|[pP]age)\s*(\d+)\b", line_no_parens, re.IGNORECASE)
        if m:
            return int(m.group(1))

    # 2. Look for standalone numbers in footer (last 3 lines)
    for line in reversed(clean_lines[-3:]):
        m = re.match(r"^(\d+)$", line)
        if m:
            return int(m.group(1))

    # 3. Look for standalone numbers in header (first 3 lines)
    for line in clean_lines[:3]:
        m = re.match(r"^(\d+)$", line)
        if m:
            return int(m.group(1))

    # 4. Alternating layout in footer (last 3 lines) — skip trailing numbers on directory pages
    for line in reversed(clean_lines[-3:]):
        if re.search(r"[\.\·…]{2,}", line):
            continue
        if re.match(r"^(?:Chapter|Kapitel|Section|Part|Teil|Unit|Band|Klasse|Inhaltsfeld)\s+\d+$", line, re.IGNORECASE):
            continue
        m = re.match(r"^(\d{1,4})\s+(?:(?:\|\s*|\d+(?:\.\d+)*\s*[•|\-–]\s*))?[a-zA-ZäöüÄÖÜß]", line)
        if m and not is_directory_page:
            return int(m.group(1))
        if not is_directory_page:
            m = re.search(r"[a-zA-ZäöüÄÖÜß\)\.](?:\s*[|•\-–]\s*|\s+)(\d{1,4})$", line)
            if m:
                return int(m.group(1))

    # 5. Alternating layout in header (first 3 lines)
    for line in clean_lines[:3]:
        if re.search(r"[\.\·…]{2,}", line):
            continue
        if re.match(r"^(?:Chapter|Kapitel|Section|Part|Teil|Unit|Band|Klasse|Inhaltsfeld)\s+\d+$", line, re.IGNORECASE):
            continue
        m = re.match(r"^(\d{1,4})\s+(?:(?:\|\s*|\d+(?:\.\d+)*\s*[•|\-–]\s*))?[a-zA-ZäöüÄÖÜß]", line)
        if m:
            return int(m.group(1))
        if not is_directory_page:
            m = re.search(r"[a-zA-ZäöüÄÖÜß\)\.](?:\s*[|•\-–]\s*|\s+)(\d{1,4})$", line)
            if m:
                return int(m.group(1))

    return None


def _resolve_page_sequence(detected: list[int | None], fallback_start_page: int = 1) -> list[int]:
    """Resolves a list of per-page detected numbers into a complete, strictly monotonic (+1) sequence.
    Uses consensus offset (d_i - i) across pages (preferring adjacent +1 pairs) to reject OCR outliers
    (such as duplicate, backward-jumping, or multi-digit misread numbers), or falls back to
    `fallback_start_page + i`.
    """
    total_pages = len(detected)
    if total_pages == 0:
        return [fallback_start_page]

    # Collect valid offsets (d_i - i >= 1) and weight offsets supported by consecutive +1 transitions
    valid_pairs = [(idx, int(d)) for idx, d in enumerate(detected) if d is not None and int(d) - idx >= 1]
    if valid_pairs:
        from collections import Counter

        offset_counts: Counter = Counter()
        for idx, d in valid_pairs:
            offset_counts[d - idx] += 1

        # Give extra weight to offsets confirmed by strictly increasing (+1) pairs
        for i in range(len(valid_pairs) - 1):
            idx1, d1 = valid_pairs[i]
            idx2, d2 = valid_pairs[i + 1]
            if (d1 - idx1) == (d2 - idx2):
                offset_counts[d1 - idx1] += 2

        # Pick the offset with the highest score; break ties by preferring the offset closest to fallback_start_page
        best_offset = max(
            offset_counts.keys(),
            key=lambda off: (offset_counts[off], -abs(off - max(1, fallback_start_page))),
        )
        return [best_offset + i for i in range(total_pages)]

    return [max(1, fallback_start_page) + i for i in range(total_pages)]




def detect_spread_page_pair_for_pdf_page(pdf_path: str, page_idx: int) -> tuple[int, int] | None:
    """Detects whether a specific PDF page is a landscape double-page spread (width > height * 1.18)
    containing two consecutive printed page numbers (p_left, p_left + 1) at the left and right margins.
    """
    if not pdf_path or not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        return None
    try:
        doc = pdfium.PdfDocument(pdf_path)
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return None
        page = doc[page_idx]
        pw, ph = page.get_size()
        if pw <= ph * 1.18:
            doc.close()
            return None
        textpage = page.get_textpage()
        text = textpage.get_text_range().strip()
        textpage.close()
        doc.close()

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in lines[:4] + lines[-4:]:
            m = re.match(r"^(?:Seite\s*)?(\d{1,4})\b.*?\b(?:Seite\s*)?(\d{1,4})$", line, re.IGNORECASE)
            if m:
                p1, p2 = int(m.group(1)), int(m.group(2))
                if p2 == p1 + 1:
                    return (p1, p2)
    except Exception:
        pass
    return None


def detect_page_number_for_pdf_page(pdf_path: str, page_idx: int) -> int | None:
    """Extracts printed page number from a specific page index in a PDF.
    Returns None if no page number could be detected.
    """
    if not pdf_path or not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        return None
    spread_pair = detect_spread_page_pair_for_pdf_page(pdf_path, page_idx)
    if spread_pair is not None:
        return spread_pair[0]
    try:
        doc = pdfium.PdfDocument(pdf_path)
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return None
        page = doc[page_idx]
        textpage = page.get_textpage()
        text = textpage.get_text_range().strip()
        textpage.close()
        doc.close()

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            return detect_page_number_from_text_lines(lines)
    except Exception as e:
        logger.warning(f"Error detecting page number for page index {page_idx}: {e}")
    return None


def get_physical_page_numbers_for_pdf(
    pdf_path: str,
    fallback_start_page: int = 1,
    directory_info: dict[str, Any] | None = None,
) -> list[int]:
    """Returns a list of physical page numbers, one for each page in the PDF.
    First checks if a Table of Contents, List of Figures, List of Tables, or
    List of Pictures is present in the first 20 pages and uses its entries to
    infer and verify the physical page sequence. Otherwise scans each page
    individually for printed page numbers and fills undetected pages continuously.
    """
    if pdf_path and not os.path.isabs(pdf_path) and not os.path.exists(pdf_path):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        cand_path = os.path.join(project_root, pdf_path)
        if os.path.exists(cand_path):
            pdf_path = cand_path

    total_pages = get_pdf_page_count(pdf_path)
    if total_pages == 0:
        return [fallback_start_page]

    # Use directory check (cached, checks at most first 20 pages without formulas/tables/images)
    if directory_info is None and pdf_path and os.path.exists(pdf_path) and pdf_path.lower().endswith(".pdf"):
        try:
            from backend.services.directory_service import check_document_directories
            directory_info = check_document_directories(pdf_path, max_pages=20)
        except Exception as e:
            logger.debug(f"Fast directory check skipped in get_physical_page_numbers_for_pdf: {e}")

    if (
        directory_info
        and directory_info.get("has_any_directory")
        and isinstance(directory_info.get("page_numbers"), list)
        and len(directory_info["page_numbers"]) == total_pages
    ):
        return [int(p) for p in directory_info["page_numbers"]]

    spread_pairs = [detect_spread_page_pair_for_pdf_page(pdf_path, i) for i in range(total_pages)]
    if any(sp is not None for sp in spread_pairs):
        resolved_spread: list[int] = []
        for i, sp in enumerate(spread_pairs):
            if sp is not None:
                resolved_spread.append(sp[0])
            elif resolved_spread:
                resolved_spread.append(resolved_spread[-1] + 2)
            else:
                d_val = detect_page_number_for_pdf_page(pdf_path, i)
                resolved_spread.append(d_val if d_val is not None else max(1, fallback_start_page) + 2 * i)
        return resolved_spread

    detected = [detect_page_number_for_pdf_page(pdf_path, i) for i in range(total_pages)]
    return _resolve_page_sequence(detected, fallback_start_page=fallback_start_page)


def detect_physical_start_page(
    pdf_path: str, directory_info: dict[str, Any] | None = None
) -> int:
    """Returns the physical page number of the first page of the PDF.
    Uses directory information if available, scans page 0, or falls back to 1.
    """
    pages = get_physical_page_numbers_for_pdf(pdf_path, directory_info=directory_info)
    return pages[0] if pages else 1



async def run_background_extraction(
    task: dict,
    input_path: str,
    output_root: str,
    upload_dir: str,
    pages_str: str | None = None,
    method: str = "auto",
    lang: str = "en",
    backend: str = "vlm-engine",
    engine: str = "infinity",
) -> None:
    """Execute document OCR/layout extraction and VLM image description in the background."""
    task["status"] = "queued"
    task["progress"] = {
        "percent": 0,
        "current": 0,
        "total": 0,
        "phase": "In Warteschlange..."
    }
    
    # Notify listeners about queued status
    queued_event = '{"status": "progress", "percent": 0, "current": 0, "total": 0, "phase": "In Warteschlange..."}\n'
    for queue in list(task["listeners"]):
        try:
            await queue.put(queued_event)
        except Exception:
            pass

    from backend.services.task_manager import acquire_sleep_assertion_sync, release_sleep_assertion_sync
    acquire_sleep_assertion_sync()
    try:
        async with get_extraction_lock():
            await _run_background_extraction_locked(
                task=task,
                input_path=input_path,
                output_root=output_root,
                upload_dir=upload_dir,
                pages_str=pages_str,
                method=method,
                lang=lang,
                backend=backend,
                engine=engine,
            )
    finally:
        release_sleep_assertion_sync()


async def _run_background_extraction_locked(
    task: dict,
    input_path: str,
    output_root: str,
    upload_dir: str,
    pages_str: str | None = None,
    method: str = "auto",
    lang: str = "en",
    backend: str = "vlm-engine",
    engine: str = "infinity",
) -> None:
    # Release GPU memory before starting extraction (GPU sequencing)
    try:
        from backend.services.llm_service import release_gpu_memory
        release_gpu_memory()
    except ImportError:
        pass

    task_id = task["task_id"]
    task["status"] = "processing"

    # Check for E2E Mock mode
    original_name = task.get("original_name", "")
    if os.environ.get("E2E_MOCK") == "true":
        logger.info(f"E2E_MOCK is true and file is {original_name}. Running mock extraction for task {task_id}")
        from backend.services.mock_fixtures import run_e2e_mock_extraction
        await run_e2e_mock_extraction(task, input_path, output_root)
        return

    # Determine page range parameters
    process_path = input_path

    # Ensure directory check and physical start page detection are available
    directory_info = task.get("directory_info")
    if directory_info is None and os.path.exists(input_path):
        try:
            from backend.services.directory_service import check_document_directories, save_directory_info
            directory_info = check_document_directories(input_path, max_pages=20)
            task["directory_info"] = directory_info
            save_directory_info(output_root, directory_info)
        except Exception as e:
            logger.debug(f"Directory check skipped in background extraction: {e}")

    physical_start = task.get("physical_start_page") or 1
    if physical_start == 1:
        physical_start = detect_physical_start_page(input_path, directory_info=directory_info)
        task["physical_start_page"] = physical_start

    if pages_str and task["extension"] == ".pdf":
        pages = parse_page_selection(pages_str)
        if pages:
            # Check if this is a physical page offset selection
            pdf_total = task.get("page_count", 0)
            if pdf_total == 0:
                pdf_total = get_pdf_page_count(input_path)
            is_physical_offset = pages[-1] > pdf_total
            if is_physical_offset:
                # Map physical range offsets back to relative page numbers (1-based)
                mapped_pages = [p - physical_start + 1 for p in pages]
                if any(p < 1 or p > pdf_total for p in mapped_pages):
                    mapped_pages = [p - pages[0] + 1 for p in pages]
                mapped_pages_str = ",".join(str(p) for p in mapped_pages)
            else:
                mapped_pages = pages
                mapped_pages_str = pages_str

            selected_pdf_path = os.path.join(upload_dir, "selected", f"{task_id}.pdf")
            if extract_pdf_pages(input_path, mapped_pages_str, selected_pdf_path):
                process_path = selected_pdf_path

    # Count pages for progress reporting
    total_pdf_pages = 1
    if task["extension"] == ".pdf":
        total_pdf_pages = get_pdf_page_count(process_path) or 1

    base_name = os.path.splitext(os.path.basename(process_path))[0]
    auto_dir = os.path.join(output_root, base_name, "auto")
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import sys

    python_exe = sys.executable or "python"
    if engine == "docling":
        # Setup output auto dir directly since our docling script writes to it
        cmd = [
            python_exe,
            "-m",
            "backend.services.docling_extractor",
            "--input", process_path,
            "--output-dir", auto_dir,
            "--ocr-lang", lang,
        ]
    elif engine in ("lightonocr", "lightonocr3"):
        cmd = [
            python_exe,
            "-m",
            "backend.services.lightonocr_extractor",
            "--input", process_path,
            "--output-dir", auto_dir,
        ]
    else:
        # Default engine: Infinity-Parser2-Flash
        cmd = [
            python_exe,
            "-m",
            "backend.services.infinity_parser_extractor",
            "--input", process_path,
            "--output-dir", auto_dir,
        ]

    # Setup subprocess environment (cross-platform CUDA / MPS / CPU detection)
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "8"
    env["MKL_NUM_THREADS"] = "8"
    env["OPENBLAS_NUM_THREADS"] = "8"
    env["NUMEXPR_NUM_THREADS"] = "8"
    if sys.platform == "darwin":
        env["VECLIB_MAXIMUM_THREADS"] = "8"
        env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
        env["MLX_ENABLE_COMPILE"] = "0"
        env["MLX_DISABLE_COMPILE"] = "1"
    if "TORCH_DEVICE" not in env:
        try:
            import torch
            if torch.cuda.is_available():
                env["TORCH_DEVICE"] = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                env["TORCH_DEVICE"] = "mps"
            else:
                env["TORCH_DEVICE"] = "cpu"
        except ImportError:
            env["TORCH_DEVICE"] = "mps" if sys.platform == "darwin" else "cpu"
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["PYTHONMALLOC"] = "malloc"
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["PYTHONWARNINGS"] = "ignore::UserWarning:multiprocessing.resource_tracker"

    try:
        # Initial log
        start_log = f"{engine.capitalize()}-Prozess gestartet..."
        task["logs"].append(start_log)
        start_event = f'{{"status": "log", "message": {json.dumps(start_log)}}}\n'
        for queue in list(task["listeners"]):
            await queue.put(start_event)

        # Launch the subprocess
        logger.info(f"Running {engine} extraction for task {task_id}: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=project_root,
        )
        task["process"] = process

        # Read stdout chunk by chunk and parse tqdm bars & page streaming chunks
        chunk_buffer = ""
        current_page = 0
        seen_layout_parsing = False
        in_stream_page = False
        stream_page_buffer = []

        while True:
            chunk_bytes = await process.stdout.read(1024)
            if not chunk_bytes:
                break

            chunk_str = chunk_bytes.decode("utf-8", errors="ignore")
            chunk_buffer += chunk_str

            lines = re.split(r"[\r\n]+", chunk_buffer)
            chunk_buffer = lines.pop() if lines else ""

            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue

                if line_str == "---STREAM_PAGE_START---":
                    in_stream_page = True
                    stream_page_buffer = []
                    continue
                elif line_str == "---STREAM_PAGE_END---":
                    in_stream_page = False
                    try:
                        page_json_str = "\n".join(stream_page_buffer)
                        page_data = json.loads(page_json_str)
                        if page_data.get("status") == "raw_chunk":
                            delta = page_data.get("delta", "")
                            if delta:
                                prev_raw = task.get("raw_markdown", "")
                                task["raw_markdown"] = (prev_raw + "\n\n" + delta).strip() if prev_raw else delta
                            raw_chunk_event = f'{json.dumps(page_data)}\n'
                            for queue in list(task["listeners"]):
                                await queue.put(raw_chunk_event)
                    except Exception as ex:
                        logger.warning(f"Failed to parse streamed raw page chunk: {ex}")
                    stream_page_buffer = []
                    continue

                if in_stream_page:
                    stream_page_buffer.append(line)
                    continue

                # Filter out harmless Python shutdown/cleanup warnings from user UI log console
                if "resource_tracker" in line_str or "leaked semaphore" in line_str:
                    logger.debug(f"Filtered internal cleanup warning from UI logs: {line_str}")
                    continue

                task["logs"].append(line_str)
                log_event = f'{{"status": "log", "message": {json.dumps(line_str)}}}\n'
                for queue in list(task["listeners"]):
                    await queue.put(log_event)

                # Parse progress indicator from tqdm bar
                if "%|" in line_str:
                    percent_match = re.search(r"(\d+)%\|", line_str)
                    progress_match = re.search(r"(\d+)/(\d+)", line_str)

                    if percent_match and progress_match:
                        percent_val = int(percent_match.group(1))
                        current_val = int(progress_match.group(1))

                        phase = task.get("progress", {}).get("phase", "Extraktion...")
                        global_percent = task.get("progress", {}).get("percent", 0)

                        if "Layout Output Parsing" in line_str:
                            seen_layout_parsing = True
                            phase = "Layout-Verarbeitung"
                            global_percent = int(75 + (percent_val / 100.0) * 1)
                        elif "Predict" in line_str:
                            if not seen_layout_parsing:
                                phase = "Layout-Analyse"
                                global_percent = int(0 + (percent_val / 100.0) * 75)
                                current_page = current_val
                            else:
                                phase = "Tabellen-Inhaltsanalyse"
                                global_percent = int(77 + (percent_val / 100.0) * 1)
                        elif "Table orientation" in line_str:
                            phase = "Tabellen-Orientierung"
                            global_percent = int(75 + (percent_val / 100.0) * 1)
                        elif "Table-ocr det" in line_str:
                            phase = "Tabellen-Texterkennung"
                            global_percent = int(76 + (percent_val / 100.0) * 1)
                        elif "Table-ocr rec" in line_str:
                            phase = "Tabellen-Inhaltsanalyse"
                            global_percent = int(77 + (percent_val / 100.0) * 1)
                        elif "Table-wireless" in line_str or "Table-wired" in line_str:
                            phase = "Tabellen-Strukturierung"
                            global_percent = int(78 + (percent_val / 100.0) * 2)
                        elif "OCR-det" in line_str:
                            phase = "Dokumenten-Texterkennung"
                            global_percent = int(80 + (percent_val / 100.0) * 10)
                        elif "Processing pages" in line_str:
                            phase = "Extraktion & Formatierung"
                            global_percent = int(90 + (percent_val / 100.0) * 5)
                            current_page = current_val
                        elif "OCR-rec" in line_str:
                            phase = "Texterkennung-Finalisierung"
                            global_percent = int(95 + (percent_val / 100.0) * 4)

                        current_progress = task["progress"].get("percent", 0)
                        if global_percent < current_progress:
                            global_percent = current_progress

                        if current_page == 0:
                            current_page = max(1, int((global_percent / 100.0) * total_pdf_pages))

                        current_page = min(current_page, total_pdf_pages)

                        progress_info = {
                            "percent": global_percent,
                            "current": current_page,
                            "total": total_pdf_pages,
                            "phase": phase
                        }
                        task["progress"] = progress_info

                        progress_event = (
                            f'{{"status": "progress", "percent": {global_percent}, '
                            f'"current": {current_page}, "total": {total_pdf_pages}, '
                            f'"phase": "{phase}"}}\n'
                        )
                        for queue in list(task["listeners"]):
                            await queue.put(progress_event)

        await process.wait()

        if task.get("is_abort_requested") or task.get("status") == "aborted":
            logger.info(f"Extraction task {task_id} was aborted by user.")
            abort_event = '{"status": "aborted", "message": "Konvertierung wurde auf Benutzerwunsch abgebrochen."}\n'
            for queue in list(task["listeners"]):
                await queue.put(abort_event)
            return

        if process.returncode != 0:
            err_msg = f"{engine.capitalize()}-Extraktion fehlgeschlagen mit Exit-Code {process.returncode}."
            logger.error(f"{engine.capitalize()} process failed for task {task_id} with exit code {process.returncode}. Last 20 logs:")
            for log in task.get("logs", [])[-20:]:
                logger.error(f"  [{engine.capitalize()} Output] {log}")
            task["status"] = "failed"
            error_event = f'{{"status": "error", "message": "{err_msg}"}}\n'
            for queue in list(task["listeners"]):
                await queue.put(error_event)
            return

        # Locate the output Markdown file
        auto_dir = os.path.join(output_root, base_name, "auto")

        if not os.path.exists(auto_dir):
            import glob
            md_files = glob.glob(os.path.join(output_root, "**", "*.md"), recursive=True)
            if md_files:
                md_path = md_files[0]
                auto_dir = os.path.dirname(md_path)
            else:
                err_msg = "Markdown-Ausgabedatei wurde nicht gefunden."
                task["status"] = "failed"
                error_event = f'{{"status": "error", "message": "{err_msg}"}}\n'
                for queue in list(task["listeners"]):
                    await queue.put(error_event)
                return
        else:
            md_path = os.path.join(auto_dir, f"{base_name}.md")

        if not os.path.exists(md_path):
            import glob
            md_files = glob.glob(os.path.join(auto_dir, "*.md"))
            if md_files:
                md_path = md_files[0]
            else:
                err_msg = "No Markdown file found in output directory."
                task["status"] = "failed"
                error_event = f'{{"status": "error", "message": "{err_msg}"}}\n'
                for queue in list(task["listeners"]):
                    await queue.put(error_event)
                return

        with open(md_path, encoding="utf-8") as f:
            markdown_content = f.read()

        # Inject page numbers from metadata content list JSON
        json_path = os.path.join(auto_dir, f"{base_name}_content_list.json")
        if not os.path.exists(json_path):
            json_path = os.path.join(auto_dir, f"{base_name}_content_list_v2.json")
        if not os.path.exists(json_path):
            import glob
            json_files = glob.glob(os.path.join(auto_dir, "*content_list*.json"))
            if json_files:
                json_path = json_files[0]
            else:
                json_path = None

        if json_path:
            logger.info(f"Processing metadata JSON: {json_path}")

        if json_path:
            markdown_content = insert_page_numbers_from_metadata(
                markdown_content,
                json_path,
                pages_str,
                pdf_path=process_path,
                directory_info=directory_info,
            )

        if directory_info and directory_info.get("has_any_directory"):
            try:
                from backend.services.directory_service import (
                    apply_directory_heading_levels,
                    apply_directory_page_numbers,
                )
                markdown_content, _ = apply_directory_heading_levels(markdown_content, directory_info)
                if not pages_str:
                    markdown_content = apply_directory_page_numbers(markdown_content, directory_info)
            except Exception as dir_err:
                logger.warning(f"Error applying directory structure to raw markdown: {dir_err}")

        # Find images
        image_dir = os.path.join(auto_dir, "images")
        images = []
        if os.path.exists(image_dir):
            images = [
                os.path.join(image_dir, f)
                for f in os.listdir(image_dir)
                if os.path.isfile(os.path.join(image_dir, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))
            ]

        # Update task state
        task["status"] = "completed"
        task["raw_markdown"] = markdown_content
        task["image_dir"] = image_dir
        task["images"] = images
        task["progress"] = {
            "percent": 100,
            "current": total_pdf_pages,
            "total": total_pdf_pages,
            "phase": "Extraktion abgeschlossen",
        }

        # Notify listeners
        completed_event = (
            f'{{"status": "completed", '
            f'"markdown": {json.dumps(markdown_content)}, '
            f'"image_count": {len(images)}}}\n'
        )
        for queue in list(task["listeners"]):
            await queue.put(completed_event)

        log_msg = f"{engine.capitalize()}-Extraktion abgeschlossen: {len(markdown_content)} Zeichen, {len(images)} Bilder"
        task["logs"].append(log_msg)

    except Exception as e:
        err_msg = f"Systemfehler während der Extraktion: {str(e)}"
        logger.error(f"Extraction failed for task {task_id}: {e}")
        task["status"] = "failed"
        error_event = f'{{"status": "error", "message": {json.dumps(err_msg)}}}\n'
        for queue in list(task["listeners"]):
            await queue.put(error_event)
    finally:
        # Close listener queues (send None to end SSE stream)
        for queue in list(task["listeners"]):
            try:
                await queue.put(None)
            except Exception:
                pass
        import gc
        gc.collect()
