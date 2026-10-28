import os
import re
import json
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from backend.services.fibs_postprocess import standardise_markdown_fallback
from backend.services.llm_service import describe_markdown_images
from backend.services.vlm_describer import main as vlm_describer_main, parse_vlm_description


def test_describe_markdown_images_with_local_images(tmp_path):
    # Create mock images directory and mock image file
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    img_file = images_dir / "picture_0_test.png"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(img_file)

    raw_md = "# Kapitel 1\n\n![](images/picture_0_test.png)\n\nFließtext."

    with patch("backend.services.llm_service.describe_image") as mock_desc:
        mock_desc.return_value = parse_vlm_description("Ein blaues Quadrat als Testgrafik.")
        res = describe_markdown_images(raw_md, str(images_dir))
        assert "<Bild> Abbildung:\nBeschreibung: Ein blaues Quadrat als Testgrafik.\n</Bild>" in res
        assert "![](images/picture_0_test.png)" not in res


def test_describe_markdown_images_structured_vlm_answer(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    Image.new("RGB", (60, 60), color="green").save(images_dir / "d.png")
    raw_md = "Absatz.\n\n![](images/d.png)\n\nAbb. 1 Ablauf eines Versuchs"
    answer = parse_vlm_description(
        "BILDART: Flussdiagramm\nTEXT_IM_BILD: ja\nDEKORATIV: nein\nBESCHREIBUNG:\nStart \\to Messen \\to Ende"
    )
    with patch("backend.services.llm_service.describe_image", return_value=answer):
        res = describe_markdown_images(raw_md, str(images_dir))
    assert "<Bild> Flussdiagramm:\nBeschreibung mit Bildtext: Start \\to Messen \\to Ende\n</Bild>" in res


def test_describe_markdown_images_drops_decorative_without_caption(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    Image.new("RGB", (60, 60), color="yellow").save(images_dir / "deko.png")
    raw_md = "Erster Absatz.\n\n![](images/deko.png)\n\nZweiter Absatz."
    answer = parse_vlm_description(
        "BILDART: Zeichnung\nTEXT_IM_BILD: nein\nDEKORATIV: ja\nBESCHREIBUNG:\nEine geschwungene Zierlinie."
    )
    with patch("backend.services.llm_service.describe_image", return_value=answer):
        res = describe_markdown_images(raw_md, str(images_dir))
    assert "<Bild>" not in res
    assert "deko.png" not in res
    assert "Erster Absatz." in res and "Zweiter Absatz." in res


def test_describe_markdown_images_fallback_when_image_missing(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()

    raw_md = "# Kapitel 1\n\n![Physik-Versuch](images/missing.png)\n\nText."
    with patch("backend.services.llm_service.describe_image", return_value=None):
        res = describe_markdown_images(raw_md, str(images_dir))
        assert "<Bild> Abbildung:\nBeschreibung: Physik-Versuch\n</Bild>" in res


def test_standardise_markdown_fallback_preserves_existing_bild_tags():
    raw_md = "# Titel\n\n<Bild> Zeichnung: Ein Prisma bricht weißes Licht in Spektralfarben. </Bild>\n\nText."
    std = standardise_markdown_fallback(raw_md, "uebertragungsregeln_09_2025")
    assert "<Bild> Zeichnung: Ein Prisma bricht weißes Licht in Spektralfarben. </Bild>" in std


def test_infinity_extractor_embedded_image_extraction(tmp_path):
    pdf_source = "testdata/test_educational.pdf"
    if not os.path.exists(pdf_source):
        pytest.skip("test_educational.pdf not found in testdata")

    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_source)
    extracted_images = []
    
    images_dir = tmp_path / "images"
    images_dir.mkdir()

    for p_idx, page in enumerate(pdf):
        for obj_idx, obj in enumerate(page.get_objects()):
            if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                bitmap = obj.get_bitmap()
                img_pil = bitmap.to_pil()
                if img_pil.width >= 30 and img_pil.height >= 30:
                    fn = f"picture_{p_idx}_{obj_idx}.png"
                    img_pil.save(images_dir / fn, format="PNG")
                    extracted_images.append(fn)

    assert len(extracted_images) > 0
    assert (images_dir / extracted_images[0]).exists()


def test_vlm_describer_empty_args_handling(capsys):
    with patch("sys.argv", ["vlm_describer.py", "--images", ""]):
        vlm_describer_main()
        captured = capsys.readouterr()
        assert "---JSON_START---" in captured.out
        assert "{}" in captured.out
        assert "---JSON_END---" in captured.out


def test_describe_markdown_images_with_skip_descriptions(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    img_file = images_dir / "picture_0.png"
    Image.new("RGB", (100, 100), color="red").save(img_file)

    raw_md = "# Kapitel\n\n![Optischer Versuchsaufbau](images/picture_0.png)\n\nFließtext."
    # With skip_descriptions=True, describe_image should NEVER be called
    with patch("backend.services.llm_service.describe_image") as mock_desc:
        res = describe_markdown_images(raw_md, str(images_dir), skip_descriptions=True)
        mock_desc.assert_not_called()
        assert "<Bild> Abbildung:\nBeschreibung: Optischer Versuchsaufbau\n</Bild>" in res


def test_evaluate_images_with_golden_metadata():
    from scripts.run_benchmark import evaluate_images, load_golden_image_metadata
    
    meta = load_golden_image_metadata()
    assert "test_educational.pdf" in meta
    assert meta["test_educational.pdf"]["total_images"] == 7
    
    pred_md = (
        "((45))\n\n# Physik\n\n<Bild> Zeichnung:\nBeschreibung mit Bildtext: Versuchsaufbau\n</Bild>\n\n"
        "((47))\n\n<Bild> Zeichnung:\nBeschreibung mit Bildtext: Prisma vorne\n</Bild>\n\n"
        "<Bild> Diagramm:\nBeschreibung mit Bildtext: Prisma Seite\n</Bild>\n\n"
        "<Bild> Foto:\nBeschreibung mit Bildtext: Laborversuch\n</Bild>\n\n"
        "<Bild> Zeichnung:\nBeschreibung mit Bildtext: Spiegel\n</Bild>\n\n"
        "<Bild> Foto:\nBeschreibung mit Bildtext: Laser im Wasser\n</Bild>\n\n"
        "((48))\n\n<Bild> Diagramm:\nBeschreibung mit Bildtext: Totalreflexion\n</Bild>"
    )
    gold_md = (
        "((45))\n\n# Physik\n\n![Versuchsaufbau](figures/dispersion_prisma.png)\n\n"
        "((47))\n\n![Prisma vorne](figures/prisma_front.png)\n\n"
        "![Prisma Seite](figures/prisma_side.png)\n\n"
        "![Laborversuch](figures/prisma_lab_photo.png)\n\n"
        "![Spiegel](figures/reflexion_spiegel.png)\n\n"
        "![Laser im Wasser](figures/brechung_wasser_photo.png)\n\n"
        "((48))\n\n![Totalreflexion](figures/strahlengang.png)"
    )
    
    eval_res = evaluate_images(pred_md, gold_md, dataset_name="test_educational.pdf")
    assert eval_res["score"] >= 90.0
    assert eval_res["gold_count"] == 7
    assert eval_res["pred_count"] == 7
    assert eval_res["matched_count"] == 7
