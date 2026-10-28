# Lizenz- und Quellendokumentation für Testdaten (OER Attribution Registry)

Dieses Dokument erfasst alle im Projekt **E-Buch Standard Konverter** genutzten Testmaterialien, Referenz-PDFs und Ground-Truth-Texte. Gemäß den Richtlinien in [AGENTS.md](../AGENTS.md) werden **ausschließlich Quellen dokumentiert, die physisch im Verzeichnis `testdata/` vorliegen und lizenzrechtlich für kommerzielle sowie öffentliche Nutzung verifiziert wurden**.

---

## 1. Physik Libre (Physik – Sekundarstufe II)
- **Werk:** *Physik Libre – Ein freies Physikbuch*
- **Autoren:** Michael A. Rundel (Initiator & Hauptautor) sowie Mitwirkende der Physik-Libre-Community
- **Offizielle Quelle:** [https://physikbuch.schule/](https://physikbuch.schule/)
- **Lizenzseite:** [https://physikbuch.schule/licenses.html](https://physikbuch.schule/licenses.html)
- **Original-Download:** [https://physikbuch.schule/PhysikLibre.pdf](https://physikbuch.schule/PhysikLibre.pdf)
- **Lizenz:**
  - **Buchinhalt / PDF:** Creative Commons Attribution-ShareAlike 4.0 International ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.de))
  - **LaTeX-Quellcode:** [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- **Dateien in `testdata/`:**
  - [testdata/physik_optik_sample.pdf](physik_optik_sample.pdf) & `testdata/physik_optik_sample_scanned.pdf` (4-seitiger Referenzauszug aus Kapitel 11: Optik, Lichtbrechung und Brechungsindex, S. 500–503)
- **Besonderheiten für E-Buch:** Reale mathematische Formeln ($n = \frac{c_0}{c_M}$), Strahlengang-Diagramme, Brechungsindex-Tabellen und wechselnde Kolumnentitel.

---

## 2. OpenStax (Biologie, Chemie, Gesellschaftswissenschaften)
- **Herausgeber:** OpenStax, Rice University
- **Offizielle Quelle:** [https://openstax.org](https://openstax.org)
- **Lizenz:** Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/))
- **Attribution Statement:** *"Access for free at openstax.org."*
- **Dateien in `testdata/`:**
  - [testdata/openstax_biology_sample.pdf](openstax_biology_sample.pdf) & `testdata/openstax_biology_sample_scanned.pdf`
    - **Ursprungswerk:** *Concepts of Biology* (OpenStax)
    - **Original-URL:** [https://assets.openstax.org/oscms-prodcms/media/documents/Concepts-Biology_-_WEB.pdf](https://assets.openstax.org/oscms-prodcms/media/documents/Concepts-Biology_-_WEB.pdf)
    - **Inhalt:** 4-seitiger Auszug aus Chapter 3 (*Cell Structure and Function*, gedruckte Buchseiten S. 57–60). Mikroskopische Zellabbildungen (`FIGURE 3.1`–`3.4`, CC BY 4.0 / Public Domain), didaktische Callout-Kästen (*LEARNING OBJECTIVES*, *LINK TO LEARNING*, *CAREER CONNECTION*) und Begriffsklärungen.
  - [testdata/openstax_chemistry_sample.pdf](openstax_chemistry_sample.pdf) & `testdata/openstax_chemistry_sample_scanned.pdf`
    - **Ursprungswerk:** *Chemistry 2e* (OpenStax)
    - **Original-URL:** [https://assets.openstax.org/oscms-prodcms/media/documents/chemistry-2e_-_WEB.pdf](https://assets.openstax.org/oscms-prodcms/media/documents/chemistry-2e_-_WEB.pdf)
    - **Inhalt:** 4-seitiger Auszug aus Chapter 3.2 (*Determining Empirical and Molecular Formulas*, gedruckte Buchseiten S. 127–130). Stöchiometrische Beispielrechnungen (*EXAMPLE 3.9`–`3.12*), Flussdiagramm zur Verhältnisformelbestimmung (`FIGURE 3.11`), Hämatit-Foto (`FIGURE 3.12`) und *Check Your Learning*-Übungsboxen.
  - [testdata/openstax_history_sample.pdf](openstax_history_sample.pdf) & `testdata/openstax_history_sample_scanned.pdf`
    - **Ursprungswerk:** *World History, Volume 1: to 1500* (OpenStax)
    - **Original-URL:** [https://assets.openstax.org/oscms-prodcms/media/documents/World_History_Volume_1-WEB.pdf](https://assets.openstax.org/oscms-prodcms/media/documents/World_History_Volume_1-WEB.pdf)
    - **Inhalt:** 4-seitiger Auszug aus Chapter 3.4 (*The Indus Valley Civilization*, gedruckte Buchseiten S. 101–104). Archäologische Sachdarstellungen (`FIGURE 3.25` CC BY 2.0, `FIGURE 3.27` Public Domain, `FIGURE 3.28` Public Domain / CC BY 2.0), programmatisch neu erstellte gemeinfreie Handelsroutenkarte (`FIGURE 3.26` unter **CC0 1.0 Public Domain**, ersetzt die frühere `CC BY-NC-SA 4.0`-Drittanbieterkarte zur Sicherstellung 100 % kommerzieller Lizenzfreiheit) und Reflexionskasten (*THE PAST MEETS THE PRESENT: Deciphering Indus Valley Script*).

---

## 3. Deterministisch generierte Multi-Format-Schulbuch-Suite & OpenStreetMap-Kartografie
- **Generator-Skripte:** `scripts/generate_schoolbook_suite.py` & `scripts/generate_test_pdfs.py` (erzeugt ausschließlich mit `reportlab`, `Pillow`, `numpy` und `pypdfium2` ohne AGPL-Abhängigkeiten; **0 % Textübernahme** aus kommerziellen Schulbüchern, verifiziert per 7-Wort-N-Gramm-Audit gegen alle 50 Verlags-PDFs).
- **Abgedeckte Buchformate (analog zu den 50 NRW-Verlags-PDFs):**
  1. **DIN A4 Arbeitsheft- & Großformat (`210 × 297 mm` = `595,3 × 841,9 pt`)**:
     - [testdata/grundschule_mathematik.pdf](grundschule_mathematik.pdf) & `testdata/grundschule_mathematik_scanned.pdf` (Grundschule Klasse 3: Mathematik; S. 14–16 mit Zahlenstrahl inkl. Dienes-Material, Rechenmauer, Rechendreieck, analogen Uhren, Busfahrplan, Stellenwerttafel und Quadrat-Schwierigkeitssymbolen `□`, `◩`, `■`)
     - [testdata/grundschule_sachkunde.pdf](grundschule_sachkunde.pdf) & `testdata/grundschule_sachkunde_scanned.pdf` (Grundschule Klasse 3: Sachunterricht; S. 24–25 zum Lebensraum Streuobstwiese mit Lückentext und Wortspeicher, Wetter-/Naturprotokoll-Tabelle, illustrierter Nahrungskette und Ankreuzaufgaben)
     - [testdata/sek1_deutsch.pdf](sek1_deutsch.pdf) & `testdata/sek1_deutsch_scanned.pdf` (Sekundarstufe I Klasse 7: Deutsch; S. 112–113 mit literarischem Erzähltext inkl. Zeilenzählern, Randspalten, seitenübergreifender Silbentrennung, Methoden- und Checklisten-Kästen sowie differenzierter Typografie)
     - [testdata/sek1_englisch.pdf](sek1_englisch.pdf) & `testdata/sek1_englisch_scanned.pdf` (Sekundarstufe I Klasse 7/8: Englisch; S. 64–65 mit Jugendmagazin-Collage inkl. OpenStreetMap-Nebenkarte von St Ives Bay, Dialogen, dreispaltigem IPA-Vokabelverzeichnis und Stern-Schwierigkeitssymbolen `★`, `★★`, `★★★`)
     - [testdata/sek1_geographie.pdf](sek1_geographie.pdf) & `testdata/sek1_geographie_scanned.pdf` (Sekundarstufe I Klasse 9/10: Geographie; S. 204–205 mit thematisch-physischer Karte des Oberrheingrabens auf OpenStreetMap-Kartengrundlage, doppelseitigen Walter-Lieth-Klimadiagrammen Abb. 2.2a/b, Fußnoten und seitenübergreifender Silbentrennung)
     - [testdata/sek1_geschichte.pdf](sek1_geschichte.pdf) & `testdata/sek1_geschichte_scanned.pdf` (Sekundarstufe I Klasse 9/10: Geschichte; S. 246–247 mit historischer Zeitleiste 1835–1914, Industrialisierungs-Statistiktabelle, Fußnote, Quellenkästen M1–M3 und Rauten-Schwierigkeitssymbolen `◇`, `◈`, `◆`)
     - [testdata/sek2_chemie.pdf](sek2_chemie.pdf) & `testdata/sek2_chemie_scanned.pdf` (Sekundarstufe II Klasse 11–12: Chemie; S. 310–311 im zweispaltigen Lehrbuch-Layout mit Versuchsprotokoll, GHS-Gefahrstoffpiktogrammen, Redox- und Gleichgewichtsgleichungen, 2D-Skelett- und Haworth-Strukturformeln, Beispielrechnung zum Massenwirkungsgesetz und Kreis-Schwierigkeitssymbolen `○`, `◐`, `●`)
     - [testdata/sek2_biologie.pdf](sek2_biologie.pdf) & `testdata/sek2_biologie_scanned.pdf` (Sekundarstufe II Klasse 11–12: Biologie; S. 412–413 im zweispaltigen Lehrbuch-Layout mit Michaelis-Menten-Enzymkinetik, seitenübergreifender Messwerttabelle Tabelle 6.1, RGT-Regel und pH-Optimum)
     - [testdata/sek2_physik_verzeichnisse.pdf](sek2_physik_verzeichnisse.pdf) & `testdata/sek2_physik_verzeichnisse_scanned.pdf` (Sekundarstufe II Klasse 11–12: Physik; S. 44–47 zur Wellenoptik und Quantenphysik mit Inhaltsverzeichnis inkl. H1–H4-Gliederungsebenen, Abbildungsverzeichnis, Tabellenverzeichnis und Bildverzeichnis auf S. 44 sowie Doppelspalt-Interferenz, Gitter-Spektroskopie und Photoeffekt auf S. 45–47)
  2. **B5+ Standard-Schulbuchformat (`190 × 260 mm` = `538,6 × 737,0 pt`, Standard-Mittelstufenformat)**:
     - [testdata/sek1_informatik.pdf](sek1_informatik.pdf) & `testdata/sek1_informatik_scanned.pdf` (Sekundarstufe I Klasse 7/8: Informatik & Medienbildung; S. 18–19 zu Algorithmen, Kontrollstrukturen und Robotik mit Programmablaufplan-Grafik `Abb. 1.1`, Mediencode-Randkasten, Wahrheitstabelle `Tabelle 1.1`, Kompetenz-Checkliste *„Teste dich!“*, eingebetteten Soft-Hyphens `\u00ad` und InDesign-Druckerei-Slug `.indd` am unteren Seitenrand)
  3. **B5-Breitformat (`195 × 260 mm` = `552,8 × 737,0 pt`, Standard-Oberstufenformat)**:
     - [testdata/sek2_mathematik_analysis.pdf](sek2_mathematik_analysis.pdf) & `testdata/sek2_mathematik_analysis_scanned.pdf` (Sekundarstufe II EF/Q1: Mathematik Analysis; S. 50–51 zu ganzrationalen Funktionen, Differential- und Integralrechnung mit Koordinatensystem-Funktionsgraphen `Abb. 2.1`, Merksatz-Kasten, Charakteristika-Tabelle `Tabelle 2.1`, Tipp-Kasten zur Integralberechnung und Aufgaben mit Quadrat-Schwierigkeitssymbolen `□`, `◩`, `■`)
  4. **Querformat / Doppelseiten-Spread (`240 × 170 mm` = `680,3 × 481,9 pt`, FIBS Regel 1 `((18)) / ((19))`)**:
     - [testdata/grundschule_lesebuch_doppelseite.pdf](grundschule_lesebuch_doppelseite.pdf) & `testdata/grundschule_lesebuch_doppelseite_scanned.pdf` (Grundschule Klasse 2/3: Deutsch Lesebuch im Doppelseiten-Layout `((18)) / ((19))` und `((20)) / ((21))` mit Erzähltext, Zeilenzählern `5`, `10`, `15`, Illustration `Abb. 3.1`, Wortbausteine-Kasten, Rollen-Tabelle `Tabelle 3.1` und Leseverständnisaufgaben)
  5. **Kompakte synthetische Basis-Referenzdokumente (US-Letter `612 × 792 pt`)**:
     - [testdata/test_educational.pdf](test_educational.pdf), `testdata/test_educational_scanned.pdf` & `testdata/test_educational.docx` (Physikalischer Lehrbuchtext zu Lichtbrechung und Dispersion, S. 45–48, 7 Abbildungen `4.1`–`4.4`)
     - [testdata/deutsch_textanalyse.pdf](deutsch_textanalyse.pdf) & `testdata/deutsch_textanalyse_scanned.pdf` (Deutschunterricht: Szenenanalyse zu Faust I, S. 85–87)
     - [testdata/mathe_grade3.pdf](mathe_grade3.pdf) & `testdata/mathe_grade3_scanned.pdf` (Grundschulmathematik: Geometrie und Rechenaufgaben, S. 1–3)
- **Lizenz der Lehr- und Übungstexte, Diagramme und Illustrationen:** Creative Commons CC0 1.0 Universal (Public Domain Dedication) / Apache-2.0.
- **Lizenz & Quellenangabe für OpenStreetMap-Kartengrundlagen:**
  - **Quelle:** [https://www.openstreetmap.org/](https://www.openstreetmap.org/) (`tile.openstreetmap.org`, lokal gecacht unter `testdata/figures/osm_cache/` für deterministische Offline-Ausführung)
  - **Lizenz:** Open Data Commons Open Database License ([ODbL 1.0](https://www.openstreetmap.org/copyright))
  - **Pflicht-Attribution:** *„Kartengrundlage: © OpenStreetMap-Mitwirkende (ODbL 1.0, openstreetmap.org/copyright)“* bzw. *„© OpenStreetMap contributors (ODbL)“* (eingebettet in `testdata/figures/geo_karte_oberrheingraben.png`, `testdata/figures/sek1_cornwall_coastal_action.png` sowie in den zugehörigen Bildunterschriften und Ground-Truth-Dateien).

---

## 4. Richtlinie zu urheberrechtlich geschützten Werken & Externem Test-Korpus (`ebuch-testdaten`)
- Urheberrechtlich geschützte Schulbuchwerke dürfen **unter keinen Umständen in dieses Haupt-Repository (`ebuch-konvertierung`) eingecheckt oder hochgeladen werden**.
- Für die interne Evaluierung auf realen Verlags-Musterdateien samt zugehörigen verifizierten Golden Ground Truths (`*.raw.golden.md` und `*.uebertragungsregeln_09_2025.golden.md`) und Metadatenkatalog (`CATALOG.md` / `catalog.json`) wird ausschließlich ein separates, privates Begleit-Repository im Nachbarverzeichnis (`../ebuch-testdaten`) verwendet.
- Bei Ausführung von `scripts/run_benchmark.py --external-data-dir ../ebuch-testdaten` werden sämtliche Extraktions- und Benchmark-Artefakte für externe Korpus-Dateien ausschließlich innerhalb des privaten Begleit-Repositorys (`../ebuch-testdaten/benchmarks/runs/`) gespeichert.
