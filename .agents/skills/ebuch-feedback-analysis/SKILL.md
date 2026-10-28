---
name: ebuch-feedback-analysis
description: >-
  Process and implement fixes from Gemma 4 Feedback Analysis reports
  (assets/feedback/<task_id>/<feedback_id>/report.md) or maintain the
  Feedback mode (backend/services/feedback_service.py, feedback_analyzer.py).
  Activate this skill whenever the user pastes or references a Feedback report
  ("für den Coding Assistant", "Muster N", "Offene Fragen") or asks to modify
  the Feedback analyzer.
---

# Working with Gemma Feedback Analyses (💬 Feedback Mode)

Users upload a manually corrected transfer in the **Feedback** mode. Gemma 4 compares it with the automatic transfer and writes a report "für den Coding Assistant" stored in `assets/feedback/<task_id>/<feedback_id>/report.md` (inputs: `original.md`, `revised.md`, `feedback.txt`, `regions/*.png`, `meta.json`).

Report structure: `Zusammenfassung` → `Übersicht` (pattern table) → `Fehlermuster` (one `### Muster N` per pattern incl. **Benötigte Testdaten**) → `Maßnahmen für den Coding Assistant` → `Benötigte Testdaten` (test case table) → `Offene Fragen` → deterministic `Anhang` (metrics, not written by the LLM).

## 1. Answered Open Questions (`## Offene Fragen`)

In the UI, the user answers Gemma's open questions in a modal, which rewrites the report:

```markdown
## Offene Fragen
1. <Frage>
   - **Antwort:** <user's answer>
2. <Frage>
   - **Antwort:** – (übersprungen, weiterhin offen)
```

- A `**Antwort:**` from the user is a **binding rule interpretation** for this task and overrides Gemma's "Erwartetes Verhalten" where they conflict. Implement it generically (zero overfitting) and cover it with a unit test; if it changes a transfer rule, update `SYSTEM_PROMPTS` in `backend/services/llm_service.py`.
- Questions marked `"übersprungen, weiterhin offen"` are **not decided** — do not guess; ask the user before implementing anything that depends on them.

## 2. Treat the Report as Hypotheses, Not a Specification

- **Gemma 12B can be wrong**: It may hallucinate root causes, invent function names, or suggest changes that contradict FIBS rules. Verify every claim before writing code.
- **Source of truth**: The FIBS ruleset (*Übertragungsregeln FIBS, Stand September 2025* in `SYSTEM_PROMPTS` and the golden ground truths), **not** the human correction and not Gemma.
- **Human corrections can contain errors**: Check the report's deterministic `Anhang`. Rules listed under `"In Korrektur neu auftretende Linter-Regeln"` or a *lower* linter score for the correction mean the human-edited file itself violates FIBS rules — do not copy those violations into the converter.
- **Low similarity (< 40%)**: Often caused by different page scope, re-ordered content, or deliberately removed decorative content rather than converter bugs. Check `+/-` line counts first.

## 3. Step-by-Step Pattern Verification & Generic Implementation

For each `Muster` in the overview table, in priority order:

1. **Reproduce**: Find a concrete instance in `original.md` vs. `revised.md` (the report itself redacts snippets to $\le 12$ words for copyright compliance).
2. **Check the rule**: Confirm expected behaviour against the FIBS 09/2025 ruleset. If unbacked by a rule, list it as an open question.
3. **Locate the stage**: Confirm referenced files/functions exist (`rg`); entries marked `"(zu prüfen)"` are guesses. Stages:
   - Extraction: `extraction_service.py`, `*_extractor.py`, `extraction_postprocess.py`
   - Image descriptions: `vlm_describer.py`, `fibs_formatting.py`
   - LLM standardisation & deterministic post-processing: `llm_service.py`
   - DOCX export/import: `docx_service.py`, `formula_service.py`
4. **Implement generically (Zero Overfitting)**:
   - **Reject** suggestions that hardcode words, titles, or phrases from the analysed textbook (enforced by `test_no_test_data_leakage_across_backend_services`).
   - Use structural/layout heuristics (font size/weight, BBox geometry, cross-page repetition, numbering schemes) or general prompt rules.
   - Prefer deterministic post-processing for unambiguous syntax (page markers, list tabs, footnote refs) and prompt rules for semantic decisions.

## 4. Test Data Requirements (`Benötigte Testdaten`)

- **Unit-Test-Snippet**: Write a short **synthetic** Markdown snippet (own wording, zero text from the analysed proprietary book) and add the failing test first (TDD).
- **PDF-Seite (E2E/Benchmark)**: Check `testdata/` and `testdata/ATTRIBUTIONS.md` or extend `scripts/generate_schoolbook_suite.py`. **Never commit pages or text of a proprietary textbook** into `ebuch-konvertierung`.
- **Validation & Summary**: Run `.venv/bin/pytest backend/tests` (and `scripts/run_benchmark.py --mode fast` when extraction/standardisation rules changed). In the final response, list per pattern: *implemented* / *rejected (reason)* / *needs clarification*, plus added tests.

## 5. Maintaining the Feedback Feature (`feedback_service.py` & `feedback_analyzer.py`)

- Keep `build_analysis_prompt()` and `generate_mock_report()` in `backend/services/feedback_service.py` in sync (tested in `backend/tests/test_feedback_service.py`).
- Always run `redact_long_passages(normalize_report_markdown(raw_report), [original_md, revised_md])` before persisting `report.md` or `meta.json`. Live streamed tokens are unfiltered and must never be persisted to disk.
- Open questions are parsed/applied via `extract_open_questions()` and `apply_question_answers()` (`POST /api/feedback/reports/{task_id}/{feedback_id}/answers`).
- `feedback_analyzer.py` runs as an isolated subprocess (1 image per prompt, `mx.clear_cache()` between steps, `release_gpu_memory()` before/after in `main.py`).
