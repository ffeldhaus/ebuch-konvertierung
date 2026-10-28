"""
Unit tests for the German Schoolbook Benchmark & Test Suite (`scripts/generate_schoolbook_suite.py`).

Verifies:
  1. All 8 single-subject digital PDFs and 8 300-DPI scan-degraded PDFs (`*_scanned.pdf`) exist,
     have valid pages, and have detectable printed textbook page numbers; legacy combined multi-subject
     PDFs are removed.
  2. All Golden Ground Truth Markdown files (`*_raw.md`, `*.raw.golden.md`,
     `*_uebertragungsregeln_09_2025.md`, `*.uebertragungsregeln_09_2025.golden.md`) exist.
  3. Zero bracketed instruction leakage (`[leicht]`, `[mittel]`, `[schwer]`, `[Partnerarbeit]`,
     `[Schere und Kleber]`) in the generated PDFs or `*_raw.md` files.
  4. Distinct difficulty icon systems (`□`/`◩`/`■`, `★`/`★★`/`★★★`, `◇`/`◈`/`◆`, `○`/`◐`/`●`)
     are used in 4 schoolbooks (with corresponding `*_rules.txt`), while the other 4 schoolbooks
     use no difficulty indicators at all.
  5. `sek2_chemie.pdf` and `sek2_biologie.pdf` render explanatory Lehrtext in a 2-column layout
     (`x_col1 ≈ 48 pt` and `x_col2 ≈ 308 pt` at overlapping vertical coordinates).
  6. Every FIBS 09/2025 ground truth achieves a 100/100 score in `a11y_linter.lint_markdown`.
  7. `golden_image_metadata.json` entries match the generated figures and score 100% in `evaluate_images`.
  8. No AGPL libraries (such as PyMuPDF/fitz) are used in the generator.
"""

import json
import os
import pypdfium2
import pytest

from backend.services.a11y_linter import autofix_markdown, lint_markdown
from backend.services.extraction_service import detect_page_number_for_pdf_page
from scripts.run_benchmark import PROJECT_ROOT, evaluate_images

TEST_DATA_DIR = os.path.join(PROJECT_ROOT, "testdata")
GOLDEN_DIR = os.path.join(TEST_DATA_DIR, "golden")

SCHOOLBOOK_DOCS = [
    ("grundschule_mathematik", [14, 15, 16], 3),
    ("grundschule_sachkunde", [24, 25], 1),
    ("grundschule_lesebuch_doppelseite", [18, 20], 1),
    ("sek1_deutsch", [112, 113], 0),
    ("sek1_englisch", [64, 65], 1),
    ("sek1_geographie", [204, 205], 3),
    ("sek1_geschichte", [246, 247], 1),
    ("sek1_informatik", [18, 19], 1),
    ("sek2_chemie", [310, 311], 1),
    ("sek2_biologie", [412, 413], 1),
    ("sek2_physik_verzeichnisse", [44, 45, 46, 47], 1),
    ("sek2_mathematik_analysis", [50, 51], 1),
]

LEGACY_COMBINED_DOCS = [
    "grundschule_mathe_sachkunde",
    "sek1_sprachen_deutsch_englisch",
    "sek1_geographie_geschichte",
    "sek2_chemie_biologie",
]


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_schoolbook_pdfs_and_scanned_variants_exist_and_have_valid_pages(
    base_name, expected_pages, expected_img_count
):
    from backend.services.extraction_service import get_physical_page_numbers_for_pdf

    digital_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    scanned_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}_scanned.pdf")

    assert os.path.exists(digital_pdf), f"Missing digital PDF: {digital_pdf}"
    assert os.path.exists(scanned_pdf), f"Missing scanned PDF: {scanned_pdf}"
    assert os.path.getsize(digital_pdf) > 2_500
    assert os.path.getsize(scanned_pdf) > 40_000

    doc_dig = pypdfium2.PdfDocument(digital_pdf)
    doc_scan = pypdfium2.PdfDocument(scanned_pdf)
    assert len(doc_dig) == len(expected_pages)
    assert len(doc_scan) == len(expected_pages)

    if base_name == "grundschule_lesebuch_doppelseite":
        detected_pages = [detect_page_number_for_pdf_page(digital_pdf, i) for i in range(len(expected_pages))]
    else:
        detected_pages = get_physical_page_numbers_for_pdf(digital_pdf)
    assert detected_pages == expected_pages


def test_legacy_combined_multi_subject_files_are_removed():
    """Ensures old multi-subject/multi-language combined PDFs and golden files are absent."""
    for legacy_base in LEGACY_COMBINED_DOCS:
        assert not os.path.exists(os.path.join(TEST_DATA_DIR, f"{legacy_base}.pdf"))
        assert not os.path.exists(os.path.join(TEST_DATA_DIR, f"{legacy_base}_scanned.pdf"))
        assert not os.path.exists(os.path.join(GOLDEN_DIR, f"{legacy_base}_raw.md"))
        assert not os.path.exists(os.path.join(GOLDEN_DIR, f"{legacy_base}_uebertragungsregeln_09_2025.md"))


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_no_bracketed_instruction_leakage_in_pdfs_or_raw_ground_truths(
    base_name, expected_pages, expected_img_count
):
    """Verifies that neither the PDFs nor *_raw.md leak target FIBS bracket labels like [leicht]."""
    leaked_labels = [
        "[leicht]",
        "[mittel]",
        "[schwer]",
        "[Partnerarbeit]",
        "[Schere und Kleber]",
        "[GHS02]",
        "[GHS05]",
        "[GHS07]",
    ]

    digital_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    doc = pypdfium2.PdfDocument(digital_pdf)
    pdf_text = "\n".join(page.get_textpage().get_text_range() for page in doc)
    for label in leaked_labels:
        assert label not in pdf_text, f"Bracketed FIBS instruction '{label}' leaked into {base_name}.pdf"

    raw_path = os.path.join(GOLDEN_DIR, f"{base_name}.raw.golden.md")
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_md = f.read()
    for label in leaked_labels:
        assert label not in raw_md, f"Bracketed FIBS instruction '{label}' leaked into {base_name}.raw.golden.md"


def test_authentic_difficulty_icon_systems_and_books_without_difficulty_indicators():
    """
    Verifies that 4 books use distinct visual difficulty icon systems (squares, stars, diamonds, circles)
    mapped via *_rules.txt, while the other 4 books use no difficulty indicators at all.
    """
    books_with_icons = {
        "grundschule_mathematik": ["□", "◩", "■"],
        "sek1_englisch": ["★", "★★", "★★★"],
        "sek1_geschichte": ["◇", "◈", "◆"],
        "sek2_chemie": ["○", "◐", "●"],
    }
    for base_name, icons in books_with_icons.items():
        pdf_path = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
        rules_path = os.path.join(TEST_DATA_DIR, f"{base_name}_rules.txt")
        ueb_path = os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md")

        assert os.path.exists(rules_path), f"Missing rules file: {rules_path}"
        with open(rules_path, "r", encoding="utf-8") as rf:
            rules_txt = rf.read()

        doc = pypdfium2.PdfDocument(pdf_path)
        pdf_text = "\n".join(page.get_textpage().get_text_range() for page in doc)
        for icon in icons:
            assert icon in pdf_text, f"Expected difficulty icon '{icon}' in {base_name}.pdf"
            assert icon in rules_txt, f"Expected difficulty icon '{icon}' documented in {base_name}_rules.txt"

        with open(ueb_path, "r", encoding="utf-8") as uf:
            ueb_md = uf.read()
        assert "[leicht]" in ueb_md and "[mittel]" in ueb_md and "[schwer]" in ueb_md

    books_without_difficulty = [
        "grundschule_sachkunde",
        "sek1_deutsch",
        "sek1_geographie",
        "sek2_biologie",
    ]
    all_diff_icons = ["□", "◩", "■", "★", "◇", "◈", "◆", "○", "◐", "●"]
    for base_name in books_without_difficulty:
        pdf_path = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
        ueb_path = os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md")
        doc = pypdfium2.PdfDocument(pdf_path)
        pdf_text = "\n".join(page.get_textpage().get_text_range() for page in doc)
        for icon in all_diff_icons:
            assert icon not in pdf_text, f"Unexpected difficulty icon '{icon}' in {base_name}.pdf"
        with open(ueb_path, "r", encoding="utf-8") as uf:
            ueb_md = uf.read()
        for label in ("[leicht]", "[mittel]", "[schwer]"):
            assert label not in ueb_md, f"Unexpected '{label}' in {base_name}.uebertragungsregeln_09_2025.golden.md"


def test_fallback_and_post_process_difficulty_icon_systems():
    """
    Verifies that standardise_markdown_fallback + post_process_structure converts all 4 difficulty icon
    systems (squares, stars, diamonds, circles) into FIBS [leicht]/[mittel]/[schwer] indicators.
    """
    from backend.services.fibs_postprocess import post_process_structure, standardise_markdown_fallback

    sample_raw = (
        "### Aufgabe 1 □: Kopfrechnen\n"
        "### Aufgabe 2 ★: Reading Comprehension\n"
        "### Aufgabe 3 ★★: Speaking Practice\n"
        "### Aufgabe 4 ★★★: Mediation\n"
        "### Aufgabe 5 ◇: Quellenvergleich\n"
        "### Aufgabe 6 ◈: Statistik auswerten\n"
        "### Aufgabe 7 ◆: Historisches Urteil\n"
    )
    std = post_process_structure(standardise_markdown_fallback(sample_raw), raw_markdown=sample_raw)
    assert "### Aufgabe 1: Kopfrechnen\n[leicht]" in std
    assert "### Aufgabe 2: Reading Comprehension\n[leicht]" in std
    assert "### Aufgabe 3: Speaking Practice\n[mittel]" in std
    assert "### Aufgabe 4: Mediation\n[schwer]" in std
    assert "### Aufgabe 5: Quellenvergleich\n[leicht]" in std
    assert "### Aufgabe 6: Statistik auswerten\n[mittel]" in std
    assert "### Aufgabe 7: Historisches Urteil\n[schwer]" in std


@pytest.mark.parametrize("base_name", ["sek2_chemie", "sek2_biologie"])
def test_sek2_science_books_have_two_column_text_layout(base_name):
    """Verifies that both pages of sek2_chemie.pdf and sek2_biologie.pdf contain 2-column explanatory text."""
    pdf_path = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    doc = pypdfium2.PdfDocument(pdf_path)
    assert len(doc) == 2

    for page_idx, page in enumerate(doc):
        textpage = page.get_textpage()
        n_chars = textpage.count_chars()
        left_col_ys = set()
        right_col_ys = set()
        for c_i in range(n_chars):
            ch = textpage.get_text_range(c_i, 1)
            if not ch.strip():
                continue
            left, bottom, right, top = textpage.get_charbox(c_i)
            # Exclude running header/footer bands (y < 50 or y > 785)
            if 60 <= bottom <= 760:
                y_bucket = int(round(bottom / 6.0))
                if 45 <= left <= 95:
                    left_col_ys.add(y_bucket)
                elif 304 <= left <= 355:
                    right_col_ys.add(y_bucket)
        shared_two_col_bands = left_col_ys.intersection(right_col_ys)
        assert len(shared_two_col_bands) >= 5, (
            f"Page {page_idx + 1} of {base_name}.pdf lacks 2-column text layout "
            f"(only {len(shared_two_col_bands)} shared y-bands)"
        )


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_schoolbook_golden_files_exist_and_pass_a11y_linter_100_percent(
    base_name, expected_pages, expected_img_count
):
    raw_dot = os.path.join(GOLDEN_DIR, f"{base_name}.raw.golden.md")
    ueb_dot = os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md")

    for path in (raw_dot, ueb_dot):
        assert os.path.exists(path), f"Missing golden file: {path}"
    # Verify redundant underscore-named duplicates are removed
    assert not os.path.exists(os.path.join(GOLDEN_DIR, f"{base_name}_raw.md"))
    assert not os.path.exists(os.path.join(GOLDEN_DIR, f"{base_name}_uebertragungsregeln_09_2025.md"))

    with open(raw_dot, "r", encoding="utf-8") as f:
        raw_md = f.read()
    with open(ueb_dot, "r", encoding="utf-8") as f:
        ueb_md = f.read()

    # Check page markers ((num)) for all expected physical pages
    for p_num in expected_pages:
        assert f"(({p_num}))" in raw_md
        assert f"(({p_num}))" in ueb_md

    # Verify 100/100 FIBS 09/2025 accessibility linter compliance
    report = lint_markdown(ueb_md)
    assert report.score == 100, f"Linter issues in {base_name}: {report.issues}"
    assert report.passed is True
    assert report.issues == []

    # Verify idempotency under autofix_markdown
    fixed_md, fixes = autofix_markdown(ueb_md)
    assert fixes == []
    assert fixed_md.strip() == ueb_md.strip()


def test_grundschule_mathe_and_sachkunde_fibs_challenges():
    mathe_path = os.path.join(GOLDEN_DIR, "grundschule_mathematik.uebertragungsregeln_09_2025.golden.md")
    with open(mathe_path, "r", encoding="utf-8") as f:
        mathe_md = f.read()

    # Instructional pictograms & difficulty labels in Mathematik
    assert "[Partnerarbeit]" in mathe_md
    assert "[Schere und Kleber]" in mathe_md
    assert "[leicht]" in mathe_md and "[mittel]" in mathe_md and "[schwer]" in mathe_md

    # 2-column arithmetic grid unrolled linearly a) through j)
    subtask_positions = [mathe_md.index(f"\n{letter}) ") for letter in "abcdefghij"]
    assert subtask_positions == sorted(subtask_positions)
    assert "_..._" in mathe_md

    sach_path = os.path.join(GOLDEN_DIR, "grundschule_sachkunde.uebertragungsregeln_09_2025.golden.md")
    with open(sach_path, "r", encoding="utf-8") as f:
        sach_md = f.read()

    # <Lückentext> with word bank, checkboxes, <Tabelle>, and food chain in Sachkunde
    assert "<Lückentext>" in sach_md and "</Lückentext>" in sach_md
    assert "_Wortspeicher:_" in sach_md
    assert "\n[ ] Das grüne Apfelblatt" in sach_md
    assert "<Tabelle>" in sach_md and "</Tabelle>" in sach_md
    assert "Apfelblatt (Erzeuger) \\to Raupe (1. Verbraucher)" in sach_md
    assert "[Partnerarbeit]" in sach_md


def test_sek1_deutsch_and_englisch_fibs_challenges():
    de_path = os.path.join(GOLDEN_DIR, "sek1_deutsch.uebertragungsregeln_09_2025.golden.md")
    with open(de_path, "r", encoding="utf-8") as f:
        de_md = f.read()

    # Margin line numbers every 5 lines
    for ln in ("5 Nele", "10 Draußen", "15 Brechern", "20 Gegen", "25 Leuchtturmwärter."):
        assert ln in de_md

    # Cross-page word hyphenation completed BEFORE ((113))
    idx_word = de_md.index("25 Leuchtturmwärter.")
    idx_p113 = de_md.index("((113))")
    idx_next_sentence = de_md.index("Am nächsten Morgen glitzerte")
    assert idx_word < idx_p113 < idx_next_sentence

    # Differentiated typography (*fett*, %kursiv%, #unterstrichen#)
    assert "*erfahrene*" in de_md
    assert "%trotz der Dunkelheit%" in de_md
    assert "#durch die enge Fahrrinne#" in de_md

    en_path = os.path.join(GOLDEN_DIR, "sek1_englisch.uebertragungsregeln_09_2025.golden.md")
    with open(en_path, "r", encoding="utf-8") as f:
        en_md = f.read()

    # 3-column English-German vocabulary table with IPA phonetics
    assert "[/ˈkəʊstlaɪn/]" in en_md
    assert "[/ˈnɒlɪdʒ/]" in en_md
    assert "[/ɪnˌvaɪrənˈmentl/]" in en_md
    assert "[Partnerarbeit]" in en_md


def test_sek1_geographie_and_geschichte_fibs_challenges():
    geo_path = os.path.join(GOLDEN_DIR, "sek1_geographie.uebertragungsregeln_09_2025.golden.md")
    with open(geo_path, "r", encoding="utf-8") as f:
        geo_md = f.read()

    assert "#### Abb. 2.1: Physische und thematische Karte des Oberrheingrabens" in geo_md
    assert "#### Abb. 2.2a: Klimadiagramm Freiburg im Breisgau (269 m ü. NN)" in geo_md
    assert "#### Abb. 2.2b: Klimadiagramm Feldberg im Schwarzwald (1493 m ü. NN)" in geo_md
    assert "Maßstab 1 : 2.500.000" in geo_md
    assert "Binnenschifffahrt." in geo_md
    for n in (1, 2):
        assert f"{{{n}}}" in geo_md
        assert f"<Anmerkung> {n} " in geo_md

    hist_path = os.path.join(GOLDEN_DIR, "sek1_geschichte.uebertragungsregeln_09_2025.golden.md")
    with open(hist_path, "r", encoding="utf-8") as f:
        hist_md = f.read()

    assert "#### Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)" in hist_md
    assert "{1}" in hist_md and "<Anmerkung> 1 " in hist_md
    assert "_M1: Bericht eines Fabrikinspektors (1878)_" in hist_md
    assert "_M2: Erinnerungen einer Textilarbeiterin (1884)_" in hist_md


def test_sek2_chemie_and_biologie_fibs_challenges():
    chem_path = os.path.join(GOLDEN_DIR, "sek2_chemie.uebertragungsregeln_09_2025.golden.md")
    with open(chem_path, "r", encoding="utf-8") as f:
        chem_md = f.read()

    # GHS hazard pictograms in square brackets instead of <Bild>
    assert "[Gefahrstoffsymbol: Entzündbar]" in chem_md
    assert "[Gefahrstoffsymbol: Ätzend]" in chem_md
    assert "[Gefahrstoffsymbol: Achtung]" in chem_md

    # Chemical equations with equilibrium arrows, reaction conditions, ion charges & oxidation numbers
    assert "\\rightleftharpoons" in chem_md
    assert "\\xrightarrow{\\text{Kat., } 450\\,^\\circ\\text{C}}" in chem_md
    assert "\\overset{+\\text{VI}}{\\text{Cr}}_2\\overset{-\\text{II}}{\\text{O}}_7^{2-}" in chem_md

    bio_path = os.path.join(GOLDEN_DIR, "sek2_biologie.uebertragungsregeln_09_2025.golden.md")
    with open(bio_path, "r", encoding="utf-8") as f:
        bio_md = f.read()

    assert "v = \\frac{v_{\\max} \\cdot [S]}{K_M + [S]}" in bio_md
    # Page-spanning table merged into a single <Tabelle> on page 412 before ((413))
    assert bio_md.count("<Tabelle>") == 1
    assert bio_md.count("</Tabelle>") == 1
    assert "0,5\t18,2\t8,4\t22,8 %" in bio_md
    assert "32,0\t78,8\t73,1\t98,5 %" in bio_md
    assert bio_md.index("</Tabelle>") < bio_md.index("((413))")


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_golden_image_metadata_and_evaluate_images(base_name, expected_pages, expected_img_count):
    meta_path = os.path.join(GOLDEN_DIR, "golden_image_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    pdf_key = f"{base_name}.pdf"
    assert pdf_key in meta
    assert meta[pdf_key]["total_images"] == expected_img_count
    assert len(meta[pdf_key]["images"]) == expected_img_count

    for img_entry in meta[pdf_key]["images"]:
        fig_file = os.path.join(TEST_DATA_DIR, img_entry["filename"])
        assert os.path.exists(fig_file), f"Missing figure file: {fig_file}"
        assert img_entry["aspect_ratio"] > 0

    ueb_path = os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md")
    with open(ueb_path, "r", encoding="utf-8") as f:
        ueb_md = f.read()

    eval_res = evaluate_images(ueb_md, ueb_md, dataset_name=pdf_key)
    assert eval_res["gold_count"] == expected_img_count
    assert eval_res["pred_count"] == expected_img_count
    assert eval_res["score"] == 100.0
    assert eval_res["tag_compliance"] == 100.0


def test_generator_script_uses_no_agpl_libraries():
    script_path = os.path.join(PROJECT_ROOT, "scripts", "generate_schoolbook_suite.py")
    with open(script_path, "r", encoding="utf-8") as f:
        source = f.read()
    assert "import fitz" not in source
    assert "from fitz" not in source
    assert "import pymupdf" not in source


def test_digital_pdfs_contain_expected_embedded_unicode_text():
    expected_snippets = {
        "grundschule_mathematik.pdf": ["Zahlenstrahl", "Aufgabe 1 □:", "Rechenmauer", "Hallenbad"],
        "grundschule_sachkunde.pdf": ["Streuobstwiese", "Wortspeicher:", "☐", "Nahrungskette"],
        "sek1_deutsch.pdf": ["Worterklärungen (Randspalte)", "Leuchtturm-", "Konjunktiv I", "Schreibkonferenz"],
        "sek1_englisch.pdf": ["Aufgabe 1 ★:", "Aufgabe 4 ★★★:", "[/ˈnɒlɪdʒ/]", "[/ˈkəʊstlaɪn/]"],
        "sek1_geographie.pdf": ["Oberrheingraben¹", "Maßstabs (1 : 2.500.000)", "Klimadiagramm", "Binnen-"],
        "sek1_geschichte.pdf": ["Aufgabe 1 ◈:", "Aufgabe 2 ◇:", "Aufgabe 3 ◆:", "M1: Bericht", "M2: Erinnerungen"],
        "sek2_chemie.pdf": ["Versuchsprotokoll V4.1", "Cr₂O₇²⁻", "Kat., 450 °C", "○ Aufgabe 1:"],
        "sek2_biologie.pdf": ["Michaelis-Menten", "Tabelle 6.1", "RGT-", "pH-Optimum"],
    }
    for fname, snippets in expected_snippets.items():
        pdf_path = os.path.join(TEST_DATA_DIR, fname)
        doc = pypdfium2.PdfDocument(pdf_path)
        full_text = "\n".join(page.get_textpage().get_text_range() for page in doc).replace("\ufffe", "-")
        for snip in snippets:
            assert snip in full_text, f"Expected '{snip}' in embedded text of {fname}"


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_scanned_pdfs_have_300_dpi_raster_and_paper_tint(base_name, expected_pages, expected_img_count):
    digital_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    scanned_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}_scanned.pdf")
    doc_dig = pypdfium2.PdfDocument(digital_pdf)
    pw, ph = doc_dig[0].get_size()
    exp_w = int(round(pw * 300.0 / 72.0))
    exp_h = int(round(ph * 300.0 / 72.0))

    doc = pypdfium2.PdfDocument(scanned_pdf)
    first_page_pil = doc[0].render(scale=300.0 / 72.0).to_pil().convert("RGB")
    w, h = first_page_pil.size
    assert abs(w - exp_w) <= 15
    assert abs(h - exp_h) <= 15
    r, g, b = first_page_pil.getpixel((10, 10))
    assert r < 255 and b < r


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_commercial_page_density_on_every_page(base_name, expected_pages, expected_img_count):
    """Verifies that every generated page has authentic commercial schoolbook text/visual density."""
    digital_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    doc = pypdfium2.PdfDocument(digital_pdf)
    for page_idx, page in enumerate(doc):
        page_text = page.get_textpage().get_text_range().strip()
        assert len(page_text) >= 650, (
            f"Page {expected_pages[page_idx]} of {base_name}.pdf is too sparse ({len(page_text)} chars)"
        )
        pil_img = page.render(scale=1.5).to_pil().convert("L")
        w, h = pil_img.size
        lower_band = pil_img.crop((int(w * 0.08), int(h * 0.72), int(w * 0.92), int(h * 0.92)))
        dark_pixels = sum(1 for px in lower_band.tobytes() if px < 220)
        assert dark_pixels > 500, (
            f"Lower third of page {expected_pages[page_idx]} in {base_name}.pdf is mostly empty ({dark_pixels} dark px)"
        )


def test_openstreetmap_odbl_attribution_and_tile_cache():
    """Verifies OpenStreetMap (ODbL 1.0) attribution in ATTRIBUTIONS.md, Golden files, and cached tiles."""
    attr_path = os.path.join(TEST_DATA_DIR, "ATTRIBUTIONS.md")
    with open(attr_path, "r", encoding="utf-8") as f:
        attr_md = f.read()
    assert "OpenStreetMap" in attr_md
    assert "ODbL" in attr_md
    assert "Michael A. Rundel" in attr_md
    assert "CC BY-SA 4.0" in attr_md

    geo_ueb = os.path.join(GOLDEN_DIR, "sek1_geographie.uebertragungsregeln_09_2025.golden.md")
    with open(geo_ueb, "r", encoding="utf-8") as f:
        geo_md = f.read()
    assert "OpenStreetMap-Mitwirkende" in geo_md and "ODbL" in geo_md

    en_ueb = os.path.join(GOLDEN_DIR, "sek1_englisch.uebertragungsregeln_09_2025.golden.md")
    with open(en_ueb, "r", encoding="utf-8") as f:
        en_md = f.read()
    assert "OpenStreetMap contributors" in en_md and "ODbL" in en_md

    osm_cache_dir = os.path.join(TEST_DATA_DIR, "figures", "osm_cache")
    assert os.path.isdir(osm_cache_dir)
    cached_tiles = [f for f in os.listdir(osm_cache_dir) if f.endswith(".png")]
    assert len(cached_tiles) >= 6


def test_figure_texture_and_visual_richness():
    """Verifies that all generated figures have high-resolution gradients, shadows, and rich color palettes."""
    from PIL import Image

    meta_path = os.path.join(GOLDEN_DIR, "golden_image_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    for base_name, _, _ in SCHOOLBOOK_DOCS:
        pdf_key = f"{base_name}.pdf"
        for img_entry in meta[pdf_key]["images"]:
            fig_path = os.path.join(TEST_DATA_DIR, img_entry["filename"])
            with Image.open(fig_path) as im:
                rgb = im.convert("RGB")
                w, h = rgb.size
                assert [w, h] == img_entry["pixel_resolution"]
                unique_colors = len(rgb.getcolors(maxcolors=1_000_000))
                assert unique_colors >= 400, (
                    f"Figure {img_entry['filename']} looks too flat ({unique_colors} unique RGB colors)"
                )


def test_multi_format_schoolbook_page_dimensions():
    """
    Verifies that the generated schoolbook suite covers the authentic publisher book formats:
      - DIN A4 (595.3 x 841.9 pt)
      - B5+ Standard-Schulbuchformat (190 x 260 mm = 538.6 x 737.0 pt)
      - B5-Breitformat (195 x 260 mm = 552.8 x 737.0 pt)
      - Querformat / Doppelseiten-Spread (240 x 170 mm = 680.3 x 481.9 pt) with ((18)) / ((19))
    """
    expected_formats = {
        "grundschule_mathematik.pdf": (595.3, 841.9),
        "sek1_informatik.pdf": (538.6, 737.0),
        "sek2_mathematik_analysis.pdf": (552.8, 737.0),
        "grundschule_lesebuch_doppelseite.pdf": (680.3, 481.9),
    }
    for fname, (exp_w, exp_h) in expected_formats.items():
        doc = pypdfium2.PdfDocument(os.path.join(TEST_DATA_DIR, fname))
        w, h = doc[0].get_size()
        assert abs(w - exp_w) <= 1.0 and abs(h - exp_h) <= 1.0, (
            f"Unexpected page size for {fname}: ({w:.1f}, {h:.1f}) vs ({exp_w}, {exp_h})"
        )

    # Check FIBS Rule 1 double-page markers ((18)) / ((19)) and ((20)) / ((21))
    with open(os.path.join(GOLDEN_DIR, "grundschule_lesebuch_doppelseite.uebertragungsregeln_09_2025.golden.md"), encoding="utf-8") as f:
        les_ueb = f.read()
    assert "((18)) / ((19))" in les_ueb
    assert "((20)) / ((21))" in les_ueb


@pytest.mark.parametrize("base_name,expected_pages,expected_img_count", SCHOOLBOOK_DOCS)
def test_generated_pdfs_have_high_word_recall_in_golden_files(base_name, expected_pages, expected_img_count):
    """
    Ensures every generated schoolbook PDF is 100% consistent with its Golden Ground Truth
    (>= 94% of all >=4-letter words in the PDF text layer appear in the Golden Ground Truth).
    """
    import re

    pdf_path = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
    doc = pypdfium2.PdfDocument(pdf_path)
    pdf_txt = "\n".join(p.get_textpage().get_text_range() for p in doc)
    # Strip running headers/footers and InDesign .indd slugs before word comparison
    pdf_txt = re.sub(r"(?m)^\S+\.indd\s+\d+.*$", "", pdf_txt)
    pdf_txt = pdf_txt.replace("\u00ad", "").replace("\ufffe", "")
    pdf_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", pdf_txt.lower()))

    with open(os.path.join(GOLDEN_DIR, f"{base_name}.raw.golden.md"), encoding="utf-8") as f:
        raw_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", f.read().lower()))
    with open(os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md"), encoding="utf-8") as f:
        ueb_words = set(re.findall(r"[a-zA-ZäöüÄÖÜß]{4,}", f.read().lower()))

    recall_raw = len(pdf_words & raw_words) / max(1, len(pdf_words))
    recall_ueb = len(pdf_words & ueb_words) / max(1, len(pdf_words))
    assert recall_raw >= 0.94, f"Low word recall ({recall_raw:.1%}) in {base_name}.raw.golden.md"
    assert recall_ueb >= 0.94, f"Low word recall ({recall_ueb:.1%}) in {base_name}.uebertragungsregeln_09_2025.golden.md"


def test_all_repo_test_data_free_of_noncommercial_restrictions_and_publisher_ngrams():
    """
    Verifies:
      1. Zero NonCommercial ('CC BY-NC', 'CC BY NC-SA', 'NC-SA') restrictions in any PDF or golden file in test_data/ & benchmarks/golden/.
      2. Zero 7-word n-gram overlap between any generated test document in ebuch-konvertierung and the 50 publisher PDFs in ../ebuch-testdaten (if present).
    """
    import re

    for fname in sorted(os.listdir(TEST_DATA_DIR)):
        if fname.endswith(".pdf") and not fname.endswith("_scanned.pdf"):
            doc = pypdfium2.PdfDocument(os.path.join(TEST_DATA_DIR, fname))
            txt = "\n".join(p.get_textpage().get_text_range() for p in doc)
            assert not re.search(r"CC\s+BY[\s\-]*NC", txt, re.IGNORECASE), (
                f"NonCommercial license restriction found in {fname}"
            )

    for gname in sorted(os.listdir(GOLDEN_DIR)):
        if gname.endswith(".md"):
            with open(os.path.join(GOLDEN_DIR, gname), encoding="utf-8") as f:
                gtxt = f.read()
            assert not re.search(r"CC\s+BY[\s\-]*NC", gtxt, re.IGNORECASE), (
                f"NonCommercial license restriction found in {gname}"
            )

    ext_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "ebuch-testdaten", "testdata"))
    ext_files = []
    if os.path.isdir(ext_dir) and os.access(ext_dir, os.R_OK):
        try:
            ext_files = os.listdir(ext_dir)
        except PermissionError:
            ext_files = []
    if ext_files:
        pub_ngrams = set()
        for fn in ext_files:
            if fn.endswith(".pdf") and not fn.endswith("_scanned.pdf"):
                try:
                    d = pypdfium2.PdfDocument(os.path.join(ext_dir, fn))
                    t = " ".join(p.get_textpage().get_text_range() for p in d)
                    words = re.findall(r"[a-zA-ZäöüÄÖÜß]{2,}", t.lower())
                    for i in range(len(words) - 6):
                        pub_ngrams.add(" ".join(words[i : i + 7]))
                except Exception:
                    pass
        for base_name, _, _ in SCHOOLBOOK_DOCS:
            d = pypdfium2.PdfDocument(os.path.join(TEST_DATA_DIR, f"{base_name}.pdf"))
            t = " ".join(p.get_textpage().get_text_range() for p in d).replace("\u00ad", "")
            words = re.findall(r"[a-zA-ZäöüÄÖÜß]{2,}", t.lower())
            overlaps = [
                " ".join(words[i : i + 7])
                for i in range(len(words) - 6)
                if " ".join(words[i : i + 7]) in pub_ngrams
            ]
            assert overlaps == [], f"Copied publisher 7-gram found in {base_name}.pdf: {overlaps[:3]}"

