"""Generate TTS narration audio and Google-Docs-rendered FIBS viewer HTML.

Synthesizes 26 atomic German narration beats using ``gemini-3.8-flash-tts`` with
two alternating voices (``Kore`` and ``Charon``), enforces lowercase ``fibs`` in
all TTS inputs so the model pronounces it naturally as a word rather than
spelling letters, appends 0.22s of digital silence to each WAV for clean
sentence endings, records exact frame-derived durations in ``manifest.json``,
and writes the fullscreen Google Docs FIBS preview HTML.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS_DIR = PROJECT_ROOT / "assets" / "video_capture"
SILENCE_PAD_SEC = 0.22
SAMPLE_RATE_HZ = 24000

BEATS: list[dict[str, str]] = [
    {
        "id": "01a_welcome",
        "voice": "Kore",
        "step_label": "Schritt 1 / 17 • Willkommen",
        "caption_text": (
            "Willkommen beim E-Buch Standard Konverter – Ihrer lokalen "
            "Arbeitsumgebung für die barrierefreie Schulbuchübertragung."
        ),
        "tts_text": (
            "Willkommen beim E-Buch Standard Konverter – Ihrer lokalen "
            "Arbeitsumgebung für die barrierefreie Schulbuchübertragung."
        ),
    },
    {
        "id": "01b_header_overview",
        "voice": "Kore",
        "step_label": "Schritt 1 / 17 • Kopfleiste & Prozessanzeige",
        "caption_text": (
            "In der oberen Kopfleiste verfolgen Sie jederzeit die vier "
            "Arbeitsschritte vom Upload bis zur fertigen Word-Datei, wählen "
            "das Farbschema und blenden Teilansichten flexibel ein oder aus."
        ),
        "tts_text": (
            "In der oberen Kopfleiste verfolgen Sie jederzeit die vier "
            "Arbeitsschritte vom Upload bis zur fertigen Word-Datei, wählen "
            "das Farbschema und blenden Teilansichten flexibel ein oder aus."
        ),
    },
    {
        "id": "01c_header_modes_dropdown",
        "voice": "Kore",
        "step_label": "Schritt 1 / 17 • Modus-Auswahl in der Kopfleiste",
        "caption_text": (
            "Über das Modus-Menü links oben wechseln Sie direkt zwischen der "
            "Übertragung, dem Benchmark- und Evaluierungs-Center, dem "
            "Feedback-Modus und den Einstellungen."
        ),
        "tts_text": (
            "Über das Modus-Menü links oben wechseln Sie direkt zwischen der "
            "Übertragung, dem Benchmark- und Evaluierungs-Center, dem "
            "Feedback-Modus und den Einstellungen."
        ),
    },
    {
        "id": "02a_workspace_left",
        "voice": "Kore",
        "step_label": "Schritt 2 / 17 • Arbeitsbereich: Linke Seitenleiste",
        "caption_text": (
            "Darunter gliedert sich der Arbeitsbereich in drei übersichtliche "
            "Bereiche: Links steuern Sie den Regelsatz, den Dokument-Upload, "
            "die Seitenauswahl und die Erkennungs-Optionen."
        ),
        "tts_text": (
            "Darunter gliedert sich der Arbeitsbereich in drei übersichtliche "
            "Bereiche: Links steuern Sie den Regelsatz, den Dokument-Upload, "
            "die Seitenauswahl und die Erkennungs-Optionen."
        ),
    },
    {
        "id": "02b_workspace_center",
        "voice": "Kore",
        "step_label": "Schritt 2 / 17 • Arbeitsbereich: Mittlerer Hauptbereich",
        "caption_text": (
            "In der Mitte befinden sich die Original-Vorschau sowie die "
            "Editoren für den erfassten Rohtext und das fertig strukturierte "
            "E-Buch-Markdown."
        ),
        "tts_text": (
            "In der Mitte befinden sich die Original-Vorschau sowie die "
            "Editoren für den erfassten Rohtext und das fertig strukturierte "
            "E-Buch-Markdown."
        ),
    },
    {
        "id": "02c_workspace_right",
        "voice": "Kore",
        "step_label": "Schritt 2 / 17 • Arbeitsbereich: Rechte Seitenleiste",
        "caption_text": (
            "Rechts legen Sie das Zielgruppen-Profil sowie die "
            "Dokumentvorlage fest und starten den Export nach Word."
        ),
        "tts_text": (
            "Rechts legen Sie das Zielgruppen-Profil sowie die "
            "Dokumentvorlage fest und starten den Export nach Word."
        ),
    },
    {
        "id": "03_concept_architecture",
        "voice": "Charon",
        "step_label": "Schritt 3 / 17 • Konzept: Zweistufige lokale Verarbeitung",
        "caption_text": (
            "Das gesamte System arbeitet zu 100 Prozent lokal und "
            "datenschutzkonform auf Ihrem eigenen Rechner in zwei Stufen: "
            "Zuerst erfasst die optische Seitenanalyse alle Texte, Tabellen, "
            "Formeln und Bilder; danach wendet das lokale Sprachmodell "
            "Gemma 4 seitenweise die offiziellen FIBS-Übertragungsregeln an."
        ),
        "tts_text": (
            "Das gesamte System arbeitet zu hundert Prozent lokal und "
            "datenschutzkonform auf Ihrem eigenen Rechner in zwei Stufen: "
            "Zuerst erfasst die optische Seitenanalyse alle Texte, Tabellen, "
            "Formeln und Bilder; danach wendet das lokale Sprachmodell "
            "Gemma vier seitenweise die offiziellen fibs Übertragungsregeln an."
        ),
    },
    {
        "id": "04a_ruleset_select",
        "voice": "Kore",
        "step_label": "Schritt 4 / 17 • Auswahl des Regelsatzes",
        "caption_text": (
            "Beginnen wir einen konkreten Durchlauf: Links oben wählen wir "
            "zunächst den gewünschten Regelsatz aus – hier die offiziellen "
            "FIBS-Übertragungsregeln vom September 2025."
        ),
        "tts_text": (
            "Beginnen wir einen konkreten Durchlauf: Links oben wählen wir "
            "zunächst den gewünschten Regelsatz aus – hier die offiziellen "
            "fibs Übertragungsregeln vom September 2025."
        ),
    },
    {
        "id": "04b_document_upload",
        "voice": "Kore",
        "step_label": "Schritt 5 / 17 • Dokument-Upload & Zusatzregeln",
        "caption_text": (
            "Darunter laden wir das gewünschte Schulbuch-Kapitel als "
            "PDF-Datei hoch. Optional lassen sich hier auch fach- oder "
            "buchspezifische Zusatzregeln aus einer Buchkonferenz ergänzen."
        ),
        "tts_text": (
            "Darunter laden wir das gewünschte Schulbuch-Kapitel als "
            "PDF-Datei hoch. Optional lassen sich hier auch fach- oder "
            "buchspezifische Zusatzregeln aus einer Buchkonferenz ergänzen."
        ),
    },
    {
        "id": "05_page_selection",
        "voice": "Charon",
        "step_label": "Schritt 6 / 17 • Gezielte Buchseiten-Auswahl",
        "caption_text": (
            "Über die Seitenauswahl tragen wir die gedruckten Buchseiten "
            "501 und 502 ein. Das Programm findet automatisch die passenden "
            "Seiten innerhalb der PDF-Datei und übernimmt die originalen "
            "Buchseitenzahlen exakt in den Text."
        ),
        "tts_text": (
            "Über die Seitenauswahl tragen wir die gedruckten Buchseiten "
            "fünfhunderteins und fünfhundertzwei ein. Das Programm findet "
            "automatisch die passenden Seiten innerhalb der PDF-Datei und "
            "übernimmt die originalen Buchseitenzahlen exakt in den Text."
        ),
    },
    {
        "id": "06_engine_selection",
        "voice": "Kore",
        "step_label": "Schritt 7 / 17 • Wahl der Erkennungs-Variante",
        "caption_text": (
            "Je nach Buchvorlage stehen drei lokale Erkennungs-Varianten "
            "bereit – von höchster Genauigkeit für Formeln, Tabellen und "
            "Scans bis zur schnellen Fließtext-Erfassung – inklusive "
            "automatischer Bildbeschreibungen."
        ),
        "tts_text": (
            "Je nach Buchvorlage stehen drei lokale Erkennungs-Varianten "
            "bereit – von höchster Genauigkeit für Formeln, Tabellen und "
            "Scans bis zur schnellen Fließtext-Erfassung – inklusive "
            "automatischer Bildbeschreibungen."
        ),
    },
    {
        "id": "07_concept_extraction",
        "voice": "Charon",
        "step_label": "Schritt 8 / 17 • Konzept: Was bei der Seitenanalyse passiert",
        "caption_text": (
            "Bei der Seitenanalyse betrachtet die Software jede Buchseite "
            "sowohl textlich als auch optisch: Wiederkehrende Kopf- und "
            "Fußzeilen am Seitenrand werden automatisch ausgeblendet, "
            "Abbildungen passgenau ausgeschnitten und Überschriften, "
            "Infokästen, Tabellen sowie mathematische Formeln in eine "
            "saubere Lesereihenfolge gebracht."
        ),
        "tts_text": (
            "Bei der Seitenanalyse betrachtet die Software jede Buchseite "
            "sowohl textlich als auch optisch: Wiederkehrende Kopf- und "
            "Fußzeilen am Seitenrand werden automatisch ausgeblendet, "
            "Abbildungen passgenau ausgeschnitten und Überschriften, "
            "Infokästen, Tabellen sowie mathematische Formeln in eine "
            "saubere Lesereihenfolge gebracht."
        ),
    },
    {
        "id": "08a_start_extraction",
        "voice": "Kore",
        "step_label": "Schritt 9 / 17 • Extraktion starten",
        "caption_text": (
            "Mit einem Klick auf „Extraktion starten“ beginnt nun die "
            "automatische Verarbeitung auf dem lokalen Rechner."
        ),
        "tts_text": (
            "Mit einem Klick auf Extraktion starten beginnt nun die "
            "automatische Verarbeitung auf dem lokalen Rechner."
        ),
    },
    {
        "id": "08b_extraction_running",
        "voice": "Kore",
        "step_label": "Schritt 9 / 17 • Fortschrittsanzeige während der Analyse",
        "caption_text": (
            "Während die ausgewählten Buchseiten nacheinander erfasst und "
            "nach den Übertragungsregeln aufbereitet werden, informiert die "
            "kompakte Fortschrittsleiste oben über den aktuellen Stand."
        ),
        "tts_text": (
            "Während die ausgewählten Buchseiten nacheinander erfasst und "
            "nach den Übertragungsregeln aufbereitet werden, informiert die "
            "kompakte Fortschrittsleiste oben über den aktuellen Stand."
        ),
    },
    {
        "id": "09_bbox_grounding",
        "voice": "Charon",
        "step_label": "Schritt 10 / 17 • Erkannte Layout-Bereiche auf der Buchseite",
        "caption_text": (
            "Nach Abschluss der Analyse zeigt die Ansicht „Layout-Boxen“ in "
            "der Originalvorschau genau, welche Bereiche auf Buchseite 501 "
            "als Kopfzeile, Überschrift, Fließtext, Formel oder Abbildung "
            "erkannt wurden."
        ),
        "tts_text": (
            "Nach Abschluss der Analyse zeigt die Ansicht Layout-Boxen in "
            "der Originalvorschau genau, welche Bereiche auf Buchseite "
            "fünfhunderteins als Kopfzeile, Überschrift, Fließtext, Formel "
            "oder Abbildung erkannt wurden."
        ),
    },
    {
        "id": "10_main_editors_comparison",
        "voice": "Kore",
        "step_label": "Schritt 11 / 17 • Direktvergleich im Hauptbereich",
        "caption_text": (
            "Im Hauptbereich vergleichen wir nun beide Ergebnisse direkt "
            "nebeneinander: Links steht der erfasste Rohtext aus der "
            "Seitenanalyse, rechts das fertig strukturierte "
            "E-Buch-Standard-Markdown mit der Formatierungsleiste."
        ),
        "tts_text": (
            "Im Hauptbereich vergleichen wir nun beide Ergebnisse direkt "
            "nebeneinander: Links steht der erfasste Rohtext aus der "
            "Seitenanalyse, rechts das fertig strukturierte "
            "E-Buch-Standard-Markdown mit der Formatierungsleiste."
        ),
    },
    {
        "id": "11_fibs_concepts_content",
        "voice": "Charon",
        "step_label": "Schritt 12 / 17 • Angewandte FIBS-Strukturregeln",
        "caption_text": (
            "Rechts sehen wir die angewandten FIBS-Regeln im Detail: Die "
            "originalen Buchseitenzahlen stehen in doppelten runden Klammern, "
            "Überschriften sind lückenlos gestuft, Abbildungen erhalten eine "
            "kompakte, sachliche Bildbeschreibung, und auf Seite 502 folgen "
            "Formeln sowie die strukturierte Datentabelle."
        ),
        "tts_text": (
            "Rechts sehen wir die angewandten fibs Regeln im Detail: Die "
            "originalen Buchseitenzahlen stehen in doppelten runden Klammern, "
            "Überschriften sind lückenlos gestuft, Abbildungen erhalten eine "
            "kompakte, sachliche Bildbeschreibung, und auf Seite "
            "fünfhundertzwei folgen Formeln sowie die strukturierte "
            "Datentabelle."
        ),
    },
    {
        "id": "12_diff_view",
        "voice": "Kore",
        "step_label": "Schritt 13 / 17 • Farbcodierte Differenz-Ansicht",
        "caption_text": (
            "Über die Schaltfläche „Differenzen“ lassen sich sämtliche "
            "Regel-Anpassungen bei Struktur-Tags, Hervorhebungen und "
            "Textstellen farblich hervorgehoben auf einen Blick "
            "kontrollieren."
        ),
        "tts_text": (
            "Über die Schaltfläche Differenzen lassen sich sämtliche "
            "Regel-Anpassungen bei Struktur-Tags, Hervorhebungen und "
            "Textstellen farblich hervorgehoben auf einen Blick "
            "kontrollieren."
        ),
    },
    {
        "id": "13_ai_correction_bar",
        "voice": "Kore",
        "step_label": "Schritt 14 / 17 • Interaktive KI-Nachbearbeitung",
        "caption_text": (
            "Möchten Sie einzelne Passagen gezielt anpassen, formulieren Sie "
            "Ihren Änderungswunsch einfach unten in der Eingabeleiste – das "
            "lokale Sprachmodell setzt die Korrekturanweisung direkt im "
            "Dokument um."
        ),
        "tts_text": (
            "Möchten Sie einzelne Passagen gezielt anpassen, formulieren Sie "
            "Ihren Änderungswunsch einfach unten in der Eingabeleiste – das "
            "lokale Sprachmodell setzt die Korrekturanweisung direkt im "
            "Dokument um."
        ),
    },
    {
        "id": "14a_export_options",
        "voice": "Kore",
        "step_label": "Schritt 15 / 17 • Zielgruppen-Profil & Dokumentvorlage",
        "caption_text": (
            "Für die Ausgabe wählen wir in der rechten Seitenleiste zunächst "
            "das passende Zielgruppen-Profil – etwa Sehbehindert, "
            "Brailleschrift oder Großdruck – sowie die offizielle "
            "FIBS-Dokumentvorlage."
        ),
        "tts_text": (
            "Für die Ausgabe wählen wir in der rechten Seitenleiste zunächst "
            "das passende Zielgruppen-Profil – etwa Sehbehindert, "
            "Brailleschrift oder Großdruck – sowie die offizielle "
            "fibs Dokumentvorlage."
        ),
    },
    {
        "id": "14b_export_download",
        "voice": "Kore",
        "step_label": "Schritt 15 / 17 • Word-Datei erzeugen & herunterladen",
        "caption_text": (
            "Anschließend erzeugen wir per Klick auf „Word-Datei erzeugen“ "
            "das fertige Dokument oder laden ergänzend auch die beiden "
            "Markdown-Dateien herunter."
        ),
        "tts_text": (
            "Anschließend erzeugen wir per Klick auf Word-Datei erzeugen "
            "das fertige Dokument oder laden ergänzend auch die beiden "
            "Markdown-Dateien herunter."
        ),
    },
    {
        "id": "15a_gdocs_page1",
        "voice": "Charon",
        "step_label": "Schritt 16 / 17 • Dokumentvorschau: Echte FIBS-Formatvorlagen",
        "caption_text": (
            "In der Dokumentvorschau sehen wir die echten "
            "FIBS-Formatvorlagen im Einsatz: Nach dem standardisierten "
            "Titelblock folgt Buchseite 501 in gut lesbarer Verdana-Schrift "
            "mit eineinhalbzeiligem Zeilenabstand, klar abgestuften "
            "Überschriften, Listeneinzug und dem eingebetteten Bild-Block."
        ),
        "tts_text": (
            "In der Dokumentvorschau sehen wir die echten "
            "fibs Formatvorlagen im Einsatz: Nach dem standardisierten "
            "Titelblock folgt Buchseite fünfhunderteins in gut lesbarer "
            "Verdana-Schrift mit eineinhalbzeiligem Zeilenabstand, klar "
            "abgestuften Überschriften, Listeneinzug und dem eingebetteten "
            "Bild-Block."
        ),
    },
    {
        "id": "15b_gdocs_page2",
        "voice": "Charon",
        "step_label": "Schritt 16 / 17 • Dokumentvorschau: Seitenumbruch & Tabelle",
        "caption_text": (
            "Vor jeder neuen Buchseite – hier Seite 502 – erzeugt der Export "
            "automatisch einen Seitenumbruch samt unsichtbarer "
            "Screenreader-Textmarke; darunter sehen wir die abgesetzte Formel "
            "sowie die sauber gerahmte FIBS-Datentabelle zum Brechungsindex."
        ),
        "tts_text": (
            "Vor jeder neuen Buchseite – hier Seite fünfhundertzwei – erzeugt "
            "der Export automatisch einen Seitenumbruch samt unsichtbarer "
            "Screenreader-Textmarke; darunter sehen wir die abgesetzte Formel "
            "sowie die sauber gerahmte fibs Datentabelle zum Brechungsindex."
        ),
    },
    {
        "id": "16_benchmark_center",
        "voice": "Kore",
        "step_label": "Schritt 17 / 17 • Benchmark & Abgleich mit geprüfter Fassung",
        "caption_text": (
            "Im Benchmark- und Evaluierungs-Center lässt sich eine "
            "Übertragung, nachdem sie von einer Fachkraft geprüft und in Word "
            "überarbeitet wurde, direkt mit dem automatischen Ergebnis "
            "vergleichen – das System wertet alle Abweichungen aus und "
            "erzeugt automatisches Feedback zur Verbesserung der "
            "Übertragungsregeln."
        ),
        "tts_text": (
            "Im Benchmark- und Evaluierungs-Center lässt sich eine "
            "Übertragung, nachdem sie von einer Fachkraft geprüft und in Word "
            "überarbeitet wurde, direkt mit dem automatischen Ergebnis "
            "vergleichen – das System wertet alle Abweichungen aus und "
            "erzeugt automatisches Feedback zur Verbesserung der "
            "Übertragungsregeln."
        ),
    },
    {
        "id": "17a_feedback_input",
        "voice": "Kore",
        "step_label": "Schritt 17 / 17 • Feedback-Modus: Korrektur & PDF-Markierung",
        "caption_text": (
            "Im Feedback-Modus melden Übertragungskräfte konkrete Korrekturen "
            "zu einem Auftrag zurück: Für unser Optik-Kapitel laden wir die "
            "überarbeitete Fassung hoch, notieren, dass englische "
            "Fachbegriffe in Klammern ohne Prozentzeichen stehen sollen, und "
            "markieren die entsprechende Stelle direkt auf Buchseite 501."
        ),
        "tts_text": (
            "Im Feedback-Modus melden Übertragungskräfte konkrete Korrekturen "
            "zu einem Auftrag zurück: Für unser Optik-Kapitel laden wir die "
            "überarbeitete Fassung hoch, notieren, dass englische "
            "Fachbegriffe in Klammern ohne Prozentzeichen stehen sollen, und "
            "markieren die entsprechende Stelle direkt auf Buchseite "
            "fünfhunderteins."
        ),
    },
    {
        "id": "17b_feedback_report",
        "voice": "Charon",
        "step_label": "Schritt 17 / 17 • Feedback-Modus: Automatische Muster-Analyse",
        "caption_text": (
            "Die lokale Gemma-4-Fehleranalyse fasst die Abweichungen "
            "anschließend zu übersichtlichen Mustern zusammen – hier zu "
            "fremdsprachigen Klammerzusätzen und Gleichungsnummern – und "
            "formuliert konkrete Regel-Ergänzungen für künftige Kapitel."
        ),
        "tts_text": (
            "Die lokale Gemma-vier-Fehleranalyse fasst die Abweichungen "
            "anschließend zu übersichtlichen Mustern zusammen – hier zu "
            "fremdsprachigen Klammerzusätzen und Gleichungsnummern – und "
            "formuliert konkrete Regel-Ergänzungen für künftige Kapitel."
        ),
    },
]

DOCX_FULLSCREEN_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>schulbuch_kapitel_fibs.docx – Google Docs / FIBS-Formatvorlagen</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #e2e8f0;
      color: #0f172a;
      font-family: Inter, system-ui, -apple-system, sans-serif;
      padding-top: 52px;
      padding-bottom: 180px;
    }
    .gdocs-topbar {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 46px;
      background: #f8fafc;
      border-bottom: 1px solid #cbd5e1;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 28px;
      z-index: 100;
    }
    .gdocs-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .gdocs-icon {
      width: 26px;
      height: 26px;
      border-radius: 5px;
      background: #2563eb;
      color: #ffffff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 13px;
    }
    .gdocs-docname {
      font-weight: 700;
      font-size: 14px;
      color: #0f172a;
      letter-spacing: -0.01em;
    }
    .gdocs-pill {
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
      padding: 3px 10px;
      border-radius: 5px;
      font-size: 11.5px;
      font-weight: 600;
    }
    .gdocs-right {
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 12px;
      color: #334155;
      font-weight: 600;
    }
    .spread-section {
      max-width: 1760px;
      margin: 14px auto 48px auto;
      padding: 12px 20px;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      gap: 26px;
    }
    .page-card {
      background: #ffffff;
      border: 1px solid #94a3b8;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14);
      border-radius: 4px;
      overflow: hidden;
      width: 590px;
      flex-shrink: 0;
    }
    .page-card img {
      display: block;
      width: 100%;
      height: auto;
    }
    .style-sidebar {
      width: 380px;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      border-top: 3px solid #2563eb;
      border-radius: 8px;
      padding: 18px 20px;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 8px;
    }
    .style-sidebar h3 {
      font-size: 14px;
      font-weight: 700;
      color: #0f172a;
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 8px;
    }
    .style-item {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 3px solid #2563eb;
      border-radius: 6px;
      padding: 10px 12px;
      font-size: 12.5px;
      line-height: 1.45;
      color: #334155;
    }
    .style-item strong {
      display: block;
      color: #0f172a;
      font-size: 13px;
      margin-bottom: 2px;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11.5px;
      color: #1d4ed8;
    }
  </style>
</head>
<body>
  <div class="gdocs-topbar">
    <div class="gdocs-left">
      <div class="gdocs-icon">W</div>
      <span class="gdocs-docname">schulbuch_kapitel_fibs.docx</span>
      <span class="gdocs-pill">Dokumentenvorlage FIBS (Verdana 14 pt • 1,5-zeilig • 2 cm Rand)</span>
    </div>
    <div class="gdocs-right">
      <span>Google Docs Dokument-Rendering</span>
      <span>•</span>
      <span>Buchseiten ((501)) – ((502))</span>
    </div>
  </div>

  <!-- Spread 1: Buchseite ((501)) rendered via Google Docs -->
  <section id="spread-1" class="spread-section">
    <div id="page-1" class="page-card">
      <img src="gdocs_pages/gdocs_page_1.png" alt="FIBS Dokumentseite 1 – Titelblock und Buchseite 501" />
    </div>
    <div id="page-2" class="page-card">
      <img src="gdocs_pages/gdocs_page_2.png" alt="FIBS Dokumentseite 2 – Überschrift 3, Überschrift 4 und Bild-Block" />
    </div>
    <aside class="style-sidebar">
      <h3>Aktive FIBS-Formatvorlagen (S. 501)</h3>
      <div class="style-item">
        <strong>Standardisierter FIBS-Titelblock</strong>
        Fach, Titel, Verlag, Platzhalter-ISBN <span class="mono">000-0-000-00000-0</span> und Seitenbereich direkt aus der offiziellen Vorlage.
      </div>
      <div class="style-item">
        <strong>Abgestufte Überschriften (Verdana fett)</strong>
        <span class="mono">Überschrift 1</span> (20 pt), <span class="mono">Überschrift 2</span> (18 pt), <span class="mono">Überschrift 3</span> (16 pt) und <span class="mono">Überschrift 4</span> (14 pt für Bildtitel).
      </div>
      <div class="style-item">
        <strong>Standard &amp; Liste (Barrierefrei)</strong>
        Durchgängig <span class="mono">Verdana 14 pt</span> mit 1,5-fachem Zeilenabstand, hängendem Listeneinzug (1 cm) sowie mehrzeiligem <span class="mono">&lt;Bild&gt;</span>-Block.
      </div>
    </aside>
  </section>

  <!-- Spread 2: Buchseite ((502)) rendered via Google Docs -->
  <section id="spread-2" class="spread-section">
    <div id="page-4" class="page-card">
      <img src="gdocs_pages/gdocs_page_4.png" alt="FIBS Dokumentseite 4 – Seitenumbruch vor ((502)), Formel und Tabelle" />
    </div>
    <div id="page-5" class="page-card">
      <img src="gdocs_pages/gdocs_page_5.png" alt="FIBS Dokumentseite 5 – Fortsetzung Datentabelle und Fließtext" />
    </div>
    <aside class="style-sidebar">
      <h3>Seitenumbruch &amp; Tabellenstil (S. 502)</h3>
      <div class="style-item" style="border-left-color:#0d9488;">
        <strong>Automatischer Seitenumbruch vor ((502))</strong>
        Jede neue Buchseite beginnt auf einer eigenen Seite inklusive unsichtbarer OpenXML-Sprungmarke <span class="mono">page_502</span> für Screenreader.
      </div>
      <div class="style-item" style="border-left-color:#0d9488;">
        <strong>Abgesetzte Formel &amp; Gleichungsnummer</strong>
        LaTeX-Ausdruck <span class="mono">$$n = \\frac{c_0}{c_M}$$ (11.1)</span> klar lesbar im Fließtext verankert.
      </div>
      <div class="style-item" style="border-left-color:#0d9488;">
        <strong>Echte Word-Datentabelle (&lt;Tabelle&gt;)</strong>
        FIBS-Tabellenformatvorlage mit durchgehenden Rahmenlinien, 0,25 cm oberem Zellenabstand und gefetteter Kopfzeile.
      </div>
    </aside>
  </section>
</body>
</html>
"""


def validate_beats_no_uppercase_fibs() -> None:
    """Ensure zero TTS prompt strings contain uppercase ``FIBS``.

    Raises:
        ValueError: If any ``tts_text`` contains ``FIBS`` in uppercase.
    """
    for beat in BEATS:
        tts_text = beat["tts_text"]
        if "FIBS" in tts_text:
            raise ValueError(
                f"Beat {beat['id']} contains uppercase 'FIBS' in tts_text: {tts_text!r}"
            )


def get_access_token() -> str:
    """Retrieve a Google Cloud access token using gcloud ADC.

    Returns:
        Bearer access token string.
    """
    proc = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def request_tts_audio(text: str, voice: str, token: str | None) -> bytes:
    """Request German TTS audio bytes from gemini-3.8-flash-tts.

    Args:
        text: German narration text to synthesize (with lowercase ``fibs``).
        voice: Prebuilt voice name (``Kore`` or ``Charon``).
        token: Google Cloud ADC Bearer token if using Vertex AI.

    Returns:
        Raw audio payload bytes returned by the API.

    Raises:
        RuntimeError: If all retry attempts fail.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "feldhaus-nrw")
    if api_key:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.8-flash-tts:generateContent?key={api_key}"
        )
        headers = {"Content-Type": "application/json"}
    else:
        url = (
            "https://aiplatform.googleapis.com/v1beta1/projects/"
            f"{project}/locations/global/publishers/google/models/"
            "gemini-3.8-flash-tts:generateContent"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": project,
            "Content-Type": "application/json",
        }

    payload = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice},
                }
            },
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url, data=data_bytes, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                part = body["candidates"][0]["content"]["parts"][0]
                return base64.b64decode(part["inlineData"]["data"])
        except (urllib.error.URLError, KeyError, IndexError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(
        f"Failed to synthesize TTS for voice={voice}: {last_err}"
    )


def write_padded_wav(raw_audio: bytes, out_path: Path) -> float:
    """Write WAV file with trailing silence and return exact duration.

    Args:
        raw_audio: Audio bytes returned by ``gemini-3.8-flash-tts``.
        out_path: Destination ``.wav`` file path.

    Returns:
        Exact duration in seconds (``total_frames / framerate``).
    """
    if raw_audio[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw_audio), "rb") as reader:
            nchannels = reader.getnchannels()
            sampwidth = reader.getsampwidth()
            framerate = reader.getframerate()
            frames = reader.readframes(reader.getnframes())
    else:
        nchannels = 1
        sampwidth = 2
        framerate = SAMPLE_RATE_HZ
        frames = raw_audio

    silence_frames = int(framerate * SILENCE_PAD_SEC)
    silence_bytes = b"\x00" * (silence_frames * nchannels * sampwidth)
    combined_frames = frames + silence_bytes

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as writer:
        writer.setnchannels(nchannels)
        writer.setsampwidth(sampwidth)
        writer.setframerate(framerate)
        writer.writeframes(combined_frames)

    total_frames = len(combined_frames) // (nchannels * sampwidth)
    return round(total_frames / framerate, 4)


def wav_duration_sec(wav_path: Path) -> float:
    """Read the exact duration of an existing WAV file in seconds.

    Args:
        wav_path: Path to the ``.wav`` file.

    Returns:
        Duration in seconds rounded to 4 decimals.
    """
    with wave.open(str(wav_path), "rb") as reader:
        return round(reader.getnframes() / reader.getframerate(), 4)


def main() -> None:
    """Synthesize all 26 TTS beats, write manifest.json and HTML viewer."""
    validate_beats_no_uppercase_fibs()

    assets_dir = Path(
        os.environ.get("EBUCH_VIDEO_ASSETS_DIR", str(DEFAULT_ASSETS_DIR))
    )
    audio_dir = assets_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    cache_path = audio_dir / "tts_cache.json"
    cache: dict[str, str] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    token: str | None = None
    manifest: list[dict[str, object]] = []

    for idx, beat in enumerate(BEATS, start=1):
        beat_id = beat["id"]
        voice = beat["voice"]
        tts_text = beat["tts_text"]
        caption_text = beat["caption_text"]
        digest = hashlib.sha256(f"{voice}:{tts_text}".encode()).hexdigest()
        wav_path = audio_dir / f"{beat_id}.wav"

        if wav_path.exists() and cache.get(beat_id) == digest:
            duration_sec = wav_duration_sec(wav_path)
            print(
                f"[{idx:02d}/{len(BEATS)}] Cached {beat_id} ({voice}): "
                f"{duration_sec:.2f}s"
            )
        else:
            if token is None and not os.environ.get("GEMINI_API_KEY"):
                token = get_access_token()
            raw_audio = request_tts_audio(
                text=tts_text, voice=voice, token=token
            )
            duration_sec = write_padded_wav(raw_audio, wav_path)
            cache[beat_id] = digest
            cache_path.write_text(
                json.dumps(cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(
                f"[{idx:02d}/{len(BEATS)}] Synthesized {beat_id} ({voice}): "
                f"{duration_sec:.2f}s"
            )

        manifest.append(
            {
                "id": beat_id,
                "voice": voice,
                "step_label": beat["step_label"],
                "caption_text": caption_text,
                "tts_text": tts_text,
                "text": caption_text,
                "wav_path": str(wav_path.resolve()),
                "duration_sec": duration_sec,
            }
        )

    manifest_path = audio_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    viewer_path = assets_dir / "docx_fullscreen_viewer.html"
    viewer_path.write_text(DOCX_FULLSCREEN_HTML, encoding="utf-8")

    total_dur = sum(float(item["duration_sec"]) for item in manifest)
    print(
        f"Done! {len(manifest)} beats ({total_dur:.2f}s total) written to "
        f"{manifest_path}"
    )


if __name__ == "__main__":
    main()
