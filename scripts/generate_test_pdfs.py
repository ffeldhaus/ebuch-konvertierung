from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    BaseDocTemplate, SimpleDocTemplate, PageTemplate, Frame, Paragraph, Spacer, 
    Table, TableStyle, PageBreak, FrameBreak, NextPageTemplate
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import os

def draw_page_number_alternating(canvas, doc):
    page_num = doc.page + 84 # starts at 85
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#4A5568"))
    
    # Draw header
    canvas.drawString(54, 750, "FAUST I - TEXTANALYSE")
    canvas.drawRightString(612 - 54, 750, "DEUTSCHUNTERRICHT")
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.5)
    canvas.line(54, 742, 612 - 54, 742)
    
    # Draw footer with alternating page numbers
    canvas.setFont("Helvetica", 9)
    if page_num % 2 == 1:
        # Odd page: bottom left
        canvas.drawString(54, 36, f"{page_num}   Deutsch Textanalyse")
    else:
        # Even page: bottom right
        canvas.drawRightString(612 - 54, 36, f"Deutsch Textanalyse   {page_num}")
    
    canvas.line(54, 48, 612 - 54, 48)
    canvas.restoreState()

def draw_page_number_centered(canvas, doc):
    page_num = doc.page # starts at 1
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#4A5568"))
    
    # Draw header
    canvas.drawString(54, 750, "MATHEMATIK")
    canvas.drawRightString(612 - 54, 750, "KLASSE 3")
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.5)
    canvas.line(54, 742, 612 - 54, 742)
    
    # Draw footer with centered page numbers
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(612 / 2.0, 36, f"{page_num}")
    
    canvas.line(54, 48, 612 - 54, 48)
    canvas.restoreState()

UNICODE_FONT = "Helvetica-Bold"
for font_path, font_name in [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuBold"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuRegular"),
    ("/Library/Fonts/Arial Unicode.ttf", "ArialUnicode"),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "ArialUnicode"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "ArialCustom"),
    ("/System/Library/Fonts/Geneva.ttf", "GenevaCustom")
]:
    if os.path.exists(font_path):
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont(font_name, font_path))
            UNICODE_FONT = font_name
            break
        except Exception:
            pass

def make_callout_box(title_text, desc_text, content_flowable, bg_color="#F0F9FF", border_color="#0284C7", icon_char="4"):
    styles = getSampleStyleSheet()
    box_title_style = ParagraphStyle(
        "BoxTitle",
        parent=styles["Normal"],
        fontName=UNICODE_FONT,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0F172A")
    )
    box_desc_style = ParagraphStyle(
        "BoxDesc",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475569")
    )
    
    header_data = [
        [
            [
                Paragraph(title_text, box_title_style),
                Paragraph(desc_text, box_desc_style)
            ]
        ]
    ]
    header_table = Table(header_data, colWidths=[480])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    
    box_content = [header_table, Spacer(1, 6)]
    if isinstance(content_flowable, list):
        box_content.extend(content_flowable)
    else:
        box_content.append(content_flowable)
        
    container = Table([[box_content]], colWidths=[496])
    container.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(bg_color)),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor(border_color)),
        ('LINELEFT', (0,0), (0,-1), 4, colors.HexColor(border_color)),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    return container

def create_deutsch_textanalyse():
    pdf_path = "testdata/deutsch_textanalyse.pdf"
    doc = BaseDocTemplate(
        pdf_path,
        pagesize=letter
    )
    
    # Template 1: Single Column (Page 3)
    frame_one = Frame(54, 54, 504, 684, id='one_col', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template_one = PageTemplate(id='OneCol', frames=[frame_one], onPage=draw_page_number_alternating)
    
    # Template 2: Header + 2 Columns (Page 2)
    p2_head = Frame(54, 590, 504, 148, id='p2_head', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p2_col1 = Frame(54, 54, 240, 526, id='p2_col1', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p2_col2 = Frame(54 + 240 + 24, 54, 240, 526, id='p2_col2', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template_two = PageTemplate(id='TwoCol', frames=[p2_head, p2_col1, p2_col2], onPage=draw_page_number_alternating)
    
    # Template 3: Header + 3 Columns (Page 1)
    p1_head = Frame(54, 580, 504, 158, id='p1_head', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p1_col1 = Frame(54, 54, 152, 516, id='p1_col1', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p1_col2 = Frame(54 + 152 + 24, 54, 152, 516, id='p1_col2', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    p1_col3 = Frame(54 + 2 * (152 + 24), 54, 152, 516, id='p1_col3', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template_three = PageTemplate(id='ThreeCol', frames=[p1_head, p1_col1, p1_col2, p1_col3], onPage=draw_page_number_alternating)
    
    doc.addPageTemplates([template_three, template_two, template_one])
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=6
    )
    heading2_style = ParagraphStyle(
        "Heading2Style",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4
    )
    heading3_style = ParagraphStyle(
        "Heading3Style",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=6,
        spaceAfter=4
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
        alignment=4 # Justified
    )

    story = []
    
    # =========================================================================
    # --- PAGE 1: HEADER + 3 BALANCED COLUMNS (Page 85) ---
    # =========================================================================
    # 1. Header Frame (Full Width across top)
    story.append(Paragraph("Literarische Textanalyse: Johann Wolfgang von Goethe - Faust I", title_style))
    story.append(Paragraph("Epochenkontext und Szenenanalyse: Studierzimmer I", heading2_style))
    story.append(Paragraph(
        "Goethes Tragödie Faust I steht an der Epochenschwelle zwischen Sturm und Drang und der Weimarer Klassik. Fausts Eingangsmonolog im „Studierzimmer I“ verdeutlicht den Übergang von einem rationalistischen Weltbild der Aufklärung hin zu einem irrationalen, emotional geladenen Erkenntnisstreben. Der Monolog spiegelt eine tiefe existenzielle Krise wider, die durch das akademische Wissen allein nicht gelöst werden kann.",
        body_style
    ))
    story.append(FrameBreak())
    
    # 2. Column 1 (Section I starts here and hyphenates across into Column 2)
    story.append(Paragraph("<b>I. Die Epoche und ihr Einfluss</b>", heading3_style))
    story.append(Paragraph(
        "Goethes Faust I stellt einen Höhepunkt der deutschen Literatur dar. Die Entstehungsgeschichte erstreckt sich über mehrere Jahrzehnte und verbindet Elemente des Sturm und Drang mit der Weimarer Klass-",
        body_style
    ))
    story.append(FrameBreak())
    
    # 3. Column 2 (Continuation of Section I from Column 1, then Section II starting and hyphenating into Column 3)
    story.append(Paragraph(
        "ik. In dieser Epoche steht die Harmonie von Gefühl und Verstand im Vordergrund. Die klassischen Ideale von Humanität, Schönheit und Ausgewogenheit prägten Goethes spätere Arbeiten maßgeblich. Faust spiegelt diesen inneren Reifungsprozess wider, indem er sich von den emotionalen Ausbrüchen des Sturm und Drang zu einer reflektierten Auseinandersetzung mit den Grenzen der menschlichen Existenz entwickelt.",
        body_style
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>II. Die Tragik des Gelehrten</b>", heading3_style))
    story.append(Paragraph(
        "Faust repräsentiert den neuzeitlichen Gelehrten, der die vier traditionellen Fakultäten – Philosophie, Juristerei, Medizin und Theologie – mit heißem Bemühn durchdrungen hat. Trotz seines immensen Wissens erkennt er schmerzhaft die fundamentale Begrenztheit rein rationaler Erkennt-",
        body_style
    ))
    story.append(FrameBreak())
    
    # 4. Column 3 (Continuation of Section II from Column 2, then Section III hyphenating across page boundary into Page 86)
    story.append(Paragraph(
        "nis. Seine existenzielle Verzweiflung entspringt der Erkenntnis, dass der Verstand allein die tiefsten Geheimnisse der Schöpfung nicht erfassen kann („dass ich erkenne, was die Welt im Innersten zusammenhält“). Das akademische Studium hinterlässt ihn geistig verarmt und führt in eine tiefe existenzielle Krise.",
        body_style
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>III. Die Flucht in die Magie</b>", heading3_style))
    story.append(Paragraph(
        "Um den Fesseln des abstrakten Wissens zu entkommen, wendet sich Faust der Magie und Naturmystik zu. Durch das Zeichen des Makrokosmos versucht er, die universellen Kräfte zu erfassen, empfindet das Erblickte jedoch nur als passives Schauspiel. Erst die Beschwörung des Erdgeistes konfrontiert ihn mit der lebendigen schöpferischen Wirklichkeit. Doch als der Erdgeist ihn zurückweist, treibt ihn dies an den Rand der totalen Selbstauf-",
        body_style
    ))
    
    # Switch template to TwoCol for Page 2
    story.append(NextPageTemplate('TwoCol'))
    story.append(PageBreak())
    
    # =========================================================================
    # --- PAGE 2: HEADER + 2 BALANCED COLUMNS (Page 86) ---
    # =========================================================================
    # 1. Header Frame (Completes hyphenation from Page 85, then introduces Page 86 header)
    story.append(Paragraph(
        "gabe. Dieser existentielle Tiefpunkt markiert den Wendepunkt des gesamten Dramas.",
        body_style
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Figurenkonstellation und dualistisches Erkenntnisstreben", title_style))
    story.append(Paragraph("Die Kontrastfiguren: Faust und Wagner", heading2_style))
    story.append(Paragraph(
        "Der fundamentale Kontrast zwischen Fausts existentialistischem Drang und dem philisterhaften Akademismus seiner Epoche wird durch seinen Famulus Wagner verkörpert. Während Faust sich nach der Unmittelbarkeit des Lebens und dem Einswerden mit der Natur sehnt, begnügt sich Wagner mit dem Sammeln, Archivieren und Kommentieren historischer Schriften.",
        body_style
    ))
    story.append(FrameBreak())
    
    # 2. Column 1 (Section IV starts here and hyphenates across into Column 2)
    story.append(Paragraph("<b>IV. Faust und Wagner: Ein philosophischer Dualismus</b>", heading3_style))
    story.append(Paragraph(
        "Der Kontrast zwischen Faust und seinem Famulus Wagner verdeutlicht zwei grundlegend unvereinbare Lebens- und Wissenskonzepte. Während Faust nach lebendiger Erfahrung und ganzheitlicher Erkenntnis strebt, begnügt sich Wagner mit der akribischen Anhäufung von philisterhaftem Bücherwissen und dogmatischer Gelehrsamkeit.",
        body_style
    ))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "Während Faust die Natur als lebendigen Organismus erfahren will, sieht Wagner die Wissenschaft als rein mechanisches Handwerk. Wagner ist erfüllt von der Rekonstruktion alter Pergamente und spürt keinerlei Drang, über die gedruckten Zeilen hinauszugehen. Diese geistige Zerrissenheit prägt die Charak-",
        body_style
    ))
    story.append(FrameBreak())
    
    # 3. Column 2 (Continuation of Section IV from Column 1, then Section V)
    story.append(Paragraph(
        "tere und bildet die psychologische Triebkraft für Fausts späteren Pakt mit Mephistopheles. Wagner verbleibt in seiner sterilen Gelehrtenwelt, während Faust den Schritt in das radikal Unbekannte wagt.",
        body_style
    ))
    story.append(Spacer(1, 5))
    story.append(Paragraph("<b>V. Die Szene „Vor dem Tor“ und der Osterspaziergang</b>", heading3_style))
    story.append(Paragraph(
        "In der Szene „Vor dem Tor“ tritt Faust aus der Enge des gotischen Studierzimmers hinaus in die erwachende Frühlingsnatur und unter das feiernde Volk. Der Osterspaziergang symbolisiert Fausts Sehnsucht nach Befreiung, irdischer Lebensfreude und sozialer Integration („Hier bin ich Mensch, hier darf ich's sein!“).",
        body_style
    ))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "Inmitten der Menschenmenge spürt er für kurze Zeit die aufkeimende Lebenskraft der Natur, wird jedoch sofort wieder von seinem tiefen seelischen Zwiespalt eingeholt: „Zwei Seelen wohnen, ach! in meiner Brust“. Dieser unauflösbare Konflikt leitet den Übergang zur Teufelsbegegnung ein und bereitet den Auftritt des Pudels vor.",
        body_style
    ))
    
    # Switch template to OneCol for Page 3
    story.append(NextPageTemplate('OneCol'))
    story.append(PageBreak())
    
    # =========================================================================
    # --- PAGE 3: 1 COLUMN (Page 87) ---
    # =========================================================================
    story.append(Paragraph("Metrische Formanalyse des Monologs", title_style))
    story.append(Paragraph("Die Bedeutung des Knittelverses in Faust I", heading2_style))
    story.append(Paragraph(
        "Der Knittelvers ist das prägende Metrum des Faust-Dramas. Er geht auf das 15. und 16. Jahrhundert zurück (berühmt durch Hans Sachs) und wurde von Goethe wiederbelebt, um einen volkstümlichen, aber hochdramatischen Ton zu treffen. Seine Besonderheit liegt in der lockeren Struktur, die es erlaubt, gesprochene Sprache und philosophische Tiefe organisch miteinander zu verschmelzen.",
        body_style
    ))
    story.append(Spacer(1, 8))
    
    # Box for Knittelvers metrics
    form_details = [
        Paragraph("• <b>Hebungen:</b> Der Vers besitzt stets vier Hebungen.", body_style),
        Paragraph("• <b>Senkungen:</b> Die Anzahl der Senkungen ist frei (Füllungsfreiheit), was den Rhythmus flexibel macht.", body_style),
        Paragraph("• <b>Reimbindung:</b> Konsequenter Paarreim (aabb...) binden den Text dramatisch zusammen.", body_style),
        Paragraph("• <b>Dramaturgischer Effekt:</b> Untermalung von Fausts getriebenem, ruhelosem Geist.", body_style)
    ]
    form_box = make_callout_box(
        "Strukturelle Eigenschaften des Knittelverses",
        "Form und metrische Freiheit im Knittelvers",
        form_details,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(form_box)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("<b>Vers-für-Vers Metrische Analyse (Beispiel)</b>", heading3_style))
    story.append(Paragraph(
        "1. <i>„Habe nun, ach! Philosophie“</i>: Vier Hebungen, weibliche Kadenz (Philosophie).<br/>"
        "2. <i>„Juristerei und Medizin“</i>: Vier Hebungen, männliche Kadenz (Medizin).<br/>"
        "3. <i>„Und leider auch Theologie“</i>: Weibliche Endung, Zäsur nach ‚leider‘.<br/>"
        "4. <i>„Durchaus studiert, mit heißem Bemühn“</i>: Männliche Kadenz, starker Akzent auf ‚Bemühn‘.",
        body_style
    ))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("<b>Leitfragen zur Erarbeitung und Nachbereitung</b>", heading3_style))
    story.append(Paragraph(
        "1. Analysieren Sie Fausts Eingangsmonolog im Hinblick auf den Wandel seines Naturbegriffs im Vergleich zur zeitgenössischen Aufklärung.<br/>"
        "2. Diskutieren Sie das Verhältnis zwischen Faust und Wagner. Inwiefern spiegeln sie zwei komplementäre Konzepte wissenschaftlichen Arbeitens?<br/>"
        "3. Welche dramaturgische Funktion besitzt die Zurückweisung Fausts durch den Erdgeist?",
        body_style
    ))
    
    doc.build(story)
    print(f"Created {pdf_path}")

def create_mathe_grade3():
    pdf_path = "testdata/mathe_grade3.pdf"
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=68,
        bottomMargin=68
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=10
    )
    heading2_style = ParagraphStyle(
        "Heading2Style",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16,
        textColor=colors.HexColor("#334155"),
        spaceBefore=6,
        spaceAfter=8
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569")
    )
    math_cell_style = ParagraphStyle(
        "MathCell",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#0F172A")
    )

    story = []
    
    # --- PAGE 1 ---
    story.append(Paragraph("Mathematische Übungen - 3. Klasse", title_style))
    story.append(Paragraph("Kapitel 1: Addition, Subtraktion und das Einmaleins im Zahlenraum 1000", heading2_style))
    story.append(Spacer(1, 10))
    
    # Box 1: Kopfrechnen (Pencil Box, Blue)
    math_data1 = [
        [Paragraph("a)  24 + 37 = ____", math_cell_style), Paragraph("f)  85 - 29 = ____", math_cell_style)],
        [Paragraph("b)  45 + 18 = ____", math_cell_style), Paragraph("g)  92 - 47 = ____", math_cell_style)],
        [Paragraph("c)  89 + 11 = ____", math_cell_style), Paragraph("h)  73 - 38 = ____", math_cell_style)],
        [Paragraph("d)  56 + 28 = ____", math_cell_style), Paragraph("i)  61 - 25 = ____", math_cell_style)],
        [Paragraph("e)  67 + 19 = ____", math_cell_style), Paragraph("j)  54 - 16 = ____", math_cell_style)]
    ]
    t_math1 = Table(math_data1, colWidths=[236, 236])
    t_math1.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box1 = make_callout_box(
        "Aufgabe 1 □: Kopfrechnen im Hunderterraum",
        "Berechne die folgenden Summen und Differenzen so schnell wie möglich:",
        t_math1,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box1)
    story.append(Spacer(1, 10))
    
    # Box 2: Schriftliches Rechnen (Pencil Box, Blue)
    math_data2 = [
        [Paragraph("a)  342 + 257 = ____", math_cell_style), Paragraph("d)  876 - 432 = ____", math_cell_style)],
        [Paragraph("b)  518 + 199 = ____", math_cell_style), Paragraph("e)  953 - 284 = ____", math_cell_style)],
        [Paragraph("c)  409 + 386 = ____", math_cell_style), Paragraph("f)  612 - 347 = ____", math_cell_style)]
    ]
    t_math2 = Table(math_data2, colWidths=[236, 236])
    t_math2.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box2 = make_callout_box(
        "Aufgabe 2 □: Schriftliches Rechnen bis 1000",
        "Schreibe die Zahlen stellengerecht untereinander und addiere bzw. subtrahiere:",
        t_math2,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box2)
    story.append(Spacer(1, 10))
    
    # Box 3: Einmaleins (Pencil Box, Blue)
    math_data3 = [
        [Paragraph("a)  6 * 7 = ____", math_cell_style), Paragraph("e)  4 * 9 = ____", math_cell_style)],
        [Paragraph("b)  8 * 9 = ____", math_cell_style), Paragraph("f)  7 * 8 = ____", math_cell_style)],
        [Paragraph("c)  5 * 12 = ____", math_cell_style), Paragraph("g)  3 * 15 = ____", math_cell_style)],
        [Paragraph("d)  9 * 7 = ____", math_cell_style), Paragraph("h)  8 * 6 = ____", math_cell_style)]
    ]
    t_math3 = Table(math_data3, colWidths=[236, 236])
    t_math3.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box3 = make_callout_box(
        "Aufgabe 3 ◩: Multiplikation und das kleine Einmaleins",
        "Löse die Multiplikationsaufgaben:",
        t_math3,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box3)
    story.append(Spacer(1, 10))
    
    # Box 4: Sachaufgabe (Star Box, Yellow)
    p_task1 = Paragraph(
        "In der Klasse 3a sind 24 Kinder. Für ein Bastelprojekt bringt jedes Kind 4 Kastanien mit. Wie viele Kastanien haben die Kinder insgesamt gesammelt? Schreibe die Rechnung und die Antwort auf.<br/>"
        "Rechnung: ________________________ Antwort: ________________________",
        body_style
    )
    box4 = make_callout_box(
        "Aufgabe 4 ◩: Erste Textaufgabe",
        "Rechnen und Lösen im Sachzusammenhang",
        p_task1,
        bg_color="#FEF3C7",
        border_color="#D97706",
        icon_char="t"
    )
    story.append(box4)
    
    # --- PAGE Break to Page 2 (2) ---
    story.append(PageBreak())
    
    # --- PAGE 2 ---
    story.append(Paragraph("Kapitel 2: Division und Bruchteile", title_style))
    story.append(Paragraph("Übungen zur Division mit/ohne Rest und grafische Bruchteile", body_style))
    story.append(Spacer(1, 10))
    
    # Box 5: Division (Pencil Box, Blue)
    math_data4 = [
        [Paragraph("a)  42 : 6 = ____", math_cell_style), Paragraph("e)  72 : 8 = ____", math_cell_style)],
        [Paragraph("b)  56 : 7 = ____", math_cell_style), Paragraph("f)  81 : 9 = ____", math_cell_style)],
        [Paragraph("c)  45 : 9 = ____", math_cell_style), Paragraph("g)  60 : 5 = ____", math_cell_style)],
        [Paragraph("d)  64 : 8 = ____", math_cell_style), Paragraph("h)  36 : 4 = ____", math_cell_style)]
    ]
    t_math4 = Table(math_data4, colWidths=[236, 236])
    t_math4.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box5 = make_callout_box(
        "Aufgabe 5 ◩: Divisionen im Zahlenraum 100",
        "Rechne die Divisionsaufgaben aus:",
        t_math4,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box5)
    story.append(Spacer(1, 10))
    
    # Box 6: Division mit Rest (Pencil Box, Blue)
    math_data5 = [
        [Paragraph("a)  47 : 6 = ____ Rest ____", math_cell_style), Paragraph("d)  52 : 7 = ____ Rest ____", math_cell_style)],
        [Paragraph("b)  29 : 5 = ____ Rest ____", math_cell_style), Paragraph("e)  38 : 9 = ____ Rest ____", math_cell_style)],
        [Paragraph("c)  17 : 3 = ____ Rest ____", math_cell_style), Paragraph("f)  67 : 8 = ____ Rest ____", math_cell_style)]
    ]
    t_math5 = Table(math_data5, colWidths=[236, 236])
    t_math5.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box6 = make_callout_box(
        "Aufgabe 6 ■: Division mit Rest",
        "Achtung: Hier bleibt manchmal ein Rest übrig! Rechne genau:",
        t_math5,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box6)
    story.append(Spacer(1, 10))
    
    # Box 7: Bruchteile (Star Box, Yellow)
    p_fractions = [
        Paragraph("a) Ein runder Kuchen wird in 8 gleich große Stücke geschnitten. 3 Stücke werden gegessen. Welcher Bruchteil des Kuchens ist noch übrig? Antwort: ________", body_style),
        Paragraph("b) Eine Schokolade hat 12 Rippen. Leo isst ein Viertel (1/4) der Schokolade. Wie viele Rippen isst er? Antwort: ________ Rippen", body_style),
        Paragraph("c) Welcher Bruchteil entspricht zwei Dritteln eines Rechtecks? Schreibe als Bruch auf: ________", body_style)
    ]
    box7 = make_callout_box(
        "Aufgabe 7 ■: Einführung in Bruchteile",
        "Grafische Konzepte und mathematische Bruchteile",
        p_fractions,
        bg_color="#FEF3C7",
        border_color="#D97706",
        icon_char="t"
    )
    story.append(box7)
    story.append(Spacer(1, 10))
    
    # Box 8: Sachaufgabe Division (Star Box, Yellow)
    p_task2 = Paragraph(
        "Ein Bauer möchte 96 Eier gleichmäßig in Eierschachteln verpacken. In jede Schachtel passen genau 6 Eier. Wie viele Schachteln kann der Bauer voll machen? Schreibe die Rechnung und Antwort auf.<br/>"
        "Rechnung: ________________________ Antwort: ________________________",
        body_style
    )
    box8 = make_callout_box(
        "Aufgabe 8 ■: Sachaufgabe Verteilen",
        "Rechnen und Teilen im Alltag",
        p_task2,
        bg_color="#FEF3C7",
        border_color="#D97706",
        icon_char="t"
    )
    story.append(box8)
    
    # --- PAGE Break to Page 3 (3) ---
    story.append(PageBreak())
    
    # --- PAGE 3 ---
    story.append(Paragraph("Kapitel 3: Geometrie und Maßeinheiten", title_style))
    story.append(Paragraph("Geometrische Berechnungen und Umrechnungen von Größen", body_style))
    story.append(Spacer(1, 10))
    
    # Box 9: Umfang (Green Box, Green)
    p_geo1 = [
        Paragraph("a) Ein Quadrat hat eine Seitenlänge von a = 5 cm. Wie groß ist der Umfang U? Formel: U = 4 * a. Rechnung: ________________________ cm", body_style),
        Paragraph("b) Ein Rechteck hat eine Länge von 6 cm und eine Breite von 4 cm. Wie groß ist der Umfang U? Formel: U = 2 * (L + B). Rechnung: ________________________ cm", body_style)
    ]
    box9 = make_callout_box(
        "Aufgabe 9 ◩: Geometrie - Umfang berechnen",
        "Bestimme die Randlängen geometrischer Formen",
        p_geo1,
        bg_color="#F0FDF4",
        border_color="#16A34A",
        icon_char="v"
    )
    story.append(box9)
    story.append(Spacer(1, 10))
    
    # Box 10: Maßeinheiten (Pencil Box, Blue)
    math_data6 = [
        [Paragraph("a)  3 kg = ________ g", math_cell_style), Paragraph("e)  4 l = ________ ml", math_cell_style)],
        [Paragraph("b)  250 g + 750 g = ________ kg", math_cell_style), Paragraph("f)  1500 ml = ____ l ____ ml", math_cell_style)],
        [Paragraph("c)  2 m = ________ cm", math_cell_style), Paragraph("g)  300 cm = ________ m", math_cell_style)],
        [Paragraph("d)  1 h 30 min = ________ min", math_cell_style), Paragraph("h)  120 s = ________ min", math_cell_style)]
    ]
    t_math6 = Table(math_data6, colWidths=[236, 236])
    t_math6.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    box10 = make_callout_box(
        "Aufgabe 10 ■: Umrechnen von Maßeinheiten",
        "Gewichte, Volumina, Längen und Zeitspannen umrechnen",
        t_math6,
        bg_color="#F0F9FF",
        border_color="#0284C7",
        icon_char="4"
    )
    story.append(box10)
    story.append(Spacer(1, 10))
    
    # Box 11: 3D Shapes (Green Box, Green)
    p_shapes = [
        Paragraph("a) Ich habe 6 quadratische Flächen, 12 Kanten und 8 Ecken. Ich bin ein ________________.", body_style),
        Paragraph("b) Ich habe keine Ecken und keine Kanten. Ich bin vollkommen rund. Ich bin eine ________________.", body_style),
        Paragraph("c) Ich habe eine kreisrunde Grundfläche und eine Spitze. Ich bin ein ________________.", body_style),
        Paragraph("d) Ich habe zwei kreisrunde Flächen (oben und unten) und eine gebogene Mantelfläche. Ich bin ein ________________.", body_style)
    ]
    box11 = make_callout_box(
        "Aufgabe 11 ■: Geometrische Körper erkennen",
        "Beschreibungen lesen und Körperformen zuordnen",
        p_shapes,
        bg_color="#F0FDF4",
        border_color="#16A34A",
        icon_char="v"
    )
    story.append(box11)
    
    doc.build(story, onFirstPage=draw_page_number_centered, onLaterPages=draw_page_number_centered)
    print(f"Created {pdf_path}")

def rasterize_to_scanned_pdf(input_pdf_path: str, output_pdf_path: str):
    import pypdfium2
    from PIL import Image
    
    pdf = pypdfium2.PdfDocument(input_pdf_path)
    images = []
    for page in pdf:
        pix = page.render(scale=4.166).to_pil() # 300 DPI
        images.append(pix.convert("RGB"))
    
    if images:
        images[0].save(output_pdf_path, save_all=True, append_images=images[1:], resolution=300.0)
        print(f"Created scanned raster PDF: {output_pdf_path} ({len(images)} pages)")

os.makedirs("testdata", exist_ok=True)
create_deutsch_textanalyse()
create_mathe_grade3()

# Regenerate scanned PDFs
rasterize_to_scanned_pdf("testdata/deutsch_textanalyse.pdf", "testdata/deutsch_textanalyse_scanned.pdf")
rasterize_to_scanned_pdf("testdata/mathe_grade3.pdf", "testdata/mathe_grade3_scanned.pdf")
if os.path.exists("testdata/test_educational.pdf"):
    rasterize_to_scanned_pdf("testdata/test_educational.pdf", "testdata/test_educational_scanned.pdf")
