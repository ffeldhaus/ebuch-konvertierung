# E-Buch Document Extraction & Standardization Leaderboard

This leaderboard tracks extraction accuracy, structural integrity, formula transcription fidelity, table reconstruction, image & `<Bild>` fidelity, `<Rahmen>` callout detection, page-number monotonicity (`((N))`), Word DOCX screen-reader bookmarks, and processing speed across integrated layout engines (**LightOnOCR-3-0.8B**, **Infinity-Parser2-Flash**, and **Docling**).

Evaluations are performed against **Golden Ground Truth** references using both multi-dimensional programmatic metrics and **LLM Judge evaluations** (Gemma 4 12B-it).

> **Multi-Tier Leaderboard Design:** Both fast/small regression checks (`--mode fast`, `--mode smoke`) and comprehensive multi-engine evaluations (`--suite core`, `--suite schoolbooks`, `--suite open_all`, `--mode full`) are tracked in dedicated sections below so fast runs never overwrite full multi-engine standings. Detailed per-document records for proprietary publisher textbooks reside exclusively in `../ebuch-testdaten/benchmarks/runs/`.

---

## 📊 0. Executive Quality Overview (Small / Fast vs. Large / Full Tiers)

| Benchmark Tier | Pipeline Scope | Latest Run | Docs (`N`) | Best Engine | Raw Score | FIBS 09/2025 Score | `<Bild>` | `<Rahmen>` | Page `((N))` | Speed (s/p) |
| :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| ⚡ **Tier 1: Fast Regression** (`--mode fast`) | Docling + Deterministic FIBS (`open_all`) | `20261123_222834` | **19** | **docling** | 87.0/100 | **96.7/100** | 97.2% | 95.6% | 100.0% | 6.55 s |
| 🧪 **Tier 2: Multi-Engine + Gemma Smoke** (`--mode smoke`) | All 3 OCR Engines + Gemma 4 12B (Smoke Subset) | `20261020_224457` | **2** | **lightonocr** | 96.1/100 | **97.7/100** | 100.0% | 98.0% | 100.0% | 18.22 s |
| 🏛️ **Tier 3: Comprehensive Open Suite** (`core` / `open_all`) | All 3 OCR Engines + Gemma 4 12B (Open Textbooks) | `20261120_091049` | **19** | **docling** | 90.2/100 | **90.7/100** | 96.7% | 85.8% | 100.0% | 1.18 s |
| 🔒 **Tier 4: Extended Publisher Suite** (`--mode full`) | All 3 OCR Engines + Gemma 4 12B (Open + Publisher Corpus) | `20261105_212319` | **10** | **lightonocr** | 87.2/100 | **91.0/100** | 94.5% | 76.4% | 96.3% | 59.43 s |


---

## 🏆 1. Raw Extraction Standings (Before LLM Standardization)

*Measures the native visual/text extraction accuracy of each engine directly from the document.*

**Latest Multi-Engine Run:** 2026-11-20 09:10:49 (Run: `20261120_091049`)

### 📄 Digital Native PDFs
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (20%) | Tables (15%) | Formulas (15%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` | Page `((N))` | DOCX BM | Speed (s/p) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🚀 **Docling** (IBM Research v2.152.0) | 19 | `📄 Digital` | **90.2/100** | 98.6% | 97.4% | 92.8% | 99.5% | 77.6% | 93.1% | 91.7% | 36.8% | 100.0% | 100.0% | 100.0% | **1.18 s** |
| **#2** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 6 | `📄 Digital` | **84.5/100** | 97.9% | 97.5% | 87.2% | 100.0% | 68.2% | 82.1% | 85.2% | 21.7% | 100.0% | 100.0% | 100.0% | **14.97 s** |


---

## 📜 2. Post-Gemma Übertragungsregeln Standings (`uebertragungsregeln_09_2025`)

*Measures the final document quality after Gemma 4 12B applies the **Übertragungsregeln (Stand September 2025)** profile (`_Hervorhebung_` default, `*fett*`, `%kursiv%`, `#Merkmal#`, `<Tabelle>`, `<Bild>`, `<Rahmen>`, `\t` list tabs, and `{n}` footnotes).*

### 📄 Digital Native PDFs
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🚀 **Docling** (IBM Research v2.152.0) | 19 | `📄 Digital` | **90.7/100** | 98.1% | 96.8% | 89.0% | 74.9% | 86.4% | 82.4% | 96.7% | 98.9% | 85.8% | 100.0% | 100.0% | **+0.5 pts** |
| **#2** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 6 | `📄 Digital` | **89.7/100** | 98.8% | 97.2% | 87.5% | 85.4% | 84.5% | 69.5% | 96.2% | 100.0% | 80.7% | 100.0% | 100.0% | **+5.2 pts** |


---

## ⚡ 3. Fast Regression (`--mode fast`) & Multi-Engine Smoke (`--mode smoke`) Standings

### ⚡ Latest Fast Regression Run (`20261123_222834` – 2026-11-23 22:28:34, Deterministic FIBS Post-Process)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🚀 **Docling** (IBM Research v2.152.0) | 19 | `📄 Digital` | **96.7/100** | 97.9% | 96.3% | 96.2% | 99.1% | 94.6% | 94.5% | 97.2% | 98.8% | 95.6% | 100.0% | 98.2% | **+9.7 pts** |

### 🧪 Latest Multi-Engine + Gemma Smoke Run (`20261020_224457` – 2026-10-20 22:44:57)
| Rank | Extraction Engine | Docs (`N`) | Source | Score | Recall (15%) | Flow (10%) | Judge (18%) | Tables (12%) | Formulas (12%) | Headings (10%) | `<Bild>` (10%) | A11y (5%) | `<Rahmen>` (8%) | Page `((N))` | DOCX BM | Improvement |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **#1** | 🔥 **LightOnOCR-3-0.8B** (LightOn AI v0.7.2) | 2 | `📄 Digital` | **97.7/100** | 98.5% | 94.6% | 97.3% | 98.9% | 101.4% | 91.3% | 100.0% | 99.0% | 98.0% | 100.0% | 100.0% | **+1.6 pts** |
| **#2** | 🚀 **Docling** (IBM Research v2.152.0) | 2 | `📄 Digital` | **97.4/100** | 98.5% | 95.5% | 97.1% | 97.8% | 96.4% | 94.7% | 100.0% | 100.0% | 98.0% | 100.0% | 100.0% | **+1.4 pts** |
| **#3** | ⚡ **Infinity-Parser2-Flash** (INF Tech v0.7.2) | 2 | `📄 Digital` | **81.6/100** | 98.5% | 84.2% | 76.2% | 50.0% | 101.4% | 91.5% | 100.0% | 99.0% | 30.1% | 100.0% | 100.0% | **-4.9 pts** |


---

## 📚 4. Textbook Category & Format Breakdown

*Breaks down quality across textbook types and page geometries (DIN A4, B5+, B5-Breitformat, Querformat/Doppelseite `((N)) / ((N+1))`, and University STEM).*

*Source Run: `20261123_222834` (2026-11-23 22:28:34)*

| Textbook Category / Format | Engine | Docs (`N`) | Raw Score | FIBS 09/2025 Score | Recall | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Page `((N))` | A11y |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Core Baseline (4)** | `docling` | 4 | 93.6/100 | **98.7/100** | 99.2% | 96.7% | 100.0% | 97.5% | 100.0% | 99.2% | 100.0% | 100.0% |
| **OpenStax STEM/Uni (3)** | `docling` | 3 | 74.7/100 | **91.3/100** | 95.8% | 78.3% | 96.7% | 100.0% | 94.9% | 87.0% | 100.0% | 93.3% |
| **Grundschule & Doppelseite (3)** | `docling` | 3 | 83.1/100 | **97.9/100** | 96.1% | 98.0% | 100.0% | 100.0% | 100.0% | 97.3% | 100.0% | 100.0% |
| **Sekundarstufe I (5)** | `docling` | 5 | 90.5/100 | **98.1/100** | 98.6% | 98.6% | 100.0% | 98.5% | 100.0% | 96.1% | 100.0% | 99.6% |
| **Sekundarstufe II & Verzeichnisse (4)** | `docling` | 4 | 88.1/100 | **95.9/100** | 98.3% | 96.5% | 89.5% | 99.8% | 92.5% | 98.5% | 100.0% | 100.0% |

---

## ⚖️ Engine Architecture & Commercial Licensing Matrix

| Engine | Primary Architecture | License | Commercial Usability | Role in Production Pipeline |
| :--- | :--- | :---: | :---: | :--- |
| **LightOnOCR-3-0.8B** | Compact End-to-End Vision-Language Model (~0.8B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary Compact VLM Engine**: High-accuracy formula/table/scan OCR with minimal memory footprint (~1.7 GB BF16) on Apple Silicon & CPU/CUDA. |
| **Infinity-Parser2-Flash** | End-to-End Vision-Language Model (~2B Qwen3.5 via MLX-VLM / Transformers) + Docling Layout | Apache 2.0 | ✅ Permitted | **Primary High-Capacity VLM Engine**: High-fidelity multimodal extraction for complex STEM formulas, native math LaTeX, Markdown tables, and scanned/raster PDF OCR. |
| **Docling** | Granite-DocLayNet Layout (`RT-DETR-v2`) + `TableFormer` + Unicode Math Normalization | MIT / Apache 2.0 | ✅ Permitted | **High-Speed Layout Engine**: Ultra-fast structural extraction, BBox heading hierarchy clustering, and table parsing. |

---

## 📜 Historical Runs Log

### Run `20261123_222834` (2026-11-23 22:28:34) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.152.0 | Apache 2.0 *(Commercial)* | 87.0 | **96.7** | 94.5% | 94.6% | 99.1% | 97.2% | 95.6% | 6.55 s |


### Run `20261123_215430` (2026-11-23 21:54:30) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.151.1 | Apache 2.0 *(Commercial)* | 87.0 | **95.7** | 94.5% | 81.4% | 99.1% | 97.2% | 95.6% | 1.5 s |

### Run `20261123_214555` (2026-11-23 21:45:55) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.151.1 | Apache 2.0 *(Commercial)* | 87.0 | **95.7** | 94.5% | 81.4% | 99.1% | 97.2% | 95.6% | 1.02 s |

### Run `20261120_091049` (2026-11-20 09:10:49) — Tier: `open_multi_engine`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.151.1 | Apache 2.0 *(Commercial)* | 90.2 | **90.7** | 82.4% | 86.4% | 74.9% | 96.7% | 85.8% | 1.18 s |
| lightonocr | 6 | v0.7.2 | Apache 2.0 *(Commercial)* | 84.5 | **89.7** | 69.5% | 84.5% | 85.4% | 96.2% | 80.7% | 14.97 s |

### Run `20261120_133353` (2026-11-20 13:33:53) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.151.1 | Apache 2.0 *(Commercial)* | 87.0 | **94.8** | 94.5% | 88.8% | 84.6% | 97.2% | 95.8% | 0.84 s |

### Run `20261120_090845` (2026-11-20 09:08:45) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.151.1 | Apache 2.0 *(Commercial)* | 90.2 | **95.2** | 94.5% | 100.0% | 84.6% | 97.2% | 95.8% | 0.85 s |

### Run `20261105_212319` (2026-11-05 21:23:19) — Tier: `full_extended`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 10 | v2.148.0 | Apache 2.0 *(Commercial)* | 88.4 | **90.9** | 81.6% | 93.9% | 88.5% | 98.9% | 77.0% | 1.44 s |
| lightonocr | 10 | v0.7.2 | Apache 2.0 *(Commercial)* | 87.2 | **91.0** | 80.0% | 95.3% | 88.5% | 94.5% | 76.4% | 59.43 s |
| infinity | 5 | v0.7.2 | Apache 2.0 *(Commercial)* | 88.2 | **93.8** | 81.7% | 97.8% | 90.5% | 100.0% | 89.9% | 36.14 s |

### Run `20261104_215559` (2026-11-04 21:55:59) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.147.0 | Apache 2.0 *(Commercial)* | 89.9 | **96.1** | 94.1% | 89.7% | 99.2% | 98.6% | 93.5% | 1.12 s |

### Run `20261019_211337` (2026-10-19 21:13:37) — Tier: `partial`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.121.0 | Apache 2.0 *(Commercial)* | 89.2 | **89.7** | 88.8% | 82.9% | 97.4% | 85.8% | 18.5% | 0.42 s |
| lightonocr | 1 | v0.6.15 | Apache 2.0 *(Commercial)* | 98.9 | **98.9** | 100.0% | 100.0% | 100.0% | 100.0% | 77.1% | 129.57 s |
| infinity | 2 | v0.6.15 | Apache 2.0 *(Commercial)* | 84.6 | **82.2** | 89.8% | 87.0% | 50.0% | 91.7% | 23.6% | 21.11 s |

### Run `20261029_121704` (2026-10-29 12:17:04) — Tier: `fast`
| Engine | Docs (`N`) | Version | License | Raw Score | Übertragungsregeln 09/25 | Headings | Formulas | Tables | `<Bild>` | `<Rahmen>` | Speed (s/page) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| docling | 19 | v2.144.0 | Apache 2.0 *(Commercial)* | 90.0 | **96.1** | 94.8% | 89.7% | 99.2% | 97.2% | 94.3% | 1.12 s |

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

