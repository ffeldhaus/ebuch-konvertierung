"""Unit tests for directory-assisted page number normalization, deduplication, and bounding."""

import json
import re

from backend.services.directory_service import apply_directory_page_numbers
from backend.services.extraction_service import insert_page_numbers_from_metadata


def test_heading_prefixed_page_markers_do_not_corrupt_or_overflow_page_range(tmp_path):
    """Verifies that ``#### ((294))``, ``### ((295)) Titel``, and dangling ``####`` lines
    are normalized and deduplicated before page counting so a 25-page extraction
    (272-296) never invents ``((297))`` or ``((298))`` or shifts page breaks.
    """
    blocks = []
    md_parts = []
    for offset in range(25):
        pg = 272 + offset
        blocks.append(
            {
                "type": "text",
                "text": f"Synthetischer Lehrtext der Physik auf Seite {pg} zur Mechanik.",
                "page_idx": offset,
            }
        )
        if pg == 293:
            md_parts.append(
                f"(({pg}))\n\nSynthetischer Lehrtext der Physik auf Seite {pg} zur Mechanik.\n\n####"
            )
        elif pg == 294:
            md_parts.append(
                f"#### (({pg}))\n\nSynthetischer Lehrtext der Physik auf Seite {pg} zur Mechanik."
            )
        elif pg == 295:
            md_parts.append(
                f"### (({pg})) Abschnitt zur Dynamik\n\nSynthetischer Lehrtext der Physik auf Seite {pg} zur Mechanik."
            )
        else:
            md_parts.append(
                f"(({pg}))\n\nSynthetischer Lehrtext der Physik auf Seite {pg} zur Mechanik."
            )

    raw_md = "\n\n".join(md_parts)
    cl_path = tmp_path / "synthetic_25p_content_list.json"
    cl_path.write_text(json.dumps(blocks), encoding="utf-8")

    dir_info = {
        "has_any_directory": True,
        "physical_start_page": 272,
        "page_numbers": list(range(272, 297)),
        "toc_entries": [
            {
                "title": "Synthetischer Lehrtext der Physik auf Seite 272",
                "clean_title": "Synthetischer Lehrtext der Physik auf Seite 272",
                "page": 272,
                "level": 2,
            }
        ],
        "figure_entries": [],
        "table_entries": [],
        "picture_entries": [],
    }

    result = insert_page_numbers_from_metadata(
        raw_md,
        str(cl_path),
        pages_str="272-296",
        directory_info=dir_info,
    )

    found_markers = [int(m) for m in re.findall(r"\(\((\d+)\)\)", result)]
    assert found_markers == list(range(272, 297))
    assert "((297))" not in result
    assert "((298))" not in result
    assert "#### ((294))" not in result
    assert "### ((295))" not in result
    assert "### Abschnitt zur Dynamik" in result
    assert not re.search(r"(?m)^[ \t]*#{1,6}[ \t]*$", result)


def test_apply_directory_page_numbers_deduplicates_and_bounds_markers():
    """Verifies that apply_directory_page_numbers deduplicates consecutive identical
    page markers and respects max_pages / known_pages upper bounds.
    """
    dir_info = {
        "has_any_directory": True,
        "physical_start_page": 272,
        "page_numbers": [272, 273, 274],
        "toc_entries": [
            {
                "title": "Kapitel 10 Thermodynamik",
                "clean_title": "Kapitel 10 Thermodynamik",
                "page": 272,
                "level": 1,
            }
        ],
        "figure_entries": [],
        "table_entries": [],
        "picture_entries": [],
    }
    md = (
        "((272))\n\n"
        "# Kapitel 10 Thermodynamik\n\n"
        "((273))\n\n"
        "####\n\n"
        "#### ((273))\n\n"
        "Zweite Seite.\n\n"
        "### ((274)) Unterabschnitt Wärme\n\n"
        "Dritte Seite.\n"
    )
    repaired = apply_directory_page_numbers(md, dir_info, max_pages=3)
    markers = [int(m) for m in re.findall(r"\(\((\d+)\)\)", repaired)]
    assert markers == [272, 273, 274]
    assert "((275))" not in repaired
    assert "### Unterabschnitt Wärme" in repaired
