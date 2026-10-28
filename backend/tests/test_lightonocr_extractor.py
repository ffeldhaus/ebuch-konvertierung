import os
import tempfile
from PIL import Image
import pytest

from backend.services.lightonocr_extractor import (
    build_lightonocr_messages,
    ensure_lightonocr_cache_enabled,
    parse_grounding_blocks,
    post_process_lightonocr_page,
)


def test_build_lightonocr_messages_plain_and_grounding():
    # Plain mode MUST NOT include any custom text instruction (out-of-distribution per LightOnOCR-3 spec)
    msgs_plain = build_lightonocr_messages(mode="plain")
    assert len(msgs_plain) == 1
    assert msgs_plain[0]["role"] == "user"
    assert msgs_plain[0]["content"] == [{"type": "image"}]

    # Grounding mode MUST use the exact single word 'grounding'
    msgs_grounding = build_lightonocr_messages(mode="grounding")
    assert len(msgs_grounding) == 1
    assert msgs_grounding[0]["content"] == [
        {"type": "image"},
        {"type": "text", "text": "grounding"},
    ]


def test_parse_grounding_blocks_filters_headers_preserves_footnotes_and_merges_text_plus():
    raw_grounding = (
        "![header](89,15,834,33) 502 KAPITEL 11. OPTIK\n\n"
        "![title](91,60,400,85) ### 11.6.3 Brechungsindex\n\n"
        "![text](91,100,835,160) Der Brechungsindex beschreibt das Verhältnis der Lichtgeschwindigkeiten und wird\n\n"
        "![image](200,180,600,380)\n\n"
        "![caption](200,390,600,410) Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem\n\n"
        "![text+](91,430,835,480) in verschiedenen optischen Medien gemessen.\n\n"
        "![footnote](91,880,835,910) 1 Optisches Dichte-Experiment: Beschrieben von Snellius 1621.\n\n"
        "![page_number](450,950,480,970) 502"
    )
    img = Image.new("RGB", (800, 1000), color=(255, 255, 255))
    with tempfile.TemporaryDirectory() as tmpdir:
        cleaned_md, cropped_files = parse_grounding_blocks(
            raw_grounding,
            page_pil_img=img,
            images_dir=tmpdir,
            page_idx=2,
            has_existing_images=False,
        )
        # Running header and page_number stripped
        assert "502 KAPITEL 11. OPTIK" not in cleaned_md
        assert "\n502" not in cleaned_md
        # Title preserved
        assert "### 11.6.3 Brechungsindex" in cleaned_md
        # text and text+ merged across intermediate image/caption
        assert "wird in verschiedenen optischen Medien gemessen." in cleaned_md
        # Footnote strictly preserved for E-Buch
        assert "1 Optisches Dichte-Experiment: Beschrieben von Snellius 1621." in cleaned_md
        # Image cropped from bbox fallback
        assert len(cropped_files) == 1
        assert os.path.exists(os.path.join(tmpdir, cropped_files[0]))


def test_post_process_lightonocr_page_converts_html_tables_and_matches_images():
    raw_page = (
        "502\n\n"
        "KAPITEL II. OPTIK\n\n"
        "![image](image_1.png)\n\n"
        "*Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem*\n\n"
        "### 11.6.3 Brechungsindex\n\n"
        "Formel mit \\$c_0\\$:\n\n"
        "$$\n"
        "n = \\frac{c_0}{c_M} \\tag{11.1}\n"
        "$$\n\n"
        "<table>\n"
        "  <thead><tr><th>Material</th><th>Brechungsindex $n$</th></tr></thead>\n"
        "  <tbody><tr><td>Vakuum</td><td>1</td></tr><tr><td>Wasser</td><td>1,33</td></tr></tbody>\n"
        "</table>\n\n"
        "Seite 502"
    )
    res = post_process_lightonocr_page(
        raw_page,
        page_images=["picture_2_0_abc123.png"],
        phys_num=502,
        page_tables=[],
    )
    assert "((502))" in res
    assert "![](images/picture_2_0_abc123.png)" in res
    assert "image_1.png" not in res
    assert "$c_0$" in res
    assert "\\$c_0\\$" not in res
    assert "| Material | Brechungsindex $n$ |" in res
    assert "| Vakuum | 1 |" in res
    assert "<table>" not in res
    assert "Seite 502" not in res


def test_ensure_lightonocr_cache_enabled(tmp_path):
    cfg_file = tmp_path / "config.json"
    gen_file = tmp_path / "generation_config.json"
    cfg_file.write_text('{"use_cache": false, "text_config": {"use_cache": false}}', encoding="utf-8")
    gen_file.write_text('{"use_cache": false}', encoding="utf-8")

    ensure_lightonocr_cache_enabled(str(tmp_path))

    import json
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    gen = json.loads(gen_file.read_text(encoding="utf-8"))
    assert cfg["use_cache"] is True
    assert cfg["text_config"]["use_cache"] is True
    assert gen["use_cache"] is True


def test_post_process_lightonocr_page_strips_two_line_all_caps_running_header():
    raw_page = (
        "FAUST I - TEXTANALYSE\n\n"
        "DEUTSCHUNTERRICHT\n\n"
        "# Literarische Textanalyse: Johann Wolfgang von Goethe - Faust I\n\n"
        "Einleitungstext.\n\n"
        "85   Deutsch Textanalyse"
    )
    res = post_process_lightonocr_page(raw_page, page_images=[], phys_num=85)
    assert "FAUST I - TEXTANALYSE" not in res
    assert "DEUTSCHUNTERRICHT" not in res
    assert "# Literarische Textanalyse: Johann Wolfgang von Goethe - Faust I" in res
    assert "((85))" in res


def test_lightonocr_benchmark_and_service_registration(tmp_path):
    from unittest.mock import MagicMock, patch
    from backend.services.custom_benchmark_service import run_single_engine_extraction
    from scripts.run_benchmark import BENCHMARK_LICENSE_TAGS, run_lightonocr_extraction

    assert "lightonocr" in BENCHMARK_LICENSE_TAGS
    assert "Apache 2.0" in BENCHMARK_LICENSE_TAGS["lightonocr"]
    assert "mineru" not in BENCHMARK_LICENSE_TAGS
    assert "chandra" not in BENCHMARK_LICENSE_TAGS

    out_dir = str(tmp_path / "out")
    with patch("backend.services.custom_benchmark_service.run_lightonocr_extraction") as mock_extract:
        mock_extract.return_value = ("# LightOn Title\n\nBody", 1.8)
        res_md, dur = run_single_engine_extraction("lightonocr", "dummy.pdf", out_dir)
        assert res_md == "# LightOn Title\n\nBody"
        assert dur == 1.8
        mock_extract.assert_called_once_with("dummy.pdf", out_dir, task=None)

    pdf_path = str(tmp_path / "sample.pdf")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sample.md"), "w", encoding="utf-8") as f:
        f.write("# LightOn Page\n\n- Item")

    mock_task = MagicMock()
    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = [
        "Processing pages: 0%| 1/1\n",
        "---STREAM_PAGE_START---\n",
        '{"status": "raw_chunk", "delta": "# LightOn Page"}\n',
        "---STREAM_PAGE_END---\n",
        "Processing pages: 100%| 1/1\n",
        "",
    ]
    mock_proc.wait.return_value = 0
    with patch("subprocess.Popen", return_value=mock_proc):
        content, duration = run_lightonocr_extraction(pdf_path, out_dir, task=mock_task)
        assert "# LightOn Page" in content
        assert duration >= 0.0
        logged_msgs = [call.args[0] for call in mock_task.add_log.call_args_list]
        assert any("Processing pages: 100%| 1/1" in m for m in logged_msgs)
        assert not any("STREAM_PAGE" in m or "raw_chunk" in m for m in logged_msgs)


def test_shared_fuse_vlm_page_with_docling_recovers_flattened_table():
    """Tests 2a unified hybrid fusion: recovers Docling TableFormer structure when VLM flattened a table."""
    from backend.services.extraction_postprocess import fuse_vlm_page_with_docling

    # VLM emitted flattened text for a 3-row table that Docling extracted as a clean pipe table
    vlm_page = (
        "# Optische Medien\n\n"
        "Material Brechungsindex Lichtgeschwindigkeit\n"
        "Vakuum 1,00 300000\n"
        "Wasser 1,33 225000\n"
        "Kronglas 1,52 197000\n\n"
        "Abschlusstext nach der Tabelle."
    )
    docling_tables = [
        "| Material | Brechungsindex | Lichtgeschwindigkeit |\n"
        "|---|---|---|\n"
        "| Vakuum | 1,00 | 300000 |\n"
        "| Wasser | 1,33 | 225000 |\n"
        "| Kronglas | 1,52 | 197000 |"
    ]
    fused = fuse_vlm_page_with_docling(
        vlm_page,
        page_images=[],
        phys_num=12,
        page_tables=docling_tables,
    )
    assert "((12))" in fused
    assert "| Material | Brechungsindex | Lichtgeschwindigkeit |" in fused
    assert "| Kronglas | 1,52 | 197000 |" in fused
    assert "Abschlusstext nach der Tabelle." in fused


def test_render_pdf_page_for_vlm_snaps_to_32px_grid():
    """Tests that render_pdf_page_for_vlm snaps dimensions to exact multiples of 32 (Qwen3-VL patch grid)."""
    from unittest.mock import MagicMock
    from backend.services.pdf_render_service import render_pdf_page_for_vlm

    fake_page = MagicMock()
    # A4-like aspect ratio in PDF points: 595 x 842
    fake_page.get_size.return_value = (595.0, 842.0)
    raw_pil = Image.new("RGB", (1085, 1536), color=(255, 255, 255))
    fake_bitmap = MagicMock()
    fake_bitmap.to_pil.return_value = raw_pil
    fake_page.render.return_value = fake_bitmap

    rendered = render_pdf_page_for_vlm(fake_page, target_longest_edge=1536.0, grid_factor=32)
    w, h = rendered.size
    assert w % 32 == 0
    assert h % 32 == 0
    assert max(w, h) == 1536

