((18))

# Kapitel 1: Algorithmen und Programmierung

## 1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife

Ein Algorithmus ist eine eindeutige, ausführbare und endliche Handlungsvorschrift zur schrittweisen Lösung eines Problems. In der modernen Robotik und Mikrocontroller-Technik verarbeiten autonome Systeme kontinuierlich Sensordaten, um auf Hindernisse in ihrer Umgebung zu reagieren. Dabei folgt jedes Computerprogramm drei elementaren Kontrollstrukturen: der linearen Sequenz (Befehlsfolge), der bedingten Verzweigung (Wenn-Dann-Sonst-Entscheidung) und der Wiederholungsschleife (Iteration).

#### Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters

<Bild> Strukturdiagramm:
Beschreibung mit Bildtext: Programmablaufplan (PAP) zur Hinderniserkennung und Ausweichsteuerung eines Roboters in einer Endlosschleife (alle 50 ms):
Start \to Ultraschallsensor: Messe Abstand $d$ (cm) \to Entscheidung: $d < 25\,\text{cm}$?
Ja \to Stoppe Motoren und drehe $90^\circ$ nach rechts.
Nein \to Fahre geradeaus (Geschwindigkeit $v = 50\,\%$).
</Bild>

<Rahmen>
_Mediencode 74108-18: Interaktive Simulation Labyrinth-Roboter_
-	Teste den Programmablaufplan aus Abb. 1.1 im virtuellen 2D-Parcours mit verschiedenen Schwellenwerten ($d < 15\,\text{cm}$, $d < 25\,\text{cm}$, $d < 40\,\text{cm}$) und beobachte die Fahrspur des Roboters.
</Rahmen>

<Rahmen>
_Merksatz: Algorithmus und Grundstrukturen nach Böhm und Jacopini_
-	_Eindeutigkeit (Determiniertheit):_ Nach jedem Einzelschritt ist exakt festgelegt, welche Anweisung als Nächstes ausgeführt wird; es gibt keinen Interpretationsspielraum.
-	_Sequenz (Folge):_ Anweisungen werden streng nacheinander von oben nach unten abgearbeitet.
-	_Bedingte Verzweigung (Selektion):_ Eine logische Bedingung (Wahrheitswert wahr oder falsch) entscheidet darüber, ob der Ja-Zweig oder der Nein-Zweig durchlaufen wird.
-	_Schleife (Iteration):_ Ein Anweisungsblock wird solange wiederholt, wie eine Laufbedingung erfüllt ist (kopfgesteuerte Solange-Schleife) oder eine feste Anzahl erreicht wurde.
-	_Satz von Böhm und Jacopini (1966):_ Jedes berechenbare Problem lässt sich ausschließlich durch die Kombination von Sequenz, Verzweigung und Schleife ohne Sprungbefehle lösen.
-	_Terminierung vs. Endlosschleife:_ Während Berechnungsalgorithmen nach endlich vielen Schritten enden müssen, nutzen eingebettete Steuerungen oft eine dauerhafte Ereignisschleife.
</Rahmen>

((19))

### Logische Verknüpfungen und Sensordaten-Auswertung

Damit ein autonomer Transportroboter in einer Werkhalle nicht mit Regalen oder Personen kollidiert, kombiniert seine Steuerung oft mehrere Sensoren über boolesche Operatoren (_UND_, _ODER_, _NICHT_). Ein Ausweichmanöver wird genau dann eingeleitet, wenn der vordere Ultraschallsensor ein Hindernis meldet ($A = 1$) _oder_ der Stoßfänger-Taster ausgelöst wird ($B = 1$).

### Tabelle 1.1: Wahrheitstabelle und Aktor-Reaktion der Robotersteuerung

<Tabelle>
Sensor A (Abstand < 25 cm)	Sensor B (Taster vorn)	Verknüpfung A ODER B	Aktor-Befehl (Fahrmotoren)
0 (frei)	0 (nicht gedrückt)	0 (falsch)	Geradeaus fahren ($v = 50\,\%$)
0 (frei)	1 (gedrückt)	1 (wahr)	Sofort stoppen & zurücksetzen
1 (Hindernis nah)	0 (nicht gedrückt)	1 (wahr)	Stoppen & $90^\circ$ rechts drehen
1 (Hindernis nah)	1 (gedrückt)	1 (wahr)	Not-Stopp & Warnsignalton
</Tabelle>

### Aufgabe 1: Programmablaufplan nachvollziehen (Trace-Tabelle)

Der Ultraschallsensor liefert nacheinander die Messwerte $d = 62\,\text{cm}$, $d = 38\,\text{cm}$, $d = 19\,\text{cm}$ und $d = 45\,\text{cm}$. Gib für jeden Messwert an, welchen Zweig der Roboter in Abb. 1.1 durchläuft.

### Aufgabe 2: Erweiterung um einen linken und rechten Seitensensor

Formuliere eine geschachtelte Wenn-Dann-Sonst-Bedingung, mit der der Roboter vor einer Drehung prüft, ob rechts mehr Platz ist als links ($d_{\text{rechts}} > d_{\text{links}}$).

### Aufgabe 3: Boolesche Algebra im Alltag

Erkläre den Unterschied zwischen einer _UND_-Verknüpfung (Konjunktion) und einer _ODER_-Verknüpfung (Disjunktion) am Beispiel einer automatischen Gewächshaus-Bewässerung.

<Rahmen>
_Checkliste: Teste dich! — Trainingsplan zu Kapitel 1_
-	Ich kann die Begriffe Algorithmus, Sequenz, Verzweigung und Schleife an einem Alltagsbeispiel erläutern (Nachlesen: S. 18, Merksatz).
-	Ich kann einen gegebenen Programmablaufplan (PAP) nach DIN 66001 lesen und für konkrete Eingabewerte Schritt für Schritt auswerten (Nachlesen: S. 18, Abb. 1.1).
-	Ich kann einfache und zusammengesetzte Bedingungen mit den logischen Operatoren _UND_, _ODER_ sowie _NICHT_ in einer Wahrheitstabelle darstellen (Nachlesen: S. 19, Tab. 1.1).
-	Ich kann erklären, warum eine Robotersteuerung in einer dauerhaften Ereignisschleife arbeitet und wie ein Not-Stopp-Abbruchkriterium integriert wird (Nachlesen: S. 19).
-	Ich kann zu einer textuell beschriebenen Problemstellung selbstständig einen fehlerfreien Programmablaufplan entwerfen und testen (Übung: Aufgabe 2).
-	Ich kann im Simulator mithilfe des Mediencodes 74108-18 eigene Schwellenwerte experimentell erproben und optimieren (Digitale Zusatzaufgabe: S. 18).
</Rahmen>
