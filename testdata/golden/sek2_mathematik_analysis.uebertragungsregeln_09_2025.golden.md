((50))

# Kapitel 2: Analysis — Untersuchung ganzrationaler Funktionen

## 2.1 Charakteristische Punkte, Ableitungsfunktion und Integralfläche

Eine ganzrationale Funktion $n$-ten Grades besitzt die allgemeine Funktionsgleichung $f(x) = a_n \cdot x^n + a_{n-1} \cdot x^{n-1} + \dots + a_1 \cdot x + a_0$ mit $a_n \neq 0$. Ihr globales Verhalten für betragsgroße Werte von $x$ wird ausschließlich vom Leitkoeffizienten $a_n$ und dem höchsten Exponenten $n$ bestimmt. Mithilfe der ersten und zweiten Ableitungsfunktion $f'(x)$ und $f''(x)$ lassen sich lokale Extrempunkte sowie Wendepunkte exakt berechnen.

#### Abb. 2.1: Funktionsgraph von f(x) und Ableitungsgraph f'(x) mit Extrem-, Wende- und Integralbereich

<Bild> Diagramm:
Beschreibung mit Bildtext: Koordinatensystem mit dem blauen Funktionsgraphen $f(x) = \frac{1}{4}x^3 - 1{,}5x^2 + 2x + 1$, dem roten Ableitungsgraphen $f'(x) = 0{,}75x^2 - 3x + 2$, den markierten Punkten Hochpunkt $H(0{,}85 \mid 1{,}77)$, Wendepunkt $W(2 \mid 1)$ und Tiefpunkt $T(3{,}15 \mid 0{,}23)$ sowie der hellblau schraffierten Integralfläche $A = 4\,\text{FE}$ zwischen Graph und $x$-Achse im Intervall $[0; 4]$.
</Bild>

<Rahmen>
_Merksatz: Notwendige und hinreichende Kriterien der Differential- und Integralrechnung_
-	_Potenz- und Summenregel der Ableitung:_ Für $f(x) = c \cdot x^n$ gilt $f'(x) = c \cdot n \cdot x^{n-1}$.
-	_Notwendige Bedingung für lokale Extremstellen:_ $f'(x_E) = 0$ (waagerechte Tangente).
-	_Hinreichende Bedingung für lokale Extremstellen:_ Gilt $f'(x_E) = 0$ und $f''(x_E) < 0$, so liegt bei $x_E$ ein lokales Maximum (Hochpunkt $H$) vor. Gilt $f'(x_E) = 0$ und $f''(x_E) > 0$, so liegt bei $x_E$ ein lokales Minimum (Tiefpunkt $T$) vor.
-	_Notwendige und hinreichende Bedingung für Wendestellen (Krümmungswechsel):_ Gilt $f''(x_W) = 0$ und $f'''(x_W) \neq 0$, so besitzt der Graph bei $W(x_W \mid f(x_W))$ einen Wendepunkt.
-	_Hauptsatz der Differential- und Integralrechnung (Bestimmtes Integral):_ Ist $F(x)$ eine Stammfunktion von $f(x)$ mit $F'(x) = f(x)$, so gilt auf dem Intervall $[a; b]$: $\int_a^b f(x)\,dx = [F(x)]_a^b = F(b) - F(a)$.
-	_Symmetrieverhalten ganzrationaler Funktionen:_ Nur gerade Exponenten ($f(-x) = f(x)$): Achsensymmetrie zur $y$-Achse. Nur ungerade Exponenten ($f(-x) = -f(x)$): Punktsymmetrie zum Koordinatenursprung $O(0 \mid 0)$.
-	_Tangentensteigung $m_t$ in einem Kurvenpunkt $P(x_0 \mid f(x_0))$:_ $t(x) = f'(x_0) \cdot (x - x_0) + f(x_0)$.
</Rahmen>

((51))

### Tabelle 2.1: Charakteristische Punkte von f(x) = 0,25 x^3 - 1,5 x^2 + 2 x + 1

<Tabelle>
Merkmal / Punkt	x-Wert	Funktionswert $f(x)$	Ableitungswerte & Begründung
y-Achsenabschnitt $S_y$	$x = 0$	$f(0) = 1{,}00$	$f'(0) = 2{,}00$ (steigend)
Hochpunkt $H$ (Maximum)	$x_H \approx 0{,}85$	$f(x_H) \approx 1{,}77$	$f'(x_H) = 0$ und $f''(x_H) \approx -1{,}73 < 0$
Wendepunkt $W$	$x_W = 2{,}00$	$f(2) = 1{,}00$	$f''(2) = 0$ und $f'''(2) = 1{,}50 \neq 0$
Tiefpunkt $T$ (Minimum)	$x_T \approx 3{,}15$	$f(x_T) \approx 0{,}23$	$f'(x_T) = 0$ und $f''(x_T) \approx +1{,}73 > 0$
Randpunkt im Intervall	$x = 4{,}00$	$f(4) = 1{,}00$	$f'(4) = 2{,}00$ (punktsymmetrisch zu $W$)
</Tabelle>

<Rahmen>
_Tipp: Musterlösung zur Berechnung des bestimmten Integrals auf [0; 4]_
-	Gegeben ist $f(x) = 0{,}25 x^3 - 1{,}5 x^2 + 2 x + 1$ mit den Ableitungen $f'(x) = 0{,}75 x^2 - 3 x + 2$ und $f''(x) = 1{,}5 x - 3$. Da $f(x) > 0$ für alle $x \in [0; 4]$ gilt, liegt der Graph vollständig über der $x$-Achse.
-	_Bildung einer Stammfunktion $F(x)$:_ $F(x) = \frac{1}{16} x^4 - 0{,}5 x^3 + x^2 + x$.
-	_Einsetzen der Integrationsgrenzen $a = 0$ und $b = 4$ nach dem Hauptsatz:_ $A = \int_0^4 f(x)\,dx = F(4) - F(0) = (16 - 32 + 16 + 4) - 0 = 4$ Flächeneinheiten (FE).
-	_Kontrolle durch Punktsymmetrie zu $W(2 \mid 1)$:_ Das Rechteck der Breite 4 und Höhe 1 hat genau $A = 4\,\text{FE}$.
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

Der Graph einer ganzrationalen Funktion 3. Grades verläuft durch den Ursprung $O(0 \mid 0)$, besitzt im Punkt $W(2 \mid 4)$ einen Wendepunkt und hat dort die Steigung $m = -3$.
a) Stellen Sie das lineare Gleichungssystem auf und weisen Sie nach, dass $p(x) = 0{,}5 x^3 - 3 x^2 + 3 x + 0$ bzw. mit angepasstem Koeffizienten die Bedingungen erfüllt.
b) Berechnen Sie den Inhalt der Fläche, die der Graph von $f(x)$ aus Abb. 2.1 mit der Wendetangente und der $y$-Achse im ersten Quadranten einschließt.

Hinweis zur Selbstkontrolle: Nutzen Sie für Teilaufgabe b) die Differenzfunktion $d(x) = f(x) - t_W(x)$ und bestimmen Sie vor der Integration die Schnittstellen im Intervall $[0; 4]$.
