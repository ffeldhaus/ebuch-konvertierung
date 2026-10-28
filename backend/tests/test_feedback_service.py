"""
Tests for the Feedback mode (feedback_service + /api/feedback/* endpoints).

Covers:
- Loading transfer documents (.md / .docx)
- Programmatic change summary between original and revised transfer
- Copyright guard: redaction of long verbatim passages in the Gemma report
- Prompt construction (no long passages, pattern-oriented output)
- API flow: create job, list jobs, render PDF page, analyze (E2E_MOCK), list/get reports
"""
import io
import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.main import app, FEEDBACK_DIR
from backend.services import feedback_service as fs
from backend.services.fibs_constants import SKIPPED_ANSWER
from backend.services.prompts import (
    PIPELINE_CONTEXT,
    REGION_FINDINGS_PLACEHOLDER,
    build_analysis_prompt,
    build_region_prompt,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_PDF = os.path.join(PROJECT_ROOT, "testdata", "test_educational.pdf")

ORIGINAL_MD = """# Kapitel 1

## Aufgabe

Die Zellmembran umgibt die Zelle und trennt das Zellinnere von der Umgebung ab.

- Punkt eins
- Punkt zwei

<Bild> Abbildung: Abbildung ohne Beschreibung </Bild>
"""

REVISED_MD = """# Kapitel 1

((12))

### Aufgabe 1: Zellaufbau

Die Zellmembran umgibt die Zelle und trennt das Zellinnere von der Umgebung ab.

-\tPunkt eins
-\tPunkt zwei

<Bild> Foto: Mikroskopaufnahme einer Pflanzenzelle mit grüner Zellwand. </Bild>
"""


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests: document loading
# ---------------------------------------------------------------------------

def test_load_transfer_document_markdown(tmp_path):
    p = tmp_path / "rev.md"
    p.write_text(REVISED_MD, encoding="utf-8")
    assert fs.load_transfer_document(str(p)) == REVISED_MD


def test_load_transfer_document_docx_roundtrip(tmp_path):
    from backend.services.docx_service import convert_markdown_to_docx

    docx_path = tmp_path / "rev.docx"
    convert_markdown_to_docx(REVISED_MD, str(docx_path))
    text = fs.load_transfer_document(str(docx_path))
    assert "Aufgabe 1: Zellaufbau" in text
    assert "Zellmembran" in text


def test_load_transfer_document_rejects_unknown_extension(tmp_path):
    p = tmp_path / "rev.exe"
    p.write_bytes(b"\x00")
    with pytest.raises(ValueError):
        fs.load_transfer_document(str(p))


# ---------------------------------------------------------------------------
# Unit tests: change summary
# ---------------------------------------------------------------------------

def test_classify_segment_categories():
    assert "heading" in fs.classify_segment("### Aufgabe 1: Test")
    assert "page_marker" in fs.classify_segment("((12))")
    assert "image" in fs.classify_segment("<Bild> Foto: x </Bild>")
    assert "list" in fs.classify_segment("-\tPunkt")
    assert "math" in fs.classify_segment("<L> x^2 </L>")
    assert "table" in fs.classify_segment("| a | b |")
    assert "frame" in fs.classify_segment("<Rahmen> Info </Rahmen>")
    assert fs.classify_segment("Nur normaler Text.") == ["text"]


def test_compute_change_summary_detects_pattern_categories():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD, snippet_chars=40)
    cats = summary["category_counts"]
    assert cats.get("heading", 0) >= 1
    assert cats.get("page_marker", 0) >= 1
    assert cats.get("image", 0) >= 1
    assert cats.get("list", 0) >= 1
    assert 0.0 < summary["similarity"] < 1.0
    assert summary["hunk_count"] == len(summary["hunks"]) or summary["truncated"]
    # Snippets must stay short (copyright guard for prompt + appendix)
    for h in summary["hunks"]:
        for s in h.removed + h.added:
            assert len(s) <= 41  # 40 chars + ellipsis


def test_compute_change_summary_identical_documents():
    summary = fs.compute_change_summary(ORIGINAL_MD, ORIGINAL_MD)
    assert summary["hunk_count"] == 0
    assert summary["similarity"] == 1.0


def test_compute_change_summary_limits_hunks():
    orig = "\n\n".join(f"Absatz {i} alt" for i in range(100))
    rev = "\n\n".join(f"Absatz {i} neu" for i in range(100))
    summary = fs.compute_change_summary(orig, rev, max_hunks=5)
    assert len(summary["hunks"]) == 5
    assert summary["truncated"] is True


def test_compare_lint_reports_scores():
    cmp = fs.compare_lint_reports(ORIGINAL_MD, REVISED_MD)
    assert "score_original" in cmp and "score_revised" in cmp
    assert isinstance(cmp["rules_fixed_in_revision"], dict)


# ---------------------------------------------------------------------------
# Unit tests: copyright guard
# ---------------------------------------------------------------------------

LONG_SOURCE = (
    "Die Photosynthese ist ein biochemischer Vorgang bei dem Pflanzen mit Hilfe "
    "von Lichtenergie aus Kohlenstoffdioxid und Wasser Zucker und Sauerstoff herstellen."
)


def test_redact_long_passages_removes_verbatim_copy():
    report = f"Problem: Der Absatz \"{LONG_SOURCE}\" wurde falsch formatiert."
    redacted = fs.redact_long_passages(report, [LONG_SOURCE], max_words=10)
    assert "[…]" in redacted
    assert "Kohlenstoffdioxid und Wasser Zucker" not in redacted
    assert redacted.startswith("Problem:")
    assert "wurde falsch formatiert." in redacted


def test_redact_long_passages_keeps_short_examples():
    report = "Beispiel: `Die Photosynthese ist` wird als Überschrift erkannt."
    assert fs.redact_long_passages(report, [LONG_SOURCE], max_words=10) == report


def test_redact_long_passages_without_sources():
    assert fs.redact_long_passages("abc def", [], max_words=3) == "abc def"


# ---------------------------------------------------------------------------
# Unit tests: prompts and mock report
# ---------------------------------------------------------------------------

def test_build_analysis_prompt_contains_rules_and_inputs():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    lint_cmp = fs.compare_lint_reports(ORIGINAL_MD, REVISED_MD)
    prompt = build_analysis_prompt(
        change_summary=summary,
        lint_comparison=lint_cmp,
        feedback_text="Überschriften der Aufgaben sind falsch.",
        task_meta={"engine": "docling", "pages": "45", "original_name": "x.pdf"},
        region_count=1,
    )
    assert "Überschriften der Aufgaben sind falsch." in prompt
    assert REGION_FINDINGS_PLACEHOLDER in prompt
    assert "keine längeren textpassagen" in prompt.lower()
    assert "Muster" in prompt
    assert "docling" in prompt


def test_build_region_prompt_includes_note():
    p = build_region_prompt("Tabelle fehlt", page=45)
    assert "Tabelle fehlt" in p
    assert "45" in p


def test_pipeline_context_matches_system_prompt_conventions():
    """The conventions Gemma receives must not contradict SYSTEM_PROMPTS (no <L> tags,
    standard emphasis _…_, differentiated * / % only when required, multi-line <Bild> format)."""
    ctx = PIPELINE_CONTEXT
    assert "Formeln in <L>" not in ctx
    assert "niemals <L>" in ctx
    assert "$…$" in ctx  # LaTeX delimiters
    assert "_…_" in ctx
    assert "Fett *…*" not in ctx  # * / % are only for necessary differentiation
    assert "Beschreibung mit Bildtext:" in ctx


def test_generate_mock_report_has_sections():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    report = fs.generate_mock_report(summary, "Feedback", ["Tabelle mit 3 Spalten"])
    assert "## Zusammenfassung" in report
    assert "## Fehlermuster" in report
    assert "## Maßnahmen" in report
    assert "## Übersicht" in report
    assert "## Benötigte Testdaten" in report
    assert "**Benötigte Testdaten:**" in report


def test_build_analysis_prompt_requests_overview_and_test_data():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    lint_cmp = fs.compare_lint_reports(ORIGINAL_MD, REVISED_MD)
    prompt = build_analysis_prompt(summary, lint_cmp, "", {"Engine": "docling"}, 0)
    # Fixed section order for readability
    order = ["## Zusammenfassung", "## Übersicht", "## Fehlermuster", "## Maßnahmen für den Coding Assistant",
             "## Benötigte Testdaten", "## Offene Fragen"]
    positions = [prompt.rindex(s) for s in order]
    assert positions == sorted(positions)
    # Per-pattern test data field and OER constraint
    assert "**Benötigte Testdaten:**" in prompt
    assert "OER" in prompt and "ATTRIBUTIONS.md" in prompt
    # Readability rules: no LaTeX in prose, no references to invisible block numbers
    assert "→" in prompt and "LaTeX" in prompt
    assert "Blocknummern" in prompt


def test_normalize_report_markdown_bullets_and_arrows():
    raw = (
        "### Muster 1: Diagramme\n"
        "**Kategorie**: Listen\n"
        "**Häufigkeit:** hoch\n"
        "- **Beispiel:** ALT $\\to$ NEU\n"
        "Text mit $\\rightarrow$ Pfeil und Formel <L> a \\to b </L>\n"
        "| a | b |\n"
    )
    out = fs.normalize_report_markdown(raw)
    assert "- **Kategorie:** Listen" in out
    assert "- **Häufigkeit:** hoch" in out
    assert "- **Beispiel:** ALT → NEU" in out          # existing bullet not doubled
    assert "- - " not in out
    assert "Text mit → Pfeil" in out
    assert "<L> a \\to b </L>" in out                   # E-Buch formulas untouched
    assert "| a | b |" in out
    assert "### Muster 1: Diagramme" in out


def test_build_statistics_appendix():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    lint_cmp = fs.compare_lint_reports(ORIGINAL_MD, REVISED_MD)
    appendix = fs.build_statistics_appendix(summary, lint_cmp, {"engine": "docling"})
    assert "Anhang" in appendix
    assert "heading" in appendix or "Überschriften" in appendix


def test_build_statistics_appendix_warns_on_rule_based_fallback():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    lint_cmp = fs.compare_lint_reports(ORIGINAL_MD, REVISED_MD)
    appendix_fb = fs.build_statistics_appendix(
        summary, lint_cmp, {"Engine": "docling", "Standardisierungs-Backend": "rule_based_fallback"}
    )
    assert "[!WARNING]" in appendix_fb
    assert "regelbasierte" in appendix_fb.lower()

    appendix_gemma = fs.build_statistics_appendix(
        summary, lint_cmp, {"Engine": "docling", "Standardisierungs-Backend": "gemma"}
    )
    assert "[!WARNING]" not in appendix_gemma



# ---------------------------------------------------------------------------
# Unit tests: live log / token streaming protocol
# ---------------------------------------------------------------------------

def test_parse_analyzer_line_protocol():
    assert fs.parse_analyzer_line("[PROGRESS] 2/3 Analysiere Stelle 2") == (
        "progress", {"step": 2, "total": 3, "label": "Analysiere Stelle 2"})
    assert fs.parse_analyzer_line('[TOKEN] "Hallo\\nWelt"') == ("token", {"delta": "Hallo\nWelt"})
    assert fs.parse_analyzer_line("[SECTION] region 2") == ("section", {"section": "region", "index": 2})
    assert fs.parse_analyzer_line("[SECTION] report") == ("section", {"section": "report", "index": None})
    assert fs.parse_analyzer_line("2026-10-13 - feedback_analyzer - INFO - Loading model") == (
        "log", {"message": "2026-10-13 - feedback_analyzer - INFO - Loading model"})
    assert fs.parse_analyzer_line("   ") is None
    # Broken token payloads degrade to a log line instead of crashing
    assert fs.parse_analyzer_line("[TOKEN] not-json")[0] == "log"


FAKE_ANALYZER = r'''
import json, sys, argparse
p = argparse.ArgumentParser(); p.add_argument("--input-json"); p.add_argument("--output-json")
a = p.parse_args()
w = sys.stderr.write
w("INFO - Loading Gemma model\n")
w("[PROGRESS] 1/2 Analysiere markierte Stelle 1/1\n")
w("[SECTION] region 1\n")
for t in ["Eine ", "Tabelle"]:
    w("[TOKEN] " + json.dumps(t) + "\n")
w("[PROGRESS] 2/2 Erstelle Fehleranalyse\n")
w("[SECTION] report\n")
for t in ["## Zusammenfassung\n", "Alles gut."]:
    w("[TOKEN] " + json.dumps(t) + "\n")
json.dump({"region_findings": ["Eine Tabelle"], "report": "## Zusammenfassung\nAlles gut."}, open(a.output_json, "w"))
'''


def test_run_gemma_feedback_analysis_forwards_live_events(tmp_path, monkeypatch):
    import asyncio

    script = tmp_path / "fake_analyzer.py"
    script.write_text(FAKE_ANALYZER, encoding="utf-8")
    monkeypatch.setattr(fs, "ANALYZER_SCRIPT", str(script))

    events = []
    result = asyncio.run(fs.run_gemma_feedback_analysis(
        "prompt", [{"path": "x.png", "prompt": "p"}], str(tmp_path), lambda kind, data: events.append((kind, data))
    ))
    kinds = [k for k, _ in events]
    assert result["report"].startswith("## Zusammenfassung")
    assert result["region_findings"] == ["Eine Tabelle"]
    assert ("log", {"message": "INFO - Loading Gemma model"}) in events
    assert ("section", {"section": "region", "index": 1}) in events
    assert ("section", {"section": "report", "index": None}) in events
    assert "".join(d["delta"] for k, d in events if k == "token") == "Eine Tabelle## Zusammenfassung\nAlles gut."
    assert kinds.count("progress") == 2
    # Temporary analyzer files are cleaned up
    assert not (tmp_path / "analyzer_input.json").exists()


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

def _create_job(client, with_pdf=True, transfer_name="orig.md", transfer_bytes=None):
    files = {
        "transfer_file": (transfer_name, io.BytesIO(transfer_bytes or ORIGINAL_MD.encode("utf-8")), "text/markdown"),
    }
    if with_pdf:
        with open(TEST_PDF, "rb") as f:
            files["source_pdf"] = ("quelle.pdf", io.BytesIO(f.read()), "application/pdf")
    resp = client.post("/api/feedback/jobs", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_create_and_list_feedback_job(client):
    job = _create_job(client)
    task_id = job["task_id"]
    try:
        assert job["has_markdown"] is True
        assert job["has_pdf"] is True
        assert job["page_count"] > 0

        resp = client.get("/api/feedback/jobs")
        assert resp.status_code == 200
        jobs = {j["task_id"]: j for j in resp.json()["jobs"]}
        assert task_id in jobs
        assert jobs[task_id]["has_markdown"] is True

        md_resp = client.get(f"/api/feedback/jobs/{task_id}/files/markdown")
        assert md_resp.status_code == 200
        assert "Zellmembran" in md_resp.text
    finally:
        client.delete(f"/api/tasks/{task_id}")


def test_api_create_job_from_docx_stores_docx(client, tmp_path):
    from backend.services.docx_service import convert_markdown_to_docx

    docx_path = tmp_path / "orig.docx"
    convert_markdown_to_docx(ORIGINAL_MD, str(docx_path))
    job = _create_job(client, with_pdf=False, transfer_name="orig.docx", transfer_bytes=docx_path.read_bytes())
    try:
        assert job["has_docx"] is True
        assert job["has_markdown"] is True
        assert job["has_pdf"] is False
        resp = client.get(f"/api/feedback/jobs/{job['task_id']}/files/docx")
        assert resp.status_code == 200
    finally:
        client.delete(f"/api/tasks/{job['task_id']}")


def test_api_create_job_rejects_invalid_transfer(client):
    resp = client.post(
        "/api/feedback/jobs",
        files={"transfer_file": ("x.exe", io.BytesIO(b"abc"), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_api_render_page_png(client):
    job = _create_job(client)
    try:
        resp = client.get(f"/api/feedback/jobs/{job['task_id']}/pages/0")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get(f"/api/feedback/jobs/{job['task_id']}/pages/9999").status_code == 404
    finally:
        client.delete(f"/api/tasks/{job['task_id']}")


def _tiny_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 10), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_api_analyze_streams_report_and_persists(client):
    job = _create_job(client)
    task_id = job["task_id"]
    try:
        files = [
            ("revised_file", ("rev.md", io.BytesIO(REVISED_MD.encode("utf-8")), "text/markdown")),
            ("feedback_file", ("fb.txt", io.BytesIO("Bilder ohne Beschreibung.".encode("utf-8")), "text/plain")),
            ("regions", ("region_1.png", io.BytesIO(_tiny_png()), "image/png")),
        ]
        data = {
            "task_id": task_id,
            "feedback_text": "Aufgabenüberschriften falsch und Seitenzahl fehlt.",
            "regions_meta": json.dumps([{"page": 45, "note": "Seitenzahl fehlt"}]),
        }
        resp = client.post("/api/feedback/analyze", data=data, files=files)
        assert resp.status_code == 200
        events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        statuses = [e["status"] for e in events]
        assert "progress" in statuses
        # Live Gemma log + token stream (mock mode streams the mock report)
        assert "log" in statuses
        assert {"status": "section", "section": "report", "index": None} in events
        assert "Zusammenfassung" in "".join(e["delta"] for e in events if e["status"] == "token")
        assert statuses[-1] == "completed", events[-1]
        final = events[-1]
        report = final["report"]
        assert "## Zusammenfassung" in report
        assert "Anhang" in report
        fid = final["feedback_id"]

        feedback_dir = os.path.join(FEEDBACK_DIR, task_id, fid)
        assert os.path.exists(os.path.join(feedback_dir, "report.md"))
        assert os.path.exists(os.path.join(feedback_dir, "revised.md"))
        assert os.path.exists(os.path.join(feedback_dir, "regions", "region_1.png"))
        with open(os.path.join(feedback_dir, "feedback.txt"), encoding="utf-8") as f:
            fb = f.read()
        assert "Seitenzahl fehlt" in fb and "Bilder ohne Beschreibung" in fb

        lst = client.get(f"/api/feedback/reports?task_id={task_id}").json()["reports"]
        assert any(r["feedback_id"] == fid for r in lst)
        detail = client.get(f"/api/feedback/reports/{task_id}/{fid}").json()
        assert detail["report"] == report
    finally:
        client.delete(f"/api/tasks/{task_id}")
        shutil.rmtree(os.path.join(FEEDBACK_DIR, task_id), ignore_errors=True)


def test_api_analyze_requires_revised_file(client):
    job = _create_job(client, with_pdf=False)
    try:
        resp = client.post("/api/feedback/analyze", data={"task_id": job["task_id"]})
        assert resp.status_code == 422
    finally:
        client.delete(f"/api/tasks/{job['task_id']}")


def test_api_analyze_unknown_task(client):
    resp = client.post(
        "/api/feedback/analyze",
        data={"task_id": "does-not-exist"},
        files={"revised_file": ("rev.md", io.BytesIO(b"# x"), "text/markdown")},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Open questions: parsing, answering, API
# ---------------------------------------------------------------------------

REPORT_WITH_QUESTIONS = """## Zusammenfassung
Kurz.

## Offene Fragen
*   Wie sollen Warnsymbole übertragen werden?
*   Gibt es eine Liste erlaubter
    Abkürzungen?

---

## Anhang: Automatisch ermittelte Kennzahlen
| Kennzahl | Wert |
"""


def test_extract_open_questions_bullets_and_continuation():
    qs = fs.extract_open_questions(REPORT_WITH_QUESTIONS)
    assert [q.question for q in qs] == [
        "Wie sollen Warnsymbole übertragen werden?",
        "Gibt es eine Liste erlaubter Abkürzungen?",
    ]
    assert all(q.answer is None for q in qs)


def test_extract_open_questions_numbered_and_none():
    assert fs.extract_open_questions("## Offene Fragen\n- Keine\n") == []
    assert fs.extract_open_questions("## Zusammenfassung\nText\n") == []
    qs = fs.extract_open_questions("## Offene Fragen\n1. Frage A?\n2) Frage B?\n\n## Weiter\n- nicht dabei?")
    assert [q.question for q in qs] == ["Frage A?", "Frage B?"]


def test_extract_open_questions_plain_question_lines():
    qs = fs.extract_open_questions("## Offene Fragen\nIst das eine Regel?\nKein Fragesatz.\n")
    assert [q.question for q in qs] == ["Ist das eine Regel?"]


def test_apply_question_answers_roundtrip_and_skip():
    updated = fs.apply_question_answers(REPORT_WITH_QUESTIONS, ["Als Bild mit kurzer Beschreibung.", None])
    assert "1. Wie sollen Warnsymbole übertragen werden?" in updated
    assert "   - **Antwort:** Als Bild mit kurzer Beschreibung." in updated
    assert SKIPPED_ANSWER in updated
    # Rest of the report (appendix) is preserved
    assert updated.rstrip().endswith("| Kennzahl | Wert |")
    assert "## Zusammenfassung" in updated
    # Re-parsing yields the answers (skipped → None) and re-answering replaces them
    qs = fs.extract_open_questions(updated)
    assert [q.answer for q in qs] == ["Als Bild mit kurzer Beschreibung.", None]
    again = fs.apply_question_answers(updated, [None, "Nein."])
    assert [q.answer for q in fs.extract_open_questions(again)] == [None, "Nein."]
    assert again.count("## Offene Fragen") == 1


def test_apply_question_answers_multiline_answer_is_flattened():
    updated = fs.apply_question_answers(REPORT_WITH_QUESTIONS, ["Zeile 1\nZeile 2", ""])
    assert "**Antwort:** Zeile 1 Zeile 2" in updated
    assert fs.extract_open_questions(updated)[1].answer is None


def test_apply_question_answers_length_mismatch():
    with pytest.raises(ValueError):
        fs.apply_question_answers(REPORT_WITH_QUESTIONS, ["nur eine"])


def test_mock_report_has_parseable_open_questions():
    summary = fs.compute_change_summary(ORIGINAL_MD, REVISED_MD)
    report = fs.generate_mock_report(summary, "Feedback", ["Tabelle mit 3 Spalten"])
    qs = fs.extract_open_questions(report)
    assert qs and all(q.question.endswith("?") for q in qs)


def test_api_answer_open_questions(client):
    job = _create_job(client)
    task_id = job["task_id"]
    try:
        files = [("revised_file", ("rev.md", io.BytesIO(REVISED_MD.encode("utf-8")), "text/markdown"))]
        resp = client.post("/api/feedback/analyze", data={"task_id": task_id}, files=files)
        final = [json.loads(line) for line in resp.text.splitlines() if line.strip()][-1]
        assert final["status"] == "completed"
        questions = final["open_questions"]
        assert questions
        fid = final["feedback_id"]

        answers = ["Kurze Antwort."] + [None] * (len(questions) - 1)
        r = client.post(f"/api/feedback/reports/{task_id}/{fid}/answers", json={"answers": answers})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "**Antwort:** Kurze Antwort." in body["report"]
        assert body["open_questions"][0]["answer"] == "Kurze Antwort."
        assert "Anhang" in body["report"]

        detail = client.get(f"/api/feedback/reports/{task_id}/{fid}").json()
        assert detail["report"] == body["report"]
        assert detail["open_questions"][0]["answer"] == "Kurze Antwort."
        assert os.path.exists(os.path.join(FEEDBACK_DIR, task_id, fid, "answers.json"))

        bad = client.post(f"/api/feedback/reports/{task_id}/{fid}/answers", json={"answers": []})
        assert bad.status_code == 400
    finally:
        client.delete(f"/api/tasks/{task_id}")
        shutil.rmtree(os.path.join(FEEDBACK_DIR, task_id), ignore_errors=True)
