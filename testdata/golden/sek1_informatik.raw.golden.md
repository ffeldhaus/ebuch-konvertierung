((18))

# Kapitel 1: Algorithmen und Programmierung

## 1.1 Kontrollstrukturen: Sequenz, Verzweigung und Schleife

Ein Algorithmus ist eine eindeutige, ausführbare und endliche Handlungsvorschrift zur schrittweisen Lösung eines Problems. In der modernen Robotik und Mikrocontroller-Technik verarbeiten autonome Systeme kontinuierlich Sensordaten, um auf Hindernisse in ihrer Umgebung zu reagieren. Dabei folgt jedes Computerprogramm drei elementaren Kontrollstrukturen: der linearen Sequenz (Befehlsfolge), der bedingten Verzweigung (Wenn-Dann-Sonst-Entscheidung) und der Wiederholungsschleife (Iteration).

![Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters](figures/informatik_programmablaufplan.png)

Abb. 1.1: Programmablaufplan (PAP) zur Hinderniserkennung eines autonomen Roboters

**Mediencode 74108-18: Interaktive Simulation Labyrinth-Roboter**
- Teste den Programmablaufplan aus Abb. 1.1 im virtuellen 2D-Parcours mit verschiedenen Schwellenwerten ($d < 15\,\text{cm}$, $d < 25\,\text{cm}$, $d < 40\,\text{cm}$) und beobachte die Fahrspur des Roboters.

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
| 0 (frei) | 0 (nicht gedrückt) | 0 (falsch) | Geradeaus fahren ($v = 50\,\%$) |
| 0 (frei) | 1 (gedrückt) | 1 (wahr) | Sofort stoppen & zurücksetzen |
| 1 (Hindernis nah) | 0 (nicht gedrückt) | 1 (wahr) | Stoppen & 90° rechts drehen |
| 1 (Hindernis nah) | 1 (gedrückt) | 1 (wahr) | Not-Stopp & Warnsignalton |

### Aufgabe 1: Programmablaufplan nachvollziehen (Trace-Tabelle)

Der Ultraschallsensor liefert nacheinander die Messwerte $d = 62\,\text{cm}$, $d = 38\,\text{cm}$, $d = 19\,\text{cm}$ und $d = 45\,\text{cm}$. Gib für jeden Messwert an, welchen Zweig der Roboter in Abb. 1.1 durchläuft.

### Aufgabe 2: Erweiterung um einen linken und rechten Seitensensor

Formuliere eine geschachtelte Wenn-Dann-Sonst-Bedingung, mit der der Roboter vor einer Drehung prüft, ob rechts mehr Platz ist als links ($d_{\text{rechts}} > d_{\text{links}}$).

### Aufgabe 3: Boolesche Algebra im Alltag

Erkläre den Unterschied zwischen einer UND-Verknüpfung (Konjunktion) und einer ODER-Verknüpfung (Disjunktion) am Beispiel einer automatischen Gewächshaus-Bewässerung.

**Checkliste: Teste dich! — Trainingsplan zu Kapitel 1**
- Ich kann die Begriffe Algorithmus, Sequenz, Verzweigung und Schleife an einem Alltagsbeispiel erläutern (Nachlesen: S. 18, Merksatz).
- Ich kann einen gegebenen Programmablaufplan (PAP) nach DIN 66001 lesen und für konkrete Eingabewerte Schritt für Schritt auswerten (Nachlesen: S. 18, Abb. 1.1).
- Ich kann einfache und zusammengesetzte Bedingungen mit den logischen Operatoren UND, ODER sowie NICHT in einer Wahrheitstabelle darstellen (Nachlesen: S. 19, Tab. 1.1).
- Ich kann erklären, warum eine Robotersteuerung in einer dauerhaften Ereignisschleife arbeitet und wie ein Not-Stopp-Abbruchkriterium integriert wird (Nachlesen: S. 19).
- Ich kann zu einer textuell beschriebenen Problemstellung selbstständig einen fehlerfreien Programmablaufplan entwerfen und testen (Übung: Aufgabe 2).
- Ich kann im Simulator mithilfe des Mediencodes 74108-18 eigene Schwellenwerte experimentell erproben und optimieren (Digitale Zusatzaufgabe: S. 18).
