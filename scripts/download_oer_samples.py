"""Download authentic OER textbook samples from OpenStax (Biology, Chemistry, World History).

Downloads each textbook to a temporary file, extracts a realistic 4-page section with
authentic diagrams, callout boxes, and formulas, and saves it to testdata/.
Then removes the large temporary file to maintain repository lightness.
"""

import os
import urllib.request
from pypdf import PdfReader, PdfWriter

TARGETS = [
    {
        "name": "Biologie (Concepts of Biology)",
        "url": "https://assets.openstax.org/oscms-prodcms/media/documents/Concepts-Biology_-_WEB.pdf",
        "output": "testdata/openstax_biology_sample.pdf",
        "pages": (70, 74),  # Chapter 3: Cell Structure and Function
        "description": "Zellstrukturen, Mikroskopie-Abbildungen, Organellen und didaktische Infoboxen",
    },
    {
        "name": "Chemie (Chemistry 2e)",
        "url": "https://assets.openstax.org/oscms-prodcms/media/documents/chemistry-2e_-_WEB.pdf",
        "output": "testdata/openstax_chemistry_sample.pdf",
        "pages": (140, 144),  # Chemical Formulas and Bonding
        "description": "Molekülstrukturen, chemische Reaktionsgleichungen und Tabellen",
    },
    {
        "name": "Gesellschaftswissenschaften / Geschichte (World History Volume 1)",
        "url": "https://assets.openstax.org/oscms-prodcms/media/documents/World_History_Volume_1-WEB.pdf",
        "output": "testdata/openstax_history_sample.pdf",
        "pages": (110, 114),  # Ancient Civilizations & Trade Routes
        "description": "Historische Quellentexte, Zeitleisten, Karten mit Legenden und Randbemerkungen",
    },
]

def main():
    for target in TARGETS:
        out_path = target["output"]
        if os.path.exists(out_path):
            print(f"Skipping {target['name']}, already exists at {out_path}")
            continue

        tmp_file = f"/tmp/{os.path.basename(out_path)}"
        print(f"\n--- Downloading {target['name']} ---")
        print(f"URL: {target['url']}")
        urllib.request.urlretrieve(target['url'], tmp_file)
        file_size_mb = os.path.getsize(tmp_file) / (1024 * 1024)
        print(f"Downloaded {file_size_mb:.1f} MB. Extracting pages {target['pages'][0]}-{target['pages'][1]}...")

        reader = PdfReader(tmp_file)
        writer = PdfWriter()
        start_p, end_p = target["pages"]
        for p in range(start_p, min(end_p, len(reader.pages))):
            writer.add_page(reader.pages[p])

        with open(out_path, "wb") as f:
            writer.write(f)

        os.remove(tmp_file)
        sample_kb = os.path.getsize(out_path) / 1024
        print(f"Successfully created {out_path} ({sample_kb:.1f} KB)")

if __name__ == "__main__":
    main()
