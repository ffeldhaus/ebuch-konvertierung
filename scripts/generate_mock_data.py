import os
import sys
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Initialize directories
script_dir = os.path.dirname(os.path.abspath(__file__))
assets_dir = os.path.abspath(os.path.join(script_dir, "..", "assets"))
test_data_dir = os.path.abspath(os.path.join(script_dir, "..", "testdata"))
images_dir = os.path.join(assets_dir, "images")
os.makedirs(images_dir, exist_ok=True)
os.makedirs(test_data_dir, exist_ok=True)

# 1. Generate Mock Images using Pillow (Illustrations & Pixel Photographs)
image_path = os.path.join(images_dir, "mock_diagram.png")
image_path_3a = os.path.join(images_dir, "mock_diagram_3a.png")
image_path_3b = os.path.join(images_dir, "mock_diagram_3b.png")
image_path_3c = os.path.join(images_dir, "mock_photo_3c.png")
image_path_3d = os.path.join(images_dir, "mock_diagram_3d.png")
image_path_3e = os.path.join(images_dir, "mock_photo_3e.png")
image_path_4 = os.path.join(images_dir, "mock_diagram_4.png")

print(f"Generating mock diagram (Page 1): {image_path}...")
img = Image.new("RGB", (600, 400), color=(240, 248, 255))
draw = ImageDraw.Draw(img)
draw.polygon([(300, 100), (200, 300), (400, 300)], fill=(220, 220, 220), outline=(100, 100, 100), width=2)
draw.line([(50, 220), (250, 220)], fill=(255, 255, 255), width=4)
draw.text((80, 190), "Weisses Licht", fill=(0, 0, 0))
colors = [
    (255, 0, 0), (255, 127, 0), (255, 255, 0),
    (0, 255, 0), (0, 0, 255), (75, 0, 130), (148, 0, 211)
]
for i, color in enumerate(colors):
    y_offset = i * 6
    draw.line([(350, 250), (550, 180 + y_offset)], fill=color, width=3)
draw.text((450, 150), "Spektrum", fill=(0, 0, 0))
img.save(image_path)

# Page 3 Top 1: Vector Drawing Illustration (Prism Front)
img_3a = Image.new("RGB", (300, 200), color=(248, 250, 252))
draw_3a = ImageDraw.Draw(img_3a)
draw_3a.polygon([(150, 30), (50, 170), (250, 170)], fill=(219, 234, 254), outline=(37, 99, 235), width=3)
draw_3a.line([(150, 30), (150, 170)], fill=(147, 197, 253), width=2)
draw_3a.text((105, 175), "Frontansicht (Zeichnung)", fill=(30, 41, 59))
img_3a.save(image_path_3a)

# Page 3 Top 2: Ray Tracing Diagram (Prism Side)
img_3b = Image.new("RGB", (300, 200), color=(248, 250, 252))
draw_3b = ImageDraw.Draw(img_3b)
draw_3b.rectangle([(40, 40), (260, 160)], fill=(241, 245, 249), outline=(100, 116, 139), width=2)
draw_3b.line([(20, 100), (280, 100)], fill=(239, 68, 68), width=3) # Ray
draw_3b.line([(150, 30), (150, 170)], fill=(148, 163, 184), width=1) # Normal
draw_3b.text((95, 165), "Strahlengang (Diagramm)", fill=(30, 41, 59))
img_3b.save(image_path_3b)

# Page 3 Top 3: Pixel Photograph (Photographic look with texture/gradient)
img_3c = Image.new("RGB", (300, 200), color=(15, 23, 42))
draw_3c = ImageDraw.Draw(img_3c)
for y in range(200):
    val = int(20 + 40 * (y / 200.0))
    for x in range(300):
        # Add subtle photographic noise / gradient
        noise = (x * 7 + y * 13) % 15
        img_3c.putpixel((x, y), (val + noise, val + 10 + noise, val + 25 + noise))
draw_3c = ImageDraw.Draw(img_3c)
# Draw glass prism reflection in dark laboratory room
draw_3c.polygon([(150, 40), (80, 160), (220, 160)], fill=(70, 95, 130), outline=(180, 210, 245), width=2)
draw_3c.line([(30, 110), (130, 110)], fill=(255, 255, 255), width=3)
draw_3c.line([(170, 110), (270, 80)], fill=(255, 100, 100), width=2)
draw_3c.line([(170, 110), (270, 140)], fill=(100, 150, 255), width=2)
draw_3c.text((85, 170), "Laborversuch (Fotoaufnahme)", fill=(226, 232, 240))
img_3c.save(image_path_3c)

# Page 3 Bottom 1: Vector Illustration (Reflection on Mirror)
img_3d = Image.new("RGB", (300, 200), color=(248, 250, 252))
draw_3d = ImageDraw.Draw(img_3d)
draw_3d.line([(30, 150), (270, 150)], fill=(51, 65, 85), width=4) # Mirror surface
draw_3d.line([(150, 30), (150, 150)], fill=(148, 163, 184), width=1) # Normal
draw_3d.line([(60, 60), (150, 150)], fill=(16, 185, 129), width=3) # Einfallender Strahl
draw_3d.line([(150, 150), (240, 60)], fill=(16, 185, 129), width=3) # Reflektierter Strahl
draw_3d.text((80, 160), "Reflexionsgesetz (Illustration)", fill=(30, 41, 59))
img_3d.save(image_path_3d)

# Page 3 Bottom 2: Pixel Photograph (Laser in Water Tank)
img_3e = Image.new("RGB", (300, 200), color=(8, 47, 73))
draw_3e = ImageDraw.Draw(img_3e)
for y in range(200):
    val = int(10 + 30 * (y / 200.0))
    for x in range(300):
        noise = (x * 11 + y * 17) % 12
        img_3e.putpixel((x, y), (val, val + 35 + noise, val + 65 + noise))
draw_3e = ImageDraw.Draw(img_3e)
draw_3e.line([(20, 80), (280, 80)], fill=(56, 189, 248), width=2) # Water surface
draw_3e.line([(50, 30), (150, 80)], fill=(74, 222, 128), width=3) # Laser in air
draw_3e.line([(150, 80), (220, 180)], fill=(34, 197, 94), width=3) # Laser in water
draw_3e.text((70, 175), "Laserbrechung im Wasser (Foto)", fill=(240, 249, 255))
img_3e.save(image_path_3e)

# Page 4: Diagram for Total Reflection
img_4 = Image.new("RGB", (300, 200), color=(248, 250, 252))
draw_4 = ImageDraw.Draw(img_4)
draw_4.line([(20, 100), (280, 100)], fill=(71, 85, 105), width=3)
draw_4.line([(50, 170), (150, 100)], fill=(234, 88, 12), width=3)
draw_4.line([(150, 100), (250, 170)], fill=(234, 88, 12), width=3)
draw_4.text((75, 170), "Totalreflexion (Diagramm)", fill=(30, 41, 59))
img_4.save(image_path_4)
print("All 6 test images generated successfully.")

# 2. Generate Mock educational DOCX Document
docx_path = os.path.join(test_data_dir, "test_educational.docx")
print(f"Generating mock DOCX: {docx_path}...")
doc = Document()

# Add standard styles and properties
title = doc.add_heading("Physik für die Sekundarstufe II", 0)
subtitle = doc.add_heading("Kapitel 4: Optik und Lichtbrechung", 1)

# Introduction text
p1 = doc.add_paragraph(
    "Das Phänomen der Lichtbrechung (Refraktion) ist die Richtungsänderung einer Welle durch eine "
    "Geschwindigkeitsänderung beim Übergang in ein anderes Medium. Ein bekanntes optisches Element zur "
    "Untersuchung dieses Effekts ist das Prisma, welches weißes Licht in seine Spektralfarben zerlegen kann."
)

# Add list of refraction facts
doc.add_heading("Wichtige Grundregeln", 2)
# Ref: 2.1.4: Liste, Liste 2
p_list1 = doc.add_paragraph("-\tLicht breitet sich im Vakuum mit c = 299.792 km/s aus.", style="List Bullet")
p_list2 = doc.add_paragraph("-\tBeim Übergang in ein dichteres Medium verringert sich die Lichtgeschwindigkeit.", style="List Bullet")
p_list3 = doc.add_paragraph("-\tDer Brechungsindex n beschreibt das Verhältnis der Lichtgeschwindigkeit im Vakuum zu der im Medium.", style="List Bullet")

# Add Section with 2 columns if possible
# Standard text before diagram
doc.add_heading("Versuch: Zerlegung durch ein Prisma", 2)
doc.add_paragraph("Betrachten wir das nachfolgende Experiment zur Dispersion:")

# Add Mock Image with caption and annotations
# We add image first
doc.add_picture(image_path, width=Inches(4.5))
# Caption text
p_cap = doc.add_paragraph("Abbildung 4.1: Versuchsaufbau zur optischen Dispersion mit einem Glasprisma.")
p_cap.runs[0].font.italic = True

# Add sidebar or box (Rahmen)
doc.add_heading("Definition", 2)
p_box = doc.add_paragraph(
    "Merksatz:\n"
    "Die Abhängigkeit des Brechungsindex n von der Frequenz (bzw. Wellenlänge) "
    "des Lichts bezeichnet man als Dispersion. Rotes Licht wird weniger stark "
    "gebrochen als blaues Licht, weshalb ein breites Farbspektrum entsteht."
)

# End of Page 1: Add page break and page number
doc.add_paragraph()
p_p45 = doc.add_paragraph("[Seite 45]")
p_p45.alignment = WD_ALIGN_PARAGRAPH.RIGHT
doc.add_page_break()

# Add Table (Vocabulary/Parameters)
doc.add_heading("Physikalische Grössen und Konstanten", 2)
table = doc.add_table(rows=4, cols=3)
table.style = 'Light Shading Accent 1'

# Headers
hdr_cells = table.rows[0].cells
hdr_cells[0].text = 'Symbol'
hdr_cells[1].text = 'Bedeutung'
hdr_cells[2].text = 'Typischer Wert / Einheit'

# Row 1
row_cells = table.rows[1].cells
row_cells[0].text = 'c'
row_cells[1].text = 'Lichtgeschwindigkeit im Vakuum'
p = row_cells[2].paragraphs[0]
p.text = '2.9979 x 10'
r = p.add_run('8')
r.font.superscript = True
p.add_run(' ')
r2 = p.add_run('m')
r2.font.superscript = True
p.add_run('/')
r3 = p.add_run('s')
r3.font.subscript = True

# Row 2
row_cells = table.rows[2].cells
p2 = row_cells[0].paragraphs[0]
p2.text = 'n'
r_sub = p2.add_run('Glas')
r_sub.font.subscript = True
row_cells[1].text = 'Brechungsindex von Kronglas'
row_cells[2].text = '1.51 - 1.54'

# Row 3
row_cells = table.rows[3].cells
row_cells[0].text = 'λ'
row_cells[1].text = 'Wellenlänge des sichtbaren Lichts'
row_cells[2].text = '380 - 780 nm'

# Add Footnote references
doc.add_paragraph("")
doc.add_paragraph(
    "Im optischen Dichte-Experiment^1 wurde nachgewiesen, dass Licht beim Übergang von Luft in Wasser "
    "gebrochen wird. Dieser Effekt lässt sich mathematisch durch das Snelliussche Brechungsgesetz beschreiben^2."
)

doc.add_heading("Mathematische Formeln im Fließtext:", level=3)
p_math1 = doc.add_paragraph("Hier ist eine inline Formel: ")
p_math1.add_run("n")
p_math1.add_run("1").font.subscript = True
p_math1.add_run(" · sin(α) = n")
p_math1.add_run("2").font.subscript = True
p_math1.add_run(" · sin(β)")

p_math2 = doc.add_paragraph("Hier ist ein MathML-Render-Beispiel für dieselbe Formel:")

p_math3 = doc.add_paragraph()
p_math3.add_run("n")
p_math3.add_run("1").font.subscript = True
p_math3.add_run(" · sin(α) = n")
p_math3.add_run("2").font.subscript = True
p_math3.add_run(" · sin(β)")

p_math4 = doc.add_paragraph("Hier ist eine komplexe Blockgleichung:")

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def set_cell_top_border(cell, color="4A5568", sz="6", val="single"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    top = OxmlElement('w:top')
    top.set(qn('w:val'), val)
    top.set(qn('w:sz'), sz)
    top.set(qn('w:space'), '0')
    top.set(qn('w:color'), color)
    tcBorders.append(top)
    tcPr.append(tcBorders)

def set_cell_margins(cell, top=100, bottom=100, left=0, right=0):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for name, value in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{name}')
        node.set(qn('w:w'), str(value))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

# Render integral equation with stacked limits using a borderless table (3 columns)
t_int = doc.add_table(rows=3, cols=3)
t_int.autofit = True

# Column widths
t_int.columns[0].width = Inches(0.5)
t_int.columns[1].width = Inches(1.3)
t_int.columns[2].width = Inches(1.3)

# Row 0: Upper limit
cell_up = t_int.rows[0].cells[0]
p_up = cell_up.paragraphs[0]
p_up.alignment = WD_ALIGN_PARAGRAPH.RIGHT
p_up.add_run("∞").font.size = Pt(8)

# Row 1: Integral sign & Integrand & Root Expression
cell_mid = t_int.rows[1].cells[0]
p_mid = cell_mid.paragraphs[0]
p_mid.alignment = WD_ALIGN_PARAGRAPH.RIGHT
r_int = p_mid.add_run("∫")
r_int.font.size = Pt(20)

cell_eq = t_int.rows[1].cells[1]
p_eq = cell_eq.paragraphs[0]
p_eq.alignment = WD_ALIGN_PARAGRAPH.RIGHT
p_eq.add_run("e")
r_exp1 = p_eq.add_run("-x")
r_exp1.font.superscript = True
r_exp2 = p_eq.add_run("²")
r_exp2.font.superscript = True
p_eq.add_run(" dx = √")
set_cell_margins(cell_eq, left=0, right=0)

cell_root = t_int.rows[1].cells[2]
p_root = cell_root.paragraphs[0]
p_root.alignment = WD_ALIGN_PARAGRAPH.LEFT
p_root.add_run("π + x")
r_exp3 = p_root.add_run("²")
r_exp3.font.superscript = True
p_root.add_run(" - 1")
set_cell_margins(cell_root, left=0, right=0)
set_cell_top_border(cell_root)

# Row 2: Lower limit
cell_low = t_int.rows[2].cells[0]
p_low = cell_low.paragraphs[0]
p_low.alignment = WD_ALIGN_PARAGRAPH.RIGHT
p_low.add_run("-∞").font.size = Pt(8)

# Footnotes section at the bottom of Page 2 (before page number)
doc.add_paragraph("---")
p_fn1 = doc.add_paragraph("^1 Optisches Dichte-Experiment: Erstmalig systematisch beschrieben von Willebrord Snellius im Jahr 1621.")
p_fn1.runs[0].font.size = Pt(10)
p_fn2 = doc.add_paragraph("^2 Snelliussche Brechungsgesetz: ")
p_fn2.add_run("n")
p_fn2.add_run("1").font.subscript = True
p_fn2.add_run(" · sin(α) = n")
p_fn2.add_run("2").font.subscript = True
p_fn2.add_run(" · sin(β).")
p_fn2.runs[0].font.size = Pt(10)

# End of Page 2: Add page number
doc.add_paragraph()
p_p46 = doc.add_paragraph("[Seite 46]")
p_p46.alignment = WD_ALIGN_PARAGRAPH.RIGHT

# Add a page break for Page 3 in DOCX
doc.add_page_break()

# Page 3 Title
h_p3 = doc.add_heading("Übungen und Schüleraufgaben", level=2)

# Side-by-side images at TOP of Page 3 in DOCX (1 row, 3 cells table)
doc.add_paragraph("Betrachten Sie die drei folgenden Abbildungen zum Versuchsaufbau:")
table_imgs_top = doc.add_table(rows=1, cols=3)
table_imgs_top.autofit = True

cell1 = table_imgs_top.rows[0].cells[0]
p1 = cell1.paragraphs[0]
p1.add_run().add_picture(image_path_3a, width=Inches(1.8))
p1_cap = cell1.add_paragraph("Abbildung 4.2a: Prisma von vorne (Schematische Zeichnung)")
p1_cap.runs[0].font.italic = True
p1_cap.runs[0].font.size = Pt(8.5)

cell2 = table_imgs_top.rows[0].cells[1]
p2 = cell2.paragraphs[0]
p2.add_run().add_picture(image_path_3b, width=Inches(1.8))
p2_cap = cell2.add_paragraph("Abbildung 4.2b: Strahlengang im Prisma (Diagramm)")
p2_cap.runs[0].font.italic = True
p2_cap.runs[0].font.size = Pt(8.5)

cell3 = table_imgs_top.rows[0].cells[2]
p3 = cell3.paragraphs[0]
p3.add_run().add_picture(image_path_3c, width=Inches(1.8))
p3_cap = cell3.add_paragraph("Abbildung 4.2c: Reales Glasprisma im Laborversuch (Fotoaufnahme)")
p3_cap.runs[0].font.italic = True
p3_cap.runs[0].font.size = Pt(8.5)

# 2-column layout in DOCX (using a table with 1 row, 2 cells)
doc.add_paragraph("")
doc.add_paragraph("Vergleichen Sie die Ausbreitung von Licht in verschiedenen Medien:")
table_col2 = doc.add_table(rows=1, cols=2)
table_col2.rows[0].cells[0].paragraphs[0].text = "Spalte A: Ausbreitung in Luft\nLicht breitet sich in Luft nahezu ungehindert aus. Der Brechungsindex beträgt ca. 1.0003."
table_col2.rows[0].cells[1].paragraphs[0].text = "Spalte B: Ausbreitung in Glas\nIn dichteren Medien wie Glas verringert sich die Lichtgeschwindigkeit deutlich (n = 1.5)."

# Spanning container below them with tasks and difficulty circles
doc.add_paragraph("")
p_tasks_box = doc.add_paragraph("Aufgabenstellung für die Arbeitsgruppen:")
p_tasks_box.runs[0].font.bold = True
table_span = doc.add_table(rows=1, cols=1)
cell_span = table_span.rows[0].cells[0]
cell_span.paragraphs[0].text = "Arbeitsauftrag:\n" \
                               "○ Aufgabe 1 (leicht): Bestimmen Sie die Lichtgeschwindigkeit in Glas.\n" \
                               "◐ Aufgabe 2 (mittel): Berechnen Sie den Grenzwinkel der Totalreflexion für Glas.\n" \
                               "● Aufgabe 3 (schwer): Skizzieren Sie den Strahlengang für ein gleichschenkliges Prisma."

# Side-by-side images at BOTTOM of Page 3 in DOCX (1 row, 2 cells table)
doc.add_paragraph("")
doc.add_paragraph("Ergänzende Beobachtungen zu optischen Grenzflächeneffekten:")
table_imgs_bot = doc.add_table(rows=1, cols=2)
table_imgs_bot.autofit = True

cell_b1 = table_imgs_bot.rows[0].cells[0]
pb1 = cell_b1.paragraphs[0]
pb1.add_run().add_picture(image_path_3d, width=Inches(2.5))
pb1_cap = cell_b1.add_paragraph("Abbildung 4.3a: Reflexionsgesetz am Spiegel (Illustration)")
pb1_cap.runs[0].font.italic = True
pb1_cap.runs[0].font.size = Pt(8.5)

cell_b2 = table_imgs_bot.rows[0].cells[1]
pb2 = cell_b2.paragraphs[0]
pb2.add_run().add_picture(image_path_3e, width=Inches(2.5))
pb2_cap = cell_b2.add_paragraph("Abbildung 4.3b: Laserstrahl-Lichtbrechung im Wasser (Foto)")
pb2_cap.runs[0].font.italic = True
pb2_cap.runs[0].font.size = Pt(8.5)

# End of Page 3: Add page number in DOCX
doc.add_paragraph()
p_p47 = doc.add_paragraph("[Seite 47]")
p_p47.alignment = WD_ALIGN_PARAGRAPH.RIGHT

# Add a page break for Page 4 in DOCX
doc.add_page_break()

# Page 4 Title
h_p4 = doc.add_heading("Erweiterte physikalische Phänomene", level=2)

# 3-column layout in DOCX (using a table with 1 row, 3 cells)
doc.add_paragraph("Drei zentrale Eigenschaften optischer Systeme:")
table_col3 = doc.add_table(rows=1, cols=3)
table_col3.rows[0].cells[0].paragraphs[0].text = "1. Refraktion\nDie Brechung des Lichts an Grenzflächen."
table_col3.rows[0].cells[1].paragraphs[0].text = "2. Reflexion\nDas Zurückwerfen von Lichtstrahlen an Spiegeln."
table_col3.rows[0].cells[2].paragraphs[0].text = "3. Absorption\nDie Umwandlung von Lichtenergie in Wärme."

# Spanning container below 3-columns
doc.add_paragraph("")
table_span3 = doc.add_table(rows=1, cols=1)
cell_span3 = table_span3.rows[0].cells[0]
cell_span3.paragraphs[0].text = "Fortgeschrittener Arbeitsauftrag:\n" \
                                "◐ Aufgabe 4 (mittel): Erklären Sie den Unterschied zwischen Reflexion und Absorption.\n" \
                                "● Aufgabe 5 (schwer): Leiten Sie den Zusammenhang zwischen Absorption und Brechungsindex her."

# Left-aligned figure alongside right-hand explanatory text in DOCX
doc.add_paragraph("")
table_left_fig = doc.add_table(rows=1, cols=2)
table_left_fig.rows[0].cells[0].paragraphs[0].add_run().add_picture(image_path_4, width=Inches(2.0))
p_fig4_cap = table_left_fig.rows[0].cells[0].add_paragraph("Abbildung 4.4: Strahlengang bei Totalreflexion")
p_fig4_cap.runs[0].font.italic = True
p_fig4_cap.runs[0].font.size = Pt(8.5)
table_left_fig.rows[0].cells[1].paragraphs[0].text = "Die Totalreflexion tritt auf, wenn Licht von einem optisch dichteren in ein dünneres Medium übergeht und der Einfallswinkel den Grenzwinkel überschreitet."

# End of Page 4: Add page number in DOCX
doc.add_paragraph()
p_p48 = doc.add_paragraph("[Seite 48]")
p_p48.alignment = WD_ALIGN_PARAGRAPH.RIGHT

doc.save(docx_path)
print("DOCX generated successfully.")

# 3. Generate Mock educational PDF using ReportLab
pdf_path = os.path.join(test_data_dir, "test_educational.pdf")
print(f"Generating mock PDF: {pdf_path}...")

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak, Flowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

pdf = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=54, bottomMargin=54)
story = []
styles = getSampleStyleSheet()

# Register Unicode-capable fonts for ReportLab (supports ○, ◐, ●, ∫, ∞, √, π, α, β, λ on both macOS and Linux)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
PDF_FONT_ITALIC = "Helvetica-Oblique"

for reg_path, bold_path, ital_path in [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
]:
    if os.path.exists(reg_path):
        try:
            pdfmetrics.registerFont(TTFont("UniRegular", reg_path))
            PDF_FONT_REGULAR = "UniRegular"
            if os.path.exists(bold_path):
                pdfmetrics.registerFont(TTFont("UniBold", bold_path))
                PDF_FONT_BOLD = "UniBold"
            else:
                PDF_FONT_BOLD = "UniRegular"
            if os.path.exists(ital_path):
                pdfmetrics.registerFont(TTFont("UniItalic", ital_path))
                PDF_FONT_ITALIC = "UniItalic"
            else:
                PDF_FONT_ITALIC = "UniRegular"
            break
        except Exception:
            pass

# Custom styles
title_style = ParagraphStyle(
    "TitleStyle",
    parent=styles["Heading1"],
    fontName=PDF_FONT_BOLD,
    fontSize=22,
    leading=26,
    textColor=colors.HexColor("#1A365D"),
    spaceAfter=8
)
subtitle_style = ParagraphStyle(
    "SubtitleStyle",
    parent=styles["Heading2"],
    fontName=PDF_FONT_BOLD,
    fontSize=16,
    leading=20,
    textColor=colors.HexColor("#2C5282"),
    spaceAfter=8
)
h3_style = ParagraphStyle(
    "H3Style",
    parent=styles["Heading2"],
    fontName=PDF_FONT_BOLD,
    fontSize=13,
    leading=17,
    textColor=colors.HexColor("#1E293B"),
    spaceBefore=8,
    spaceAfter=6
)
body_style = ParagraphStyle(
    "BodyStyle",
    parent=styles["BodyText"],
    fontName=PDF_FONT_REGULAR,
    fontSize=10,
    leading=14,
    spaceAfter=10
)
italic_caption_style = ParagraphStyle(
    "ItalicCaptionStyle",
    parent=body_style,
    fontName=PDF_FONT_ITALIC,
    fontSize=9.5,
    leading=13
)
right_style = ParagraphStyle(
    "RightStyle",
    parent=styles["BodyText"],
    fontName=PDF_FONT_REGULAR,
    fontSize=10,
    leading=14,
    alignment=2,
    textColor=colors.HexColor("#4A5568")
)
def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(PDF_FONT_REGULAR, 10)
    canvas.setFillColor(colors.HexColor("#4A5568"))
    page_num = doc.page
    if page_num == 1:
        canvas.drawRightString(540, 36, "Seite 45")
    elif page_num == 2:
        canvas.drawRightString(540, 36, "Seite 46")
    elif page_num == 3:
        canvas.drawRightString(540, 36, "Seite 47")
    elif page_num == 4:
        canvas.drawRightString(540, 36, "Seite 48")
    canvas.restoreState()
list_style = ParagraphStyle(
    "ListStyle",
    parent=styles["BodyText"],
    fontName=PDF_FONT_REGULAR,
    fontSize=10,
    leading=14,
    leftIndent=20,
    firstLineIndent=-10,
    spaceAfter=5
)
box_style = ParagraphStyle(
    "BoxStyle",
    parent=styles["BodyText"],
    fontName=PDF_FONT_REGULAR,
    fontSize=10,
    leading=14,
    backColor=colors.HexColor("#EDF2F7"),
    borderColor=colors.HexColor("#CBD5E0"),
    borderWidth=1,
    borderPadding=8,
    spaceAfter=10
)

# Add Elements Page 1
story.append(Paragraph("Physik für die Sekundarstufe II", title_style))
story.append(Paragraph("Kapitel 4: Optik und Lichtbrechung", subtitle_style))
story.append(Spacer(1, 10))

story.append(Paragraph(
    "Das Phänomen der Lichtbrechung (Refraktion) ist die Richtungsänderung einer Welle durch eine "
    "Geschwindigkeitsänderung beim Übergang in ein anderes Medium. Ein bekanntes optisches Element zur "
    "Untersuchung dieses Effekts ist das Prisma, welches weißes Licht in seine Spektralfarben zerlegen kann.",
    body_style
))

story.append(Paragraph("Wichtige Grundregeln", h3_style))
story.append(Paragraph("- &nbsp; Licht breitet sich im Vakuum mit c = 299.792 km/s aus.", list_style))
story.append(Paragraph("- &nbsp; Beim Übergang in ein dichteres Medium verringert sich die Lichtgeschwindigkeit.", list_style))
story.append(Paragraph("- &nbsp; Der Brechungsindex n beschreibt das Verhältnis der Lichtgeschwindigkeit im Vakuum zu der im Medium.", list_style))
story.append(Spacer(1, 10))

story.append(Paragraph("Versuch: Zerlegung durch ein Prisma", h3_style))
story.append(Paragraph("Betrachten wir das nachfolgende Experiment zur Dispersion:", body_style))

# Add image
rlimg = RLImage(image_path, width=300, height=200)
story.append(rlimg)
story.append(Spacer(1, 5))
story.append(Paragraph("Abbildung 4.1: Versuchsaufbau zur optischen Dispersion mit einem Glasprisma.", italic_caption_style))
story.append(Spacer(1, 10))

# Definition box (Rahmen) with heading above box per FIBS § 8.5
story.append(Paragraph("Merksatz:", h3_style))
story.append(Paragraph(
    "Die Abhängigkeit des Brechungsindex n von der Frequenz (bzw. Wellenlänge) "
    "des Lichts bezeichnet man als Dispersion. Rotes Licht wird weniger stark "
    "gebrochen als blaues Licht, weshalb ein breites Farbspektrum entsteht.",
    box_style
))

# End of Page 1: Add PageBreak
story.append(PageBreak())

# Table
story.append(Paragraph("Physikalische Grössen und Konstanten", h3_style))
data = [
    [Paragraph(f'<font name="{PDF_FONT_BOLD}">Symbol</font>', body_style), Paragraph(f'<font name="{PDF_FONT_BOLD}">Bedeutung</font>', body_style), Paragraph(f'<font name="{PDF_FONT_BOLD}">Typischer Wert / Einheit</font>', body_style)],
    [Paragraph("c", body_style), Paragraph("Lichtgeschwindigkeit im Vakuum", body_style), Paragraph("2.9979 x 10<sup>8</sup> m/s", body_style)],
    [Paragraph("n<sub>Glas</sub>", body_style), Paragraph("Brechungsindex von Kronglas", body_style), Paragraph("1.51 - 1.54", body_style)],
    [Paragraph("λ", body_style), Paragraph("Wellenlänge des sichtbaren Lichts", body_style), Paragraph("380 - 780 nm", body_style)]
]
t = Table(data, colWidths=[60, 200, 140])
t.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E2E8F0")),
    ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
    ('TOPPADDING', (0,0), (-1,-1), 5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 5),
]))
story.append(t)
story.append(Spacer(1, 15))

# Footnote reference paragraph
story.append(Paragraph(
    "Im optischen Dichte-Experiment<sup>1</sup> wurde nachgewiesen, dass Licht beim Übergang von Luft in Wasser "
    "gebrochen wird. Dieser Effekt lässt sich mathematisch durch das Snelliussche Brechungsgesetz beschreiben<sup>2</sup>.",
    body_style
))
story.append(Spacer(1, 10))

h4_style = ParagraphStyle(
    "H4Style",
    parent=styles["Heading3"],
    fontName=PDF_FONT_BOLD,
    fontSize=11.5,
    leading=15,
    textColor=colors.HexColor("#1E293B"),
    spaceBefore=6,
    spaceAfter=6
)
story.append(Paragraph("Mathematische Formeln im Fließtext:", h4_style))
story.append(Paragraph("Hier ist eine inline Formel: n<sub>1</sub> · sin(α) = n<sub>2</sub> · sin(β)", body_style))
story.append(Paragraph("Hier ist ein MathML-Render-Beispiel für dieselbe Formel:", body_style))
story.append(Paragraph("n<sub>1</sub> · sin(α) = n<sub>2</sub> · sin(β)", body_style))
story.append(Paragraph("Hier ist eine komplexe Blockgleichung:", body_style))

# Render integral equation with both Unicode text stream (∫, -∞, ∞, √, π) and visual overbar
from reportlab.graphics.shapes import Drawing, Line, String as RLString

d_eq = Drawing(300, 40)
d_eq.add(RLString(16, 28, "∞", fontName=PDF_FONT_REGULAR, fontSize=8, textAnchor="middle"))
d_eq.add(RLString(16, 8, "∫", fontName=PDF_FONT_REGULAR, fontSize=22, textAnchor="middle"))
d_eq.add(RLString(16, 0, "-∞", fontName=PDF_FONT_REGULAR, fontSize=8, textAnchor="middle"))
d_eq.add(RLString(32, 11, "e", fontName=PDF_FONT_REGULAR, fontSize=12))
d_eq.add(RLString(39, 16, "-x", fontName=PDF_FONT_REGULAR, fontSize=8))
d_eq.add(RLString(47, 21, "2", fontName="UniRegular" if PDF_FONT_REGULAR == "UniRegular" else PDF_FONT_REGULAR, fontSize=6))
d_eq.add(RLString(56, 11, " dx = √(π + x", fontName=PDF_FONT_REGULAR, fontSize=12))
d_eq.add(RLString(138, 17, "2", fontName=PDF_FONT_REGULAR, fontSize=8))
d_eq.add(RLString(144, 11, " - 1)", fontName=PDF_FONT_REGULAR, fontSize=12))
d_eq.add(Line(98, 25, 175, 25, strokeColor=colors.HexColor("#4A5568"), strokeWidth=1))

story.append(d_eq)
story.append(Spacer(1, 180))

# Footnotes section at the bottom of Page 2 (foot of Seite 46)
story.append(Table([[Paragraph("", body_style)]], colWidths=[200], style=[('LINEBELOW', (0,0), (-1,-1), 0.5, colors.gray)]))
story.append(Spacer(1, 6))

footnote_style = ParagraphStyle("FootnoteStyle", parent=body_style, fontName=PDF_FONT_REGULAR, fontSize=9.5, leading=13, textColor=colors.HexColor("#4A5568"))
story.append(Paragraph("<sup>1</sup> Optisches Dichte-Experiment: Erstmalig systematisch beschrieben von Willebrord Snellius im Jahr 1621.", footnote_style))
story.append(Paragraph("<sup>2</sup> Snelliussche Brechungsgesetz: n<sub>1</sub> · sin(α) = n<sub>2</sub> · sin(β).", footnote_style))
story.append(Spacer(1, 10))

# Page 3 PDF (Seite 47)
story.append(PageBreak())
story.append(Paragraph("Übungen und Schüleraufgaben", subtitle_style))

# 3 Side-by-side images at TOP of Page 3 in PDF
story.append(Paragraph("Betrachten Sie die drei folgenden Abbildungen zum Versuchsaufbau:", body_style))
rlimg3a = RLImage(image_path_3a, width=135, height=90)
rlimg3b = RLImage(image_path_3b, width=135, height=90)
rlimg3c = RLImage(image_path_3c, width=135, height=90)
t_side_imgs = Table([[rlimg3a, rlimg3b, rlimg3c]], colWidths=[140, 140, 140])
t_side_imgs.setStyle(TableStyle([
    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(t_side_imgs)
story.append(Spacer(1, 3))
t_side_caps = Table([[
    Paragraph("Abbildung 4.2a: Prisma von vorne (Schematische Zeichnung).", italic_caption_style),
    Paragraph("Abbildung 4.2b: Strahlengang im Prisma (Diagramm).", italic_caption_style),
    Paragraph("Abbildung 4.2c: Reales Glasprisma im Labor (Fotoaufnahme).", italic_caption_style)
]], colWidths=[140, 140, 140])
story.append(t_side_caps)
story.append(Spacer(1, 6))

# Introductory sentence + 2-column comparison table with visible grid so TableFormer & VLMs recognize it as a table
story.append(Paragraph("Vergleichen Sie die Ausbreitung von Licht in verschiedenen Medien:", body_style))
col2_data = [
    [
        Paragraph(f'<font name="{PDF_FONT_BOLD}">Spalte A: Ausbreitung in Luft</font>', body_style),
        Paragraph(f'<font name="{PDF_FONT_BOLD}">Spalte B: Ausbreitung in Glas</font>', body_style)
    ],
    [
        Paragraph("Licht breitet sich in Luft nahezu ungehindert aus. Der Brechungsindex beträgt ca. 1.0003.", body_style),
        Paragraph("In dichteren Medien wie Glas verringert sich die Lichtgeschwindigkeit deutlich (n = 1.5).", body_style)
    ]
]
t_col2 = Table(col2_data, colWidths=[210, 210])
t_col2.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#E2E8F0")),
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
    ('TOPPADDING', (0,0), (-1,-1), 5),
    ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ('LEFTPADDING', (0,0), (-1,-1), 6),
]))
story.append(t_col2)
story.append(Spacer(1, 6))

# Introductory sentence + Spanning container box with Unicode ○, ◐, ● difficulty symbols
story.append(Paragraph(f'<font name="{PDF_FONT_BOLD}">Aufgabenstellung für die Arbeitsgruppen:</font>', body_style))
task_content = f'<font name="{PDF_FONT_BOLD}">Arbeitsauftrag:</font><br/>' \
               "○ Aufgabe 1 (leicht): Bestimmen Sie die Lichtgeschwindigkeit in Glas.<br/>" \
               "◐ Aufgabe 2 (mittel): Berechnen Sie den Grenzwinkel der Totalreflexion für Glas.<br/>" \
               "● Aufgabe 3 (schwer): Skizzieren Sie den Strahlengang für ein gleichschenkliges Prisma."
story.append(Paragraph(task_content, box_style))
story.append(Spacer(1, 6))

# 2 Side-by-side images at BOTTOM of Page 3 in PDF
story.append(Paragraph("Ergänzende Beobachtungen zu optischen Grenzflächeneffekten:", body_style))
rlimg3d = RLImage(image_path_3d, width=180, height=95)
rlimg3e = RLImage(image_path_3e, width=180, height=95)
t_bot_imgs = Table([[rlimg3d, rlimg3e]], colWidths=[210, 210])
t_bot_imgs.setStyle(TableStyle([
    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
]))
story.append(t_bot_imgs)
story.append(Spacer(1, 3))
t_bot_caps = Table([[
    Paragraph("Abbildung 4.3a: Reflexionsgesetz am Spiegel (Illustration).", italic_caption_style),
    Paragraph("Abbildung 4.3b: Laserstrahl-Lichtbrechung im Wasser (Foto).", italic_caption_style)
]], colWidths=[210, 210])
story.append(t_bot_caps)

# Page 4 PDF (Seite 48)
story.append(PageBreak())
story.append(Paragraph("Erweiterte physikalische Phänomene", subtitle_style))

# Introductory sentence + 3-column numbered items
story.append(Paragraph("Drei zentrale Eigenschaften optischer Systeme:", body_style))
col3_data = [
    [
        Paragraph(f'<font name="{PDF_FONT_BOLD}">1. Refraktion</font><br/>Die Brechung des Lichts an Grenzflächen.', body_style),
        Paragraph(f'<font name="{PDF_FONT_BOLD}">2. Reflexion</font><br/>Das Zurückwerfen von Lichtstrahlen an Spiegeln.', body_style),
        Paragraph(f'<font name="{PDF_FONT_BOLD}">3. Absorption</font><br/>Die Umwandlung von Lichtenergie in Wärme.', body_style)
    ]
]
t_col3 = Table(col3_data, colWidths=[133, 133, 134])
t_col3.setStyle(TableStyle([
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ('LEFTPADDING', (0,0), (-1,-1), 5),
]))
story.append(t_col3)
story.append(Spacer(1, 10))

# Left-aligned figure alongside right-hand explanatory text
rlimg4_left = RLImage(image_path_4, width=140, height=90)
left_fig_cell = [
    rlimg4_left,
    Paragraph("Abbildung 4.4: Strahlengang bei Totalreflexion.", italic_caption_style)
]
right_text_cell = Paragraph(
    "Die Totalreflexion tritt auf, wenn Licht von einem optisch dichteren in ein dünneres Medium übergeht und der Einfallswinkel den Grenzwinkel überschreitet.",
    body_style
)
t_left_fig = Table([[left_fig_cell, right_text_cell]], colWidths=[160, 240])
t_left_fig.setStyle(TableStyle([
    ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ('RIGHTPADDING', (0,0), (0,0), 10),
    ('LEFTPADDING', (1,0), (1,0), 10),
]))
story.append(t_left_fig)
story.append(Spacer(1, 10))

# Spanning container box page 4
task_content4 = f'<font name="{PDF_FONT_BOLD}">Fortgeschrittener Arbeitsauftrag:</font><br/>' \
                "◐ Aufgabe 4 (mittel): Erklären Sie den Unterschied zwischen Reflexion und Absorption.<br/>" \
                "● Aufgabe 5 (schwer): Leiten Sie den Zusammenhang zwischen Absorption und Brechungsindex her."
story.append(Paragraph(task_content4, box_style))

pdf.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
print("PDF generated successfully.")
