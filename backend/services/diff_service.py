"""Side-by-side token diffing and classification for Markdown comparison."""

import difflib
import re


def classify_token(text: str) -> str:
    """Classify a diff token into 'tag', 'format', 'text', or 'none'."""
    stripped = text.strip()
    if not stripped:
        return "none"
    # 1. E-Buch tags or page numbers (like <Bild>, ((45)))
    if re.match(r"^<[^>]+>$", stripped) or re.match(r"^\(\(\d+\)\)$", stripped):
        return "tag"
    # 2. Markdown emphasis markers (like **, *, %, _)
    if stripped in ["**", "*", "%", "_"]:
        return "format"
    # 3. Text changes containing alphanumeric characters
    if re.search(r"[a-zA-Z0-9äöüÄÖÜß]", stripped):
        return "text"
    # 4. Punctuation
    return "none"

def strip_ground_truth_preamble(text: str) -> str:
    """Strips ground truth metadata preamble, book headers, and <Anmerkung>...</Anmerkung> tags
    occurring before the first page marker ((num)).
    If no page marker is found, strips <Anmerkung> blocks and leading metadata headers.
    """
    if not text:
        return ""

    # 1. If a page marker like ((80)) or ((1)) exists, strip everything preceding the first page marker
    match = re.search(r"(?:^|\n)\s*(\(\(\s*\d+\s*\)\))", text)
    if match:
        return text[match.start(1):].lstrip()

    # 2. Fallback: if no page marker exists, remove <Anmerkung>...</Anmerkung> blocks
    cleaned = re.sub(r"<Anmerkung\b[^>]*>.*?</Anmerkung>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Strip common header lines at the very beginning (e.g. Fach:, Titel:, ISBN:, etc.)
    lines = cleaned.splitlines()
    start_idx = 0
    header_patterns = [
        r"^(?:Fach|Titel|Verlag|ISBN|Seite|Übertragen|Übertragungsanstalt|Stiftstr|Datum)\s*:",
        r"^\d{5}\s+[A-Za-zäöüÄÖÜß\s]+$",
    ]
    for i, line in enumerate(lines):
        line_s = line.strip()
        if not line_s:
            continue
        if any(re.match(p, line_s, re.IGNORECASE) for p in header_patterns):
            start_idx = i + 1
        else:
            break

    return "\n".join(lines[start_idx:]).lstrip()


def normalize_images_for_diff(text: str) -> str:
    """Normalizes image descriptions (inside <Bild>...</Bild> or ![...](...))
    so that variable AI/manual description wording is ignored during visual diffing,
    while preserving the presence and positioning of the <Bild> tag.
    """
    if not text:
        return ""
    text = re.sub(r"<Bild\b[^>]*>.*?</Bild>", "<Bild></Bild>", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"!\[.*?\]\([^)]+\)", "<Bild></Bild>", text)
    return text


def extract_document_components(text: str) -> dict:
    """Extracts floating and out-of-flow blocks (<Bild>, <Tabelle>/Markdown Tables, <Rahmen>) from document text.

    Returns:
    {
        "clean_body": str,  # Body flow with floating blocks stripped and whitespace normalized
        "images": list[str],  # List of raw image blocks (<Bild>...</Bild>)
        "tables": list[str],  # List of raw table blocks (<Tabelle>...</Tabelle> or |...|)
        "boxes": list[str]    # List of raw callout/sidebar blocks (<Rahmen>...</Rahmen>)
    }
    """
    if not text:
        return {"clean_body": "", "images": [], "tables": [], "boxes": []}

    images = []
    tables = []
    boxes = []

    # 1. Extract <Bild>...</Bild>
    def bild_cb(m):
        images.append(m.group(0).strip())
        return "\n"
    
    cur_text = re.sub(r"<Bild\b[^>]*>.*?</Bild>", bild_cb, text, flags=re.DOTALL | re.IGNORECASE)
    
    # Also extract markdown images ![...](...)
    def md_img_cb(m):
        images.append(f"<Bild> {m.group(0).strip()} </Bild>")
        return "\n"
    cur_text = re.sub(r"!\[.*?\]\([^)]+\)", md_img_cb, cur_text)

    # 2. Extract <Tabelle>...</Tabelle>, resolved small tables (<Anmerkung>\nDie folgende Tabelle wurde aufgelöst.\n</Anmerkung>...), or HTML <table>...</table>
    def tab_cb(m):
        tables.append(m.group(0).strip())
        return "\n"
    cur_text = re.sub(r"<Tabelle\b[^>]*>.*?</Tabelle>", tab_cb, cur_text, flags=re.DOTALL | re.IGNORECASE)
    cur_text = re.sub(
        r"<Anmerkung>\s*Die folgende Tabelle wurde aufgelöst\.\s*</Anmerkung>(?:\s*\n+[^\n#<]+){1,4}",
        tab_cb,
        cur_text,
        flags=re.IGNORECASE,
    )
    cur_text = re.sub(r"<table\b[^>]*>.*?</table>", tab_cb, cur_text, flags=re.DOTALL | re.IGNORECASE)

    # Extract markdown table blocks (2 or more consecutive lines starting and ending with |)
    def md_tab_cb(m):
        tables.append(m.group(0).strip())
        return "\n"
    cur_text = re.sub(r"(?:^[ \t]*\|.+?\|[ \t]*(?:\n|$)){2,}", md_tab_cb, cur_text, flags=re.MULTILINE)

    # 3. Extract <Rahmen>...</Rahmen>
    def rahmen_cb(m):
        boxes.append(m.group(0).strip())
        return "\n"
    cur_text = re.sub(r"<Rahmen\b[^>]*>.*?</Rahmen>", rahmen_cb, cur_text, flags=re.DOTALL | re.IGNORECASE)

    # Clean up excessive newlines
    clean_body = re.sub(r"\n{3,}", "\n\n", cur_text).strip()

    return {
        "clean_body": clean_body,
        "images": images,
        "tables": tables,
        "boxes": boxes
    }


def _diff_text_segment(text1: str, text2: str) -> list[dict]:
    """Helper to diff two text chunks at token level."""
    def tokenize(text):
        if not text:
            return []
        return re.findall(r"(<[^>]+>|\(\(\d+\)\)|\*\*|\*|%|_|[a-zA-Z0-9äöüÄÖÜß]+|[^\w\s]|\s+)", text)

    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)
    matcher = difflib.SequenceMatcher(lambda x: x.isspace(), tokens1, tokens2, autojunk=False)
    diff_segments = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for t in tokens1[i1:i2]:
                diff_segments.append({"type": "equal", "text": t, "category": "none"})
        elif tag == 'replace':
            for t in tokens1[i1:i2]:
                diff_segments.append({"type": "delete", "text": t, "category": classify_token(t)})
            for t in tokens2[j1:j2]:
                diff_segments.append({"type": "insert", "text": t, "category": classify_token(t)})
        elif tag == 'delete':
            for t in tokens1[i1:i2]:
                diff_segments.append({"type": "delete", "text": t, "category": classify_token(t)})
        elif tag == 'insert':
            for t in tokens2[j1:j2]:
                diff_segments.append({"type": "insert", "text": t, "category": classify_token(t)})

    # Merge consecutive identical segments
    if not diff_segments:
        return []

    merged = [diff_segments[0]]
    for s in diff_segments[1:]:
        last = merged[-1]
        if last["type"] == s["type"] and last["category"] == s["category"]:
            last["text"] += s["text"]
        else:
            merged.append(s)

    return merged


def get_diff_highlighting(raw_text: str, std_text: str, strip_preamble: bool = True, ignore_image_descriptions: bool = True) -> list[dict]:
    """Compares raw_text (or ground truth) and std_text with floating block separation.
    Compares body text linearly, and appends structured diff sections for Tables, Images, and Rahmen.
    """
    if strip_preamble and raw_text:
        raw_text = strip_ground_truth_preamble(raw_text)

    # 1. Extract floating components for both texts
    comp_raw = extract_document_components(raw_text)
    comp_std = extract_document_components(std_text)

    # 2. Main body flow diff
    all_segments = _diff_text_segment(comp_raw["clean_body"], comp_std["clean_body"])

    # 3. Dedicated Tables Diff
    if comp_raw["tables"] or comp_std["tables"]:
        header = "\n\n### 📊 Tabellen-Vergleich\n"
        all_segments.append({"type": "equal", "text": header, "category": "none"})
        max_t = max(len(comp_raw["tables"]), len(comp_std["tables"]))
        for idx in range(max_t):
            t_raw = comp_raw["tables"][idx] if idx < len(comp_raw["tables"]) else ""
            t_std = comp_std["tables"][idx] if idx < len(comp_std["tables"]) else ""
            t_segments = _diff_text_segment(t_raw, t_std)
            all_segments.extend(t_segments)
            all_segments.append({"type": "equal", "text": "\n", "category": "none"})

    # 4. Dedicated Images / Figures Diff
    if comp_raw["images"] or comp_std["images"]:
        header = "\n\n### 🖼️ Abbildungen & Bildbeschreibungen (<Bild>)\n"
        all_segments.append({"type": "equal", "text": header, "category": "none"})
        max_i = max(len(comp_raw["images"]), len(comp_std["images"]))
        for idx in range(max_i):
            i_raw = comp_raw["images"][idx] if idx < len(comp_raw["images"]) else ""
            i_std = comp_std["images"][idx] if idx < len(comp_std["images"]) else ""
            # If ignore_image_descriptions is true, normalize tag inner descriptions for the diff
            if ignore_image_descriptions:
                i_raw_norm = normalize_images_for_diff(i_raw) if i_raw else ""
                i_std_norm = normalize_images_for_diff(i_std) if i_std else ""
                i_segments = _diff_text_segment(i_raw_norm, i_std_norm)
            else:
                i_segments = _diff_text_segment(i_raw, i_std)
            all_segments.extend(i_segments)
            all_segments.append({"type": "equal", "text": "\n", "category": "none"})

    # 5. Dedicated Boxes / Rahmen Diff
    if comp_raw["boxes"] or comp_std["boxes"]:
        header = "\n\n### 📦 Infokästen & Rahmen (<Rahmen>)\n"
        all_segments.append({"type": "equal", "text": header, "category": "none"})
        max_b = max(len(comp_raw["boxes"]), len(comp_std["boxes"]))
        for idx in range(max_b):
            b_raw = comp_raw["boxes"][idx] if idx < len(comp_raw["boxes"]) else ""
            b_std = comp_std["boxes"][idx] if idx < len(comp_std["boxes"]) else ""
            b_segments = _diff_text_segment(b_raw, b_std)
            all_segments.extend(b_segments)
            all_segments.append({"type": "equal", "text": "\n", "category": "none"})

    return all_segments
