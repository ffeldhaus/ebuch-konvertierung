# E-Buch Document Extraction & Standardization Leaderboard

This leaderboard tracks extraction accuracy, structural integrity, formula transcription fidelity, table reconstruction, image & `<Bild>` fidelity, `<Rahmen>` callout detection, page-number monotonicity (`((N))`), Word DOCX screen-reader bookmarks, and processing speed across integrated layout engines (**LightOnOCR-3-0.8B**, **Infinity-Parser2-Flash**, and **Docling**).

Evaluations are performed against **Golden Ground Truth** references using both multi-dimensional programmatic metrics and **LLM Judge evaluations** (Gemma 4 12B-it).

> **Multi-Tier Leaderboard Design:** Both fast/small regression checks (`--mode fast`, `--mode smoke`) and comprehensive multi-engine evaluations (`--suite core`, `--suite schoolbooks`, `--suite open_all`, `--mode full`) are tracked in dedicated sections below so fast runs never overwrite full multi-engine standings. Detailed per-document records for proprietary publisher textbooks reside exclusively in `../ebuch-testdaten/benchmarks/runs/`.

---

## 📊 0. Executive Quality Overview (Small / Fast vs. Large / Full Tiers)

| Benchmark Tier | Pipeline Scope | Latest Run | Docs (`N`) | Best Engine | Raw Score | FIBS 09/2025 Score | `<Bild>` | `<Rahmen>` | Page `((N))` | Speed (s/p) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| ⚡ **Tier 1: Fast Regression** (`--mode fast`) | Docling + Deterministic FIBS (`open_all`) | `20261020_230137` | **19** | **docling** | 90.4/100 | **94.6/100** | 98.6% | 93.6% | 100.0% | 0.55 s |
| 🧪 **Tier 2: Multi-Engine + Gemma Smoke** (`--mode smoke`) | All 3 OCR Engines + Gemma 4 12B (Smoke Subset) | `20261020_224457` | **2** | **lightonocr** | 96.1/100 | **97.7/100** | 100.0% | 98.0% | 100.0% | 18.22 s |
| 🏛️ **Tier 3: Comprehensive Open Suite** (`core` / `open_all`) | All 3 OCR Engines + Gemma 4 12B (Open Textbooks) | `20261018_125458` | **4** | **lightonocr** | 98.4/100 | **98.9/100** | 100.0% | 100.0% | 100.0% | 145.23 s |
| 🔒 **Tier 4: Extended Publisher Suite** (`--mode full`) | All 3 OCR Engines + Gemma 4 12B (Open + Publisher Corpus) | *Pending* | – | – | – | – | – | – | – | – |


---

## 🏆 1. Raw Extraction Standings (Before LLM Standardization)

*Measures the native visual/text extraction accuracy of each engine directly from the document.*

**Latest Multi-Engine Run:** 2026-10-18 12:54:58 (Run: `20261018_125458`)

### 📄 Digital Native PDFs
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (20%) | Tables (15%) | Formulas (15%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` | Page `((N))` | DOCX BM | Speed (s/p) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 4 | `📄 Digital` | **98.4/100** | 98.3% | 97.1% | 99.0% | 100.0% | 98.8% | 100.0% | 100.0% | 87.5% | 100.0% | 100.0% | 100.0% | **145.23 s** |
| **#2** | 🚀 **Docling** (IBM Research v2.140.0) | 4 | `📄 Digital` | **98.1/100** | 99.6% | 98.3% | 98.6% | 100.0% | 95.6% | 99.1% | 100.0% | 88.0% | 100.0% | 100.0% | 100.0% | **5.03 s** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 4 | `📄 Digital` | **98.1/100** | 98.3% | 95.7% | 97.9% | 100.0% | 100.0% | 99.1% | 100.0% | 87.5% | 100.0% | 100.0% | 100.0% | **31.18 s** |


### 📸 Scanned Image PDFs (300 DPI Raster)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (20%) | Tables (15%) | Formulas (15%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` | Page `((N))` | DOCX BM | Speed (s/p) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 4 | `📄 Scanned` | **98.4/100** | 98.3% | 97.1% | 99.0% | 100.0% | 98.8% | 100.0% | 100.0% | 87.5% | 100.0% | 100.0% | 100.0% | **116.78 s** |
| **#2** | 🚀 **Docling** (IBM Research v2.140.0) | 4 | `📄 Scanned` | **95.2/100** | 97.6% | 95.7% | 95.8% | 99.6% | 94.5% | 89.2% | 100.0% | 80.0% | 100.0% | 100.0% | 100.0% | **22.07 s** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 4 | `📄 Scanned` | **95.2/100** | 97.0% | 89.1% | 91.8% | 100.0% | 97.9% | 97.2% | 100.0% | 87.5% | 100.0% | 100.0% | 100.0% | **30.79 s** |


---

## 📜 2. Post-Gemma Übertragungsregeln Standings (`uebertragungsregeln_09_2025`)

*Measures the final document quality after Gemma 4 12B applies the **Übertragungsregeln (Stand September 2025)** profile (`_Hervorhebung_` default, `*fett*`, `%kursiv%`, `#Merkmal#`, `<Tabelle>`, `<Bild>`, `<Rahmen>`, `\t` list tabs, and `{n}` footnotes).*

### 📄 Digital Native PDFs
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 4 | `📄 Digital` | **98.9/100** | 97.7% | 96.5% | 99.0% | 100.0% | 98.8% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | **+0.5 pts** |
| **#2** | 🚀 **Docling** (IBM Research v2.140.0) | 4 | `📄 Digital` | **98.5/100** | 98.5% | 98.1% | 98.6% | 100.0% | 95.6% | 99.1% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | **+0.4 pts** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 4 | `📄 Digital` | **98.4/100** | 97.8% | 94.4% | 97.6% | 100.0% | 100.0% | 99.1% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | **+0.3 pts** |


### 📸 Scanned Image PDFs (300 DPI Raster)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 4 | `📄 Scanned` | **98.9/100** | 97.7% | 96.5% | 99.0% | 100.0% | 98.8% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | **+0.5 pts** |
| **#2** | 🚀 **Docling** (IBM Research v2.140.0) | 4 | `📄 Scanned` | **95.8/100** | 96.2% | 94.6% | 95.8% | 99.7% | 94.5% | 90.1% | 100.0% | 97.5% | 100.0% | 100.0% | 100.0% | **+0.6 pts** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 4 | `📄 Scanned` | **95.3/100** | 96.5% | 86.0% | 91.3% | 100.0% | 97.9% | 97.5% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | **+0.1 pts** |


---

## ⚡ 3. Fast Regression (`--mode fast`) & Multi-Engine Smoke (`--mode smoke`) Standings

### ⚡ Latest Fast Regression Run (`20261020_230137` – 2026-10-20 23:01:37, Deterministic FIBS Post-Process)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🚀 **Docling** (IBM Research v2.140.0) | 19 | `📄 Digital` | **94.6/100** | 98.1% | 96.6% | 93.7% | 90.1% | 86.1% | 93.1% | 98.6% | 99.9% | 93.6% | 100.0% | 100.0% | **+4.2 pts** |

### 🧪 Latest Multi-Engine + Gemma Smoke Run (`20261020_224457` – 2026-10-20 22:44:57)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 2 | `📄 Digital` | **97.7/100** | 98.5% | 94.6% | 97.3% | 98.9% | 101.4% | 91.3% | 100.0% | 99.0% | 98.0% | 100.0% | 100.0% | **+1.6 pts** |
| **#2** | 🚀 **Docling** (IBM Research v2.140.0) | 2 | `📄 Digital` | **97.4/100** | 98.5% | 95.5% | 97.1% | 97.8% | 96.4% | 94.7% | 100.0% | 100.0% | 98.0% | 100.0% | 100.0% | **+1.4 pts** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 2 | `📄 Digital` | **81.6/100** | 98.5% | 84.2% | 76.2% | 50.0% | 101.4% | 91.5% | 100.0% | 99.0% | 30.1% | 100.0% | 100.0% | **-4.9 pts** |


---

## 📚 4. Textbook Category & Format Breakdown

*Breaks down quality across textbook types and page geometries (DIN A4, B5+, B5-Breitformat, Querformat/Doppelseite `((N)) / ((N+1))`, and University STEM).*

*Source Run: `20261020_230137` (2026-10-20 23:01:37)*

| Textbook Category / Format | Engine | Docs (`N`) | Raw Score | FIBS 09/2025 Score | Recall | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Page `((N))` | A11y |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Core Baseline (4)** | `docling` | 4 | 90.9/100 | **92.8/100** | 99.7% | 97.8% | 71.9% | 50.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| **OpenStax STEM/Uni (3)** | `docling` | 3 | 75.7/100 | **86.8/100** | 93.2% | 73.0% | 77.3% | 100.0% | 92.7% | 83.6% | 100.0% | 100.0% |
| **Grundschule & Doppelseite (3)** | `docling` | 3 | 97.0/100 | **98.1/100** | 98.6% | 97.3% | 95.0% | 99.6% | 100.0% | 95.9% | 100.0% | 100.0% |
| **Sekundarstufe I (5)** | `docling` | 5 | 96.2/100 | **98.2/100** | 99.0% | 98.6% | 101.0% | 98.5% | 100.0% | 95.6% | 100.0% | 99.6% |
| **Sekundarstufe II & Verzeichnisse (4)** | `docling` | 4 | 88.7/100 | **95.2/100** | 98.5% | 93.6% | 85.5% | 98.8% | 100.0% | 93.8% | 100.0% | 100.0% |

---

## ⚖️ Engine Architecture & Commercial Licensing Matrix

| Engine | Primary Architecture | License | Commercial Usability | Role in Production Pipeline |
| :--- | :--- | :---: | :---: | :--- |
| **LightOnOCR-3-0.8B** | Compact End-to-End Vision-Language Model (~0.8B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary Compact VLM Engine**: High-accuracy formula/table/scan OCR with minimal memory footprint (~1.7 GB BF16) on Apple Silicon & CPU/CUDA. |
| **Infinity-Parser2-Flash** | End-to-End Vision-Language Model (~2B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary High-Capacity VLM Engine**: High-fidelity multimodal extraction for complex STEM formulas, native math LaTeX, Markdown tables, and scanned/raster PDF OCR. |
| **Docling** | Granite-DocLayNet Layout (`RT-DETR-v2`) + `TableFormer` + Unicode Math Normalization | MIT / Apache 2.0 | ✅ Permitted | **High-Speed Layout Engine**: Ultra-fast structural extraction, BBox heading hierarchy clustering, and table parsing. |

---

## 📜 Historical Runs Log

### Run `20261020_230137` (2026-10-20 23:01:37) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.140.0 | Apache 2.0 *(Commercial)* | 90.4 | **94.6** | 93.1% | 86.1% | 90.1% | 98.6% | 93.6% | 0.55 s |

### Run `20261020_224457` (2026-10-20 22:44:57) — Tier: `smoke`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 2 | v2.140.0 | Apache 2.0 *(Commercial)* | 96.0 | **97.4** | 94.7% | 96.4% | 97.8% | 100.0% | 98.0% | 1.79 s |
| lightonocr | 2 | v0.7.2 | Apache 2.0 *(Commercial)* | 96.1 | **97.7** | 91.3% | 101.4% | 98.9% | 100.0% | 98.0% | 18.22 s |
| infinity | 2 | v0.7.2 | Apache 2.0 *(Commercial)* | 86.5 | **81.6** | 91.5% | 101.4% | 50.0% | 100.0% | 30.1% | 21.11 s |

### Run `20261020_213800` (2026-10-20 21:38:00) — Tier: `smoke`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 3 | v2.140.0 | Apache 2.0 *(Commercial)* | 87.7 | **88.7** | 77.7% | 96.4% | 98.5% | 98.1% | 78.1% | 1.34 s |
| lightonocr | 2 | v0.7.2 | Apache 2.0 *(Commercial)* | 95.8 | **96.2** | 88.2% | 101.4% | 97.8% | 100.0% | 98.0% | 18.22 s |

### Run `20261020_213242` (2026-10-20 21:32:42) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.140.0 | Apache 2.0 *(Commercial)* | 90.5 | **94.7** | 93.8% | 86.1% | 90.1% | 97.2% | 94.6% | 0.46 s |

### Run `20261020_201744` (2026-10-20 20:17:44) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.140.0 | Apache 2.0 *(Commercial)* | 90.9 | **94.8** | 94.1% | 71.0% | 99.1% | 97.2% | 94.0% | 0.46 s |

### Run `20261020_163726` (2026-10-20 16:37:26) — Tier: `smoke`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 3 | v2.121.0 | Apache 2.0 *(Commercial)* | 87.1 | **89.8** | 77.2% | 91.5% | 98.2% | 97.0% | 76.0% | 0.93 s |
| lightonocr | 3 | v0.6.15 | Apache 2.0 *(Commercial)* | 87.7 | **88.7** | 58.8% | 94.9% | 98.2% | 98.5% | 76.4% | 13.82 s |
| infinity | 3 | v0.6.15 | Apache 2.0 *(Commercial)* | 87.5 | **86.8** | 55.9% | 90.5% | 98.2% | 97.2% | 71.3% | 48.1 s |

### Run `20261020_133819` (2026-10-20 13:38:19) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.121.0 | Apache 2.0 *(Commercial)* | 92.3 | **94.5** | 92.6% | 86.6% | 99.5% | 94.4% | 73.4% | 0.38 s |

### Run `20261019_211337` (2026-10-19 21:13:37) — Tier: `open_multi_engine`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.121.0 | Apache 2.0 *(Commercial)* | 89.2 | **89.7** | 88.8% | 82.9% | 97.4% | 85.8% | 18.5% | 0.42 s |
| lightonocr | 1 | v0.6.15 | Apache 2.0 *(Commercial)* | 98.9 | **98.9** | 100.0% | 100.0% | 100.0% | 100.0% | 77.1% | 129.57 s |
| infinity | 2 | v0.6.15 | Apache 2.0 *(Commercial)* | 84.6 | **82.2** | 89.8% | 87.0% | 50.0% | 91.7% | 23.6% | 21.11 s |

### Run `20261018_125458` (2026-10-18 12:54:58)
| Engine | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | v2.137.0 | Apache 2.0 *(Commercial)* | 98.1 | **98.5** | 99.1% | 95.6% | 100.0% | 5.03 s |
| infinity | v5.19.0 | Apache 2.0 *(Commercial)* | 98.1 | **98.4** | 99.1% | 100.0% | 100.0% | 31.18 s |
| lightonocr | v5.19.0 | Apache 2.0 *(Commercial)* | 98.4 | **98.9** | 100.0% | 98.8% | 100.0% | 145.23 s |

### Run `20261017_134936` (2026-10-17 13:49:36)
| Engine | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | v2.137.0 | Apache 2.0 *(Commercial)* | 99.2 | **99.3** | 100.0% | 100.0% | 100.0% | 4.57 s |
| infinity | v5.19.0 | Apache 2.0 *(Commercial)* | 98.4 | **98.8** | 99.1% | 100.0% | 100.0% | 32.62 s |
| lightonocr | v5.19.0 | Apache 2.0 *(Commercial)* | 98.7 | **98.6** | 100.0% | 100.0% | 100.0% | 145.23 s |
