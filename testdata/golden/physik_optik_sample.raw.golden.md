((500))

# Kapitel 11. Optik

![Abbildung 11.49: Lichtweg mit Knick](images/abb_11_49.png)
Abbildung 11.49: Lichtweg mit Knick

![Abbildung 11.50: Lichtbrechung am Übergang Luft-Glas](images/abb_11_50.png)
Abbildung 11.50: Lichtbrechung am Übergang Luft-Glas

((501))

## 11.6. Licht in unterschiedlichen Medien

Dabei wird der Lichtstrahl immer so gebrochen, dass der Brechungswinkel (engl. angle of refraction; Winkel zwischen dem gebrochenen Lichtstrahl und dem Lot) immer kleiner als der Einfallswinkel (Winkel zwischen dem einfallenden Lichtstrahl und dem Lot) ist. Trifft der Lichtstrahl senkrecht auf die Oberfläche, kommt es zu keiner Ablenkung.

Wie stark ein Lichtstrahl gebrochen wird, hängt von dem jeweiligen (durchsichtigen) Material ab. Nimmst du zum Beispiel Wasser statt Glas, ist der Brechungswinkel (bei gleichem Einfallswinkel) größer – er weicht weniger stark von seiner ursprünglichen Richtung ab.

Bei genauer Betrachtung siehst du auch einen reflektierten Strahl. Tatsächlich teilt sich die Lichtenergie beim Auftreffen an der Grenzschicht der beiden Medien in einen reflektierten und einen gebrochenen Anteil auf.

Links:
- WebApp: Lichtbrechung

### 11.6.2 Fermatsches Prinzip

Welche Eigenschaft eines (lichtdurchlässigen) Materials bestimmt eigentlich, wie stark ein Lichtstrahl gebrochen wird? Der Grund ist, dass sich Licht in unterschiedlichen Materialien unterschiedlich schnell ausbreitet. Während die Geschwindigkeit von Licht an Luft fast der Vakuum-Lichtgeschwindigkeit von $c_0 = 3 \cdot 10^8 \text{ m/s}$ entspricht, ist sie in Wasser und Glas kleiner.

![Abbildung 11.51: Wie erreicht der Rettungsschwimmer den Ertrinkenden am schnellsten?](images/abb_11_51.png)
Abbildung 11.51: Wie erreicht der Rettungsschwimmer den Ertrinkenden am schnellsten?

Sieh dir das Bild 11.51 an. Du bist ein Rettungsschwimmer und befindest dich am Strand (Punkt A). Plötzlich entdeckst du im Wasser einen Ertrinkenden (Punkt B). Welchen Weg nimmst du, um ihn am schnellsten zu retten?

Normalerweise ist die Luftlinie der kürzeste Weg. Allerdings kannst du am Strand wesentlich schneller laufen als im Wasser. Daher wird es klüger sein, etwas länger am Strand zu laufen und dann erst abzubiegen. Der Weg wird dadurch zwar länger, aber zeitlich kürzer! In Bild 11.52 siehst du den zeitlich kürzesten Weg für den konkreten Fall, dass der Rettungsschwimmer viermal so schnell am Strand läuft wie im Wasser.

Licht verhält sich nach demselben Prinzip: Ein Lichtstrahl wird stets so gebrochen, dass er die zwei Punkte in kürzester Zeit durchläuft. Dieses Verhalten von Licht wird Fermatsches Prinzip (engl. Fermat's principle) – nach Pierre de Fermat – genannt.

Vielleicht fragst du dich, woher das Licht im Voraus "weiß", welches der kürzeste Weg ist? Siehst du dir die Laufzeitkurve in 11.52 (unten) genau an, stellst du fest, dass sich die Laufzeit um das Minimum herum nur ganz wenig ändert. Das Licht nimmt sozusagen alle Lichtwege gleichzeitig (Wellenphänomen), aber um das Minimum herum findet konstruktive Interferenz statt, alle anderen Wege löschen sich durch destruktive Interferenz aus.

((502))

![Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem](images/abb_11_52.png)
Abbildung 11.52: Laufzeit beim Rettungsschwimmer-Problem

### 11.6.3 Brechungsindex

Wie schnell sich Licht in einem Medium ausbreitet, wird oft nicht als Geschwindigkeitswert angegeben. Wegen der großen Zahlen wird stattdessen das Verhältnis der Vakuum-Lichtgeschwindigkeit $c_0$ zur Ausbreitungsgeschwindigkeit $c_M$ des Lichts im Medium (Material) angegeben:

$$n = \frac{c_0}{c_M}$$ (11.1)

Diese materialabhängige dimensionslose Größe (Zahl) $n$ wird Brechungsindex oder Brechzahl (engl. refractive index) des jeweiligen Materials genannt. Hat ein Medium einen Brechungsindex von 2 ist die Lichtgeschwindigkeit gerade halb so groß wie in Vakuum. Zur Orientierung findest du in der Tabelle die Brechzahlen einiger optischer Medien:

| Material | Brechungsindex n |
| :--- | :--- |
| Vakuum | 1 |
| Luft | 1,000292 |
| Eis | 1,31 |
| Wasser | 1,33 |
| Augenlinse (Mensch) | 1,35 - 1,42 |
| Glas | 1,45 - 1,93 |
| Fensterglas | ca. 1,5 |
| Diamant | 2,42 |

Für den Brechungsindex wird oft auch die Bezeichnung optische Dichte verwendet. Je größer die optische Dichte, desto langsamer breitet sich Licht in diesem Medium aus. Das ist eine recht anschauliche Vorstellung. Der Begriff der Dichte ist prinzipiell unabhängig von dem der optischen Dichte eines Materials. Vielfach haben aber Medien mit einer größeren Dichte auch eine größere optische Dichte.

((503))

### 11.6.4 Snelliussches Brechungsgesetz

Das Snelliussches Brechungsgesetz (engl. Snell's law) – benannt nach Willebrord van Roijen Snell – beschreibt den mathematischen Zusammenhang zwischen Einfallswinkel und Brechungswinkel (Bild 11.53).

![Abbildung 11.53: Snelliussches Brechungsgesetz](images/abb_11_53.png)
Abbildung 11.53: Snelliussches Brechungsgesetz

Es lautet:

$$\frac{\sin(\alpha_1)}{\sin(\alpha_2)} = \frac{c_1}{c_2} = \frac{n_2}{n_1}$$

Eine gleichwertige Form ist:

$$n_1 \cdot \sin(\alpha_1) = n_2 \cdot \sin(\alpha_2)$$ (11.2)

In der Gleichung bedeuteten:
- $\alpha_1$, den Einfallswinkel im Medium 1
- $\alpha_2$, den Brechungswinkel im Medium 2
- $c_1$, die Lichtgeschwindigkeit im Medium 1
- $c_2$, die Lichtgeschwindigkeit im Medium 2
- $n_1$, den Brechungsindex von Medium 1
- $n_2$, den Brechungsindex von Medium 2

### 11.6.5 Herleitung des Snelliusschen Brechungsgesetzes

Für die Herleitung des Snelliusschen Brechungsgesetzes wenden wir das Fermatsche Prinzip (11.6.2) an, nachdem das Licht den Weg mit der kürzesten Lichtlaufzeit nimmt – es handelt sich also um eine Extremwertaufgabe.
