import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from backend.services.extraction_postprocess import (
    clean_markdown_fences,
    fuse_vlm_page_with_docling,
)
from backend.services.custom_benchmark_service import run_single_engine_extraction
from backend.services.fibs_postprocess import post_process_structure
from scripts.run_benchmark import run_infinity_extraction, BENCHMARK_LICENSE_TAGS


def test_clean_markdown_fences():
    """Verifies that wrapping code fences are properly stripped."""
    # Test wrapped markdown fence
    wrapped = "```markdown\n# Heading 1\nSome text\n```"
    assert clean_markdown_fences(wrapped) == "# Heading 1\nSome text"

    # Test generic fence
    generic = "```\n# Heading 1\nSome text\n```"
    assert clean_markdown_fences(generic) == "# Heading 1\nSome text"

    # Test clean markdown without fences
    clean = "# Heading 1\nSome text"
    assert clean_markdown_fences(clean) == "# Heading 1\nSome text"


def test_infinity_parser_benchmark_registration():
    """Verifies Infinity-Parser2-Flash is properly registered in benchmark license metadata."""
    assert "infinity" in BENCHMARK_LICENSE_TAGS
    assert "Apache 2.0" in BENCHMARK_LICENSE_TAGS["infinity"]


def test_run_single_engine_extraction_infinity(tmp_path):
    """Verifies custom benchmark service dispatches to infinity extractor."""
    out_dir = str(tmp_path / "out")
    with patch("backend.services.custom_benchmark_service.run_infinity_extraction") as mock_extract:
        mock_extract.return_value = ("# Extracted Title\n\nContent", 2.5)
        res_md, dur = run_single_engine_extraction("infinity", "dummy.pdf", out_dir)
        assert res_md == "# Extracted Title\n\nContent"
        assert dur == 2.5
        mock_extract.assert_called_once_with("dummy.pdf", out_dir, task=None)


def test_run_infinity_extraction_success(tmp_path):
    """Verifies run_infinity_extraction reads generated markdown on subprocess completion."""
    pdf_path = str(tmp_path / "sample.pdf")
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir, exist_ok=True)
    md_file = os.path.join(out_dir, "sample.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Parsed Page\n\n- Bullet item")

    mock_proc = MagicMock()
    mock_proc.stdout = None
    mock_proc.wait.return_value = 0
    with patch("subprocess.Popen", return_value=mock_proc):
        content, duration = run_infinity_extraction(pdf_path, out_dir)
        assert "# Parsed Page" in content
        assert duration >= 0.0


def test_extract_pdf_pictures_layout_aware(tmp_path):
    from backend.services.infinity_parser_extractor import extract_pdf_pictures_layout_aware

    img_out = str(tmp_path / "extracted_imgs")
    # Test on digital PDF
    if os.path.exists("testdata/test_educational.pdf"):
        res = extract_pdf_pictures_layout_aware("testdata/test_educational.pdf", img_out)
        assert isinstance(res, dict)
        # Should have detected pictures across the document
        total_pics = sum(len(v) for v in res.values())
        assert total_pics >= 7
        # Specifically verify page 3 (index 2) has all 5 images (3 top + 2 bottom)
        assert len(res.get(2, [])) >= 5


def test_post_process_page_markdown_captions_and_image_placement():
    """Verifies that headings on captions are normalized and images are placed right above captions."""
    raw = (
        "## Versuch: Zerlegung durch ein Prisma\n\n"
        "Betrachten wir das nachfolgende Experiment zur Dispersion:\n\n"
        "## Abbildung 4.1: Versuchsaufbau zur optischen Dispersion mit einem Glasprisma.\n\n"
        "Die Abhängigkeit des Brechungsindex $n$ von der Frequenz...\n\n"
        "Seite 45"
    )
    images = ["pic_dispersion.png"]
    processed = fuse_vlm_page_with_docling(raw, images, phys_num=45)

    assert "((45))" in processed
    # Image should be directly above the caption, not at top
    assert "![](images/pic_dispersion.png)\n\nAbbildung 4.1: Versuchsaufbau" in processed
    # Heading ## should have been stripped from the caption
    assert "## Abbildung 4.1" not in processed
    # Running footer 'Seite 45' should be stripped
    assert "Seite 45" not in processed


def test_post_process_page_markdown_multi_image_side_by_side():
    """Verifies that side-by-side images with captions are sequentially placed before each caption."""
    raw = (
        "# Übungen und Schüleraufgaben\n\n"
        "### Abbildung 4.2a: Prisma von vorne (Schematische Zeichnung).\n\n"
        "### Abbildung 4.2b: Strahlengang im Prisma (Diagramm).\n\n"
        "### Abbildung 4.2c: Reales Glasprisma im Labor (Fotoaufnahme).\n\n"
        "Vergleichen Sie die Ausbreitung von Licht:\n\n"
        "### Abbildung 4.3a: Reflexionsgesetz am Spiegel (Illustration).\n\n"
        "### Abbildung 4.3b: Laserstrahl-Lichtbrechung im Wasser (Foto).\n\n"
        "[Seite 47]"
    )
    images = ["img_3a.png", "img_3b.png", "img_3c.png", "img_3d.png", "img_3e.png"]
    processed = fuse_vlm_page_with_docling(raw, images, phys_num=47)

    assert "((47))" in processed
    assert "![](images/img_3a.png)\n\nAbbildung 4.2a: Prisma von vorne" in processed
    assert "![](images/img_3b.png)\n\nAbbildung 4.2b: Strahlengang" in processed
    assert "![](images/img_3c.png)\n\nAbbildung 4.2c: Reales Glasprisma" in processed
    assert "![](images/img_3d.png)\n\nAbbildung 4.3a: Reflexionsgesetz" in processed
    assert "![](images/img_3e.png)\n\nAbbildung 4.3b: Laserstrahl" in processed
    assert "[Seite 47]" not in processed
    assert "### Abbildung" not in processed


def test_post_process_page_markdown_running_headers_and_word_hyphenation():
    """Verifies stripping running top header and joining hyphenated words."""
    raw = (
        "FAUST I - TEXTANALYSE\n\n"
        "Dies ist ein Textabschnitt über Zellkompartimen- ten in biologischen Systemen.\n\n"
        "85   Deutsch Textanalyse"
    )
    processed = fuse_vlm_page_with_docling(raw, [], phys_num=85)

    assert "FAUST I - TEXTANALYSE" not in processed
    assert "Zellkompartimenten" in processed
    assert "85   Deutsch Textanalyse" not in processed
    assert "((85))" in processed


def test_post_process_page_markdown_remaining_images_and_marker_injection():
    """Verifies that remaining images without captions are injected cleanly."""
    # With pre-existing page marker
    raw_with_marker = "((10))\n\n# Kapitel 1\nEinleitungstext."
    res = fuse_vlm_page_with_docling(raw_with_marker, ["standalone1.png", "standalone2.png"], phys_num=10)
    assert "((10))" in res
    assert "![](images/standalone1.png)" in res
    assert "![](images/standalone2.png)" in res

    # Without pre-existing marker
    raw_no_marker = "# Kapitel 2\nWeiterer Text."
    res2 = fuse_vlm_page_with_docling(raw_no_marker, ["standalone3.png"], phys_num=11)
    assert res2.startswith("((11))")
    assert "![](images/standalone3.png)" in res2

    # Inline heading newline expansion in clean_markdown_fences
    inline_headings = "Paragraph text. ## Subheading\nAnother text. ### Deep heading"
    cleaned = clean_markdown_fences(inline_headings)
    assert "\n\n## Subheading" in cleaned
    assert "\n\n### Deep heading" in cleaned


def test_infinity_unextracted_image_placeholder_and_fake_caption_bild():
    """
    Regression test for TODO:
    - 'Infinity-Platzhalter ! [Chemical Structure](#) ergeben leere <Bild>-Blöcke'
    - 'Bildunterschriften ohne extrahiertes Bild werden zu Schein-Bildern'
    """
    # 1. Spaced placeholder '! [Chemical Structure](#)' with an extracted image maps to ![](images/...)
    raw_with_img = "## Reaktionsmechanismus\n\n! [Chemical Structure](#)\n\nAbb. 1: Strukturformel."
    res_with_img = fuse_vlm_page_with_docling(raw_with_img, ["chem_1.png"], phys_num=12)
    assert "![](images/chem_1.png)" in res_with_img
    assert "! [Chemical Structure](#)" not in res_with_img

    # 2. Spaced placeholder '! [Chemical Structure](#)' with NO extracted image becomes <Anmerkung>
    raw_no_img = "## Reaktionsmechanismus\n\n! [Chemical Structure](#)\n\nWeiterer Text."
    res_no_img = fuse_vlm_page_with_docling(raw_no_img, [], phys_num=12)
    assert "<Anmerkung> Abbildung nicht extrahiert: Chemical Structure </Anmerkung>" in res_no_img
    assert "! [Chemical Structure](#)" not in res_no_img

    # 3. post_process_structure unwraps fake <Bild> blocks whose description only repeats a caption
    # when raw_markdown had no extracted images at all
    raw_page_without_images = "((15))\n\n## Optik\n\nAbb. 1: Versuchsaufbau zur Lichtbrechung.\n\nFließtext."
    llm_hallucinated_bild = (
        "((15))\n\n## Optik\n\n"
        "<Bild> Abbildung:\nBeschreibung: Abb. 1: Versuchsaufbau zur Lichtbrechung.\n</Bild>\n\n"
        "Fließtext."
    )
    cleaned_std = post_process_structure(llm_hallucinated_bild, raw_markdown=raw_page_without_images)
    assert "<Bild>" not in cleaned_std
    assert "Abb. 1: Versuchsaufbau zur Lichtbrechung." in cleaned_std



