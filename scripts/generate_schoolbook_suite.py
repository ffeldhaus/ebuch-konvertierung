#!/usr/bin/env python3
"""
Deterministic Generator for the German Schoolbook Benchmark & Test Suite.

Generates 12 realistic, single-subject, single-language German & English schoolbook PDFs across
Grundschule, Sekundarstufe I, and Sekundarstufe II in 4 authentic book geometries
(DIN A4 210x297 mm, B5+ 190x260 mm, B5-Breitformat 195x260 mm, and Querformat/Doppelseite 240x170 mm), along with:
  - 300-DPI scan-degraded counterparts (*_scanned.pdf) with paper tint, subtle skew, and scan noise
  - Authentic publisher difficulty icon systems (squares □/◩/■, stars ★/★★/★★★, diamonds ◇/◈/◆, circles ○/◐/●)
    and books without difficulty indicators, with zero bracketed instruction leakage in PDFs
  - 2-column scientific textbook layouts for Sekundarstufe II Chemie and Biologie
  - High-resolution programmatic figures (charts, OpenStreetMap cartography, geometric drawings, organic chemistry structures)
  - Canonical Golden Ground Truth Markdown files in testdata/golden/:
      * {doc}.raw.golden.md
      * {doc}.uebertragungsregeln_09_2025.golden.md
  - Book-specific rules files (*_rules.txt) and updated entries in testdata/golden/golden_image_metadata.json

Strict Copyright & Licensing Policy:
  - Synthesized texts, tasks, tables, plots, chemical structures, and illustrations are
    100% Copyright-Free (Creative Commons CC0 1.0 Universal / Apache-2.0).
  - Cartographic base layers for Upper Rhine Graben and St Ives Bay use OpenStreetMap® data
    licensed under the Open Data Commons Open Database License (ODbL 1.0) with full attribution:
    "© OpenStreetMap-Mitwirkende (ODbL 1.0, openstreetmap.org/copyright)".
  - Built exclusively with ReportLab, Pillow, NumPy, and pypdfium2 (no AGPL tools).
"""

import json
import math
import os
import random
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEST_DATA_DIR = os.path.join(PROJECT_ROOT, "testdata")
FIGURES_DIR = os.path.join(TEST_DATA_DIR, "figures")
OSM_CACHE_DIR = os.path.join(FIGURES_DIR, "osm_cache")
GOLDEN_DIR = os.path.join(TEST_DATA_DIR, "golden")
GOLDEN_META_PATH = os.path.join(GOLDEN_DIR, "golden_image_metadata.json")

PAGE_W, PAGE_H = A4  # 595.27559 x 841.88976 pt


# ---------------------------------------------------------------------------
# Font Registration (DejaVu TrueType with full Unicode / IPA / Math coverage)
# ---------------------------------------------------------------------------

def _find_font_file(candidates: List[str]) -> Optional[str]:
    """Returns the first existing TrueType font path across Linux, macOS, and Windows."""
    search_dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/TTF",
        "/opt/homebrew/share/fonts",
        "/usr/local/share/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "/System/Library/Fonts",
        "C:/Windows/Fonts",
    ]
    for candidate in candidates:
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        for sdir in search_dirs:
            full = os.path.join(sdir, candidate)
            if os.path.exists(full):
                return full
    return None


def register_fonts() -> Dict[str, str]:
    """Registers DejaVu / system TrueType fonts across Linux, macOS, and Windows with safe fallbacks."""
    ttf_map = {
        "Sans": ("DejaVuSans", ["DejaVuSans.ttf", "Arial Unicode.ttf", "Arial.ttf"], "Helvetica"),
        "SansBold": ("DejaVuSans-Bold", ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"], "Helvetica-Bold"),
        "SansOblique": ("DejaVuSans-Oblique", ["DejaVuSans-Oblique.ttf", "Arial Italic.ttf", "ariali.ttf"], "Helvetica-Oblique"),
        "Serif": ("DejaVuSerif", ["DejaVuSerif.ttf", "Times New Roman.ttf", "times.ttf"], "Times-Roman"),
        "SerifBold": ("DejaVuSerif-Bold", ["DejaVuSerif-Bold.ttf", "Times New Roman Bold.ttf", "timesbd.ttf"], "Times-Bold"),
        "SerifItalic": ("DejaVuSerif-Italic", ["DejaVuSerif-Italic.ttf", "Times New Roman Italic.ttf", "timesi.ttf"], "Times-Italic"),
        "Mono": ("DejaVuSansMono", ["DejaVuSansMono.ttf", "Courier New.ttf", "cour.ttf"], "Courier"),
    }
    resolved: Dict[str, str] = {}
    for key, (name, candidates, fallback) in ttf_map.items():
        path = _find_font_file(candidates)
        if path:
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                resolved[key] = name
                continue
            except Exception:
                pass
        resolved[key] = fallback
    return resolved


def load_pil_font(size: int, bold: bool = False, serif: bool = False, oblique: bool = False) -> ImageFont.FreeTypeFont:
    """Loads a deterministic TrueType font for PIL figure drawing across Linux, macOS, and Windows."""
    if serif:
        if bold:
            candidates = ["DejaVuSerif-Bold.ttf", "Times New Roman Bold.ttf", "timesbd.ttf"]
        elif oblique:
            candidates = ["DejaVuSerif-Italic.ttf", "Times New Roman Italic.ttf", "timesi.ttf"]
        else:
            candidates = ["DejaVuSerif.ttf", "Times New Roman.ttf", "times.ttf"]
    else:
        if bold:
            candidates = ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica.ttc"]
        elif oblique:
            candidates = ["DejaVuSans-Oblique.ttf", "Arial Italic.ttf", "ariali.ttf"]
        else:
            candidates = ["DejaVuSans.ttf", "Arial Unicode.ttf", "Arial.ttf", "Helvetica.ttc"]
    path = _find_font_file(candidates)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def compute_image_meta_entry(
    fig_id: str,
    page_idx: int,
    physical_page: int,
    rel_filename: str,
    caption: str,
    img_type: str,
    x_pt: float,
    y_bottom_pt: float,
    w_pt: float,
    h_pt: float,
    px_w: int,
    px_h: int,
    page_w: float = PAGE_W,
    page_h: float = PAGE_H,
) -> Dict[str, Any]:
    """Computes golden_image_metadata.json entry from ReportLab bottom-left coordinates."""
    y_top_pt = page_h - (y_bottom_pt + h_pt)
    y_bot_from_top_pt = page_h - y_bottom_pt
    norm_box = [
        int(round((y_top_pt / page_h) * 1000)),
        int(round((x_pt / page_w) * 1000)),
        int(round((y_bot_from_top_pt / page_h) * 1000)),
        int(round(((x_pt + w_pt) / page_w) * 1000)),
    ]
    return {
        "id": fig_id,
        "page_idx": page_idx,
        "physical_page": physical_page,
        "filename": rel_filename,
        "caption": caption,
        "type": img_type,
        "pt_bounds": [round(x_pt, 1), round(y_bottom_pt, 1), round(x_pt + w_pt, 1), round(y_bottom_pt + h_pt, 1)],
        "pt_size": [round(w_pt, 1), round(h_pt, 1)],
        "pixel_resolution": [px_w, px_h],
        "aspect_ratio": round(w_pt / h_pt, 2),
        "normalized_box_1000": norm_box,
    }


# ---------------------------------------------------------------------------
# OpenStreetMap (ODbL 1.0) Cartography & Texture Helpers
# ---------------------------------------------------------------------------

def deg2tile_float(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[float, float]:
    """Converts (lat, lon) in degrees to fractional Web Mercator tile coordinates at `zoom`."""
    lat_rad = math.radians(lat_deg)
    n = float(2 ** zoom)
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def fetch_osm_tile(z: int, x: int, y: int) -> Optional[Image.Image]:
    """Fetches a single 256x256 OpenStreetMap tile with persistent local caching in OSM_CACHE_DIR."""
    os.makedirs(OSM_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(OSM_CACHE_DIR, f"osm_{z}_{x}_{y}.png")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 500:
        try:
            with Image.open(cache_path) as raw_img:
                return raw_img.convert("RGB")
        except Exception:
            pass
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ebuch-konvertierung-schoolbook-benchmark/1.0 (https://openstreetmap.org/copyright; ODbL-1.0)"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        with open(cache_path, "wb") as f:
            f.write(data)
        with Image.open(cache_path) as raw_img:
            return raw_img.convert("RGB")
    except Exception:
        return None


def stitch_osm_bbox(
    lat_north: float,
    lon_west: float,
    lat_south: float,
    lon_east: float,
    zoom: int,
    target_w: int,
    target_h: int,
) -> Tuple[Image.Image, Any]:
    """
    Stitches OpenStreetMap tiles covering the bounding box (lat_north, lon_west, lat_south, lon_east),
    crops to the exact geographic bounding box, and resizes to (target_w, target_h).
    Returns (image, project_fn) where project_fn(lat, lon) -> (px_x, px_y) in target image coordinates.
    """
    x_min_f, y_min_f = deg2tile_float(lat_north, lon_west, zoom)
    x_max_f, y_max_f = deg2tile_float(lat_south, lon_east, zoom)

    tx_min, tx_max = int(math.floor(x_min_f)), int(math.floor(x_max_f))
    ty_min, ty_max = int(math.floor(y_min_f)), int(math.floor(y_max_f))

    grid_w = (tx_max - tx_min + 1) * 256
    grid_h = (ty_max - ty_min + 1) * 256
    canvas_img = Image.new("RGB", (grid_w, grid_h), (226, 240, 217))

    any_loaded = False
    for tx in range(tx_min, tx_max + 1):
        for ty in range(ty_min, ty_max + 1):
            tile = fetch_osm_tile(zoom, tx, ty)
            if tile is not None:
                canvas_img.paste(tile, ((tx - tx_min) * 256, (ty - ty_min) * 256))
                any_loaded = True

    crop_x0 = int(round((x_min_f - tx_min) * 256))
    crop_y0 = int(round((y_min_f - ty_min) * 256))
    crop_x1 = int(round((x_max_f - tx_min) * 256))
    crop_y1 = int(round((y_max_f - ty_min) * 256))

    cropped = canvas_img.crop((crop_x0, crop_y0, max(crop_x0 + 16, crop_x1), max(crop_y0 + 16, crop_y1)))
    resized = cropped.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

    if not any_loaded:
        # Procedural shaded-relief fallback if offline and cache empty
        arr = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        arr[:, :] = (218, 242, 208)
        resized = Image.fromarray(arr, mode="RGB")

    def project(lat: float, lon: float) -> Tuple[int, int]:
        xf, yf = deg2tile_float(lat, lon, zoom)
        u = (xf - x_min_f) / max(1e-6, (x_max_f - x_min_f))
        v = (yf - y_min_f) / max(1e-6, (y_max_f - y_min_f))
        return int(round(u * target_w)), int(round(v * target_h))

    return resized, project


def make_vertical_gradient(w: int, h: int, top_rgb: Tuple[int, int, int], bot_rgb: Tuple[int, int, int], grain: float = 0.0) -> Image.Image:
    """Creates a smooth vertical gradient image with optional deterministic paper/surface micro-texture."""
    y_t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    top = np.array(top_rgb, dtype=np.float32)[None, None, :]
    bot = np.array(bot_rgb, dtype=np.float32)[None, None, :]
    arr = top * (1.0 - y_t) + bot * y_t
    arr = np.broadcast_to(arr, (h, w, 3)).copy()
    if grain > 0:
        rng = np.random.default_rng(12345)
        noise = rng.normal(0.0, grain, size=(h, w, 1)).astype(np.float32)
        arr = np.clip(arr + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGB")


def paste_with_drop_shadow(
    base: Image.Image,
    box: Tuple[int, int, int, int],
    radius: int,
    fill_rgb: Tuple[int, int, int],
    outline_rgb: Tuple[int, int, int],
    outline_w: int = 3,
    shadow_offset: Tuple[int, int] = (6, 8),
    shadow_alpha: int = 52,
) -> None:
    """Draws a rounded card with a soft Gaussian drop shadow onto `base`."""
    x0, y0, x1, y1 = box
    sx, sy = shadow_offset
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x0 + sx, y0 + sy, x1 + sx, y1 + sy], radius=radius, fill=(15, 23, 42, shadow_alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=6))
    base_rgba = base.convert("RGBA")
    composited = Image.alpha_composite(base_rgba, overlay)
    base.paste(composited.convert("RGB"))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill_rgb, outline=outline_rgb, width=outline_w)


# ---------------------------------------------------------------------------
# Programmatic High-Resolution Figure Generators
# ---------------------------------------------------------------------------

def generate_gs_figures() -> Dict[str, str]:
    """Generates richly textured, 2x-supersampled illustrations for Document 1 (Grundschule Mathe & Sachkunde)."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    paths: Dict[str, str] = {}

    # -------------------------------------------------------------------------
    # 1. Number line (Zahlenstrahl bis 1000) with 3D Dienes Blocks - 1800x520 -> 900x260
    # -------------------------------------------------------------------------
    p1 = os.path.join(FIGURES_DIR, "gs_zahlenstrahl_1000.png")
    W, H = 1800, 520
    img = make_vertical_gradient(W, H, (240, 249, 255), (219, 234, 254), grain=2.5)
    paste_with_drop_shadow(img, (16, 16, W - 16, H - 16), radius=26, fill_rgb=(252, 250, 242), outline_rgb=(37, 99, 235), outline_w=5)
    d = ImageDraw.Draw(img)
    f_bold = load_pil_font(36, bold=True)
    f_reg = load_pil_font(28)
    f_small = load_pil_font(24, bold=True)

    # Top-right mini-legend showing 3D Dienes Base-10 Blocks (Hunderterplatte, Zehnerstange, Einerwürfel)
    paste_with_drop_shadow(img, (1170, 32, 1756, 152), radius=18, fill_rgb=(239, 246, 255), outline_rgb=(147, 197, 253), outline_w=3, shadow_offset=(3, 4), shadow_alpha=35)
    d = ImageDraw.Draw(img)
    # 3D Hunderterplatte (100)
    hx, hy = 1196, 54
    d.polygon([(hx, hy + 14), (hx + 16, hy), (hx + 76, hy), (hx + 60, hy + 14)], fill=(96, 165, 250), outline=(30, 58, 138))
    d.polygon([(hx + 60, hy + 14), (hx + 76, hy), (hx + 76, hy + 60), (hx + 60, hy + 74)], fill=(37, 99, 235), outline=(30, 58, 138))
    d.rectangle([hx, hy + 14, hx + 60, hy + 74], fill=(59, 130, 246), outline=(30, 58, 138), width=2)
    for gi in range(1, 5):
        d.line([(hx + gi * 12, hy + 14), (hx + gi * 12, hy + 74)], fill=(191, 219, 254), width=1)
        d.line([(hx, hy + 14 + gi * 12), (hx + 60, hy + 14 + gi * 12)], fill=(191, 219, 254), width=1)
    d.text((hx + 84, hy + 26), "1 H = 100", fill=(30, 58, 138), font=f_small)
    # 3D Zehnerstange (10)
    zx, zy = 1418, 52
    d.rectangle([zx, zy + 10, zx + 18, zy + 74], fill=(34, 197, 94), outline=(20, 83, 45), width=2)
    for gi in range(1, 5):
        d.line([(zx, zy + 10 + gi * 13), (zx + 18, zy + 10 + gi * 13)], fill=(187, 247, 208), width=1)
    d.text((zx + 28, zy + 28), "1 Z = 10", fill=(20, 83, 45), font=f_small)
    # 3D Einerwürfel (1)
    ex, ey = 1588, 76
    d.rectangle([ex, ey, ex + 22, ey + 22], fill=(245, 158, 11), outline=(146, 64, 14), width=2)
    d.text((ex + 30, ey - 4), "1 E = 1", fill=(146, 64, 14), font=f_small)

    # 3D Wooden Ruler / Number Line Track
    y_axis = 304
    d.rounded_rectangle([76, y_axis - 22, 1710, y_axis + 22], radius=10, fill=(254, 243, 199), outline=(180, 83, 9), width=3)
    d.line([(96, y_axis), (1696, y_axis)], fill=(30, 58, 138), width=8)
    d.polygon([(1724, y_axis), (1686, y_axis - 18), (1686, y_axis + 18)], fill=(30, 58, 138))

    # Major 100-ticks, medium 50-ticks, and minor 10-ticks
    for unit_10 in range(101):
        x = int(round(100 + unit_10 * 15.6))
        if unit_10 % 10 == 0:
            d.line([(x, y_axis - 24), (x, y_axis + 24)], fill=(30, 58, 138), width=6)
            i = unit_10 // 10
            if i in (0, 2, 5, 8, 10):
                lbl = str(i * 100)
                x_off = -12 if i == 0 else (-52 if i == 10 else -34)
                d.text((x + x_off, y_axis + 28), lbl, fill=(30, 58, 138), font=f_bold)
        elif unit_10 % 5 == 0:
            d.line([(x, y_axis - 15), (x, y_axis + 15)], fill=(59, 130, 246), width=4)
        else:
            d.line([(x, y_axis - 8), (x, y_axis + 8)], fill=(147, 197, 253), width=2)

    # Jump arcs: 150 -> 400 (+250) and 400 -> 750 (+350) with drop shadows and arrowheads
    x_150 = int(round(100 + 15 * 15.6))
    x_400 = int(round(100 + 40 * 15.6))
    x_750 = int(round(100 + 75 * 15.6))

    d.arc([x_150, 96, x_400, y_axis], start=180, end=0, fill=(220, 38, 38), width=8)
    d.polygon([(x_400, y_axis - 12), (x_400 - 18, y_axis - 34), (x_400 + 8, y_axis - 36)], fill=(220, 38, 38))
    mx1 = (x_150 + x_400) // 2
    d.rounded_rectangle([mx1 - 74, 34, mx1 + 74, 86], radius=14, fill=(254, 226, 226), outline=(220, 38, 38), width=4)
    d.text((mx1 - 54, 41), "+ 250", fill=(185, 28, 28), font=f_bold)

    d.arc([x_400, 82, x_750, y_axis], start=180, end=0, fill=(22, 163, 74), width=8)
    d.polygon([(x_750, y_axis - 12), (x_750 - 18, y_axis - 34), (x_750 + 8, y_axis - 36)], fill=(22, 163, 74))
    mx2 = (x_400 + x_750) // 2
    d.rounded_rectangle([mx2 - 74, 22, mx2 + 74, 74], radius=14, fill=(220, 252, 231), outline=(22, 163, 74), width=4)
    d.text((mx2 - 54, 29), "+ 350", fill=(21, 128, 61), font=f_bold)

    # Callout boxes below axis
    for x_tick in (x_150, x_400, x_750):
        d.line([(x_tick, y_axis), (x_tick, y_axis + 84)], fill=(217, 119, 6), width=5)
    paste_with_drop_shadow(img, (x_150 - 58, y_axis + 82, x_150 + 58, y_axis + 158), radius=12, fill_rgb=(254, 242, 242), outline_rgb=(185, 28, 28), outline_w=4, shadow_offset=(3, 4))
    d = ImageDraw.Draw(img)
    d.text((x_150 - 38, y_axis + 98), "150", fill=(185, 28, 28), font=f_bold)
    for xb in (x_400, x_750):
        paste_with_drop_shadow(img, (xb - 58, y_axis + 82, xb + 58, y_axis + 158), radius=12, fill_rgb=(255, 255, 255), outline_rgb=(217, 119, 6), outline_w=5, shadow_offset=(3, 4))
        d = ImageDraw.Draw(img)
        d.text((xb - 12, y_axis + 98), "?", fill=(217, 119, 6), font=f_bold)

    img.resize((900, 260), resample=Image.Resampling.LANCZOS).save(p1)
    paths["fig_gs_1"] = p1

    # -------------------------------------------------------------------------
    # 2. Rechenmauer (3D Beveled Bricks) & Zahlenhaus / Rechendreieck - 1800x720 -> 900x360
    # -------------------------------------------------------------------------
    p2 = os.path.join(FIGURES_DIR, "gs_rechenmauer_dreieck.png")
    W, H = 1800, 720
    img = make_vertical_gradient(W, H, (255, 253, 244), (254, 243, 199), grain=2.5)
    paste_with_drop_shadow(img, (14, 14, W - 14, H - 14), radius=24, fill_rgb=(255, 252, 245), outline_rgb=(245, 158, 11), outline_w=5)
    d = ImageDraw.Draw(img)
    f_hdr = load_pil_font(34, bold=True)
    f_brick = load_pil_font(40, bold=True)

    # Left panel card: Rechenmauer
    paste_with_drop_shadow(img, (44, 38, 860, 676), radius=20, fill_rgb=(255, 248, 231), outline_rgb=(217, 119, 6), outline_w=3)
    # Right panel card: Zahlenhaus / Rechendreieck
    paste_with_drop_shadow(img, (892, 38, 1756, 676), radius=20, fill_rgb=(239, 246, 255), outline_rgb=(59, 130, 246), outline_w=3)
    d = ImageDraw.Draw(img)

    d.text((78, 56), "Rechenmauer (Addition)", fill=(146, 64, 14), font=f_hdr)
    d.text((924, 56), "Zahlenhaus / Rechendreieck", fill=(30, 64, 175), font=f_hdr)

    # 3D beveled sandstone bricks on left
    bw, bh = 236, 116
    base_y = 485
    bricks = [
        (92, base_y, "125", False),
        (92 + bw + 8, base_y, "240", False),
        (92 + 2 * (bw + 8), base_y, "?", True),
        (92 + (bw + 8) // 2, base_y - bh - 8, "365", False),
        (92 + bw + 8 + (bw + 8) // 2, base_y - bh - 8, "?", True),
        (92 + bw + 8, base_y - 2 * (bh + 8), "850", False),
    ]
    for bx, by, val, is_empty in bricks:
        # Brick drop shadow
        d.rounded_rectangle([bx + 6, by + 8, bx + bw + 6, by + bh + 8], radius=10, fill=(180, 130, 70))
        fill_c = (255, 255, 255) if is_empty else (253, 230, 138)
        top_bevel = (255, 255, 255) if is_empty else (254, 249, 195)
        bot_bevel = (226, 232, 240) if is_empty else (217, 119, 6)
        out_c = (217, 119, 6) if is_empty else (146, 64, 14)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=fill_c, outline=out_c, width=5)
        # Bevel highlight lines
        d.line([(bx + 8, by + 8), (bx + bw - 8, by + 8)], fill=top_bevel, width=4)
        d.line([(bx + 8, by + bh - 8), (bx + bw - 8, by + bh - 8)], fill=bot_bevel, width=4)
        x_txt = bx + 102 if val == "?" else bx + 74
        d.text((x_txt, by + 32), val, fill=(120, 53, 15) if not is_empty else (217, 119, 6), font=f_brick)

    # Right: Textured Rechendreieck with roofed frame & shadowed product cards
    tri_pts = [(1330, 150), (1070, 558), (1590, 558)]
    # Shadow triangle
    d.polygon([(px + 8, py + 10) for px, py in tri_pts], fill=(147, 197, 253))
    d.polygon(tri_pts, outline=(30, 64, 175), fill=(219, 234, 254), width=6)
    cx, cy = 1330, 422
    d.line([(1330, 150), (cx, cy)], fill=(30, 64, 175), width=4)
    d.line([(1070, 558), (cx, cy)], fill=(30, 64, 175), width=4)
    d.line([(1590, 558), (cx, cy)], fill=(30, 64, 175), width=4)
    # Inner numbers: 6, 8, 5 inside circular badges
    for icx, icy, ival in [(1256, 355, "6"), (1404, 355, "8"), (1330, 495, "5")]:
        d.ellipse([icx - 36, icy - 36, icx + 36, icy + 36], fill=(255, 255, 255), outline=(37, 99, 235), width=4)
        d.text((icx - 13, icy - 24), ival, fill=(30, 58, 138), font=f_brick)

    # Outer product boxes
    outer_boxes = [(1005, 290, "48", False), (1515, 290, "?", True), (1262, 578, "?", True)]
    for ox, oy, oval, is_q in outer_boxes:
        paste_with_drop_shadow(
            img, (ox, oy, ox + 136, oy + 82), radius=14,
            fill_rgb=(255, 255, 255) if is_q else (224, 242, 254),
            outline_rgb=(217, 119, 6) if is_q else (29, 78, 216),
            outline_w=5, shadow_offset=(4, 6)
        )
        d = ImageDraw.Draw(img)
        x_off = 54 if oval == "?" else 38
        d.text((ox + x_off, oy + 16), oval, fill=(217, 119, 6) if is_q else (30, 64, 175), font=f_brick)

    img.resize((900, 360), resample=Image.Resampling.LANCZOS).save(p2)
    paths["fig_gs_2"] = p2

    # -------------------------------------------------------------------------
    # 3. Analog clocks (07:45, 11:20, 15:55) with 60 ticks & time-of-day badges - 1800x600 -> 900x300
    # -------------------------------------------------------------------------
    p3 = os.path.join(FIGURES_DIR, "gs_analoge_uhren.png")
    W, H = 1800, 600
    img = make_vertical_gradient(W, H, (236, 253, 245), (209, 250, 229), grain=2.0)
    paste_with_drop_shadow(img, (14, 14, W - 14, H - 14), radius=24, fill_rgb=(245, 253, 248), outline_rgb=(16, 185, 129), outline_w=5)
    d = ImageDraw.Draw(img)
    f_clk_num = load_pil_font(30, bold=True)
    f_clk_lbl = load_pil_font(32, bold=True)

    clocks = [
        (330, 268, 7, 45, "Uhr A (Morgen)", (14, 116, 144)),
        (900, 268, 11, 20, "Uhr B (Vormittag)", (6, 95, 70)),
        (1470, 268, 3, 55, "Uhr C (Nachmittag)", (180, 83, 9)),
    ]
    for cx, cy, hr, mn, label, frame_col in clocks:
        r = 194
        # Drop shadow of clock case
        d.ellipse([cx - r - 8, cy - r + 10, cx + r + 8, cy + r + 26], fill=(167, 243, 208))
        # Outer metallic/colored bezel
        d.ellipse([cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12], fill=frame_col, outline=(15, 23, 42), width=4)
        # Inner cream clock face
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 254, 248), outline=(203, 213, 225), width=3)
        # Subtle inner decorative ring
        d.ellipse([cx - r + 58, cy - r + 58, cx + r - 58, cy + r - 58], outline=(226, 232, 240), width=2)
        # 60 minute & 12 hour ticks
        for m_i in range(60):
            ang = math.radians(m_i * 6 - 90)
            is_hr = m_i % 5 == 0
            r_outer = r - 8
            r_inner = r - (24 if is_hr else 15)
            d.line(
                [
                    (cx + int(r_inner * math.cos(ang)), cy + int(r_inner * math.sin(ang))),
                    (cx + int(r_outer * math.cos(ang)), cy + int(r_outer * math.sin(ang))),
                ],
                fill=(15, 23, 42) if is_hr else (148, 163, 184),
                width=5 if is_hr else 2,
            )
        # 1..12 numerals
        for h_i in range(1, 13):
            ang = math.radians(h_i * 30 - 90)
            tx = cx + int((r - 48) * math.cos(ang))
            ty = cy + int((r - 48) * math.sin(ang))
            x_adj = -19 if h_i >= 10 else -9
            d.text((tx + x_adj, ty - 18), str(h_i), fill=(15, 23, 42), font=f_clk_num)

        # Hour hand (tapered red)
        h_ang = math.radians(((hr % 12) + mn / 60.0) * 30 - 90)
        hx_end = cx + int(96 * math.cos(h_ang))
        hy_end = cy + int(96 * math.sin(h_ang))
        d.line([(cx + 3, cy + 4), (hx_end + 3, hy_end + 4)], fill=(203, 213, 225), width=14)
        d.line([(cx, cy), (hx_end, hy_end)], fill=(220, 38, 38), width=13)

        # Minute hand (tapered navy blue)
        m_ang = math.radians(mn * 6 - 90)
        mx_end = cx + int(132 * math.cos(m_ang))
        my_end = cy + int(132 * math.sin(m_ang))
        d.line([(cx + 3, cy + 4), (mx_end + 3, my_end + 4)], fill=(203, 213, 225), width=10)
        d.line([(cx, cy), (mx_end, my_end)], fill=(30, 58, 138), width=9)

        # Center brass cap
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=(245, 158, 11), outline=(15, 23, 42), width=3)

        # Label pill below clock
        paste_with_drop_shadow(img, (cx - 190, cy + r + 24, cx + 190, cy + r + 84), radius=16, fill_rgb=(255, 255, 255), outline_rgb=frame_col, outline_w=3, shadow_offset=(2, 4))
        d = ImageDraw.Draw(img)
        lbl_w = int(d.textlength(label, font=f_clk_lbl))
        d.text((cx - lbl_w // 2, cy + r + 35), label, fill=frame_col, font=f_clk_lbl)

    img.resize((900, 300), resample=Image.Resampling.LANCZOS).save(p3)
    paths["fig_gs_3"] = p3

    # -------------------------------------------------------------------------
    # 4. Food chain diagram with botanical/zoological illustrations - 1800x540 -> 900x270
    # -------------------------------------------------------------------------
    p4 = os.path.join(FIGURES_DIR, "gs_nahrungskette_wiese.png")
    W, H = 1800, 540
    img = make_vertical_gradient(W, H, (224, 242, 254), (220, 252, 231), grain=2.5)
    d = ImageDraw.Draw(img)
    # Rolling meadow hills at bottom
    d.polygon([(0, 410), (450, 385), (980, 405), (1450, 380), (1800, 400), (1800, 540), (0, 540)], fill=(134, 239, 172))
    d.rounded_rectangle([12, 12, W - 12, H - 12], radius=24, outline=(22, 163, 74), width=5)

    f_title = load_pil_font(34, bold=True)
    f_card_t = load_pil_font(32, bold=True)
    f_sub = load_pil_font(26)
    d.text((56, 28), "Nahrungskette auf der Streuobstwiese (Pfeil = „wird gefressen von“)", fill=(20, 83, 45), font=f_title)

    nodes = [
        (56, 102, 396, 488, "Apfelblatt", "(Erzeuger)", (240, 253, 244), (22, 163, 74)),
        (488, 102, 828, 488, "Raupe", "(1. Verbraucher)", (254, 252, 232), (202, 138, 4)),
        (920, 102, 1260, 488, "Kohlmeise", "(2. Verbraucher)", (239, 246, 255), (37, 99, 235)),
        (1352, 102, 1744, 488, "Turmfalke", "(Beutegreifer)", (254, 242, 242), (220, 38, 38)),
    ]
    for x1, y1, x2, y2, title, role, col, border_col in nodes:
        paste_with_drop_shadow(img, (x1, y1, x2, y2), radius=24, fill_rgb=col, outline_rgb=border_col, outline_w=5, shadow_offset=(5, 7))

    d = ImageDraw.Draw(img)
    # Wildflower dots along the green meadow hills at the bottom
    for fx, fy, fcol in [(42, 460, (253, 224, 71)), (435, 430, (255, 255, 255)), (865, 445, (253, 224, 71)), (1310, 435, (255, 255, 255)), (1765, 455, (253, 224, 71))]:
        d.ellipse([fx - 7, fy - 7, fx + 7, fy + 7], fill=fcol, outline=(202, 138, 4), width=2)

    # Illustration 1: Veined green apple leaf with woody petiole, highlight, and glistening dewdrop
    lx, ly = 226, 225
    d.line([(lx - 122, ly + 18), (lx - 86, ly + 12)], fill=(120, 53, 15), width=8)  # woody petiole stem
    d.ellipse([lx - 95, ly - 55, lx + 95, ly + 55], fill=(34, 197, 94), outline=(21, 128, 61), width=4)
    d.chord([lx - 90, ly - 50, lx + 90, ly + 50], start=185, end=355, fill=(74, 222, 128))  # upper leaf highlight
    d.line([(lx - 92, ly + 12), (lx + 85, ly - 5)], fill=(20, 83, 45), width=6)
    for vx in (-50, -15, 20, 50):
        d.line([(lx + vx, ly + 2), (lx + vx + 22, ly - 32)], fill=(187, 247, 208), width=3)
        d.line([(lx + vx, ly + 2), (lx + vx + 22, ly + 32)], fill=(187, 247, 208), width=3)
    d.ellipse([lx + 28, ly - 30, lx + 50, ly - 8], fill=(186, 230, 253), outline=(2, 132, 199), width=2)
    d.ellipse([lx + 33, ly - 26, lx + 39, ly - 20], fill=(255, 255, 255))  # specular glint

    # Illustration 2: Segmented green caterpillar with prolegs & dorsal spots on twig
    rx, ry = 658, 240
    d.line([(rx - 120, ry + 34), (rx + 120, ry + 24)], fill=(120, 53, 15), width=10)
    for seg_i in range(6):
        sx = rx - 82 + seg_i * 30
        sy = ry + int(10 * math.sin(seg_i * 0.9))
        # Tiny prolegs gripping the twig
        d.ellipse([sx - 6, sy + 18, sx + 6, sy + 30], fill=(54, 83, 20))
        d.ellipse([sx - 24, sy - 24, sx + 24, sy + 24], fill=(132, 204, 22) if seg_i % 2 == 0 else (101, 163, 13), outline=(54, 83, 20), width=3)
        d.ellipse([sx - 5, sy - 14, sx + 5, sy - 4], fill=(217, 249, 157))  # dorsal spot
    # Head & antennae
    hx_c, hy_c = rx + 76, ry - 4
    d.ellipse([hx_c - 26, hy_c - 26, hx_c + 26, hy_c + 26], fill=(77, 124, 15), outline=(54, 83, 20), width=3)
    d.ellipse([hx_c + 6, hy_c - 10, hx_c + 16, hy_c], fill=(255, 255, 255))
    d.ellipse([hx_c + 10, hy_c - 8, hx_c + 15, hy_c - 3], fill=(15, 23, 42))
    d.line([(hx_c + 12, hy_c - 24), (hx_c + 28, hy_c - 46)], fill=(54, 83, 20), width=3)
    d.ellipse([hx_c + 24, hy_c - 50, hx_c + 32, hy_c - 42], fill=(180, 83, 9))

    # Illustration 3: Great Tit (Kohlmeise) with perch twig, tail, yellow breast, black belly stripe, white cheek
    kx, ky = 1090, 235
    d.line([(kx - 95, ky + 56), (kx + 85, ky + 48)], fill=(120, 53, 15), width=7)  # perch branch
    d.polygon([(kx - 112, ky + 8), (kx - 62, ky - 8), (kx - 62, ky + 14), (kx - 106, ky + 26)], fill=(51, 65, 85), outline=(15, 23, 42), width=2)  # tail
    d.ellipse([kx - 70, ky - 38, kx + 55, ky + 46], fill=(250, 204, 21), outline=(15, 23, 42), width=3)  # yellow belly
    d.line([(kx + 28, ky - 2), (kx - 12, ky + 42)], fill=(15, 23, 42), width=8)  # iconic black belly stripe (Krawatte)
    d.polygon([(kx - 65, ky - 10), (kx + 35, ky - 22), (kx + 15, ky + 32), (kx - 55, ky + 25)], fill=(71, 85, 105), outline=(15, 23, 42), width=2)  # wing
    d.line([(kx - 35, ky - 2), (kx + 8, ky + 10)], fill=(241, 245, 249), width=5)  # white wing bar
    d.ellipse([kx + 22, ky - 56, kx + 82, ky + 2], fill=(15, 23, 42))  # black head cap
    d.ellipse([kx + 34, ky - 36, kx + 72, ky - 8], fill=(255, 255, 255))  # white cheek patch
    d.ellipse([kx + 52, ky - 44, kx + 62, ky - 34], fill=(255, 255, 255))  # eye highlight
    d.polygon([(kx + 80, ky - 30), (kx + 106, ky - 22), (kx + 80, ky - 14)], fill=(51, 65, 85))  # beak
    d.line([(kx - 15, ky + 44), (kx - 18, ky + 54)], fill=(51, 65, 85), width=4)
    d.line([(kx + 10, ky + 44), (kx + 8, ky + 52)], fill=(51, 65, 85), width=4)

    # Illustration 4: Kestrel (Turmfalke) in flight with barred fan tail, spotted rufous wings & malar stripes
    tx, ty = 1548, 228
    # Barred fan tail
    d.polygon([(tx - 16, ty + 36), (tx + 16, ty + 36), (tx + 34, ty + 82), (tx - 34, ty + 82)], fill=(148, 163, 184), outline=(15, 23, 42), width=3)
    d.line([(tx - 30, ty + 74), (tx + 30, ty + 74)], fill=(15, 23, 42), width=6)
    # Rufous wings with dark spots
    d.polygon([(tx - 132, ty - 32), (tx - 15, ty - 5), (tx - 65, ty + 35)], fill=(180, 83, 9), outline=(120, 53, 15), width=3)
    d.polygon([(tx + 132, ty - 32), (tx + 15, ty - 5), (tx + 65, ty + 35)], fill=(180, 83, 9), outline=(120, 53, 15), width=3)
    for spx, spy in [(-75, -8), (-52, 8), (-92, -16), (75, -8), (52, 8), (92, -16)]:
        d.ellipse([tx + spx - 4, ty + spy - 4, tx + spx + 4, ty + spy + 4], fill=(69, 26, 3))
    d.ellipse([tx - 38, ty - 34, tx + 38, ty + 48], fill=(217, 119, 6), outline=(120, 53, 15), width=3)
    # Yellow talons
    d.ellipse([tx - 18, ty + 40, tx - 6, ty + 52], fill=(250, 204, 21), outline=(120, 53, 15), width=2)
    d.ellipse([tx + 6, ty + 40, tx + 18, ty + 52], fill=(250, 204, 21), outline=(120, 53, 15), width=2)
    # Blue-grey head with eyes & hooked beak
    d.ellipse([tx - 24, ty - 62, tx + 24, ty - 16], fill=(100, 116, 139), outline=(15, 23, 42), width=3)
    d.ellipse([tx - 13, ty - 46, tx - 5, ty - 38], fill=(15, 23, 42))
    d.ellipse([tx + 5, ty - 46, tx + 13, ty - 38], fill=(15, 23, 42))
    d.polygon([(tx - 8, ty - 36), (tx + 8, ty - 36), (tx, ty - 16)], fill=(245, 158, 11), outline=(15, 23, 42), width=2)

    # Labels on cards
    for x1, y1, x2, y2, title, role, col, border_col in nodes:
        d.line([(x1 + 24, y2 - 132), (x2 - 24, y2 - 132)], fill=border_col, width=2)
        d.text((x1 + 32, y2 - 116), title, fill=(15, 23, 42), font=f_card_t)
        d.text((x1 + 32, y2 - 64), role, fill=(51, 65, 85), font=f_sub)

    # Shaded trophic arrows between cards
    for ax in (402, 834, 1266):
        d.line([(ax, 295), (ax + 68, 295)], fill=(21, 128, 61), width=12)
        d.polygon([(ax + 82, 295), (ax + 54, 270), (ax + 54, 320)], fill=(21, 128, 61))

    img.resize((900, 270), resample=Image.Resampling.LANCZOS).save(p4)
    paths["fig_gs_4"] = p4
    return paths


def generate_sek1_lang_figures() -> Dict[str, str]:
    """Generates Youth Eco-Magazine Collage with textured Cornwall coast + real OpenStreetMap St Ives inset."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    p1 = os.path.join(FIGURES_DIR, "sek1_cornwall_coastal_action.png")
    W, H = 1800, 640
    img = make_vertical_gradient(W, H, (125, 211, 252), (224, 242, 254), grain=2.0)
    d = ImageDraw.Draw(img)

    # Left half (x=0..720): Textured Cornwall Coastal Scene + OpenStreetMap Inset of St Ives Bay
    # Multi-layered ocean with foaming surf waves
    d.rectangle([0, 290, 760, 460], fill=(3, 105, 161))
    d.rectangle([0, 345, 760, 460], fill=(2, 132, 199))
    d.rectangle([0, 395, 760, 465], fill=(14, 165, 233))
    for wx in range(-20, 740, 75):
        d.arc([wx, 378, wx + 85, 412], start=0, end=180, fill=(224, 242, 254), width=5)
        d.arc([wx + 25, 425, wx + 105, 458], start=0, end=180, fill=(255, 255, 255), width=6)

    # Sandy beach with pebbles
    d.polygon([(0, 455), (760, 440), (760, 640), (0, 640)], fill=(253, 230, 138))
    d.polygon([(0, 495), (760, 475), (760, 640), (0, 640)], fill=(252, 211, 77))

    # Rugged layered granite cliffs on left with rock strata cracks & grassy headland
    d.polygon([(0, 340), (65, 190), (195, 165), (320, 225), (390, 355), (0, 365)], fill=(87, 83, 78), outline=(41, 37, 36), width=3)
    d.polygon([(45, 345), (120, 210), (245, 195), (345, 350)], fill=(120, 113, 108))
    # Granite strata lines
    d.line([(35, 265), (155, 245), (285, 275)], fill=(68, 64, 60), width=3)
    d.line([(20, 308), (165, 290), (325, 315)], fill=(68, 64, 60), width=3)
    d.polygon([(0, 200), (65, 182), (198, 156), (322, 218), (265, 232), (140, 196), (0, 222)], fill=(34, 197, 94), outline=(21, 128, 61), width=2)

    # Flying coastal seabirds (gulls) in the sky
    for gx, gy in [(62, 92), (370, 108), (445, 76)]:
        d.arc([gx - 22, gy - 10, gx, gy + 10], start=200, end=350, fill=(255, 255, 255), width=4)
        d.arc([gx, gy - 10, gx + 22, gy + 10], start=190, end=340, fill=(255, 255, 255), width=4)

    # Godrevy-style red-and-white striped lighthouse with lantern room & light beams
    lx, ly = 165, 58
    d.polygon([(lx + 24, ly + 12), (lx + 240, ly - 30), (lx + 240, ly + 45)], fill=(254, 249, 195))
    d.polygon([(lx, ly + 115), (lx + 8, ly + 18), (lx + 42, ly + 18), (lx + 50, ly + 115)], fill=(255, 255, 255), outline=(30, 41, 59), width=3)
    d.polygon([(lx + 5, ly + 52), (lx + 45, ly + 52), (lx + 47, ly + 82), (lx + 3, ly + 82)], fill=(220, 38, 38))
    d.rectangle([lx + 6, ly + 4, lx + 44, ly + 18], fill=(30, 41, 59))
    d.ellipse([lx + 12, ly - 10, lx + 38, ly + 12], fill=(253, 224, 71), outline=(30, 41, 59), width=3)

    # Real OpenStreetMap Inset Map of St Ives Bay (z=12) at bottom-left of coastal scene
    osm_st_ives, proj_st = stitch_osm_bbox(50.255, -5.515, 50.175, -5.375, zoom=12, target_w=460, target_h=245)
    osm_st_ives = ImageEnhance.Contrast(osm_st_ives).enhance(1.08)
    paste_with_drop_shadow(img, (22, 368, 498, 624), radius=16, fill_rgb=(255, 255, 255), outline_rgb=(3, 105, 161), outline_w=4, shadow_offset=(4, 6))
    img.paste(osm_st_ives, (30, 376))
    d = ImageDraw.Draw(img)
    f_map_sm = load_pil_font(19, bold=True)
    f_map_att = load_pil_font(13)
    # Pin markers on St Ives inset (place Godrevy label to the left of its pin so it stays inside the inset frame)
    px_harb, py_harb = proj_st(50.211, -5.477)
    px_godr, py_godr = proj_st(50.242, -5.391)
    for mpx, mpy, mlbl, bx0, bx1 in [
        (30 + px_harb, 376 + py_harb, "St Ives Pier", 12, 144),
        (30 + px_godr, 376 + py_godr, "Godrevy", -112, -12),
    ]:
        d.ellipse([mpx - 9, mpy - 9, mpx + 9, mpy + 9], fill=(220, 38, 38), outline=(255, 255, 255), width=3)
        d.rounded_rectangle([mpx + bx0, mpy - 14, mpx + bx1, mpy + 14], radius=6, fill=(255, 255, 255), outline=(15, 23, 42), width=2)
        d.text((mpx + bx0 + 8, mpy - 11), mlbl, fill=(15, 23, 42), font=f_map_sm)
    d.rectangle([30, 596, 490, 620], fill=(255, 255, 255))
    d.text((36, 600), "Inset Map: St Ives Bay | © OpenStreetMap contributors (ODbL)", fill=(51, 65, 85), font=f_map_att)

    # Right half (x=535..1768): Magazine Info Poster Card with Waste Breakdown Mini-Chart
    paste_with_drop_shadow(img, (535, 36, 1768, 604), radius=24, fill_rgb=(255, 255, 255), outline_rgb=(15, 23, 42), outline_w=5, shadow_offset=(8, 10))
    d = ImageDraw.Draw(img)
    # Header banner inside card
    d.rounded_rectangle([555, 54, 1748, 132], radius=14, fill=(3, 105, 161))
    f_title = load_pil_font(35, bold=True)
    f_bold = load_pil_font(28, bold=True)
    f_reg = load_pil_font(27)
    d.text((580, 72), "YOUTH ECO-REPORT: ST IVES BEACH CLEAN-UP", fill=(255, 255, 255), font=f_title)

    # Bullet facts on left side of card
    d.text((575, 162), "• Volunteers collected: 142 kg marine plastic", fill=(15, 23, 42), font=f_reg)
    d.text((575, 224), "• Fishing nets & ropes: 38 % of total waste", fill=(15, 23, 42), font=f_reg)
    d.text((575, 286), "• Single-use bottles & caps: 47 % of total waste", fill=(15, 23, 42), font=f_reg)
    d.text((575, 358), "• Next action day: Saturday, 10:00 a.m. at Harbour Pier", fill=(21, 128, 61), font=f_bold)

    # Motto banner at bottom of card
    d.rounded_rectangle([570, 434, 1455, 568], radius=16, fill=(254, 242, 242), outline=(220, 38, 38), width=3)
    d.text((595, 458), "Motto: \"Protect Our Coastline – Every Piece Counts!\"", fill=(185, 28, 28), font=f_bold)
    d.text((595, 512), " Cornwall Schools Marine Conservation Network · Issue #14", fill=(100, 116, 139), font=load_pil_font(22, oblique=True))

    # Mini Donut Chart on right side of card (x=1480..1735)
    dcx, dcy, dr = 1608, 305, 108
    d.pieslice([dcx - dr, dcy - dr, dcx + dr, dcy + dr], start=-90, end=-90 + int(0.47 * 360), fill=(2, 132, 199), outline=(255, 255, 255), width=3)
    d.pieslice([dcx - dr, dcy - dr, dcx + dr, dcy + dr], start=-90 + int(0.47 * 360), end=-90 + int(0.85 * 360), fill=(245, 158, 11), outline=(255, 255, 255), width=3)
    d.pieslice([dcx - dr, dcy - dr, dcx + dr, dcy + dr], start=-90 + int(0.85 * 360), end=270, fill=(16, 185, 129), outline=(255, 255, 255), width=3)
    d.ellipse([dcx - 54, dcy - 54, dcx + 54, dcy + 54], fill=(255, 255, 255))
    d.text((dcx - 42, dcy - 16), "142 kg", fill=(15, 23, 42), font=load_pil_font(24, bold=True))
    d.text((1515, 435), "47% Bottles", fill=(2, 132, 199), font=load_pil_font(21, bold=True))
    d.text((1515, 468), "38% Nets", fill=(180, 83, 9), font=load_pil_font(21, bold=True))
    d.text((1515, 501), "15% Other", fill=(6, 95, 70), font=load_pil_font(21, bold=True))

    img.resize((900, 320), resample=Image.Resampling.LANCZOS).save(p1)
    return {"fig_s1_lang_1": p1}


def generate_sek1_geo_hist_figures() -> Dict[str, str]:
    """Generates OpenStreetMap-based Upper Rhine Graben cartography, Walter-Lieth climate diagrams, and timeline."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    paths: Dict[str, str] = {}

    # -------------------------------------------------------------------------
    # 1. OpenStreetMap & Physical/Thematic Map of Oberrheingraben - 1800x960 -> 900x480
    # -------------------------------------------------------------------------
    p1 = os.path.join(FIGURES_DIR, "geo_karte_oberrheingraben.png")
    W, H = 1800, 960
    img = make_vertical_gradient(W, H, (241, 245, 249), (226, 232, 240), grain=1.5)
    f_title = load_pil_font(34, bold=True)
    f_bold = load_pil_font(28, bold=True)
    f_reg = load_pil_font(24)
    f_sm = load_pil_font(21)

    # Map viewport on left: (36, 36, 1216, 924) -> 1180 x 888
    map_x0, map_y0, map_w, map_h = 36, 36, 1180, 888
    # Stitch real OpenStreetMap tiles (z=8) for 49.30°N..47.42°N, 6.75°E..9.25°E
    osm_map, proj = stitch_osm_bbox(49.30, 6.75, 47.42, 9.25, zoom=8, target_w=map_w, target_h=map_h)

    # Composite subtle hypsometric elevation tinting & relief shading over the OSM base layer
    relief = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(relief)
    # Upper Rhine Plain (< 200 m) warm green tint along the graben axis
    graben_poly = [proj(lat, lon) for lat, lon in [(49.25, 8.15), (49.25, 8.65), (48.55, 8.05), (47.95, 7.80), (47.55, 7.62), (47.55, 7.25), (48.55, 7.45)]]
    rd.polygon(graben_poly, fill=(134, 239, 172, 58))
    # Vosges (west, 200-800+ m) & Palatinate Forest
    vosges_poly = [proj(lat, lon) for lat, lon in [(48.85, 7.00), (48.85, 7.42), (47.75, 7.25), (47.75, 6.82)]]
    rd.polygon(vosges_poly, fill=(217, 119, 6, 72))
    # Black Forest (east, > 800 m)
    bf_poly = [proj(lat, lon) for lat, lon in [(48.90, 8.20), (48.90, 8.85), (47.62, 8.45), (47.62, 7.75), (48.35, 7.88)]]
    rd.polygon(bf_poly, fill=(180, 83, 9, 78))
    relief = relief.filter(ImageFilter.GaussianBlur(radius=14))
    osm_tinted = Image.alpha_composite(osm_map.convert("RGBA"), relief).convert("RGB")

    paste_with_drop_shadow(img, (map_x0 - 4, map_y0 - 4, map_x0 + map_w + 4, map_y0 + map_h + 4), radius=14, fill_rgb=(255, 255, 255), outline_rgb=(15, 23, 42), outline_w=5)
    img.paste(osm_tinted, (map_x0, map_y0))
    d = ImageDraw.Draw(img)

    # Lat/Lon Graticule lines projected accurately onto the OpenStreetMap layer
    for lon_deg, lon_lbl in [(7.0, "7°O"), (8.0, "8°O"), (9.0, "9°O")]:
        gx, _ = proj(48.0, lon_deg)
        gx += map_x0
        d.line([(gx, map_y0), (gx, map_y0 + map_h)], fill=(71, 85, 105), width=2)
        d.rounded_rectangle([gx + 6, map_y0 + 8, gx + 68, map_y0 + 40], radius=6, fill=(255, 255, 255), outline=(100, 116, 139), width=2)
        d.text((gx + 12, map_y0 + 11), lon_lbl, fill=(30, 41, 59), font=f_sm)

    for lat_deg, lat_lbl in [(49.0, "49°N"), (48.0, "48°N"), (47.5, "47°30'N")]:
        _, gy = proj(lat_deg, 8.0)
        gy += map_y0
        if map_y0 + 20 < gy < map_y0 + map_h - 20:
            d.line([(map_x0, gy), (map_x0 + map_w, gy)], fill=(71, 85, 105), width=2)
            lbl_show = "47°N" if lat_deg == 47.5 else lat_lbl
            d.rounded_rectangle([map_x0 + 8, gy - 34, map_x0 + 78, gy - 4], radius=6, fill=(255, 255, 255), outline=(100, 116, 139), width=2)
            d.text((map_x0 + 14, gy - 31), lbl_show, fill=(30, 41, 59), font=f_sm)

    # Reinforced Rhine & Neckar courses on top of OSM
    rhine_coords = [(47.56, 7.59), (47.80, 7.55), (48.05, 7.58), (48.35, 7.72), (48.58, 7.80), (48.82, 8.12), (49.01, 8.32), (49.28, 8.44)]
    rhine_px = [(map_x0 + proj(lat, lon)[0], map_y0 + proj(lat, lon)[1]) for lat, lon in rhine_coords]
    d.line(rhine_px, fill=(29, 78, 216), width=10)
    d.line(rhine_px, fill=(96, 165, 250), width=4)
    rx_lbl, ry_lbl = proj(48.30, 7.72)
    d.rounded_rectangle([map_x0 + rx_lbl - 102, map_y0 + ry_lbl - 18, map_x0 + rx_lbl - 8, map_y0 + ry_lbl + 18], radius=6, fill=(239, 246, 255), outline=(59, 130, 246), width=2)
    d.text((map_x0 + rx_lbl - 94, map_y0 + ry_lbl - 15), "Rhein", fill=(30, 58, 138), font=f_bold)

    neckar_coords = [(49.25, 8.68), (49.14, 9.18), (48.80, 9.22)]
    neckar_px = [(map_x0 + proj(lat, lon)[0], map_y0 + proj(lat, lon)[1]) for lat, lon in neckar_coords]
    d.line(neckar_px, fill=(37, 99, 235), width=7)
    nx_lbl, ny_lbl = proj(49.18, 8.88)
    d.rounded_rectangle([map_x0 + nx_lbl - 48, map_y0 + ny_lbl - 38, map_x0 + nx_lbl + 46, map_y0 + ny_lbl - 6], radius=6, fill=(239, 246, 255), outline=(59, 130, 246), width=2)
    d.text((map_x0 + nx_lbl - 40, map_y0 + ny_lbl - 35), "Neckar", fill=(30, 58, 138), font=f_reg)

    # Tectonic fault lines (Grabenbruch-Randverwerfungen) dashed dark red
    west_fault = [(map_x0 + proj(lat, lon)[0], map_y0 + proj(lat, lon)[1]) for lat, lon in [(48.95, 7.92), (48.55, 7.46), (47.85, 7.26)]]
    east_fault = [(map_x0 + proj(lat, lon)[0], map_y0 + proj(lat, lon)[1]) for lat, lon in [(48.98, 8.45), (48.45, 8.02), (47.65, 7.68)]]
    d.line(west_fault, fill=(153, 27, 27), width=5)
    d.line(east_fault, fill=(153, 27, 27), width=5)

    # Mountain range banners (auto-sized around text width)
    vx, vy = proj(48.20, 7.08)
    vw = int(d.textlength("Vogesen", font=f_bold))
    paste_with_drop_shadow(img, (map_x0 + vx - vw // 2 - 18, map_y0 + vy - 24, map_x0 + vx + vw // 2 + 18, map_y0 + vy + 24), radius=10, fill_rgb=(146, 64, 14), outline_rgb=(255, 255, 255), outline_w=3)
    sx, sy = proj(48.25, 8.28)
    sw = int(d.textlength("Schwarzwald", font=f_bold))
    paste_with_drop_shadow(img, (map_x0 + sx - sw // 2 - 18, map_y0 + sy - 24, map_x0 + sx + sw // 2 + 18, map_y0 + sy + 24), radius=10, fill_rgb=(120, 53, 15), outline_rgb=(255, 255, 255), outline_w=3)
    d = ImageDraw.Draw(img)
    d.text((map_x0 + vx - vw // 2, map_y0 + vy - 17), "Vogesen", fill=(255, 255, 255), font=f_bold)
    d.text((map_x0 + sx - sw // 2, map_y0 + sy - 17), "Schwarzwald", fill=(255, 255, 255), font=f_bold)

    # Cities & Feldberg summit marker with halo pills
    cities = [
        (49.0069, 8.4037, "Karlsruhe", (18, -18), False),
        (48.5734, 7.7521, "Straßburg", (-168, -18), False),
        (47.9990, 7.8421, "Freiburg", (-145, -20), False),
        (47.5596, 7.5886, "Basel", (18, -18), False),
        (47.8739, 8.0039, "Feldberg (1493 m)", (18, -14), True),
    ]
    for lat, lon, cname, (dx_l, dy_l), is_peak in cities:
        cx, cy = proj(lat, lon)
        cx, cy = map_x0 + cx, map_y0 + cy
        if is_peak:
            d.polygon([(cx, cy - 16), (cx - 15, cy + 12), (cx + 15, cy + 12)], fill=(185, 28, 28), outline=(255, 255, 255), width=3)
        else:
            d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(220, 38, 38), outline=(255, 255, 255), width=4)
        tw = int(d.textlength(cname, font=f_bold))
        lx0, ly0 = cx + dx_l - 8, cy + dy_l - 4
        d.rounded_rectangle([lx0, ly0, lx0 + tw + 16, ly0 + 38], radius=8, fill=(255, 255, 255), outline=(15, 23, 42), width=2)
        d.text((lx0 + 8, ly0 + 3), cname, fill=(185, 28, 28) if is_peak else (15, 23, 42), font=f_bold)

    # Bottom-left OpenStreetMap attribution strip inside map
    att_str = "Kartengrundlage: © OpenStreetMap-Mitwirkende (ODbL 1.0)"
    att_w = int(d.textlength(att_str, font=f_sm))
    d.rounded_rectangle([map_x0 + 10, map_y0 + map_h - 42, map_x0 + 28 + att_w, map_y0 + map_h - 8], radius=6, fill=(255, 255, 255), outline=(148, 163, 184), width=2)
    d.text((map_x0 + 19, map_y0 + map_h - 36), att_str, fill=(30, 41, 59), font=f_sm)

    # Right panel (1244..1764): Compass rose, Thematic & Elevation Legend, Scale bar
    paste_with_drop_shadow(img, (1244, 36, 1764, 924), radius=20, fill_rgb=(255, 255, 255), outline_rgb=(71, 85, 105), outline_w=4, shadow_offset=(6, 8))
    d = ImageDraw.Draw(img)
    # 8-point Compass Rose
    rcx, rcy = 1504, 168
    d.ellipse([rcx - 78, rcy - 78, rcx + 78, rcy + 78], fill=(248, 250, 252), outline=(148, 163, 184), width=3)
    d.polygon([(rcx, rcy - 74), (rcx - 18, rcy), (rcx + 18, rcy)], fill=(220, 38, 38), outline=(15, 23, 42), width=2)
    d.polygon([(rcx, rcy + 74), (rcx - 18, rcy), (rcx + 18, rcy)], fill=(71, 85, 105), outline=(15, 23, 42), width=2)
    d.polygon([(rcx - 74, rcy), (rcx, rcy - 16), (rcx, rcy + 16)], fill=(148, 163, 184), outline=(15, 23, 42), width=2)
    d.polygon([(rcx + 74, rcy), (rcx, rcy - 16), (rcx, rcy + 16)], fill=(148, 163, 184), outline=(15, 23, 42), width=2)
    d.text((rcx - 12, rcy - 112), "N", fill=(185, 28, 28), font=f_bold)
    d.text((rcx - 10, rcy + 80), "S", fill=(51, 65, 85), font=f_reg)
    d.text((rcx - 106, rcy - 15), "W", fill=(51, 65, 85), font=f_reg)
    d.text((rcx + 84, rcy - 15), "O", fill=(51, 65, 85), font=f_reg)

    # Legend
    d.text((1276, 315), "Höhenstufen & Legende:", fill=(15, 23, 42), font=f_bold)
    leg_items = [
        ((134, 239, 172), "Tiefland (< 200 m)"),
        ((217, 119, 6), "Bergland (200–800 m)"),
        ((180, 83, 9), "Mittelgebirge (> 800 m)"),
        ((37, 99, 235), "Hauptflüsse (Rhein/Neckar)"),
        ((153, 27, 27), "Grabenbruch-Verwerfung"),
        ((220, 38, 38), "Städte / Messstationen"),
    ]
    for idx, (col, lbl) in enumerate(leg_items):
        ly = 368 + idx * 62
        d.rounded_rectangle([1276, ly, 1336, ly + 42], radius=6, fill=col, outline=(15, 23, 42), width=3)
        d.text((1352, ly + 6), lbl, fill=(30, 41, 59), font=f_reg)

    # Scale bar
    d.line([(1276, 750), (1732, 750)], fill=(203, 213, 225), width=2)
    d.text((1276, 768), "Maßstab 1 : 2.500.000", fill=(15, 23, 42), font=f_bold)
    d.rectangle([1276, 816, 1436, 840], fill=(15, 23, 42), outline=(15, 23, 42), width=3)
    d.rectangle([1436, 816, 1596, 840], fill=(255, 255, 255), outline=(15, 23, 42), width=3)
    d.text((1272, 850), "0", fill=(15, 23, 42), font=f_reg)
    d.text((1420, 850), "25", fill=(15, 23, 42), font=f_reg)
    d.text((1570, 850), "50 km", fill=(15, 23, 42), font=f_reg)
    d.text((1276, 888), "Quelle: OpenStreetMap (ODbL)", fill=(100, 116, 139), font=f_sm)

    img.resize((900, 480), resample=Image.Resampling.LANCZOS).save(p1)
    paths["fig_geo_1"] = p1

    # -------------------------------------------------------------------------
    # 2a & 2b: Walter-Lieth Style Dual-Axis Climate Diagrams (1040x760 -> 520x380)
    # -------------------------------------------------------------------------
    stations = [
        (
            "fig_geo_2a",
            "geo_klima_freiburg.png",
            "Freiburg i. Br. (269 m ü. NN)",
            "Jahresmittel: 11,4 °C | Summe: 934 mm",
            "Klimatyp: Warm-gemäßigtes Weinbauklima (Oberrheinebene)",
            [2.4, 3.6, 7.5, 11.2, 15.6, 19.0, 21.1, 20.5, 16.4, 11.5, 6.1, 3.1],
            [52, 50, 62, 74, 98, 106, 96, 88, 78, 82, 74, 74],
        ),
        (
            "fig_geo_2b",
            "geo_klima_feldberg.png",
            "Feldberg / Schw. (1493 m ü. NN)",
            "Jahresmittel: 3,9 °C | Summe: 1909 mm",
            "Klimatyp: Kühl-feuchtes Mittelgebirgsklima (Staulage)",
            [-3.8, -3.5, -1.0, 2.1, 6.5, 9.8, 11.9, 11.6, 8.4, 4.9, -0.2, -2.9],
            [168, 148, 155, 134, 158, 166, 162, 154, 142, 166, 174, 182],
        ),
    ]
    months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    f_c_title = load_pil_font(28, bold=True)
    f_c_sub = load_pil_font(23, bold=True)
    f_c_reg = load_pil_font(22)
    f_c_sm = load_pil_font(20)

    for fig_key, fname, st_title, st_sub, st_type, temps, precs in stations:
        p_clim = os.path.join(FIGURES_DIR, fname)
        CW, CH = 1040, 760
        cimg = make_vertical_gradient(CW, CH, (248, 250, 252), (241, 245, 249), grain=1.5)
        paste_with_drop_shadow(cimg, (12, 12, CW - 12, CH - 12), radius=20, fill_rgb=(255, 255, 255), outline_rgb=(71, 85, 105), outline_w=4)
        cd = ImageDraw.Draw(cimg)
        # Header banner
        cd.rounded_rectangle([28, 24, CW - 28, 118], radius=12, fill=(239, 246, 255), outline=(147, 197, 253), width=2)
        cd.text((42, 30), st_title, fill=(15, 23, 42), font=f_c_title)
        cd.text((42, 66), st_sub, fill=(30, 64, 175), font=f_c_sub)
        cd.text((42, 92), st_type, fill=(71, 85, 105), font=f_c_sm)

        # Plot area: x=126..906, y=165..655 (0°C / 0mm at y=555)
        x0, x1, y_top, y_zero, y_bot = 126, 906, 165, 555, 655
        cd.rectangle([x0, y_top, x1, y_bot], fill=(252, 254, 255), outline=(100, 116, 139), width=3)

        # Horizontal & vertical gridlines
        cd.text((22, 126), "Temp. (°C)", fill=(185, 28, 28), font=f_c_reg)
        for t_val in (-10, 0, 10, 20, 30):
            ty = y_zero - int(t_val * 9.5)
            cd.line([(x0 - 8, ty), (x1, ty)], fill=(203, 213, 225) if t_val != 0 else (15, 23, 42), width=2 if t_val != 0 else 3)
            cd.text((44, ty - 14), f"{t_val}", fill=(185, 28, 28), font=f_c_reg)

        cd.text((860, 126), "Nied. (mm)", fill=(29, 78, 216), font=f_c_reg)
        for p_val in (0, 40, 80, 120, 160, 200):
            py = y_zero - int(p_val * 1.9)
            cd.line([(x1, py), (x1 + 8, py)], fill=(29, 78, 216), width=2)
            cd.text((920, py - 14), f"{p_val}", fill=(29, 78, 216), font=f_c_reg)

        col_w = (x1 - x0) / 12.0
        t_pts = []
        for m_i in range(12):
            gx = int(x0 + m_i * col_w)
            cd.line([(gx, y_top), (gx, y_bot)], fill=(241, 245, 249), width=2)
            bx = int(x0 + m_i * col_w + 8)
            bw_bar = int(col_w - 16)
            prec_mm = precs[m_i]
            by = y_zero - int(prec_mm * 1.9)
            # Perhumid (>100 mm) dark navy cap + standard humid blue bar
            cd.rectangle([bx, by, bx + bw_bar, y_zero], fill=(59, 130, 246), outline=(29, 78, 216), width=2)
            if prec_mm > 100:
                y_100 = y_zero - int(100 * 1.9)
                cd.rectangle([bx, by, bx + bw_bar, y_100], fill=(30, 58, 138), outline=(29, 78, 216), width=2)
            cd.text((bx + 14, y_bot + 12), months[m_i], fill=(15, 23, 42), font=f_c_reg)
            tx = int(x0 + (m_i + 0.5) * col_w)
            ty = y_zero - int(temps[m_i] * 9.5)
            t_pts.append((tx, ty))

        # Smooth red temperature curve with white-halo markers
        cd.line(t_pts, fill=(220, 38, 38), width=8)
        for tx, ty in t_pts:
            cd.ellipse([tx - 9, ty - 9, tx + 9, ty + 9], fill=(220, 38, 38), outline=(255, 255, 255), width=3)

        cimg.resize((520, 380), resample=Image.Resampling.LANCZOS).save(p_clim)
        paths[fig_key] = p_clim

    # -------------------------------------------------------------------------
    # 3. Historical Timeline (Zeitleiste 1835-1914) with Era Bands - 1800x500 -> 900x250
    # -------------------------------------------------------------------------
    p3 = os.path.join(FIGURES_DIR, "hist_zeitleiste_industrialisierung.png")
    W, H = 1800, 500
    img = make_vertical_gradient(W, H, (254, 252, 232), (254, 243, 199), grain=2.5)
    paste_with_drop_shadow(img, (12, 12, W - 12, H - 12), radius=24, fill_rgb=(255, 251, 235), outline_rgb=(161, 98, 7), outline_w=5)
    d = ImageDraw.Draw(img)
    d.text((52, 28), "Zeitleiste: Industrialisierung und Soziale Frage in Deutschland (1835–1914)", fill=(113, 63, 18), font=f_title)

    # Era background bands along timeline track
    y_track = 276
    d.rounded_rectangle([76, y_track - 22, 850, y_track + 22], radius=8, fill=(253, 230, 138), outline=(180, 83, 9), width=3)
    d.rounded_rectangle([850, y_track - 22, 1685, y_track + 22], radius=8, fill=(251, 191, 36), outline=(146, 64, 14), width=3)
    d.polygon([(1735, y_track), (1680, y_track - 32), (1680, y_track + 32)], fill=(120, 53, 15))
    d.text((225, y_track - 14), "Frühindustrialisierung", fill=(120, 53, 15), font=f_sm)
    d.text((915, y_track - 14), "Hochindustrialisierung", fill=(120, 53, 15), font=f_sm)

    events = [
        (190, "1835", "Erste Eisenbahn", "(Nürnberg–Fürth)", True),
        (510, "1848", "Märzrevolution", "(Verfassungsforderung)", False),
        (870, "1871", "Reichsgründung", "(Hochindustrialisierung)", True),
        (1230, "1883–89", "Sozialgesetze", "(Kranken- & Rentenvers.)", False),
        (1550, "1914", "Vorabend 1. WK", "(Elektro- & Chemieind.)", True),
    ]
    for ex, yr, l1, l2, above in events:
        if above:
            d.line([(ex, y_track - 22), (ex, 206)], fill=(180, 83, 9), width=5)
            paste_with_drop_shadow(img, (ex - 150, 84, ex + 150, 204), radius=14, fill_rgb=(255, 255, 255), outline_rgb=(180, 83, 9), outline_w=3, shadow_offset=(4, 5))
            d = ImageDraw.Draw(img)
            d.text((ex - 48, 92), yr, fill=(180, 83, 9), font=f_bold)
            d.text((ex - 134, 130), l1, fill=(15, 23, 42), font=f_reg)
            d.text((ex - 134, 162), l2, fill=(71, 85, 105), font=f_sm)
        else:
            d.line([(ex, y_track + 22), (ex, 344)], fill=(180, 83, 9), width=5)
            paste_with_drop_shadow(img, (ex - 155, 344, ex + 155, 464), radius=14, fill_rgb=(255, 255, 255), outline_rgb=(180, 83, 9), outline_w=3, shadow_offset=(4, 5))
            d = ImageDraw.Draw(img)
            d.text((ex - 58, 352), yr, fill=(180, 83, 9), font=f_bold)
            d.text((ex - 140, 390), l1, fill=(15, 23, 42), font=f_reg)
            d.text((ex - 140, 422), l2, fill=(71, 85, 105), font=f_sm)
        d.ellipse([ex - 16, y_track - 16, ex + 16, y_track + 16], fill=(185, 28, 28), outline=(255, 255, 255), width=4)

    img.resize((900, 250), resample=Image.Resampling.LANCZOS).save(p3)
    paths["fig_hist_1"] = p3
    return paths


def generate_sek2_chem_bio_figures() -> Dict[str, str]:
    """Generates 2x-supersampled chemical structural formulas (with stereo-wedged Haworth ring) and Michaelis-Menten curve."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    paths: Dict[str, str] = {}
    f_title = load_pil_font(32, bold=True)
    f_bold = load_pil_font(28, bold=True)
    f_reg = load_pil_font(25)
    f_small = load_pil_font(22)

    # -------------------------------------------------------------------------
    # 1. 2D Organic Structural Formulas + Haworth Projection - 1800x680 -> 900x340
    # -------------------------------------------------------------------------
    p1 = os.path.join(FIGURES_DIR, "chem_strukturformeln_veresterung_glucose.png")
    W, H = 1800, 680
    img = make_vertical_gradient(W, H, (248, 250, 252), (241, 245, 249), grain=1.5)
    paste_with_drop_shadow(img, (12, 12, 1044, H - 12), radius=20, fill_rgb=(255, 255, 255), outline_rgb=(13, 148, 136), outline_w=4)
    paste_with_drop_shadow(img, (1068, 12, W - 12, H - 12), radius=20, fill_rgb=(255, 255, 255), outline_rgb=(37, 99, 235), outline_w=4)
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([28, 26, 1028, 82], radius=10, fill=(240, 253, 250))
    d.text((44, 38), "A) Säurekatalysierte Veresterung (Skelettformel)", fill=(19, 78, 74), font=f_bold)
    d.rounded_rectangle([1084, 26, W - 28, 82], radius=10, fill=(239, 246, 255))
    d.text((1100, 38), "B) α-D-Glucopyranose (Haworth-Formel)", fill=(30, 58, 138), font=f_bold)

    # Shaded functional-group highlight halos on Panel A
    d.rounded_rectangle([128, 104, 290, 312], radius=18, fill=(254, 226, 226), outline=(252, 165, 165), width=2)  # Carboxyl halo
    d.rounded_rectangle([350, 242, 430, 312], radius=14, fill=(219, 234, 254), outline=(147, 197, 253), width=2)  # Hydroxyl halo
    d.rounded_rectangle([752, 104, 912, 312], radius=18, fill=(254, 243, 199), outline=(252, 211, 77), width=2)   # Ester halo

    # Acetic acid skeletal: CH3-C(=O)-OH
    d.line([(72, 290), (152, 240)], fill=(15, 23, 42), width=6)
    d.line([(146, 240), (146, 148)], fill=(15, 23, 42), width=6)
    d.line([(158, 240), (158, 148)], fill=(15, 23, 42), width=6)
    d.text((138, 106), "O", fill=(220, 38, 38), font=f_bold)
    d.line([(152, 240), (224, 284)], fill=(15, 23, 42), width=6)
    d.text((230, 266), "OH", fill=(220, 38, 38), font=f_bold)
    d.text((64, 340), "Ethansäure", fill=(51, 65, 85), font=f_reg)
    d.text((312, 236), "+", fill=(15, 23, 42), font=f_title)

    # Ethanol skeletal: HO-CH2-CH3
    d.text((358, 266), "HO", fill=(29, 78, 216), font=f_bold)
    d.line([(416, 284), (484, 240), (552, 284)], fill=(29, 78, 216), width=6)
    d.text((390, 340), "Ethanol", fill=(51, 65, 85), font=f_reg)

    # Equilibrium arrows with H+ catalyst
    d.text((604, 184), "H⁺", fill=(185, 28, 28), font=f_bold)
    d.line([(584, 244), (680, 244)], fill=(15, 23, 42), width=6)
    d.polygon([(686, 244), (662, 230), (662, 244)], fill=(15, 23, 42))
    d.line([(584, 264), (680, 264)], fill=(15, 23, 42), width=6)
    d.polygon([(578, 264), (602, 264), (602, 278)], fill=(15, 23, 42))

    # Ethyl acetate skeletal + H2O
    d.line([(716, 290), (784, 240)], fill=(15, 23, 42), width=6)
    d.line([(778, 240), (778, 148)], fill=(15, 23, 42), width=6)
    d.line([(790, 240), (790, 148)], fill=(15, 23, 42), width=6)
    d.text((770, 106), "O", fill=(220, 38, 38), font=f_bold)
    d.line([(784, 240), (844, 280)], fill=(15, 23, 42), width=6)
    d.text((850, 264), "O", fill=(29, 78, 216), font=f_bold)
    d.line([(884, 276), (936, 236), (992, 276)], fill=(29, 78, 216), width=6)
    d.text((712, 340), "Ethylethanoat + H₂O", fill=(51, 65, 85), font=f_reg)

    # Bottom summary box on Panel A
    d.rounded_rectangle([40, 428, 1016, 636], radius=14, fill=(248, 250, 252), outline=(203, 213, 225), width=3)
    d.text((58, 446), "Funktionelle Gruppen & Kondensationsmechanismus:", fill=(15, 23, 42), font=f_bold)
    d.text((58, 496), "• Carboxylgruppe (-COOH, rot) + Hydroxylgruppe (-OH, blau)", fill=(30, 41, 59), font=f_small)
    d.text((58, 540), "• Nukleophiler Angriff  ⇌  Estergruppe (-COO-, gelb) + Wassermolekül (H₂O)", fill=(30, 41, 59), font=f_small)
    d.text((58, 584), "• Gleichgewichtskonstante bei 25 °C:  Kc ≈ 4,0  (Ausbeute ~67 % im 1:1-Ansatz)", fill=(19, 78, 74), font=f_small)

    # Right panel: Stereo-wedged Haworth projection of alpha-D-Glucopyranose
    ring = [(1256, 232), (1488, 232), (1592, 372), (1488, 512), (1256, 512), (1152, 372)]
    d.polygon(ring, outline=(15, 23, 42), fill=(252, 254, 255), width=5)
    # Stereo-thickened front lower bonds (C1-C2-C3-C4) as in authentic chemistry textbooks
    d.polygon([(1152, 372), (1256, 504), (1256, 522), (1152, 378)], fill=(15, 23, 42))
    d.polygon([(1592, 372), (1488, 504), (1488, 522), (1592, 378)], fill=(15, 23, 42))
    d.rectangle([1256, 504, 1488, 522], fill=(15, 23, 42))

    # Ring oxygen at top-right vertex (1488, 232)
    d.ellipse([1458, 202, 1518, 262], fill=(254, 226, 226), outline=(220, 38, 38), width=3)
    d.text((1474, 214), "O", fill=(220, 38, 38), font=f_bold)

    # Carbon number badges & axial/equatorial OH substituents C1..C6
    # C1 (anomeric carbon, right vertex 1592, 372)
    d.line([(1592, 372), (1592, 468)], fill=(185, 28, 28), width=6)
    d.rounded_rectangle([1536, 472, 1756, 522], radius=10, fill=(254, 226, 226), outline=(185, 28, 28), width=3)
    d.text((1550, 480), "OH (C1, α)", fill=(185, 28, 28), font=f_bold)
    # C2 (bottom-right 1488, 512)
    d.line([(1488, 512), (1488, 594)], fill=(15, 23, 42), width=6)
    d.text((1464, 600), "OH", fill=(15, 23, 42), font=f_reg)
    # C3 (bottom-left 1256, 512) -> OH pointing UP
    d.line([(1256, 512), (1256, 426)], fill=(15, 23, 42), width=6)
    d.text((1232, 388), "OH", fill=(15, 23, 42), font=f_reg)
    # C4 (left vertex 1152, 372) -> OH pointing DOWN
    d.line([(1152, 372), (1152, 468)], fill=(15, 23, 42), width=6)
    d.text((1124, 474), "OH", fill=(15, 23, 42), font=f_reg)
    # C5 (top-left 1256, 232) -> CH2OH pointing UP
    d.line([(1256, 232), (1256, 148)], fill=(29, 78, 216), width=6)
    d.rounded_rectangle([1188, 98, 1408, 146], radius=10, fill=(219, 234, 254), outline=(29, 78, 216), width=3)
    d.text((1204, 106), "CH₂OH (C6)", fill=(29, 78, 216), font=f_bold)

    img.resize((900, 340), resample=Image.Resampling.LANCZOS).save(p1)
    paths["fig_chem_1"] = p1

    # -------------------------------------------------------------------------
    # 2. Enzyme Kinetics Michaelis-Menten Curve + Lock-and-Key Inset - 1800x720 -> 900x360
    # -------------------------------------------------------------------------
    p2 = os.path.join(FIGURES_DIR, "bio_michaelis_menten_kinetik.png")
    W, H = 1800, 720
    img = make_vertical_gradient(W, H, (248, 250, 252), (240, 253, 250), grain=1.5)
    paste_with_drop_shadow(img, (12, 12, W - 12, H - 12), radius=22, fill_rgb=(255, 255, 255), outline_rgb=(15, 118, 110), outline_w=4)
    d = ImageDraw.Draw(img)
    d.text((48, 28), "Enzymkinetik nach Michaelis-Menten (ohne und mit kompetitivem Hemmstoff)", fill=(15, 23, 42), font=f_title)

    ox, oy = 185, 608
    xmax, ymax = 1280, 104
    # Fine coordinate grid
    for gx in range(ox + 150, xmax, 150):
        d.line([(gx, ymax), (gx, oy)], fill=(226, 232, 240), width=2)
    for gy in range(ymax + 80, oy, 80):
        d.line([(ox, gy), (xmax, gy)], fill=(226, 232, 240), width=2)

    # Axes with arrowheads
    d.line([(ox, oy), (xmax, oy)], fill=(15, 23, 42), width=6)
    d.polygon([(xmax + 16, oy), (xmax - 8, oy - 12), (xmax - 8, oy + 12)], fill=(15, 23, 42))
    d.line([(ox, oy), (ox, ymax)], fill=(15, 23, 42), width=6)
    d.polygon([(ox, ymax - 16), (ox - 12, ymax + 8), (ox + 12, ymax + 8)], fill=(15, 23, 42))
    d.text((540, 646), "Substratkonzentration [S] in mmol/L →", fill=(15, 23, 42), font=f_bold)
    d.text((146, 82), "v", fill=(15, 23, 42), font=f_bold)

    # vmax and 1/2 vmax dashed reference lines
    y_vmax = 156
    y_half = (oy + y_vmax) // 2
    for x_dash in range(ox, xmax - 10, 28):
        d.line([(x_dash, y_vmax), (x_dash + 16, y_vmax)], fill=(185, 28, 28), width=4)
        d.line([(x_dash, y_half), (x_dash + 16, y_half)], fill=(30, 64, 175), width=4)
    d.text((38, y_vmax - 18), "v_max", fill=(185, 28, 28), font=f_bold)
    d.text((28, y_half - 18), "½ v_max", fill=(30, 64, 175), font=f_bold)

    # Hyperbolic curves: v = vmax * S / (Km + S)
    vmax_px = oy - y_vmax
    km1_px = 145.0
    km2_px = 365.0
    pts_no_inh = []
    pts_comp = []
    for dx in range(0, xmax - ox - 20, 6):
        v1 = vmax_px * dx / (km1_px + dx)
        v2 = vmax_px * dx / (km2_px + dx)
        pts_no_inh.append((ox + dx, int(oy - v1)))
        pts_comp.append((ox + dx, int(oy - v2)))
    d.line(pts_no_inh, fill=(22, 163, 74), width=8)
    d.line(pts_comp, fill=(217, 119, 6), width=8)

    # Experimental data points along curves
    for dx_pt in (60, 145, 280, 520, 820, 1040):
        for km_val, col in [(km1_px, (21, 128, 61)), (km2_px, (180, 83, 9))]:
            vy = int(oy - vmax_px * dx_pt / (km_val + dx_pt))
            d.ellipse([ox + dx_pt - 8, vy - 8, ox + dx_pt + 8, vy + 8], fill=col, outline=(255, 255, 255), width=3)

    # Km vertical drop lines
    x_km1 = int(ox + km1_px)
    x_km2 = int(ox + km2_px)
    d.line([(x_km1, y_half), (x_km1, oy)], fill=(22, 163, 74), width=4)
    d.line([(x_km2, y_half), (x_km2, oy)], fill=(217, 119, 6), width=4)
    d.text((x_km1 - 28, oy + 14), "K_M", fill=(21, 128, 61), font=f_bold)
    d.text((x_km2 - 30, oy + 14), "K_M'", fill=(180, 83, 9), font=f_bold)

    d.text((590, 178), "Ohne Hemmstoff (K_M klein)", fill=(21, 128, 61), font=f_bold)
    d.text((685, 348), "Kompetitive Hemmung (K_M' erhöht)", fill=(180, 83, 9), font=f_bold)

    # Right sidebar inset card (x=1320..1760): Molecular Lock-and-Key Competitive Inhibition Diagram
    paste_with_drop_shadow(img, (1320, 104, 1760, 646), radius=18, fill_rgb=(240, 253, 250), outline_rgb=(13, 148, 136), outline_w=3, shadow_offset=(4, 6))
    d = ImageDraw.Draw(img)
    d.text((1342, 124), "Molekularer Mechanismus:", fill=(19, 78, 74), font=load_pil_font(25, bold=True))
    d.text((1342, 160), "Kompetitive Hemmung", fill=(180, 83, 9), font=f_reg)
    # Enzyme active site graphic
    ecx, ecy = 1540, 340
    d.pieslice([ecx - 115, ecy - 115, ecx + 115, ecy + 115], start=35, end=325, fill=(45, 212, 191), outline=(15, 118, 110), width=4)
    # Substrate (green wedge) vs Competitive Inhibitor (orange wedge) competing for active cleft
    d.polygon([(ecx + 95, ecy - 65), (ecx + 165, ecy - 95), (ecx + 165, ecy - 25)], fill=(34, 197, 94), outline=(20, 83, 45), width=3)
    d.text((1585, 206), "Substrat [S]", fill=(21, 128, 61), font=f_small)
    d.polygon([(ecx + 85, ecy + 45), (ecx + 165, ecy + 15), (ecx + 165, ecy + 85)], fill=(245, 158, 11), outline=(146, 64, 14), width=3)
    d.text((1585, 436), "Inhibitor [I]", fill=(180, 83, 9), font=f_small)
    d.text((1442, 326), "Enzym", fill=(19, 78, 74), font=f_bold)
    d.text((1346, 505), "• [S] und [I] konkurrieren um", fill=(30, 41, 59), font=f_small)
    d.text((1362, 535), "dasselbe aktive Zentrum.", fill=(30, 41, 59), font=f_small)
    d.text((1346, 575), "• Hohes [S] verdrängt [I]", fill=(30, 41, 59), font=f_small)
    d.text((1362, 605), "→ v_max bleibt unverändert.", fill=(19, 78, 74), font=f_small)

    img.resize((900, 360), resample=Image.Resampling.LANCZOS).save(p2)
    paths["fig_bio_1"] = p2

    # -------------------------------------------------------------------------
    # 3. Double-Slit Interference & Intensity Profile - 1800x640 -> 900x320
    # -------------------------------------------------------------------------
    p3 = os.path.join(FIGURES_DIR, "physik_doppelspalt_interferenz.png")
    W, H = 1800, 640
    img = make_vertical_gradient(W, H, (240, 249, 255), (224, 242, 254), grain=2.0)
    paste_with_drop_shadow(img, (14, 14, W - 14, H - 14), radius=22, fill_rgb=(255, 255, 255), outline_rgb=(30, 64, 175), outline_w=5)
    d = ImageDraw.Draw(img)
    d.text((48, 30), "Doppelspalt-Interferenz: Kohärente Elementarwellen und Intensitätsverlauf I(α)", fill=(30, 58, 138), font=f_title)

    # Left diagram: Laser beam -> Double slit S1, S2 -> Screen with interference fringes
    d.line([(60, 340), (240, 340)], fill=(220, 38, 38), width=10)
    d.text((64, 298), "Laser (λ = 632,8 nm)", fill=(185, 28, 28), font=f_bold)
    # Slit barrier at x=250 with slits at y=250 and y=430
    d.rectangle([244, 110, 260, 232], fill=(30, 41, 59))
    d.rectangle([244, 268, 260, 412], fill=(30, 41, 59))
    d.rectangle([244, 448, 260, 570], fill=(30, 41, 59))
    d.text((205, 235), "S₁", fill=(30, 58, 138), font=f_bold)
    d.text((205, 415), "S₂", fill=(30, 58, 138), font=f_bold)
    # Semicircular Huygens wave fronts from S1 and S2
    for rad in range(70, 560, 70):
        d.arc([252 - rad, 250 - rad, 252 + rad, 250 + rad], start=-55, end=55, fill=(239, 68, 68), width=3)
        d.arc([252 - rad, 430 - rad, 252 + rad, 430 + rad], start=-55, end=55, fill=(59, 130, 246), width=3)
    # Observation screen at x=880
    d.line([(880, 100), (880, 580)], fill=(15, 23, 42), width=6)
    for k_ord, fy in [(-2, 140), (-1, 240), (0, 340), (1, 440), (2, 540)]:
        d.ellipse([866, fy - 16, 894, fy + 16], fill=(220, 38, 38), outline=(127, 29, 29), width=2)
        d.text((908, fy - 14), f"k = {k_ord} (Max.)", fill=(30, 41, 59), font=f_small)

    # Right diagram: Intensity profile curve I(y)
    paste_with_drop_shadow(img, (1080, 96, 1750, 584), radius=16, fill_rgb=(248, 250, 252), outline_rgb=(59, 130, 246), outline_w=3)
    d = ImageDraw.Draw(img)
    d.text((1112, 114), "Intensitätsverteilung I(y) auf dem Schirm", fill=(30, 58, 138), font=f_bold)
    curve_pts = []
    for py in range(165, 555, 3):
        dy = (py - 360) / 100.0
        envelope = math.exp(-0.22 * dy * dy)
        val = (math.cos(math.pi * dy) ** 2) * envelope
        px = 1140 + int(val * 540)
        curve_pts.append((px, py))
    d.line([(1140, 160), (1140, 560)], fill=(71, 85, 105), width=3)
    d.line(curve_pts, fill=(220, 38, 38), width=6)
    d.text((1460, 344), "Hauptmaximum (k = 0)", fill=(185, 28, 28), font=f_small)
    d.text((1160, 520), "Δs = k · λ (konstruktiv)", fill=(30, 58, 138), font=f_small)

    img.resize((900, 320), resample=Image.Resampling.LANCZOS).save(p3)
    paths["fig_phys_1"] = p3
    return paths


# ---------------------------------------------------------------------------
# ReportLab Drawing Helpers (Mascots, Pictograms, GHS Symbols, Headers)
# ---------------------------------------------------------------------------

def draw_decorative_owl_mascot(c: canvas.Canvas, x: float, y: float) -> None:
    """Draws a multi-layered vector owl mascot perched on a leafy twig with feather tufts & beak (omitted in FIBS 09/2025)."""
    c.saveState()
    # Wooden branch + green leaf below owl
    c.setStrokeColor(colors.HexColor("#78350F"))
    c.setLineWidth(3.0)
    c.line(x - 22, y - 16, x + 22, y - 14)
    c.setFillColor(colors.HexColor("#22C55E"))
    c.setStrokeColor(colors.HexColor("#15803D"))
    c.setLineWidth(0.9)
    c.ellipse(x + 12, y - 15, x + 21, y - 10, fill=1, stroke=1)
    # Ear tufts
    p_ears = c.beginPath()
    p_ears.moveTo(x - 14, y + 8)
    p_ears.lineTo(x - 18, y + 20)
    p_ears.lineTo(x - 5, y + 14)
    p_ears.moveTo(x + 14, y + 8)
    p_ears.lineTo(x + 18, y + 20)
    p_ears.lineTo(x + 5, y + 14)
    p_ears.close()
    c.setFillColor(colors.HexColor("#B45309"))
    c.setStrokeColor(colors.HexColor("#78350F"))
    c.setLineWidth(1.2)
    c.drawPath(p_ears, fill=1, stroke=1)
    # Body & folded side wings
    c.setFillColor(colors.HexColor("#D97706"))
    c.circle(x, y, 16, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#B45309"))
    c.ellipse(x - 17, y - 10, x - 11, y + 4, fill=1, stroke=1)
    c.ellipse(x + 11, y - 10, x + 17, y + 4, fill=1, stroke=1)
    # Cream belly patch with small feather scallop lines
    c.setFillColor(colors.HexColor("#FEF3C7"))
    c.ellipse(x - 10, y - 13, x + 10, y + 3, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#D97706"))
    c.setLineWidth(0.9)
    for fx, fy in [(-4, -5), (4, -5), (0, -8), (-4, -10), (4, -10)]:
        c.arc(x + fx - 2.5, y + fy - 1.5, x + fx + 2.5, y + fy + 1.5, 180, 180)
    # Little orange claws on branch
    c.setFillColor(colors.HexColor("#EA580C"))
    c.circle(x - 5, y - 15, 2.0, fill=1, stroke=0)
    c.circle(x + 5, y - 15, 2.0, fill=1, stroke=0)
    # Eyes & pupils
    c.setStrokeColor(colors.HexColor("#78350F"))
    c.setLineWidth(1.1)
    c.setFillColor(colors.white)
    c.circle(x - 5.5, y + 4, 5.2, fill=1, stroke=1)
    c.circle(x + 5.5, y + 4, 5.2, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#1E293B"))
    c.circle(x - 5.0, y + 4, 2.3, fill=1, stroke=0)
    c.circle(x + 5.0, y + 4, 2.3, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.circle(x - 4.2, y + 4.8, 0.8, fill=1, stroke=0)
    c.circle(x + 5.8, y + 4.8, 0.8, fill=1, stroke=0)
    # Orange beak triangle
    beak = c.beginPath()
    beak.moveTo(x - 3, y + 1)
    beak.lineTo(x + 3, y + 1)
    beak.lineTo(x, y - 4)
    beak.close()
    c.setFillColor(colors.HexColor("#EA580C"))
    c.drawPath(beak, fill=1, stroke=0)
    c.restoreState()


def draw_partner_pictogram(c: canvas.Canvas, x: float, y: float) -> None:
    """Draws a small instructional partner-work icon (two student silhouettes)."""
    c.saveState()
    c.setFillColor(colors.HexColor("#2563EB"))
    c.circle(x, y + 7, 3.2, fill=1, stroke=0)
    c.circle(x + 8, y + 7, 3.2, fill=1, stroke=0)
    c.roundRect(x - 3.5, y - 1, 7, 5.5, 2, fill=1, stroke=0)
    c.roundRect(x + 4.5, y - 1, 7, 5.5, 2, fill=1, stroke=0)
    c.restoreState()


def draw_scissors_glue_pictogram(c: canvas.Canvas, x: float, y: float) -> None:
    """Draws a small instructional scissors-and-glue icon."""
    c.saveState()
    c.setStrokeColor(colors.HexColor("#D97706"))
    c.setLineWidth(1.4)
    c.circle(x, y + 2, 2.5, fill=0, stroke=1)
    c.circle(x, y + 7, 2.5, fill=0, stroke=1)
    c.line(x + 2, y + 3, x + 10, y + 8)
    c.line(x + 2, y + 6, x + 10, y + 1)
    c.restoreState()


def draw_ghs_diamond(c: canvas.Canvas, cx: float, cy: float, r: float, symbol: str, fonts: Dict[str, str]) -> None:
    """Draws a red-bordered GHS hazard diamond with inner vector hazard pictogram (flame, corrosive, exclamation)."""
    c.saveState()
    p = c.beginPath()
    p.moveTo(cx, cy + r)
    p.lineTo(cx + r, cy)
    p.lineTo(cx, cy - r)
    p.lineTo(cx - r, cy)
    p.close()
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#DC2626"))
    c.setLineWidth(2.2)
    c.drawPath(p, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#111827"))
    c.setStrokeColor(colors.HexColor("#111827"))
    if symbol == "GHS02":
        c.setLineWidth(1.5)
        c.line(cx - 6, cy - 6, cx + 6, cy - 6)
        flame = c.beginPath()
        flame.moveTo(cx, cy + 8)
        flame.lineTo(cx + 5, cy + 1)
        flame.lineTo(cx + 3, cy - 5)
        flame.lineTo(cx - 3, cy - 5)
        flame.lineTo(cx - 5, cy + 1)
        flame.close()
        c.drawPath(flame, fill=1, stroke=0)
    elif symbol == "GHS05":
        c.setLineWidth(1.5)
        c.line(cx - 7, cy - 6, cx + 7, cy - 6)
        c.line(cx - 6, cy + 5, cx - 1, cy + 1)
        c.line(cx + 6, cy + 5, cx + 1, cy + 1)
        c.circle(cx - 1, cy - 2, 1.2, fill=1, stroke=0)
        c.circle(cx + 1, cy - 3.5, 1.2, fill=1, stroke=0)
    else:
        c.setFont(fonts["SansBold"], 14)
        c.drawCentredString(cx, cy - 5, "!")
    c.setFont(fonts["SansBold"], 6.5)
    c.setFillColor(colors.HexColor("#991B1B"))
    c.drawCentredString(cx, cy - r - 7, symbol)
    c.restoreState()


def draw_book_header_footer(
    c: canvas.Canvas,
    page_num: int,
    chapter_title: str,
    subject_label: str,
    fonts: Dict[str, str],
    accent_hex: str = "#1E40AF",
) -> None:
    """Draws alternating even/odd textbook running headers, decorative margin accent strip, and printed page numbers."""
    c.saveState()
    c.setStrokeColor(colors.HexColor(accent_hex))
    c.setLineWidth(1.0)
    c.line(48, PAGE_H - 42, PAGE_W - 48, PAGE_H - 42)
    c.line(48, 42, PAGE_W - 48, 42)
    # Subtle outer margin chapter tab bar (purely decorative visual polish)
    c.setFillColor(colors.HexColor(accent_hex))
    if page_num % 2 == 0:
        c.rect(0, PAGE_H - 110, 10, 52, fill=1, stroke=0)
    else:
        c.rect(PAGE_W - 10, PAGE_H - 110, 10, 52, fill=1, stroke=0)
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.HexColor("#475569"))
    if page_num % 2 == 0:
        c.drawString(48, PAGE_H - 36, f"{page_num}   |   {chapter_title}")
        c.drawRightString(PAGE_W - 48, PAGE_H - 36, subject_label)
        c.drawString(48, 28, str(page_num))
    else:
        c.drawString(48, PAGE_H - 36, subject_label)
        c.drawRightString(PAGE_W - 48, PAGE_H - 36, f"{chapter_title}   |   {page_num}")
        c.drawRightString(PAGE_W - 48, 28, str(page_num))
    c.restoreState()


def draw_styled_emphasis_sentence(
    c: canvas.Canvas,
    x: float,
    y: float,
    prefix: str,
    bold_word: str,
    mid_text: str,
    italic_phrase: str,
    underlined_phrase: str,
    fonts: Dict[str, str],
    size: float = 9.4,
) -> None:
    """Draws a sentence with real bold, italic, and underlined spans in ReportLab."""
    cur_x = x
    c.setFont(fonts["Sans"], size)
    c.drawString(cur_x, y, prefix)
    cur_x += c.stringWidth(prefix, fonts["Sans"], size)

    c.setFont(fonts["SansBold"], size)
    c.drawString(cur_x, y, bold_word)
    cur_x += c.stringWidth(bold_word, fonts["SansBold"], size)

    c.setFont(fonts["Sans"], size)
    c.drawString(cur_x, y, mid_text)
    cur_x += c.stringWidth(mid_text, fonts["Sans"], size)

    c.setFont(fonts["SansOblique"], size)
    c.drawString(cur_x, y, italic_phrase)
    cur_x += c.stringWidth(italic_phrase, fonts["SansOblique"], size)

    c.setFont(fonts["Sans"], size)
    c.drawString(cur_x, y, " ")
    cur_x += c.stringWidth(" ", fonts["Sans"], size)

    u_w = c.stringWidth(underlined_phrase, fonts["Sans"], size)
    c.drawString(cur_x, y, underlined_phrase)
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(cur_x, y - 1.8, cur_x + u_w, y - 1.8)
    c.restoreState()
    cur_x += u_w
    c.drawString(cur_x, y, ".")


def draw_two_column_section(
    c: canvas.Canvas,
    y_top: float,
    left_lines: List[str],
    right_lines: List[str],
    fonts: Dict[str, str],
    font_key: str = "Serif",
    font_size: float = 8.8,
    line_h: float = 13.5,
) -> float:
    """
    Renders a 2-column scientific textbook prose block (x_col1=48..286, x_col2=308..547)
    with a subtle vertical column rule at x=297 pt. Returns the bottom y coordinate.
    """
    c.saveState()
    c.setFont(fonts[font_key], font_size)
    c.setFillColor(colors.black)
    max_rows = max(len(left_lines), len(right_lines))
    for r_idx, l_txt in enumerate(left_lines):
        c.drawString(48.0, y_top - r_idx * line_h, l_txt)
    for r_idx, r_txt in enumerate(right_lines):
        c.drawString(308.0, y_top - r_idx * line_h, r_txt)
    y_bot = y_top - max(0, max_rows - 1) * line_h - 4.0
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setLineWidth(0.8)
    c.line(297.0, y_bot, 297.0, y_top + 8.0)
    c.restoreState()
    return y_bot


# ---------------------------------------------------------------------------
# PDF Builders for the 8 Single-Subject Schoolbooks (85%–92% Page Density)
# ---------------------------------------------------------------------------

def build_grundschule_mathe_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 3-page Grundschule Klasse 3 Mathematik PDF (pages 14–16) with □/◩/■ difficulty icons."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Zahlenreise 3: Mathematik für die Grundschule")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 14 ====================
    draw_book_header_footer(c, 14, "Kapitel 1: Orientierung im Zahlenraum bis 1000", "Mathematik · Klasse 3", fonts, "#2563EB")
    draw_decorative_owl_mascot(c, PAGE_W - 72, PAGE_H - 76)

    c.setFont(fonts["SansBold"], 17.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 74, "Mathematik – Klasse 3")
    c.setFont(fonts["SansBold"], 12.8)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(48, PAGE_H - 96, "Kapitel 1: Große Zahlen und Orientierung bis 1000")

    c.setFont(fonts["Sans"], 10.0)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 118, "Auf unserer Zahlenreise entdecken wir Hunderter, Zehner und Einer. Schau dir den Zahlenstrahl")
    c.drawString(48, PAGE_H - 133, "genau an und ergänze die fehlenden Zielzahlen in den Kästchen.")

    # Figure 1.1: Zahlenstrahl
    fig1_x, fig1_y, fig1_w, fig1_h = 48.0, PAGE_H - 291.0, 495.0, 143.0
    c.drawImage(figs["fig_gs_1"], fig1_x, fig1_y, width=fig1_w, height=fig1_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.drawString(48, fig1_y - 14, "Abb. 1.1: Sprünge am Zahlenstrahl bis 1000")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_gs_1", 0, 14, "figures/gs_zahlenstrahl_1000.png",
            "Abb. 1.1: Sprünge am Zahlenstrahl bis 1000", "Zahlenstrahl",
            fig1_x, fig1_y, fig1_w, fig1_h, 900, 260
        )
    )

    # Task 1: 2-column arithmetic grid a) - j) with square icon □ and vector partner pictogram ONLY
    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#0F172A"))
    t1_prefix = "Aufgabe 1 □: Kopfrechnen im Tausenderraum"
    c.drawString(48, fig1_y - 36, t1_prefix)
    px1 = 48 + c.stringWidth(t1_prefix, fonts["SansBold"], 10.6)
    draw_partner_pictogram(c, px1 + 10, fig1_y - 36)
    c.setFont(fonts["Sans"], 9.8)
    c.drawString(48, fig1_y - 52, "Rechnet abwechselnd. Tragt die Ergebnisse auf den Linien ein:")

    col1_tasks = [
        ("a) 150 + 250 = ____", 48, fig1_y - 72),
        ("b) 320 + 180 = ____", 48, fig1_y - 89),
        ("c) 460 + 240 = ____", 48, fig1_y - 106),
        ("d) 780 - 350 = ____", 48, fig1_y - 123),
        ("e) 900 - 420 = ____", 48, fig1_y - 140),
    ]
    col2_tasks = [
        ("f) 275 + 125 = ____", 310, fig1_y - 72),
        ("g) 640 - 190 = ____", 310, fig1_y - 89),
        ("h) 510 + 390 = ____", 310, fig1_y - 106),
        ("i) 850 - 270 = ____", 310, fig1_y - 123),
        ("j) 999 - 333 = ____", 310, fig1_y - 140),
    ]
    c.setFont(fonts["Mono"], 10.2)
    for txt, tx, ty in col1_tasks + col2_tasks:
        c.drawString(tx, ty, txt)

    # Task 2: Place value decomposition with drawn empty answer boxes (icon ◩ only)
    c.setFont(fonts["SansBold"], 10.8)
    c.drawString(48, fig1_y - 168, "Aufgabe 2 ◩: Hunderter, Zehner und Einer zerlegen")
    c.setFont(fonts["Sans"], 9.8)
    c.drawString(48, fig1_y - 184, "Zerlege die Zahlen in Hunderter (H), Zehner (Z) und Einer (E):")

    def draw_line_with_boxes(y_line: float, segments: List[str]) -> None:
        cx_pos = 48.0
        c.setFont(fonts["Sans"], 9.8)
        for seg_idx, seg in enumerate(segments):
            c.drawString(cx_pos, y_line, seg)
            cx_pos += c.stringWidth(seg, fonts["Sans"], 9.8)
            if seg_idx < len(segments) - 1:
                c.rect(cx_pos + 3, y_line - 2, 22, 13, fill=0, stroke=1)
                cx_pos += 28

    draw_line_with_boxes(fig1_y - 203, ["a) 483 = 4 H + ", " Z + ", " E"])
    draw_line_with_boxes(fig1_y - 221, ["b) 709 = ", " H + 0 Z + ", " E"])
    draw_line_with_boxes(fig1_y - 239, ["c) ", " = 9 H + 5 Z + 2 E"])

    # Right-side Tip Callout Box alongside Task 2 (Tipp vom Eulen-Detektiv)
    c.setFillColor(colors.HexColor("#FEF3C7"))
    c.setStrokeColor(colors.HexColor("#F59E0B"))
    c.roundRect(298, fig1_y - 252, 245, 62, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.HexColor("#92400E"))
    c.drawString(308, fig1_y - 203, "Tipp vom Eulen-Detektiv:")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    c.drawString(308, fig1_y - 217, "Achte auf die Null als Platzhalter!")
    c.drawString(308, fig1_y - 230, "Bei 709 steht an der Zehnerstelle")
    c.drawString(308, fig1_y - 243, "eine 0: 7 H + 0 Z + 9 E.")

    # Stellenwerttafel & Nachbarhunderter
    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(48, 272, "Stellenwerttafel und Nachbarhunderter bestimmen:")
    c.setFont(fonts["Sans"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, 255, "Bestimme zu jeder Zahl den Vorgänger, den Nachfolger sowie die beiden Nachbarhunderter:")

    st_rows = [
        ["Zahl", "Hunderter (H)", "Zehner (Z)", "Einer (E)", "Vorgänger", "Nachfolger"],
        ["358", "3", "5", "8", "357", "359"],
        ["640", "6", "____", "0", "____", "641"],
        ["809", "____", "0", "9", "808", "____"],
    ]
    st_cols = [48, 118, 210, 298, 382, 464, 547]
    st_top = 244
    st_rh = 20
    for r_i, r_vals in enumerate(st_rows):
        ry = st_top - (r_i + 1) * st_rh
        if r_i == 0:
            c.setFillColor(colors.HexColor("#DBEAFE"))
            c.rect(st_cols[0], ry, st_cols[-1] - st_cols[0], st_rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.8)
        for c_i, cell_txt in enumerate(r_vals):
            c.rect(st_cols[c_i], ry, st_cols[c_i + 1] - st_cols[c_i], st_rh, fill=0, stroke=1)
            c.drawString(st_cols[c_i] + 6, ry + 5, cell_txt)

    # Merksatz box at bottom of Page 14
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#3B82F6"))
    c.roundRect(48, 58, PAGE_W - 96, 86, 8, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.setFont(fonts["SansBold"], 10.2)
    c.drawString(60, 126, "Merksatz: Tausenderbündelung")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(60, 108, "Zehn Einer bilden einen Zehner (10 E = 1 Z). Zehn Zehner bilden einen Hunderter (10 Z = 1 H).")
    c.drawString(60, 92, "Zehn Hunderter ergeben zusammen genau einen Tausender (10 H = 1 T = 1000).")
    c.drawString(60, 74, "In der Stellenwerttafel steht jede Ziffer genau für ihren Stellenwert (T – H – Z – E).")
    c.showPage()

    # ==================== PAGE 15 ====================
    draw_book_header_footer(c, 15, "Kapitel 1: Orientierung im Zahlenraum bis 1000", "Mathematik · Klasse 3", fonts, "#2563EB")
    c.setFont(fonts["SansBold"], 13)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(48, PAGE_H - 72, "Rechenmauern und Zahlenhäuser knacken")

    # Figure 1.2: Rechenmauer & Rechendreieck
    fig2_x, fig2_y, fig2_w, fig2_h = 48.0, PAGE_H - 285.0, 495.0, 198.0
    c.drawImage(figs["fig_gs_2"], fig2_x, fig2_y, width=fig2_w, height=fig2_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, fig2_y - 14, "Abb. 1.2: Rechenmauer und Rechendreieck mit Lücken")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_gs_2", 1, 15, "figures/gs_rechenmauer_dreieck.png",
            "Abb. 1.2: Rechenmauer und Rechendreieck mit Lücken", "Rechenmauer und Rechendreieck",
            fig2_x, fig2_y, fig2_w, fig2_h, 900, 360
        )
    )

    c.setFont(fonts["SansBold"], 10.4)
    t3_prefix = "Aufgabe 3 ◩: Fehlende Steine und Außenfelder berechnen"
    c.drawString(48, fig2_y - 38, t3_prefix)
    px3 = 48 + c.stringWidth(t3_prefix, fonts["SansBold"], 10.4)
    draw_scissors_glue_pictogram(c, px3 + 10, fig2_y - 38)
    c.setFont(fonts["Sans"], 9.8)
    c.drawString(48, fig2_y - 55, "In der Rechenmauer gilt: Zwei Nachbarsteine unten ergeben zusammen den Stein darüber.")
    c.drawString(48, fig2_y - 71, "Im Rechendreieck werden jeweils zwei Innenzahlen miteinander multipliziert.")
    c.drawString(48, fig2_y - 89, "a) Rechenmauer rechts unten: 850 - 365 = ____ (mittlerer Stein rechts), also 240 + ____ = 485.")
    c.drawString(48, fig2_y - 106, "b) Rechendreieck rechts: 8 * 5 = ____ und unten: 6 * 5 = ____.")

    c.setFont(fonts["SansBold"], 10.8)
    c.drawString(48, fig2_y - 134, "Aufgabe 4 ■: Sachaufgabe – Ausflug ins Naturkundemuseum")
    c.setFont(fonts["Sans"], 9.8)
    c.drawString(48, fig2_y - 152, "Die vier dritten Klassen der Lindenschule besuchen das Naturkundemuseum. Insgesamt fahren")
    c.drawString(48, fig2_y - 168, "96 Kinder und 8 Lehrkräfte mit. Der Eintritt kostet für jedes Kind 4 Euro und für Erwachsene 7 Euro.")
    c.drawString(48, fig2_y - 186, "Rechnung Kinder: ____ Euro    |    Rechnung Erwachsene: ____ Euro")
    c.drawString(48, fig2_y - 203, "Gesamtkosten: ____ Euro       |    Antwort: Die Schule bezahlt insgesamt ____ Euro.")

    # Number sequences & patterns block
    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, 322, "Zahlenfolgen und Regeldetektive:")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 304, "Erkenne die Rechenregel und setze die Zahlenfolgen um jeweils zwei Schritte fort:")
    c.setFont(fonts["Mono"], 9.8)
    c.drawString(56, 285, "a) 120,  230,  340,  450,  ____,  ____    (Regel: immer + 110)")
    c.drawString(56, 267, "b) 950,  825,  700,  575,  ____,  ____    (Regel: immer - 125)")
    c.drawString(56, 249, "c) 105,  215,  335,  465,  ____,  ____    (Regel: + 110, + 120, + 130, ...)")

    # Bottom Lösungsstrategie Box on Page 15
    c.setFillColor(colors.HexColor("#FFFBEB"))
    c.setStrokeColor(colors.HexColor("#F59E0B"))
    c.roundRect(48, 58, PAGE_W - 96, 162, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#92400E"))
    c.drawString(60, 200, "Merksatz: Sachaufgaben in 3 Schritten lösen (Frage – Rechnung – Antwort)")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(60, 180, "• 1. Schritt (Frage & Angaben): Lies den Text genau und unterstreiche alle wichtigen Zahlen.")
    c.drawString(60, 162, "• 2. Schritt (Rechnung): Zerlege schwierige Aufgaben in Teilrechnungen (z. B. Kinder und")
    c.drawString(68, 146, "Erwachsene getrennt berechnen) und addiere anschließend die Teilergebnisse.")
    c.drawString(60, 128, "• 3. Schritt (Antwort & Überschlag): Prüfe dein Ergebnis mit einem Überschlag (100 · 4 Euro =")
    c.drawString(68, 112, "400 Euro) und schreibe einen vollständigen Antwortsatz mit der passenden Einheit.")
    c.drawString(60, 90, "• Zusatzfrage für Schnelle: Für die Busfahrt bezahlt die Schule pauschal 260 Euro.")
    c.drawString(68, 74, "Wie viel kostet der Ausflug insgesamt mit Busfahrt? Rechnung: 440 Euro + 260 Euro = ____ Euro.")
    c.showPage()

    # ==================== PAGE 16 ====================
    draw_book_header_footer(c, 16, "Kapitel 2: Größen im Alltag – Uhrzeiten und Zeitspannen", "Mathematik · Klasse 3", fonts, "#2563EB")
    c.setFont(fonts["SansBold"], 13)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(48, PAGE_H - 72, "Kapitel 2: Uhrzeiten ablesen, Zeitspannen und Fahrpläne berechnen")

    # Figure 1.3: Analoge Uhren
    fig3_x, fig3_y, fig3_w, fig3_h = 48.0, PAGE_H - 252.0, 495.0, 165.0
    c.drawImage(figs["fig_gs_3"], fig3_x, fig3_y, width=fig3_w, height=fig3_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, fig3_y - 14, "Abb. 1.3: Drei analoge Uhren im Tagesverlauf")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_gs_3", 2, 16, "figures/gs_analoge_uhren.png",
            "Abb. 1.3: Drei analoge Uhren im Tagesverlauf", "Uhren-Darstellung",
            fig3_x, fig3_y, fig3_w, fig3_h, 900, 300
        )
    )

    c.setFont(fonts["SansBold"], 10.8)
    c.drawString(48, fig3_y - 38, "Aufgabe 5 □: Uhrzeiten und Zeitspannen bestimmen")
    c.setFont(fonts["Sans"], 9.8)
    c.drawString(48, fig3_y - 55, "Trage die passenden digitalen Uhrzeiten ein und berechne die Dauer:")
    c.drawString(48, fig3_y - 72, "a) Uhr A zeigt ____ Uhr. Bis zum Unterrichtsbeginn um 08:30 Uhr vergehen noch ____ Minuten.")
    c.drawString(48, fig3_y - 89, "b) Uhr B zeigt ____ Uhr. Uhr C zeigt am Nachmittag ____ Uhr.")

    # Task 6: Bus timetable table
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(48, fig3_y - 116, "Aufgabe 6 ◩: Fahrplan-Rätsel – Mit dem Schulbus zum Hallenbad")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, fig3_y - 133, "Berechne die fehlende Ankunftszeit in der Fahrplantabelle:")

    bus_rows = [
        ["Haltestelle", "Buslinie 12 (Früh)", "Buslinie 12 (Spät)", "Fahrtdauer ab Schule"],
        ["Lindenschule (Abfahrt)", "08:15 Uhr", "09:45 Uhr", "0 Minuten"],
        ["Rathausplatz", "08:27 Uhr", "09:57 Uhr", "12 Minuten"],
        ["Hallenbad (Ankunft)", "08:40 Uhr", "____ Uhr", "25 Minuten"],
    ]
    b_cols = [48, 194, 308, 422, 547]
    b_top = fig3_y - 144
    b_rh = 22
    for r_i, r_vals in enumerate(bus_rows):
        ry = b_top - (r_i + 1) * b_rh
        if r_i == 0:
            c.setFillColor(colors.HexColor("#DBEAFE"))
            c.rect(b_cols[0], ry, b_cols[-1] - b_cols[0], b_rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.8)
        for c_i, cell_txt in enumerate(r_vals):
            c.rect(b_cols[c_i], ry, b_cols[c_i + 1] - b_cols[c_i], b_rh, fill=0, stroke=1)
            c.drawString(b_cols[c_i] + 6, ry + 6, cell_txt)

    # Task 7: Time calculation word problems
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(48, 326, "Aufgabe 7 ■: Sachaufgaben zu Zeitspannen im Schulalltag")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 308, "a) Das Schwimmtraining beginnt um 08:50 Uhr und dauert 1 Stunde und 15 Minuten. Ende: ____ Uhr.")
    c.drawString(48, 291, "b) Die Projektwoche dauert 5 Schultage zu je 4 Stunden. Das sind insgesamt ____ Stunden.")
    c.drawString(48, 274, "c) Rechne in Minuten um: 1 h 35 min = ____ min   |   2 h 20 min = ____ min   |   150 min = ____ h ____ min.")

    # Bottom Merksatz Box on Page 16
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#2563EB"))
    c.roundRect(48, 58, PAGE_W - 96, 194, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 232, "Merksatz: Zeitpunkt und Zeitspanne umrechnen")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(60, 212, "• Zeitpunkt (Uhrzeit): Gibt genau an, wie spät es auf der Uhr ist (z. B. 08:15 Uhr oder 15:55 Uhr).")
    c.drawString(60, 192, "• Zeitspanne (Dauer): Gibt an, wie lange ein Vorgang dauert (z. B. 25 Minuten oder 2 Stunden).")
    c.drawString(60, 172, "• Umrechnungszahlen für die Zeit:")
    c.drawString(68, 154, "1 Tag (d) = 24 Stunden (h)   |   1 Stunde (h) = 60 Minuten (min)   |   1 Minute (min) = 60 Sekunden (s).")
    c.drawString(60, 134, "• Rechentipp (Ergänzen bis zur vollen Stunde): Berechne zuerst die Minuten bis zur nächsten")
    c.drawString(68, 118, "vollen Stunde (von 07:45 Uhr bis 08:00 Uhr sind es 15 min) und zähle dann die weiteren Minuten")
    c.drawString(68, 102, "dazu (von 08:00 Uhr bis 08:30 Uhr sind es 30 min; zusammen also 15 min + 30 min = 45 min).")
    c.drawString(60, 80, "• Achtung: Eine Viertelstunde hat 15 Minuten, eine halbe Stunde 30 Minuten, eine Dreiviertelstunde 45 Minuten.")
    c.showPage()
    c.save()
    return meta_entries


def build_grundschule_sachkunde_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Grundschule Klasse 3 Sachunterricht PDF (pages 24–25) with NO difficulty indicators."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Natur-Entdecker 3: Sachunterricht für die Grundschule")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 24 ====================
    draw_book_header_footer(c, 24, "Kapitel 2: Lebensraum Streuobstwiese im Jahreslauf", "Sachunterricht · Klasse 3", fonts, "#059669")
    draw_decorative_owl_mascot(c, PAGE_W - 72, PAGE_H - 76)

    c.setFont(fonts["SansBold"], 17.0)
    c.setFillColor(colors.HexColor("#065F46"))
    c.drawString(48, PAGE_H - 74, "Sachunterricht – Klasse 3")
    c.setFont(fonts["SansBold"], 12.8)
    c.setFillColor(colors.HexColor("#047857"))
    c.drawString(48, PAGE_H - 96, "Kapitel 2: Lebensraum Streuobstwiese und das Bienenjahr")

    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 118, "Auf einer Streuobstwiese wachsen hochstämmige Apfel-, Birnen- und Kirschbäume unterschiedlichen")
    c.drawString(48, PAGE_H - 134, "Alters. Zwischen den Bäumen blühen im Frühling Löwenzahn, Wiesensalbei und Margeriten. Hier finden")
    c.drawString(48, PAGE_H - 150, "Honigbienen, Wildbienen, Schmetterlinge, Singvögel und Igel das ganze Jahr über Nahrung und Schutz.")

    # Task 1: Lückentext with Word Bank Box (NO difficulty symbol!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#064E3B"))
    c.drawString(48, PAGE_H - 178, "Aufgabe 1: Lückentext – Das Bienenjahr auf der Streuobstwiese")
    c.setFillColor(colors.HexColor("#ECFDF5"))
    c.setStrokeColor(colors.HexColor("#10B981"))
    c.roundRect(48, PAGE_H - 214, PAGE_W - 96, 28, 6, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#065F46"))
    c.drawString(60, PAGE_H - 204, "Wortspeicher:   Blüten  ·  Nektar  ·  Bestäubung  ·  Früchte  ·  Winterruhe")

    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 232, "Setze die passenden Wörter aus dem Wortspeicher in die Lücken ein:")
    c.drawString(48, PAGE_H - 250, "Im Frühling öffnen die Apfelbäume ihre duftenden ____. Die Honigbienen sammeln dort")
    c.drawString(48, PAGE_H - 267, "süßen ____ und tragen Blütenstaub von Baum zu Baum. Durch diese wichtige ____")
    c.drawString(48, PAGE_H - 284, "wachsen im Sommer saftige ____. Im kalten Dezember hält das Bienenvolk ____.")

    # Sachunterricht Info Box
    c.setFillColor(colors.HexColor("#F0FDF4"))
    c.setStrokeColor(colors.HexColor("#16A34A"))
    c.roundRect(48, 366, PAGE_W - 96, 166, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#166534"))
    c.drawString(60, 512, "Sachwissen kompakt: Das Honigbienen-Volk im Jahreslauf")
    c.setFont(fonts["Sans"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(60, 492, "• Königin, Arbeiterinnen und Drohnen: In einem einzigen Bienenstock leben im Sommer bis zu")
    c.drawString(68, 476, "50.000 weibliche Arbeitsbienen, einige hundert männliche Drohnen und eine einzige Bienenkönigin.")
    c.drawString(60, 456, "• Bestäubungsleistung: Für ein einziges Glas Honig (500 g) müssen die Sammlerinnen rund")
    c.drawString(68, 440, "40.000-mal ausfliegen und dabei Millionen einzelner Obst- und Wiesenblüten besuchen.")
    c.drawString(60, 420, "• Verständigung durch den Schwänzeltanz: Kehrt eine Kundschafterin zur Wabe zurück, zeigt sie")
    c.drawString(68, 404, "den anderen Bienen durch Richtung und Tempo ihres Tanzes genau den Weg zur Futterquelle.")
    c.drawString(60, 384, "• Überwinterung: Im Winter bildet das Volk eine enge Wintertraube und hält die Temperatur")
    c.drawString(68, 370, "im Inneren durch Muskelzittern konstant bei etwa 25 °C bis 30 °C.")

    # Task 2: Observation table (NO difficulty symbol!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#064E3B"))
    c.drawString(48, 340, "Aufgabe 2: Wetter- und Naturprotokoll ergänzen")
    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, 323, "Vervollständige die Beobachtungstabelle unserer Schulwiese im Jahresverlauf:")

    ty_top = 310
    row_h = 22
    col_xs = [48, 106, 228, 344, 547]
    rows_data = [
        ["Monat", "Mittlere Temperatur", "Sonnenstunden/Tag", "Beobachtung auf der Wiese"],
        ["April", "10 °C", "6 Stunden", "Apfelblüte beginnt, Hummeln fliegen"],
        ["Juli", "21 °C", "____ Stunden", "Reife Kirschen, viele Kohlmeisen"],
        ["Oktober", "____ °C", "4 Stunden", "Apfelernte und bunter Laubfall"],
    ]
    for r_i, r_vals in enumerate(rows_data):
        ry = ty_top - (r_i + 1) * row_h
        if r_i == 0:
            c.setFillColor(colors.HexColor("#D1FAE5"))
            c.rect(col_xs[0], ry, col_xs[-1] - col_xs[0], row_h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.8)
        for c_i, cell_txt in enumerate(r_vals):
            c.rect(col_xs[c_i], ry, col_xs[c_i + 1] - col_xs[c_i], row_h, fill=0, stroke=1)
            c.drawString(col_xs[c_i] + 5, ry + 6, cell_txt)

    # Bottom Tip Box on Page 24
    c.setFillColor(colors.HexColor("#ECFDF5"))
    c.setStrokeColor(colors.HexColor("#059669"))
    c.roundRect(48, 58, PAGE_W - 96, 146, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#065F46"))
    c.drawString(60, 184, "Forscher-Tipp: Wildbienen und Nistplätze auf dem Schulhof schützen")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 164, "• Neben der Honigbiene leben in Deutschland über 560 verschiedene Wildbienenarten (z. B. die")
    c.drawString(68, 148, "Rote Mauerbiene und die Erdhummel). Die meisten Wildbienen bilden keinen Staat, sondern")
    c.drawString(68, 132, "legen ihre Brutzellen einzeln in hohlen Pflanzenstängeln, im Totholz oder im sandigen Boden an.")
    c.drawString(60, 112, "• Wenn eine Wiese erst spät im Juni gemäht wird, können Wiesenblumen aussamen und bieten")
    c.drawString(68, 96, "Insekten, Raupen und Wiesenvögeln bis in den Herbst hinein reichlich Nahrung.")
    c.drawString(60, 76, "• Beobachte am Insektenhotel immer ruhig aus 1 Meter Abstand und verschließe niemals die Röhren.")
    c.showPage()

    # ==================== PAGE 25 ====================
    draw_book_header_footer(c, 25, "Kapitel 2: Lebensraum Streuobstwiese im Jahreslauf", "Sachunterricht · Klasse 3", fonts, "#059669")
    c.setFont(fonts["SansBold"], 13)
    c.setFillColor(colors.HexColor("#047857"))
    c.drawString(48, PAGE_H - 72, "Nahrungsbeziehungen und Naturbeobachtung auf der Wiese")

    # Figure 2.1: Nahrungskette
    fig4_x, fig4_y, fig4_w, fig4_h = 48.0, PAGE_H - 238.0, 495.0, 148.5
    c.drawImage(figs["fig_gs_4"], fig4_x, fig4_y, width=fig4_w, height=fig4_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, fig4_y - 14, "Abb. 2.1: Nahrungskette auf der Streuobstwiese")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_gs_4", 1, 25, "figures/gs_nahrungskette_wiese.png",
            "Abb. 2.1: Nahrungskette auf der Streuobstwiese", "Strukturdiagramm",
            fig4_x, fig4_y, fig4_w, fig4_h, 900, 270
        )
    )

    # Task 3: Checkboxes ☐ -> [ ] (NO difficulty symbol!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#064E3B"))
    c.drawString(48, fig4_y - 38, "Aufgabe 3: Aussagen zur Nahrungskette prüfen")
    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, fig4_y - 55, "Kreuze alle richtigen Aussagen zur Streuobstwiese an:")
    checkbox_lines = [
        "☐ Das grüne Apfelblatt bildet als Pflanze den Anfang der Nahrungskette (Erzeuger).",
        "☐ Die Raupe frisst ausschließlich Kohlmeisen und Greifvögel.",
        "☐ Die Kohlmeise füttert ihre Jungen im Frühling mit vielen Raupen.",
        "☐ Der Turmfalke steht als Beutegreifer am Ende dieser Nahrungskette.",
    ]
    for idx, cb_line in enumerate(checkbox_lines):
        c.drawString(56, fig4_y - 74 - idx * 18, cb_line)

    # Task 4: Partner work task (vector partner pictogram ONLY, NO bracketed text in PDF)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#064E3B"))
    t4_prefix = "Aufgabe 4: Forscherauftrag – Eigene Nahrungskette legen"
    c.drawString(48, 412, t4_prefix)
    px4 = 48 + c.stringWidth(t4_prefix, fonts["SansBold"], 10.8)
    draw_partner_pictogram(c, px4 + 10, 412)
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 392, "1. Bringt die vier Lebewesen in die richtige Reihenfolge (1 bis 4): Igel – Regenwurm – Falllaub – Fuchs.")
    c.drawString(48, 374, "2. Überlegt gemeinsam: Was passiert auf der Streuobstwiese, wenn im Frühling alle Insekten fehlen?")
    c.drawString(48, 356, "3. Zeichnet in euer Forscherheft eine eigene Nahrungskette mit vier Pfeilen („wird gefressen von“).")

    # Additional Task 5 on Stockwerke der Streuobstwiese
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#064E3B"))
    c.drawString(48, 326, "Aufgabe 5: Die Stockwerke der Streuobstwiese zuordnen")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 308, "Ordne jedem Lebensbereich der Wiese zwei passende Tiere zu (Maulwurf, Grünspecht, Schmetterling,")
    c.drawString(48, 292, "Regenwurm, Siebenschläfer, Wildbiene):")
    c.drawString(56, 274, "a) Baumkrone und Baumhöhlen: ____    b) Blüten- und Krautschicht: ____    c) Wiesenboden: ____")

    # Bottom Merksatz Box on Page 25
    c.setFillColor(colors.HexColor("#ECFDF5"))
    c.setStrokeColor(colors.HexColor("#059669"))
    c.roundRect(48, 58, PAGE_W - 96, 196, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#065F46"))
    c.drawString(60, 234, "Merksatz: Erzeuger, Verbraucher und das Gleichgewicht in der Natur")
    c.setFont(fonts["Sans"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(60, 212, "• Erzeuger (Pflanzen): Grüne Pflanzen wie der Apfelbaum oder das Wiesengras stellen mithilfe")
    c.drawString(68, 196, "von Sonnenlicht, Wasser und Luft ihre Nahrung selbst her. Sie stehen am Beginn jeder Kette.")
    c.drawString(60, 176, "• Verbraucher (Pflanzenfresser und Fleischfresser): Tiere wie Raupen, Käfer, Singvögel und")
    c.drawString(68, 160, "Greifvögel sind auf Pflanzen oder andere Tiere als Nahrungsquelle angewiesen.")
    c.drawString(60, 140, "• Zersetzer (Destruenten): Regenwürmer, Asseln und Bodenpilze verwandeln welkes Herbstlaub")
    c.drawString(68, 124, "wieder in wertvollen Humusboden. So schließt sich der natürliche Stoffkreislauf der Wiese.")
    c.drawString(60, 102, "• Naturschutz-Regel: Auf einer ungespritzten Streuobstwiese finden über 2.000 Tier- und")
    c.drawString(68, 86, "Pflanzenarten einen geschützten Lebensraum.")
    c.showPage()
    c.save()
    return meta_entries


def build_sek1_deutsch_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe I Klasse 7 Deutsch PDF (pages 112–113) with NO difficulty indicators."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Sprachfenster 7: Deutsch für die Sekundarstufe I")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 112 ====================
    draw_book_header_footer(c, 112, "Kapitel 5: Erzähltexte und Medienberichte", "Deutsch · Klasse 7", fonts, "#9333EA")
    c.setFont(fonts["SerifBold"], 15)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(48, PAGE_H - 74, "Kapitel 5: Mensch und Natur in Erzählung und Reportage")
    c.setFont(fonts["SansBold"], 12)
    c.setFillColor(colors.HexColor("#6B21A8"))
    c.drawString(48, PAGE_H - 96, "5.1 Lesetext: Sturm über der Hallig (mit Zeilenzählung)")

    # Main reading column (left, x=68..372) with margin line numbers every 5 lines
    reading_lines = [
        "Seit dem frühen Nachmittag drückte ein bleigrauer Himmel",
        "auf das flache Wattenmeer. Jan stand am Deichfenster",
        "der kleinen Warft und beobachtete, wie die ersten",
        "Schaumkronen über die Salzwiesen rollten. Seine Schwester",
        "Nele prüfte die schweren Holzläden im Erdgeschoss.",  # 5
        "„Wenn der Westwind bis zum Abend auf Sturmstärke",
        "dreht, steigt das Wasser heute bis an die oberste",
        "Steinkante“, sagte Großvater Tamme ruhig, während er",
        "die Taschenlampen auf den Küchentisch stellte.",
        "Draußen pfiff die Böe bereits durch die alten Eschen.",  # 10
        "Plötzlich blinkte weit draußen am Horizont das helle",
        "Leuchtfeuer der Nachbarinsel dreimal kurz auf.",
        "Jan griff nach dem Fernglas seines Großvaters und",
        "suchte die aufgewühlte Fahrrinne ab. Zwischen den",
        "Brechern erkannte er das rote Rettungsboot der Küsten-",  # 15 (cross-line hyphenation)
        "wache, das langsam gegen die Strömung ankämpfte.",
        "Im Funkgerät knisterte eine leise Stimme: Alle",
        "Bewohner der Hallig sollten die unteren Räume sichern",
        "und die Notfunkfrequenz eingeschaltet lassen.",
        "Gegen Mitternacht erreichte der Wasserstand seinen",  # 20
        "Höchstwert; das Meer donnerte gegen die Befestigung,",
        "doch die jahrhundertealte Warft hielt dem Druck stand.",
        "Gebannt blickten die Kinder durch das Dachfenster",
        "hinüber zum sicheren Lichtkegel, den der erfahrene",
        "Leuchtturm-",  # 25 -> Cross-page word hyphenation onto Page 113 ("wärter.")
    ]
    c.setFont(fonts["Serif"], 10.0)
    y_start = PAGE_H - 124
    for idx, rline in enumerate(reading_lines, start=1):
        ly = y_start - (idx - 1) * 18.2
        if idx % 5 == 0:
            c.setFont(fonts["SansBold"], 8.5)
            c.setFillColor(colors.HexColor("#7E22CE"))
            c.drawRightString(58, ly, str(idx))
            c.setFont(fonts["Serif"], 10.0)
        c.setFillColor(colors.black)
        c.drawString(68, ly, rline)

    # Margin vocabulary / annotation box (Randspalte top right)
    c.setFillColor(colors.HexColor("#FAF5FF"))
    c.setStrokeColor(colors.HexColor("#A855F7"))
    c.roundRect(380, PAGE_H - 356, 167, 232, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 8.4)
    c.setFillColor(colors.HexColor("#6B21A8"))
    c.drawString(388, PAGE_H - 142, "Worterklärungen (Randspalte)")
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.black)
    margin_notes = [
        "• Hallig: kleine, nicht",
        "  eingedeichte Marschinsel",
        "  im nordfriesischen",
        "  Wattenmeer.",
        "• Warft: künstlich aufge-",
        "  schütteter Wohnhügel zum",
        "  Schutz bei Landunter.",
        "• Brecher: hohe, sich",
        "  überschlagende Meeres-",
        "  welle bei Sturmflut.",
    ]
    for m_i, m_txt in enumerate(margin_notes):
        c.drawString(388, PAGE_H - 162 - m_i * 15.5, m_txt)

    # Second Margin Box (Randspalte middle right)
    c.setFillColor(colors.HexColor("#F5F3FF"))
    c.setStrokeColor(colors.HexColor("#8B5CF6"))
    c.roundRect(380, PAGE_H - 568, 167, 198, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.0)
    c.setFillColor(colors.HexColor("#5B21B6"))
    c.drawString(388, PAGE_H - 388, "Hintergrund: Sturmflut")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    bg_notes = [
        "• Bei schweren Weststürmen",
        "  drückt der Wind das Nord-",
        "  seewasser in die Deutsche",
        "  Bucht („Blanker Hans“).",
        "• Auf den zehn nordfriesischen",
        "  Halligen tritt mehrmals im",
        "  Winterhalbjahr „Landunter“",
        "  ein: Nur die Warften ragen",
        "  dann noch aus den Fluten.",
    ]
    for b_i, b_txt in enumerate(bg_notes):
        c.drawString(388, PAGE_H - 408 - b_i * 15.5, b_txt)

    # Bottom Method Box across full width of Page 112
    c.setFillColor(colors.HexColor("#F3E8FF"))
    c.setStrokeColor(colors.HexColor("#9333EA"))
    c.roundRect(48, 58, PAGE_W - 96, 192, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(60, 230, "Methode: Einen literarischen Erzähltext auf Spannungsmerkmale untersuchen")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 210, "• 1. Atmosphäre und Schauplatz (Exposition): Achte auf sinnliche Adjektive und Verben, mit denen")
    c.drawString(68, 194, "Wetter, Lichtverhältnisse und Geräusche beschrieben werden (z. B. „bleigrauer Himmel“, „pfiff“).")
    c.drawString(60, 176, "• 2. Figurenrede und innere Handlung: Untersuche, wie die Figuren auf die Gefahr reagieren")
    c.drawString(68, 160, "(z. B. Großvater Tammes ruhige Anweisungen im Kontrast zur wachsenden Unruhe der Kinder).")
    c.drawString(60, 142, "• 3. Steigerung bis zum Höhepunkt (Klimax): Markiere Textstellen, an denen sich die Bedrohung")
    c.drawString(68, 126, "verdichtet (Leuchtfeuer am Horizont, knisternder Notfunk, Höchststand um Mitternacht).")
    c.drawString(60, 108, "• 4. Satzbau und Erzähltempo: Kurze Hauptsätze beschleunigen das Erzähltempo in Gefahrenszenen,")
    c.drawString(68, 92, "während präzise Detailbeschreibungen den Blick der Lesenden wie durch ein Fernglas lenken.")
    c.drawString(60, 72, "• Tipp für Textbelege: Gib bei jedem Zitat stets die genaue Zeile in Klammern an, z. B. (Z. 14–16).")
    c.showPage()

    # ==================== PAGE 113 ====================
    draw_book_header_footer(c, 113, "Kapitel 5: Erzähltexte und Medienberichte", "Deutsch · Klasse 7", fonts, "#9333EA")
    c.setFont(fonts["Serif"], 10.2)
    c.setFillColor(colors.black)
    c.drawString(68, PAGE_H - 72, "wärter. Am nächsten Morgen glitzerte der nasse Schlick in der")
    c.drawString(68, PAGE_H - 90, "Wintersonne, und die Seevögel kehrten kreischend auf die Wiesen zurück.")

    # Task 1: Reading comprehension (NO difficulty symbol!)
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(48, PAGE_H - 122, "Aufgabe 1: Textverständnis und Spannungsaufbau untersuchen")
    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 140, "1. Beschreibe, mit welchen sprachlichen Mitteln in Zeile 1–10 die drohende Sturmflut angekündigt wird.")
    c.drawString(48, PAGE_H - 157, "2. Erkläre die Bedeutung der Begriffe „Hallig“ und „Warft“ mithilfe der Randspalte.")

    # Task 2: Differentiated typography rendered with real Bold, Italic, and Underline
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(48, PAGE_H - 186, "Aufgabe 2: Hervorhebungen bestimmen (fett, kursiv, unterstrichen)")
    c.setFont(fonts["Sans"], 9.8)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 204, "Bestimme in den drei Beispielsätzen die Wortart der fett gedruckten Wörter, die Funktion der")
    c.drawString(48, PAGE_H - 220, "kursiv gesetzten Ausdrücke und das Satzglied der unterstrichenen Wortgruppen:")
    draw_styled_emphasis_sentence(
        c, 56, PAGE_H - 240,
        "a) Der ", "erfahrene", " Kapitän steuert das Rettungsboot ",
        "trotz der Dunkelheit", "durch die enge Fahrrinne", fonts, 9.4
    )
    draw_styled_emphasis_sentence(
        c, 56, PAGE_H - 258,
        "b) Viele ", "wachsame", " Inselbewohner sichern ",
        "vor dem nahenden Hochwasser", "alle Fenster und Türen", fonts, 9.4
    )
    draw_styled_emphasis_sentence(
        c, 56, PAGE_H - 276,
        "c) Am Morgen meldet der ", "örtliche", " Wetterdienst ",
        "glücklicherweise", "das Ende der schweren Sturmflut", fonts, 9.4
    )

    # Grammar box (<Rahmen>)
    c.setFillColor(colors.HexColor("#F3E8FF"))
    c.setStrokeColor(colors.HexColor("#7E22CE"))
    c.roundRect(48, PAGE_H - 404, PAGE_W - 96, 108, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(60, PAGE_H - 314, "Sprachwissen: Indirekte Rede mit Konjunktiv I und II")
    c.setFont(fonts["Sans"], 9.4)
    c.setFillColor(colors.black)
    c.drawString(60, PAGE_H - 333, "• In Nachrichten und Berichten wird die indirekte Rede meist im Konjunktiv I gebildet:")
    c.drawString(68, PAGE_H - 349, "  Großvater Tamme erklärt, das Wasser steige heute bis an die oberste Steinkante.")
    c.drawString(60, PAGE_H - 368, "• Stimmt der Konjunktiv I mit dem Indikativ überein, weicht man auf den Konjunktiv II aus:")
    c.drawString(68, PAGE_H - 384, "  Die Helfer berichten, viele Boote kämen erst bei Ebbe wieder frei.")

    # Task 3 & Task 4 (NO difficulty symbols!)
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(48, 412, "Aufgabe 3: Direkte Rede in einen Zeitungsbericht umformen")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 394, "Forme die folgenden Aussagen für die Lokalzeitung „Nordfriesische Nachrichten“ in die indirekte Rede um:")
    c.drawString(56, 376, "a) Jan ruft: „Ich sehe das rote Rettungsboot der Küstenwache zwischen den hohen Brechern!“")
    c.drawString(56, 359, "b) Nele berichtet: „Wir haben alle Holzläden im Erdgeschoss rechtzeitig verriegelt.“")
    c.drawString(56, 342, "c) Der Einsatzleiter betont: „Die Bewohner der Hallig sind während der gesamten Nacht in Sicherheit.“")

    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#581C87"))
    c.drawString(48, 312, "Aufgabe 4: Schreibauftrag – Innerer Monolog oder Erlebnisbericht")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, 294, "Wähle eine der beiden Schreibaufgaben aus und verfasse einen zusammenhängenden Text (ca. 120 Wörter):")
    c.drawString(56, 276, "1. Innerer Monolog: Versetze dich in Jan (Z. 23–25), als er um Mitternacht zum Leuchtturm blickt.")
    c.drawString(56, 259, "2. Zeitungsreportage: Schreibe einen sachlichen Bericht über den Einsatz des Rettungsbootes.")

    # Bottom Checkliste Box on Page 113
    c.setFillColor(colors.HexColor("#FAF5FF"))
    c.setStrokeColor(colors.HexColor("#A855F7"))
    c.roundRect(48, 58, PAGE_W - 96, 176, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#6B21A8"))
    c.drawString(60, 214, "Checkliste zur Textüberarbeitung: Indirekte Rede & Schreibkonferenz")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 194, "• Redeeinleitung: Habe ich abwechslungsreiche Verben des Sagens verwendet (z. B. berichten,")
    c.drawString(68, 178, "erklären, betonen, warnen, schildern) statt immer nur „sagen“ zu wiederholen?")
    c.drawString(60, 160, "• Moduswechsel: Stehen alle Verben der wiedergegebenen Rede korrekt im Konjunktiv I (er sehe,")
    c.drawString(68, 144, "es steige, sie sei) bzw. bei Formen-Gleichheit im Konjunktiv II (sie hätten, sie kämen)?")
    c.drawString(60, 126, "• Pronomen & Perspektive: Wurden Personal- und Possessivpronomen sinnvoll angepasst")
    c.drawString(68, 110, "(aus „Ich sehe mein Boot“ wird „Jan ruft, er sehe sein Boot“)?")
    c.drawString(60, 92, "• Zeichensetzung: Fehlen die Anführungszeichen bei der indirekten Rede und steht vor dem")
    c.drawString(68, 76, "eingeleiteten Nebensatz ein Komma?")
    c.showPage()
    c.save()
    return meta_entries


def build_sek1_englisch_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe I Klasse 7/8 Englisch PDF (pages 64–65) with ★/★★/★★★ difficulty icons."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Bridge 7/8: English for Sekundarstufe I")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 64 ====================
    draw_book_header_footer(c, 64, "Unit 4: Protecting Our Coasts and Oceans", "Englisch · Klasse 7/8", fonts, "#0284C7")
    c.setFont(fonts["SansBold"], 15.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, PAGE_H - 72, "Unit 4: Teen Action – Protecting the Cornwall Coastline")

    # Figure 4.1: Cornwall Clean-up Magazine Collage with OpenStreetMap Inset
    fig_x, fig_y, fig_w, fig_h = 48.0, PAGE_H - 266.0, 495.0, 176.0
    c.drawImage(figs["fig_s1_lang_1"], fig_x, fig_y, width=fig_w, height=fig_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, fig_y - 14, "Abb. 4.1: Jugendmagazin-Collage – Clean-up Action at Cornwall Coast")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_s1_lang_1", 0, 64, "figures/sek1_cornwall_coastal_action.png",
            "Abb. 4.1: Jugendmagazin-Collage – Clean-up Action at Cornwall Coast", "Jugendmagazin-Collage",
            fig_x, fig_y, fig_w, fig_h, 900, 320
        )
    )

    # 3-Column Magazine Reading Spread + Dialogue Box with Speaker Labels
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, fig_y - 36, "4.1 Dialogue: Planning the Saturday Beach Clean-up")

    c.setStrokeColor(colors.HexColor("#BAE6FD"))
    c.line(208, fig_y - 46, 208, fig_y - 80)
    c.line(374, fig_y - 46, 374, fig_y - 80)
    c.setFont(fonts["SansOblique"], 8.2)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(48, fig_y - 54, "St Ives Teen Magazine:")
    c.drawString(48, fig_y - 66, "Every Saturday, local volun-")
    c.drawString(216, fig_y - 54, "teers meet at the harbour")
    c.drawString(216, fig_y - 66, "pier to collect marine")
    c.drawString(382, fig_y - 54, "plastic and protect coastal")
    c.drawString(382, fig_y - 66, "seabirds in Cornwall.")

    dialogue = [
        ("Maya:", "Look at the harbour poster, Liam! Volunteers collected 142 kilos of plastic last month."),
        ("Liam:", "That's impressive, Maya. If we join the group on Saturday, we will help protect the seabirds."),
        ("Mrs O'Connor:", "Good morning, you two! Have you signed up for the St Ives environmental project yet?"),
        ("Maya:", "Yes, Mrs O'Connor! If more students had reusable bottles, there would be far less waste."),
        ("Liam:", "Let's bring sturdy gloves and recycling bags to the Harbour Pier at ten o'clock."),
    ]
    dy = fig_y - 94
    for spk, utt in dialogue:
        c.setFont(fonts["SansBold"], 9.4)
        c.setFillColor(colors.HexColor("#0F172A"))
        c.drawString(54, dy, spk)
        c.setFont(fonts["Sans"], 9.4)
        c.drawString(132, dy, utt)
        dy -= 18

    # Comprehension & Speaking Tasks with ★ / ★★ icons ONLY (no bracketed text!)
    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, 374, "Aufgabe 1 ★: Reading & Map Comprehension – St Ives Eco-Report")
    c.setFont(fonts["Sans"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, 356, "1. Look at Abb. 4.1: Which two types of marine litter make up the largest share of waste in St Ives Bay?")
    c.drawString(48, 340, "2. Find St Ives Pier and Godrevy Lighthouse on the OpenStreetMap inset and explain why the bay traps plastic.")

    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    t2_en_prefix = "Aufgabe 2 ★★: Speaking – Organising a School Green Day"
    c.drawString(48, 314, t2_en_prefix)
    px_en = 48 + c.stringWidth(t2_en_prefix, fonts["SansBold"], 11.0)
    draw_partner_pictogram(c, px_en + 10, 314)
    c.setFont(fonts["Sans"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, 296, "Work with a partner. Discuss how your class could reduce plastic waste using the Useful Phrases box:")

    # Useful Phrases Box on Page 64
    c.setFillColor(colors.HexColor("#F0F9FF"))
    c.setStrokeColor(colors.HexColor("#38BDF8"))
    c.roundRect(48, 174, PAGE_W - 96, 108, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(60, 264, "Useful Phrases: Expressing Opinions and Making Suggestions")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 245, "• Giving your opinion: In my opinion, we should...  |  I strongly believe that...  |  From my point of view...")
    c.drawString(60, 227, "• Making suggestions: Why don't we organise a...?  |  If we banned single-use cups, we would save...")
    c.drawString(60, 209, "• Agreeing & reacting: That's a great point!  |  I completely agree with you.  |  Let's put up a poster.")
    c.drawString(60, 191, "• Polite disagreement: I see your point, but what if...?  |  Wouldn't it be better if we started with...?")

    # Grammar Box on Page 64
    c.setFillColor(colors.HexColor("#E0F2FE"))
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.roundRect(48, 58, PAGE_W - 96, 100, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(60, 140, "Grammar Box: Conditional Sentences Type I and Type II")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(60, 120, "• Type I (real/likely):  if + Simple Present  →  will-future   (If we join on Saturday, we will help.)")
    c.drawString(60, 102, "• Type II (unreal/hypothetical):  if + Simple Past  →  would + infinitive")
    c.drawString(68, 84, "(If more students had reusable bottles, there would be far less waste.)")
    c.drawString(60, 67, "• Watch out: Never use 'will' or 'would' inside the if-clause itself!")
    c.showPage()

    # ==================== PAGE 65 ====================
    draw_book_header_footer(c, 65, "Unit 4: Protecting Our Coasts and Oceans", "Englisch · Klasse 7/8", fonts, "#0284C7")
    c.setFont(fonts["SansBold"], 13.5)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, PAGE_H - 72, "4.2 Vocabulary Unit 4 – English / IPA Phonetics / Deutsch")

    # 3-Column Vocabulary Table with IPA Phonetics and Example Sentences
    vocab_rows = [
        ("English Word & Example", "", "IPA Phonetics", "Deutsche Bedeutung"),
        ("coastline (n.)", "We must protect our rocky coastline.", "[/ˈkəʊstlaɪn/]", "Küstenlinie, Meeresküste"),
        ("knowledge (n.)", "Local knowledge helps the rescue team.", "[/ˈnɒlɪdʒ/]", "Wissen, Kenntnis"),
        ("volunteer (n./v.)", "Sixteen volunteers cleaned the cove.", "[/ˌvɒlənˈtɪə(r)/]", "Freiwillige(r); freiwillig helfen"),
        ("environmental (adj.)", "She joined an environmental club.", "[/ɪnˌvaɪrənˈmentl/]", "Umwelt-, ökologisch"),
        ("sustainable (adj.)", "Sustainable tourism avoids waste.", "[/səˈsteɪnəbl/]", "nachhaltig, zukunftsfähig"),
        ("pollution (n.)", "Marine pollution threatens sea turtles.", "[/pəˈluːʃn/]", "Verschmutzung, Umweltbelastung"),
        ("harbour pier (n.)", "Meet us at the old harbour pier.", "[/ˈhɑːbə pɪə(r)/]", "Hafenmole, Landungsbrücke"),
    ]
    v_top = PAGE_H - 90
    v_rh = 32
    v_cols = [48, 265, 375, 547]
    for r_i, (w_head, w_ex, ipa_txt, de_txt) in enumerate(vocab_rows):
        ry = v_top - (r_i + 1) * v_rh
        if r_i == 0:
            c.setFillColor(colors.HexColor("#BAE6FD"))
            c.rect(v_cols[0], ry, v_cols[-1] - v_cols[0], v_rh, fill=1, stroke=0)
            c.setFillColor(colors.black)
            c.setFont(fonts["SansBold"], 9.0)
            for c_i, h_val in enumerate((w_head, ipa_txt, de_txt)):
                c.rect(v_cols[c_i], ry, v_cols[c_i + 1] - v_cols[c_i], v_rh, fill=0, stroke=1)
                c.drawString(v_cols[c_i] + 6, ry + 11, h_val)
        else:
            c.setFillColor(colors.black)
            for c_i in range(3):
                c.rect(v_cols[c_i], ry, v_cols[c_i + 1] - v_cols[c_i], v_rh, fill=0, stroke=1)
            c.setFont(fonts["SansBold"], 8.8)
            c.drawString(v_cols[0] + 6, ry + 18, w_head)
            c.setFont(fonts["Sans"], 8.2)
            c.drawString(v_cols[0] + 6, ry + 5, w_ex)
            c.setFont(fonts["Sans"], 8.8)
            c.drawString(v_cols[1] + 6, ry + 11, ipa_txt)
            c.drawString(v_cols[2] + 6, ry + 11, de_txt)

    # Task 3 & Task 4 on Page 65 with ★★ and ★★★ icons ONLY
    y_after_vocab = v_top - len(vocab_rows) * v_rh
    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, y_after_vocab - 24, "Aufgabe 3 ★★: Mediation & Conditional Practice")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    y_t3 = y_after_vocab - 42
    c.drawString(48, y_t3, "Complete the conditional sentences with the correct verb forms:")
    c.drawString(56, y_t3 - 18, "a) If the tide ____ (rise) quickly, the coastguard will warn all boats in the harbour.")
    c.drawString(56, y_t3 - 35, "b) If people ____ (not drop) plastic on the beach, seabirds would be much safer.")
    c.drawString(56, y_t3 - 52, "c) What ____ you ____ (do) if you found an entangled seal on the coastline?")

    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, y_t3 - 82, "Aufgabe 4 ★★★: Mediation – E-Mail an eine Partnerschule in Cornwall")
    c.setFont(fonts["Sans"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, y_t3 - 100, "Deine Klasse plant eine Umwelt-Projektwoche und hat den Artikel aus dem St Ives Teen Magazine")
    c.drawString(48, y_t3 - 116, "aus Unit 4 gelesen. Dein Mitschüler Lukas versteht kein Englisch und bittet dich um eine Zusammenfassung.")
    c.drawString(56, y_t3 - 134, "1. Erkläre Lukas auf Deutsch die wichtigsten Ergebnisse der Strandreinigung in St Ives (Menge, Müllarten).")
    c.drawString(56, y_t3 - 150, "2. Write a short reply email (60–80 words) to Maya and Liam introducing your own school eco-project.")

    # Study Skills Box at bottom of Page 65
    c.setFillColor(colors.HexColor("#F0F9FF"))
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.roundRect(48, 58, PAGE_W - 96, 162, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(60, 200, "Study Skills: Working with an English-German Dictionary & IPA Phonetics")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 180, "• 1. Word class abbreviations: Always check whether a headword is a noun (n.), verb (v.), or")
    c.drawString(68, 164, "adjective (adj.). Many English words like 'volunteer' can be used both as a noun and a verb.")
    c.drawString(60, 146, "• 2. Word stress in IPA: The vertical mark [ˈ] in phonetic transcription always stands directly")
    c.drawString(68, 130, "before the main stressed syllable (e.g. [/səˈsteɪnəbl/] -> stress on '-stain-').")
    c.drawString(60, 112, "• 3. British vs. American English: Note British spelling '-our' in 'harbour' (AE: 'harbor') and")
    c.drawString(68, 96, "the optional final r-sound [ə(r)] in British Received Pronunciation.")
    c.drawString(60, 76, "• Tip for Mediation: Never translate sentence by sentence—summarise the key facts in your own words!")
    c.showPage()
    c.save()
    return meta_entries


def build_sek1_geographie_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe I Klasse 9/10 Geographie PDF (pages 204–205) with NO difficulty indicators."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Erdkunde 9/10: Naturraum und Klima in Mitteleuropa")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 204 ====================
    draw_book_header_footer(c, 204, "Kapitel 2: Naturraum und Klima in Mitteleuropa", "Geographie · Klasse 9/10", fonts, "#15803D")
    c.setFont(fonts["SansBold"], 14.2)
    c.setFillColor(colors.HexColor("#14532D"))
    c.drawString(48, PAGE_H - 72, "Kapitel 2: Der Oberrheingraben – Naturraum, Relief und Klima")
    c.setFont(fonts["SansBold"], 11.8)
    c.setFillColor(colors.HexColor("#166534"))
    c.drawString(48, PAGE_H - 92, "2.1 Topographie und Grabenbruch im Südwesten")

    c.setFont(fonts["Serif"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 110, "Zwischen den Mittelgebirgen Vogesen im Westen und Schwarzwald im Osten erstreckt sich der rund")
    c.drawString(48, PAGE_H - 125, "300 km lange Oberrheingraben¹. Durch die geschützte Beckenlage und die geringe Meereshöhe zählt")
    c.drawString(48, PAGE_H - 140, "die Region zu den wärmsten und fruchtbarsten Naturräumen Mitteleuropas.")

    # Figure 2.1: OpenStreetMap Thematic & Physical Map of Oberrheingraben
    m_x, m_y, m_w, m_h = 48.0, PAGE_H - 418.0, 495.0, 264.0
    c.drawImage(figs["fig_geo_1"], m_x, m_y, width=m_w, height=m_h)
    c.setFont(fonts["SansBold"], 8.0)
    c.drawString(48, m_y - 14, "Abb. 2.1: Physische und thematische Karte des Oberrheingrabens (© OpenStreetMap-Mitwirkende, ODbL)")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_geo_1", 0, 204, "figures/geo_karte_oberrheingraben.png",
            "Abb. 2.1: Physische und thematische Karte des Oberrheingrabens", "Karte",
            m_x, m_y, m_w, m_h, 900, 480
        )
    )

    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#14532D"))
    c.drawString(48, m_y - 36, "Aufgabe 1: Kartenarbeit zum Oberrheingraben")
    c.setFont(fonts["Sans"], 9.4)
    c.setFillColor(colors.black)
    c.drawString(48, m_y - 52, "1. Bestimme mithilfe des Maßstabs (1 : 2.500.000) und des Gradnetzes die Lage von Straßburg und Freiburg.")
    c.drawString(48, m_y - 68, "2. Beschreibe das Höhenprofil entlang des 48. nördlichen Breitengrades von West nach Ost.")

    # Methode Box on Page 204
    c.setFillColor(colors.HexColor("#F0FDF4"))
    c.setStrokeColor(colors.HexColor("#15803D"))
    c.roundRect(48, 174, PAGE_W - 96, 164, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#14532D"))
    c.drawString(60, 320, "Methode: Eine physische und thematische Karte systematisch auswerten")
    c.setFont(fonts["Sans"], 9.0)
    c.setFillColor(colors.black)
    c.drawString(60, 301, "• 1. Orientierung & Thema: Lies zuerst Kartenüberschrift, Maßstab (1 : 2.500.000: 1 cm auf der")
    c.drawString(68, 286, "Karte entspricht 25 km in der Wirklichkeit), Windrose und die Höhenstufen der Legende.")
    c.drawString(60, 268, "• 2. Verortung im Gradnetz: Bestimme geographische Breite (nördliche Breite: 47°N bis 49°N)")
    c.drawString(68, 253, "und geographische Länge (östliche Länge: 7°O bis 9°O) der wichtigsten Städte und Flüsse.")
    c.drawString(60, 235, "• 3. Raummuster beschreiben: Gliedere den Naturraum in Teilräume (Tiefland der Rheinebene")
    c.drawString(68, 220, "unter 200 m vs. steil aufragende Randgebirge Vogesen und Schwarzwald über 800 m).")
    c.drawString(60, 202, "• 4. Zusammenhänge erklären: Verknüpfe Relief, Gewässernetz und Siedlungsachsen (warum")
    c.drawString(68, 187, "verlaufen Autobahnen, Eisenbahnlinien und Großstädte gebündelt entlang der Grabenachse?).")

    # Explanatory Sub-Section at bottom of Page 204 ending with cross-page hyphenation "Binnen-" -> "schifffahrt." on Page 205
    c.setFont(fonts["SansBold"], 10.4)
    c.setFillColor(colors.HexColor("#166534"))
    c.drawString(48, 152, "Geologie, Lössböden und Wasserstraßen der Oberrheinebene")
    c.setFont(fonts["Serif"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(48, 135, "Beim Einsinken des Grabenbruchs lagerten der Rhein und seine Nebenflüsse mächtige Kies- und")
    c.drawString(48, 120, "Schotterschichten ab. An den Vorbergzonen bildeten sich während der Kaltzeiten fruchtbare Lössböden.")
    c.drawString(48, 105, "Im 19. Jahrhundert veränderte zudem die Rheinbegradigung durch Johann Gottfried Tulla den")
    c.drawString(48, 90, "Flusslauf grundlegend und schuf die Voraussetzung für die moderne Großstadtentwicklung und Binnen-")

    # Footnote 1 at bottom of Page 204
    c.setStrokeColor(colors.HexColor("#94A3B8"))
    c.line(48, 72, 220, 72)
    c.setFont(fonts["Serif"], 8.0)
    c.drawString(48, 56, "¹ Tektonischer Grabenbruch: Einsenkung der Erdkruste im Tertiär entlang paralleler Verwerfungslinien.")
    c.showPage()

    # ==================== PAGE 205 ====================
    draw_book_header_footer(c, 205, "Kapitel 2: Naturraum und Klima in Mitteleuropa", "Geographie · Klasse 9/10", fonts, "#15803D")
    c.setFont(fonts["Serif"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 68, "schifffahrt. Heute zählt die Rheinschiene zwischen Basel, Straßburg und Karlsruhe zu den wichtigsten")
    c.drawString(48, PAGE_H - 83, "europäischen Verkehrs- und Wirtschaftsachsen.")

    c.setFont(fonts["SansBold"], 12.5)
    c.setFillColor(colors.HexColor("#166534"))
    c.drawString(48, PAGE_H - 106, "2.2 Höhenstufen und Luv-Lee-Effekt im Klimavergleich")

    # Side-by-side Subfigures Abb. 2.2a and Abb. 2.2b
    c1_x, c1_y, c1_w, c1_h = 48.0, PAGE_H - 298.0, 240.0, 175.4
    c2_x, c2_y, c2_w, c2_h = 303.0, PAGE_H - 298.0, 240.0, 175.4
    c.drawImage(figs["fig_geo_2a"], c1_x, c1_y, width=c1_w, height=c1_h)
    c.drawImage(figs["fig_geo_2b"], c2_x, c2_y, width=c2_w, height=c2_h)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(c1_x, c1_y - 14, "Abb. 2.2a: Klimadiagramm Freiburg (269 m)")
    c.drawString(c2_x, c2_y - 14, "Abb. 2.2b: Klimadiagramm Feldberg (1493 m)")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_geo_2a", 1, 205, "figures/geo_klima_freiburg.png",
            "Abb. 2.2a: Klimadiagramm Freiburg im Breisgau (269 m ü. NN)", "Klimadiagramm",
            c1_x, c1_y, c1_w, c1_h, 520, 380
        )
    )
    meta_entries.append(
        compute_image_meta_entry(
            "fig_geo_2b", 1, 205, "figures/geo_klima_feldberg.png",
            "Abb. 2.2b: Klimadiagramm Feldberg im Schwarzwald (1493 m ü. NN)", "Klimadiagramm",
            c2_x, c2_y, c2_w, c2_h, 520, 380
        )
    )

    c.setFont(fonts["Serif"], 9.5)
    c.drawString(48, c1_y - 34, "Der Vergleich der beiden Klimastationen verdeutlicht den vertikalen Temperaturgradienten sowie den")
    c.drawString(48, c1_y - 49, "Steigungsregen an den Westflanken des Schwarzwalds². Während Freiburg ein mildes Weinbauklima")
    c.drawString(48, c1_y - 64, "aufweist, herrscht auf dem Feldberg ein kühl-feuchtes Gebirgsklima mit fast doppeltem Jahresniederschlag.")

    # Task 2 on Page 205 (NO difficulty indicator!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#14532D"))
    c.drawString(48, 452, "Aufgabe 2: Klimadiagramme vergleichen und Luv-Lee-Effekt erklären")
    c.setFont(fonts["Sans"], 9.4)
    c.setFillColor(colors.black)
    c.drawString(48, 435, "1. Werte die Klimadiagramme von Freiburg (Abb. 2.2a) und Feldberg (Abb. 2.2b) nach Temperaturamplitude,")
    c.drawString(56, 420, "Jahresmitteltemperatur und Jahresniederschlagssumme systematisch aus.")
    c.drawString(48, 404, "2. Berechne die durchschnittliche Temperaturabnahme pro 100 Höhenmeter zwischen Freiburg und Feldberg.")
    c.drawString(48, 388, "3. Begründe, warum die westlich gelegene Stadt Colmar im Lee der Vogesen nur ca. 550 mm Niederschlag erhält.")

    # Task 3 on Page 205
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#14532D"))
    c.drawString(48, 362, "Aufgabe 3: Flussregulierung und Hochwasserschutz am Oberrhein beurteilen")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(48, 345, "1. Erläutere die ökologischen Folgen der Rheinbegradigung durch Tulla für Grundwasserspiegel und Auenwälder.")
    c.drawString(48, 329, "2. Erkläre die Funktionsweise gesteuerter Rückhaltepolder im Rahmen des Integrierten Rheinprogramms.")

    # Geo-Lexikon Box on Page 205
    c.setFillColor(colors.HexColor("#ECFDF5"))
    c.setStrokeColor(colors.HexColor("#059669"))
    c.roundRect(48, 84, PAGE_W - 96, 232, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#065F46"))
    c.drawString(60, 298, "Geo-Lexikon: Luv-Lee-Effekt, Föhnwirkung und Rheinbegradigung")
    c.setFont(fonts["Sans"], 9.0)
    c.setFillColor(colors.black)
    c.drawString(60, 278, "• Luv-Seite (Windzugewandte Seite): Feuchte atlantische Luftmassen werden aus Westen an")
    c.drawString(68, 263, "den Vogesen und dem Schwarzwald zum Aufsteigen gezwungen. Dabei kühlt die Luft um ca.")
    c.drawString(68, 248, "0,65 °C pro 100 m ab (feuchtadiabatisch), Wolken bilden sich und es fällt Steigungsregen.")
    c.drawString(60, 229, "• Lee-Seite (Windabgewandte Seite): Im Windschatten der Vogesen sinken die abgeregneten")
    c.drawString(68, 214, "Luftmassen in den Oberrheingraben hinab, erwärmen sich trockenadiabatisch um ca. 1,0 °C")
    c.drawString(68, 199, "pro 100 m und lösen Wolken auf (sonnenreiches, trockenes Becken- und Weinbauklima).")
    c.drawString(60, 180, "• Anthropogener Eingriff durch Tulla (ab 1817): Durch den Durchstich zahlreicher Mäander-")
    c.drawString(68, 165, "schlingen verkürzte sich der Oberrhein um über 80 km; die Fließgeschwindigkeit und Tiefen-")
    c.drawString(68, 150, "erosion nahmen stark zu, während ehemalige Überschwemmungsauen trockenfielen.")
    c.drawString(60, 131, "• Hochwasserschutz heute (Integriertes Rheinprogramm): Rückhalteräume (Polder) entlang des")
    c.drawString(68, 116, "Oberrheins werden bei Extremhochwasser gezielt geflutet, um Unterliegerstädte zu schützen.")
    c.drawString(60, 97, "• Klimawandel-Indikator: Im Oberrheingraben steigt die Zahl der Heißen Tage (> 30 °C) deutlich.")

    # Footnote 2 at bottom of Page 205
    c.setStrokeColor(colors.HexColor("#94A3B8"))
    c.line(48, 72, 220, 72)
    c.setFont(fonts["Serif"], 8.0)
    c.drawString(48, 56, "² Steigungsregen (orographischer Niederschlag): Abkühlung und Kondensation feuchter Luftmassen beim Aufstieg am Gebirge.")
    c.showPage()
    c.save()
    return meta_entries


def build_sek1_geschichte_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe I Klasse 9/10 Geschichte PDF (pages 246–247) with ◇/◈/◆ difficulty icons."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Zeitenwandel 9/10: Geschichte für die Sekundarstufe I")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 246 ====================
    draw_book_header_footer(c, 246, "Kapitel 3: Industrialisierung und Soziale Frage", "Geschichte · Klasse 9/10", fonts, "#B45309")
    c.setFont(fonts["SansBold"], 14.2)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(48, PAGE_H - 72, "Kapitel 3: Industrialisierung und Soziale Frage im 19. Jahrhundert")
    c.setFont(fonts["SansBold"], 11.8)
    c.setFillColor(colors.HexColor("#92400E"))
    c.drawString(48, PAGE_H - 92, "3.1 Zeitleiste: Industrialisierung im Deutschen Bund und Kaiserreich")

    # Figure 3.1: Historical Timeline
    tl_x, tl_y, tl_w, tl_h = 48.0, PAGE_H - 246.0, 495.0, 137.5
    c.drawImage(figs["fig_hist_1"], tl_x, tl_y, width=tl_w, height=tl_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, tl_y - 14, "Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_hist_1", 0, 246, "figures/hist_zeitleiste_industrialisierung.png",
            "Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)", "Zeitleiste",
            tl_x, tl_y, tl_w, tl_h, 900, 250
        )
    )

    c.setFont(fonts["Serif"], 9.6)
    c.drawString(48, tl_y - 36, "Der Übergang von der Agrar- zur Industriegesellschaft führte zu einem rasanten Städtewachstum")
    c.drawString(48, tl_y - 51, "(Urbanisierung) und verschärfte die soziale Lage der Fabrikarbeiterschaft¹. Als Leitsektoren der")
    c.drawString(48, tl_y - 66, "Frühindustrialisierung wirkten der Eisenbahnbau, der Steinkohlenbergbau und die Eisenverhüttung.")

    # Historical Statistics Table (Tabelle 3.1)
    c.setFont(fonts["SansBold"], 9.6)
    c.setFillColor(colors.HexColor("#92400E"))
    c.drawString(48, 496, "Tabelle 3.1: Streckennetz der Eisenbahn, Steinkohlenförderung und Urbanisierung (1840–1910)")
    hist_rows = [
        ["Jahr", "Eisenbahnnetz (km)", "Steinkohle (Mio. t)", "Einwohner Essen", "Einwohner Mannheim"],
        ["1840", "469 km", "3,2 Mio. t", "6.300", "22.800"],
        ["1871", "21.471 km", "29,4 Mio. t", "51.500", "39.600"],
        ["1910", "61.209 km", "152,8 Mio. t", "294.600", "193.900"],
    ]
    h_cols = [48, 98, 212, 322, 428, 547]
    h_top = 486
    h_rh = 22
    for r_i, r_vals in enumerate(hist_rows):
        ry = h_top - (r_i + 1) * h_rh
        if r_i == 0:
            c.setFillColor(colors.HexColor("#FEF3C7"))
            c.rect(h_cols[0], ry, h_cols[-1] - h_cols[0], h_rh, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.5)
        for c_i, cell_txt in enumerate(r_vals):
            c.rect(h_cols[c_i], ry, h_cols[c_i + 1] - h_cols[c_i], h_rh, fill=0, stroke=1)
            c.drawString(h_cols[c_i] + 5, ry + 6, cell_txt)

    # Box on Phases of Industrialization
    c.setFillColor(colors.HexColor("#FFFBEB"))
    c.setStrokeColor(colors.HexColor("#D97706"))
    c.roundRect(48, 196, PAGE_W - 96, 178, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(60, 354, "Historisches Grundwissen: Von der Früh- zur Hochindustrialisierung")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(60, 334, "• 1. Vorbedingungen (ab 1834): Die Gründung des Deutschen Zollvereins (1834) beseitigte")
    c.drawString(68, 318, "Binnenzölle und schuf einen einheitlichen Wirtschaftsraum für Handel und Gewerbe.")
    c.drawString(60, 300, "• 2. Frühindustrialisierung (1835–1870): Mit der ersten deutschen Eisenbahn zwischen Nürnberg")
    c.drawString(68, 284, "und Fürth (1835) entstand ein starker Nachfrageschub nach Lokomotiven, Schienen und Kohle.")
    c.drawString(60, 266, "• 3. Hochindustrialisierung (ab 1871): Nach der Reichsgründung stieg Deutschland durch neue")
    c.drawString(68, 250, "Leitindustrien (Chemieindustrie am Rhein, Elektrotechnik, Maschinenbau) zur führenden")
    c.drawString(68, 234, "Industrienation Europas auf. Gleichzeitig wuchsen Industriestädte wie Essen sprunghaft an.")
    c.drawString(60, 214, "• 4. Soziale Folgeprobleme: Wohnungsnot in Mietskasernen, 12- bis 14-Stunden-Schichten und")
    c.drawString(68, 200, "fehlende Absicherung bei Krankheit oder Unfall führten zur Entstehung der Arbeiterbewegung.")

    # Task 1 on Page 246 with diamond icon ◈ ONLY
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(48, 172, "Aufgabe 1 ◈: Statistik und Zeitleiste zur Industrialisierung auswerten")
    c.setFont(fonts["Sans"], 8.9)
    c.setFillColor(colors.black)
    c.drawString(48, 152, "1. Beschreibe anhand von Abb. 3.1 und Tabelle 3.1 den Zusammenhang zwischen Eisenbahnbau und Kohleförderung.")
    c.drawString(48, 134, "2. Vergleiche das Bevölkerungswachstum der Ruhrmetropole Essen mit der Rheinhafenstadt Mannheim (1840–1910).")
    c.drawString(48, 116, "3. Erkläre, warum Historiker den Eisenbahnbau als „Lokomotive der Industrialisierung“ bezeichnen.")

    # Footnote 1 at bottom of Page 246
    c.setStrokeColor(colors.HexColor("#94A3B8"))
    c.line(48, 72, 220, 72)
    c.setFont(fonts["Serif"], 8.0)
    c.drawString(48, 56, "¹ Soziale Frage: Bezeichnung für die wirtschaftlichen und gesellschaftlichen Missstände der Industriearbeiterschaft im 19. Jh.")
    c.showPage()

    # ==================== PAGE 247 ====================
    draw_book_header_footer(c, 247, "Kapitel 3: Industrialisierung und Soziale Frage", "Geschichte · Klasse 9/10", fonts, "#B45309")
    c.setFont(fonts["SansBold"], 13)
    c.setFillColor(colors.HexColor("#92400E"))
    c.drawString(48, PAGE_H - 72, "3.2 Historische Quellen im Vergleich: Arbeitsalltag in der Fabrik")

    # Side-by-side historical source boxes M1 and M2
    c.setFillColor(colors.HexColor("#FEF3C7"))
    c.setStrokeColor(colors.HexColor("#D97706"))
    c.roundRect(48, PAGE_H - 282, 240, 192, 8, fill=1, stroke=1)
    c.roundRect(305, PAGE_H - 282, 240, 192, 8, fill=1, stroke=1)

    c.setFont(fonts["SansBold"], 8.5)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(56, PAGE_H - 110, "M1: Bericht eines Fabrikinspektors (1878)")
    c.drawString(313, PAGE_H - 110, "M2: Erinnerungen einer Textilarbeiterin (1884)")

    m1_lines = [
        "„In den mechanischen Websälen beginnt",
        "die tägliche Schicht um sechs Uhr früh",
        "und endet erst um acht Uhr abends.",
        "Der ohrenbetäubende Lärm der Web-",
        "stühle und die feuchte, staubige Luft",
        "beanspruchen die Gesundheit der",
        "Arbeiter über die Maßen.“",
    ]
    m2_lines = [
        "„Wer fünf Minuten nach dem Werk-",
        "signal am Fabriktor erscheint, dem",
        "wird ein Viertel des Tageslohns",
        "abgezogen. Dennoch hoffen wir auf",
        "den neuen Arbeiterbildungsverein,",
        "der kürzere Arbeitszeiten und",
        "Sicherheit an den Maschinen fordert.“",
    ]
    c.setFont(fonts["Serif"], 9.1)
    c.setFillColor(colors.black)
    for idx, l_txt in enumerate(m1_lines):
        c.drawString(56, PAGE_H - 132 - idx * 17.5, l_txt)
    for idx, l_txt in enumerate(m2_lines):
        c.drawString(313, PAGE_H - 132 - idx * 17.5, l_txt)

    # Task 2 with diamond icon ◇ ONLY
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(48, PAGE_H - 308, "Aufgabe 2 ◇: Quellenvergleich M1 und M2")
    c.setFont(fonts["Sans"], 9.6)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 326, "1. Arbeite aus M1 und M2 die Arbeitsbedingungen in den Textilfabriken heraus.")
    c.drawString(48, PAGE_H - 343, "2. Vergleiche die Perspektive des staatlichen Fabrikinspektors (M1) mit der Sicht der Arbeiterin (M2).")

    # Source M3 Box on Page 247
    c.setFillColor(colors.HexColor("#FEF3C7"))
    c.setStrokeColor(colors.HexColor("#B45309"))
    c.roundRect(48, 354, PAGE_W - 96, 122, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(60, 458, "M3: Auszug aus der Kaiserlichen Botschaft zur Sozialgesetzgebung (17. November 1881)")
    c.setFont(fonts["Serif"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(60, 439, "„Schon im Februar dieses Jahres haben Wir Unsere Überzeugung aussprechen lassen, dass die")
    c.drawString(60, 423, "Heilung der sozialen Schäden nicht ausschließlich im Wege der Repression sozialdemokratischer")
    c.drawString(60, 407, "Ausschreitungen, sondern gleichmäßig auf dem der positiven Förderung des Wohles der Arbeiter")
    c.drawString(60, 391, "zu suchen sein werde. [...] Diejenigen, welche durch Alter oder Invalidität erwerbsunfähig")
    c.drawString(60, 375, "werden, haben der Gesamtheit gegenüber einen begründeten Anspruch auf staatliche Fürsorge.“")

    # Task 3 with diamond icon ◆ ONLY & Methode Box at bottom of Page 247
    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(48, 330, "Aufgabe 3 ◆: Historisches Urteil zur Bismarck’schen Sozialgesetzgebung")
    c.setFont(fonts["Sans"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(48, 312, "1. Erläutere anhand von M3 die doppelte Zielsetzung („Zuckerbrot und Peitsche“) der Sozialpolitik ab 1881.")
    c.drawString(48, 295, "2. Beurteile, inwiefern die Kranken- (1883), Unfall- (1884) und Rentenversicherung (1889) die in M1 und M2")
    c.drawString(56, 279, "geschilderten Missstände im Fabrikalltag lösen konnten.")

    c.setFillColor(colors.HexColor("#FFFBEB"))
    c.setStrokeColor(colors.HexColor("#B45309"))
    c.roundRect(48, 58, PAGE_W - 96, 206, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#78350F"))
    c.drawString(60, 244, "Methode: Schriftliche historische Quellen kritisch analysieren und vergleichen")
    c.setFont(fonts["Sans"], 9.0)
    c.setFillColor(colors.black)
    c.drawString(60, 224, "• 1. Äußere Quellenkritik (Einordnung): Wer ist der Verfasser (Stellung, Amt, soziale Schicht)?")
    c.drawString(68, 208, "Wann und wo ist die Quelle entstanden? An welchen Adressatenkreis richtet sich der Text?")
    c.drawString(60, 190, "• 2. Textsorte bestimmen: Handelt es sich um einen amtlichen Verwaltungsbericht (M1), ein")
    c.drawString(68, 174, "persönliches Selbstzeugnis / Erinnerungen (M2) oder eine offizielle Regierungserklärung (M3)?")
    c.drawString(60, 156, "• 3. Inhaltsanalyse: Fasse die Kernaussagen und Schlüsselbegriffe mit eigenen Worten zusammen.")
    c.drawString(60, 138, "• 4. Innere Quellenkritik (Standortgebundenheit & Intention): Welche Interessen verfolgt der")
    c.drawString(68, 122, "Autor? Was wird bewusst betont, beschönigt oder verschwiegen?")
    c.drawString(60, 104, "• 5. Mehrperspektivischer Vergleich: Stelle Gemeinsamkeiten und Widersprüche zwischen den")
    c.drawString(68, 88, "Quellen gegenüber und ordne sie in den historischen Gesamtzusammenhang des Kaiserreichs ein.")
    c.drawString(60, 70, "• Merke: Erst das Zusammenspiel mehrerer Perspektiven ermöglicht ein ausgewogenes Sachurteil!")
    c.showPage()
    c.save()
    return meta_entries


def build_sek2_chemie_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe II Klasse 11–12 Chemie PDF (pages 310–311) with 2-column Lehrtext and ○/◐/● difficulty icons."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Chemie Oberstufe Q1/Q2: Chemisches Gleichgewicht und Redoxreaktionen")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 310 ====================
    draw_book_header_footer(c, 310, "Kapitel 4: Chemisches Gleichgewicht und Redoxreaktionen", "Chemie · Sekundarstufe II", fonts, "#0F766E")
    c.setFont(fonts["SansBold"], 12.6)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, PAGE_H - 70, "Kapitel 4: Chemisches Gleichgewicht, Veresterung und Redoxreaktionen")
    c.setFont(fonts["SansBold"], 11.4)
    c.setFillColor(colors.HexColor("#0F766E"))
    c.drawString(48, PAGE_H - 90, "4.1 Säurekatalysierte Veresterung und dynamisches Gleichgewicht")

    # 2-Column Explanatory Lehrtext at top of Page 310
    p310_col1 = [
        "Carbonsäuren reagieren mit Alkoholen unter",
        "Säurekatalyse zu fruchtig riechenden Estern",
        "und Wasser. Im Gegensatz zu vielen Fällungs-",
        "reaktionen verläuft diese Kondensation un-",
        "vollständig: Gleichzeitig spaltet das gebildete",
        "Wasser den Ester in einer Rückreaktion (Hydro-",
    ]
    p310_col2 = [
        "lyse) wieder in Säure und Alkohol. Sobald die",
        "Reaktionsgeschwindigkeiten von Hin- und Rück-",
        "reaktion exakt übereinstimmen (v_hin = v_rück),",
        "befindet sich das geschlossene System im",
        "dynamischen chemischen Gleichgewicht. Die",
        "Stoffmengenkonzentrationen bleiben konstant.",
    ]
    draw_two_column_section(c, PAGE_H - 108, p310_col1, p310_col2, fonts, font_key="Serif", font_size=8.8, line_h=13.5)

    # Lab Protocol Header with inline GHS Pictograms (flame, corrosive, exclamation mark)
    c.setFillColor(colors.HexColor("#F0FDFA"))
    c.setStrokeColor(colors.HexColor("#0D9488"))
    c.roundRect(48, 492, PAGE_W - 96, 154, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#134E4A"))
    c.drawString(60, 624, "Versuchsprotokoll V4.1 – Gefahrstoffhinweise:")
    draw_ghs_diamond(c, 370, 628, 12, "GHS02", fonts)
    draw_ghs_diamond(c, 412, 628, 12, "GHS05", fonts)
    draw_ghs_diamond(c, 454, 628, 12, "GHS07", fonts)

    c.setFont(fonts["Sans"], 8.9)
    c.setFillColor(colors.black)
    protocol_lines = [
        "Materialien & Chemikalien: Reagenzgläser, Wasserbad (80 °C), Ethansäure (CH₃COOH),",
        "Ethanol (C₂H₅OH), konzentrierte Schwefelsäure (H₂SO₄, Kat.), Kaliumdichromat-Lösung (K₂Cr₂O₇).",
        "Durchführung: 3 mL Ethansäure und 3 mL Ethanol werden mit 5 Tropfen konz. H₂SO₄ vorsichtig",
        "im Wasserbad erwärmt. Anschließend wird das Gemisch auf Eiswasser gegeben.",
        "Beobachtung: Es bildet sich eine obere, fruchtig nach Klebstoff riechende organische Phase.",
        "Auswertung: Es stellt sich ein dynamisches Veresterungsgleichgewicht ein.",
    ]
    for idx, pline in enumerate(protocol_lines):
        c.drawString(60, 598 - idx * 17.5, pline)

    # Chemical Equations Section
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 472, "Reaktionsgleichungen, Ionenladungen und Oxidationszahlen:")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(56, 454, "1) Veresterungsgleichgewicht (Katalyse durch Oxonium-Ionen H₃O⁺):")
    c.drawString(72, 438, "CH₃COOH + C₂H₅OH   ⇌   CH₃COOC₂H₅ + H₂O     (ΔH° ≈ -4 kJ/mol)")

    c.drawString(56, 416, "2) Redoxreaktion von Dichromat-Ionen mit Eisen(II)-Ionen in saurer Lösung:")
    y_eq2 = 392
    c.drawString(72, y_eq2, "Cr₂O₇²⁻   +   14 H₃O⁺   +   6 Fe²⁺     →     2 Cr³⁺   +   6 Fe³⁺   +   21 H₂O")
    c.setFont(fonts["SansBold"], 7.2)
    c.setFillColor(colors.HexColor("#B91C1C"))
    c.drawString(73, y_eq2 + 10, "+VI -II")
    c.drawString(220, y_eq2 + 10, "+II")
    c.drawString(303, y_eq2 + 10, "+III")
    c.drawString(362, y_eq2 + 10, "+III")

    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(56, 370, "3) Großtechnische Gleichgewichtsreaktion (Kontaktverfahren):")
    y_eq3 = 350
    c.drawString(72, y_eq3, "2 SO₂ (g)  +  O₂ (g)")
    c.setFont(fonts["SansBold"], 7.8)
    c.setFillColor(colors.HexColor("#0F766E"))
    c.drawCentredString(232, y_eq3 + 8, "Kat., 450 °C")
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.2)
    c.line(192, y_eq3 + 3, 272, y_eq3 + 3)
    c.line(266, y_eq3 + 6, 272, y_eq3 + 3)
    c.line(266, y_eq3, 272, y_eq3 + 3)
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(285, y_eq3, "2 SO₃ (g)")

    # 2-Column Reaction Mechanism Section
    c.setFont(fonts["SansBold"], 10.4)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 326, "Reaktionsmechanismus der säurekatalysierten Veresterung (Addition-Eliminierung):")
    mech_col1 = [
        "• Schritt 1 (Protonierung): Ein Oxonium-Ion",
        "(H₃O⁺) überträgt ein Proton auf den Carbonyl-",
        "sauerstoff der Ethansäure. Dadurch erhöht sich",
        "die positive Teilladung am Carbonyl-C-Atom.",
        "• Schritt 2 (Nukleophiler Angriff): Das freie",
    ]
    mech_col2 = [
        "Elektronenpaar des Ethanol-Sauerstoffatoms",
        "greift das elektrophile Carbonyl-C-Atom unter",
        "Bildung einer tetraedrischen Zwischenstufe an.",
        "• Schritt 3 (Eliminierung): Nach Protonenwan-",
        "derung wird H₂O abgespalten (H⁺-Regeneration).",
    ]
    draw_two_column_section(c, 308, mech_col1, mech_col2, fonts, font_key="Sans", font_size=8.5, line_h=13.0)

    # Lab Safety Box at bottom of Page 310
    c.setFillColor(colors.HexColor("#FEF2F2"))
    c.setStrokeColor(colors.HexColor("#DC2626"))
    c.roundRect(48, 58, PAGE_W - 96, 180, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#991B1B"))
    c.drawString(60, 220, "Sicherheit im Chemielabor: Umgang mit Mineralsäuren und Oxidationsmitteln")
    c.setFont(fonts["Sans"], 8.4)
    c.setFillColor(colors.black)
    c.drawString(60, 202, "• Schutzkleidung: Bei allen Experimenten mit konzentrierter Schwefelsäure (H₂SO₄) und Dichromaten")
    c.drawString(68, 187, "sind Schutzbrille, Laborkittel und Schutzhandschuhe zwingend zu tragen.")
    c.drawString(60, 170, "• Verdünnungsregel für konzentrierte Schwefelsäure: „Erst das Wasser, dann die Säure, sonst")
    c.drawString(68, 155, "geschieht das Ungeheure!“ Wegen der stark exothermen Hydratation niemals Wasser in konz. H₂SO₄ gießen.")
    c.drawString(60, 138, "• Brandschutz: Ethanol und Ethylethanoat sind leicht entzündbare Flüssigkeiten (GHS02); daher")
    c.drawString(68, 123, "erfolgt das Erwärmen im Schülerversuch ausschließlich im elektrisch beheizten Wasserbad (80 °C).")
    c.drawString(60, 106, "• Fachgerechte Entsorgung: Chrom(VI)-haltige Lösungen (K₂Cr₂O₇) müssen im sauren Medium")
    c.drawString(68, 91, "vollständig zu Chrom(III)-Ionen reduziert und im Sammelbehälter für Schwermetallsalze entsorgt werden.")
    c.drawString(60, 72, "• Erste Hilfe: Säurespritzer auf der Haut sofort mit reichlich fließendem Wasser abspülen.")
    c.showPage()

    # ==================== PAGE 311 ====================
    draw_book_header_footer(c, 311, "Kapitel 4: Chemisches Gleichgewicht und Redoxreaktionen", "Chemie · Sekundarstufe II", fonts, "#0F766E")
    c.setFont(fonts["SansBold"], 12.5)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, PAGE_H - 72, "4.2 Strukturformeln und Massenwirkungsgesetz (MWG)")

    # Figure 4.1: 2D Organic Structural Formulas
    s_x, s_y, s_w, s_h = 48.0, PAGE_H - 270.0, 495.0, 187.0
    c.drawImage(figs["fig_chem_1"], s_x, s_y, width=s_w, height=s_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, s_y - 14, "Abb. 4.1: Strukturformeln der säurekatalysierten Veresterung und der α-D-Glucopyranose")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_chem_1", 1, 311, "figures/chem_strukturformeln_veresterung_glucose.png",
            "Abb. 4.1: Strukturformeln der säurekatalysierten Veresterung und der α-D-Glucopyranose", "Strukturformel",
            s_x, s_y, s_w, s_h, 900, 340
        )
    )

    # 2-Column Explanatory Lehrtext on Page 311
    p311_col1 = [
        "Im dynamischen Gleichgewicht ist der Quotient",
        "aus dem Produkt der Gleichgewichtskonzen-",
        "trationen der Produkte und dem Produkt der",
        "Eduktkonzentrationen bei konstanter Tempe-",
        "ratur unveränderlich. Diese quantitative Be-",
        "ziehung heißt Massenwirkungsgesetz (MWG):",
    ]
    p311_col2 = [
        "Für die Veresterung von Ethansäure mit Etha-",
        "nol beträgt die Gleichgewichtskonstante bei",
        "Raumtemperatur Kc ≈ 4,0. Durch gezieltes",
        "Entfernen eines Reaktionsprodukts aus dem",
        "Gleichgewichtsgemisch lässt sich die Ausbeute",
        "an Ethylethanoat im Labor deutlich steigern.",
    ]
    draw_two_column_section(c, 536, p311_col1, p311_col2, fonts, font_key="Serif", font_size=8.8, line_h=13.5)

    c.setFont(fonts["SansBold"], 10.2)
    c.setFillColor(colors.HexColor("#0F176E") if False else colors.HexColor("#115E59"))
    c.drawString(72, 444, "Kc = [ c(CH₃COOC₂H₅) · c(H₂O) ] / [ c(CH₃COOH) · c(C₂H₅OH) ] ≈ 4,0")

    # Tasks with difficulty symbols ○ ◐ ● ONLY (NO [leicht]/[mittel]/[schwer] text in PDF!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 418, "Aufgaben zur Redoxchemie und zum chemischen Gleichgewicht:")
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(56, 400, "○ Aufgabe 1: Bestimmen Sie alle Oxidationszahlen in Cr₂O₇²⁻, SO₂ und SO₃.")
    c.drawString(56, 383, "◐ Aufgabe 2: Formulieren Sie die Teilgleichungen der Oxidation und Reduktion für Versuch V4.1.")
    c.drawString(56, 366, "● Aufgabe 3: Berechnen Sie die Gleichgewichtskonzentration an Ethylethanoat bei einem")
    c.drawString(72, 351, "Ausgangsansatz von jeweils 1,0 mol Ethansäure und 1,0 mol Ethanol (Kc = 4,0).")

    # Worked Example Box (Beispielrechnung) & Le Chatelier Box
    c.setFillColor(colors.HexColor("#F0FDFA"))
    c.setStrokeColor(colors.HexColor("#0D9488"))
    c.roundRect(48, 196, PAGE_W - 96, 144, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(60, 322, "Beispielrechnung: Gleichgewichtskonstante Kc und Gleichgewichtsausbeute")
    c.setFont(fonts["Sans"], 7.9)
    c.setFillColor(colors.black)
    c.drawString(60, 304, "• Ansatz im geschlossenen System: n₀(CH₃COOH) = 1,0 mol und n₀(C₂H₅OH) = 1,0 mol (Volumen V kürzt sich heraus).")
    c.drawString(60, 288, "• Im Gleichgewicht seien x mol Ester und x mol Wasser entstanden; es verbleiben (1,0 - x) mol Säure und Alkohol.")
    c.drawString(60, 272, "• Einsetzen in das Massenwirkungsgesetz:  Kc = x² / (1,0 - x)² = 4,0.")
    c.drawString(60, 256, "• Ziehen der Quadratwurzel auf beiden Seiten:  x / (1,0 - x) = 2,0   =>   x = 2,0 - 2,0·x   =>   3,0·x = 2,0.")
    c.drawString(60, 240, "• Ergebnis: Im Gleichgewicht liegen n(Ester) = n(H₂O) = 2/3 mol ≈ 0,67 mol (Ausbeute 66,7 %) sowie")
    c.drawString(68, 226, "jeweils 1/3 mol ≈ 0,33 mol unverbrauchte Ethansäure und Ethanol vor.")
    c.drawString(60, 208, "• Ausbeutesteigerung im Labor: Durch kontinuierliches Abdestillieren des leichtflüchtigen Esters (Sdp. 77 °C).")

    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#2563EB"))
    c.roundRect(48, 58, PAGE_W - 96, 128, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 168, "Merksatz: Prinzip von Le Chatelier (Prinzip vom kleinsten Zwang)")
    c.setFont(fonts["Sans"], 8.0)
    c.setFillColor(colors.black)
    c.drawString(60, 150, "• Übt man auf ein chemisches System im Gleichgewicht durch Änderung von Konzentration, Druck oder")
    c.drawString(68, 135, "Temperatur einen äußeren Zwang aus, so verschiebt sich die Gleichgewichtslage so, dass die")
    c.drawString(68, 120, "Wirkung des äußeren Zwangs minimiert wird.")
    c.drawString(60, 102, "• Temperaturerhöhung begünstigt stets die endotherme Teilreaktion; Temperaturerniedrigung")
    c.drawString(68, 87, "begünstigt die exotherme Teilreaktion (z. B. SO₃-Bildung im Kontaktverfahren bei 450 °C).")
    c.drawString(60, 69, "• Ein Katalysator setzt die Aktivierungsenergie E_A herab, verändert aber niemals die Gleichgewichtskonstante Kc!")
    c.showPage()
    c.save()
    return meta_entries


def build_sek2_biologie_pdf(pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Builds 2-page Sekundarstufe II Klasse 11–12 Biologie PDF (pages 412–413) with 2-column Lehrtext and NO difficulty icons."""
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setTitle("Biologie Oberstufe Q1/Q2: Stoffwechselphysiologie und Enzymkinetik")
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 412 ====================
    draw_book_header_footer(c, 412, "Kapitel 6: Stoffwechselphysiologie und Enzymkinetik", "Biologie · Sekundarstufe II", fonts, "#0F766E")
    c.setFont(fonts["SansBold"], 14.0)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, PAGE_H - 70, "Kapitel 6: Biokatalyse, Enzymkinetik und Stoffwechselregulation")
    c.setFont(fonts["SansBold"], 11.4)
    c.setFillColor(colors.HexColor("#0F766E"))
    c.drawString(48, PAGE_H - 90, "6.1 Molekulare Wirkungsweise von Enzymen und Michaelis-Menten-Kinetik")

    # Figure 6.1: Michaelis-Menten Kinetics Curve
    b_x, b_y, b_w, b_h = 48.0, PAGE_H - 298.0, 495.0, 198.0
    c.drawImage(figs["fig_bio_1"], b_x, b_y, width=b_w, height=b_h)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.black)
    c.drawString(48, b_y - 14, "Abb. 6.1: Michaelis-Menten-Kinetik und Kompetitive Hemmung")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_bio_1", 0, 412, "figures/bio_michaelis_menten_kinetik.png",
            "Abb. 6.1: Michaelis-Menten-Kinetik und Kompetitive Hemmung", "Diagramm",
            b_x, b_y, b_w, b_h, 900, 360
        )
    )

    # 2-Column Explanatory Lehrtext on Page 412
    p412_col1 = [
        "Enzyme wirken als hochspezifische Biokataly-",
        "satoren, indem sie das Substrat im aktiven",
        "Zentrum nach dem Induced-Fit-Modell binden",
        "und die Aktivierungsenergie E_A über einen",
        "Enzym-Substrat-Komplex [ES] herabsetzen.",
        "Die Abhängigkeit der Reaktionsgeschwindig-",
    ]
    p412_col2 = [
        "keit v von der Substratkonzentration [S] folgt",
        "der Michaelis-Menten-Gleichung. Bei niedrigen",
        "Konzentrationen steigt v nahezu linear an,",
        "während bei hohen Substratkonzentrationen",
        "alle aktiven Zentren der Enzymmoleküle ge-",
        "sättigt sind und v_max asymptotisch erreicht wird:",
    ]
    draw_two_column_section(c, 508, p412_col1, p412_col2, fonts, font_key="Serif", font_size=8.8, line_h=13.5)

    c.setFont(fonts["SansBold"], 10.5)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(72, 418, "v = (v_max · [S]) / (K_M + [S])")

    # Bio-Kompakt Box on Page 412
    c.setFillColor(colors.HexColor("#F0FDFA"))
    c.setStrokeColor(colors.HexColor("#0D9488"))
    c.roundRect(48, 200, PAGE_W - 96, 208, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(60, 390, "Bio-Kompakt: Bedeutung der Michaelis-Konstante K_M und Formen der Enzymhemmung")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    c.drawString(60, 372, "• Michaelis-Konstante K_M: Gibt genau diejenige Substratkonzentration [S] (in mmol/L) an, bei der")
    c.drawString(68, 358, "die Hälfte der Maximalgeschwindigkeit (v = ½ v_max) erreicht wird. Ein kleiner K_M-Wert")
    c.drawString(68, 344, "bedeutet eine hohe Affinität (Bindungsstärke) des Enzyms zu seinem Substrat.")
    c.drawString(60, 326, "• Kompetitive Hemmung (Verdrängungshemmung): Der Inhibitor ähnelt strukturell dem Substrat")
    c.drawString(68, 312, "und konkurriert um das aktive Zentrum. Die scheinbare Michaelis-Konstante K_M' ist erhöht;")
    c.drawString(68, 298, "durch hohe Substratkonzentrationen [S] lässt sich der Hemmstoff jedoch verdrängen (v_max bleibt gleich).")
    c.drawString(60, 280, "• Allosterische (nicht-kompetitive) Hemmung: Der Effektor bindet außerhalb des aktiven Zentrums")
    c.drawString(68, 266, "an ein allosterisches Zentrum und verändert die räumliche Konformation des Enzyms.")
    c.drawString(68, 252, "Dadurch sinkt die Maximalgeschwindigkeit v_max, während K_M unverändert bleibt.")
    c.drawString(60, 234, "• Irreversible Hemmung (Enzymgifte): Schwermetall-Ionen (z. B. Pb²⁺, Hg²⁺, Cu²⁺) bilden kovalente")
    c.drawString(68, 220, "Bindungen mit Schwefelgruppen (-SH) der Aminosäure Cystein und inaktivieren das Enzym dauerhaft.")
    c.drawString(60, 206, "• Beispiel Katalase: Spaltet Wasserstoffperoxid (2 H₂O₂ → 2 H₂O + O₂) mit hoher Wechselzahl.")

    # Borderless table spanning across the page break (Page 412 -> Page 413)
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 182, "Tabelle 6.1: Messreihe zur Substratabhängigkeit der Katalase-Aktivität (Teil 1)")
    c.setStrokeColor(colors.HexColor("#0F766E"))
    c.line(48, 174, PAGE_W - 48, 174)
    p412_rows = [
        ("Substrat [S] (mmol/L)", "v ohne Hemmstoff (µmol/min)", "v mit Hemmstoff (µmol/min)", "Sättigungsgrad (%)"),
        ("0,5", "18,2", "8,4", "22,8 %"),
        ("1,0", "32,0", "15,1", "40,0 %"),
        ("2,0", "48,0", "25,6", "60,0 %"),
    ]
    tx_cols = [48, 174, 320, 462]
    for r_i, r_vals in enumerate(p412_rows):
        ry = 158 - r_i * 21
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.3 if r_i == 0 else 9.0)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(tx_cols[c_i], ry, val)
    c.line(48, 82, PAGE_W - 48, 82)
    c.setFont(fonts["SansOblique"], 8.5)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawRightString(PAGE_W - 48, 66, "(Fortsetzung von Tabelle 6.1 auf der Folgeseite)")
    c.showPage()

    # ==================== PAGE 413 ====================
    draw_book_header_footer(c, 413, "Kapitel 6: Stoffwechselphysiologie und Enzymkinetik", "Biologie · Sekundarstufe II", fonts, "#0F766E")
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, PAGE_H - 72, "Tabelle 6.1 (Fortsetzung): Messreihe zur Substratabhängigkeit der Katalase-Aktivität")
    c.setStrokeColor(colors.HexColor("#0F766E"))
    c.line(48, PAGE_H - 78, PAGE_W - 48, PAGE_H - 78)
    p413_rows = [
        ("Substrat [S] (mmol/L)", "v ohne Hemmstoff (µmol/min)", "v mit Hemmstoff (µmol/min)", "Sättigungsgrad (%)"),
        ("4,0", "61,5", "38,8", "76,9 %"),
        ("8,0", "71,1", "53,3", "88,9 %"),
        ("16,0", "76,2", "65,5", "95,3 %"),
        ("32,0", "78,8", "73,1", "98,5 %"),
    ]
    for r_i, r_vals in enumerate(p413_rows):
        ry = PAGE_H - 96 - r_i * 20
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.3 if r_i == 0 else 9.0)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(tx_cols[c_i], ry, val)
    c.line(48, PAGE_H - 184, PAGE_W - 48, PAGE_H - 184)

    # Section 6.2 with 2-Column Explanatory Lehrtext on Page 413
    c.setFont(fonts["SansBold"], 11.6)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 634, "6.2 Abhängigkeit der Enzymaktivität von Temperatur und pH-Wert")

    p413_col1 = [
        "Neben der Substratkonzentration bestimmen",
        "Temperatur und pH-Wert die räumliche Tertiär-",
        "struktur von Enzymproteinen. Nach der RGT-",
        "Regel (Reaktionsgeschwindigkeit-Temperatur-",
        "Regel) erhöht eine Temperatursteigerung um",
        "10 °C die Umsatzrate zunächst um das 2- bis",
        "3-Fache (Q₁₀ ≈ 2–3), da die kinetische Energie",
        "der Teilchen zunimmt. Oberhalb des Tempera-",
        "turoptimums (beim Menschen ca. 37 °C–40 °C)",
        "zerstört die Wärmebewegung jedoch Wasser-",
    ]
    p413_col2 = [
        "stoffbrücken und führt zur irreversiblen Dena-",
        "turierung. Ebenso besitzt jedes Enzym ein",
        "spezifisches pH-Optimum (Pepsin im Magen",
        "pH ≈ 2,0; Speichel-Amylase pH ≈ 7,0; Trypsin",
        "im Dünndarm pH ≈ 8,5). Änderungen der Oxo-",
        "nium-Ionenkonzentration verändern die Ladung",
        "saurer (-COO⁻) und basischer (-NH₃⁺) Seiten-",
        "ketten, sodass Ionenbindungen im aktiven",
        "Zentrum gelöst werden und die Substratbin-",
        "dung drastisch abnimmt.",
    ]
    draw_two_column_section(c, 614, p413_col1, p413_col2, fonts, font_key="Serif", font_size=8.8, line_h=13.5)

    # Tasks on Page 413 (NO difficulty indicators!)
    c.setFont(fonts["SansBold"], 10.8)
    c.setFillColor(colors.HexColor("#115E59"))
    c.drawString(48, 464, "Auswertungs- und Vertiefungsaufgaben zur Enzymkinetik:")
    c.setFont(fonts["Sans"], 9.1)
    c.setFillColor(colors.black)
    c.drawString(56, 446, "Aufgabe 1: Ermitteln Sie aus Abb. 6.1 und Tabelle 6.1 näherungsweise v_max sowie K_M.")
    c.drawString(56, 428, "Aufgabe 2: Begründen Sie auf molekularer Ebene, warum bei kompetitiver Hemmung")
    c.drawString(72, 413, "zwar die scheinbare Michaelis-Konstante K_M' steigt, v_max bei hohem [S] jedoch erreicht wird.")
    c.drawString(56, 395, "Aufgabe 3: Berechnen Sie aus Tabelle 6.1 die prozentuale Hemmung bei [S] = 1,0 mmol/L")
    c.drawString(72, 380, "im Vergleich zu [S] = 32,0 mmol/L und erläutern Sie das Ergebnis.")
    c.drawString(56, 362, "Aufgabe 4: Vergleichen Sie einen anorganischen Katalysator (z. B. H₃O⁺) mit einem Enzym hinsichtlich")
    c.drawString(72, 347, "Spezifität und Temperaturstabilität und erklären Sie, warum Fieber über 42 °C lebensbedrohlich ist.")

    # Bottom Abitur Summary Box on Page 413
    c.setFillColor(colors.HexColor("#F0FDFA"))
    c.setStrokeColor(colors.HexColor("#0F766E"))
    c.roundRect(48, 58, PAGE_W - 96, 272, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.HexColor("#134E4A"))
    c.drawString(60, 310, "Zusammenfassung Abiturwissen: Biokatalyse, Enzymkinetik und Stoffwechselregulation")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(60, 290, "• Aktives Zentrum & Induced-Fit-Modell: Bei der Anlagerung des Substrats passt sich die Raum-")
    c.drawString(68, 274, "struktur des aktiven Zentrums dynamisch an (Substrat- und Wirkungsspezifität).")
    c.drawString(60, 254, "• Energetische Wirkung: Enzyme senken ausschließlich die Aktivierungsenergie E_A über den")
    c.drawString(68, 238, "Enzym-Substrat-Komplex [ES], verändern jedoch weder die Reaktionsenthalpie ΔH noch die")
    c.drawString(68, 222, "Gleichgewichtslage einer reversiblen Stoffwechselreaktion.")
    c.drawString(60, 202, "• Michaelis-Konstante K_M als Affinitätsmaß: Kleines K_M kennzeichnet hohe Substrataffinität;")
    c.drawString(68, 186, "kompetitive Inhibitoren erhöhen scheinbar K_M' ohne v_max zu senken, während allosterische")
    c.drawString(68, 170, "Hemmstoffe v_max herabsetzen.")
    c.drawString(60, 150, "• Negative Rückkopplung (Endprodukthemmung): In mehrschrittigen Stoffwechselketten wirkt das")
    c.drawString(68, 134, "Endprodukt häufig als allosterischer Inhibitor des Schrittmacherenzyms und verhindert Überproduktion.")
    c.drawString(60, 114, "• Kofaktoren und Koenzyme: Viele Enzyme benötigen für ihre katalytische Aktivität zusätzliche")
    c.drawString(68, 98, "Metall-Ionen (z. B. Mg²⁺, Zn²⁺, Fe²⁺) oder organische Überträgermoleküle (NAD⁺, FAD, ATP, Coenzym A).")
    c.drawString(60, 78, "• Kompartimentierung: Durch Reaktionsräume (Mitochondrien, Chloroplasten, Lysosomen) können")
    c.drawString(68, 64, "unterschiedliche pH-Werte und Enzymgarnituren gleichzeitig in derselben Zelle arbeiten.")
    c.showPage()
    c.save()
    return meta_entries


def build_sek2_physik_verzeichnisse_pdf(
    pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Document 9: Sekundarstufe II (Klasse 11–12) — Physik: Wellenoptik und Quantenphysik (4 pages, pp. 44–47).
    Specifically designed to test fast post-upload directory detection and directory-assisted
    page number & heading hierarchy reconstruction:
      - Page 1 (p. 44): Contains Inhaltsverzeichnis (with H1..H4 hierarchy including unnumbered
        indented subsections), Abbildungsverzeichnis, Tabellenverzeichnis, and Bildverzeichnis.
      - Pages 2–4 (pp. 45–47): Content pages with chapters, unnumbered H3/H4 subsections, figures,
        tables, and pictures. Printed page numbers are intentionally omitted on pages 2–4 so
        their page numbers (45, 46, 47) and unnumbered heading levels (###, ####) must be inferred
        from the directories.
    """
    c = canvas.Canvas(pdf_path, pagesize=A4)
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 44 (Directories Page) ====================
    c.setStrokeColor(colors.HexColor("#1E3A8A"))
    c.setLineWidth(1.0)
    c.line(48, PAGE_H - 42, PAGE_W - 48, PAGE_H - 42)
    c.setFont(fonts["SansBold"], 8.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 34, "44   |   Physik Oberstufe · Verzeichnisse zu Kapitel 5")

    # 1. Inhaltsverzeichnis
    c.setFont(fonts["SansBold"], 15.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 72, "Inhaltsverzeichnis")

    toc_rows = [
        (48, "SansBold", 10.5, "Kapitel 5: Wellenoptik und Quantenphysik .............................. 45"),
        (64, "SansBold", 9.8, "5.1 Interferenz und Beugung am Doppelspalt ............................ 45"),
        (84, "Sans", 9.3, "Versuchsaufbau mit dem Doppelspalt .................................... 45"),
        (104, "SansOblique", 9.0, "Herleitung der Gangunterschiedsformel ................................. 46"),
        (64, "SansBold", 9.8, "5.2 Optisches Gitter und hochauflösende Spektroskopie ................. 46"),
        (84, "Sans", 9.3, "Photoelektrischer Effekt und Lichtquantenhypothese .................... 47"),
    ]
    y_cursor = PAGE_H - 98
    c.setFillColor(colors.black)
    for x_ind, f_key, f_sz, line_txt in toc_rows:
        c.setFont(fonts[f_key], f_sz)
        c.drawString(x_ind, y_cursor, line_txt)
        y_cursor -= 20

    # 2. Abbildungsverzeichnis
    y_cursor -= 14
    c.setFont(fonts["SansBold"], 13.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, y_cursor, "Abbildungsverzeichnis")
    y_cursor -= 22
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(48, y_cursor, "Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt .... 45")
    y_cursor -= 18
    c.drawString(48, y_cursor, "Abb. 5.2: Beugung am optischen Gitter und Linienspektrum ................ 46")

    # 3. Tabellenverzeichnis
    y_cursor -= 30
    c.setFont(fonts["SansBold"], 13.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, y_cursor, "Tabellenverzeichnis")
    y_cursor -= 22
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(48, y_cursor, "Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien ... 46")
    y_cursor -= 18
    c.drawString(48, y_cursor, "Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt ......... 47")

    # 4. Bildverzeichnis
    y_cursor -= 30
    c.setFont(fonts["SansBold"], 13.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, y_cursor, "Bildverzeichnis")
    y_cursor -= 22
    c.setFont(fonts["Sans"], 9.3)
    c.setFillColor(colors.black)
    c.drawString(48, y_cursor, "Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young .. 45")
    y_cursor -= 18
    c.drawString(48, y_cursor, "Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung ... 47")

    # Introductory orientation box at bottom of Page 44
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#2563EB"))
    c.roundRect(48, 70, PAGE_W - 96, 175, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 224, "Lernwegweiser zu Kapitel 5: Vom Wellenmodell zum Quantenobjekt Photon")
    c.setFont(fonts["Sans"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(60, 204, "• In Abschnitt 5.1 untersuchen Sie die Kohärenz und Interferenz von Licht am Doppelspalt")
    c.drawString(68, 189, "und leiten die Bedingung für konstruktive und destruktive Interferenz geometrisch her.")
    c.drawString(60, 170, "• In Abschnitt 5.2 nutzen Sie optische Mehrfachspalt-Gitter zur präzisen Wellenlängen-")
    c.drawString(68, 155, "bestimmung atomarer Spektrallinien (Fraunhofer-Linien und Quecksilber-Dampflampe).")
    c.drawString(60, 136, "• Abschließend zeigt der äußere lichtelektrische Effekt (Hallwachs- und Photoeffekt),")
    c.drawString(68, 121, "dass Energie im elektromagnetischen Strahlungsfeld nur in Lichtquanten E = h · f")
    c.drawString(68, 106, "übertragen wird. Alle Abbildungen, Tabellen und Bilder sind oben mit Seitenzahl verzeichnet.")
    c.showPage()

    # ==================== PAGE 45 (No printed footer/header page number!) ====================
    c.setFont(fonts["SansBold"], 14.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 64, "Kapitel 5: Wellenoptik und Quantenphysik")

    c.setFont(fonts["SansBold"], 11.8)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(48, PAGE_H - 92, "5.1 Interferenz und Beugung am Doppelspalt")

    c.setFont(fonts["Serif"], 9.4)
    c.setFillColor(colors.black)
    p45_intro = [
        "Im Jahr 1802 gelang dem englischen Naturforscher Thomas Young mit dem Doppelspaltversuch",
        "der entscheidende experimentelle Nachweis für die Wellennatur des Lichts. Trifft monochro-",
        "matisches, kohärentes Licht der Wellenlänge λ auf zwei eng benachbarte parallele Spalte",
        "mit dem Spaltmittenabstand d, so gehen von beiden Öffnungen nach dem Huygens’schen Prinzip",
        "zylindrische Elementarwellen aus, die sich im Raum hinter der Blende ungestört überlagern.",
    ]
    for idx, ln in enumerate(p45_intro):
        c.drawString(48, PAGE_H - 114 - idx * 14, ln)

    # Unnumbered H3 heading (level 3 in TOC!)
    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 196, "Versuchsaufbau mit dem Doppelspalt")

    # Figure 5.1
    f_x, f_y, f_w, f_h = 48.0, PAGE_H - 388.0, 495.0, 176.0
    c.drawImage(figs["fig_phys_1"], f_x, f_y, width=f_w, height=f_h)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.black)
    c.drawString(48, f_y - 14, "Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_phys_1",
            1,
            45,
            "figures/physik_doppelspalt_interferenz.png",
            "Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt",
            "Diagramm",
            f_x,
            f_y,
            f_w,
            f_h,
            900,
            320,
        )
    )

    c.setFont(fonts["Serif"], 9.4)
    p45_body = [
        "Auf dem Beobachtungsschirm im Abstand L >> d entsteht ein charakteristisches Streifenmuster",
        "aus abwechselnd hellen Interferenzmaxima und dunklen Interferenzminima. Ein helles Maximum",
        "k-ter Ordnung tritt immer dort auf, wo der Gangunterschied Δs der beiden Teilwellen ein",
        "ganzzahliges Vielfaches der Wellenlänge λ beträgt (Δs = k · λ mit k = 0, 1, 2, ...).",
        "Beträgt der Gangunterschied hingegen ein ungeradzahliges Vielfaches einer halben Wellen-",
        "länge, löschen sich Wellenberg und Wellental durch destruktive Interferenz gegenseitig aus.",
    ]
    for idx, ln in enumerate(p45_body):
        c.drawString(48, PAGE_H - 424 - idx * 14, ln)

    # Bild 5.1 description box
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.setStrokeColor(colors.HexColor("#64748B"))
    c.roundRect(48, 72, PAGE_W - 96, 170, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 222, "Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young")
    c.setFont(fonts["Sans"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(60, 202, "• Kohärenzbedingung: Zeitlich und räumlich konstante Phasenbeziehung zwischen beiden")
    c.drawString(68, 187, "Elementarwellenzügen; im modernen Schulexperiment durch einen He-Ne-Laser (λ = 632,8 nm).")
    c.drawString(60, 168, "• Konstruktive Interferenz (Verstärkung): Δs = d · sin(α_k) = k · λ (für k = 0, 1, 2, ...).")
    c.drawString(60, 149, "• Destruktive Interferenz (Auslöschung): Δs = d · sin(α_k) = (k + ½) · λ.")
    c.drawString(60, 130, "• Kleinwinkelnäherung (für kleine Winkel α < 10° gilt sin(α) ≈ tan(α) = y_k / L):")
    c.drawString(68, 114, "Der Streifenabstand benachbarter Maxima auf dem Schirm beträgt Δy = (λ · L) / d.")
    c.drawString(60, 94, "• Je kleiner der Spaltabstand d gewählt wird, desto weiter rücken die Maxima auseinander.")
    c.showPage()

    # ==================== PAGE 46 (No printed footer/header page number!) ====================
    # Unnumbered H4 heading (level 4 in TOC!)
    c.setFont(fonts["SansBold"], 10.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 64, "Herleitung der Gangunterschiedsformel")

    c.setFont(fonts["Serif"], 9.4)
    c.setFillColor(colors.black)
    p46_deriv = [
        "Da der Schirmabstand L im Experiment sehr viel größer als der Spaltmittenabstand d ist",
        "(Fraunhofer-Näherung), verlaufen die beiden Strahlen von den Spalten S₁ und S₂ zu einem",
        "Schirmpunkt P nahezu parallel unter demselben Beugungswinkel α. Fällen wir vom oberen",
        "Spalt S₁ das Lot auf den unteren Strahl, entsteht ein rechtwinkliges Dreieck mit der",
        "Hypotenuse d und der Gegenkathete Δs. Daraus folgt unmittelbar Δs = d · sin(α).",
    ]
    for idx, ln in enumerate(p46_deriv):
        c.drawString(48, PAGE_H - 84 - idx * 14, ln)

    # Section 5.2 (level 2 in TOC!)
    c.setFont(fonts["SansBold"], 11.8)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(48, PAGE_H - 172, "5.2 Optisches Gitter und hochauflösende Spektroskopie")

    c.setFont(fonts["Serif"], 9.4)
    c.setFillColor(colors.black)
    p46_gitter = [
        "Ersetzt man den Doppelspalt durch ein optisches Transmissionsgitter mit N >> 100 äqui-",
        "distanten Spalten (Gitterkonstante g = 1 / n), so bleibt die Lage der Hauptmaxima bei",
        "g · sin(α_k) = k · λ erhalten. Durch die Vielstrahlinterferenz aller N Elementarwellen",
        "werden die Hauptmaxima jedoch extrem scharf und lichtstark, während zwischen zwei",
        "Hauptmaxima jeweils N - 1 Nebenminima nahezu vollständige Dunkelheit erzeugen.",
    ]
    for idx, ln in enumerate(p46_gitter):
        c.drawString(48, PAGE_H - 194 - idx * 14, ln)

    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 278, "Abb. 5.2: Beugung am optischen Gitter und Linienspektrum")
    c.setFont(fonts["Sans"], 8.9)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 294, "Schematischer Strahlengang am Mehrfachspalt (Gitterkonstante g = 1,67 µm, entsprechend 600 Linien/mm):")
    c.drawString(48, PAGE_H - 308, "Kurzwelliges violettes Licht (405 nm) wird weniger stark gebeugt als langwelliges rotes Licht (656 nm).")

    # Table 5.1
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 344, "Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien")
    c.setStrokeColor(colors.HexColor("#1E3A8A"))
    c.line(48, PAGE_H - 352, PAGE_W - 48, PAGE_H - 352)
    tab51_rows = [
        ("Spektrallinie / Element", "Farbeindruck", "Wellenlänge λ (nm)", "Winkel α₁ (1. Ordnung)"),
        ("Quecksilber (Hg-Linie h)", "Violett", "404,7 nm", "14,1°"),
        ("Wasserstoff (H-beta)", "Blaugrün (Cyan)", "486,1 nm", "17,0°"),
        ("Natrium-Doppellinie (Na-D)", "Gelb-Orange", "589,3 nm", "20,7°"),
        ("Helium-Neon-Laser", "Hellrot", "632,8 nm", "22,3°"),
        ("Wasserstoff (H-alpha)", "Tiefrot", "656,3 nm", "23,2°"),
    ]
    t51_cols = [48, 208, 332, 446]
    for r_i, r_vals in enumerate(tab51_rows):
        ry = PAGE_H - 368 - r_i * 20
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.6 if r_i == 0 else 9.0)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(t51_cols[c_i], ry, val)
    c.line(48, PAGE_H - 478, PAGE_W - 48, PAGE_H - 478)

    # Bottom info box on Page 46
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#1D4ED8"))
    c.roundRect(48, 72, PAGE_W - 96, 265, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 316, "Methoden-Kasten: Gitter-Spektroskopie in Astrophysik und Labor")
    c.setFont(fonts["Sans"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(60, 296, "• Auflösungsvermögen eines Gitters: R = λ / Δλ = k · N (wächst mit der beleuchteten Spaltzahl N).")
    c.drawString(60, 276, "• Beispiel Natrium-D-Doppellinie (λ₁ = 589,0 nm und λ₂ = 589,6 nm): Um beide Linien in der")
    c.drawString(68, 260, "ersten Beugungsordnung (k = 1) getrennt aufzulösen, müssen mindestens N ≈ 983 Gitterfurchen")
    c.drawString(68, 244, "kohärent ausgeleuchtet werden.")
    c.drawString(60, 224, "• Maximal beobachtbare Beugungsordnung: Da sin(α_k) ≤ 1 gelten muss, folgt k_max = ⌊g / λ⌋.")
    c.drawString(60, 204, "• Chemische Spektralanalyse (Bunsen & Kirchhoff): Jedes chemische Element besitzt ein")
    c.drawString(68, 188, "unverwechselbares Linienspektrum als optischen Fingerabdruck elektronischer Übergänge.")
    c.drawString(60, 168, "• In der Astrophysik ermöglicht die Verschiebung der Fraunhofer’schen Absorptionslinien")
    c.drawString(68, 152, "(Doppler-Effekt) die exakte Bestimmung der Radialgeschwindigkeit ferner Galaxien.")
    c.drawString(60, 132, "• Unterschied zum Dispersionsprisma: Beim optischen Gitter wird langwelliges rotes Licht")
    c.drawString(68, 116, "stärker abgelenkt als kurzwelliges blaues Licht (Normaldispersion beim Prisma ist umgekehrt).")
    c.drawString(60, 96, "• Eichung im Schülerexperiment: Mit der bekannten He-Ne-Laserwellenlänge λ = 632,8 nm")
    c.drawString(68, 80, "lässt sich zunächst die Gitterkonstante g eines unbekannten optischen Gitters bestimmen.")
    c.showPage()

    # ==================== PAGE 47 (No printed footer/header page number!) ====================
    # Unnumbered H3 heading (level 3 in TOC!)
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 64, "Photoelektrischer Effekt und Lichtquantenhypothese")

    c.setFont(fonts["Serif"], 9.4)
    c.setFillColor(colors.black)
    p47_photo = [
        "Bestrahlt man eine metallische Photokathode (z. B. Cäsium oder Kalium) mit kurzwelligem",
        "ultraviolettem oder blauem Licht, so werden augenblicklich Leitungselektronen aus der",
        "Metalloberfläche ausgelöst (äußerer lichtelektrischer Effekt). Nach der klassischen Wellen-",
        "theorie müsste die maximale kinetische Energie E_kin,max der Photoelektronen von der",
        "Bestrahlungsstärke (Intensität) des Lichts abhängen. Das Experiment mit der Gegenspannungs-",
        "methode zeigt jedoch: E_kin,max hängt ausschließlich linear von der Lichtfrequenz f ab!",
        "Albert Einstein deutete diesen Befund 1905 mit seiner Lichtquantenhypothese: Elektromagne-",
        "tische Strahlung der Frequenz f besteht aus einzelnen Energiequanten (Photonen) der Energie",
        "E_Photon = h · f mit dem Planck’schen Wirkungsquantum h = 6,626 · 10⁻³⁴ J·s.",
    ]
    for idx, ln in enumerate(p47_photo):
        c.drawString(48, PAGE_H - 86 - idx * 14, ln)

    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 224, "Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung")
    c.setFont(fonts["Sans"], 8.9)
    c.setFillColor(colors.black)
    c.drawString(48, PAGE_H - 240, "Vakuum-Photozelle mit bestrahlter Kalium-Kathode, Ringanode, einstellbarer Gegenspannung U_G und")
    c.drawString(48, PAGE_H - 254, "Picoamperemeter: Bei e · U_G = E_kin,max = h · f - W_A sinkt der Photostrom exakt auf null.")

    # Table 5.2
    c.setFont(fonts["SansBold"], 10.0)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 286, "Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt")
    c.setStrokeColor(colors.HexColor("#1E3A8A"))
    c.line(48, PAGE_H - 294, PAGE_W - 48, PAGE_H - 294)
    tab52_rows = [
        ("Kathodenmetall", "Austrittsarbeit W_A (eV)", "Grenzfrequenz f_G (10¹⁴ Hz)", "Grenzwellenlänge λ_G (nm)"),
        ("Cäsium (Cs)", "1,94 eV", "4,69 · 10¹⁴ Hz", "639 nm (Rot)"),
        ("Kalium (K)", "2,25 eV", "5,44 · 10¹⁴ Hz", "551 nm (Grün)"),
        ("Natrium (Na)", "2,28 eV", "5,51 · 10¹⁴ Hz", "544 nm (Grün)"),
        ("Zink (Zn)", "4,31 eV", "10,4 · 10¹⁴ Hz", "288 nm (UV)"),
        ("Platin (Pt)", "5,32 eV", "12,9 · 10¹⁴ Hz", "233 nm (UV)"),
    ]
    t52_cols = [48, 182, 322, 456]
    for r_i, r_vals in enumerate(tab52_rows):
        ry = PAGE_H - 310 - r_i * 20
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.6 if r_i == 0 else 9.0)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(t52_cols[c_i], ry, val)
    c.line(48, PAGE_H - 420, PAGE_W - 48, PAGE_H - 420)

    # Exercises & Merksatz on Page 47
    c.setFont(fonts["SansBold"], 10.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(48, PAGE_H - 446, "Übungsaufgaben zu Wellenoptik und Quantenphysik:")
    c.setFont(fonts["Sans"], 8.9)
    c.setFillColor(colors.black)
    c.drawString(56, PAGE_H - 464, "Aufgabe 1: Berechnen Sie aus Tab. 5.1 die Gitterkonstante g des verwendeten optischen Gitters.")
    c.drawString(56, PAGE_H - 480, "Aufgabe 2: Begründen Sie mithilfe von Tab. 5.2, warum rotes Laserlicht (λ = 632,8 nm) zwar an")
    c.drawString(72, PAGE_H - 494, "einer Cäsium-Kathode, nicht aber an einer Kalium- oder Zink-Kathode Photoelektronen auslöst.")
    c.drawString(56, PAGE_H - 510, "Aufgabe 3: Bestimmen Sie die maximale kinetische Energie und Geschwindigkeit der Photoelektronen")
    c.drawString(72, PAGE_H - 524, "beim Bestrahlen einer Kalium-Kathode mit violettem Quecksilberlicht (λ = 404,7 nm).")

    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#1E3A8A"))
    c.roundRect(48, 64, PAGE_W - 96, 224, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(60, 268, "Merksatz: Einstein’sche Gleichung des Photoeffekts und Welle-Teilchen-Dualismus")
    c.setFont(fonts["Sans"], 8.7)
    c.setFillColor(colors.black)
    c.drawString(60, 248, "• Energiebilanz beim Photoeffekt: E_kin,max = h · f - W_A = e · U_G.")
    c.drawString(60, 228, "• Grenzfrequenz f_G = W_A / h: Unterhalb von f_G werden selbst bei höchster Lichtintensität")
    c.drawString(68, 212, "keine Elektronen ausgelöst; oberhalb von f_G setzt der Photostrom verzögerungsfrei ein.")
    c.drawString(60, 192, "• Bedeutung der Lichtintensität: Eine höhere Bestrahlungsstärke bedeutet mehr Photonen pro")
    c.drawString(68, 176, "Sekunde und erhöht die Stromstärke I_Photo, nicht jedoch die Einzelenergie h · f.")
    c.drawString(60, 156, "• Welle-Teilchen-Dualismus: Bei der Ausbreitung im Raum (Beugung am Doppelspalt und Gitter)")
    c.drawString(68, 140, "zeigt Licht Welleneigenschaften; bei der Wechselwirkung mit Materie (Emission und Absorption)")
    c.drawString(68, 124, "tritt sein Teilchencharakter in Form unteilbarer Lichtquanten (Photonen) hervor.")
    c.drawString(60, 104, "• Umrechnung der Energieeinheit Elektronenvolt: 1 eV = 1,602 · 10⁻¹⁹ J.")
    c.drawString(60, 84, "• Impuls eines Photons: p = E / c = h / λ (experimentell bestätigt durch den Compton-Effekt).")
    c.showPage()

    c.save()
    return meta_entries


# ---------------------------------------------------------------------------
# Multi-Format Schoolbook Extensions (B5+, B5-Breit, Querformat-Doppelseite)
# & OpenStax CC0 Map Sanitizer
# ---------------------------------------------------------------------------

B5_PLUS_SIZE = (538.58, 737.01)      # 190 x 260 mm (Sek I standard textbook format)
B5_WIDE_SIZE = (552.76, 737.01)      # 195 x 260 mm (Sek II wide textbook format)
SPREAD_LANDSCAPE_SIZE = (680.31, 481.89)  # 240 x 170 mm (Grundschule Lesebuch Doppelseiten-Spread)


def generate_multi_format_figures() -> Dict[str, str]:
    """Generates high-resolution figures for the 3 multi-format schoolbooks and the CC0 Indus-Mesopotamia map."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    figs: Dict[str, str] = {}

    # 1. Informatik Flowchart (Programmablaufplan): 880 x 340 px
    inf_path = os.path.join(FIGURES_DIR, "informatik_programmablaufplan.png")
    im_inf = make_vertical_gradient(880, 340, (238, 246, 255), (214, 232, 252), grain=2.5)
    draw = ImageDraw.Draw(im_inf)
    f_b = load_pil_font(15, bold=True)
    f_r = load_pil_font(13)
    draw.rounded_rectangle([12, 12, 868, 328], radius=12, outline=(30, 64, 175), width=3)
    draw.text((28, 22), "Programmablaufplan (PAP): Hinderniserkennung & Ausweichsteuerung", fill=(23, 37, 84), font=f_b)
    # Start node
    draw.rounded_rectangle([40, 130, 155, 190], radius=24, fill=(34, 197, 94), outline=(21, 128, 61), width=2)
    draw.text((68, 150), "Start", fill=(255, 255, 255), font=f_b)
    # Sensor input node
    draw.rectangle([195, 125, 365, 195], fill=(59, 130, 246), outline=(29, 78, 216), width=2)
    draw.text((210, 140), "Ultraschallsensor:", fill=(255, 255, 255), font=f_b)
    draw.text((210, 162), "Messe Abstand d (cm)", fill=(239, 246, 255), font=f_r)
    # Decision diamond
    draw.polygon([(485, 95), (585, 160), (485, 225), (385, 160)], fill=(250, 204, 21), outline=(180, 83, 9), width=2)
    draw.text((435, 150), "d < 25 cm ?", fill=(30, 41, 59), font=f_b)
    # Ja branch (top right)
    draw.rectangle([635, 65, 845, 135], fill=(239, 68, 68), outline=(153, 27, 27), width=2)
    draw.text((650, 78), "Ja: Stoppe Motoren &", fill=(255, 255, 255), font=f_b)
    draw.text((650, 102), "drehe 90° nach rechts", fill=(255, 241, 242), font=f_r)
    # Nein branch (bottom right)
    draw.rectangle([635, 185, 845, 255], fill=(16, 185, 129), outline=(6, 95, 70), width=2)
    draw.text((650, 198), "Nein: Fahre geradeaus", fill=(255, 255, 255), font=f_b)
    draw.text((650, 222), "(Geschwindigkeit v = 50 %)", fill=(236, 253, 245), font=f_r)
    # Arrows
    draw.line([(155, 160), (195, 160)], fill=(30, 41, 59), width=3)
    draw.line([(365, 160), (385, 160)], fill=(30, 41, 59), width=3)
    draw.line([(485, 95), (485, 80), (635, 80)], fill=(185, 28, 28), width=3)
    draw.line([(485, 225), (485, 235), (635, 235)], fill=(4, 120, 87), width=3)
    draw.text((28, 290), "Endlosschleife (Wiederhole fortlaufend alle 50 ms bis Stopp-Taste gedrückt)", fill=(30, 58, 138), font=f_r)
    im_inf.save(inf_path, "PNG")
    figs["fig_info_1"] = inf_path

    # 2. Mathematik Analysis Function Plot: 880 x 360 px
    ana_path = os.path.join(FIGURES_DIR, "mathe_analysis_funktionsgraphen.png")
    im_ana = make_vertical_gradient(880, 360, (248, 250, 252), (226, 232, 240), grain=2.5)
    draw_a = ImageDraw.Draw(im_ana)
    draw_a.rounded_rectangle([10, 10, 870, 350], radius=10, outline=(15, 23, 42), width=2)
    # Grid lines
    ox, oy = 140, 260
    scale_x, scale_y = 95.0, 42.0
    for gx in range(-1, 7):
        px = int(ox + gx * scale_x)
        draw_a.line([(px, 30), (px, 330)], fill=(203, 213, 225), width=1)
        if gx != 0:
            draw_a.text((px - 6, oy + 6), str(gx), fill=(51, 65, 85), font=f_r)
    for gy in range(-1, 5):
        py = int(oy - gy * scale_y)
        draw_a.line([(50, py), (840, py)], fill=(203, 213, 225), width=1)
        if gy != 0:
            draw_a.text((ox - 24, py - 8), str(gy), fill=(51, 65, 85), font=f_r)
    # Shaded integral region under f(x) = 0.25*x^3 - 1.5*x^2 + 2*x + 1 on [0, 4]
    poly_pts = [(ox, oy)]
    for step in range(0, 161):
        xv = step * 4.0 / 160.0
        yv = 0.25 * (xv ** 3) - 1.5 * (xv ** 2) + 2.0 * xv + 1.0
        poly_pts.append((int(ox + xv * scale_x), int(oy - yv * scale_y)))
    poly_pts.append((int(ox + 4.0 * scale_x), oy))
    draw_a.polygon(poly_pts, fill=(191, 219, 254))
    # Axes
    draw_a.line([(45, oy), (845, oy)], fill=(15, 23, 42), width=2)
    draw_a.line([(ox, 25), (ox, 335)], fill=(15, 23, 42), width=2)
    draw_a.text((830, oy - 22), "x", fill=(15, 23, 42), font=f_b)
    draw_a.text((ox + 8, 24), "y = f(x)", fill=(15, 23, 42), font=f_b)
    # Plot curve f(x) and derivative f'(x)
    curve_pts = []
    deriv_pts = []
    for step in range(-30, 230):
        xv = step / 40.0
        yv = 0.25 * (xv ** 3) - 1.5 * (xv ** 2) + 2.0 * xv + 1.0
        dyv = 0.75 * (xv ** 2) - 3.0 * xv + 2.0
        px = int(ox + xv * scale_x)
        py = int(oy - yv * scale_y)
        pdy = int(oy - dyv * scale_y)
        if 30 <= py <= 330:
            curve_pts.append((px, py))
        if 30 <= pdy <= 330:
            deriv_pts.append((px, pdy))
    if len(curve_pts) > 2:
        draw_a.line(curve_pts, fill=(29, 78, 216), width=3)
    if len(deriv_pts) > 2:
        draw_a.line(deriv_pts, fill=(220, 38, 38), width=2)
    # Highlight H, W, T
    for x_pt_val, y_pt_val, lbl_txt, col in [
        (0.845, 1.77, "H(0,85 | 1,77)", (22, 163, 74)),
        (2.0, 1.0, "W(2 | 1)", (147, 51, 234)),
        (3.155, 0.23, "T(3,15 | 0,23)", (217, 119, 6)),
    ]:
        cx = int(ox + x_pt_val * scale_x)
        cy = int(oy - y_pt_val * scale_y)
        draw_a.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=col, outline=(15, 23, 42))
        draw_a.text((cx + 8, cy - 16), lbl_txt, fill=col, font=f_b)
    draw_a.text((520, 38), "Blau: f(x) = ¼x³ - 1,5x² + 2x + 1", fill=(29, 78, 216), font=f_b)
    draw_a.text((520, 62), "Rot: Ableitung f'(x) = 0,75x² - 3x + 2", fill=(220, 38, 38), font=f_b)
    draw_a.text((210, 215), "Integralfläche A = 4 FE", fill=(30, 64, 175), font=f_b)
    im_ana.save(ana_path, "PNG")
    figs["fig_ana_1"] = ana_path

    # 3. Grundschule Lesebuch Lighthouse Illustration: 840 x 320 px
    les_path = os.path.join(FIGURES_DIR, "gs_lesebuch_kueste.png")
    im_les = make_vertical_gradient(840, 320, (30, 58, 138), (96, 165, 250), grain=2.5)
    draw_l = ImageDraw.Draw(im_les)
    # Sea waves at bottom
    draw_l.rectangle([0, 215, 840, 320], fill=(15, 118, 110))
    for wx in range(0, 840, 70):
        draw_l.arc([wx, 205, wx + 80, 245], start=0, end=180, fill=(153, 246, 228), width=3)
    # Rocky island & red-white lighthouse
    draw_l.polygon([(120, 240), (200, 175), (310, 185), (360, 240)], fill=(100, 116, 139))
    for stripe_i in range(5):
        sy = 180 - stripe_i * 24
        scol = (220, 38, 38) if stripe_i % 2 == 0 else (248, 250, 252)
        draw_l.rectangle([225, sy - 24, 275, sy], fill=scol, outline=(30, 41, 59))
    # Lantern & warm light beam
    draw_l.polygon([(275, 68), (780, 18), (780, 145)], fill=(254, 240, 138))
    draw_l.ellipse([230, 44, 270, 72], fill=(250, 204, 21), outline=(161, 98, 7), width=2)
    # Fishing boat in the beam
    draw_l.polygon([(560, 215), (670, 215), (650, 245), (580, 245)], fill=(120, 53, 15), outline=(255, 255, 255))
    draw_l.text((40, 275), "Der kleine Leuchtturm weist dem Fischerboot „Nordstern“ den sicheren Weg in den Hafen.", fill=(255, 255, 255), font=f_b)
    im_les.save(les_path, "PNG")
    figs["fig_les_1"] = les_path

    # 4. CC0 1.0 Public Domain Trade-Routes Map (Indus Valley - Mesopotamia) for OpenStax History: 700 x 500 px
    cc0_map_path = os.path.join(FIGURES_DIR, "openstax_indus_mesopotamia_trade_cc0.png")
    im_map = make_vertical_gradient(700, 500, (245, 235, 210), (222, 205, 172), grain=2.5)
    draw_m = ImageDraw.Draw(im_map)
    # Sea bodies (Persian Gulf & Arabian Sea / Indian Ocean)
    draw_m.polygon([(140, 240), (260, 275), (315, 345), (275, 370), (130, 290)], fill=(147, 197, 253), outline=(59, 130, 246), width=2)
    draw_m.polygon([(275, 370), (315, 345), (490, 355), (699, 440), (699, 499), (240, 499)], fill=(96, 165, 250), outline=(37, 99, 235), width=2)
    # Mesopotamia & Indus fertile river valleys
    draw_m.line([(65, 110), (115, 175), (155, 245)], fill=(37, 99, 235), width=3)
    draw_m.line([(45, 135), (100, 195), (155, 245)], fill=(37, 99, 235), width=3)
    draw_m.line([(565, 95), (535, 215), (495, 355)], fill=(37, 99, 235), width=4)
    # Trade routes (Overland Iranian Plateau & Maritime Arabian Sea)
    draw_m.line([(125, 215), (285, 175), (445, 165), (545, 175)], fill=(185, 28, 28), width=4)
    draw_m.line([(155, 255), (265, 325), (395, 385), (515, 365)], fill=(15, 118, 110), width=4)
    # Cities
    for cx, cy, cname in [
        (105, 190, "Babylon"),
        (140, 235, "Ur (Mesopotamia)"),
        (550, 170, "Harappa"),
        (515, 285, "Mohenjo-Daro"),
        (535, 365, "Lothal (Port)"),
    ]:
        draw_m.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(15, 23, 42), outline=(255, 255, 255), width=2)
        draw_m.text((cx + 10, cy - 10), cname, fill=(15, 23, 42), font=f_b)
    draw_m.text((240, 135), "Overland Route (Iranian Plateau: Lapis Lazuli & Tin)", fill=(153, 27, 27), font=f_b)
    draw_m.text((260, 415), "Maritime Trade Route (Arabian Sea / Meluhha)", fill=(17, 94, 89), font=f_b)
    draw_m.text((20, 20), "Indus Valley & Mesopotamia Trade Network (3rd Millennium BCE) · CC0 1.0", fill=(30, 41, 59), font=f_b)
    im_map.save(cc0_map_path, "PNG")
    figs["fig_openstax_cc0_map"] = cc0_map_path

    return figs


def build_sek1_informatik_pdf(
    pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Document 10: Sekundarstufe I (Klasse 7/8) — Informatik & Medienbildung (2 pages, pp. 18–19).
    Physical format: B5+ Standard-Schulbuchformat (190 x 260 mm = 538.58 x 737.01 pt).
    Tests:
      - Non-A4 B5+ page dimensions
      - Flowchart diagram (Abb. 1.1), Mediencode/QR margin box, and Merksatz callout box
      - Truth table (Tabelle 1.1) and self-assessment competency check ('Teste dich!')
      - PDF text-layer soft hyphens (\u00ad) and InDesign print-production slug line (.indd) at bottom edge
    """
    pw, ph = B5_PLUS_SIZE
    c = canvas.Canvas(pdf_path, pagesize=B5_PLUS_SIZE)
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 18 ====================
    c.setStrokeColor(colors.HexColor("#1D4ED8"))
    c.setLineWidth(1.0)
    c.line(40, ph - 38, pw - 40, ph - 38)
    c.setFont(fonts["SansBold"], 8.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 30, "18   |   Kapitel 1: Algorithmen, Kontrollstrukturen und Datenverarbeitung")

    c.setFont(fonts["SansBold"], 13.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 62, "Kapitel 1: Algorithmen und Programmierung")
    c.setFont(fonts["SansBold"], 11.0)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(40, ph - 84, "1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife")

    # Explanatory text containing authentic soft hyphens (\u00ad) as found in 34/50 publisher PDFs
    c.setFont(fonts["Serif"], 9.0)
    c.setFillColor(colors.black)
    p18_lines = [
        "Ein Algorithmus ist eine eindeutige, ausführbare und endliche Handlungsvorschrift zur",
        "schrittweisen Lösung eines Problems. In der modernen Robotik und Mikro\u00adcontroller-",
        "Technik verarbeiten autonome Systeme kontinuierlich Sensordaten, um auf Hindernisse",
        "in ihrer Umgebung zu reagieren. Dabei folgt jedes Computer\u00adprogramm drei elementaren",
        "Kontrollstrukturen: der linearen Sequenz (Befehlsfolge), der bedingten Verzweigung",
        "(Wenn-Dann-Sonst-Entscheidung) und der Wiederholungsschleife (Iteration).",
    ]
    for idx, ln in enumerate(p18_lines):
        c.drawString(40, ph - 104 - idx * 13.5, ln)

    # Flowchart Figure Abb. 1.1
    fx, fy, fw, fh = 40.0, ph - 365.0, 458.0, 175.0
    c.drawImage(figs["fig_info_1"], fx, fy, width=fw, height=fh)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(40, fy - 14, "Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_info_1",
            0,
            18,
            "figures/informatik_programmablaufplan.png",
            "Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters",
            "Strukturdiagramm",
            fx,
            fy,
            fw,
            fh,
            880,
            340,
            page_w=pw,
            page_h=ph,
        )
    )

    # Mediencode / Digital Box (typical in 21/50 NRW publisher textbooks)
    c.setFillColor(colors.HexColor("#F0FDF4"))
    c.setStrokeColor(colors.HexColor("#16A34A"))
    c.roundRect(40, ph - 445, pw - 80, 54, 6, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.HexColor("#166534"))
    c.drawString(50, ph - 408, "Mediencode 74108-18: Interaktive Simulation Labyrinth-Roboter")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    c.drawString(50, ph - 423, "• Teste den Programmablaufplan aus Abb. 1.1 im virtuellen 2D-Parcours mit verschiedenen")
    c.drawString(58, ph - 436, "Schwellenwerten (d < 15 cm, d < 25 cm, d < 40 cm) und beobachte die Fahrspur des Roboters.")

    # Merksatz Callout Box at bottom of Page 18
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#2563EB"))
    c.roundRect(40, 58, pw - 80, 215, 7, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(50, 254, "Merksatz: Algorithmus und Grundstrukturen nach Böhm und Jacopini")
    c.setFont(fonts["Sans"], 8.4)
    c.setFillColor(colors.black)
    c.drawString(50, 236, "• Eindeutigkeit (Determiniertheit): Nach jedem Einzelschritt ist exakt festgelegt, welche")
    c.drawString(58, 222, "Anweisung als Nächstes ausgeführt wird; es gibt keinen Interpretationsspielraum.")
    c.drawString(50, 204, "• Sequenz (Folge): Anweisungen werden streng nacheinander von oben nach unten abgearbeitet.")
    c.drawString(50, 186, "• Bedingte Verzweigung (Selektion): Eine logische Bedingung (Wahrheitswert wahr oder falsch)")
    c.drawString(58, 172, "entscheidet darüber, ob der Ja-Zweig oder der Nein-Zweig durchlaufen wird.")
    c.drawString(50, 154, "• Schleife (Iteration): Ein Anweisungsblock wird solange wiederholt, wie eine Laufbedingung")
    c.drawString(58, 140, "erfüllt ist (kopfgesteuerte Solange-Schleife) oder eine feste Anzahl erreicht wurde.")
    c.drawString(50, 122, "• Satz von Böhm und Jacopini (1966): Jedes berechenbare Problem lässt sich ausschließlich")
    c.drawString(58, 108, "durch die Kombination von Sequenz, Verzweigung und Schleife ohne Sprungbefehle lösen.")
    c.drawString(50, 90, "• Terminierung vs. Endlosschleife: Während Berechnungsalgorithmen nach endlich vielen")
    c.drawString(58, 76, "Schritten enden müssen, nutzen eingebettete Steuerungen oft eine dauerhafte Ereignisschleife.")

    # InDesign print-production slug at bottom edge (should be stripped by post-processing!)
    c.setFont(fonts["Mono"], 6.5)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(40, 18, "INFO_NRW_7_8_K01_010_029.indd   18   14.10.2025   09:42:15")
    c.showPage()

    # ==================== PAGE 19 ====================
    c.setStrokeColor(colors.HexColor("#1D4ED8"))
    c.setLineWidth(1.0)
    c.line(40, ph - 38, pw - 40, ph - 38)
    c.setFont(fonts["SansBold"], 8.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 30, "1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife   |   19")

    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 62, "Logische Verknüpfungen und Sensordaten-Auswertung")

    c.setFont(fonts["Serif"], 9.0)
    c.setFillColor(colors.black)
    p19_intro = [
        "Damit ein autonomer Transportroboter in einer Werkhalle nicht mit Regalen oder Personen",
        "kollidiert, kombiniert seine Steuerung oft mehrere Sensoren über boolesche Operatoren",
        "(UND, ODER, NICHT). Ein Ausweichmanöver wird genau dann eingeleitet, wenn der vordere",
        "Ultraschallsensor ein Hindernis meldet (A = 1) ODER der Stoßfänger-Taster ausgelöst wird (B = 1).",
    ]
    for idx, ln in enumerate(p19_intro):
        c.drawString(40, ph - 82 - idx * 13.5, ln)

    # Table 1.1: Truth & Sensor Table
    c.setFont(fonts["SansBold"], 9.5)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 150, "Tabelle 1.1: Wahrheitstabelle und Aktor-Reaktion der Robotersteuerung")
    c.line(40, ph - 156, pw - 40, ph - 156)
    tab_info_rows = [
        ("Sensor A (Abstand < 25 cm)", "Sensor B (Taster vorn)", "Verknüpfung A ODER B", "Aktor-Befehl (Fahrmotoren)"),
        ("0 (frei)", "0 (nicht gedrückt)", "0 (falsch)", "Geradeaus fahren (v = 50 %)"),
        ("0 (frei)", "1 (gedrückt)", "1 (wahr)", "Sofort stoppen & zurücksetzen"),
        ("1 (Hindernis nah)", "0 (nicht gedrückt)", "1 (wahr)", "Stoppen & 90° rechts drehen"),
        ("1 (Hindernis nah)", "1 (gedrückt)", "1 (wahr)", "Not-Stopp & Warnsignalton"),
    ]
    t_info_cols = [40, 172, 286, 386]
    for r_i, r_vals in enumerate(tab_info_rows):
        ry = ph - 172 - r_i * 18
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.0 if r_i == 0 else 8.3)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(t_info_cols[c_i], ry, val)
    c.line(40, ph - 252, pw - 40, ph - 252)

    # Exercises on Page 19 (no difficulty symbols)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 278, "Aufgabe 1: Programmablaufplan nachvollziehen (Trace-Tabelle)")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(40, ph - 293, "Der Ultraschallsensor liefert nacheinander die Messwerte d = 62 cm, d = 38 cm, d = 19 cm und")
    c.drawString(40, ph - 306, "d = 45 cm. Gib für jeden Messwert an, welchen Zweig der Roboter in Abb. 1.1 durchläuft.")

    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 330, "Aufgabe 2: Erweiterung um einen linken und rechten Seitensensor")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(40, ph - 345, "Formuliere eine geschachtelte Wenn-Dann-Sonst-Bedingung, mit der der Roboter vor einer")
    c.drawString(40, ph - 358, "Drehung prüft, ob rechts mehr Platz ist als links (d_rechts > d_links).")

    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(40, ph - 382, "Aufgabe 3: Boolesche Algebra im Alltag")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(40, ph - 397, "Erkläre den Unterschied zwischen einer UND-Verknüpfung (Konjunktion) und einer ODER-")
    c.drawString(40, ph - 410, "Verknüpfung (Disjunktion) am Beispiel einer automatischen Gewächshaus-Bewässerung.")

    # Self-assessment box ('Checkliste: Teste dich!') at bottom of Page 19
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#1D4ED8"))
    c.roundRect(40, 58, pw - 80, 240, 7, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(50, 280, "Checkliste: Teste dich! — Trainingsplan zu Kapitel 1")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    c.drawString(50, 260, "• Ich kann die Begriffe Algorithmus, Sequenz, Verzweigung und Schleife an einem")
    c.drawString(58, 246, "Alltagsbeispiel erläutern (Nachlesen: S. 18, Merksatz).")
    c.drawString(50, 226, "• Ich kann einen gegebenen Programmablaufplan (PAP) nach DIN 66001 lesen und für")
    c.drawString(58, 212, "konkrete Eingabewerte Schritt für Schritt auswerten (Nachlesen: S. 18, Abb. 1.1).")
    c.drawString(50, 192, "• Ich kann einfache und zusammengesetzte Bedingungen mit den logischen Operatoren")
    c.drawString(58, 178, "UND, ODER sowie NICHT in einer Wahrheitstabelle darstellen (Nachlesen: S. 19, Tab. 1.1).")
    c.drawString(50, 158, "• Ich kann erklären, warum eine Robotersteuerung in einer dauerhaften Ereignisschleife")
    c.drawString(58, 144, "arbeitet und wie ein Not-Stopp-Abbruchkriterium integriert wird (Nachlesen: S. 19).")
    c.drawString(50, 124, "• Ich kann zu einer textuell beschriebenen Problemstellung selbstständig einen")
    c.drawString(58, 110, "fehlerfreien Programmablaufplan entwerfen und testen (Übung: Aufgabe 2).")
    c.drawString(50, 90, "• Ich kann im Simulator mithilfe des Mediencodes 74108-18 eigene Schwellenwerte")
    c.drawString(58, 76, "experimentell erproben und optimieren (Digitale Zusatzaufgabe: S. 18).")

    c.setFont(fonts["Mono"], 6.5)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawString(40, 18, "INFO_NRW_7_8_K01_010_029.indd   19   14.10.2025   09:42:16")
    c.showPage()
    c.save()
    return meta_entries


def build_sek2_mathematik_analysis_pdf(
    pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Document 11: Sekundarstufe II (EF / Q1) — Mathematik: Analysis (2 pages, pp. 50–51).
    Physical format: B5-Breitformat (195 x 260 mm = 552.76 x 737.01 pt).
    Tests:
      - B5-wide page dimensions
      - Polynomial analysis, limits, derivatives, and definite integrals in display/inline math
      - Function plot with extrema H/T, inflection point W, and shaded integral area (Abb. 2.1)
      - Merksatz box, Example box, characteristic table (Tabelle 2.1), and square difficulty icons (□, ◩, ■)
    """
    pw, ph = B5_WIDE_SIZE
    c = canvas.Canvas(pdf_path, pagesize=B5_WIDE_SIZE)
    meta_entries: List[Dict[str, Any]] = []

    # ==================== PAGE 50 ====================
    c.setStrokeColor(colors.HexColor("#0F172A"))
    c.setLineWidth(1.0)
    c.line(42, ph - 38, pw - 42, ph - 38)
    c.setFont(fonts["SansBold"], 8.4)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(42, ph - 30, "50   |   Kapitel 2: Ganzrationale Funktionen, Differential- und Integralrechnung")

    c.setFont(fonts["SansBold"], 13.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(42, ph - 62, "Kapitel 2: Analysis — Untersuchung ganzrationaler Funktionen")
    c.setFont(fonts["SansBold"], 11.2)
    c.setFillColor(colors.HexColor("#1D4ED8"))
    c.drawString(42, ph - 84, "2.1 Charakteristische Punkte, Ableitungsfunktion und Integralfläche")

    c.setFont(fonts["Serif"], 9.1)
    c.setFillColor(colors.black)
    p50_intro = [
        "Eine ganzrationale Funktion n-ten Grades besitzt die allgemeine Funktionsgleichung",
        "f(x) = a_n · x^n + a_{n-1} · x^{n-1} + ... + a_1 · x + a_0 mit a_n ≠ 0. Ihr globales",
        "Verhalten für betragsgroße Werte von x wird ausschließlich vom Leitkoeffizienten a_n und",
        "dem höchsten Exponenten n bestimmt. Mithilfe der ersten und zweiten Ableitungsfunktion",
        "f'(x) und f''(x) lassen sich lokale Extrempunkte sowie Wendepunkte exakt berechnen.",
    ]
    for idx, ln in enumerate(p50_intro):
        c.drawString(42, ph - 104 - idx * 13.5, ln)

    # Figure 2.1
    fx, fy, fw, fh = 42.0, ph - 375.0, 468.0, 190.0
    c.drawImage(figs["fig_ana_1"], fx, fy, width=fw, height=fh)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.black)
    c.drawString(42, fy - 14, "Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_ana_1",
            0,
            50,
            "figures/mathe_analysis_funktionsgraphen.png",
            "Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich",
            "Diagramm",
            fx,
            fy,
            fw,
            fh,
            880,
            360,
            page_w=pw,
            page_h=ph,
        )
    )

    # Merksatz Callout Box on Page 50
    c.setFillColor(colors.HexColor("#EFF6FF"))
    c.setStrokeColor(colors.HexColor("#1D4ED8"))
    c.roundRect(42, 62, pw - 84, 268, 8, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.4)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(54, 310, "Merksatz: Notwendige und hinreichende Kriterien der Differential- und Integralrechnung")
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.black)
    c.drawString(54, 290, "• Potenz- und Summenregel der Ableitung: Für f(x) = c · x^n gilt f'(x) = c · n · x^{n-1}.")
    c.drawString(54, 272, "• Notwendige Bedingung für lokale Extremstellen: f'(x_E) = 0 (waagerechte Tangente).")
    c.drawString(54, 254, "• Hinreichende Bedingung für lokale Extremstellen:")
    c.drawString(62, 239, "Gilt f'(x_E) = 0 und f''(x_E) < 0, so liegt bei x_E ein lokales Maximum (Hochpunkt H) vor.")
    c.drawString(62, 224, "Gilt f'(x_E) = 0 und f''(x_E) > 0, so liegt bei x_E ein lokales Minimum (Tiefpunkt T) vor.")
    c.drawString(54, 206, "• Notwendige und hinreichende Bedingung für Wendestellen (Krümmungswechsel):")
    c.drawString(62, 191, "Gilt f''(x_W) = 0 und f'''(x_W) ≠ 0, so besitzt der Graph bei W(x_W | f(x_W)) einen Wendepunkt.")
    c.drawString(54, 173, "• Hauptsatz der Differential- und Integralrechnung (Bestimmtes Integral):")
    c.drawString(62, 158, "Ist F(x) eine Stammfunktion von f(x) mit F'(x) = f(x), so gilt auf dem Intervall [a; b]:")
    c.drawString(62, 143, "∫_a^b f(x) dx = [F(x)]_a^b = F(b) - F(a).")
    c.drawString(54, 125, "• Symmetrieverhalten ganzrationaler Funktionen:")
    c.drawString(62, 110, "Nur gerade Exponenten (f(-x) = f(x)): Achsensymmetrie zur y-Achse.")
    c.drawString(62, 95, "Nur ungerade Exponenten (f(-x) = -f(x)): Punktsymmetrie zum Koordinatenursprung O(0 | 0).")
    c.drawString(54, 77, "• Tangentensteigung m_t in einem Kurvenpunkt P(x_0 | f(x_0)): t(x) = f'(x_0) · (x - x_0) + f(x_0).")
    c.showPage()

    # ==================== PAGE 51 ====================
    c.setStrokeColor(colors.HexColor("#0F172A"))
    c.setLineWidth(1.0)
    c.line(42, ph - 38, pw - 42, ph - 38)
    c.setFont(fonts["SansBold"], 8.4)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(42, ph - 30, "2.1 Charakteristische Punkte, Ableitungsfunktion und Integralfläche   |   51")

    # Table 2.1
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(42, ph - 62, "Tabelle 2.1: Charakteristische Punkte von f(x) = 0,25 x³ - 1,5 x² + 2 x + 1")
    c.line(42, ph - 68, pw - 42, ph - 68)
    tab21_rows = [
        ("Merkmal / Punkt", "x-Wert", "Funktionswert f(x)", "Ableitungswerte & Begründung"),
        ("y-Achsenabschnitt S_y", "x = 0", "f(0) = 1,00", "f'(0) = 2,00 (steigend)"),
        ("Hochpunkt H (Maximum)", "x_H ≈ 0,85", "f(x_H) ≈ 1,77", "f'(x_H) = 0 und f''(x_H) ≈ -1,73 < 0"),
        ("Wendepunkt W", "x_W = 2,00", "f(2) = 1,00", "f''(2) = 0 und f'''(2) = 1,50 ≠ 0"),
        ("Tiefpunkt T (Minimum)", "x_T ≈ 3,15", "f(x_T) ≈ 0,23", "f'(x_T) = 0 und f''(x_T) ≈ +1,73 > 0"),
        ("Randpunkt im Intervall", "x = 4,00", "f(4) = 1,00", "f'(4) = 2,00 (punktsymmetrisch zu W)"),
    ]
    t21_cols = [42, 178, 268, 368]
    for r_i, r_vals in enumerate(tab21_rows):
        ry = ph - 84 - r_i * 18
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.1 if r_i == 0 else 8.4)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(t21_cols[c_i], ry, val)
    c.line(42, ph - 180, pw - 42, ph - 180)

    # Worked Example Callout Box
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.setStrokeColor(colors.HexColor("#475569"))
    c.roundRect(42, ph - 325, pw - 84, 130, 7, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(54, ph - 213, "Tipp: Musterlösung zur Berechnung des bestimmten Integrals auf [0; 4]")
    c.setFont(fonts["Sans"], 8.4)
    c.setFillColor(colors.black)
    c.drawString(54, ph - 231, "• Gegeben ist f(x) = 0,25 x³ - 1,5 x² + 2 x + 1 mit den Ableitungen f'(x) = 0,75 x² - 3 x + 2")
    c.drawString(62, ph - 245, "und f''(x) = 1,5 x - 3. Da f(x) > 0 für alle x ∈ [0; 4] gilt, liegt der Graph vollständig über der x-Achse.")
    c.drawString(54, ph - 263, "• Bildung einer Stammfunktion F(x): F(x) = (1/16) x⁴ - 0,5 x³ + x² + x.")
    c.drawString(54, ph - 281, "• Einsetzen der Integrationsgrenzen a = 0 und b = 4 nach dem Hauptsatz:")
    c.drawString(62, ph - 295, "A = ∫_0^4 f(x) dx = F(4) - F(0) = (16 - 32 + 16 + 4) - 0 = 4 Flächeneinheiten (FE).")
    c.drawString(54, ph - 313, "• Kontrolle durch Punktsymmetrie zu W(2 | 1): Das Rechteck der Breite 4 und Höhe 1 hat genau A = 4 FE.")

    # Differentiated Exercises (Aufgabe 1 □, Aufgabe 2 ◩, Aufgabe 3 ■)
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(42, ph - 352, "Aufgabe 1 □: Ableitungsfunktionen und Steigung bestimmen")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(42, ph - 368, "Bilden Sie zu den folgenden ganzrationalen Funktionen jeweils die erste und zweite Ableitung")
    c.drawString(42, ph - 381, "und berechnen Sie die Steigung des Graphen an der Stelle x_0 = 2:")
    c.drawString(52, ph - 396, "a) g(x) = x³ - 6 x² + 9 x - 2")
    c.drawString(52, ph - 410, "b) h(x) = -0,5 x⁴ + 3 x² - 4")
    c.drawString(52, ph - 424, "c) k(x) = 2 x³ + 4 x - 7")

    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(42, ph - 448, "Aufgabe 2 ◩: Vollständige Kurvendiskussion und Wendetangente")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(42, ph - 464, "Gegeben ist die Funktion f(x) = x³ - 3 x² - 9 x + 11. Bestimmen Sie rechnerisch die")
    c.drawString(42, ph - 477, "Koordinaten aller lokalen Extrempunkte sowie des Wendepunkts W. Stellen Sie anschließend")
    c.drawString(42, ph - 490, "die Gleichung der Wendetangente t_W(x) auf und prüfen Sie die Symmetrie zum Wendepunkt.")

    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#1E3A8A"))
    c.drawString(42, ph - 514, "Aufgabe 3 ■: Steckbriefaufgabe und Flächeninhalt zwischen zwei Graphen")
    c.setFont(fonts["Sans"], 8.6)
    c.setFillColor(colors.black)
    c.drawString(42, ph - 530, "Der Graph einer ganzrationalen Funktion 3. Grades verläuft durch den Ursprung O(0 | 0),")
    c.drawString(42, ph - 543, "besitzt im Punkt W(2 | 4) einen Wendepunkt und hat dort die Steigung m = -3.")
    c.drawString(52, ph - 558, "a) Stellen Sie das lineare Gleichungssystem auf und weisen Sie nach, dass p(x) = 0,5 x³ - 3 x² + 3 x + 0")
    c.drawString(64, ph - 571, "bzw. mit angepasstem Koeffizienten die Bedingungen erfüllt.")
    c.drawString(52, ph - 586, "b) Berechnen Sie den Inhalt der Fläche, die der Graph von f(x) aus Abb. 2.1 mit der")
    c.drawString(64, ph - 599, "Wendetangente und der y-Achse im ersten Quadranten einschließt.")
    c.drawString(42, ph - 620, "Hinweis zur Selbstkontrolle: Nutzen Sie für Teilaufgabe b) die Differenzfunktion d(x) = f(x) - t_W(x)")
    c.drawString(42, ph - 633, "und bestimmen Sie vor der Integration die Schnittstellen im Intervall [0; 4].")
    c.showPage()
    c.save()
    return meta_entries


def build_grundschule_lesebuch_doppelseite_pdf(
    pdf_path: str, fonts: Dict[str, str], figs: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Document 12: Grundschule (Klasse 2/3) — Deutsch / Lesebuch im Querformat-Doppelseiten-Spread (2 spreads: pp. 18/19 and 20/21).
    Physical format: Landscape Double-Page Spread (240 x 170 mm = 680.31 x 481.89 pt).
    Tests:
      - Landscape spread page dimensions (width > height)
      - FIBS Rule 1 double-page markers: ((18)) / ((19)) and ((20)) / ((21))
      - Literary story with line numbers (5, 10, 15), Wortbausteine callout box, comparison table, and reading tasks
    """
    pw, ph = SPREAD_LANDSCAPE_SIZE
    c = canvas.Canvas(pdf_path, pagesize=SPREAD_LANDSCAPE_SIZE)
    meta_entries: List[Dict[str, Any]] = []

    # ==================== SPREAD 1: ((18)) / ((19)) ====================
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.setLineWidth(1.0)
    c.line(36, ph - 32, pw - 36, ph - 32)
    c.setFont(fonts["SansBold"], 8.5)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 24, "Seite 18   |   Kapitel 3: Geschichten vom Meer und von der Küste   |   Seite 19")
    # Center book fold line indicator
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.setDash(3, 3)
    c.line(pw / 2.0, 28, pw / 2.0, ph - 38)
    c.setDash()

    c.setFont(fonts["SansBold"], 13.5)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(36, ph - 54, "Kapitel 3: Der kleine Leuchtturm auf der Felseninsel")
    c.setFont(fonts["SansBold"], 10.6)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 74, "3.1 Ein stürmischer Abend an der Nordsee")

    # Figure 3.1 across upper right / center of spread
    fx, fy, fw, fh = 360.0, ph - 215.0, 284.0, 108.0
    c.drawImage(figs["fig_les_1"], fx, fy, width=fw, height=fh)
    c.setFont(fonts["SansBold"], 8.2)
    c.setFillColor(colors.black)
    c.drawString(360, fy - 12, "Abb. 3.1: Der kleine Leuchtturm weist dem Fischerboot den Weg")
    meta_entries.append(
        compute_image_meta_entry(
            "fig_les_1",
            0,
            18,
            "figures/gs_lesebuch_kueste.png",
            "Abb. 3.1: Der kleine Leuchtturm weist dem Fischerboot den Weg",
            "Zeichnung",
            fx,
            fy,
            fw,
            fh,
            840,
            320,
            page_w=pw,
            page_h=ph,
        )
    )

    c.setFont(fonts["Serif"], 8.9)
    c.setFillColor(colors.black)
    story_lines = [
        "Auf einer runden Felseninsel mitten im Wattenmeer steht ein kleiner rot-weiß",
        "gestreifter Leuchtturm. Jeden Abend, sobald die Sonne hinter dem Horizont",
        "versinkt, steigt Leuchtturmwärter Piet die vierzig Holzstufen bis zur",
        "gläsernen Laternenkuppel hinauf und entzündet das helle Leuchtfeuer.",
        "5 Heute pfeift ein kräftiger Herbstwind über die Wellen. Dunkle Regenwolken",
        "ziehen über den Himmel, und die schäumende Gischt spritzt hoch an die",
        "Felsen. Draußen auf dem offenen Meer schaukelt das kleine Fischerboot",
        "\"Nordstern\" von Kapitänin Hanna. Durch den dichten Nebel kann Hanna",
        "die rettende Hafeneinfahrt kaum noch erkennen.",
        "10 Da blitzt plötzlich der goldgelbe Lichtstrahl des kleinen Leuchtturms",
        "dreimal kurz hintereinander durch die Dunkelheit: hell – dunkel – hell!",
        "15 Sofort weiß Kapitänin Hanna, wo die flachen Sandbänke liegen, und steuert",
        "ihr Boot sicher in das ruhige Hafenbecken der Insel.",
    ]
    for idx, ln in enumerate(story_lines):
        c.drawString(36, ph - 94 - idx * 14.0, ln)

    # Callout Box on Spread 1 bottom
    c.setFillColor(colors.HexColor("#F0F9FF"))
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.roundRect(36, 42, pw - 72, 138, 7, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 9.2)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(48, 162, "Wortbausteine: Zusammengesetzte Nomen rund um das Meer")
    c.setFont(fonts["Sans"], 8.3)
    c.setFillColor(colors.black)
    c.drawString(48, 144, "• Aus zwei Nomen kannst du ein neues zusammengesetztes Nomen bilden. Das zweite Wort")
    c.drawString(56, 130, "(Grundwort) bestimmt immer den Artikel (der, die oder das) des gesamten Wortes:")
    c.drawString(48, 114, "• das Leuchtfeuer + der Turm -> der Leuchtturm (Mehrzahl: die Leuchttürme).")
    c.drawString(48, 98, "• der Sturm + die Flut -> die Sturmflut; der Nebel + das Horn -> das Nebelhorn.")
    c.drawString(48, 82, "• der Hafen + die Einfahrt -> die Hafeneinfahrt; der Sand + die Bank -> die Sandbank.")
    c.drawString(48, 66, "• Merke: Manchmal steht zwischen beiden Wörtern ein Fugen-s oder Fugen-n (das Schiffshorn).")
    c.showPage()

    # ==================== SPREAD 2: ((20)) / ((21)) ====================
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.setLineWidth(1.0)
    c.line(36, ph - 32, pw - 36, ph - 32)
    c.setFont(fonts["SansBold"], 8.5)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 24, "Seite 20   |   3.1 Ein stürmischer Abend an der Nordsee   |   Seite 21")
    # Table 3.1 with full cell grid borders
    c.setFont(fonts["SansBold"], 9.8)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 54, "Tabelle 3.1: Wer hat welche Aufgabe in der Geschichte?")
    tab31_rows = [
        ("Figur / Gegenstand", "Ort in der Geschichte", "Wichtige Aufgabe im Herbststurm"),
        ("Leuchtturmwärter Piet", "Laternenkuppel auf dem Turm", "Entzündet und überwacht das Leuchtfeuer"),
        ("Kleiner Leuchtturm", "Felseninsel im Wattenmeer", "Sendet dreimal kurz das Lichtsignal aus"),
        ("Kapitänin Hanna", "Fischerboot \"Nordstern\"", "Hält Ausschau und lenkt das Boot um die Sandbank"),
    ]
    t31_x = [36, 204, 388, pw - 36]
    t31_top = ph - 62
    row_h = 20
    # Header background fill
    c.setFillColor(colors.HexColor("#E0F2FE"))
    c.rect(t31_x[0], t31_top - row_h, t31_x[-1] - t31_x[0], row_h, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#0284C7"))
    c.setLineWidth(0.8)
    for r_i in range(len(tab31_rows) + 1):
        ry_line = t31_top - r_i * row_h
        c.line(t31_x[0], ry_line, t31_x[-1], ry_line)
    for cx_line in t31_x:
        c.line(cx_line, t31_top - len(tab31_rows) * row_h, cx_line, t31_top)
    for r_i, r_vals in enumerate(tab31_rows):
        ry = t31_top - (r_i + 1) * row_h + 6
        c.setFont(fonts["SansBold"] if r_i == 0 else fonts["Sans"], 8.3 if r_i == 0 else 8.5)
        c.setFillColor(colors.black)
        for c_i, val in enumerate(r_vals):
            c.drawString(t31_x[c_i] + 6, ry, val)

    # Reading Tasks on Spread 2
    c.setFont(fonts["SansBold"], 9.6)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 166, "Aufgabe 1: Textstellen mit Zeilenzahlen finden")
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.black)
    c.drawString(36, ph - 181, "Lies die Geschichte auf der Doppelseite 18/19 noch einmal genau durch und beantworte:")
    c.drawString(48, ph - 195, "a) Wie viele Holzstufen muss Leuchtturmwärter Piet jeden Abend hinaufsteigen?")
    c.drawString(48, ph - 209, "b) Warum kann Kapitänin Hanna die Hafeneinfahrt im Sturm kaum erkennen (Zeile 5 bis 9)?")
    c.drawString(48, ph - 223, "c) Woran erkennt Hanna das besondere Lichtsignal ihres Heimatleuchtturms (Zeile 10 bis 15)?")

    c.setFont(fonts["SansBold"], 9.6)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 247, "Aufgabe 2: Zusammengesetzte Nomen bilden und Artikel bestimmen")
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.black)
    c.drawString(36, ph - 262, "Bilde aus den Wortbausteinen zusammengesetzte Nomen mit dem richtigen Artikel:")
    c.drawString(48, ph - 276, "a) das Meer + das Wasser -> ____")
    c.drawString(48, ph - 290, "b) der Herbst + der Wind -> ____")
    c.drawString(48, ph - 304, "c) das Holz + die Stufe -> ____")

    c.setFont(fonts["SansBold"], 9.6)
    c.setFillColor(colors.HexColor("#0369A1"))
    c.drawString(36, ph - 328, "Aufgabe 3: Eine eigene Fortsetzung schreiben")
    c.setFont(fonts["Sans"], 8.5)
    c.setFillColor(colors.black)
    c.drawString(36, ph - 343, "Stell dir vor, Kapitänin Hanna legt mit ihrem Boot im Hafen an und besucht Piet im Leuchtturm.")
    c.drawString(36, ph - 357, "Schreibe in dein Heft, worüber die beiden bei einer Tasse heißem Tee sprechen.")

    # Bottom Tip Box on Spread 2
    c.setFillColor(colors.HexColor("#FEFCE8"))
    c.setStrokeColor(colors.HexColor("#CA8A04"))
    c.roundRect(36, 38, pw - 72, 74, 6, fill=1, stroke=1)
    c.setFont(fonts["SansBold"], 8.8)
    c.setFillColor(colors.HexColor("#854D0E"))
    c.drawString(48, 94, "Tipp: So findest du Antworten schnell mit den Zeilenzahlen am Rand")
    c.setFont(fonts["Sans"], 8.2)
    c.setFillColor(colors.black)
    c.drawString(48, 78, "• Am linken Textrand siehst du in jeder fünften Zeile eine kleine Zahl (5, 10, 15).")
    c.drawString(48, 64, "• Fahre mit dem Finger von der genannten Zeilenzahl nach rechts in den Satz hinein.")
    c.drawString(48, 50, "• Unterstreiche wichtige Schlüsselwörter mit Bleistift, bevor du deine Antwort formulierst.")
    c.showPage()
    c.save()
    return meta_entries


def sanitize_openstax_history_cc0_map(fonts: Dict[str, str], cc0_map_path: str) -> None:
    """
    Replaces Page 2 (physical page 102) of `testdata/openstax_history_sample.pdf` so that
    `FIGURE 3.26` (which previously carried a third-party `CC BY NC-SA 4.0` attribution)
    is replaced with our 100% CC0 1.0 Public Domain trade-routes map (`cc0_map_path`)
    and pure CC0 1.0 / CC BY 4.0 attribution. Also regenerates `openstax_history_sample_scanned.pdf`.
    """
    import io
    import pypdfium2 as pdfium

    hist_pdf_path = os.path.join(TEST_DATA_DIR, "openstax_history_sample.pdf")
    hist_scan_path = os.path.join(TEST_DATA_DIR, "openstax_history_sample_scanned.pdf")
    if not os.path.exists(hist_pdf_path):
        return

    orig_doc = pdfium.PdfDocument(hist_pdf_path)
    if len(orig_doc) < 4:
        orig_doc.close()
        return

    # Check if Page 2 still contains 'NC-SA'
    p2_text = orig_doc[1].get_textpage().get_text_range()
    if "NC-SA" not in p2_text and "NC" not in p2_text:
        orig_doc.close()
        return

    # Extract Public Domain Figure 3.27 image from page 2 (index 1) so it is preserved faithfully
    fig327_tmp_path = os.path.join(FIGURES_DIR, "openstax_fig_3_27_pd.png")
    for obj in orig_doc[1].get_objects():
        if obj.type == 3:
            b = obj.get_bounds()
            if b[1] < 400:  # Figure 3.27 at y=[166, 389.6]
                pil_327 = obj.get_bitmap().to_pil()
                pil_327.save(fig327_tmp_path, "PNG")
                break

    # Build clean replacement page 102 (612 x 792 pt US Letter) in memory
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612.0, 792.0))
    c.setFont(fonts["Sans"], 8.0)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(50, 760, "102   3 • Early Civilizations and Urban Societies")

    # Draw CC0 Figure 3.26 at exact bounds [180.0, 554.4, 432.0, 734.4]
    c.drawImage(cc0_map_path, 180.0, 554.4, width=252.0, height=180.0)
    c.setFont(fonts["SansBold"], 8.2)
    c.setFillColor(colors.black)
    c.drawString(
        72.5,
        540.8,
        "FIGURE 3.26 Indus Valley Trade with Mesopotamia. From the work of archaeologists, we know that significant trade",
    )
    c.setFont(fonts["Sans"], 8.2)
    c.drawString(
        72.5,
        527.0,
        "took place between the inhabitants of the Indus River valley and their contemporaries in Mesopotamia. (credit:",
    )
    c.drawString(
        72.5,
        513.4,
        '"Indus-Mesopotamia Trade Routes Map", CC0 1.0 Public Domain; text: Rice University, OpenStax, under CC BY 4.0 license)',
    )

    c.setFont(fonts["Serif"], 9.3)
    p102_para1 = [
        "The influence of Mesopotamia on the Indus valley culture is evident in the use of seals. The Indus valley seals",
        "were inscribed with depictions of human figures and animals such as bulls and goats, likely totems for families",
        "or lineages, and brief inscriptions that likely indicate names, titles, or occupations. Merchants marked",
        "ownership of goods by making an impression of the seal on the soft clay that covered the mouth of the jar or",
        "other vessel that held the objects, or on clay tags attached to sacks of grain (Figure 3.27). A similar practice",
        "occurred in contemporary Mesopotamia, where the seal was in the shape of a cylinder that could be rolled to",
        "leave an impression. Archaeologists have found seals from the Indus valley in ancient Sumerian cities such as",
        "Ur.",
    ]
    for idx, ln in enumerate(p102_para1):
        c.drawString(72.3, 493.6 - idx * 13.5, ln)

    # Draw Public Domain Figure 3.27 at exact bounds [108.0, 166.0, 504.0, 389.6]
    if os.path.exists(fig327_tmp_path):
        c.drawImage(fig327_tmp_path, 108.0, 166.0, width=396.0, height=223.6)

    c.setFont(fonts["SansBold"], 8.2)
    c.drawString(
        72.5,
        150.0,
        "FIGURE 3.27 An Indus Valley Seal. On the left is a seal from the Indus valley civilization, and on the right is a",
    )
    c.setFont(fonts["Sans"], 8.2)
    c.drawString(
        72.5,
        136.5,
        "modern clay impression made from it. Such seals typically showed animals and a script that remains to be",
    )
    c.drawString(
        72.5,
        123.0,
        'deciphered. (credit: modification of work "Stamp seal and modern impression: unicorn and incense burner (?)" by',
    )
    c.drawString(72.5, 109.5, "Dodge Fund, 1949/The Metropolitan Museum of Art, Public Domain)")

    c.setFont(fonts["Serif"], 9.3)
    c.drawString(
        72.3,
        88.0,
        "The script that appears on many of the seals is unique to the people of the Indus valley civilization, and",
    )
    c.drawString(
        72.3,
        74.5,
        "scholars have yet to decipher it. It seems to consist of phonograms, signs for the sounds of syllables, and there",
    )
    c.drawString(
        72.3,
        61.0,
        "appear to be about four hundred such signs. Many speculate that the language written in this script may be",
    )
    c.setFont(fonts["Sans"], 8.0)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawString(72.2, 26.0, "Access for free at openstax.org")
    c.showPage()
    c.save()

    rep_doc = pdfium.PdfDocument(buf.getvalue())
    out_doc = pdfium.PdfDocument.new()
    out_doc.import_pages(orig_doc, [0])
    out_doc.import_pages(rep_doc, [0])
    out_doc.import_pages(orig_doc, [2, 3])
    orig_doc.close()
    rep_doc.close()
    out_doc.save(hist_pdf_path)
    out_doc.close()
    if os.path.exists(fig327_tmp_path):
        os.remove(fig327_tmp_path)

    generate_scanned_pdf(hist_pdf_path, hist_scan_path, seed=503)



# ---------------------------------------------------------------------------
# Realistic 300-DPI Scan Degradation Pipeline (pypdfium2 + Pillow)
# ---------------------------------------------------------------------------

def generate_scanned_pdf(digital_pdf_path: str, scanned_pdf_path: str, seed: int = 42) -> None:
    """
    Renders each page of `digital_pdf_path` at 300 DPI via pypdfium2 and applies
    realistic textbook scan artifacts (warm paper tint, deterministic subtle skew,
    slight optical blur, and subtle sensor grain) before saving as a multi-page PDF.
    """
    import pypdfium2

    rng = random.Random(seed)
    pdf = pypdfium2.PdfDocument(digital_pdf_path)
    scanned_pages: List[Image.Image] = []

    for page_idx, page in enumerate(pdf):
        # 300 DPI: 300 / 72 = 4.1666667
        pil_img = page.render(scale=300.0 / 72.0).to_pil().convert("RGB")
        w, h = pil_img.size

        # 1. Warm paper tint (slight cream/ivory paper background)
        r_ch, g_ch, b_ch = pil_img.split()
        r_ch = r_ch.point(lambda v: min(255, int(v * 0.992)))
        g_ch = g_ch.point(lambda v: min(255, int(v * 0.982)))
        b_ch = b_ch.point(lambda v: min(255, int(v * 0.958)))
        tinted = Image.merge("RGB", (r_ch, g_ch, b_ch))

        # 2. Subtle alternating page skew (-0.35° / +0.30°)
        angle = -0.35 if page_idx % 2 == 0 else 0.30
        rotated = tinted.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(248, 245, 238))

        # 3. Deterministic low-amplitude paper grain & slight optical softening
        grain = Image.new("L", (w // 4, h // 4))
        grain_bytes = bytes(rng.randint(244, 255) for _ in range((w // 4) * (h // 4)))
        grain.frombytes(grain_bytes)
        grain_full = grain.resize((w, h), resample=Image.Resampling.BILINEAR).convert("RGB")
        blended = Image.blend(rotated, grain_full, alpha=0.05)
        softened = blended.filter(ImageFilter.GaussianBlur(radius=0.35))
        final_page = ImageEnhance.Contrast(softened).enhance(1.04)
        scanned_pages.append(final_page)

    if scanned_pages:
        scanned_pages[0].save(
            scanned_pdf_path,
            save_all=True,
            append_images=scanned_pages[1:],
            resolution=300.0,
        )


# ---------------------------------------------------------------------------
# Golden Ground Truth Generators (Raw & FIBS Übertragungsregeln 09/2025)
# ---------------------------------------------------------------------------

def get_golden_ground_truths() -> Dict[str, Tuple[str, str]]:
    """Returns (raw_md, uebertragungsregeln_09_2025_md) for each of the 8 single-subject schoolbooks."""

    # -------------------- 1. GRUNDSCHULE MATHEMATIK --------------------
    gs_mathe_raw = """((14))

# Mathematik – Klasse 3

## Kapitel 1: Große Zahlen und Orientierung bis 1000

Auf unserer Zahlenreise entdecken wir Hunderter, Zehner und Einer. Schau dir den Zahlenstrahl genau an und ergänze die fehlenden Zielzahlen in den Kästchen.

![Abb. 1.1: Sprünge am Zahlenstrahl bis 1000](figures/gs_zahlenstrahl_1000.png)

Abb. 1.1: Sprünge am Zahlenstrahl bis 1000

### Aufgabe 1 □: Kopfrechnen im Tausenderraum

Rechnet abwechselnd. Tragt die Ergebnisse auf den Linien ein:

a) 150 + 250 = ____    f) 275 + 125 = ____
b) 320 + 180 = ____    g) 640 - 190 = ____
c) 460 + 240 = ____    h) 510 + 390 = ____
d) 780 - 350 = ____    i) 850 - 270 = ____
e) 900 - 420 = ____    j) 999 - 333 = ____

### Aufgabe 2 ◩: Hunderter, Zehner und Einer zerlegen

Zerlege die Zahlen in Hunderter (H), Zehner (Z) und Einer (E):
a) 483 = 4 H + ____ Z + ____ E
b) 709 = ____ H + 0 Z + ____ E
c) ____ = 9 H + 5 Z + 2 E

**Tipp vom Eulen-Detektiv:**
Achte auf die Null als Platzhalter! Bei 709 steht an der Zehnerstelle eine 0: 7 H + 0 Z + 9 E.

**Stellenwerttafel und Nachbarhunderter bestimmen:**
Bestimme zu jeder Zahl den Vorgänger, den Nachfolger sowie die beiden Nachbarhunderter:

| Zahl | Hunderter (H) | Zehner (Z) | Einer (E) | Vorgänger | Nachfolger |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 358 | 3 | 5 | 8 | 357 | 359 |
| 640 | 6 | ____ | 0 | ____ | 641 |
| 809 | ____ | 0 | 9 | 808 | ____ |

**Merksatz: Tausenderbündelung**
Zehn Einer bilden einen Zehner (10 E = 1 Z). Zehn Zehner bilden einen Hunderter (10 Z = 1 H). Zehn Hunderter ergeben zusammen genau einen Tausender (10 H = 1 T = 1000). In der Stellenwerttafel steht jede Ziffer genau für ihren Stellenwert (T – H – Z – E).

((15))

## Rechenmauern und Zahlenhäuser knacken

![Abb. 1.2: Rechenmauer und Rechendreieck mit Lücken](figures/gs_rechenmauer_dreieck.png)

Abb. 1.2: Rechenmauer und Rechendreieck mit Lücken

### Aufgabe 3 ◩: Fehlende Steine und Außenfelder berechnen

In der Rechenmauer gilt: Zwei Nachbarsteine unten ergeben zusammen den Stein darüber. Im Rechendreieck werden jeweils zwei Innenzahlen miteinander multipliziert.
a) Rechenmauer rechts unten: 850 - 365 = ____ (mittlerer Stein rechts), also 240 + ____ = 485.
b) Rechendreieck rechts: 8 * 5 = ____ und unten: 6 * 5 = ____.

### Aufgabe 4 ■: Sachaufgabe – Ausflug ins Naturkundemuseum

Die vier dritten Klassen der Lindenschule besuchen das Naturkundemuseum. Insgesamt fahren 96 Kinder und 8 Lehrkräfte mit. Der Eintritt kostet für jedes Kind 4 Euro und für Erwachsene 7 Euro.
Rechnung Kinder: ____ Euro
Rechnung Erwachsene: ____ Euro
Gesamtkosten: ____ Euro
Antwort: Die Schule bezahlt insgesamt ____ Euro.

**Zahlenfolgen und Regeldetektive:**
Erkenne die Rechenregel und setze die Zahlenfolgen um jeweils zwei Schritte fort:
a) 120, 230, 340, 450, ____, ____ (Regel: immer + 110)
b) 950, 825, 700, 575, ____, ____ (Regel: immer - 125)
c) 105, 215, 335, 465, ____, ____ (Regel: + 110, + 120, + 130, ...)

**Merksatz: Sachaufgaben in 3 Schritten lösen (Frage – Rechnung – Antwort)**
- 1. Schritt (Frage & Angaben): Lies den Text genau und unterstreiche alle wichtigen Zahlen.
- 2. Schritt (Rechnung): Zerlege schwierige Aufgaben in Teilrechnungen (z. B. Kinder und Erwachsene getrennt berechnen) und addiere anschließend die Teilergebnisse.
- 3. Schritt (Antwort & Überschlag): Prüfe dein Ergebnis mit einem Überschlag (100 · 4 Euro = 400 Euro) und schreibe einen vollständigen Antwortsatz mit der passenden Einheit.
- Zusatzfrage für Schnelle: Für die Busfahrt bezahlt die Schule pauschal 260 Euro. Wie viel kostet der Ausflug insgesamt mit Busfahrt? Rechnung: 440 Euro + 260 Euro = ____ Euro.

((16))

## Kapitel 2: Uhrzeiten ablesen, Zeitspannen und Fahrpläne berechnen

![Abb. 1.3: Drei analoge Uhren im Tagesverlauf](figures/gs_analoge_uhren.png)

Abb. 1.3: Drei analoge Uhren im Tagesverlauf

### Aufgabe 5 □: Uhrzeiten und Zeitspannen bestimmen

Trage die passenden digitalen Uhrzeiten ein und berechne die Dauer:
a) Uhr A zeigt ____ Uhr. Bis zum Unterrichtsbeginn um 08:30 Uhr vergehen noch ____ Minuten.
b) Uhr B zeigt ____ Uhr. Uhr C zeigt am Nachmittag ____ Uhr.

### Aufgabe 6 ◩: Fahrplan-Rätsel – Mit dem Schulbus zum Hallenbad

Berechne die fehlende Ankunftszeit in der Fahrplantabelle:

| Haltestelle | Buslinie 12 (Früh) | Buslinie 12 (Spät) | Fahrtdauer ab Schule |
| :--- | :--- | :--- | :--- |
| Lindenschule (Abfahrt) | 08:15 Uhr | 09:45 Uhr | 0 Minuten |
| Rathausplatz | 08:27 Uhr | 09:57 Uhr | 12 Minuten |
| Hallenbad (Ankunft) | 08:40 Uhr | ____ Uhr | 25 Minuten |

### Aufgabe 7 ■: Sachaufgaben zu Zeitspannen im Schulalltag

a) Das Schwimmtraining beginnt um 08:50 Uhr und dauert 1 Stunde und 15 Minuten. Ende: ____ Uhr.
b) Die Projektwoche dauert 5 Schultage zu je 4 Stunden. Das sind insgesamt ____ Stunden.
c) Rechne in Minuten um: 1 h 35 min = ____ min | 2 h 20 min = ____ min | 150 min = ____ h ____ min.

**Merksatz: Zeitpunkt und Zeitspanne umrechnen**
- Zeitpunkt (Uhrzeit): Gibt genau an, wie spät es auf der Uhr ist (z. B. 08:15 Uhr oder 15:55 Uhr).
- Zeitspanne (Dauer): Gibt an, wie lange ein Vorgang dauert (z. B. 25 Minuten oder 2 Stunden).
- Umrechnungszahlen für die Zeit: 1 Tag (d) = 24 Stunden (h) | 1 Stunde (h) = 60 Minuten (min) | 1 Minute (min) = 60 Sekunden (s).
- Rechentipp (Ergänzen bis zur vollen Stunde): Berechne zuerst die Minuten bis zur nächsten vollen Stunde (von 07:45 Uhr bis 08:00 Uhr sind es 15 min) und zähle dann die weiteren Minuten dazu (von 08:00 Uhr bis 08:30 Uhr sind es 30 min; zusammen also 15 min + 30 min = 45 min).
- Achtung: Eine Viertelstunde hat 15 Minuten, eine halbe Stunde 30 Minuten, eine Dreiviertelstunde 45 Minuten.
"""

    gs_mathe_ueb = """((14))

# Mathematik – Klasse 3

## Kapitel 1: Große Zahlen und Orientierung bis 1000

Auf unserer Zahlenreise entdecken wir Hunderter, Zehner und Einer. Schau dir den Zahlenstrahl genau an und ergänze die fehlenden Zielzahlen in den Kästchen.

#### Abb. 1.1: Sprünge am Zahlenstrahl bis 1000

<Bild> Zahlenstrahl:
Beschreibung mit Bildtext: Zahlenstrahl von 0 bis 1000 mit Hundertermarkierungen bei 0, 200, 500, 800 und 1000 sowie einer Legende mit Dienes-Material (1 H = 100, 1 Z = 10, 1 E = 1). Von der Startzahl 150 führt ein roter Sprungbogen mit der Beschriftung + 250 zu einem leeren Kästchen [ ? ] und von dort ein grüner Sprungbogen mit der Beschriftung + 350 zu einem zweiten leeren Kästchen [ ? ].
</Bild>

### Aufgabe 1: Kopfrechnen im Tausenderraum
[leicht] [Partnerarbeit]

Rechnet abwechselnd. Tragt die Ergebnisse auf den Linien ein:
a) 150 + 250 = _..._
b) 320 + 180 = _..._
c) 460 + 240 = _..._
d) 780 - 350 = _..._
e) 900 - 420 = _..._
f) 275 + 125 = _..._
g) 640 - 190 = _..._
h) 510 + 390 = _..._
i) 850 - 270 = _..._
j) 999 - 333 = _..._

### Aufgabe 2: Hunderter, Zehner und Einer zerlegen
[mittel]

Zerlege die Zahlen in Hunderter (H), Zehner (Z) und Einer (E):
a) 483 = 4 H + _..._ Z + _..._ E
b) 709 = _..._ H + 0 Z + _..._ E
c) _..._ = 9 H + 5 Z + 2 E

<Rahmen>
_Tipp vom Eulen-Detektiv:_
Achte auf die Null als Platzhalter! Bei 709 steht an der Zehnerstelle eine 0: 7 H + 0 Z + 9 E.
</Rahmen>

_Stellenwerttafel und Nachbarhunderter bestimmen:_
Bestimme zu jeder Zahl den Vorgänger, den Nachfolger sowie die beiden Nachbarhunderter:

<Tabelle>
Zahl\tHunderter (H)\tZehner (Z)\tEiner (E)\tVorgänger\tNachfolger
358\t3\t5\t8\t357\t359
640\t6\t_..._\t0\t_..._\t641
809\t_..._\t0\t9\t808\t_..._
</Tabelle>

<Rahmen>
_Merksatz: Tausenderbündelung_
Zehn Einer bilden einen Zehner (10 E = 1 Z). Zehn Zehner bilden einen Hunderter (10 Z = 1 H). Zehn Hunderter ergeben zusammen genau einen Tausender (10 H = 1 T = 1000). In der Stellenwerttafel steht jede Ziffer genau für ihren Stellenwert (T – H – Z – E).
</Rahmen>

((15))

## Rechenmauern und Zahlenhäuser knacken

#### Abb. 1.2: Rechenmauer und Rechendreieck mit Lücken

<Bild> Rechenmauer und Rechendreieck:
Beschreibung mit Bildtext: Links eine dreistufige Rechenmauer (Addition) mit der Basisreihe 125, 240, _..._, der mittleren Reihe 365, _..._ und dem Zielstein 850 an der Spitze. Rechts ein Rechendreieck (Multiplikation) mit den drei Innenzahlen 6, 8 und 5 sowie dem linken Außenfeld 48 und zwei leeren Außenfeldern _..._ rechts und unten.
</Bild>

### Aufgabe 3: Fehlende Steine und Außenfelder berechnen
[mittel] [Schere und Kleber]

In der Rechenmauer gilt: Zwei Nachbarsteine unten ergeben zusammen den Stein darüber. Im Rechendreieck werden jeweils zwei Innenzahlen miteinander multipliziert.
a) Rechenmauer rechts unten: 850 - 365 = _..._ (mittlerer Stein rechts), also 240 + _..._ = 485.
b) Rechendreieck rechts: 8 * 5 = _..._ und unten: 6 * 5 = _..._.

### Aufgabe 4: Sachaufgabe – Ausflug ins Naturkundemuseum
[schwer]

Die vier dritten Klassen der Lindenschule besuchen das Naturkundemuseum. Insgesamt fahren 96 Kinder und 8 Lehrkräfte mit. Der Eintritt kostet für jedes Kind 4 Euro und für Erwachsene 7 Euro.
Rechnung Kinder: _..._ Euro
Rechnung Erwachsene: _..._ Euro
Gesamtkosten: _..._ Euro
Antwort: Die Schule bezahlt insgesamt _..._ Euro.

_Zahlenfolgen und Regeldetektive:_
Erkenne die Rechenregel und setze die Zahlenfolgen um jeweils zwei Schritte fort:
a) 120, 230, 340, 450, _..._, _..._ (Regel: immer + 110)
b) 950, 825, 700, 575, _..._, _..._ (Regel: immer - 125)
c) 105, 215, 335, 465, _..._, _..._ (Regel: + 110, + 120, + 130, ...)

<Rahmen>
_Merksatz: Sachaufgaben in 3 Schritten lösen (Frage – Rechnung – Antwort)_
-\t1. Schritt (Frage & Angaben): Lies den Text genau und unterstreiche alle wichtigen Zahlen.
-\t2. Schritt (Rechnung): Zerlege schwierige Aufgaben in Teilrechnungen (z. B. Kinder und Erwachsene getrennt berechnen) und addiere anschließend die Teilergebnisse.
-\t3. Schritt (Antwort & Überschlag): Prüfe dein Ergebnis mit einem Überschlag (100 · 4 Euro = 400 Euro) und schreibe einen vollständigen Antwortsatz mit der passenden Einheit.
-\tZusatzfrage für Schnelle: Für die Busfahrt bezahlt die Schule pauschal 260 Euro. Wie viel kostet der Ausflug insgesamt mit Busfahrt? Rechnung: 440 Euro + 260 Euro = _..._ Euro.
</Rahmen>

((16))

## Kapitel 2: Uhrzeiten ablesen, Zeitspannen und Fahrpläne berechnen

#### Abb. 1.3: Drei analoge Uhren im Tagesverlauf

<Bild> Uhren-Darstellung:
Beschreibung mit Bildtext: Drei analoge Zifferblätter von 1 bis 12 nebeneinander. Uhr A (Morgen): Stundenzeiger kurz vor 8, Minutenzeiger auf 9 (07:45 Uhr). Uhr B (Vormittag): Stundenzeiger kurz nach 11, Minutenzeiger auf 4 (11:20 Uhr). Uhr C (Nachmittag): Stundenzeiger kurz vor 4, Minutenzeiger auf 11 (15:55 Uhr).
</Bild>

### Aufgabe 5: Uhrzeiten und Zeitspannen bestimmen
[leicht]

Trage die passenden digitalen Uhrzeiten ein und berechne die Dauer:
a) Uhr A zeigt _..._ Uhr. Bis zum Unterrichtsbeginn um 08:30 Uhr vergehen noch _..._ Minuten.
b) Uhr B zeigt _..._ Uhr. Uhr C zeigt am Nachmittag _..._ Uhr.

### Aufgabe 6: Fahrplan-Rätsel – Mit dem Schulbus zum Hallenbad
[mittel]

Berechne die fehlende Ankunftszeit in der Fahrplantabelle:

<Tabelle>
Haltestelle\tBuslinie 12 (Früh)\tBuslinie 12 (Spät)\tFahrtdauer ab Schule
Lindenschule (Abfahrt)\t08:15 Uhr\t09:45 Uhr\t0 Minuten
Rathausplatz\t08:27 Uhr\t09:57 Uhr\t12 Minuten
Hallenbad (Ankunft)\t08:40 Uhr\t_..._ Uhr\t25 Minuten
</Tabelle>

### Aufgabe 7: Sachaufgaben zu Zeitspannen im Schulalltag
[schwer]

a) Das Schwimmtraining beginnt um 08:50 Uhr und dauert 1 Stunde und 15 Minuten. Ende: _..._ Uhr.
b) Die Projektwoche dauert 5 Schultage zu je 4 Stunden. Das sind insgesamt _..._ Stunden.
c) Rechne in Minuten um: 1 h 35 min = _..._ min | 2 h 20 min = _..._ min | 150 min = _..._ h _..._ min.

<Rahmen>
_Merksatz: Zeitpunkt und Zeitspanne umrechnen_
-\t_Zeitpunkt (Uhrzeit):_ Gibt genau an, wie spät es auf der Uhr ist (z. B. 08:15 Uhr oder 15:55 Uhr).
-\t_Zeitspanne (Dauer):_ Gibt an, wie lange ein Vorgang dauert (z. B. 25 Minuten oder 2 Stunden).
-\t_Umrechnungszahlen für die Zeit:_ 1 Tag (d) = 24 Stunden (h) | 1 Stunde (h) = 60 Minuten (min) | 1 Minute (min) = 60 Sekunden (s).
-\t_Rechentipp (Ergänzen bis zur vollen Stunde):_ Berechne zuerst die Minuten bis zur nächsten vollen Stunde (von 07:45 Uhr bis 08:00 Uhr sind es 15 min) und zähle dann die weiteren Minuten dazu (von 08:00 Uhr bis 08:30 Uhr sind es 30 min; zusammen also 15 min + 30 min = 45 min).
-\t_Achtung:_ Eine Viertelstunde hat 15 Minuten, eine halbe Stunde 30 Minuten, eine Dreiviertelstunde 45 Minuten.
</Rahmen>
"""

    # -------------------- 2. GRUNDSCHULE SACHKUNDE --------------------
    gs_sachkunde_raw = """((24))

# Sachunterricht – Klasse 3

## Kapitel 2: Lebensraum Streuobstwiese und das Bienenjahr

Auf einer Streuobstwiese wachsen hochstämmige Apfel-, Birnen- und Kirschbäume unterschiedlichen Alters. Zwischen den Bäumen blühen im Frühling Löwenzahn, Wiesensalbei und Margeriten. Hier finden Honigbienen, Wildbienen, Schmetterlinge, Singvögel und Igel das ganze Jahr über Nahrung und Schutz.

### Aufgabe 1: Lückentext – Das Bienenjahr auf der Streuobstwiese

Wortspeicher: Blüten · Nektar · Bestäubung · Früchte · Winterruhe

Setze die passenden Wörter aus dem Wortspeicher in die Lücken ein:
Im Frühling öffnen die Apfelbäume ihre duftenden ____. Die Honigbienen sammeln dort süßen ____ und tragen Blütenstaub von Baum zu Baum. Durch diese wichtige ____ wachsen im Sommer saftige ____. Im kalten Dezember hält das Bienenvolk ____.

**Sachwissen kompakt: Das Honigbienen-Volk im Jahreslauf**
- Königin, Arbeiterinnen und Drohnen: In einem einzigen Bienenstock leben im Sommer bis zu 50.000 weibliche Arbeitsbienen, einige hundert männliche Drohnen und eine einzige Bienenkönigin.
- Bestäubungsleistung: Für ein einziges Glas Honig (500 g) müssen die Sammlerinnen rund 40.000-mal ausfliegen und dabei Millionen einzelner Obst- und Wiesenblüten besuchen.
- Verständigung durch den Schwänzeltanz: Kehrt eine Kundschafterin zur Wabe zurück, zeigt sie den anderen Bienen durch Richtung und Tempo ihres Tanzes genau den Weg zur Futterquelle.
- Überwinterung: Im Winter bildet das Volk eine enge Wintertraube und hält die Temperatur im Inneren durch Muskelzittern konstant bei etwa 25 °C bis 30 °C.

### Aufgabe 2: Wetter- und Naturprotokoll ergänzen

Vervollständige die Beobachtungstabelle unserer Schulwiese im Jahresverlauf:

| Monat | Mittlere Temperatur | Sonnenstunden/Tag | Beobachtung auf der Wiese |
| :--- | :--- | :--- | :--- |
| April | 10 °C | 6 Stunden | Apfelblüte beginnt, Hummeln fliegen |
| Juli | 21 °C | ____ Stunden | Reife Kirschen, viele Kohlmeisen |
| Oktober | ____ °C | 4 Stunden | Apfelernte und bunter Laubfall |

**Forscher-Tipp: Wildbienen und Nistplätze auf dem Schulhof schützen**
- Neben der Honigbiene leben in Deutschland über 560 verschiedene Wildbienenarten (z. B. die Rote Mauerbiene und die Erdhummel). Die meisten Wildbienen bilden keinen Staat, sondern legen ihre Brutzellen einzeln in hohlen Pflanzenstängeln, im Totholz oder im sandigen Boden an.
- Wenn eine Wiese erst spät im Juni gemäht wird, können Wiesenblumen aussamen und bieten Insekten, Raupen und Wiesenvögeln bis in den Herbst hinein reichlich Nahrung.
- Beobachte am Insektenhotel immer ruhig aus 1 Meter Abstand und verschließe niemals die Röhren.

((25))

## Nahrungsbeziehungen und Naturbeobachtung auf der Wiese

![Abb. 2.1: Nahrungskette auf der Streuobstwiese](figures/gs_nahrungskette_wiese.png)

Abb. 2.1: Nahrungskette auf der Streuobstwiese

### Aufgabe 3: Aussagen zur Nahrungskette prüfen

Kreuze alle richtigen Aussagen zur Streuobstwiese an:
☐ Das grüne Apfelblatt bildet als Pflanze den Anfang der Nahrungskette (Erzeuger).
☐ Die Raupe frisst ausschließlich Kohlmeisen und Greifvögel.
☐ Die Kohlmeise füttert ihre Jungen im Frühling mit vielen Raupen.
☐ Der Turmfalke steht als Beutegreifer am Ende dieser Nahrungskette.

### Aufgabe 4: Forscherauftrag – Eigene Nahrungskette legen

1. Bringt die vier Lebewesen in die richtige Reihenfolge (1 bis 4): Igel – Regenwurm – Falllaub – Fuchs.
2. Überlegt gemeinsam: Was passiert auf der Streuobstwiese, wenn im Frühling alle Insekten fehlen?
3. Zeichnet in euer Forscherheft eine eigene Nahrungskette mit vier Pfeilen („wird gefressen von“).

### Aufgabe 5: Die Stockwerke der Streuobstwiese zuordnen

Ordne jedem Lebensbereich der Wiese zwei passende Tiere zu (Maulwurf, Grünspecht, Schmetterling, Regenwurm, Siebenschläfer, Wildbiene):
a) Baumkrone und Baumhöhlen: ____
b) Blüten- und Krautschicht: ____
c) Wiesenboden: ____

**Merksatz: Erzeuger, Verbraucher und das Gleichgewicht in der Natur**
- Erzeuger (Pflanzen): Grüne Pflanzen wie der Apfelbaum oder das Wiesengras stellen mithilfe von Sonnenlicht, Wasser und Luft ihre Nahrung selbst her. Sie stehen am Beginn jeder Kette.
- Verbraucher (Pflanzenfresser und Fleischfresser): Tiere wie Raupen, Käfer, Singvögel und Greifvögel sind auf Pflanzen oder andere Tiere als Nahrungsquelle angewiesen.
- Zersetzer (Destruenten): Regenwürmer, Asseln und Bodenpilze verwandeln welkes Herbstlaub wieder in wertvollen Humusboden. So schließt sich der natürliche Stoffkreislauf der Wiese.
- Naturschutz-Regel: Auf einer ungespritzten Streuobstwiese finden über 2.000 Tier- und Pflanzenarten einen geschützten Lebensraum.
"""

    gs_sachkunde_ueb = """((24))

# Sachunterricht – Klasse 3

## Kapitel 2: Lebensraum Streuobstwiese und das Bienenjahr

Auf einer Streuobstwiese wachsen hochstämmige Apfel-, Birnen- und Kirschbäume unterschiedlichen Alters. Zwischen den Bäumen blühen im Frühling Löwenzahn, Wiesensalbei und Margeriten. Hier finden Honigbienen, Wildbienen, Schmetterlinge, Singvögel und Igel das ganze Jahr über Nahrung und Schutz.

### Aufgabe 1: Lückentext – Das Bienenjahr auf der Streuobstwiese

<Lückentext>
<Rahmen>
_Wortspeicher:_ Blüten · Nektar · Bestäubung · Früchte · Winterruhe
</Rahmen>

Setze die passenden Wörter aus dem Wortspeicher in die Lücken ein:
Im Frühling öffnen die Apfelbäume ihre duftenden _..._. Die Honigbienen sammeln dort süßen _..._ und tragen Blütenstaub von Baum zu Baum. Durch diese wichtige _..._ wachsen im Sommer saftige _..._. Im kalten Dezember hält das Bienenvolk _..._.
</Lückentext>

<Rahmen>
_Sachwissen kompakt: Das Honigbienen-Volk im Jahreslauf_
-\t_Königin, Arbeiterinnen und Drohnen:_ In einem einzigen Bienenstock leben im Sommer bis zu 50.000 weibliche Arbeitsbienen, einige hundert männliche Drohnen und eine einzige Bienenkönigin.
-\t_Bestäubungsleistung:_ Für ein einziges Glas Honig (500 g) müssen die Sammlerinnen rund 40.000-mal ausfliegen und dabei Millionen einzelner Obst- und Wiesenblüten besuchen.
-\t_Verständigung durch den Schwänzeltanz:_ Kehrt eine Kundschafterin zur Wabe zurück, zeigt sie den anderen Bienen durch Richtung und Tempo ihres Tanzes genau den Weg zur Futterquelle.
-\t_Überwinterung:_ Im Winter bildet das Volk eine enge Wintertraube und hält die Temperatur im Inneren durch Muskelzittern konstant bei etwa 25 °C bis 30 °C.
</Rahmen>

### Aufgabe 2: Wetter- und Naturprotokoll ergänzen

Vervollständige die Beobachtungstabelle unserer Schulwiese im Jahresverlauf:

<Tabelle>
Monat\tMittlere Temperatur\tSonnenstunden/Tag\tBeobachtung auf der Wiese
April\t10 °C\t6 Stunden\tApfelblüte beginnt, Hummeln fliegen
Juli\t21 °C\t_..._ Stunden\tReife Kirschen, viele Kohlmeisen
Oktober\t_..._ °C\t4 Stunden\tApfelernte und bunter Laubfall
</Tabelle>

<Rahmen>
_Forscher-Tipp: Wildbienen und Nistplätze auf dem Schulhof schützen_
-\tNeben der Honigbiene leben in Deutschland über 560 verschiedene Wildbienenarten (z. B. die Rote Mauerbiene und die Erdhummel). Die meisten Wildbienen bilden keinen Staat, sondern legen ihre Brutzellen einzeln in hohlen Pflanzenstängeln, im Totholz oder im sandigen Boden an.
-\tWenn eine Wiese erst spät im Juni gemäht wird, können Wiesenblumen aussamen und bieten Insekten, Raupen und Wiesenvögeln bis in den Herbst hinein reichlich Nahrung.
-\tBeobachte am Insektenhotel immer ruhig aus 1 Meter Abstand und verschließe niemals die Röhren.
</Rahmen>

((25))

## Nahrungsbeziehungen und Naturbeobachtung auf der Wiese

#### Abb. 2.1: Nahrungskette auf der Streuobstwiese

<Bild> Strukturdiagramm:
Beschreibung mit Bildtext: Apfelblatt (Erzeuger) \\to Raupe (1. Verbraucher) \\to Kohlmeise (2. Verbraucher) \\to Turmfalke (Beutegreifer).
</Bild>

### Aufgabe 3: Aussagen zur Nahrungskette prüfen

Kreuze alle richtigen Aussagen zur Streuobstwiese an:
[ ] Das grüne Apfelblatt bildet als Pflanze den Anfang der Nahrungskette (Erzeuger).
[ ] Die Raupe frisst ausschließlich Kohlmeisen und Greifvögel.
[ ] Die Kohlmeise füttert ihre Jungen im Frühling mit vielen Raupen.
[ ] Der Turmfalke steht als Beutegreifer am Ende dieser Nahrungskette.

### Aufgabe 4: Forscherauftrag – Eigene Nahrungskette legen
[Partnerarbeit]

1.\tBringt die vier Lebewesen in die richtige Reihenfolge (1 bis 4): Igel – Regenwurm – Falllaub – Fuchs.
2.\tÜberlegt gemeinsam: Was passiert auf der Streuobstwiese, wenn im Frühling alle Insekten fehlen?
3.\tZeichnet in euer Forscherheft eine eigene Nahrungskette mit vier Pfeilen ("wird gefressen von").

### Aufgabe 5: Die Stockwerke der Streuobstwiese zuordnen

Ordne jedem Lebensbereich der Wiese zwei passende Tiere zu (Maulwurf, Grünspecht, Schmetterling, Regenwurm, Siebenschläfer, Wildbiene):
a) Baumkrone und Baumhöhlen: _..._
b) Blüten- und Krautschicht: _..._
c) Wiesenboden: _..._

<Rahmen>
_Merksatz: Erzeuger, Verbraucher und das Gleichgewicht in der Natur_
-\t_Erzeuger (Pflanzen):_ Grüne Pflanzen wie der Apfelbaum oder das Wiesengras stellen mithilfe von Sonnenlicht, Wasser und Luft ihre Nahrung selbst her. Sie stehen am Beginn jeder Kette.
-\t_Verbraucher (Pflanzenfresser und Fleischfresser):_ Tiere wie Raupen, Käfer, Singvögel und Greifvögel sind auf Pflanzen oder andere Tiere als Nahrungsquelle angewiesen.
-\t_Zersetzer (Destruenten):_ Regenwürmer, Asseln und Bodenpilze verwandeln welkes Herbstlaub wieder in wertvollen Humusboden. So schließt sich der natürliche Stoffkreislauf der Wiese.
-\t_Naturschutz-Regel:_ Auf einer ungespritzten Streuobstwiese finden über 2.000 Tier- und Pflanzenarten einen geschützten Lebensraum.
</Rahmen>
"""

    # -------------------- 3. SEK I DEUTSCH --------------------
    s1_deutsch_raw = """((112))

# Kapitel 5: Mensch und Natur in Erzählung und Reportage

## 5.1 Lesetext: Sturm über der Hallig (mit Zeilenzählung)

Seit dem frühen Nachmittag drückte ein bleigrauer Himmel
auf das flache Wattenmeer. Jan stand am Deichfenster
der kleinen Warft und beobachtete, wie die ersten
Schaumkronen über die Salzwiesen rollten. Seine Schwester
5 Nele prüfte die schweren Holzläden im Erdgeschoss.
„Wenn der Westwind bis zum Abend auf Sturmstärke
dreht, steigt das Wasser heute bis an die oberste
Steinkante“, sagte Großvater Tamme ruhig, während er
die Taschenlampen auf den Küchentisch stellte.
10 Draußen pfiff die Böe bereits durch die alten Eschen.
Plötzlich blinkte weit draußen am Horizont das helle
Leuchtfeuer der Nachbarinsel dreimal kurz auf.
Jan griff nach dem Fernglas seines Großvaters und
suchte die aufgewühlte Fahrrinne ab. Zwischen den
15 Brechern erkannte er das rote Rettungsboot der Küstenwache,
das langsam gegen die Strömung ankämpfte.
Im Funkgerät knisterte eine leise Stimme: Alle
Bewohner der Hallig sollten die unteren Räume sichern
und die Notfunkfrequenz eingeschaltet lassen.
20 Gegen Mitternacht erreichte der Wasserstand seinen
Höchstwert; das Meer donnerte gegen die Befestigung,
doch die jahrhundertealte Warft hielt dem Druck stand.
Gebannt blickten die Kinder durch das Dachfenster
hinüber zum sicheren Lichtkegel, den der erfahrene
25 Leuchtturm-

**Worterklärungen (Randspalte)**
- Hallig: kleine, nicht eingedeichte Marschinsel im nordfriesischen Wattenmeer.
- Warft: künstlich aufgeschütteter Wohnhügel zum Schutz bei Landunter.
- Brecher: hohe, sich überschlagende Meereswelle bei Sturmflut.

**Hintergrund: Sturmflut**
- Bei schweren Weststürmen drückt der Wind das Nordseewasser in die Deutsche Bucht („Blanker Hans“).
- Auf den zehn nordfriesischen Halligen tritt mehrmals im Winterhalbjahr „Landunter“ ein: Nur die Warften ragen dann noch aus den Fluten.

**Methode: Einen literarischen Erzähltext auf Spannungsmerkmale untersuchen**
- 1. Atmosphäre und Schauplatz (Exposition): Achte auf sinnliche Adjektive und Verben, mit denen Wetter, Lichtverhältnisse und Geräusche beschrieben werden (z. B. „bleigrauer Himmel“, „pfiff“).
- 2. Figurenrede und innere Handlung: Untersuche, wie die Figuren auf die Gefahr reagieren (z. B. Großvater Tammes ruhige Anweisungen im Kontrast zur wachsenden Unruhe der Kinder).
- 3. Steigerung bis zum Höhepunkt (Klimax): Markiere Textstellen, an denen sich die Bedrohung verdichtet (Leuchtfeuer am Horizont, knisternder Notfunk, Höchststand um Mitternacht).
- 4. Satzbau und Erzähltempo: Kurze Hauptsätze beschleunigen das Erzähltempo in Gefahrenszenen, während präzise Detailbeschreibungen den Blick der Lesenden wie durch ein Fernglas lenken.
- Tipp für Textbelege: Gib bei jedem Zitat stets die genaue Zeile in Klammern an, z. B. (Z. 14–16).

((113))

wärter. Am nächsten Morgen glitzerte der nasse Schlick in der Wintersonne, und die Seevögel kehrten kreischend auf die Wiesen zurück.

### Aufgabe 1: Textverständnis und Spannungsaufbau untersuchen

1. Beschreibe, mit welchen sprachlichen Mitteln in Zeile 1–10 die drohende Sturmflut angekündigt wird.
2. Erkläre die Bedeutung der Begriffe „Hallig“ und „Warft“ mithilfe der Randspalte.

### Aufgabe 2: Hervorhebungen bestimmen (fett, kursiv, unterstrichen)

Bestimme in den drei Beispielsätzen die Wortart der fett gedruckten Wörter, die Funktion der kursiv gesetzten Ausdrücke und das Satzglied der unterstrichenen Wortgruppen:
a) Der **erfahrene** Kapitän steuert das Rettungsboot *trotz der Dunkelheit* <u>durch die enge Fahrrinne</u>.
b) Viele **wachsame** Inselbewohner sichern *vor dem nahenden Hochwasser* <u>alle Fenster und Türen</u>.
c) Am Morgen meldet der **örtliche** Wetterdienst *glücklicherweise* <u>das Ende der schweren Sturmflut</u>.

**Sprachwissen: Indirekte Rede mit Konjunktiv I und II**
- In Nachrichten und Berichten wird die indirekte Rede meist im Konjunktiv I gebildet: Großvater Tamme erklärt, das Wasser steige heute bis an die oberste Steinkante.
- Stimmt der Konjunktiv I mit dem Indikativ überein, weicht man auf den Konjunktiv II aus: Die Helfer berichten, viele Boote kämen erst bei Ebbe wieder frei.

### Aufgabe 3: Direkte Rede in einen Zeitungsbericht umformen

Forme die folgenden Aussagen für die Lokalzeitung „Nordfriesische Nachrichten“ in die indirekte Rede um:
a) Jan ruft: „Ich sehe das rote Rettungsboot der Küstenwache zwischen den hohen Brechern!“
b) Nele berichtet: „Wir haben alle Holzläden im Erdgeschoss rechtzeitig verriegelt.“
c) Der Einsatzleiter betont: „Die Bewohner der Hallig sind während der gesamten Nacht in Sicherheit.“

### Aufgabe 4: Schreibauftrag – Innerer Monolog oder Erlebnisbericht

Wähle eine der beiden Schreibaufgaben aus und verfasse einen zusammenhängenden Text (ca. 120 Wörter):
1. Innerer Monolog: Versetze dich in Jan (Z. 23–25), als er um Mitternacht zum Leuchtturm blickt.
2. Zeitungsreportage: Schreibe einen sachlichen Bericht über den Einsatz des Rettungsbootes.

**Checkliste zur Textüberarbeitung: Indirekte Rede & Schreibkonferenz**
- Redeeinleitung: Habe ich abwechslungsreiche Verben des Sagens verwendet (z. B. berichten, erklären, betonen, warnen, schildern) statt immer nur „sagen“ zu wiederholen?
- Moduswechsel: Stehen alle Verben der wiedergegebenen Rede korrekt im Konjunktiv I (er sehe, es steige, sie sei) bzw. bei Formen-Gleichheit im Konjunktiv II (sie hätten, sie kämen)?
- Pronomen & Perspektive: Wurden Personal- und Possessivpronomen sinnvoll angepasst (aus „Ich sehe mein Boot“ wird „Jan ruft, er sehe sein Boot“)?
- Zeichensetzung: Fehlen die Anführungszeichen bei der indirekten Rede und steht vor dem eingeleiteten Nebensatz ein Komma?
"""

    s1_deutsch_ueb = """((112))

# Kapitel 5: Mensch und Natur in Erzählung und Reportage

## 5.1 Lesetext: Sturm über der Hallig (mit Zeilenzählung)

Seit dem frühen Nachmittag drückte ein bleigrauer Himmel
auf das flache Wattenmeer. Jan stand am Deichfenster
der kleinen Warft und beobachtete, wie die ersten
Schaumkronen über die Salzwiesen rollten. Seine Schwester
5 Nele prüfte die schweren Holzläden im Erdgeschoss.
„Wenn der Westwind bis zum Abend auf Sturmstärke
dreht, steigt das Wasser heute bis an die oberste
Steinkante“, sagte Großvater Tamme ruhig, während er
die Taschenlampen auf den Küchentisch stellte.
10 Draußen pfiff die Böe bereits durch die alten Eschen.
Plötzlich blinkte weit draußen am Horizont das helle
Leuchtfeuer der Nachbarinsel dreimal kurz auf.
Jan griff nach dem Fernglas seines Großvaters und
suchte die aufgewühlte Fahrrinne ab. Zwischen den
15 Brechern erkannte er das rote Rettungsboot der Küstenwache,
das langsam gegen die Strömung ankämpfte.
Im Funkgerät knisterte eine leise Stimme: Alle
Bewohner der Hallig sollten die unteren Räume sichern
und die Notfunkfrequenz eingeschaltet lassen.
20 Gegen Mitternacht erreichte der Wasserstand seinen
Höchstwert; das Meer donnerte gegen die Befestigung,
doch die jahrhundertealte Warft hielt dem Druck stand.
Gebannt blickten die Kinder durch das Dachfenster
hinüber zum sicheren Lichtkegel, den der erfahrene
25 Leuchtturmwärter.

<Rahmen>
_Worterklärungen (Randspalte)_
-\t_Hallig:_ kleine, nicht eingedeichte Marschinsel im nordfriesischen Wattenmeer.
-\t_Warft:_ künstlich aufgeschütteter Wohnhügel zum Schutz bei Landunter.
-\t_Brecher:_ hohe, sich überschlagende Meereswelle bei Sturmflut.
</Rahmen>

<Rahmen>
_Hintergrund: Sturmflut_
-\tBei schweren Weststürmen drückt der Wind das Nordseewasser in die Deutsche Bucht („Blanker Hans“).
-\tAuf den zehn nordfriesischen Halligen tritt mehrmals im Winterhalbjahr „Landunter“ ein: Nur die Warften ragen dann noch aus den Fluten.
</Rahmen>

<Rahmen>
_Methode: Einen literarischen Erzähltext auf Spannungsmerkmale untersuchen_
-\t_1. Atmosphäre und Schauplatz (Exposition):_ Achte auf sinnliche Adjektive und Verben, mit denen Wetter, Lichtverhältnisse und Geräusche beschrieben werden (z. B. „bleigrauer Himmel“, „pfiff“).
-\t_2. Figurenrede und innere Handlung:_ Untersuche, wie die Figuren auf die Gefahr reagieren (z. B. Großvater Tammes ruhige Anweisungen im Kontrast zur wachsenden Unruhe der Kinder).
-\t_3. Steigerung bis zum Höhepunkt (Klimax):_ Markiere Textstellen, an denen sich die Bedrohung verdichtet (Leuchtfeuer am Horizont, knisternder Notfunk, Höchststand um Mitternacht).
-\t_4. Satzbau und Erzähltempo:_ Kurze Hauptsätze beschleunigen das Erzähltempo in Gefahrenszenen, während präzise Detailbeschreibungen den Blick der Lesenden wie durch ein Fernglas lenken.
-\t_Tipp für Textbelege:_ Gib bei jedem Zitat stets die genaue Zeile in Klammern an, z. B. (Z. 14–16).
</Rahmen>

((113))

Am nächsten Morgen glitzerte der nasse Schlick in der Wintersonne, und die Seevögel kehrten kreischend auf die Wiesen zurück.

### Aufgabe 1: Textverständnis und Spannungsaufbau untersuchen

1.\tBeschreibe, mit welchen sprachlichen Mitteln in Zeile 1–10 die drohende Sturmflut angekündigt wird.
2.\tErkläre die Bedeutung der Begriffe „Hallig“ und „Warft“ mithilfe der Randspalte.

### Aufgabe 2: Hervorhebungen bestimmen (fett, kursiv, unterstrichen)

Bestimme in den drei Beispielsätzen die Wortart der fett gedruckten Wörter, die Funktion der kursiv gesetzten Ausdrücke und das Satzglied der unterstrichenen Wortgruppen:
a) Der *erfahrene* Kapitän steuert das Rettungsboot %trotz der Dunkelheit% #durch die enge Fahrrinne#.
b) Viele *wachsame* Inselbewohner sichern %vor dem nahenden Hochwasser% #alle Fenster und Türen#.
c) Am Morgen meldet der *örtliche* Wetterdienst %glücklicherweise% #das Ende der schweren Sturmflut#.

<Rahmen>
_Sprachwissen: Indirekte Rede mit Konjunktiv I und II_
-\tIn Nachrichten und Berichten wird die indirekte Rede meist im Konjunktiv I gebildet: Großvater Tamme erklärt, das Wasser steige heute bis an die oberste Steinkante.
-\tStimmt der Konjunktiv I mit dem Indikativ überein, weicht man auf den Konjunktiv II aus: Die Helfer berichten, viele Boote kämen erst bei Ebbe wieder frei.
</Rahmen>

### Aufgabe 3: Direkte Rede in einen Zeitungsbericht umformen

Forme die folgenden Aussagen für die Lokalzeitung „Nordfriesische Nachrichten“ in die indirekte Rede um:
a) Jan ruft: „Ich sehe das rote Rettungsboot der Küstenwache zwischen den hohen Brechern!“
b) Nele berichtet: „Wir haben alle Holzläden im Erdgeschoss rechtzeitig verriegelt.“
c) Der Einsatzleiter betont: „Die Bewohner der Hallig sind während der gesamten Nacht in Sicherheit.“

### Aufgabe 4: Schreibauftrag – Innerer Monolog oder Erlebnisbericht

Wähle eine der beiden Schreibaufgaben aus und verfasse einen zusammenhängenden Text (ca. 120 Wörter):
1.\tInnerer Monolog: Versetze dich in Jan (Z. 23–25), als er um Mitternacht zum Leuchtturm blickt.
2.\tZeitungsreportage: Schreibe einen sachlichen Bericht über den Einsatz des Rettungsbootes.

<Rahmen>
_Checkliste zur Textüberarbeitung: Indirekte Rede & Schreibkonferenz_
-\t_Redeeinleitung:_ Habe ich abwechslungsreiche Verben des Sagens verwendet (z. B. berichten, erklären, betonen, warnen, schildern) statt immer nur „sagen“ zu wiederholen?
-\t_Moduswechsel:_ Stehen alle Verben der wiedergegebenen Rede korrekt im Konjunktiv I (er sehe, es steige, sie sei) bzw. bei Formen-Gleichheit im Konjunktiv II (sie hätten, sie kämen)?
-\t_Pronomen & Perspektive:_ Wurden Personal- und Possessivpronomen sinnvoll angepasst (aus „Ich sehe mein Boot“ wird „Jan ruft, er sehe sein Boot“)?
-\t_Zeichensetzung:_ Fehlen die Anführungszeichen bei der indirekten Rede und steht vor dem eingeleiteten Nebensatz ein Komma?
</Rahmen>
"""

    # -------------------- 4. SEK I ENGLISCH --------------------
    s1_englisch_raw = """((64))

# Unit 4: Teen Action – Protecting the Cornwall Coastline

![Abb. 4.1: Jugendmagazin-Collage – Clean-up Action at Cornwall Coast](figures/sek1_cornwall_coastal_action.png)

Abb. 4.1: Jugendmagazin-Collage – Clean-up Action at Cornwall Coast

## 4.1 Dialogue: Planning the Saturday Beach Clean-up

*St Ives Teen Magazine:* Every Saturday, local volunteers meet at the harbour pier to collect marine plastic and protect coastal seabirds in Cornwall.

**Maya:** Look at the harbour poster, Liam! Volunteers collected 142 kilos of plastic last month.
**Liam:** That's impressive, Maya. If we join the group on Saturday, we will help protect the seabirds.
**Mrs O'Connor:** Good morning, you two! Have you signed up for the St Ives environmental project yet?
**Maya:** Yes, Mrs O'Connor! If more students had reusable bottles, there would be far less waste.
**Liam:** Let's bring sturdy gloves and recycling bags to the Harbour Pier at ten o'clock.

### Aufgabe 1 ★: Reading & Map Comprehension – St Ives Eco-Report

1. Look at Abb. 4.1: Which two types of marine litter make up the largest share of waste in St Ives Bay?
2. Find St Ives Pier and Godrevy Lighthouse on the OpenStreetMap inset and explain why the bay traps plastic.

### Aufgabe 2 ★★: Speaking – Organising a School Green Day

Work with a partner. Discuss how your class could reduce plastic waste using the Useful Phrases box:

**Useful Phrases: Expressing Opinions and Making Suggestions**
- Giving your opinion: In my opinion, we should... | I strongly believe that... | From my point of view...
- Making suggestions: Why don't we organise a...? | If we banned single-use cups, we would save...
- Agreeing & reacting: That's a great point! | I completely agree with you. | Let's put up a poster.
- Polite disagreement: I see your point, but what if...? | Wouldn't it be better if we started with...?

**Grammar Box: Conditional Sentences Type I and Type II**
- Type I (real/likely): if + Simple Present → will-future (If we join on Saturday, we will help.)
- Type II (unreal/hypothetical): if + Simple Past → would + infinitive (If more students had reusable bottles, there would be far less waste.)
- Watch out: Never use 'will' or 'would' inside the if-clause itself!

((65))

## 4.2 Vocabulary Unit 4 – English / IPA Phonetics / Deutsch

| English Word & Example | IPA Phonetics | Deutsche Bedeutung |
| :--- | :--- | :--- |
| coastline (n.) – We must protect our rocky coastline. | [/ˈkəʊstlaɪn/] | Küstenlinie, Meeresküste |
| knowledge (n.) – Local knowledge helps the rescue team. | [/ˈnɒlɪdʒ/] | Wissen, Kenntnis |
| volunteer (n./v.) – Sixteen volunteers cleaned the cove. | [/ˌvɒlənˈtɪə(r)/] | Freiwillige(r); freiwillig helfen |
| environmental (adj.) – She joined an environmental club. | [/ɪnˌvaɪrənˈmentl/] | Umwelt-, ökologisch |
| sustainable (adj.) – Sustainable tourism avoids waste. | [/səˈsteɪnəbl/] | nachhaltig, zukunftsfähig |
| pollution (n.) – Marine pollution threatens sea turtles. | [/pəˈluːʃn/] | Verschmutzung, Umweltbelastung |
| harbour pier (n.) – Meet us at the old harbour pier. | [/ˈhɑːbə pɪə(r)/] | Hafenmole, Landungsbrücke |

### Aufgabe 3 ★★: Mediation & Conditional Practice

Complete the conditional sentences with the correct verb forms:
a) If the tide ____ (rise) quickly, the coastguard will warn all boats in the harbour.
b) If people ____ (not drop) plastic on the beach, seabirds would be much safer.
c) What ____ you ____ (do) if you found an entangled seal on the coastline?

### Aufgabe 4 ★★★: Mediation – E-Mail an eine Partnerschule in Cornwall

Deine Klasse plant eine Umwelt-Projektwoche und hat den Artikel aus dem St Ives Teen Magazine aus Unit 4 gelesen. Dein Mitschüler Lukas versteht kein Englisch und bittet dich um eine Zusammenfassung.
1. Erkläre Lukas auf Deutsch die wichtigsten Ergebnisse der Strandreinigung in St Ives (Menge, Müllarten).
2. Write a short reply email (60–80 words) to Maya and Liam introducing your own school eco-project.

**Study Skills: Working with an English-German Dictionary & IPA Phonetics**
- 1. Word class abbreviations: Always check whether a headword is a noun (n.), verb (v.), or adjective (adj.). Many English words like 'volunteer' can be used both as a noun and a verb.
- 2. Word stress in IPA: The vertical mark [ˈ] in phonetic transcription always stands directly before the main stressed syllable (e.g. [/səˈsteɪnəbl/] -> stress on '-stain-').
- 3. British vs. American English: Note British spelling '-our' in 'harbour' (AE: 'harbor') and the optional final r-sound [ə(r)] in British Received Pronunciation.
- Tip for Mediation: Never translate sentence by sentence—summarise the key facts in your own words!
"""

    s1_englisch_ueb = """((64))

# Unit 4: Teen Action – Protecting the Cornwall Coastline

#### Abb. 4.1: Jugendmagazin-Collage – Clean-up Action at Cornwall Coast

<Bild> Jugendmagazin-Collage:
Beschreibung mit Bildtext: Küstenlandschaft mit Klippen, Leuchtturm und einer OpenStreetMap-Nebenkarte der Bucht von St Ives (St Ives Pier, Godrevy; © OpenStreetMap contributors, ODbL) links sowie einer Informationstafel am Strand rechts mit der Überschrift „YOUTH ECO-REPORT: ST IVES BEACH CLEAN-UP“ und einem Kreisdiagramm (142 kg: 47 % Bottles, 38 % Nets, 15 % Other). Darauf stehen die Angaben: Volunteers collected: 142 kg marine plastic; Fishing nets & ropes: 38 % of total waste; Single-use bottles & caps: 47 % of total waste; Next action day: Saturday, 10:00 a.m. at Harbour Pier; Motto: „Protect Our Coastline – Every Piece Counts!“.
</Bild>

## 4.1 Dialogue: Planning the Saturday Beach Clean-up

_St Ives Teen Magazine:_ Every Saturday, local volunteers meet at the harbour pier to collect marine plastic and protect coastal seabirds in Cornwall.

_Maya:_ Look at the harbour poster, Liam! Volunteers collected 142 kilos of plastic last month.
_Liam:_ That's impressive, Maya. If we join the group on Saturday, we will help protect the seabirds.
_Mrs O'Connor:_ Good morning, you two! Have you signed up for the St Ives environmental project yet?
_Maya:_ Yes, Mrs O'Connor! If more students had reusable bottles, there would be far less waste.
_Liam:_ Let's bring sturdy gloves and recycling bags to the Harbour Pier at ten o'clock.

### Aufgabe 1: Reading & Map Comprehension – St Ives Eco-Report
[leicht]

1.\tLook at Abb. 4.1: Which two types of marine litter make up the largest share of waste in St Ives Bay?
2.\tFind St Ives Pier and Godrevy Lighthouse on the OpenStreetMap inset and explain why the bay traps plastic.

### Aufgabe 2: Speaking – Organising a School Green Day
[mittel] [Partnerarbeit]

Work with a partner. Discuss how your class could reduce plastic waste using the Useful Phrases box:

<Rahmen>
_Useful Phrases: Expressing Opinions and Making Suggestions_
-\t_Giving your opinion:_ In my opinion, we should... | I strongly believe that... | From my point of view...
-\t_Making suggestions:_ Why don't we organise a...? | If we banned single-use cups, we would save...
-\t_Agreeing & reacting:_ That's a great point! | I completely agree with you. | Let's put up a poster.
-\t_Polite disagreement:_ I see your point, but what if...? | Wouldn't it be better if we started with...?
</Rahmen>

<Rahmen>
_Grammar Box: Conditional Sentences Type I and Type II_
-\tType I (real/likely): if + Simple Present → will-future (If we join on Saturday, we will help.)
-\tType II (unreal/hypothetical): if + Simple Past → would + infinitive (If more students had reusable bottles, there would be far less waste.)
-\tWatch out: Never use 'will' or 'would' inside the if-clause itself!
</Rahmen>

((65))

## 4.2 Vocabulary Unit 4 – English / IPA Phonetics / Deutsch

<Tabelle>
English Word & Example\tIPA Phonetics\tDeutsche Bedeutung
coastline (n.) – We must protect our rocky coastline.\t[/ˈkəʊstlaɪn/]\tKüstenlinie, Meeresküste
knowledge (n.) – Local knowledge helps the rescue team.\t[/ˈnɒlɪdʒ/]\tWissen, Kenntnis
volunteer (n./v.) – Sixteen volunteers cleaned the cove.\t[/ˌvɒlənˈtɪə(r)/]\tFreiwillige(r); freiwillig helfen
environmental (adj.) – She joined an environmental club.\t[/ɪnˌvaɪrənˈmentl/]\tUmwelt-, ökologisch
sustainable (adj.) – Sustainable tourism avoids waste.\t[/səˈsteɪnəbl/]\tnachhaltig, zukunftsfähig
pollution (n.) – Marine pollution threatens sea turtles.\t[/pəˈluːʃn/]\tVerschmutzung, Umweltbelastung
harbour pier (n.) – Meet us at the old harbour pier.\t[/ˈhɑːbə pɪə(r)/]\tHafenmole, Landungsbrücke
</Tabelle>

### Aufgabe 3: Mediation & Conditional Practice
[mittel]

Complete the conditional sentences with the correct verb forms:
a) If the tide _..._ (rise) quickly, the coastguard will warn all boats in the harbour.
b) If people _..._ (not drop) plastic on the beach, seabirds would be much safer.
c) What _..._ you _..._ (do) if you found an entangled seal on the coastline?

### Aufgabe 4: Mediation – E-Mail an eine Partnerschule in Cornwall
[schwer]

Deine Klasse plant eine Umwelt-Projektwoche und hat den Artikel aus dem St Ives Teen Magazine aus Unit 4 gelesen. Dein Mitschüler Lukas versteht kein Englisch und bittet dich um eine Zusammenfassung.
1.\tErkläre Lukas auf Deutsch die wichtigsten Ergebnisse der Strandreinigung in St Ives (Menge, Müllarten).
2.\tWrite a short reply email (60–80 words) to Maya and Liam introducing your own school eco-project.

<Rahmen>
_Study Skills: Working with an English-German Dictionary & IPA Phonetics_
-\t_1. Word class abbreviations:_ Always check whether a headword is a noun (n.), verb (v.), or adjective (adj.). Many English words like 'volunteer' can be used both as a noun and a verb.
-\t_2. Word stress in IPA:_ The vertical mark [ˈ] in phonetic transcription always stands directly before the main stressed syllable (e.g. [/səˈsteɪnəbl/] -> stress on '-stain-').
-\t_3. British vs. American English:_ Note British spelling '-our' in 'harbour' (AE: 'harbor') and the optional final r-sound [ə(r)] in British Received Pronunciation.
-\t_Tip for Mediation:_ Never translate sentence by sentence—summarise the key facts in your own words!
</Rahmen>
"""

    # -------------------- 5. SEK I GEOGRAPHIE --------------------
    s1_geo_raw = """((204))

# Kapitel 2: Der Oberrheingraben – Naturraum, Relief und Klima

## 2.1 Topographie und Grabenbruch im Südwesten

Zwischen den Mittelgebirgen Vogesen im Westen und Schwarzwald im Osten erstreckt sich der rund 300 km lange Oberrheingraben¹. Durch die geschützte Beckenlage und die geringe Meereshöhe zählt die Region zu den wärmsten und fruchtbarsten Naturräumen Mitteleuropas.

![Abb. 2.1: Physische und thematische Karte des Oberrheingrabens](figures/geo_karte_oberrheingraben.png)

Abb. 2.1: Physische und thematische Karte des Oberrheingrabens (Kartengrundlage: © OpenStreetMap-Mitwirkende, ODbL)

### Aufgabe 1: Kartenarbeit zum Oberrheingraben

1. Bestimme mithilfe des Maßstabs (1 : 2.500.000) und des Gradnetzes die Lage von Straßburg und Freiburg.
2. Beschreibe das Höhenprofil entlang des 48. nördlichen Breitengrades von West nach Ost.

**Methode: Eine physische und thematische Karte systematisch auswerten**
- 1. Orientierung & Thema: Lies zuerst Kartenüberschrift, Maßstab (1 : 2.500.000: 1 cm auf der Karte entspricht 25 km in der Wirklichkeit), Windrose und die Höhenstufen der Legende.
- 2. Verortung im Gradnetz: Bestimme geographische Breite (nördliche Breite: 47°N bis 49°N) und geographische Länge (östliche Länge: 7°O bis 9°O) der wichtigsten Städte und Flüsse.
- 3. Raummuster beschreiben: Gliedere den Naturraum in Teilräume (Tiefland der Rheinebene unter 200 m vs. steil aufragende Randgebirge Vogesen und Schwarzwald über 800 m).
- 4. Zusammenhänge erklären: Verknüpfe Relief, Gewässernetz und Siedlungsachsen (warum verlaufen Autobahnen, Eisenbahnlinien und Großstädte gebündelt entlang der Grabenachse?).

### Geologie, Lössböden und Wasserstraßen der Oberrheinebene

Beim Einsinken des Grabenbruchs lagerten der Rhein und seine Nebenflüsse mächtige Kies- und Schotterschichten ab. An den Vorbergzonen bildeten sich während der Kaltzeiten fruchtbare Lössböden. Im 19. Jahrhundert veränderte zudem die Rheinbegradigung durch Johann Gottfried Tulla den Flusslauf grundlegend und schuf die Voraussetzung für die moderne Großstadtentwicklung und Binnen-

¹ Tektonischer Grabenbruch: Einsenkung der Erdkruste im Tertiär entlang paralleler Verwerfungslinien.

((205))

schifffahrt. Heute zählt die Rheinschiene zwischen Basel, Straßburg und Karlsruhe zu den wichtigsten europäischen Verkehrs- und Wirtschaftsachsen.

## 2.2 Höhenstufen und Luv-Lee-Effekt im Klimavergleich

![Abb. 2.2a: Klimadiagramm Freiburg im Breisgau (269 m ü. NN)](figures/geo_klima_freiburg.png)
![Abb. 2.2b: Klimadiagramm Feldberg im Schwarzwald (1493 m ü. NN)](figures/geo_klima_feldberg.png)

Abb. 2.2a: Klimadiagramm Freiburg (269 m)
Abb. 2.2b: Klimadiagramm Feldberg (1493 m)

Der Vergleich der beiden Klimastationen verdeutlicht den vertikalen Temperaturgradienten sowie den Steigungsregen an den Westflanken des Schwarzwalds². Während Freiburg ein mildes Weinbauklima aufweist, herrscht auf dem Feldberg ein kühl-feuchtes Gebirgsklima mit fast doppeltem Jahresniederschlag.

### Aufgabe 2: Klimadiagramme vergleichen und Luv-Lee-Effekt erklären

1. Werte die Klimadiagramme von Freiburg (Abb. 2.2a) und Feldberg (Abb. 2.2b) nach Temperaturamplitude, Jahresmitteltemperatur und Jahresniederschlagssumme systematisch aus.
2. Berechne die durchschnittliche Temperaturabnahme pro 100 Höhenmeter zwischen Freiburg und Feldberg.
3. Begründe, warum die westlich gelegene Stadt Colmar im Lee der Vogesen nur ca. 550 mm Niederschlag erhält.

### Aufgabe 3: Flussregulierung und Hochwasserschutz am Oberrhein beurteilen

1. Erläutere die ökologischen Folgen der Rheinbegradigung durch Tulla für Grundwasserspiegel und Auenwälder.
2. Erkläre die Funktionsweise gesteuerter Rückhaltepolder im Rahmen des Integrierten Rheinprogramms.

**Geo-Lexikon: Luv-Lee-Effekt, Föhnwirkung und Rheinbegradigung**
- Luv-Seite (Windzugewandte Seite): Feuchte atlantische Luftmassen werden aus Westen an den Vogesen und dem Schwarzwald zum Aufsteigen gezwungen. Dabei kühlt die Luft um ca. 0,65 °C pro 100 m ab (feuchtadiabatisch), Wolken bilden sich und es fällt Steigungsregen.
- Lee-Seite (Windabgewandte Seite): Im Windschatten der Vogesen sinken die abgeregneten Luftmassen in den Oberrheingraben hinab, erwärmen sich trockenadiabatisch um ca. 1,0 °C pro 100 m und lösen Wolken auf (sonnenreiches, trockenes Becken- und Weinbauklima).
- Anthropogener Eingriff durch Tulla (ab 1817): Durch den Durchstich zahlreicher Mäanderschlingen verkürzte sich der Oberrhein um über 80 km; die Fließgeschwindigkeit und Tiefenerosion nahmen stark zu, während ehemalige Überschwemmungsauen trockenfielen.
- Hochwasserschutz heute (Integriertes Rheinprogramm): Rückhalteräume (Polder) entlang des Oberrheins werden bei Extremhochwasser gezielt geflutet, um Unterliegerstädte zu schützen.
- Klimawandel-Indikator: Im Oberrheingraben steigt die Zahl der Heißen Tage (> 30 °C) deutlich.

² Steigungsregen (orographischer Niederschlag): Abkühlung und Kondensation feuchter Luftmassen beim Aufstieg am Gebirge.
"""

    s1_geo_ueb = """((204))

# Kapitel 2: Der Oberrheingraben – Naturraum, Relief und Klima

## 2.1 Topographie und Grabenbruch im Südwesten

Zwischen den Mittelgebirgen Vogesen im Westen und Schwarzwald im Osten erstreckt sich der rund 300 km lange Oberrheingraben{1}. Durch die geschützte Beckenlage und die geringe Meereshöhe zählt die Region zu den wärmsten und fruchtbarsten Naturräumen Mitteleuropas.

#### Abb. 2.1: Physische und thematische Karte des Oberrheingrabens

<Bild> Karte:
Beschreibung mit Bildtext: Physische und thematische Karte des Oberrheingrabens auf OpenStreetMap-Kartengrundlage (© OpenStreetMap-Mitwirkende, ODbL 1.0) mit Gradnetz (47°N bis 49°N, 7°O bis 9°O), Windrose (N/O/S/W), Grabenbruch-Verwerfungslinien und Maßstabsleiste (Maßstab 1 : 2.500.000, 0 bis 50 km). Im Zentrum verläuft das grüne Tiefland (< 200 m) entlang des Rheins mit dem Nebenfluss Neckar und den Städten Basel, Freiburg, Straßburg und Karlsruhe; westlich liegen die Vogesen (200–800 m), östlich der Schwarzwald (> 800 m) mit dem Feldberg (1493 m).
</Bild>

### Aufgabe 1: Kartenarbeit zum Oberrheingraben

1.\tBestimme mithilfe des Maßstabs (1 : 2.500.000) und des Gradnetzes die Lage von Straßburg und Freiburg.
2.\tBeschreibe das Höhenprofil entlang des 48. nördlichen Breitengrades von West nach Ost.

<Rahmen>
_Methode: Eine physische und thematische Karte systematisch auswerten_
-\t_1. Orientierung & Thema:_ Lies zuerst Kartenüberschrift, Maßstab (1 : 2.500.000: 1 cm auf der Karte entspricht 25 km in der Wirklichkeit), Windrose und die Höhenstufen der Legende.
-\t_2. Verortung im Gradnetz:_ Bestimme geographische Breite (nördliche Breite: 47°N bis 49°N) und geographische Länge (östliche Länge: 7°O bis 9°O) der wichtigsten Städte und Flüsse.
-\t_3. Raummuster beschreiben:_ Gliedere den Naturraum in Teilräume (Tiefland der Rheinebene unter 200 m vs. steil aufragende Randgebirge Vogesen und Schwarzwald über 800 m).
-\t_4. Zusammenhänge erklären:_ Verknüpfe Relief, Gewässernetz und Siedlungsachsen (warum verlaufen Autobahnen, Eisenbahnlinien und Großstädte gebündelt entlang der Grabenachse?).
</Rahmen>

### Geologie, Lössböden und Wasserstraßen der Oberrheinebene

Beim Einsinken des Grabenbruchs lagerten der Rhein und seine Nebenflüsse mächtige Kies- und Schotterschichten ab. An den Vorbergzonen bildeten sich während der Kaltzeiten fruchtbare Lössböden. Im 19. Jahrhundert veränderte zudem die Rheinbegradigung durch Johann Gottfried Tulla den Flusslauf grundlegend und schuf die Voraussetzung für die moderne Großstadtentwicklung und Binnenschifffahrt.

<Anmerkung> 1 Tektonischer Grabenbruch: Einsenkung der Erdkruste im Tertiär entlang paralleler Verwerfungslinien. </Anmerkung>

((205))

Heute zählt die Rheinschiene zwischen Basel, Straßburg und Karlsruhe zu den wichtigsten europäischen Verkehrs- und Wirtschaftsachsen.

## 2.2 Höhenstufen und Luv-Lee-Effekt im Klimavergleich

#### Abb. 2.2a: Klimadiagramm Freiburg im Breisgau (269 m ü. NN)

<Bild> Klimadiagramm:
Beschreibung mit Bildtext: Klimadiagramm der Station Freiburg i. Br. (269 m ü. NN), Jahresmitteltemperatur 11,4 °C, Jahresniederschlag 934 mm. Die rote Temperaturkurve steigt von 2,4 °C im Januar auf 21,1 °C im Juli und fällt auf 3,1 °C im Dezember; die blauen Niederschlagsbalken erreichen ihr Maximum im Juni (106 mm).
</Bild>

#### Abb. 2.2b: Klimadiagramm Feldberg im Schwarzwald (1493 m ü. NN)

<Bild> Klimadiagramm:
Beschreibung mit Bildtext: Klimadiagramm der Station Feldberg / Schw. (1493 m ü. NN), Jahresmitteltemperatur 3,9 °C, Jahresniederschlag 1909 mm. Die rote Temperaturkurve verläuft im Winter unter 0 °C (-3,8 °C im Januar) und erreicht im Juli 11,9 °C; die blauen Niederschlagsbalken liegen ganzjährig hoch zwischen 134 mm (April) und 182 mm (Dezember).
</Bild>

Der Vergleich der beiden Klimastationen verdeutlicht den vertikalen Temperaturgradienten sowie den Steigungsregen an den Westflanken des Schwarzwalds{2}. Während Freiburg ein mildes Weinbauklima aufweist, herrscht auf dem Feldberg ein kühl-feuchtes Gebirgsklima mit fast doppeltem Jahresniederschlag.

### Aufgabe 2: Klimadiagramme vergleichen und Luv-Lee-Effekt erklären

1.\tWerte die Klimadiagramme von Freiburg (Abb. 2.2a) und Feldberg (Abb. 2.2b) nach Temperaturamplitude, Jahresmitteltemperatur und Jahresniederschlagssumme systematisch aus.
2.\tBerechne die durchschnittliche Temperaturabnahme pro 100 Höhenmeter zwischen Freiburg und Feldberg.
3.\tBegründe, warum die westlich gelegene Stadt Colmar im Lee der Vogesen nur ca. 550 mm Niederschlag erhält.

### Aufgabe 3: Flussregulierung und Hochwasserschutz am Oberrhein beurteilen

1.\tErläutere die ökologischen Folgen der Rheinbegradigung durch Tulla für Grundwasserspiegel und Auenwälder.
2.\tErkläre die Funktionsweise gesteuerter Rückhaltepolder im Rahmen des Integrierten Rheinprogramms.

<Rahmen>
_Geo-Lexikon: Luv-Lee-Effekt, Föhnwirkung und Rheinbegradigung_
-\t_Luv-Seite (Windzugewandte Seite):_ Feuchte atlantische Luftmassen werden aus Westen an den Vogesen und dem Schwarzwald zum Aufsteigen gezwungen. Dabei kühlt die Luft um ca. 0,65 °C pro 100 m ab (feuchtadiabatisch), Wolken bilden sich und es fällt Steigungsregen.
-\t_Lee-Seite (Windabgewandte Seite):_ Im Windschatten der Vogesen sinken die abgeregneten Luftmassen in den Oberrheingraben hinab, erwärmen sich trockenadiabatisch um ca. 1,0 °C pro 100 m und lösen Wolken auf (sonnenreiches, trockenes Becken- und Weinbauklima).
-\t_Anthropogener Eingriff durch Tulla (ab 1817):_ Durch den Durchstich zahlreicher Mäanderschlingen verkürzte sich der Oberrhein um über 80 km; die Fließgeschwindigkeit und Tiefenerosion nahmen stark zu, während ehemalige Überschwemmungsauen trockenfielen.
-\t_Hochwasserschutz heute (Integriertes Rheinprogramm):_ Rückhalteräume (Polder) entlang des Oberrheins werden bei Extremhochwasser gezielt geflutet, um Unterliegerstädte zu schützen.
-\t_Klimawandel-Indikator:_ Im Oberrheingraben steigt die Zahl der Heißen Tage (> 30 °C) deutlich.
</Rahmen>

<Anmerkung> 2 Steigungsregen (orographischer Niederschlag): Abkühlung und Kondensation feuchter Luftmassen beim Aufstieg am Gebirge. </Anmerkung>
"""

    # -------------------- 6. SEK I GESCHICHTE --------------------
    s1_hist_raw = """((246))

# Kapitel 3: Industrialisierung und Soziale Frage im 19. Jahrhundert

## 3.1 Zeitleiste: Industrialisierung im Deutschen Bund und Kaiserreich

![Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)](figures/hist_zeitleiste_industrialisierung.png)

Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)

Der Übergang von der Agrar- zur Industriegesellschaft führte zu einem rasanten Städtewachstum (Urbanisierung) und verschärfte die soziale Lage der Fabrikarbeiterschaft¹. Als Leitsektoren der Frühindustrialisierung wirkten der Eisenbahnbau, der Steinkohlenbergbau und die Eisenverhüttung.

### Tabelle 3.1: Streckennetz der Eisenbahn, Steinkohlenförderung und Urbanisierung (1840–1910)

| Jahr | Eisenbahnnetz (km) | Steinkohle (Mio. t) | Einwohner Essen | Einwohner Mannheim |
| :--- | :--- | :--- | :--- | :--- |
| 1840 | 469 km | 3,2 Mio. t | 6.300 | 22.800 |
| 1871 | 21.471 km | 29,4 Mio. t | 51.500 | 39.600 |
| 1910 | 61.209 km | 152,8 Mio. t | 294.600 | 193.900 |

**Historisches Grundwissen: Von der Früh- zur Hochindustrialisierung**
- 1. Vorbedingungen (ab 1834): Die Gründung des Deutschen Zollvereins (1834) beseitigte Binnenzölle und schuf einen einheitlichen Wirtschaftsraum für Handel und Gewerbe.
- 2. Frühindustrialisierung (1835–1870): Mit der ersten deutschen Eisenbahn zwischen Nürnberg und Fürth (1835) entstand ein starker Nachfrageschub nach Lokomotiven, Schienen und Kohle.
- 3. Hochindustrialisierung (ab 1871): Nach der Reichsgründung stieg Deutschland durch neue Leitindustrien (Chemieindustrie am Rhein, Elektrotechnik, Maschinenbau) zur führenden Industrienation Europas auf. Gleichzeitig wuchsen Industriestädte wie Essen sprunghaft an.
- 4. Soziale Folgeprobleme: Wohnungsnot in Mietskasernen, 12- bis 14-Stunden-Schichten und fehlende Absicherung bei Krankheit oder Unfall führten zur Entstehung der Arbeiterbewegung.

### Aufgabe 1 ◈: Statistik und Zeitleiste zur Industrialisierung auswerten

1. Beschreibe anhand von Abb. 3.1 und Tabelle 3.1 den Zusammenhang zwischen Eisenbahnbau und Kohleförderung.
2. Vergleiche das Bevölkerungswachstum der Ruhrmetropole Essen mit der Rheinhafenstadt Mannheim (1840–1910).
3. Erkläre, warum Historiker den Eisenbahnbau als „Lokomotive der Industrialisierung“ bezeichnen.

¹ Soziale Frage: Bezeichnung für die wirtschaftlichen und gesellschaftlichen Missstände der Industriearbeiterschaft im 19. Jh.

((247))

## 3.2 Historische Quellen im Vergleich: Arbeitsalltag in der Fabrik

**M1: Bericht eines Fabrikinspektors (1878)**
„In den mechanischen Websälen beginnt die tägliche Schicht um sechs Uhr früh und endet erst um acht Uhr abends. Der ohrenbetäubende Lärm der Webstühle und die feuchte, staubige Luft beanspruchen die Gesundheit der Arbeiter über die Maßen.“

**M2: Erinnerungen einer Textilarbeiterin (1884)**
„Wer fünf Minuten nach dem Werksignal am Fabriktor erscheint, dem wird ein Viertel des Tageslohns abgezogen. Dennoch hoffen wir auf den neuen Arbeiterbildungsverein, der kürzere Arbeitszeiten und Sicherheit an den Maschinen fordert.“

### Aufgabe 2 ◇: Quellenvergleich M1 und M2

1. Arbeite aus M1 und M2 die Arbeitsbedingungen in den Textilfabriken heraus.
2. Vergleiche die Perspektive des staatlichen Fabrikinspektors (M1) mit der Sicht der Arbeiterin (M2).

**M3: Auszug aus der Kaiserlichen Botschaft zur Sozialgesetzgebung (17. November 1881)**
„Schon im Februar dieses Jahres haben Wir Unsere Überzeugung aussprechen lassen, dass die Heilung der sozialen Schäden nicht ausschließlich im Wege der Repression sozialdemokratischer Ausschreitungen, sondern gleichmäßig auf dem der positiven Förderung des Wohles der Arbeiter zu suchen sein werde. [...] Diejenigen, welche durch Alter oder Invalidität erwerbsunfähig werden, haben der Gesamtheit gegenüber einen begründeten Anspruch auf staatliche Fürsorge.“

### Aufgabe 3 ◆: Historisches Urteil zur Bismarck’schen Sozialgesetzgebung

1. Erläutere anhand von M3 die doppelte Zielsetzung („Zuckerbrot und Peitsche“) der Sozialpolitik ab 1881.
2. Beurteile, inwiefern die Kranken- (1883), Unfall- (1884) und Rentenversicherung (1889) die in M1 und M2 geschilderten Missstände im Fabrikalltag lösen konnten.

**Methode: Schriftliche historische Quellen kritisch analysieren und vergleichen**
- 1. Äußere Quellenkritik (Einordnung): Wer ist der Verfasser (Stellung, Amt, soziale Schicht)? Wann und wo ist die Quelle entstanden? An welchen Adressatenkreis richtet sich der Text?
- 2. Textsorte bestimmen: Handelt es sich um einen amtlichen Verwaltungsbericht (M1), ein persönliches Selbstzeugnis / Erinnerungen (M2) oder eine offizielle Regierungserklärung (M3)?
- 3. Inhaltsanalyse: Fasse die Kernaussagen und Schlüsselbegriffe mit eigenen Worten zusammen.
- 4. Innere Quellenkritik (Standortgebundenheit & Intention): Welche Interessen verfolgt der Autor? Was wird bewusst betont, beschönigt oder verschwiegen?
- 5. Mehrperspektivischer Vergleich: Stelle Gemeinsamkeiten und Widersprüche zwischen den Quellen gegenüber und ordne sie in den historischen Gesamtzusammenhang des Kaiserreichs ein.
- Merke: Erst das Zusammenspiel mehrerer Perspektiven ermöglicht ein ausgewogenes Sachurteil!
"""

    s1_hist_ueb = """((246))

# Kapitel 3: Industrialisierung und Soziale Frage im 19. Jahrhundert

## 3.1 Zeitleiste: Industrialisierung im Deutschen Bund und Kaiserreich

#### Abb. 3.1: Zeitleiste zur Industrialisierung und Urbanisierung in Deutschland (1835–1914)

<Bild> Zeitleiste:
Beschreibung mit Bildtext: 1835 Erste Eisenbahn (Nürnberg–Fürth) \\to 1848 Märzrevolution (Verfassungsforderung) \\to 1871 Reichsgründung (Hochindustrialisierung) \\to 1883–89 Sozialgesetze (Kranken- & Rentenvers.) \\to 1914 Vorabend 1. WK (Elektro- & Chemieindustrie).
</Bild>

Der Übergang von der Agrar- zur Industriegesellschaft führte zu einem rasanten Städtewachstum (Urbanisierung) und verschärfte die soziale Lage der Fabrikarbeiterschaft{1}. Als Leitsektoren der Frühindustrialisierung wirkten der Eisenbahnbau, der Steinkohlenbergbau und die Eisenverhüttung.

### Tabelle 3.1: Streckennetz der Eisenbahn, Steinkohlenförderung und Urbanisierung (1840–1910)

<Tabelle>
Jahr\tEisenbahnnetz (km)\tSteinkohle (Mio. t)\tEinwohner Essen\tEinwohner Mannheim
1840\t469 km\t3,2 Mio. t\t6.300\t22.800
1871\t21.471 km\t29,4 Mio. t\t51.500\t39.600
1910\t61.209 km\t152,8 Mio. t\t294.600\t193.900
</Tabelle>

<Rahmen>
_Historisches Grundwissen: Von der Früh- zur Hochindustrialisierung_
-\t_1. Vorbedingungen (ab 1834):_ Die Gründung des Deutschen Zollvereins (1834) beseitigte Binnenzölle und schuf einen einheitlichen Wirtschaftsraum für Handel und Gewerbe.
-\t_2. Frühindustrialisierung (1835–1870):_ Mit der ersten deutschen Eisenbahn zwischen Nürnberg und Fürth (1835) entstand ein starker Nachfrageschub nach Lokomotiven, Schienen und Kohle.
-\t_3. Hochindustrialisierung (ab 1871):_ Nach der Reichsgründung stieg Deutschland durch neue Leitindustrien (Chemieindustrie am Rhein, Elektrotechnik, Maschinenbau) zur führenden Industrienation Europas auf. Gleichzeitig wuchsen Industriestädte wie Essen sprunghaft an.
-\t_4. Soziale Folgeprobleme:_ Wohnungsnot in Mietskasernen, 12- bis 14-Stunden-Schichten und fehlende Absicherung bei Krankheit oder Unfall führten zur Entstehung der Arbeiterbewegung.
</Rahmen>

### Aufgabe 1: Statistik und Zeitleiste zur Industrialisierung auswerten
[mittel]

1.\tBeschreibe anhand von Abb. 3.1 und Tabelle 3.1 den Zusammenhang zwischen Eisenbahnbau und Kohleförderung.
2.\tVergleiche das Bevölkerungswachstum der Ruhrmetropole Essen mit der Rheinhafenstadt Mannheim (1840–1910).
3.\tErkläre, warum Historiker den Eisenbahnbau als „Lokomotive der Industrialisierung“ bezeichnen.

<Anmerkung> 1 Soziale Frage: Bezeichnung für die wirtschaftlichen und gesellschaftlichen Missstände der Industriearbeiterschaft im 19. Jh. </Anmerkung>

((247))

## 3.2 Historische Quellen im Vergleich: Arbeitsalltag in der Fabrik

<Rahmen>
_M1: Bericht eines Fabrikinspektors (1878)_
„In den mechanischen Websälen beginnt die tägliche Schicht um sechs Uhr früh und endet erst um acht Uhr abends. Der ohrenbetäubende Lärm der Webstühle und die feuchte, staubige Luft beanspruchen die Gesundheit der Arbeiter über die Maßen.“
</Rahmen>

<Rahmen>
_M2: Erinnerungen einer Textilarbeiterin (1884)_
„Wer fünf Minuten nach dem Werksignal am Fabriktor erscheint, dem wird ein Viertel des Tageslohns abgezogen. Dennoch hoffen wir auf den neuen Arbeiterbildungsverein, der kürzere Arbeitszeiten und Sicherheit an den Maschinen fordert.“
</Rahmen>

### Aufgabe 2: Quellenvergleich M1 und M2
[leicht]

1.\tArbeite aus M1 und M2 die Arbeitsbedingungen in den Textilfabriken heraus.
2.\tVergleiche die Perspektive des staatlichen Fabrikinspektors (M1) mit der Sicht der Arbeiterin (M2).

<Rahmen>
_M3: Auszug aus der Kaiserlichen Botschaft zur Sozialgesetzgebung (17. November 1881)_
„Schon im Februar dieses Jahres haben Wir Unsere Überzeugung aussprechen lassen, dass die Heilung der sozialen Schäden nicht ausschließlich im Wege der Repression sozialdemokratischer Ausschreitungen, sondern gleichmäßig auf dem der positiven Förderung des Wohles der Arbeiter zu suchen sein werde. [...] Diejenigen, welche durch Alter oder Invalidität erwerbsunfähig werden, haben der Gesamtheit gegenüber einen begründeten Anspruch auf staatliche Fürsorge.“
</Rahmen>

### Aufgabe 3: Historisches Urteil zur Bismarck’schen Sozialgesetzgebung
[schwer]

1.\tErläutere anhand von M3 die doppelte Zielsetzung („Zuckerbrot und Peitsche“) der Sozialpolitik ab 1881.
2.\tBeurteile, inwiefern die Kranken- (1883), Unfall- (1884) und Rentenversicherung (1889) die in M1 und M2 geschilderten Missstände im Fabrikalltag lösen konnten.

<Rahmen>
_Methode: Schriftliche historische Quellen kritisch analysieren und vergleichen_
-\t_1. Äußere Quellenkritik (Einordnung):_ Wer ist der Verfasser (Stellung, Amt, soziale Schicht)? Wann und wo ist die Quelle entstanden? An welchen Adressatenkreis richtet sich der Text?
-\t_2. Textsorte bestimmen:_ Handelt es sich um einen amtlichen Verwaltungsbericht (M1), ein persönliches Selbstzeugnis / Erinnerungen (M2) oder eine offizielle Regierungserklärung (M3)?
-\t_3. Inhaltsanalyse:_ Fasse die Kernaussagen und Schlüsselbegriffe mit eigenen Worten zusammen.
-\t_4. Innere Quellenkritik (Standortgebundenheit & Intention):_ Welche Interessen verfolgt der Autor? Was wird bewusst betont, beschönigt oder verschwiegen?
-\t_5. Mehrperspektivischer Vergleich:_ Stelle Gemeinsamkeiten und Widersprüche zwischen den Quellen gegenüber und ordne sie in den historischen Gesamtzusammenhang des Kaiserreichs ein.
-\t_Merke:_ Erst das Zusammenspiel mehrerer Perspektiven ermöglicht ein ausgewogenes Sachurteil!
</Rahmen>
"""

    # -------------------- 7. SEK II CHEMIE --------------------
    s2_chem_raw = r"""((310))

# Kapitel 4: Chemisches Gleichgewicht, Veresterung und Redoxreaktionen

## 4.1 Säurekatalysierte Veresterung und dynamisches Gleichgewicht

Carbonsäuren reagieren mit Alkoholen unter Säurekatalyse zu fruchtig riechenden Estern und Wasser. Im Gegensatz zu vielen Fällungsreaktionen verläuft diese Kondensation unvollständig: Gleichzeitig spaltet das gebildete Wasser den Ester in einer Rückreaktion (Hydrolyse) wieder in Säure und Alkohol. Sobald die Reaktionsgeschwindigkeiten von Hin- und Rückreaktion exakt übereinstimmen ($v_{\text{hin}} = v_{\text{rück}}$), befindet sich das geschlossene System im dynamischen chemischen Gleichgewicht. Die Stoffmengenkonzentrationen bleiben konstant.

**Versuchsprotokoll V4.1 – Gefahrstoffhinweise:** GHS02 GHS05 GHS07
- Materialien & Chemikalien: Reagenzgläser, Wasserbad (80 °C), Ethansäure ($\text{CH}_3\text{COOH}$), Ethanol ($\text{C}_2\text{H}_5\text{OH}$), konzentrierte Schwefelsäure ($\text{H}_2\text{SO}_4$, Katalysator), Kaliumdichromat-Lösung ($\text{K}_2\text{Cr}_2\text{O}_7$).
- Durchführung: 3 mL Ethansäure und 3 mL Ethanol werden mit 5 Tropfen konz. $\text{H}_2\text{SO}_4$ vorsichtig im Wasserbad erwärmt. Anschließend wird das Gemisch auf Eiswasser gegeben.
- Beobachtung: Es bildet sich eine obere, fruchtig nach Klebstoff riechende organische Phase.
- Auswertung: Es stellt sich ein dynamisches Veresterungsgleichgewicht ein.

### Reaktionsgleichungen, Ionenladungen und Oxidationszahlen

1. Veresterungsgleichgewicht (Katalyse durch Oxonium-Ionen $\text{H}_3\text{O}^+$):

$$\text{CH}_3\text{COOH} + \text{C}_2\text{H}_5\text{OH} \rightleftharpoons \text{CH}_3\text{COOC}_2\text{H}_5 + \text{H}_2\text{O} \quad (\Delta H^\circ \approx -4\,\text{kJ/mol})$$

2. Redoxreaktion von Dichromat-Ionen mit Eisen(II)-Ionen in saurer Lösung:

$$\overset{+\text{VI}}{\text{Cr}}_2\overset{-\text{II}}{\text{O}}_7^{2-} + 14\,\text{H}_3\text{O}^+ + 6\,\overset{+\text{II}}{\text{Fe}}^{2+} \longrightarrow 2\,\overset{+\text{III}}{\text{Cr}}^{3+} + 6\,\overset{+\text{III}}{\text{Fe}}^{3+} + 21\,\text{H}_2\text{O}$$

3. Großtechnische Gleichgewichtsreaktion (Kontaktverfahren):

$$2\,\text{SO}_2\text{(g)} + \text{O}_2\text{(g)} \xrightarrow{\text{Kat., } 450\,^\circ\text{C}} 2\,\text{SO}_3\text{(g)}$$

### Reaktionsmechanismus der säurekatalysierten Veresterung (Addition-Eliminierung)

- Schritt 1 (Protonierung): Ein Oxonium-Ion ($\text{H}_3\text{O}^+$) überträgt ein Proton auf den Carbonylsauerstoff der Ethansäure. Dadurch erhöht sich die positive Teilladung am Carbonyl-C-Atom.
- Schritt 2 (Nukleophiler Angriff): Das freie Elektronenpaar des Ethanol-Sauerstoffatoms greift das elektrophile Carbonyl-C-Atom unter Bildung einer tetraedrischen Zwischenstufe an.
- Schritt 3 (Eliminierung): Nach Protonenwanderung wird $\text{H}_2\text{O}$ abgespalten ($\text{H}^+$-Regeneration).

**Sicherheit im Chemielabor: Umgang mit Mineralsäuren und Oxidationsmitteln**
- Schutzkleidung: Bei allen Experimenten mit konzentrierter Schwefelsäure ($\text{H}_2\text{SO}_4$) und Dichromaten sind Schutzbrille, Laborkittel und Schutzhandschuhe zwingend zu tragen.
- Verdünnungsregel für konzentrierte Schwefelsäure: „Erst das Wasser, dann die Säure, sonst geschieht das Ungeheure!“ Wegen der stark exothermen Hydratation niemals Wasser in konz. $\text{H}_2\text{SO}_4$ gießen.
- Brandschutz: Ethanol und Ethylethanoat sind leicht entzündbare Flüssigkeiten (GHS02); daher erfolgt das Erwärmen im Schülerversuch ausschließlich im elektrisch beheizten Wasserbad (80 °C).
- Fachgerechte Entsorgung: Chrom(VI)-haltige Lösungen ($\text{K}_2\text{Cr}_2\text{O}_7$) müssen im sauren Medium vollständig zu Chrom(III)-Ionen reduziert und im Sammelbehälter für Schwermetallsalze entsorgt werden.
- Erste Hilfe: Säurespritzer auf der Haut sofort mit reichlich fließendem Wasser abspülen.

((311))

## 4.2 Strukturformeln und Massenwirkungsgesetz (MWG)

![Abb. 4.1: Strukturformeln der säurekatalysierten Veresterung und der alpha-D-Glucopyranose](figures/chem_strukturformeln_veresterung_glucose.png)

Abb. 4.1: Strukturformeln der säurekatalysierten Veresterung und der $\alpha$-D-Glucopyranose

Im dynamischen Gleichgewicht ist der Quotient aus dem Produkt der Gleichgewichtskonzentrationen der Produkte und dem Produkt der Eduktkonzentrationen bei konstanter Temperatur unveränderlich. Diese quantitative Beziehung heißt Massenwirkungsgesetz (MWG): Für die Veresterung von Ethansäure mit Ethanol beträgt die Gleichgewichtskonstante bei Raumtemperatur $K_c \approx 4{,}0$. Durch gezieltes Entfernen eines Reaktionsprodukts aus dem Gleichgewichtsgemisch lässt sich die Ausbeute an Ethylethanoat im Labor deutlich steigern.

$$K_c = \frac{c(\text{CH}_3\text{COOC}_2\text{H}_5) \cdot c(\text{H}_2\text{O})}{c(\text{CH}_3\text{COOH}) \cdot c(\text{C}_2\text{H}_5\text{OH})} \approx 4{,}0$$

### Aufgaben zur Redoxchemie und zum chemischen Gleichgewicht

- ○ Aufgabe 1: Bestimmen Sie alle Oxidationszahlen in $\text{Cr}_2\text{O}_7^{2-}$, $\text{SO}_2$ und $\text{SO}_3$.
- ◐ Aufgabe 2: Formulieren Sie die Teilgleichungen der Oxidation und Reduktion für Versuch V4.1.
- ● Aufgabe 3: Berechnen Sie die Gleichgewichtskonzentration an Ethylethanoat bei einem Ausgangsansatz von jeweils $1{,}0\,\text{mol}$ Ethansäure und $1{,}0\,\text{mol}$ Ethanol ($K_c = 4{,}0$).

**Beispielrechnung: Gleichgewichtskonstante Kc und Gleichgewichtsausbeute**
- Ansatz im geschlossenen System: $n_0(\text{CH}_3\text{COOH}) = 1{,}0\,\text{mol}$ und $n_0(\text{C}_2\text{H}_5\text{OH}) = 1{,}0\,\text{mol}$ (Volumen $V$ kürzt sich heraus).
- Im Gleichgewicht seien $x\,\text{mol}$ Ester und $x\,\text{mol}$ Wasser entstanden; es verbleiben $(1{,}0 - x)\,\text{mol}$ Säure und Alkohol.
- Einsetzen in das Massenwirkungsgesetz: $K_c = \frac{x^2}{(1{,}0 - x)^2} = 4{,}0$.
- Ziehen der Quadratwurzel auf beiden Seiten: $\frac{x}{1{,}0 - x} = 2{,}0 \implies x = 2{,}0 - 2{,}0x \implies 3{,}0x = 2{,}0$.
- Ergebnis: Im Gleichgewicht liegen $n(\text{Ester}) = n(\text{H}_2\text{O}) = \frac{2}{3}\,\text{mol} \approx 0{,}67\,\text{mol}$ (Ausbeute 66,7 %) sowie jeweils $0{,}33\,\text{mol}$ unverbrauchte Ethansäure und Ethanol vor.
- Ausbeutesteigerung im Labor: Durch kontinuierliches Abdestillieren des leichtflüchtigen Esters (Sdp. 77 °C).

**Merksatz: Prinzip von Le Chatelier (Prinzip vom kleinsten Zwang)**
- Übt man auf ein chemisches System im Gleichgewicht durch Änderung von Konzentration, Druck oder Temperatur einen äußeren Zwang aus, so verschiebt sich die Gleichgewichtslage so, dass die Wirkung des äußeren Zwangs minimiert wird.
- Temperaturerhöhung begünstigt stets die endotherme Teilreaktion; Temperaturerniedrigung begünstigt die exotherme Teilreaktion (z. B. $\text{SO}_3$-Bildung im Kontaktverfahren bei 450 °C).
- Ein Katalysator setzt die Aktivierungsenergie $E_A$ herab, verändert aber niemals die Gleichgewichtskonstante $K_c$!
"""

    s2_chem_ueb = """((310))

# Kapitel 4: Chemisches Gleichgewicht, Veresterung und Redoxreaktionen

## 4.1 Säurekatalysierte Veresterung und dynamisches Gleichgewicht

Carbonsäuren reagieren mit Alkoholen unter Säurekatalyse zu fruchtig riechenden Estern und Wasser. Im Gegensatz zu vielen Fällungsreaktionen verläuft diese Kondensation unvollständig: Gleichzeitig spaltet das gebildete Wasser den Ester in einer Rückreaktion (Hydrolyse) wieder in Säure und Alkohol. Sobald die Reaktionsgeschwindigkeiten von Hin- und Rückreaktion exakt übereinstimmen ($v_{\\text{hin}} = v_{\\text{rück}}$), befindet sich das geschlossene System im dynamischen chemischen Gleichgewicht. Die Stoffmengenkonzentrationen bleiben konstant.

<Rahmen>
_Versuchsprotokoll V4.1 – Gefahrstoffhinweise:_ [Gefahrstoffsymbol: Entzündbar] [Gefahrstoffsymbol: Ätzend] [Gefahrstoffsymbol: Achtung]
-\t_Materialien & Chemikalien:_ Reagenzgläser, Wasserbad ($80\\,^\\circ\\text{C}$), Ethansäure ($\\text{CH}_3\\text{COOH}$), Ethanol ($\\text{C}_2\\text{H}_5\\text{OH}$), konzentrierte Schwefelsäure ($\\text{H}_2\\text{SO}_4$, Katalysator), Kaliumdichromat-Lösung ($\\text{K}_2\\text{Cr}_2\\text{O}_7$).
-\t_Durchführung:_ 3 mL Ethansäure und 3 mL Ethanol werden mit 5 Tropfen konz. $\\text{H}_2\\text{SO}_4$ vorsichtig im Wasserbad erwärmt. Anschließend wird das Gemisch auf Eiswasser gegeben.
-\t_Beobachtung:_ Es bildet sich eine obere, fruchtig nach Klebstoff riechende organische Phase.
-\t_Auswertung:_ Es stellt sich ein dynamisches Veresterungsgleichgewicht ein.
</Rahmen>

### Reaktionsgleichungen, Ionenladungen und Oxidationszahlen

1.\tVeresterungsgleichgewicht (Katalyse durch Oxonium-Ionen $\\text{H}_3\\text{O}^+$):

$$\\text{CH}_3\\text{COOH} + \\text{C}_2\\text{H}_5\\text{OH} \\rightleftharpoons \\text{CH}_3\\text{COOC}_2\\text{H}_5 + \\text{H}_2\\text{O} \\quad (\\Delta H^\\circ \\approx -4\\,\\text{kJ/mol})$$

2.\tRedoxreaktion von Dichromat-Ionen mit Eisen(II)-Ionen in saurer Lösung:

$$\\overset{+\\text{VI}}{\\text{Cr}}_2\\overset{-\\text{II}}{\\text{O}}_7^{2-} + 14\\,\\text{H}_3\\text{O}^+ + 6\\,\\overset{+\\text{II}}{\\text{Fe}}^{2+} \\longrightarrow 2\\,\\overset{+\\text{III}}{\\text{Cr}}^{3+} + 6\\,\\overset{+\\text{III}}{\\text{Fe}}^{3+} + 21\\,\\text{H}_2\\text{O}$$

3.\tGroßtechnische Gleichgewichtsreaktion (Kontaktverfahren):

$$2\\,\\text{SO}_2\\text{(g)} + \\text{O}_2\\text{(g)} \\xrightarrow{\\text{Kat., } 450\\,^\\circ\\text{C}} 2\\,\\text{SO}_3\\text{(g)}$$

### Reaktionsmechanismus der säurekatalysierten Veresterung (Addition-Eliminierung)

-\t_Schritt 1 (Protonierung):_ Ein Oxonium-Ion ($\\text{H}_3\\text{O}^+$) überträgt ein Proton auf den Carbonylsauerstoff der Ethansäure. Dadurch erhöht sich die positive Teilladung am Carbonyl-C-Atom.
-\t_Schritt 2 (Nukleophiler Angriff):_ Das freie Elektronenpaar des Ethanol-Sauerstoffatoms greift das elektrophile Carbonyl-C-Atom unter Bildung einer tetraedrischen Zwischenstufe an.
-\t_Schritt 3 (Eliminierung):_ Nach Protonenwanderung wird $\\text{H}_2\\text{O}$ abgespalten ($\\text{H}^+$-Regeneration).

<Rahmen>
_Sicherheit im Chemielabor: Umgang mit Mineralsäuren und Oxidationsmitteln_
-\t_Schutzkleidung:_ Bei allen Experimenten mit konzentrierter Schwefelsäure ($\\text{H}_2\\text{SO}_4$) und Dichromaten sind Schutzbrille, Laborkittel und Schutzhandschuhe zwingend zu tragen.
-\t_Verdünnungsregel für konzentrierte Schwefelsäure:_ „Erst das Wasser, dann die Säure, sonst geschieht das Ungeheure!“ Wegen der stark exothermen Hydratation niemals Wasser in konz. $\\text{H}_2\\text{SO}_4$ gießen.
-\t_Brandschutz:_ Ethanol und Ethylethanoat sind leicht entzündbare Flüssigkeiten (GHS02); daher erfolgt das Erwärmen im Schülerversuch ausschließlich im elektrisch beheizten Wasserbad ($80\\,^\\circ\\text{C}$).
-\t_Fachgerechte Entsorgung:_ Chrom(VI)-haltige Lösungen ($\\text{K}_2\\text{Cr}_2\\text{O}_7$) müssen im sauren Medium vollständig zu Chrom(III)-Ionen reduziert und im Sammelbehälter für Schwermetallsalze entsorgt werden.
-\t_Erste Hilfe:_ Säurespritzer auf der Haut sofort mit reichlich fließendem Wasser abspülen.
</Rahmen>

((311))

## 4.2 Strukturformeln und Massenwirkungsgesetz (MWG)

#### Abb. 4.1: Strukturformeln der säurekatalysierten Veresterung und der $\\alpha$-D-Glucopyranose

<Bild> Strukturformel:
Beschreibung mit Bildtext: Zweiteilige Darstellung organischer Strukturformeln. Teil A zeigt die säurekatalysierte Veresterung in Skelettformeln mit farbig hervorgehobenen funktionellen Gruppen: Ethansäure ($\\text{CH}_3\\text{COOH}$) + Ethanol ($\\text{C}_2\\text{H}_5\\text{OH}$) $\\rightleftharpoons$ Ethylethanoat ($\\text{CH}_3\\text{COOC}_2\\text{H}_5$) + $\\text{H}_2\\text{O}$ unter $\\text{H}^+$-Katalyse ($K_c \\approx 4{,}0$). Teil B zeigt die Haworth-Ringformel der $\\alpha$-D-Glucopyranose mit sechsgliedrigem Pyranosering, Ringsauerstoffatom, axialer OH-Gruppe an C1 ($\\alpha$-Stellung) und $\\text{CH}_2\\text{OH}$-Gruppe an C6.
</Bild>

Im dynamischen Gleichgewicht ist der Quotient aus dem Produkt der Gleichgewichtskonzentrationen der Produkte und dem Produkt der Eduktkonzentrationen bei konstanter Temperatur unveränderlich. Diese quantitative Beziehung heißt Massenwirkungsgesetz (MWG): Für die Veresterung von Ethansäure mit Ethanol beträgt die Gleichgewichtskonstante bei Raumtemperatur $K_c \\approx 4{,}0$. Durch gezieltes Entfernen eines Reaktionsprodukts aus dem Gleichgewichtsgemisch lässt sich die Ausbeute an Ethylethanoat im Labor deutlich steigern.

$$K_c = \\frac{c(\\text{CH}_3\\text{COOC}_2\\text{H}_5) \\cdot c(\\text{H}_2\\text{O})}{c(\\text{CH}_3\\text{COOH}) \\cdot c(\\text{C}_2\\text{H}_5\\text{OH})} \\approx 4{,}0$$

### Aufgaben zur Redoxchemie und zum chemischen Gleichgewicht

-\t[leicht] Aufgabe 1: Bestimmen Sie alle Oxidationszahlen in $\\text{Cr}_2\\text{O}_7^{2-}$, $\\text{SO}_2$ und $\\text{SO}_3$.
-\t[mittel] Aufgabe 2: Formulieren Sie die Teilgleichungen der Oxidation und Reduktion für Versuch V4.1.
-\t[schwer] Aufgabe 3: Berechnen Sie die Gleichgewichtskonzentration an Ethylethanoat bei einem Ausgangsansatz von jeweils $1{,}0\\,\\text{mol}$ Ethansäure und $1{,}0\\,\\text{mol}$ Ethanol ($K_c = 4{,}0$).

<Rahmen>
_Beispielrechnung: Gleichgewichtskonstante Kc und Gleichgewichtsausbeute_
-\tAnsatz im geschlossenen System: $n_0(\\text{CH}_3\\text{COOH}) = 1{,}0\\,\\text{mol}$ und $n_0(\\text{C}_2\\text{H}_5\\text{OH}) = 1{,}0\\,\\text{mol}$ (Volumen $V$ kürzt sich heraus).
-\tIm Gleichgewicht seien $x\\,\\text{mol}$ Ester und $x\\,\\text{mol}$ Wasser entstanden; es verbleiben $(1{,}0 - x)\\,\\text{mol}$ Säure und Alkohol.
-\tEinsetzen in das Massenwirkungsgesetz: $K_c = \\frac{x^2}{(1{,}0 - x)^2} = 4{,}0$.
-\tZiehen der Quadratwurzel auf beiden Seiten: $\\frac{x}{1{,}0 - x} = 2{,}0 \\implies x = 2{,}0 - 2{,}0x \\implies 3{,}0x = 2{,}0$.
-\tErgebnis: Im Gleichgewicht liegen $n(\\text{Ester}) = n(\\text{H}_2\\text{O}) = \\frac{2}{3}\\,\\text{mol} \\approx 0{,}67\\,\\text{mol}$ (Ausbeute 66,7 %) sowie jeweils $0{,}33\\,\\text{mol}$ unverbrauchte Ethansäure und Ethanol vor.
-\tAusbeutesteigerung im Labor: Durch kontinuierliches Abdestillieren des leichtflüchtigen Esters (Siedepunkt $77\\,^\\circ\\text{C}$).
</Rahmen>

<Rahmen>
_Merksatz: Prinzip von Le Chatelier (Prinzip vom kleinsten Zwang)_
-\tÜbt man auf ein chemisches System im Gleichgewicht durch Änderung von Konzentration, Druck oder Temperatur einen äußeren Zwang aus, so verschiebt sich die Gleichgewichtslage so, dass die Wirkung des äußeren Zwangs minimiert wird.
-\tTemperaturerhöhung begünstigt stets die endotherme Teilreaktion; Temperaturerniedrigung begünstigt die exotherme Teilreaktion (z. B. $\\text{SO}_3$-Bildung im Kontaktverfahren bei $450\\,^\\circ\\text{C}$).
-\tEin Katalysator setzt die Aktivierungsenergie $E_A$ herab, verändert aber niemals die Gleichgewichtskonstante $K_c$!
</Rahmen>
"""

    # -------------------- 8. SEK II BIOLOGIE --------------------
    s2_bio_raw = r"""((412))

# Kapitel 6: Biokatalyse, Enzymkinetik und Stoffwechselregulation

## 6.1 Molekulare Wirkungsweise von Enzymen und Michaelis-Menten-Kinetik

![Abb. 6.1: Michaelis-Menten-Kinetik und Kompetitive Hemmung](figures/bio_michaelis_menten_kinetik.png)

Abb. 6.1: Michaelis-Menten-Kinetik und Kompetitive Hemmung

Enzyme wirken als hochspezifische Biokatalysatoren, indem sie das Substrat im aktiven Zentrum nach dem Induced-Fit-Modell binden und die Aktivierungsenergie $E_A$ über einen Enzym-Substrat-Komplex $[ES]$ herabsetzen. Die Abhängigkeit der Reaktionsgeschwindigkeit $v$ von der Substratkonzentration $[S]$ folgt der Michaelis-Menten-Gleichung. Bei niedrigen Konzentrationen steigt $v$ nahezu linear an, während bei hohen Substratkonzentrationen alle aktiven Zentren der Enzymmoleküle gesättigt sind und $v_{\max}$ asymptotisch erreicht wird:

$$v = \frac{v_{\max} \cdot [S]}{K_M + [S]}$$

**Bio-Kompakt: Bedeutung der Michaelis-Konstante K_M und Formen der Enzymhemmung**
- Michaelis-Konstante $K_M$: Gibt genau diejenige Substratkonzentration $[S]$ (in mmol/L) an, bei der die Hälfte der Maximalgeschwindigkeit ($v = \frac{1}{2}\,v_{\max}$) erreicht wird. Ein kleiner $K_M$-Wert bedeutet eine hohe Affinität (Bindungsstärke) des Enzyms zu seinem Substrat.
- Kompetitive Hemmung (Verdrängungshemmung): Der Inhibitor ähnelt strukturell dem Substrat und konkurriert um das aktive Zentrum. Die scheinbare Michaelis-Konstante $K_M'$ ist erhöht; durch hohe Substratkonzentrationen $[S]$ lässt sich der Hemmstoff jedoch verdrängen ($v_{\max}$ bleibt gleich).
- Allosterische (nicht-kompetitive) Hemmung: Der Effektor bindet außerhalb des aktiven Zentrums an ein allosterisches Zentrum und verändert die räumliche Konformation des Enzyms. Dadurch sinkt die Maximalgeschwindigkeit $v_{\max}$, während $K_M$ unverändert bleibt.
- Irreversible Hemmung (Enzymgifte): Schwermetall-Ionen (z. B. $\text{Pb}^{2+}$, $\text{Hg}^{2+}$, $\text{Cu}^{2+}$) bilden kovalente Bindungen mit Schwefelgruppen (-SH) der Aminosäure Cystein und inaktivieren das Enzym dauerhaft.
- Beispiel Katalase: Spaltet Wasserstoffperoxid ($2\,\text{H}_2\text{O}_2 \longrightarrow 2\,\text{H}_2\text{O} + \text{O}_2$) mit hoher Wechselzahl.

### Tabelle 6.1: Messreihe zur Substratabhängigkeit der Katalase-Aktivität

| Substrat $[S]$ (mmol/L) | $v$ ohne Hemmstoff ($\mu\text{mol/min}$) | $v$ mit Hemmstoff ($\mu\text{mol/min}$) | Sättigungsgrad (%) |
| :--- | :--- | :--- | :--- |
| 0,5 | 18,2 | 8,4 | 22,8 % |
| 1,0 | 32,0 | 15,1 | 40,0 % |
| 2,0 | 48,0 | 25,6 | 60,0 % |

((413))

| Substrat $[S]$ (mmol/L) | $v$ ohne Hemmstoff ($\mu\text{mol/min}$) | $v$ mit Hemmstoff ($\mu\text{mol/min}$) | Sättigungsgrad (%) |
| :--- | :--- | :--- | :--- |
| 4,0 | 61,5 | 38,8 | 76,9 % |
| 8,0 | 71,1 | 53,3 | 88,9 % |
| 16,0 | 76,2 | 65,5 | 95,3 % |
| 32,0 | 78,8 | 73,1 | 98,5 % |

## 6.2 Abhängigkeit der Enzymaktivität von Temperatur und pH-Wert

Neben der Substratkonzentration bestimmen Temperatur und pH-Wert die räumliche Tertiärstruktur von Enzymproteinen. Nach der RGT-Regel (Reaktionsgeschwindigkeit-Temperatur-Regel) erhöht eine Temperatursteigerung um 10 °C die Umsatzrate zunächst um das 2- bis 3-Fache ($Q_{10} \approx 2\text{–}3$), da die kinetische Energie der Teilchen zunimmt. Oberhalb des Temperaturoptimums (beim Menschen ca. 37 °C–40 °C) zerstört die Wärmebewegung jedoch Wasserstoffbrücken und führt zur irreversiblen Denaturierung. Ebenso besitzt jedes Enzym ein spezifisches pH-Optimum (Pepsin im Magen $\text{pH} \approx 2{,}0$; Speichel-Amylase $\text{pH} \approx 7{,}0$; Trypsin im Dünndarm $\text{pH} \approx 8{,}5$). Änderungen der Oxonium-Ionenkonzentration verändern die Ladung saurer ($-\text{COO}^-$) und basischer ($-\text{NH}_3^+$) Seitenketten, sodass Ionenbindungen im aktiven Zentrum gelöst werden und die Substratbindung drastisch abnimmt.

### Auswertungs- und Vertiefungsaufgaben zur Enzymkinetik

- Aufgabe 1: Ermitteln Sie aus Abb. 6.1 und Tabelle 6.1 näherungsweise $v_{\max}$ sowie $K_M$.
- Aufgabe 2: Begründen Sie auf molekularer Ebene, warum bei kompetitiver Hemmung zwar die scheinbare Michaelis-Konstante $K_M'$ steigt, $v_{\max}$ bei hohem $[S]$ jedoch erreicht wird.
- Aufgabe 3: Berechnen Sie aus Tabelle 6.1 die prozentuale Hemmung bei $[S] = 1{,}0\,\text{mmol/L}$ im Vergleich zu $[S] = 32{,}0\,\text{mmol/L}$ und erläutern Sie das Ergebnis.
- Aufgabe 4: Vergleichen Sie einen anorganischen Katalysator (z. B. $\text{H}_3\text{O}^+$) mit einem Enzym hinsichtlich Spezifität und Temperaturstabilität und erklären Sie, warum Fieber über 42 °C lebensbedrohlich ist.

**Zusammenfassung Abiturwissen: Biokatalyse, Enzymkinetik und Stoffwechselregulation**
- Aktives Zentrum & Induced-Fit-Modell: Bei der Anlagerung des Substrats passt sich die Raumstruktur des aktiven Zentrums dynamisch an (Substrat- und Wirkungsspezifität).
- Energetische Wirkung: Enzyme senken ausschließlich die Aktivierungsenergie $E_A$ über den Enzym-Substrat-Komplex $[ES]$, verändern jedoch weder die Reaktionsenthalpie $\Delta H$ noch die Gleichgewichtslage einer reversiblen Stoffwechselreaktion.
- Michaelis-Konstante $K_M$ als Affinitätsmaß: Kleines $K_M$ kennzeichnet hohe Substrataffinität; kompetitive Inhibitoren erhöhen scheinbar $K_M'$ ohne $v_{\max}$ zu senken, während allosterische Hemmstoffe $v_{\max}$ herabsetzen.
- Negative Rückkopplung (Endprodukthemmung): In mehrschrittigen Stoffwechselketten wirkt das Endprodukt häufig als allosterischer Inhibitor des Schrittmacherenzyms und verhindert Überproduktion.
- Kofaktoren und Koenzyme: Viele Enzyme benötigen für ihre katalytische Aktivität zusätzliche Metall-Ionen (z. B. $\text{Mg}^{2+}$, $\text{Zn}^{2+}$, $\text{Fe}^{2+}$) oder organische Überträgermoleküle ($\text{NAD}^+$, FAD, ATP, Coenzym A).
- Kompartimentierung: Durch Reaktionsräume (Mitochondrien, Chloroplasten, Lysosomen) können unterschiedliche pH-Werte und Enzymgarnituren gleichzeitig in derselben Zelle arbeiten.
"""

    s2_bio_ueb = """((412))

# Kapitel 6: Biokatalyse, Enzymkinetik und Stoffwechselregulation

## 6.1 Molekulare Wirkungsweise von Enzymen und Michaelis-Menten-Kinetik

#### Abb. 6.1: Michaelis-Menten-Kinetik und Kompetitive Hemmung

<Bild> Diagramm:
Beschreibung mit Bildtext: Koordinatensystem mit der Substratkonzentration $[S]$ in mmol/L auf der Rechtsachse und der Reaktionsgeschwindigkeit $v$ auf der Hochachse sowie einem schematischen Schlüssel-Schloss-Modell der kompetitiven Hemmung rechts. Die grüne Sättigungskurve (ohne Hemmstoff) erreicht bei niedriger Substratkonzentration $K_M$ die halbe Maximalgeschwindigkeit $\\frac{1}{2}\\,v_{\\max}$ und nähert sich asymptotisch $v_{\\max}$ an; die orangefarbene Kurve (kompetitive Hemmung) erreicht $\\frac{1}{2}\\,v_{\\max}$ erst bei einer höheren Konzentration $K_M'$, strebt bei hohem $[S]$ aber derselben Maximalgeschwindigkeit $v_{\\max}$ zu.
</Bild>

Enzyme wirken als hochspezifische Biokatalysatoren, indem sie das Substrat im aktiven Zentrum nach dem Induced-Fit-Modell binden und die Aktivierungsenergie $E_A$ über einen Enzym-Substrat-Komplex $[ES]$ herabsetzen. Die Abhängigkeit der Reaktionsgeschwindigkeit $v$ von der Substratkonzentration $[S]$ folgt der Michaelis-Menten-Gleichung. Bei niedrigen Konzentrationen steigt $v$ nahezu linear an, während bei hohen Substratkonzentrationen alle aktiven Zentren der Enzymmoleküle gesättigt sind und $v_{\\max}$ asymptotisch erreicht wird:

$$v = \\frac{v_{\\max} \\cdot [S]}{K_M + [S]}$$

<Rahmen>
_Bio-Kompakt: Bedeutung der Michaelis-Konstante K_M und Formen der Enzymhemmung_
-\t_Michaelis-Konstante $K_M$:_ Gibt genau diejenige Substratkonzentration $[S]$ (in mmol/L) an, bei der die Hälfte der Maximalgeschwindigkeit ($v = \\frac{1}{2}\\,v_{\\max}$) erreicht wird. Ein kleiner $K_M$-Wert bedeutet eine hohe Affinität (Bindungsstärke) des Enzyms zu seinem Substrat.
-\t_Kompetitive Hemmung (Verdrängungshemmung):_ Der Inhibitor ähnelt strukturell dem Substrat und konkurriert um das aktive Zentrum. Die scheinbare Michaelis-Konstante $K_M'$ ist erhöht; durch hohe Substratkonzentrationen $[S]$ lässt sich der Hemmstoff jedoch verdrängen ($v_{\\max}$ bleibt gleich).
-\t_Allosterische (nicht-kompetitive) Hemmung:_ Der Effektor bindet außerhalb des aktiven Zentrums an ein allosterisches Zentrum und verändert die räumliche Konformation des Enzyms. Dadurch sinkt die Maximalgeschwindigkeit $v_{\\max}$, während $K_M$ unverändert bleibt.
-\t_Irreversible Hemmung (Enzymgifte):_ Schwermetall-Ionen (z. B. $\\text{Pb}^{2+}$, $\\text{Hg}^{2+}$, $\\text{Cu}^{2+}$) bilden kovalente Bindungen mit Schwefelgruppen (-SH) der Aminosäure Cystein und inaktivieren das Enzym dauerhaft.
-\t_Beispiel Katalase:_ Spaltet Wasserstoffperoxid ($2\\,\\text{H}_2\\text{O}_2 \\longrightarrow 2\\,\\text{H}_2\\text{O} + \\text{O}_2$) mit hoher Wechselzahl.
</Rahmen>

### Tabelle 6.1: Messreihe zur Substratabhängigkeit der Katalase-Aktivität

<Tabelle>
Substrat $[S]$ (mmol/L)\t$v$ ohne Hemmstoff ($\\mu\\text{mol/min}$)\t$v$ mit Hemmstoff ($\\mu\\text{mol/min}$)\tSättigungsgrad (%)
0,5\t18,2\t8,4\t22,8 %
1,0\t32,0\t15,1\t40,0 %
2,0\t48,0\t25,6\t60,0 %
4,0\t61,5\t38,8\t76,9 %
8,0\t71,1\t53,3\t88,9 %
16,0\t76,2\t65,5\t95,3 %
32,0\t78,8\t73,1\t98,5 %
</Tabelle>

((413))

## 6.2 Abhängigkeit der Enzymaktivität von Temperatur und pH-Wert

Neben der Substratkonzentration bestimmen Temperatur und pH-Wert die räumliche Tertiärstruktur von Enzymproteinen. Nach der RGT-Regel (Reaktionsgeschwindigkeit-Temperatur-Regel) erhöht eine Temperatursteigerung um $10\\,^\\circ\\text{C}$ die Umsatzrate zunächst um das 2- bis 3-Fache ($Q_{10} \\approx 2\\text{–}3$), da die kinetische Energie der Teilchen zunimmt. Oberhalb des Temperaturoptimums (beim Menschen ca. $37\\,^\\circ\\text{C}$ bis $40\\,^\\circ\\text{C}$) zerstört die Wärmebewegung jedoch Wasserstoffbrücken und führt zur irreversiblen Denaturierung. Ebenso besitzt jedes Enzym ein spezifisches pH-Optimum (Pepsin im Magen $\\text{pH} \\approx 2{,}0$; Speichel-Amylase $\\text{pH} \\approx 7{,}0$; Trypsin im Dünndarm $\\text{pH} \\approx 8{,}5$). Änderungen der Oxonium-Ionenkonzentration verändern die Ladung saurer ($-\\text{COO}^-$) und basischer ($-\\text{NH}_3^+$) Seitenketten, sodass Ionenbindungen im aktiven Zentrum gelöst werden und die Substratbindung drastisch abnimmt.

### Auswertungs- und Vertiefungsaufgaben zur Enzymkinetik

-\tAufgabe 1: Ermitteln Sie aus Abb. 6.1 und Tabelle 6.1 näherungsweise $v_{\\max}$ sowie $K_M$.
-\tAufgabe 2: Begründen Sie auf molekularer Ebene, warum bei kompetitiver Hemmung zwar die scheinbare Michaelis-Konstante $K_M'$ steigt, $v_{\\max}$ bei hohem $[S]$ jedoch erreicht wird.
-\tAufgabe 3: Berechnen Sie aus Tabelle 6.1 die prozentuale Hemmung bei $[S] = 1{,}0\\,\\text{mmol/L}$ im Vergleich zu $[S] = 32{,}0\\,\\text{mmol/L}$ und erläutern Sie das Ergebnis.
-\tAufgabe 4: Vergleichen Sie einen anorganischen Katalysator (z. B. $\\text{H}_3\\text{O}^+$) mit einem Enzym hinsichtlich Spezifität und Temperaturstabilität und erklären Sie, warum Fieber über $42\\,^\\circ\\text{C}$ lebensbedrohlich ist.

<Rahmen>
_Zusammenfassung Abiturwissen: Biokatalyse, Enzymkinetik und Stoffwechselregulation_
-\t_Aktives Zentrum & Induced-Fit-Modell:_ Bei der Anlagerung des Substrats passt sich die Raumstruktur des aktiven Zentrums dynamisch an (Substrat- und Wirkungsspezifität).
-\t_Energetische Wirkung:_ Enzyme senken ausschließlich die Aktivierungsenergie $E_A$ über den Enzym-Substrat-Komplex $[ES]$, verändern jedoch weder die Reaktionsenthalpie $\\Delta H$ noch die Gleichgewichtslage einer reversiblen Stoffwechselreaktion.
-\t_Michaelis-Konstante $K_M$ als Affinitätsmaß:_ Kleines $K_M$ kennzeichnet hohe Substrataffinität; kompetitive Inhibitoren erhöhen scheinbar $K_M'$ ohne $v_{\\max}$ zu senken, während allosterische Hemmstoffe $v_{\\max}$ herabsetzen.
-\t_Negative Rückkopplung (Endprodukthemmung):_ In mehrschrittigen Stoffwechselketten wirkt das Endprodukt häufig als allosterischer Inhibitor des Schrittmacherenzyms und verhindert Überproduktion.
-\t_Kofaktoren und Koenzyme:_ Viele Enzyme benötigen für ihre katalytische Aktivität zusätzliche Metall-Ionen (z. B. $\\text{Mg}^{2+}$, $\\text{Zn}^{2+}$, $\\text{Fe}^{2+}$) oder organische Überträgermoleküle ($\\text{NAD}^+$, FAD, ATP, Coenzym A).
-\t_Kompartimentierung:_ Durch Reaktionsräume (Mitochondrien, Chloroplasten, Lysosomen) können unterschiedliche pH-Werte und Enzymgarnituren gleichzeitig in derselben Zelle arbeiten.
</Rahmen>
"""

    # -------------------- 9. SEK II PHYSIK (VERZEICHNISSE) --------------------
    s2_phys_raw = r"""((44))

# Inhaltsverzeichnis

- Kapitel 5: Wellenoptik und Quantenphysik ................................ 45
- 5.1 Interferenz und Beugung am Doppelspalt .............................. 45
  - Versuchsaufbau mit dem Doppelspalt .................................... 45
    - Herleitung der Gangunterschiedsformel ............................... 46
- 5.2 Optisches Gitter und hochauflösende Spektroskopie ................... 46
  - Photoelektrischer Effekt und Lichtquantenhypothese .................... 47

# Abbildungsverzeichnis

- Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt .... 45
- Abb. 5.2: Beugung am optischen Gitter und Linienspektrum ................ 46

# Tabellenverzeichnis

- Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien ... 46
- Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt ......... 47

# Bildverzeichnis

- Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young .. 45
- Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung ... 47

**Lernwegweiser zu Kapitel 5: Vom Wellenmodell zum Quantenobjekt Photon**
- In Abschnitt 5.1 untersuchen Sie die Kohärenz und Interferenz von Licht am Doppelspalt und leiten die Bedingung für konstruktive und destruktive Interferenz geometrisch her.
- In Abschnitt 5.2 nutzen Sie optische Mehrfachspalt-Gitter zur präzisen Wellenlängenbestimmung atomarer Spektrallinien (Fraunhofer-Linien und Quecksilber-Dampflampe).
- Abschließend zeigt der äußere lichtelektrische Effekt (Hallwachs- und Photoeffekt), dass Energie im elektromagnetischen Strahlungsfeld nur in Lichtquanten $E = h \cdot f$ übertragen wird. Alle Abbildungen, Tabellen und Bilder sind oben mit Seitenzahl verzeichnet.

((45))

# Kapitel 5: Wellenoptik und Quantenphysik

## 5.1 Interferenz und Beugung am Doppelspalt

Im Jahr 1802 gelang dem englischen Naturforscher Thomas Young mit dem Doppelspaltversuch der entscheidende experimentelle Nachweis für die Wellennatur des Lichts. Trifft monochromatisches, kohärentes Licht der Wellenlänge $\lambda$ auf zwei eng benachbarte parallele Spalte mit dem Spaltmittenabstand $d$, so gehen von beiden Öffnungen nach dem Huygens’schen Prinzip zylindrische Elementarwellen aus, die sich im Raum hinter der Blende ungestört überlagern.

### Versuchsaufbau mit dem Doppelspalt

![Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt](figures/physik_doppelspalt_interferenz.png)

Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt

Auf dem Beobachtungsschirm im Abstand $L \gg d$ entsteht ein charakteristisches Streifenmuster aus abwechselnd hellen Interferenzmaxima und dunklen Interferenzminima. Ein helles Maximum $k$-ter Ordnung tritt immer dort auf, wo der Gangunterschied $\Delta s$ der beiden Teilwellen ein ganzzahliges Vielfaches der Wellenlänge $\lambda$ beträgt ($\Delta s = k \cdot \lambda$ mit $k = 0, 1, 2, \dots$). Beträgt der Gangunterschied hingegen ein ungeradzahliges Vielfaches einer halben Wellenlänge, löschen sich Wellenberg und Wellental durch destruktive Interferenz gegenseitig aus.

**Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young**
- Kohärenzbedingung: Zeitlich und räumlich konstante Phasenbeziehung zwischen beiden Elementarwellenzügen; im modernen Schulexperiment durch einen He-Ne-Laser ($\lambda = 632{,}8\,\text{nm}$).
- Konstruktive Interferenz (Verstärkung): $\Delta s = d \cdot \sin(\alpha_k) = k \cdot \lambda$ (für $k = 0, 1, 2, \dots$).
- Destruktive Interferenz (Auslöschung): $\Delta s = d \cdot \sin(\alpha_k) = (k + \frac{1}{2}) \cdot \lambda$.
- Kleinwinkelnäherung (für kleine Winkel $\alpha < 10^\circ$ gilt $\sin(\alpha) \approx \tan(\alpha) = \frac{y_k}{L}$): Der Streifenabstand benachbarter Maxima auf dem Schirm beträgt $\Delta y = \frac{\lambda \cdot L}{d}$.
- Je kleiner der Spaltabstand $d$ gewählt wird, desto weiter rücken die Maxima auseinander.

((46))

#### Herleitung der Gangunterschiedsformel

Da der Schirmabstand $L$ im Experiment sehr viel größer als der Spaltmittenabstand $d$ ist (Fraunhofer-Näherung), verlaufen die beiden Strahlen von den Spalten $S_1$ und $S_2$ zu einem Schirmpunkt $P$ nahezu parallel unter demselben Beugungswinkel $\alpha$. Fällen wir vom oberen Spalt $S_1$ das Lot auf den unteren Strahl, entsteht ein rechtwinkliges Dreieck mit der Hypotenuse $d$ und der Gegenkathete $\Delta s$. Daraus folgt unmittelbar $\Delta s = d \cdot \sin(\alpha)$.

## 5.2 Optisches Gitter und hochauflösende Spektroskopie

Ersetzt man den Doppelspalt durch ein optisches Transmissionsgitter mit $N \gg 100$ äquidistanten Spalten (Gitterkonstante $g = \frac{1}{n}$), so bleibt die Lage der Hauptmaxima bei $g \cdot \sin(\alpha_k) = k \cdot \lambda$ erhalten. Durch die Vielstrahlinterferenz aller $N$ Elementarwellen werden die Hauptmaxima jedoch extrem scharf und lichtstark, während zwischen zwei Hauptmaxima jeweils $N - 1$ Nebenminima nahezu vollständige Dunkelheit erzeugen.

#### Abb. 5.2: Beugung am optischen Gitter und Linienspektrum

Schematischer Strahlengang am Mehrfachspalt (Gitterkonstante $g = 1{,}67\,\mu\text{m}$, entsprechend 600 Linien/mm): Kurzwelliges violettes Licht (405 nm) wird weniger stark gebeugt als langwelliges rotes Licht (656 nm).

### Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien

| Spektrallinie / Element | Farbeindruck | Wellenlänge $\lambda$ (nm) | Winkel $\alpha_1$ (1. Ordnung) |
| :--- | :--- | :--- | :--- |
| Quecksilber (Hg-Linie h) | Violett | 404,7 nm | 14,1° |
| Wasserstoff (H-beta) | Blaugrün (Cyan) | 486,1 nm | 17,0° |
| Natrium-Doppellinie (Na-D) | Gelb-Orange | 589,3 nm | 20,7° |
| Helium-Neon-Laser | Hellrot | 632,8 nm | 22,3° |
| Wasserstoff (H-alpha) | Tiefrot | 656,3 nm | 23,2° |

**Methoden-Kasten: Gitter-Spektroskopie in Astrophysik und Labor**
- Auflösungsvermögen eines Gitters: $R = \frac{\lambda}{\Delta\lambda} = k \cdot N$ (wächst mit der beleuchteten Spaltzahl $N$).
- Beispiel Natrium-D-Doppellinie ($\lambda_1 = 589{,}0\,\text{nm}$ und $\lambda_2 = 589{,}6\,\text{nm}$): Um beide Linien in der ersten Beugungsordnung ($k = 1$) getrennt aufzulösen, müssen mindestens $N \approx 983$ Gitterfurchen kohärent ausgeleuchtet werden.
- Maximal beobachtbare Beugungsordnung: Da $\sin(\alpha_k) \le 1$ gelten muss, folgt $k_{\max} = \lfloor \frac{g}{\lambda} \rfloor$.
- Chemische Spektralanalyse (Bunsen & Kirchhoff): Jedes chemische Element besitzt ein unverwechselbares Linienspektrum als optischen Fingerabdruck elektronischer Übergänge.
- In der Astrophysik ermöglicht die Verschiebung der Fraunhofer’schen Absorptionslinien (Doppler-Effekt) die exakte Bestimmung der Radialgeschwindigkeit ferner Galaxien.
- Unterschied zum Dispersionsprisma: Beim optischen Gitter wird langwelliges rotes Licht stärker abgelenkt als kurzwelliges blaues Licht (Normaldispersion beim Prisma ist umgekehrt).
- Eichung im Schülerexperiment: Mit der bekannten He-Ne-Laserwellenlänge $\lambda = 632{,}8\,\text{nm}$ lässt sich zunächst die Gitterkonstante $g$ eines unbekannten optischen Gitters bestimmen.

((47))

### Photoelektrischer Effekt und Lichtquantenhypothese

Bestrahlt man eine metallische Photokathode (z. B. Cäsium oder Kalium) mit kurzwelligem ultraviolettem oder blauem Licht, so werden augenblicklich Leitungselektronen aus der Metalloberfläche ausgelöst (äußerer lichtelektrischer Effekt). Nach der klassischen Wellentheorie müsste die maximale kinetische Energie $E_{\text{kin,max}}$ der Photoelektronen von der Bestrahlungsstärke (Intensität) des Lichts abhängen. Das Experiment mit der Gegenspannungsmethode zeigt jedoch: $E_{\text{kin,max}}$ hängt ausschließlich linear von der Lichtfrequenz $f$ ab! Albert Einstein deutete diesen Befund 1905 mit seiner Lichtquantenhypothese: Elektromagnetische Strahlung der Frequenz $f$ besteht aus einzelnen Energiequanten (Photonen) der Energie $E_{\text{Photon}} = h \cdot f$ mit dem Planck’schen Wirkungsquantum $h = 6{,}626 \cdot 10^{-34}\,\text{J}\cdot\text{s}$.

#### Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung

Vakuum-Photozelle mit bestrahlter Kalium-Kathode, Ringanode, einstellbarer Gegenspannung $U_G$ und Picoamperemeter: Bei $e \cdot U_G = E_{\text{kin,max}} = h \cdot f - W_A$ sinkt der Photostrom exakt auf null.

### Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt

| Kathodenmetall | Austrittsarbeit $W_A$ (eV) | Grenzfrequenz $f_G$ ($10^{14}\,\text{Hz}$) | Grenzwellenlänge $\lambda_G$ (nm) |
| :--- | :--- | :--- | :--- |
| Cäsium (Cs) | 1,94 eV | $4{,}69 \cdot 10^{14}\,\text{Hz}$ | 639 nm (Rot) |
| Kalium (K) | 2,25 eV | $5{,}44 \cdot 10^{14}\,\text{Hz}$ | 551 nm (Grün) |
| Natrium (Na) | 2,28 eV | $5{,}51 \cdot 10^{14}\,\text{Hz}$ | 544 nm (Grün) |
| Zink (Zn) | 4,31 eV | $10{,}4 \cdot 10^{14}\,\text{Hz}$ | 288 nm (UV) |
| Platin (Pt) | 5,32 eV | $12{,}9 \cdot 10^{14}\,\text{Hz}$ | 233 nm (UV) |

### Übungsaufgaben zu Wellenoptik und Quantenphysik

- Aufgabe 1: Berechnen Sie aus Tab. 5.1 die Gitterkonstante $g$ des verwendeten optischen Gitters.
- Aufgabe 2: Begründen Sie mithilfe von Tab. 5.2, warum rotes Laserlicht ($\lambda = 632{,}8\,\text{nm}$) zwar an einer Cäsium-Kathode, nicht aber an einer Kalium- oder Zink-Kathode Photoelektronen auslöst.
- Aufgabe 3: Bestimmen Sie die maximale kinetische Energie und Geschwindigkeit der Photoelektronen beim Bestrahlen einer Kalium-Kathode mit violettem Quecksilberlicht ($\lambda = 404{,}7\,\text{nm}$).

**Merksatz: Einstein’sche Gleichung des Photoeffekts und Welle-Teilchen-Dualismus**
- Energiebilanz beim Photoeffekt: $E_{\text{kin,max}} = h \cdot f - W_A = e \cdot U_G$.
- Grenzfrequenz $f_G = \frac{W_A}{h}$: Unterhalb von $f_G$ werden selbst bei höchster Lichtintensität keine Elektronen ausgelöst; oberhalb von $f_G$ setzt der Photostrom verzögerungsfrei ein.
- Bedeutung der Lichtintensität: Eine höhere Bestrahlungsstärke bedeutet mehr Photonen pro Sekunde und erhöht die Stromstärke $I_{\text{Photo}}$, nicht jedoch die Einzelenergie $h \cdot f$.
- Welle-Teilchen-Dualismus: Bei der Ausbreitung im Raum (Beugung am Doppelspalt und Gitter) zeigt Licht Welleneigenschaften; bei der Wechselwirkung mit Materie (Emission und Absorption) tritt sein Teilchencharakter in Form unteilbarer Lichtquanten (Photonen) hervor.
- Umrechnung der Energieeinheit Elektronenvolt: $1\,\text{eV} = 1{,}602 \cdot 10^{-19}\,\text{J}$.
- Impuls eines Photons: $p = \frac{E}{c} = \frac{h}{\lambda}$ (experimentell bestätigt durch den Compton-Effekt).
"""

    s2_phys_ueb = """((44))

# Inhaltsverzeichnis

-\tKapitel 5: Wellenoptik und Quantenphysik 45
-\t5.1 Interferenz und Beugung am Doppelspalt 45
-\tVersuchsaufbau mit dem Doppelspalt 45
-\tHerleitung der Gangunterschiedsformel 46
-\t5.2 Optisches Gitter und hochauflösende Spektroskopie 46
-\tPhotoelektrischer Effekt und Lichtquantenhypothese 47

## Abbildungsverzeichnis

-\tAbb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt 45
-\tAbb. 5.2: Beugung am optischen Gitter und Linienspektrum 46

## Tabellenverzeichnis

-\tTab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien 46
-\tTab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt 47

## Bildverzeichnis

-\tBild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young 45
-\tBild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung 47

<Rahmen>
_Lernwegweiser zu Kapitel 5: Vom Wellenmodell zum Quantenobjekt Photon_
-\tIn Abschnitt 5.1 untersuchen Sie die Kohärenz und Interferenz von Licht am Doppelspalt und leiten die Bedingung für konstruktive und destruktive Interferenz geometrisch her.
-\tIn Abschnitt 5.2 nutzen Sie optische Mehrfachspalt-Gitter zur präzisen Wellenlängenbestimmung atomarer Spektrallinien (Fraunhofer-Linien und Quecksilber-Dampflampe).
-\tAbschließend zeigt der äußere lichtelektrische Effekt (Hallwachs- und Photoeffekt), dass Energie im elektromagnetischen Strahlungsfeld nur in Lichtquanten $E = h \\cdot f$ übertragen wird. Alle Abbildungen, Tabellen und Bilder sind oben mit Seitenzahl verzeichnet.
</Rahmen>

((45))

# Kapitel 5: Wellenoptik und Quantenphysik

## 5.1 Interferenz und Beugung am Doppelspalt

Im Jahr 1802 gelang dem englischen Naturforscher Thomas Young mit dem Doppelspaltversuch der entscheidende experimentelle Nachweis für die Wellennatur des Lichts. Trifft monochromatisches, kohärentes Licht der Wellenlänge $\\lambda$ auf zwei eng benachbarte parallele Spalte mit dem Spaltmittenabstand $d$, so gehen von beiden Öffnungen nach dem Huygens’schen Prinzip zylindrische Elementarwellen aus, die sich im Raum hinter der Blende ungestört überlagern.

### Versuchsaufbau mit dem Doppelspalt

#### Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt

<Bild> Diagramm:
Beschreibung mit Bildtext: Schematische Darstellung der Doppelspalt-Interferenz links mit einfallendem Laserstrahl ($\\lambda = 632{,}8\\,\\text{nm}$), Doppelspaltblende ($S_1$, $S_2$), halbkreisförmigen Huygens’schen Elementarwellen und den Interferenzmaxima $k = -2, -1, 0, 1, 2$ auf dem Beobachtungsschirm sowie dem zugehörigen Intensitätsverlauf $I(y)$ rechts mit dem Hauptmaximum bei $k = 0$ und der Bedingung $\\Delta s = k \\cdot \\lambda$.
</Bild>

Auf dem Beobachtungsschirm im Abstand $L \\gg d$ entsteht ein charakteristisches Streifenmuster aus abwechselnd hellen Interferenzmaxima und dunklen Interferenzminima. Ein helles Maximum $k$-ter Ordnung tritt immer dort auf, wo der Gangunterschied $\\Delta s$ der beiden Teilwellen ein ganzzahliges Vielfaches der Wellenlänge $\\lambda$ beträgt ($\\Delta s = k \\cdot \\lambda$ mit $k = 0, 1, 2, \\dots$). Beträgt der Gangunterschied hingegen ein ungeradzahliges Vielfaches einer halben Wellenlänge, löschen sich Wellenberg und Wellental durch destruktive Interferenz gegenseitig aus.

<Rahmen>
_Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young_
-\t_Kohärenzbedingung:_ Zeitlich und räumlich konstante Phasenbeziehung zwischen beiden Elementarwellenzügen; im modernen Schulexperiment durch einen He-Ne-Laser ($\\lambda = 632{,}8\\,\\text{nm}$).
-\t_Konstruktive Interferenz (Verstärkung):_ $\\Delta s = d \\cdot \\sin(\\alpha_k) = k \\cdot \\lambda$ (für $k = 0, 1, 2, \\dots$).
-\t_Destruktive Interferenz (Auslöschung):_ $\\Delta s = d \\cdot \\sin(\\alpha_k) = (k + \\frac{1}{2}) \\cdot \\lambda$.
-\t_Kleinwinkelnäherung (für kleine Winkel $\\alpha < 10^\\circ$ gilt $\\sin(\\alpha) \\approx \\tan(\\alpha) = \\frac{y_k}{L}$):_ Der Streifenabstand benachbarter Maxima auf dem Schirm beträgt $\\Delta y = \\frac{\\lambda \\cdot L}{d}$.
-\tJe kleiner der Spaltabstand $d$ gewählt wird, desto weiter rücken die Maxima auseinander.
</Rahmen>

((46))

#### Herleitung der Gangunterschiedsformel

Da der Schirmabstand $L$ im Experiment sehr viel größer als der Spaltmittenabstand $d$ ist (Fraunhofer-Näherung), verlaufen die beiden Strahlen von den Spalten $S_1$ und $S_2$ zu einem Schirmpunkt $P$ nahezu parallel unter demselben Beugungswinkel $\\alpha$. Fällen wir vom oberen Spalt $S_1$ das Lot auf den unteren Strahl, entsteht ein rechtwinkliges Dreieck mit der Hypotenuse $d$ und der Gegenkathete $\\Delta s$. Daraus folgt unmittelbar $\\Delta s = d \\cdot \\sin(\\alpha)$.

## 5.2 Optisches Gitter und hochauflösende Spektroskopie

Ersetzt man den Doppelspalt durch ein optisches Transmissionsgitter mit $N \\gg 100$ äquidistanten Spalten (Gitterkonstante $g = \\frac{1}{n}$), so bleibt die Lage der Hauptmaxima bei $g \\cdot \\sin(\\alpha_k) = k \\cdot \\lambda$ erhalten. Durch die Vielstrahlinterferenz aller $N$ Elementarwellen werden die Hauptmaxima jedoch extrem scharf und lichtstark, während zwischen zwei Hauptmaxima jeweils $N - 1$ Nebenminima nahezu vollständige Dunkelheit erzeugen.

#### Abb. 5.2: Beugung am optischen Gitter und Linienspektrum

Schematischer Strahlengang am Mehrfachspalt (Gitterkonstante $g = 1{,}67\\,\\mu\\text{m}$, entsprechend 600 Linien/mm): Kurzwelliges violettes Licht (405 nm) wird weniger stark gebeugt als langwelliges rotes Licht (656 nm).

### Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien

<Tabelle>
Spektrallinie / Element\tFarbeindruck\tWellenlänge $\\lambda$ (nm)\tWinkel $\\alpha_1$ (1. Ordnung)
Quecksilber (Hg-Linie h)\tViolett\t404,7 nm\t$14{,}1^\\circ$
Wasserstoff (H-beta)\tBlaugrün (Cyan)\t486,1 nm\t$17{,}0^\\circ$
Natrium-Doppellinie (Na-D)\tGelb-Orange\t589,3 nm\t$20{,}7^\\circ$
Helium-Neon-Laser\tHellrot\t632,8 nm\t$22{,}3^\\circ$
Wasserstoff (H-alpha)\tTiefrot\t656,3 nm\t$23{,}2^\\circ$
</Tabelle>

<Rahmen>
_Methoden-Kasten: Gitter-Spektroskopie in Astrophysik und Labor_
-\t_Auflösungsvermögen eines Gitters:_ $R = \\frac{\\lambda}{\\Delta\\lambda} = k \\cdot N$ (wächst mit der beleuchteten Spaltzahl $N$).
-\t_Beispiel Natrium-D-Doppellinie ($\\lambda_1 = 589{,}0\\,\\text{nm}$ und $\\lambda_2 = 589{,}6\\,\\text{nm}$):_ Um beide Linien in der ersten Beugungsordnung ($k = 1$) getrennt aufzulösen, müssen mindestens $N \\approx 983$ Gitterfurchen kohärent ausgeleuchtet werden.
-\t_Maximal beobachtbare Beugungsordnung:_ Da $\\sin(\\alpha_k) \\le 1$ gelten muss, folgt $k_{\\max} = \\lfloor \\frac{g}{\\lambda} \\rfloor$.
-\t_Chemische Spektralanalyse (Bunsen & Kirchhoff):_ Jedes chemische Element besitzt ein unverwechselbares Linienspektrum als optischen Fingerabdruck elektronischer Übergänge.
-\tIn der Astrophysik ermöglicht die Verschiebung der Fraunhofer’schen Absorptionslinien (Doppler-Effekt) die exakte Bestimmung der Radialgeschwindigkeit ferner Galaxien.
-\t_Unterschied zum Dispersionsprisma:_ Beim optischen Gitter wird langwelliges rotes Licht stärker abgelenkt als kurzwelliges blaues Licht (Normaldispersion beim Prisma ist umgekehrt).
-\t_Eichung im Schülerexperiment:_ Mit der bekannten He-Ne-Laserwellenlänge $\\lambda = 632{,}8\\,\\text{nm}$ lässt sich zunächst die Gitterkonstante $g$ eines unbekannten optischen Gitters bestimmen.
</Rahmen>

((47))

### Photoelektrischer Effekt und Lichtquantenhypothese

Bestrahlt man eine metallische Photokathode (z. B. Cäsium oder Kalium) mit kurzwelligem ultraviolettem oder blauem Licht, so werden augenblicklich Leitungselektronen aus der Metalloberfläche ausgelöst (äußerer lichtelektrischer Effekt). Nach der klassischen Wellentheorie müsste die maximale kinetische Energie $E_{\\text{kin,max}}$ der Photoelektronen von der Bestrahlungsstärke (Intensität) des Lichts abhängen. Das Experiment mit der Gegenspannungsmethode zeigt jedoch: $E_{\\text{kin,max}}$ hängt ausschließlich linear von der Lichtfrequenz $f$ ab! Albert Einstein deutete diesen Befund 1905 mit seiner Lichtquantenhypothese: Elektromagnetische Strahlung der Frequenz $f$ besteht aus einzelnen Energiequanten (Photonen) der Energie $E_{\\text{Photon}} = h \\cdot f$ mit dem Planck’schen Wirkungsquantum $h = 6{,}626 \\cdot 10^{-34}\\,\\text{J}\\cdot\\text{s}$.

#### Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung

Vakuum-Photozelle mit bestrahlter Kalium-Kathode, Ringanode, einstellbarer Gegenspannung $U_G$ und Picoamperemeter: Bei $e \\cdot U_G = E_{\\text{kin,max}} = h \\cdot f - W_A$ sinkt der Photostrom exakt auf null.

### Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt

<Tabelle>
Kathodenmetall\tAustrittsarbeit $W_A$ (eV)\tGrenzfrequenz $f_G$ ($10^{14}\\,\\text{Hz}$)\tGrenzwellenlänge $\\lambda_G$ (nm)
Cäsium (Cs)\t1,94 eV\t$4{,}69 \\cdot 10^{14}\\,\\text{Hz}$\t639 nm (Rot)
Kalium (K)\t2,25 eV\t$5{,}44 \\cdot 10^{14}\\,\\text{Hz}$\t551 nm (Grün)
Natrium (Na)\t2,28 eV\t$5{,}51 \\cdot 10^{14}\\,\\text{Hz}$\t544 nm (Grün)
Zink (Zn)\t4,31 eV\t$10{,}4 \\cdot 10^{14}\\,\\text{Hz}$\t288 nm (UV)
Platin (Pt)\t5,32 eV\t$12{,}9 \\cdot 10^{14}\\,\\text{Hz}$\t233 nm (UV)
</Tabelle>

### Übungsaufgaben zu Wellenoptik und Quantenphysik

-\tAufgabe 1: Berechnen Sie aus Tab. 5.1 die Gitterkonstante $g$ des verwendeten optischen Gitters.
-\tAufgabe 2: Begründen Sie mithilfe von Tab. 5.2, warum rotes Laserlicht ($\\lambda = 632{,}8\\,\\text{nm}$) zwar an einer Cäsium-Kathode, nicht aber an einer Kalium- oder Zink-Kathode Photoelektronen auslöst.
-\tAufgabe 3: Bestimmen Sie die maximale kinetische Energie und Geschwindigkeit der Photoelektronen beim Bestrahlen einer Kalium-Kathode mit violettem Quecksilberlicht ($\\lambda = 404{,}7\\,\\text{nm}$).

<Rahmen>
_Merksatz: Einstein’sche Gleichung des Photoeffekts und Welle-Teilchen-Dualismus_
-\t_Energiebilanz beim Photoeffekt:_ $E_{\\text{kin,max}} = h \\cdot f - W_A = e \\cdot U_G$.
-\t_Grenzfrequenz $f_G = \\frac{W_A}{h}$:_ Unterhalb von $f_G$ werden selbst bei höchster Lichtintensität keine Elektronen ausgelöst; oberhalb von $f_G$ setzt der Photostrom verzögerungsfrei ein.
-\t_Bedeutung der Lichtintensität:_ Eine höhere Bestrahlungsstärke bedeutet mehr Photonen pro Sekunde und erhöht die Stromstärke $I_{\\text{Photo}}$, nicht jedoch die Einzelenergie $h \\cdot f$.
-\t_Welle-Teilchen-Dualismus:_ Bei der Ausbreitung im Raum (Beugung am Doppelspalt und Gitter) zeigt Licht Welleneigenschaften; bei der Wechselwirkung mit Materie (Emission und Absorption) tritt sein Teilchencharakter in Form unteilbarer Lichtquanten (Photonen) hervor.
-\t_Umrechnung der Energieeinheit Elektronenvolt:_ $1\\,\\text{eV} = 1{,}602 \\cdot 10^{-19}\\,\\text{J}$.
-\t_Impuls eines Photons:_ $p = \\frac{E}{c} = \\frac{h}{\\lambda}$ (experimentell bestätigt durch den Compton-Effekt).
</Rahmen>
"""

    # -------------------- 10. SEK I INFORMATIK (B5+ 190x260 mm) --------------------
    s1_info_raw = """((18))

# Kapitel 1: Algorithmen und Programmierung

## 1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife

Ein Algorithmus ist eine eindeutige, ausführbare und endliche Handlungsvorschrift zur schrittweisen Lösung eines Problems. In der modernen Robotik und Mikrocontroller-Technik verarbeiten autonome Systeme kontinuierlich Sensordaten, um auf Hindernisse in ihrer Umgebung zu reagieren. Dabei folgt jedes Computerprogramm drei elementaren Kontrollstrukturen: der linearen Sequenz (Befehlsfolge), der bedingten Verzweigung (Wenn-Dann-Sonst-Entscheidung) und der Wiederholungsschleife (Iteration).

![Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters](figures/informatik_programmablaufplan.png)

Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters

**Mediencode 74108-18: Interaktive Simulation Labyrinth-Roboter**
- Teste den Programmablaufplan aus Abb. 1.1 im virtuellen 2D-Parcours mit verschiedenen Schwellenwerten ($d < 15\\,\\text{cm}$, $d < 25\\,\\text{cm}$, $d < 40\\,\\text{cm}$) und beobachte die Fahrspur des Roboters.

**Merksatz: Algorithmus und Grundstrukturen nach Böhm und Jacopini**
- Eindeutigkeit (Determiniertheit): Nach jedem Einzelschritt ist exakt festgelegt, welche Anweisung als Nächstes ausgeführt wird; es gibt keinen Interpretationsspielraum.
- Sequenz (Folge): Anweisungen werden streng nacheinander von oben nach unten abgearbeitet.
- Bedingte Verzweigung (Selektion): Eine logische Bedingung (Wahrheitswert wahr oder falsch) entscheidet darüber, ob der Ja-Zweig oder der Nein-Zweig durchlaufen wird.
- Schleife (Iteration): Ein Anweisungsblock wird solange wiederholt, wie eine Laufbedingung erfüllt ist (kopfgesteuerte Solange-Schleife) oder eine feste Anzahl erreicht wurde.
- Satz von Böhm und Jacopini (1966): Jedes berechenbare Problem lässt sich ausschließlich durch die Kombination von Sequenz, Verzweigung und Schleife ohne Sprungbefehle lösen.
- Terminierung vs. Endlosschleife: Während Berechnungsalgorithmen nach endlich vielen Schritten enden müssen, nutzen eingebettete Steuerungen oft eine dauerhafte Ereignisschleife.

((19))

### Logische Verknüpfungen und Sensordaten-Auswertung

Damit ein autonomer Transportroboter in einer Werkhalle nicht mit Regalen oder Personen kollidiert, kombiniert seine Steuerung oft mehrere Sensoren über boolesche Operatoren (UND, ODER, NICHT). Ein Ausweichmanöver wird genau dann eingeleitet, wenn der vordere Ultraschallsensor ein Hindernis meldet ($A = 1$) ODER der Stoßfänger-Taster ausgelöst wird ($B = 1$).

### Tabelle 1.1: Wahrheitstabelle und Aktor-Reaktion der Robotersteuerung

| Sensor A (Abstand < 25 cm) | Sensor B (Taster vorn) | Verknüpfung A ODER B | Aktor-Befehl (Fahrmotoren) |
| :--- | :--- | :--- | :--- |
| 0 (frei) | 0 (nicht gedrückt) | 0 (falsch) | Geradeaus fahren ($v = 50\\,\\%$) |
| 0 (frei) | 1 (gedrückt) | 1 (wahr) | Sofort stoppen & zurücksetzen |
| 1 (Hindernis nah) | 0 (nicht gedrückt) | 1 (wahr) | Stoppen & 90° rechts drehen |
| 1 (Hindernis nah) | 1 (gedrückt) | 1 (wahr) | Not-Stopp & Warnsignalton |

### Aufgabe 1: Programmablaufplan nachvollziehen (Trace-Tabelle)

Der Ultraschallsensor liefert nacheinander die Messwerte $d = 62\\,\\text{cm}$, $d = 38\\,\\text{cm}$, $d = 19\\,\\text{cm}$ und $d = 45\\,\\text{cm}$. Gib für jeden Messwert an, welchen Zweig der Roboter in Abb. 1.1 durchläuft.

### Aufgabe 2: Erweiterung um einen linken und rechten Seitensensor

Formuliere eine geschachtelte Wenn-Dann-Sonst-Bedingung, mit der der Roboter vor einer Drehung prüft, ob rechts mehr Platz ist als links ($d_{\\text{rechts}} > d_{\\text{links}}$).

### Aufgabe 3: Boolesche Algebra im Alltag

Erkläre den Unterschied zwischen einer UND-Verknüpfung (Konjunktion) und einer ODER-Verknüpfung (Disjunktion) am Beispiel einer automatischen Gewächshaus-Bewässerung.

**Checkliste: Teste dich! — Trainingsplan zu Kapitel 1**
- Ich kann die Begriffe Algorithmus, Sequenz, Verzweigung und Schleife an einem Alltagsbeispiel erläutern (Nachlesen: S. 18, Merksatz).
- Ich kann einen gegebenen Programmablaufplan (PAP) nach DIN 66001 lesen und für konkrete Eingabewerte Schritt für Schritt auswerten (Nachlesen: S. 18, Abb. 1.1).
- Ich kann einfache und zusammengesetzte Bedingungen mit den logischen Operatoren UND, ODER sowie NICHT in einer Wahrheitstabelle darstellen (Nachlesen: S. 19, Tab. 1.1).
- Ich kann erklären, warum eine Robotersteuerung in einer dauerhaften Ereignisschleife arbeitet und wie ein Not-Stopp-Abbruchkriterium integriert wird (Nachlesen: S. 19).
- Ich kann zu einer textuell beschriebenen Problemstellung selbstständig einen fehlerfreien Programmablaufplan entwerfen und testen (Übung: Aufgabe 2).
- Ich kann im Simulator mithilfe des Mediencodes 74108-18 eigene Schwellenwerte experimentell erproben und optimieren (Digitale Zusatzaufgabe: S. 18).
"""

    s1_info_ueb = """((18))

# Kapitel 1: Algorithmen und Programmierung

## 1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife

Ein Algorithmus ist eine eindeutige, ausführbare und endliche Handlungsvorschrift zur schrittweisen Lösung eines Problems. In der modernen Robotik und Mikrocontroller-Technik verarbeiten autonome Systeme kontinuierlich Sensordaten, um auf Hindernisse in ihrer Umgebung zu reagieren. Dabei folgt jedes Computerprogramm drei elementaren Kontrollstrukturen: der linearen Sequenz (Befehlsfolge), der bedingten Verzweigung (Wenn-Dann-Sonst-Entscheidung) und der Wiederholungsschleife (Iteration).

#### Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters

<Bild> Strukturdiagramm:
Beschreibung mit Bildtext: Programmablaufplan (PAP) zur Hinderniserkennung und Ausweichsteuerung eines Roboters in einer Endlosschleife (alle 50 ms):
Start \\to Ultraschallsensor: Messe Abstand $d$ (cm) \\to Entscheidung: $d < 25\\,\\text{cm}$?
Ja \\to Stoppe Motoren und drehe $90^\\circ$ nach rechts.
Nein \\to Fahre geradeaus (Geschwindigkeit $v = 50\\,\\%$).
</Bild>

<Rahmen>
_Mediencode 74108-18: Interaktive Simulation Labyrinth-Roboter_
-\tTeste den Programmablaufplan aus Abb. 1.1 im virtuellen 2D-Parcours mit verschiedenen Schwellenwerten ($d < 15\\,\\text{cm}$, $d < 25\\,\\text{cm}$, $d < 40\\,\\text{cm}$) und beobachte die Fahrspur des Roboters.
</Rahmen>

<Rahmen>
_Merksatz: Algorithmus und Grundstrukturen nach Böhm und Jacopini_
-\t_Eindeutigkeit (Determiniertheit):_ Nach jedem Einzelschritt ist exakt festgelegt, welche Anweisung als Nächstes ausgeführt wird; es gibt keinen Interpretationsspielraum.
-\t_Sequenz (Folge):_ Anweisungen werden streng nacheinander von oben nach unten abgearbeitet.
-\t_Bedingte Verzweigung (Selektion):_ Eine logische Bedingung (Wahrheitswert wahr oder falsch) entscheidet darüber, ob der Ja-Zweig oder der Nein-Zweig durchlaufen wird.
-\t_Schleife (Iteration):_ Ein Anweisungsblock wird solange wiederholt, wie eine Laufbedingung erfüllt ist (kopfgesteuerte Solange-Schleife) oder eine feste Anzahl erreicht wurde.
-\t_Satz von Böhm und Jacopini (1966):_ Jedes berechenbare Problem lässt sich ausschließlich durch die Kombination von Sequenz, Verzweigung und Schleife ohne Sprungbefehle lösen.
-\t_Terminierung vs. Endlosschleife:_ Während Berechnungsalgorithmen nach endlich vielen Schritten enden müssen, nutzen eingebettete Steuerungen oft eine dauerhafte Ereignisschleife.
</Rahmen>

((19))

### Logische Verknüpfungen und Sensordaten-Auswertung

Damit ein autonomer Transportroboter in einer Werkhalle nicht mit Regalen oder Personen kollidiert, kombiniert seine Steuerung oft mehrere Sensoren über boolesche Operatoren (_UND_, _ODER_, _NICHT_). Ein Ausweichmanöver wird genau dann eingeleitet, wenn der vordere Ultraschallsensor ein Hindernis meldet ($A = 1$) _oder_ der Stoßfänger-Taster ausgelöst wird ($B = 1$).

### Tabelle 1.1: Wahrheitstabelle und Aktor-Reaktion der Robotersteuerung

<Tabelle>
Sensor A (Abstand < 25 cm)\tSensor B (Taster vorn)\tVerknüpfung A ODER B\tAktor-Befehl (Fahrmotoren)
0 (frei)\t0 (nicht gedrückt)\t0 (falsch)\tGeradeaus fahren ($v = 50\\,\\%$)
0 (frei)\t1 (gedrückt)\t1 (wahr)\tSofort stoppen & zurücksetzen
1 (Hindernis nah)\t0 (nicht gedrückt)\t1 (wahr)\tStoppen & $90^\\circ$ rechts drehen
1 (Hindernis nah)\t1 (gedrückt)\t1 (wahr)\tNot-Stopp & Warnsignalton
</Tabelle>

### Aufgabe 1: Programmablaufplan nachvollziehen (Trace-Tabelle)

Der Ultraschallsensor liefert nacheinander die Messwerte $d = 62\\,\\text{cm}$, $d = 38\\,\\text{cm}$, $d = 19\\,\\text{cm}$ und $d = 45\\,\\text{cm}$. Gib für jeden Messwert an, welchen Zweig der Roboter in Abb. 1.1 durchläuft.

### Aufgabe 2: Erweiterung um einen linken und rechten Seitensensor

Formuliere eine geschachtelte Wenn-Dann-Sonst-Bedingung, mit der der Roboter vor einer Drehung prüft, ob rechts mehr Platz ist als links ($d_{\\text{rechts}} > d_{\\text{links}}$).

### Aufgabe 3: Boolesche Algebra im Alltag

Erkläre den Unterschied zwischen einer _UND_-Verknüpfung (Konjunktion) und einer _ODER_-Verknüpfung (Disjunktion) am Beispiel einer automatischen Gewächshaus-Bewässerung.

<Rahmen>
_Checkliste: Teste dich! — Trainingsplan zu Kapitel 1_
-\tIch kann die Begriffe Algorithmus, Sequenz, Verzweigung und Schleife an einem Alltagsbeispiel erläutern (Nachlesen: S. 18, Merksatz).
-\tIch kann einen gegebenen Programmablaufplan (PAP) nach DIN 66001 lesen und für konkrete Eingabewerte Schritt für Schritt auswerten (Nachlesen: S. 18, Abb. 1.1).
-\tIch kann einfache und zusammengesetzte Bedingungen mit den logischen Operatoren _UND_, _ODER_ sowie _NICHT_ in einer Wahrheitstabelle darstellen (Nachlesen: S. 19, Tab. 1.1).
-\tIch kann erklären, warum eine Robotersteuerung in einer dauerhaften Ereignisschleife arbeitet und wie ein Not-Stopp-Abbruchkriterium integriert wird (Nachlesen: S. 19).
-\tIch kann zu einer textuell beschriebenen Problemstellung selbstständig einen fehlerfreien Programmablaufplan entwerfen und testen (Übung: Aufgabe 2).
-\tIch kann im Simulator mithilfe des Mediencodes 74108-18 eigene Schwellenwerte experimentell erproben und optimieren (Digitale Zusatzaufgabe: S. 18).
</Rahmen>
"""

    # -------------------- 11. SEK II MATHEMATIK ANALYSIS (B5-Breit 195x260 mm) --------------------
    s2_ana_raw = """((50))

# Kapitel 2: Analysis — Untersuchung ganzrationaler Funktionen

## 2.1 Charakteristische Punkte, Ableitungsfunktion und Integralfläche

Eine ganzrationale Funktion $n$-ten Grades besitzt die allgemeine Funktionsgleichung $f(x) = a_n \\cdot x^n + a_{n-1} \\cdot x^{n-1} + \\dots + a_1 \\cdot x + a_0$ mit $a_n \\neq 0$. Ihr globales Verhalten für betragsgroße Werte von $x$ wird ausschließlich vom Leitkoeffizienten $a_n$ und dem höchsten Exponenten $n$ bestimmt. Mithilfe der ersten und zweiten Ableitungsfunktion $f'(x)$ und $f''(x)$ lassen sich lokale Extrempunkte sowie Wendepunkte exakt berechnen.

![Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich](figures/mathe_analysis_funktionsgraphen.png)

Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich

**Merksatz: Notwendige und hinreichende Kriterien der Differential- und Integralrechnung**
- Potenz- und Summenregel der Ableitung: Für $f(x) = c \\cdot x^n$ gilt $f'(x) = c \\cdot n \\cdot x^{n-1}$.
- Notwendige Bedingung für lokale Extremstellen: $f'(x_E) = 0$ (waagerechte Tangente).
- Hinreichende Bedingung für lokale Extremstellen: Gilt $f'(x_E) = 0$ und $f''(x_E) < 0$, so liegt bei $x_E$ ein lokales Maximum (Hochpunkt $H$) vor. Gilt $f'(x_E) = 0$ und $f''(x_E) > 0$, so liegt bei $x_E$ ein lokales Minimum (Tiefpunkt $T$) vor.
- Notwendige und hinreichende Bedingung für Wendestellen (Krümmungswechsel): Gilt $f''(x_W) = 0$ und $f'''(x_W) \\neq 0$, so besitzt der Graph bei $W(x_W \\mid f(x_W))$ einen Wendepunkt.
- Hauptsatz der Differential- und Integralrechnung (Bestimmtes Integral): Ist $F(x)$ eine Stammfunktion von $f(x)$ mit $F'(x) = f(x)$, so gilt auf dem Intervall $[a; b]$: $\\int_a^b f(x)\\,dx = [F(x)]_a^b = F(b) - F(a)$.
- Symmetrieverhalten ganzrationaler Funktionen: Nur gerade Exponenten ($f(-x) = f(x)$): Achsensymmetrie zur $y$-Achse. Nur ungerade Exponenten ($f(-x) = -f(x)$): Punktsymmetrie zum Koordinatenursprung $O(0 \\mid 0)$.
- Tangentensteigung $m_t$ in einem Kurvenpunkt $P(x_0 \\mid f(x_0))$: $t(x) = f'(x_0) \\cdot (x - x_0) + f(x_0)$.

((51))

### Tabelle 2.1: Charakteristische Punkte von f(x) = 0,25 x^3 - 1,5 x^2 + 2 x + 1

| Merkmal / Punkt | x-Wert | Funktionswert $f(x)$ | Ableitungswerte & Begründung |
| :--- | :--- | :--- | :--- |
| y-Achsenabschnitt $S_y$ | $x = 0$ | $f(0) = 1{,}00$ | $f'(0) = 2{,}00$ (steigend) |
| Hochpunkt $H$ (Maximum) | $x_H \\approx 0{,}85$ | $f(x_H) \\approx 1{,}77$ | $f'(x_H) = 0$ und $f''(x_H) \\approx -1{,}73 < 0$ |
| Wendepunkt $W$ | $x_W = 2{,}00$ | $f(2) = 1{,}00$ | $f''(2) = 0$ und $f'''(2) = 1{,}50 \\neq 0$ |
| Tiefpunkt $T$ (Minimum) | $x_T \\approx 3{,}15$ | $f(x_T) \\approx 0{,}23$ | $f'(x_T) = 0$ und $f''(x_T) \\approx +1{,}73 > 0$ |
| Randpunkt im Intervall | $x = 4{,}00$ | $f(4) = 1{,}00$ | $f'(4) = 2{,}00$ (punktsymmetrisch zu $W$) |

**Tipp: Musterlösung zur Berechnung des bestimmten Integrals auf [0; 4]**
- Gegeben ist $f(x) = 0{,}25 x^3 - 1{,}5 x^2 + 2 x + 1$ mit den Ableitungen $f'(x) = 0{,}75 x^2 - 3 x + 2$ und $f''(x) = 1{,}5 x - 3$. Da $f(x) > 0$ für alle $x \\in [0; 4]$ gilt, liegt der Graph vollständig über der $x$-Achse.
- Bildung einer Stammfunktion $F(x)$: $F(x) = \\frac{1}{16} x^4 - 0{,}5 x^3 + x^2 + x$.
- Einsetzen der Integrationsgrenzen $a = 0$ und $b = 4$ nach dem Hauptsatz: $A = \\int_0^4 f(x)\\,dx = F(4) - F(0) = (16 - 32 + 16 + 4) - 0 = 4$ Flächeneinheiten (FE).
- Kontrolle durch Punktsymmetrie zu $W(2 \\mid 1)$: Das Rechteck der Breite 4 und Höhe 1 hat genau $A = 4\\,\\text{FE}$.

### Aufgabe 1 □: Ableitungsfunktionen und Steigung bestimmen

Bilden Sie zu den folgenden ganzrationalen Funktionen jeweils die erste und zweite Ableitung und berechnen Sie die Steigung des Graphen an der Stelle $x_0 = 2$:
a) $g(x) = x^3 - 6 x^2 + 9 x - 2$
b) $h(x) = -0{,}5 x^4 + 3 x^2 - 4$
c) $k(x) = 2 x^3 + 4 x - 7$

### Aufgabe 2 ◩: Vollständige Kurvendiskussion und Wendetangente

Gegeben ist die Funktion $f(x) = x^3 - 3 x^2 - 9 x + 11$. Bestimmen Sie rechnerisch die Koordinaten aller lokalen Extrempunkte sowie des Wendepunkts $W$. Stellen Sie anschließend die Gleichung der Wendetangente $t_W(x)$ auf und prüfen Sie die Symmetrie zum Wendepunkt.

### Aufgabe 3 ■: Steckbriefaufgabe und Flächeninhalt zwischen zwei Graphen

Der Graph einer ganzrationalen Funktion 3. Grades verläuft durch den Ursprung $O(0 \\mid 0)$, besitzt im Punkt $W(2 \\mid 4)$ einen Wendepunkt und hat dort die Steigung $m = -3$.
a) Stellen Sie das lineare Gleichungssystem auf und weisen Sie nach, dass $p(x) = 0{,}5 x^3 - 3 x^2 + 3 x + 0$ bzw. mit angepasstem Koeffizienten die Bedingungen erfüllt.
b) Berechnen Sie den Inhalt der Fläche, die der Graph von $f(x)$ aus Abb. 2.1 mit der Wendetangente und der $y$-Achse im ersten Quadranten einschließt.

Hinweis zur Selbstkontrolle: Nutzen Sie für Teilaufgabe b) die Differenzfunktion $d(x) = f(x) - t_W(x)$ und bestimmen Sie vor der Integration die Schnittstellen im Intervall $[0; 4]$.
"""

    s2_ana_ueb = """((50))

# Kapitel 2: Analysis — Untersuchung ganzrationaler Funktionen

## 2.1 Charakteristische Punkte, Ableitungsfunktion und Integralfläche

Eine ganzrationale Funktion $n$-ten Grades besitzt die allgemeine Funktionsgleichung $f(x) = a_n \\cdot x^n + a_{n-1} \\cdot x^{n-1} + \\dots + a_1 \\cdot x + a_0$ mit $a_n \\neq 0$. Ihr globales Verhalten für betragsgroße Werte von $x$ wird ausschließlich vom Leitkoeffizienten $a_n$ und dem höchsten Exponenten $n$ bestimmt. Mithilfe der ersten und zweiten Ableitungsfunktion $f'(x)$ und $f''(x)$ lassen sich lokale Extrempunkte sowie Wendepunkte exakt berechnen.

#### Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich

<Bild> Diagramm:
Beschreibung mit Bildtext: Koordinatensystem mit dem blauen Funktionsgraphen $f(x) = \\frac{1}{4}x^3 - 1{,}5x^2 + 2x + 1$, dem roten Ableitungsgraphen $f'(x) = 0{,}75x^2 - 3x + 2$, den markierten Punkten Hochpunkt $H(0{,}85 \\mid 1{,}77)$, Wendepunkt $W(2 \\mid 1)$ und Tiefpunkt $T(3{,}15 \\mid 0{,}23)$ sowie der hellblau schraffierten Integralfläche $A = 4\\,\\text{FE}$ zwischen Graph und $x$-Achse im Intervall $[0; 4]$.
</Bild>

<Rahmen>
_Merksatz: Notwendige und hinreichende Kriterien der Differential- und Integralrechnung_
-\t_Potenz- und Summenregel der Ableitung:_ Für $f(x) = c \\cdot x^n$ gilt $f'(x) = c \\cdot n \\cdot x^{n-1}$.
-\t_Notwendige Bedingung für lokale Extremstellen:_ $f'(x_E) = 0$ (waagerechte Tangente).
-\t_Hinreichende Bedingung für lokale Extremstellen:_ Gilt $f'(x_E) = 0$ und $f''(x_E) < 0$, so liegt bei $x_E$ ein lokales Maximum (Hochpunkt $H$) vor. Gilt $f'(x_E) = 0$ und $f''(x_E) > 0$, so liegt bei $x_E$ ein lokales Minimum (Tiefpunkt $T$) vor.
-\t_Notwendige und hinreichende Bedingung für Wendestellen (Krümmungswechsel):_ Gilt $f''(x_W) = 0$ und $f'''(x_W) \\neq 0$, so besitzt der Graph bei $W(x_W \\mid f(x_W))$ einen Wendepunkt.
-\t_Hauptsatz der Differential- und Integralrechnung (Bestimmtes Integral):_ Ist $F(x)$ eine Stammfunktion von $f(x)$ mit $F'(x) = f(x)$, so gilt auf dem Intervall $[a; b]$: $\\int_a^b f(x)\\,dx = [F(x)]_a^b = F(b) - F(a)$.
-\t_Symmetrieverhalten ganzrationaler Funktionen:_ Nur gerade Exponenten ($f(-x) = f(x)$): Achsensymmetrie zur $y$-Achse. Nur ungerade Exponenten ($f(-x) = -f(x)$): Punktsymmetrie zum Koordinatenursprung $O(0 \\mid 0)$.
-\t_Tangentensteigung $m_t$ in einem Kurvenpunkt $P(x_0 \\mid f(x_0))$:_ $t(x) = f'(x_0) \\cdot (x - x_0) + f(x_0)$.
</Rahmen>

((51))

### Tabelle 2.1: Charakteristische Punkte von f(x) = 0,25 x^3 - 1,5 x^2 + 2 x + 1

<Tabelle>
Merkmal / Punkt\tx-Wert\tFunktionswert $f(x)$\tAbleitungswerte & Begründung
y-Achsenabschnitt $S_y$\t$x = 0$\t$f(0) = 1{,}00$\t$f'(0) = 2{,}00$ (steigend)
Hochpunkt $H$ (Maximum)\t$x_H \\approx 0{,}85$\t$f(x_H) \\approx 1{,}77$\t$f'(x_H) = 0$ und $f''(x_H) \\approx -1{,}73 < 0$
Wendepunkt $W$\t$x_W = 2{,}00$\t$f(2) = 1{,}00$\t$f''(2) = 0$ und $f'''(2) = 1{,}50 \\neq 0$
Tiefpunkt $T$ (Minimum)\t$x_T \\approx 3{,}15$\t$f(x_T) \\approx 0{,}23$\t$f'(x_T) = 0$ und $f''(x_T) \\approx +1{,}73 > 0$
Randpunkt im Intervall\t$x = 4{,}00$\t$f(4) = 1{,}00$\t$f'(4) = 2{,}00$ (punktsymmetrisch zu $W$)
</Tabelle>

<Rahmen>
_Tipp: Musterlösung zur Berechnung des bestimmten Integrals auf [0; 4]_
-\tGegeben ist $f(x) = 0{,}25 x^3 - 1{,}5 x^2 + 2 x + 1$ mit den Ableitungen $f'(x) = 0{,}75 x^2 - 3 x + 2$ und $f''(x) = 1{,}5 x - 3$. Da $f(x) > 0$ für alle $x \\in [0; 4]$ gilt, liegt der Graph vollständig über der $x$-Achse.
-\t_Bildung einer Stammfunktion $F(x)$:_ $F(x) = \\frac{1}{16} x^4 - 0{,}5 x^3 + x^2 + x$.
-\t_Einsetzen der Integrationsgrenzen $a = 0$ und $b = 4$ nach dem Hauptsatz:_ $A = \\int_0^4 f(x)\\,dx = F(4) - F(0) = (16 - 32 + 16 + 4) - 0 = 4$ Flächeneinheiten (FE).
-\t_Kontrolle durch Punktsymmetrie zu $W(2 \\mid 1)$:_ Das Rechteck der Breite 4 und Höhe 1 hat genau $A = 4\\,\\text{FE}$.
</Rahmen>

### Aufgabe 1: Ableitungsfunktionen und Steigung bestimmen
[leicht]

Bilden Sie zu den folgenden ganzrationalen Funktionen jeweils die erste und zweite Ableitung und berechnen Sie die Steigung des Graphen an der Stelle $x_0 = 2$:
a) $g(x) = x^3 - 6 x^2 + 9 x - 2$
b) $h(x) = -0{,}5 x^4 + 3 x^2 - 4$
c) $k(x) = 2 x^3 + 4 x - 7$

### Aufgabe 2: Vollständige Kurvendiskussion und Wendetangente
[mittel]

Gegeben ist die Funktion $f(x) = x^3 - 3 x^2 - 9 x + 11$. Bestimmen Sie rechnerisch die Koordinaten aller lokalen Extrempunkte sowie des Wendepunkts $W$. Stellen Sie anschließend die Gleichung der Wendetangente $t_W(x)$ auf und prüfen Sie die Symmetrie zum Wendepunkt.

### Aufgabe 3: Steckbriefaufgabe und Flächeninhalt zwischen zwei Graphen
[schwer]

Der Graph einer ganzrationalen Funktion 3. Grades verläuft durch den Ursprung $O(0 \\mid 0)$, besitzt im Punkt $W(2 \\mid 4)$ einen Wendepunkt und hat dort die Steigung $m = -3$.
a) Stellen Sie das lineare Gleichungssystem auf und weisen Sie nach, dass $p(x) = 0{,}5 x^3 - 3 x^2 + 3 x + 0$ bzw. mit angepasstem Koeffizienten die Bedingungen erfüllt.
b) Berechnen Sie den Inhalt der Fläche, die der Graph von $f(x)$ aus Abb. 2.1 mit der Wendetangente und der $y$-Achse im ersten Quadranten einschließt.

Hinweis zur Selbstkontrolle: Nutzen Sie für Teilaufgabe b) die Differenzfunktion $d(x) = f(x) - t_W(x)$ und bestimmen Sie vor der Integration die Schnittstellen im Intervall $[0; 4]$.
"""

    # -------------------- 12. GRUNDSCHULE LESEBUCH DOPPELSEITE (240x170 mm) --------------------
    gs_les_raw = """((18)) / ((19))

# Kapitel 3: Der kleine Leuchtturm auf der Felseninsel

## 3.1 Ein stürmischer Abend an der Nordsee

![Abb. 3.1: Der kleine Leuchtturm weist dem Fischerboot den Weg](figures/gs_lesebuch_kueste.png)

Abb. 3.1: Der kleine Leuchtturm weist dem Fischerboot den Weg

Auf einer runden Felseninsel mitten im Wattenmeer steht ein kleiner rot-weiß gestreifter Leuchtturm. Jeden Abend, sobald die Sonne hinter dem Horizont versinkt, steigt Leuchtturmwärter Piet die vierzig Holzstufen bis zur gläsernen Laternenkuppel hinauf und entzündet das helle Leuchtfeuer.
5 Heute pfeift ein kräftiger Herbstwind über die Wellen. Dunkle Regenwolken ziehen über den Himmel, und die schäumende Gischt spritzt hoch an die Felsen. Draußen auf dem offenen Meer schaukelt das kleine Fischerboot "Nordstern" von Kapitänin Hanna. Durch den dichten Nebel kann Hanna die rettende Hafeneinfahrt kaum noch erkennen.
10 Da blitzt plötzlich der goldgelbe Lichtstrahl des kleinen Leuchtturms dreimal kurz hintereinander durch die Dunkelheit: hell – dunkel – hell!
15 Sofort weiß Kapitänin Hanna, wo die flachen Sandbänke liegen, und steuert ihr Boot sicher in das ruhige Hafenbecken der Insel.

**Wortbausteine: Zusammengesetzte Nomen rund um das Meer**
- Aus zwei Nomen kannst du ein neues zusammengesetztes Nomen bilden. Das zweite Wort (Grundwort) bestimmt immer den Artikel (der, die oder das) des gesamten Wortes:
- das Leuchtfeuer + der Turm -> der Leuchtturm (Mehrzahl: die Leuchttürme).
- der Sturm + die Flut -> die Sturmflut; der Nebel + das Horn -> das Nebelhorn.
- der Hafen + die Einfahrt -> die Hafeneinfahrt; der Sand + die Bank -> die Sandbank.
- Merke: Manchmal steht zwischen beiden Wörtern ein Fugen-s oder Fugen-n (das Schiffshorn).

((20)) / ((21))

### Tabelle 3.1: Wer hat welche Aufgabe in der Geschichte?

| Figur / Gegenstand | Ort in der Geschichte | Wichtige Aufgabe im Herbststurm |
| :--- | :--- | :--- |
| Leuchtturmwärter Piet | Laternenkuppel auf dem Turm | Entzündet und überwacht das Leuchtfeuer |
| Kleiner Leuchtturm | Felseninsel im Wattenmeer | Sendet dreimal kurz das Lichtsignal aus |
| Kapitänin Hanna | Fischerboot "Nordstern" | Hält Ausschau und lenkt das Boot um die Sandbank |

### Aufgabe 1: Textstellen mit Zeilenzahlen finden

Lies die Geschichte auf der Doppelseite 18/19 noch einmal genau durch und beantworte:
a) Wie viele Holzstufen muss Leuchtturmwärter Piet jeden Abend hinaufsteigen?
b) Warum kann Kapitänin Hanna die Hafeneinfahrt im Sturm kaum erkennen (Zeile 5 bis 9)?
c) Woran erkennt Hanna das besondere Lichtsignal ihres Heimatleuchtturms (Zeile 10 bis 15)?

### Aufgabe 2: Zusammengesetzte Nomen bilden und Artikel bestimmen

Bilde aus den Wortbausteinen zusammengesetzte Nomen mit dem richtigen Artikel:
a) das Meer + das Wasser -> ____
b) der Herbst + der Wind -> ____
c) das Holz + die Stufe -> ____

### Aufgabe 3: Eine eigene Fortsetzung schreiben

Stell dir vor, Kapitänin Hanna legt mit ihrem Boot im Hafen an und besucht Piet im Leuchtturm. Schreibe in dein Heft, worüber die beiden bei einer Tasse heißem Tee sprechen.

**Tipp: So findest du Antworten schnell mit den Zeilenzahlen am Rand**
- Am linken Textrand siehst du in jeder fünften Zeile eine kleine Zahl (5, 10, 15).
- Fahre mit dem Finger von der genannten Zeilenzahl nach rechts in den Satz hinein.
- Unterstreiche wichtige Schlüsselwörter mit Bleistift, bevor du deine Antwort formulierst.
"""

    gs_les_ueb = """((18)) / ((19))

# Kapitel 3: Der kleine Leuchtturm auf der Felseninsel

## 3.1 Ein stürmischer Abend an der Nordsee

#### Abb. 3.1: Der kleine Leuchtturm weist dem Fischerboot den Weg

<Bild> Zeichnung:
Beschreibung mit Bildtext: Ein rot-weiß gestreifter Leuchtturm auf einer Felseninsel im Meer sendet bei Nacht einen gelben Lichtkegel über die Wellen zum Fischerboot "Nordstern". Bildtext: Der kleine Leuchtturm weist dem Fischerboot "Nordstern" den sicheren Weg in den Hafen.
</Bild>

Auf einer runden Felseninsel mitten im Wattenmeer steht ein kleiner rot-weiß gestreifter Leuchtturm. Jeden Abend, sobald die Sonne hinter dem Horizont versinkt, steigt Leuchtturmwärter Piet die vierzig Holzstufen bis zur gläsernen Laternenkuppel hinauf und entzündet das helle Leuchtfeuer.
5 Heute pfeift ein kräftiger Herbstwind über die Wellen. Dunkle Regenwolken ziehen über den Himmel, und die schäumende Gischt spritzt hoch an die Felsen. Draußen auf dem offenen Meer schaukelt das kleine Fischerboot "Nordstern" von Kapitänin Hanna. Durch den dichten Nebel kann Hanna die rettende Hafeneinfahrt kaum noch erkennen.
10 Da blitzt plötzlich der goldgelbe Lichtstrahl des kleinen Leuchtturms dreimal kurz hintereinander durch die Dunkelheit: hell – dunkel – hell!
15 Sofort weiß Kapitänin Hanna, wo die flachen Sandbänke liegen, und steuert ihr Boot sicher in das ruhige Hafenbecken der Insel.

<Rahmen>
_Wortbausteine: Zusammengesetzte Nomen rund um das Meer_
-\tAus zwei Nomen kannst du ein neues zusammengesetztes Nomen bilden. Das zweite Wort (Grundwort) bestimmt immer den Artikel (der, die oder das) des gesamten Wortes:
-\tdas Leuchtfeuer + der Turm \\to _der Leuchtturm_ (Mehrzahl: die Leuchttürme).
-\tder Sturm + die Flut \\to _die Sturmflut_; der Nebel + das Horn \\to _das Nebelhorn_.
-\tder Hafen + die Einfahrt \\to _die Hafeneinfahrt_; der Sand + die Bank \\to _die Sandbank_.
-\t_Merke:_ Manchmal steht zwischen beiden Wörtern ein Fugen-s oder Fugen-n (_das Schiffshorn_).
</Rahmen>

((20)) / ((21))

### Tabelle 3.1: Wer hat welche Aufgabe in der Geschichte?

<Tabelle>
Figur / Gegenstand\tOrt in der Geschichte\tWichtige Aufgabe im Herbststurm
Leuchtturmwärter Piet\tLaternenkuppel auf dem Turm\tEntzündet und überwacht das Leuchtfeuer
Kleiner Leuchtturm\tFelseninsel im Wattenmeer\tSendet dreimal kurz das Lichtsignal aus
Kapitänin Hanna\tFischerboot "Nordstern"\tHält Ausschau und lenkt das Boot um die Sandbank
</Tabelle>

### Aufgabe 1: Textstellen mit Zeilenzahlen finden

Lies die Geschichte auf der Doppelseite 18/19 noch einmal genau durch und beantworte:
a) Wie viele Holzstufen muss Leuchtturmwärter Piet jeden Abend hinaufsteigen?
b) Warum kann Kapitänin Hanna die Hafeneinfahrt im Sturm kaum erkennen (Zeile 5 bis 9)?
c) Woran erkennt Hanna das besondere Lichtsignal ihres Heimatleuchtturms (Zeile 10 bis 15)?

### Aufgabe 2: Zusammengesetzte Nomen bilden und Artikel bestimmen

Bilde aus den Wortbausteinen zusammengesetzte Nomen mit dem richtigen Artikel:
a) das Meer + das Wasser \\to _..._
b) der Herbst + der Wind \\to _..._
c) das Holz + die Stufe \\to _..._

### Aufgabe 3: Eine eigene Fortsetzung schreiben

Stell dir vor, Kapitänin Hanna legt mit ihrem Boot im Hafen an und besucht Piet im Leuchtturm. Schreibe in dein Heft, worüber die beiden bei einer Tasse heißem Tee sprechen.

<Rahmen>
_Tipp: So findest du Antworten schnell mit den Zeilenzahlen am Rand_
-\tAm linken Textrand siehst du in jeder fünften Zeile eine kleine Zahl (5, 10, 15).
-\tFahre mit dem Finger von der genannten Zeilenzahl nach rechts in den Satz hinein.
-\tUnterstreiche wichtige Schlüsselwörter mit Bleistift, bevor du deine Antwort formulierst.
</Rahmen>
"""

    return {
        "grundschule_mathematik": (gs_mathe_raw, gs_mathe_ueb),
        "grundschule_sachkunde": (gs_sachkunde_raw, gs_sachkunde_ueb),
        "grundschule_lesebuch_doppelseite": (gs_les_raw, gs_les_ueb),
        "sek1_deutsch": (s1_deutsch_raw, s1_deutsch_ueb),
        "sek1_englisch": (s1_englisch_raw, s1_englisch_ueb),
        "sek1_geographie": (s1_geo_raw, s1_geo_ueb),
        "sek1_geschichte": (s1_hist_raw, s1_hist_ueb),
        "sek1_informatik": (s1_info_raw, s1_info_ueb),
        "sek2_chemie": (s2_chem_raw, s2_chem_ueb),
        "sek2_biologie": (s2_bio_raw, s2_bio_ueb),
        "sek2_physik_verzeichnisse": (s2_phys_raw, s2_phys_ueb),
        "sek2_mathematik_analysis": (s2_ana_raw, s2_ana_ueb),
    }


def write_book_rules_files() -> None:
    """Writes book-specific *_rules.txt files for the schoolbooks that use difficulty or social-form icons."""
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    rules_by_doc = {
        "grundschule_mathematik": (
            "Datei-spezifische Regeln für grundschule_mathematik:\n"
            "1. Schwierigkeitsgrade (Quadrat-Symbole in den Aufgabenüberschriften):\n"
            "   - □ (leeres Quadrat) wird übertragen als: [leicht]\n"
            "   - ◩ (halb gefülltes Quadrat) wird übertragen als: [mittel]\n"
            "   - ■ (gefülltes Quadrat) wird übertragen als: [schwer]\n"
            "2. Piktogramme neben der Aufgabenüberschrift:\n"
            "   - Blaues Zwei-Personen-Piktogramm (bei Aufgabe 1) wird übertragen als: [Partnerarbeit]\n"
            "   - Gelbes Scheren-Piktogramm (bei Aufgabe 3) wird übertragen als: [Schere und Kleber]\n"
            "3. Schwierigkeitsgrade und Piktogramme stehen in einer eigenen Zeile direkt unter der Aufgabenüberschrift.\n"
        ),
        "grundschule_sachkunde": (
            "Datei-spezifische Regeln für grundschule_sachkunde:\n"
            "1. Dieses Schulbuch verwendet KEINE Schwierigkeitsgrad-Symbole.\n"
            "2. Piktogramme neben der Aufgabenüberschrift:\n"
            "   - Blaues Zwei-Personen-Piktogramm (bei Aufgabe 4) wird auf der Zeile unter der Aufgabenüberschrift übertragen als: [Partnerarbeit]\n"
        ),
        "sek1_englisch": (
            "Datei-spezifische Regeln für sek1_englisch:\n"
            "1. Schwierigkeitsgrade (Stern-Symbole ★ in den Aufgabenüberschriften):\n"
            "   - ★ (ein Stern) wird übertragen als: [leicht]\n"
            "   - ★★ (zwei Sterne) wird übertragen als: [mittel]\n"
            "   - ★★★ (drei Sterne) wird übertragen als: [schwer]\n"
            "2. Piktogramme neben der Aufgabenüberschrift:\n"
            "   - Blaues Zwei-Personen-Piktogramm (bei Aufgabe 2) wird übertragen als: [Partnerarbeit]\n"
            "3. Schwierigkeitsgrade und Piktogramme stehen in einer eigenen Zeile direkt unter der Aufgabenüberschrift.\n"
        ),
        "sek1_geschichte": (
            "Datei-spezifische Regeln für sek1_geschichte:\n"
            "1. Schwierigkeitsgrade (Rauten-Symbole in den Aufgabenüberschriften):\n"
            "   - ◇ (leere Raute) wird übertragen als: [leicht]\n"
            "   - ◈ (halb gefüllte Raute) wird übertragen als: [mittel]\n"
            "   - ◆ (gefüllte Raute) wird übertragen als: [schwer]\n"
            "2. Die Schwierigkeitsgrade stehen in einer eigenen Zeile direkt unter der Aufgabenüberschrift.\n"
        ),
        "sek2_chemie": (
            "Datei-spezifische Regeln für sek2_chemie:\n"
            "1. Schwierigkeitsgrade (Kreis-Symbole vor den Aufgaben im Aufgabenblock):\n"
            "   - ○ (leerer Kreis) wird übertragen als: [leicht]\n"
            "   - ◐ (halb gefüllter Kreis) wird übertragen als: [mittel]\n"
            "   - ● (gefüllter Kreis) wird übertragen als: [schwer]\n"
            "2. Gefahrstoffpiktogramme im Versuchsprotokoll:\n"
            "   - GHS02 wird übertragen als: [Gefahrstoffsymbol: Entzündbar]\n"
            "   - GHS05 wird übertragen als: [Gefahrstoffsymbol: Ätzend]\n"
            "   - GHS07 wird übertragen als: [Gefahrstoffsymbol: Achtung]\n"
        ),
        "sek2_mathematik_analysis": (
            "Datei-spezifische Regeln für sek2_mathematik_analysis:\n"
            "1. Schwierigkeitsgrade (Quadrat-Symbole in den Aufgabenüberschriften):\n"
            "   - □ (leeres Quadrat) wird übertragen als: [leicht]\n"
            "   - ◩ (halb gefülltes Quadrat) wird übertragen als: [mittel]\n"
            "   - ■ (gefülltes Quadrat) wird übertragen als: [schwer]\n"
            "2. Die Schwierigkeitsgrade stehen in einer eigenen Zeile direkt unter der Aufgabenüberschrift.\n"
        ),
    }
    for doc_base, content in rules_by_doc.items():
        rules_path = os.path.join(TEST_DATA_DIR, f"{doc_base}_rules.txt")
        with open(rules_path, "w", encoding="utf-8") as f:
            f.write(content)


LEGACY_COMBINED_DOCS = [
    "grundschule_mathe_sachkunde",
    "sek1_sprachen_deutsch_englisch",
    "sek1_geographie_geschichte",
    "sek2_chemie_biologie",
]


def cleanup_legacy_combined_files() -> None:
    """Removes obsolete multi-subject/multi-language combined PDFs and golden files."""
    for legacy_base in LEGACY_COMBINED_DOCS:
        for pdf_cand in (
            os.path.join(TEST_DATA_DIR, f"{legacy_base}.pdf"),
            os.path.join(TEST_DATA_DIR, f"{legacy_base}_scanned.pdf"),
            os.path.join(TEST_DATA_DIR, f"{legacy_base}_rules.txt"),
        ):
            if os.path.exists(pdf_cand):
                os.remove(pdf_cand)
        for gold_cand in (
            os.path.join(GOLDEN_DIR, f"{legacy_base}_raw.md"),
            os.path.join(GOLDEN_DIR, f"{legacy_base}.raw.golden.md"),
            os.path.join(GOLDEN_DIR, f"{legacy_base}_uebertragungsregeln_09_2025.md"),
            os.path.join(GOLDEN_DIR, f"{legacy_base}.uebertragungsregeln_09_2025.golden.md"),
        ):
            if os.path.exists(gold_cand):
                os.remove(gold_cand)


def write_golden_files_and_metadata(meta_by_doc: Dict[str, Dict[str, Any]]) -> None:
    """Writes canonical golden files (*.raw.golden.md and *.uebertragungsregeln_09_2025.golden.md) and updates golden_image_metadata.json."""
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    cleanup_legacy_combined_files()
    write_book_rules_files()
    truths = get_golden_ground_truths()
    for base_name, (raw_md, ueb_md) in truths.items():
        # Remove obsolete duplicate underscore-named copies if present
        for old_dup in (
            os.path.join(GOLDEN_DIR, f"{base_name}_raw.md"),
            os.path.join(GOLDEN_DIR, f"{base_name}_uebertragungsregeln_09_2025.md"),
        ):
            if os.path.exists(old_dup):
                os.remove(old_dup)

        raw_path = os.path.join(GOLDEN_DIR, f"{base_name}.raw.golden.md")
        ueb_path = os.path.join(GOLDEN_DIR, f"{base_name}.uebertragungsregeln_09_2025.golden.md")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_md)
        with open(ueb_path, "w", encoding="utf-8") as f:
            f.write(ueb_md)

    existing_meta: Dict[str, Any] = {}
    if os.path.exists(GOLDEN_META_PATH):
        with open(GOLDEN_META_PATH, "r", encoding="utf-8") as f:
            existing_meta = json.load(f)

    for legacy_base in LEGACY_COMBINED_DOCS:
        existing_meta.pop(f"{legacy_base}.pdf", None)

    existing_meta.update(meta_by_doc)
    with open(GOLDEN_META_PATH, "w", encoding="utf-8") as f:
        json.dump(existing_meta, f, indent=2, ensure_ascii=False)
        f.write("\n")


def generate_schoolbook_suite() -> Dict[str, Any]:
    """Main entry point to build all 12 single-subject digital PDFs, 12 scanned PDFs, figures, and golden ground truths."""
    os.makedirs(TEST_DATA_DIR, exist_ok=True)
    os.makedirs(FIGURES_DIR, exist_ok=True)
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    fonts = register_fonts()

    gs_figs = generate_gs_figures()
    s1_lang_figs = generate_sek1_lang_figures()
    s1_geo_figs = generate_sek1_geo_hist_figures()
    s2_chem_figs = generate_sek2_chem_bio_figures()
    mf_figs = generate_multi_format_figures()

    # Ensure openstax_history_sample.pdf replaces its CC BY NC-SA 4.0 map with our CC0 1.0 Public Domain map
    sanitize_openstax_history_cc0_map(fonts, mf_figs["fig_openstax_cc0_map"])

    specs = [
        (
            "grundschule_mathematik",
            "Grundschule Klasse 3: Mathematik (DIN A4)",
            build_grundschule_mathe_pdf,
            gs_figs,
            101,
        ),
        (
            "grundschule_sachkunde",
            "Grundschule Klasse 3: Sachunterricht (DIN A4)",
            build_grundschule_sachkunde_pdf,
            gs_figs,
            102,
        ),
        (
            "grundschule_lesebuch_doppelseite",
            "Grundschule Klasse 2/3: Deutsch Lesebuch im Querformat-Doppelseiten-Spread (240x170 mm)",
            build_grundschule_lesebuch_doppelseite_pdf,
            mf_figs,
            103,
        ),
        (
            "sek1_deutsch",
            "Sekundarstufe I Klasse 7: Deutsch (DIN A4)",
            build_sek1_deutsch_pdf,
            s1_lang_figs,
            201,
        ),
        (
            "sek1_englisch",
            "Sekundarstufe I Klasse 7/8: Englisch (DIN A4)",
            build_sek1_englisch_pdf,
            s1_lang_figs,
            202,
        ),
        (
            "sek1_geographie",
            "Sekundarstufe I Klasse 9/10: Geographie (DIN A4)",
            build_sek1_geographie_pdf,
            s1_geo_figs,
            301,
        ),
        (
            "sek1_geschichte",
            "Sekundarstufe I Klasse 9/10: Geschichte (DIN A4)",
            build_sek1_geschichte_pdf,
            s1_geo_figs,
            302,
        ),
        (
            "sek1_informatik",
            "Sekundarstufe I Klasse 7/8: Informatik & Medienbildung im B5+ Standard-Schulbuchformat (190x260 mm)",
            build_sek1_informatik_pdf,
            mf_figs,
            303,
        ),
        (
            "sek2_chemie",
            "Sekundarstufe II Klasse 11–12: Chemie (DIN A4, 2-spaltig)",
            build_sek2_chemie_pdf,
            s2_chem_figs,
            401,
        ),
        (
            "sek2_biologie",
            "Sekundarstufe II Klasse 11–12: Biologie (DIN A4, 2-spaltig)",
            build_sek2_biologie_pdf,
            s2_chem_figs,
            402,
        ),
        (
            "sek2_physik_verzeichnisse",
            "Sekundarstufe II Klasse 11–12: Physik (Inhalts-, Abbildungs-, Tabellen- und Bildverzeichnis, DIN A4)",
            build_sek2_physik_verzeichnisse_pdf,
            s2_chem_figs,
            403,
        ),
        (
            "sek2_mathematik_analysis",
            "Sekundarstufe II EF/Q1: Mathematik Analysis im B5-Breitformat (195x260 mm)",
            build_sek2_mathematik_analysis_pdf,
            mf_figs,
            404,
        ),
    ]

    meta_by_doc: Dict[str, Dict[str, Any]] = {}
    generated_pdfs: List[str] = []

    for base_name, desc, builder_fn, fig_dict, scan_seed in specs:
        digital_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}.pdf")
        scanned_pdf = os.path.join(TEST_DATA_DIR, f"{base_name}_scanned.pdf")
        images_meta = builder_fn(digital_pdf, fonts, fig_dict)
        generate_scanned_pdf(digital_pdf, scanned_pdf, seed=scan_seed)
        meta_by_doc[f"{base_name}.pdf"] = {
            "description": desc,
            "total_images": len(images_meta),
            "images": images_meta,
        }
        generated_pdfs.extend([digital_pdf, scanned_pdf])

    write_golden_files_and_metadata(meta_by_doc)
    return {"pdfs": generated_pdfs, "metadata": meta_by_doc}


if __name__ == "__main__":
    summary = generate_schoolbook_suite()
    print(f"Generated {len(summary['pdfs'])} schoolbook PDFs and updated golden ground truths.")


