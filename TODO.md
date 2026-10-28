# TODO – Verbesserungs-Backlog

Sammlung möglicher Verbesserungen, die nicht Teil der aktuellen Anfrage sind (siehe [`AGENTS.md`](AGENTS.md) §8).
Format: `- [ ] **Titel** – Priorität` · Dateien · Befund · Lösungsvorschlag.

---

## Offene Punkte (Priorisiert)

### Pipeline & Qualität

- [ ] **Erklärvideo (`ebuch_konverter_erklaervideo_de.mp4`) aktualisieren und Dateinamen/ISBN in der Kopfzeile anonymisieren** – mittel
  - Datei: `ebuch_konverter_erklaervideo_de.mp4` (Szene `02:04–02:19`, Word-Vorschau)
  - Befund: In der Kopfzeile der Word-Vorschau bei `02:04–02:19` ist noch ein alter Dateiname/ISBN-Eintrag (a proprietary publisher DOCX filename and ISBN) zu sehen; der eigentliche Buchinhalt im Video stammt bereits aus dem offenen OER-Werk *Physik Libre* (`physik_optik_sample.pdf`). Zudem zeigt das Video noch ältere Engine-Auswahloptionen.
  - Vorschlag: Bei der nächsten Video-Aktualisierung die Szene mit einem synthetischen Dateinamen (`physik_optik_sample.docx`) und einer Platzhalter-ISBN (`000-0-000-00000-0`) sowie den aktuellen drei Engines (`Docling`, `LightOnOCR-3`, `Infinity-Parser2-Flash`) neu aufnehmen.

- [ ] **Bildunterschriften ohne extrahiertes Bild werden auf gemischten Seiten zu „Schein-Bildern“** – hoch
  - Dateien: `backend/services/llm_service.py` (`post_process_structure`), `backend/services/extraction_service.py`
  - Befund: Steht auf einer Seite sowohl mindestens ein echtes Bild als auch eine weitere Bildunterschrift (`Abb. 2 …`) ohne zugehöriges extrahiertes `![…](…)`-Bild, kann Gemma aus der bildlosen Unterschrift einen zusätzlichen `<Bild>`-Block erzeugen. (Seiten komplett ohne extrahiertes Bild werden bereits deterministisch bereinigt.)
  - Vorschlag: Bildunterschriften über ihre Bounding-Box bzw. Reihenfolge 1-zu-1 den tatsächlich extrahierten Bildern derselben Seite zuordnen; überzählige bildlose Unterschriften als Fließtext mit `<Anmerkung> Abbildung nicht extrahiert </Anmerkung>` belassen.

- [ ] **System-Prompt belegt mehr als die Hälfte des Anfragebudgets** – mittel
  - Datei: `backend/services/llm_service.py` (`SYSTEM_PROMPTS`, `_build_system_prompt()`)
  - Befund: Mit dateispezifischen Regeln, Tabellenregel und Abschnittsanweisungen umfasst der System-Prompt ca. 5.800 Tokens pro Anfrage, wodurch das Seiten-Chunk-Budget (`MAX_PAGES_PER_CHUNK = 2`) stark begrenzt wird.
  - Vorschlag: System-Prompt straffen oder Prefix-Caching des lokalen Inferenz-Servers nutzen und Speicherwirkung messen.

- [ ] **Evaluierung Gemma 4 26B-A4B (MoE, 4-Bit) für Extraktion, Bildbeschreibung und Standardisierung** – mittel
  - Dateien: `backend/services/llm_service.py`, `backend/services/vlm_describer.py`, `scripts/run_benchmark.py`, `backend/services/settings_service.py`
  - Befund: Ein 4-Bit-MoE-Modell (~14–15 GB Speicher, ~4B aktive Parameter pro Token) könnte bei vergleichbarem Speicherbedarf 2–4× höheren Durchsatz und höhere Regelgenauigkeit als das dichte 12B-Modell erreichen.
  - Vorschlag: Unterstützung in `mlx-vlm` / `transformers` prüfen, gegen die Golden Ground Truths (`--mode gemma`) benchmarken und optional in den Einstellungen (`settings_service.py`) wählbar machen.

- [ ] **Evaluierung `baidu/Unlimited-OCR` (3B MoE / ~500M aktiv, MIT-Lizenz, R-SWA) als mehrseitige Stage-1-OCR-Engine** – mittel
  - Dateien: `scripts/run_benchmark.py`, `backend/services/extraction_service.py`, `backend/services/extraction_postprocess.py`
  - Befund: `Unlimited-OCR` nutzt Reference Sliding Window Attention (R-SWA) und komprimiert Seitenbilder über `DeepEncoder` (`SAM-ViT-B + CLIP-L`, `1024×1024` → ~256 visuelle Tokens/Seite), sodass mehrseitige Sequenzen in einem Durchlauf mit konstantem KV-Cache verarbeitet werden können (bessere seitenübergreifende Tabellen-, Satz- und Überschriftenkontinuität, aber potenzieller Detailverlust bei kleinen Indizes/Formeln gegenüber `1536 px` 32px-Grid und Prüfbedarf für deterministische `((num))`-Seitenmarker).
  - Vorschlag: Lokale MLX-/PyTorch-Ausführung (inkl. R-SWA-Attention und Docling-Layout-Fusion in 2–4-Seiten-Fenstern) als Benchmark-Kandidat in `scripts/run_benchmark.py` (`--mode ocr`) gegen `LightOnOCR-3` und `Infinity-Parser2-Flash` evaluieren.

### Asynchrone Verarbeitung & Betrieb

- [ ] **Gemma-Client in `llm_service.py` auf `AsyncOpenAI` / `httpx.AsyncClient` umstellen** – mittel
  - Datei: `backend/services/llm_service.py` (`start_rapid_mlx()`, `standardise_markdown()`)
  - Vorschlag: Synchrones `time.sleep`/`httpx.get` beim Server-Start und den synchronen `OpenAI`-Client im Thread-Pool durch `AsyncOpenAI` und `asyncio.sleep` ersetzen, damit Task-Abbrüche direkt per `asyncio.Task.cancel()` greifen.

- [ ] **Blockierende Datei- und DOCX-Operationen im Event-Loop auslagern (zu prüfen)** – niedrig
  - Datei: `backend/main.py` (DOCX-Erzeugung, Seitenmarker-Re-Injection, `save_meta`)
  - Vorschlag: Große Datei- und DOCX-Schritte über `asyncio.to_thread` auslagern, damit Status-Abfragen und Streams bei sehr großen Büchern flüssig bleiben.

- [ ] **Temporäre Mock-E2E-Tasks in `assets/output` automatisch bereinigen** – niedrig
  - Dateien: `playwright.config.ts`, `backend/services/task_manager.py`
  - Vorschlag: Für E2E-Mock-Läufe ein separates temporäres Ausgabeverzeichnis (`EBUCH_OUTPUT_DIR`) nutzen oder in `globalTeardown` aufräumen.

### Offene Fach-Entscheidungen (warten auf Rückmeldung)

- [ ] **Detailfragen zu komplexen MINT-Spezialfällen (Phase 2)** – mittel
  - Offene Rückfragen zur Übertragungspraxis: (1) exakte Überschriftenebene von Teilaufgaben ohne Kapitelnummerierung, (2) Behandlung eigenständiger Bildunterschriften ohne Bild, (3) Formatierung mehrspaltiger Kompetenzcheck-Tabellen, (4) Darstellung von Gefahren-/GHS-Piktogrammen und QR-Codes in Klammern, (5) Kriterium für das Auflösen von Abkürzungen.

---

## Abgeschlossene Meilensteine (Zusammenfassung)

- [x] **Plattformübergreifende Kompatibilität (macOS MLX, Linux/Windows CUDA & CPU) & Code-Konsolidierung** (20.10.):
  - `pyproject.toml` mit plattformspezifischen Markern (`sys_platform == 'darwin' and platform_machine == 'arm64'` für `mlx*`/`rapid-mlx`; `torch`, `transformers`, `accelerate`, `bitsandbytes` für Linux/Windows) ausgestattet.
  - Automatische Hardware-Erkennung (`cuda` → `mps` → `cpu`) in `main.py`, `extraction_service.py`, `lightonocr_extractor.py`, `infinity_parser_extractor.py`, `vlm_describer.py`, `feedback_analyzer.py` und `llm_service.py` (inkl. PyTorch/Transformers-Fallback und `LOCAL_LLM_BASE_URL`).
  - Ruhezustandssperre (`task_manager.py`) unterstützt `caffeinate` (macOS) und `systemd-inhibit` (Linux).
  - Gemeinsame Layout-/Callout-Helfer in `extraction_postprocess.py`, E2E-Mock-Fixtures in `mock_fixtures.py` und Custom-Benchmark-Scoring in `custom_benchmark_service.py` konsolidiert.
- [x] **Hill-Climbing Runden 1–3: OCR-Extraktion, `<Rahmen>`, `<Bild>`, MINT-Formeln, Gemma-Judge-Kalibrierung & Entkoppeltes Benchmarking** (20.10.):
  - Entkoppelte Benchmark-Profile `--mode ocr` (Track A) und `--mode gemma` (Track B) sowie de-saturiertes Composite-Scoring (`compute_doc_composite`) in `scripts/run_benchmark.py` eingeführt.
  - Fast-Suite (`--mode fast`, 19 offene Bücher) auf **94,6/100** (`<Rahmen>` `93,6 %`, `<Bild>` `98,6 %`, Tabellen `98,5 %`, Überschriften `97,1 %`, A11y-Linter `100 %`) gesteigert.
  - Gemma-Judge mit programmatischer FIBS-Referenz kalibriert (`calibrate_judge_scores_with_programmatic_reference`) und JSON-Parsing gehärtet.
- [x] **Multi-Format-Schulbuch-Generator (`scripts/generate_schoolbook_suite.py`) & Privates Testdaten-Repo (`ebuch-testdaten`)** (18.10.):
  - 12 deterministisch generierte Einzelfach-Schulbücher über 4 Buchformate (DIN A4, B5+, B5-Breitformat, Querformat-Doppelseite) + 7 OER-Referenzwerke mit 100/100 Linter-konformen Golden Ground Truths und realistischen Scan-Varianten (`*_scanned.pdf`).
  - Strikte Trennung zwischen öffentlichem Haupt-Repo (`ebuch-konvertierung`, 0-Treffer-N-Gramm-Audit) und privatem Begleit-Repo (`ebuch-testdaten`, 50 Muster-PDFs + 100 Golden Ground Truths).
- [x] **Lizenzbereinigung der OCR-Engines & Offline-Modelle** (17.10.):
  - Kommerziell bzw. durch AGPL eingeschränkte Engines entfernt; ausschließlich 100 % kommerziell freie Engines (`Docling`, `LightOnOCR-3-0.8B`, `Infinity-Parser2-Flash`) und lokale Modellpfade (`assets/models/`) im Einsatz.
- [x] **Robuste Task-Lifecycle-Architektur, Chunked Standardisation & Anti-Overfitting-Guards** (14.10.–19.10.):
  - Server-seitige Hintergrund-Jobs (`task_jobs.py`), `vlm_cache.json`-Persistenz, streng monotone Seitenmarker-Auflösung (`_resolve_page_sequence`), seitenweise Gemma-Standardisierung (`build_standardisation_chunks`) und generische Extraktions-Heuristiken ohne Testdaten-Overfitting.
