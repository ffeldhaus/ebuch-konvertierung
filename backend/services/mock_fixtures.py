"""Synthetic E2E test fixtures used only when ``E2E_MOCK=true`` is set in the environment.
Separated from production extraction services to keep service modules concise.
"""

import asyncio
import json
import os
from typing import Any


def get_e2e_mock_extraction_fixture(original_name: str, base_name: str) -> tuple[str, list[dict[str, Any]]]:
    """Returns deterministic `(mock_md, mock_blocks)` for Playwright E2E tests."""
    if "deutsch_textanalyse" in original_name:
        mock_md = (
            "((85))\n\n"
            "# Literarische Textanalyse: Johann Wolfgang von Goethe - Faust I\n\n"
            "## Epochenkontext und Szenenanalyse: Studierzimmer I\n\n"
            "Goethes Tragödie Faust I steht an der Epochenschwelle zwischen Sturm und Drang und der Weimarer Klassik. Fausts Eingangsmonolog im 'Studierzimmer I' verdeutlicht den Übergang von einem rationalistischen Weltbild der Aufklärung hin zu einem irrationalen, emotional geladenen Erkenntnisstreben. Der Monolog spiegelt eine tiefe existenzielle Krise wider, die durch das akademische Wissen allein nicht gelöst werden kann.\n\n"
            "### I. Die Epoche und ihr Einfluss\n"
            "Goethes Faust I stellt einen Hoehepunkt der deutschen Literatur dar. Die Entstehungsgeschichte erstreckt sich ueber mehrere Jahrzehnte und verbindet Elemente des Sturm und Drang mit der Weimarer Klassik.\n\n"
            "Die klassischen Ideale von Humanitaet, Schoenheit und Ausgewogenheit praegten Goethes spaetere Arbeiten massgeblich. Faust spiegelt diesen inneren Reifungsprozess wider, indem er sich von den emotionalen Ausbruechen des Sturm und Drang zu einer reflektierten Auseinandersetzung mit den Grenzen der menschlichen Existenz entwickelt.\n\n"
            "### II. Die Tragik des Gelehrten\n"
            "In dieser Epoche steht die Harmonie von Gefuehl und Verstand im Vordergrund. Faust repraesentiert den modernen Menschen, der sich aus den Fesseln des Mittelalters befreien will und nach absoluter Erkenntnis strebt. Dieser Drang fuehrt ihn in eine tiefe existenzielle Krise.\n\n"
            "Seine Verzweiflung entspringt der Erkenntnis, dass der Verstand allein die tiefsten Geheimnisse der Schopfung nicht erfassen kann. Das Studium der vier Fakultaeten hinterlaesst ihn geistig verarmt, was den Wendepunkt zur Magie einleitet.\n\n"
            "### III. Die Flucht in die Magie\n"
            "Er wendet sich der Magie zu, um die Geheimnisse des Universums zu entschluesseln, da die traditionellen Universitaetsfakultaeten ihn unbefriedigt zuruecklassen.\n\n"
            "Durch das Zeichen des Makrokosmos versucht Faust, die universellen Kraefte zu erfassen. Doch dies genuegt ihm nicht; er beschwoert den Erdgeist, nur um schmerzhaft seine eigene Unzulaenglichkeit und Begrenztheit erfahren zu muessen.\n"
        )
        mock_blocks = [
            {"type": "title", "text": "Literarische Textanalyse: Johann Wolfgang von Goethe - Faust I", "page_idx": 0},
            {"type": "title", "text": "Epochenkontext und Szenenanalyse: Studierzimmer I", "page_idx": 0},
            {"type": "paragraph", "text": "Goethes Tragödie Faust I steht an der Epochenschwelle zwischen Sturm und Drang und der Weimarer Klassik. Fausts Eingangsmonolog im 'Studierzimmer I' verdeutlicht den Übergang von einem rationalistischen Weltbild der Aufklärung hin zu einem irrationalen, emotional geladenen Erkenntnisstreben. Der Monolog spiegelt eine tiefe existenzielle Krise wider, die durch das akademische Wissen allein nicht gelöst werden kann.", "page_idx": 0},
            {"type": "title", "text": "I. Die Epoche und ihr Einfluss", "page_idx": 0},
            {"type": "paragraph", "text": "Goethes Faust I stellt einen Hoehepunkt der deutschen Literatur dar. Die Entstehungsgeschichte erstreckt sich ueber mehrere Jahrzehnte und verbindet Elemente des Sturm und Drang mit der Weimarer Klassik.", "page_idx": 0},
            {"type": "paragraph", "text": "Die klassischen Ideale von Humanitaet, Schoenheit und Ausgewogenheit praegten Goethes spaetere Arbeiten massgeblich. Faust spiegelt diesen inneren Reifungsprozess wider, indem er sich von den emotionalen Ausbruechen des Sturm und Drang zu einer reflektierten Auseinandersetzung mit den Grenzen der menschlichen Existenz entwickelt.", "page_idx": 0},
            {"type": "title", "text": "II. Die Tragik des Gelehrten", "page_idx": 0},
            {"type": "paragraph", "text": "In dieser Epoche steht die Harmonie von Gefuehl und Verstand im Vordergrund. Faust repraesentiert den modernen Menschen, der sich aus den Fesseln des Mittelalters befreien will und nach absoluter Erkenntnis strebt. Dieser Drang fuehrt ihn in eine tiefe existenzielle Krise.", "page_idx": 0},
            {"type": "paragraph", "text": "Seine Verzweiflung entspringt der Erkenntnis, dass der Verstand allein die tiefsten Geheimnisse der Schopfung nicht erfassen kann. Das Studium der vier Fakultaeten hinterlaesst ihn geistig verarmt, was den Wendepunkt zur Magie einleitet.", "page_idx": 0},
            {"type": "title", "text": "III. Die Flucht in die Magie", "page_idx": 0},
            {"type": "paragraph", "text": "Er wendet sich der Magie zu, um die Geheimnisse des Universums zu entschluesseln, da die traditionellen Universitaetsfakultaeten ihn unbefriedigt zuruecklassen.", "page_idx": 0},
            {"type": "paragraph", "text": "Durch das Zeichen des Makrokosmos versucht Faust, die universellen Kraefte zu erfassen. Doch dies genuegt ihm nicht; er beschwoert den Erdgeist, nur um schmerzhaft seine eigene Unzulaenglichkeit und Begrenztheit erfahren zu muessen.", "page_idx": 0},
        ]
    elif "mathe_grade3" in original_name:
        mock_md = (
            "((1))\n\n"
            "# Mathematische Übungen - Klasse 3\n\n"
            "Hier sind einige mathematische Übungen zur Bruchrechnung, Addition und Multiplikation.\n\n"
            "○ [leicht] Aufgabe 1: Addition im Hunderterraum\n"
            "Berechne die folgenden Summen:\n"
            "-\t$24 + 37 = 61$\n"
            "-\t$45 + 18 = 63$\n"
            "-\t$89 + 11 = 100$\n\n"
            "◐ [mittel] Aufgabe 2: Einführung in Brüche\n"
            "Teile die Formen auf. Welche Bruchteile sind schattiert?\n"
            "-\t$\\frac{1}{2}$ eines Kreises\n"
            "-\t$\\frac{3}{4}$ eines Quadrats\n"
            "-\t$\\frac{2}{3}$ eines Rechtecks\n\n"
            "● [schwer] Aufgabe 3: Textaufgabe zur Multiplikation und Division\n"
            "Auf einem Bauernhof gibt es 8 Hühnerställe. In jedem Stall leben 12 Hühner.\n"
            "-\tBerechne die Gesamtanzahl der Hühner: $8 \\cdot 12 = 96$\n"
            "-\tWenn die Hühner gleichmäßig auf 4 Gehege verteilt werden, wie viele Hühner sind dann in jedem Gehege? $96 / 4 = 24$\n"
        )
        mock_blocks = [
            {"type": "title", "text": "Mathematische Übungen - Klasse 3", "page_idx": 0},
            {"type": "paragraph", "text": "Hier sind einige mathematische Übungen zur Bruchrechnung, Addition und Multiplikation.", "page_idx": 0},
            {"type": "paragraph", "text": "○ [leicht] Aufgabe 1: Addition im Hunderterraum\nBerechne die folgenden Summen:\n-\t$24 + 37 = 61$\n-\t$45 + 18 = 63$\n-\t$89 + 11 = 100$", "page_idx": 0},
            {"type": "paragraph", "text": "◐ [mittel] Aufgabe 2: Einführung in Brüche\nTeile die Formen auf. Welche Bruchteile sind schattiert?\n-\t$\\frac{1}{2}$ eines Kreises\n-\t$\\frac{3}{4}$ eines Quadrats\n-\t$\\frac{2}{3}$ eines Rechtecks", "page_idx": 0},
            {"type": "paragraph", "text": "● [schwer] Aufgabe 3: Textaufgabe zur Multiplikation und Division\nAuf einem Bauernhof gibt es 8 Hühnerställe. In jedem Stall leben 12 Hühner.\n-\tBerechne die Gesamtanzahl der Hühner: $8 \\cdot 12 = 96$\n-\tWenn die Hühner gleichmäßig auf 4 Gehege verteilt werden, wie viele Hühner sind dann in jedem Gehege? $96 / 4 = 24$", "page_idx": 0},
        ]
    elif "test_educational" in original_name:
        mock_md = (
            "((45))\n\n"
            "# Optik und Wellenlehre\n\n"
            "## Lichtbrechung am Prisma\n\n"
            "Trifft weißes Licht auf ein optisches Prisma, so wird es beim Eintritt und Austritt gebrochen.\n\n"
            "<Bild> Zeichnung: Versuchsaufbau eines optischen Experiments mit Prismen zur Lichtbrechung. </Bild>\n\n"
            "Formel für den Brechungsindex: $n = \\frac{c_0}{c}$\n\n"
            "Hier ist eine Erläuterung{1}.\n\n"
            "<Anmerkung> 1 Brechung an der Grenzfläche zweier Medien. </Anmerkung>\n"
        )
        mock_blocks = [
            {"type": "title", "text": "Optik und Wellenlehre", "page_idx": 0, "bbox_1000": [100, 80, 750, 140]},
            {"type": "title", "text": "Lichtbrechung am Prisma", "page_idx": 0, "bbox_1000": [100, 160, 680, 210]},
            {"type": "paragraph", "text": "Trifft weißes Licht auf ein optisches Prisma, so wird es beim Eintritt und Austritt gebrochen.", "page_idx": 0, "bbox_1000": [100, 230, 880, 320]},
            {"type": "image", "text": "<Bild> Zeichnung: Versuchsaufbau eines optischen Experiments mit Prismen zur Lichtbrechung. </Bild>", "page_idx": 0, "bbox_1000": [150, 350, 820, 650]},
            {"type": "paragraph", "text": "Formel für den Brechungsindex: $n = \\frac{c_0}{c}$", "page_idx": 0, "bbox_1000": [100, 680, 700, 730]},
            {"type": "paragraph", "text": "Hier ist eine Erläuterung{1}.", "page_idx": 0, "bbox_1000": [100, 750, 500, 790]},
            {"type": "footnote", "text": "<Anmerkung> 1 Brechung an der Grenzfläche zweier Medien. </Anmerkung>", "page_idx": 0, "bbox_1000": [100, 880, 850, 930]},
        ]
    else:
        mock_md = f"Mock raw content for {base_name}"
        mock_blocks = [{"type": "text", "text": mock_md, "page_idx": 0, "bbox_1000": [100, 100, 900, 200]}]

    return mock_md, mock_blocks


async def run_e2e_mock_extraction(task: dict[str, Any], input_path: str, output_root: str) -> None:
    """Executes simulated extraction progress and writes mock artefacts for E2E tests."""
    original_name = task.get("original_name", "")
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    auto_dir = os.path.join(output_root, base_name, "auto")
    os.makedirs(auto_dir, exist_ok=True)

    mock_md, mock_blocks = get_e2e_mock_extraction_fixture(original_name, base_name)

    md_path = os.path.join(auto_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(mock_md)

    json_path = os.path.join(auto_dir, f"{base_name}_content_list.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mock_blocks, f)

    phases = [
        (20, "Layout-Analyse"),
        (50, "Dokumenten-Texterkennung"),
        (80, "Extraktion & Formatierung"),
        (100, "Extraktion abgeschlossen"),
    ]

    for percent, phase in phases:
        task["progress"] = {
            "percent": percent,
            "current": 1,
            "total": 1,
            "phase": phase,
        }
        log_msg = f"[Mock] {phase} progress: {percent}%"
        task["logs"].append(log_msg)

        progress_event = f'{{"status": "progress", "percent": {percent}, "current": 1, "total": 1, "phase": "{phase}"}}\n'
        log_event = f'{{"status": "log", "message": "{log_msg}"}}\n'

        for queue in list(task["listeners"]):
            try:
                await queue.put(log_event)
                await queue.put(progress_event)
            except Exception:
                pass
        await asyncio.sleep(0.05)

    task["status"] = "completed"
    task["raw_markdown"] = mock_md
    task["image_dir"] = os.path.join(auto_dir, "images")
    task["images"] = []

    for queue in list(task["listeners"]):
        try:
            await queue.put(f'{{"status": "completed", "markdown": {json.dumps(mock_md)}, "image_count": 0}}\n')
            await queue.put(None)
        except Exception:
            pass
