((44))

# Inhaltsverzeichnis

-	Kapitel 5: Wellenoptik und Quantenphysik 45
-	5.1 Interferenz und Beugung am Doppelspalt 45
-	Versuchsaufbau mit dem Doppelspalt 45
-	Herleitung der Gangunterschiedsformel 46
-	5.2 Optisches Gitter und hochauflösende Spektroskopie 46
-	Photoelektrischer Effekt und Lichtquantenhypothese 47

## Abbildungsverzeichnis

-	Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt 45
-	Abb. 5.2: Beugung am optischen Gitter und Linienspektrum 46

## Tabellenverzeichnis

-	Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien 46
-	Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt 47

## Bildverzeichnis

-	Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young 45
-	Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung 47

<Rahmen>
_Lernwegweiser zu Kapitel 5: Vom Wellenmodell zum Quantenobjekt Photon_
-	In Abschnitt 5.1 untersuchen Sie die Kohärenz und Interferenz von Licht am Doppelspalt und leiten die Bedingung für konstruktive und destruktive Interferenz geometrisch her.
-	In Abschnitt 5.2 nutzen Sie optische Mehrfachspalt-Gitter zur präzisen Wellenlängenbestimmung atomarer Spektrallinien (Fraunhofer-Linien und Quecksilber-Dampflampe).
-	Abschließend zeigt der äußere lichtelektrische Effekt (Hallwachs- und Photoeffekt), dass Energie im elektromagnetischen Strahlungsfeld nur in Lichtquanten $E = h \cdot f$ übertragen wird. Alle Abbildungen, Tabellen und Bilder sind oben mit Seitenzahl verzeichnet.
</Rahmen>

((45))

# Kapitel 5: Wellenoptik und Quantenphysik

## 5.1 Interferenz und Beugung am Doppelspalt

Im Jahr 1802 gelang dem englischen Naturforscher Thomas Young mit dem Doppelspaltversuch der entscheidende experimentelle Nachweis für die Wellennatur des Lichts. Trifft monochromatisches, kohärentes Licht der Wellenlänge $\lambda$ auf zwei eng benachbarte parallele Spalte mit dem Spaltmittenabstand $d$, so gehen von beiden Öffnungen nach dem Huygens’schen Prinzip zylindrische Elementarwellen aus, die sich im Raum hinter der Blende ungestört überlagern.

### Versuchsaufbau mit dem Doppelspalt

#### Abb. 5.1: Interferenzmuster und Intensitätsverteilung am Doppelspalt

<Bild> Diagramm:
Beschreibung mit Bildtext: Schematische Darstellung der Doppelspalt-Interferenz links mit einfallendem Laserstrahl ($\lambda = 632{,}8\,\text{nm}$), Doppelspaltblende ($S_1$, $S_2$), halbkreisförmigen Huygens’schen Elementarwellen und den Interferenzmaxima $k = -2, -1, 0, 1, 2$ auf dem Beobachtungsschirm sowie dem zugehörigen Intensitätsverlauf $I(y)$ rechts mit dem Hauptmaximum bei $k = 0$ und der Bedingung $\Delta s = k \cdot \lambda$.
</Bild>

Auf dem Beobachtungsschirm im Abstand $L \gg d$ entsteht ein charakteristisches Streifenmuster aus abwechselnd hellen Interferenzmaxima und dunklen Interferenzminima. Ein helles Maximum $k$-ter Ordnung tritt immer dort auf, wo der Gangunterschied $\Delta s$ der beiden Teilwellen ein ganzzahliges Vielfaches der Wellenlänge $\lambda$ beträgt ($\Delta s = k \cdot \lambda$ mit $k = 0, 1, 2, \dots$). Beträgt der Gangunterschied hingegen ein ungeradzahliges Vielfaches einer halben Wellenlänge, löschen sich Wellenberg und Wellental durch destruktive Interferenz gegenseitig aus.

<Rahmen>
_Bild 5.1: Historisches Doppelspalt-Interferenzmuster nach Thomas Young_
-	_Kohärenzbedingung:_ Zeitlich und räumlich konstante Phasenbeziehung zwischen beiden Elementarwellenzügen; im modernen Schulexperiment durch einen He-Ne-Laser ($\lambda = 632{,}8\,\text{nm}$).
-	_Konstruktive Interferenz (Verstärkung):_ $\Delta s = d \cdot \sin(\alpha_k) = k \cdot \lambda$ (für $k = 0, 1, 2, \dots$).
-	_Destruktive Interferenz (Auslöschung):_ $\Delta s = d \cdot \sin(\alpha_k) = (k + \frac{1}{2}) \cdot \lambda$.
-	_Kleinwinkelnäherung (für kleine Winkel $\alpha < 10^\circ$ gilt $\sin(\alpha) \approx \tan(\alpha) = \frac{y_k}{L}$):_ Der Streifenabstand benachbarter Maxima auf dem Schirm beträgt $\Delta y = \frac{\lambda \cdot L}{d}$.
-	Je kleiner der Spaltabstand $d$ gewählt wird, desto weiter rücken die Maxima auseinander.
</Rahmen>

((46))

#### Herleitung der Gangunterschiedsformel

Da der Schirmabstand $L$ im Experiment sehr viel größer als der Spaltmittenabstand $d$ ist (Fraunhofer-Näherung), verlaufen die beiden Strahlen von den Spalten $S_1$ und $S_2$ zu einem Schirmpunkt $P$ nahezu parallel unter demselben Beugungswinkel $\alpha$. Fällen wir vom oberen Spalt $S_1$ das Lot auf den unteren Strahl, entsteht ein rechtwinkliges Dreieck mit der Hypotenuse $d$ und der Gegenkathete $\Delta s$. Daraus folgt unmittelbar $\Delta s = d \cdot \sin(\alpha)$.

## 5.2 Optisches Gitter und hochauflösende Spektroskopie

Ersetzt man den Doppelspalt durch ein optisches Transmissionsgitter mit $N \gg 100$ äquidistanten Spalten (Gitterkonstante $g = \frac{1}{n}$), so bleibt die Lage der Hauptmaxima bei $g \cdot \sin(\alpha_k) = k \cdot \lambda$ erhalten. Durch die Vielstrahlinterferenz aller $N$ Elementarwellen werden die Hauptmaxima jedoch extrem scharf und lichtstark, während zwischen zwei Hauptmaxima jeweils $N - 1$ Nebenminima nahezu vollständige Dunkelheit erzeugen.

#### Abb. 5.2: Beugung am optischen Gitter und Linienspektrum

Schematischer Strahlengang am Mehrfachspalt (Gitterkonstante $g = 1{,}67\,\mu\text{m}$, entsprechend 600 Linien/mm): Kurzwelliges violettes Licht (405 nm) wird weniger stark gebeugt als langwelliges rotes Licht (656 nm).

### Tab. 5.1: Wellenlängen und Beugungswinkel ausgewählter Spektrallinien

<Tabelle>
Spektrallinie / Element	Farbeindruck	Wellenlänge $\lambda$ (nm)	Winkel $\alpha_1$ (1. Ordnung)
Quecksilber (Hg-Linie h)	Violett	404,7 nm	$14{,}1^\circ$
Wasserstoff (H-beta)	Blaugrün (Cyan)	486,1 nm	$17{,}0^\circ$
Natrium-Doppellinie (Na-D)	Gelb-Orange	589,3 nm	$20{,}7^\circ$
Helium-Neon-Laser	Hellrot	632,8 nm	$22{,}3^\circ$
Wasserstoff (H-alpha)	Tiefrot	656,3 nm	$23{,}2^\circ$
</Tabelle>

<Rahmen>
_Methoden-Kasten: Gitter-Spektroskopie in Astrophysik und Labor_
-	_Auflösungsvermögen eines Gitters:_ $R = \frac{\lambda}{\Delta\lambda} = k \cdot N$ (wächst mit der beleuchteten Spaltzahl $N$).
-	_Beispiel Natrium-D-Doppellinie ($\lambda_1 = 589{,}0\,\text{nm}$ und $\lambda_2 = 589{,}6\,\text{nm}$):_ Um beide Linien in der ersten Beugungsordnung ($k = 1$) getrennt aufzulösen, müssen mindestens $N \approx 983$ Gitterfurchen kohärent ausgeleuchtet werden.
-	_Maximal beobachtbare Beugungsordnung:_ Da $\sin(\alpha_k) \le 1$ gelten muss, folgt $k_{\max} = \lfloor \frac{g}{\lambda} \rfloor$.
-	_Chemische Spektralanalyse (Bunsen & Kirchhoff):_ Jedes chemische Element besitzt ein unverwechselbares Linienspektrum als optischen Fingerabdruck elektronischer Übergänge.
-	In der Astrophysik ermöglicht die Verschiebung der Fraunhofer’schen Absorptionslinien (Doppler-Effekt) die exakte Bestimmung der Radialgeschwindigkeit ferner Galaxien.
-	_Unterschied zum Dispersionsprisma:_ Beim optischen Gitter wird langwelliges rotes Licht stärker abgelenkt als kurzwelliges blaues Licht (Normaldispersion beim Prisma ist umgekehrt).
-	_Eichung im Schülerexperiment:_ Mit der bekannten He-Ne-Laserwellenlänge $\lambda = 632{,}8\,\text{nm}$ lässt sich zunächst die Gitterkonstante $g$ eines unbekannten optischen Gitters bestimmen.
</Rahmen>

((47))

### Photoelektrischer Effekt und Lichtquantenhypothese

Bestrahlt man eine metallische Photokathode (z. B. Cäsium oder Kalium) mit kurzwelligem ultraviolettem oder blauem Licht, so werden augenblicklich Leitungselektronen aus der Metalloberfläche ausgelöst (äußerer lichtelektrischer Effekt). Nach der klassischen Wellentheorie müsste die maximale kinetische Energie $E_{\text{kin,max}}$ der Photoelektronen von der Bestrahlungsstärke (Intensität) des Lichts abhängen. Das Experiment mit der Gegenspannungsmethode zeigt jedoch: $E_{\text{kin,max}}$ hängt ausschließlich linear von der Lichtfrequenz $f$ ab! Albert Einstein deutete diesen Befund 1905 mit seiner Lichtquantenhypothese: Elektromagnetische Strahlung der Frequenz $f$ besteht aus einzelnen Energiequanten (Photonen) der Energie $E_{\text{Photon}} = h \cdot f$ mit dem Planck’schen Wirkungsquantum $h = 6{,}626 \cdot 10^{-34}\,\text{J}\cdot\text{s}$.

#### Bild 5.2: Schematische Darstellung einer Photozelle zur Gegenspannung

Vakuum-Photozelle mit bestrahlter Kalium-Kathode, Ringanode, einstellbarer Gegenspannung $U_G$ und Picoamperemeter: Bei $e \cdot U_G = E_{\text{kin,max}} = h \cdot f - W_A$ sinkt der Photostrom exakt auf null.

### Tab. 5.2: Austrittsarbeit ausgewählter Metalle beim Photoeffekt

<Tabelle>
Kathodenmetall	Austrittsarbeit $W_A$ (eV)	Grenzfrequenz $f_G$ ($10^{14}\,\text{Hz}$)	Grenzwellenlänge $\lambda_G$ (nm)
Cäsium (Cs)	1,94 eV	$4{,}69 \cdot 10^{14}\,\text{Hz}$	639 nm (Rot)
Kalium (K)	2,25 eV	$5{,}44 \cdot 10^{14}\,\text{Hz}$	551 nm (Grün)
Natrium (Na)	2,28 eV	$5{,}51 \cdot 10^{14}\,\text{Hz}$	544 nm (Grün)
Zink (Zn)	4,31 eV	$10{,}4 \cdot 10^{14}\,\text{Hz}$	288 nm (UV)
Platin (Pt)	5,32 eV	$12{,}9 \cdot 10^{14}\,\text{Hz}$	233 nm (UV)
</Tabelle>

### Übungsaufgaben zu Wellenoptik und Quantenphysik

-	Aufgabe 1: Berechnen Sie aus Tab. 5.1 die Gitterkonstante $g$ des verwendeten optischen Gitters.
-	Aufgabe 2: Begründen Sie mithilfe von Tab. 5.2, warum rotes Laserlicht ($\lambda = 632{,}8\,\text{nm}$) zwar an einer Cäsium-Kathode, nicht aber an einer Kalium- oder Zink-Kathode Photoelektronen auslöst.
-	Aufgabe 3: Bestimmen Sie die maximale kinetische Energie und Geschwindigkeit der Photoelektronen beim Bestrahlen einer Kalium-Kathode mit violettem Quecksilberlicht ($\lambda = 404{,}7\,\text{nm}$).

<Rahmen>
_Merksatz: Einstein’sche Gleichung des Photoeffekts und Welle-Teilchen-Dualismus_
-	_Energiebilanz beim Photoeffekt:_ $E_{\text{kin,max}} = h \cdot f - W_A = e \cdot U_G$.
-	_Grenzfrequenz $f_G = \frac{W_A}{h}$:_ Unterhalb von $f_G$ werden selbst bei höchster Lichtintensität keine Elektronen ausgelöst; oberhalb von $f_G$ setzt der Photostrom verzögerungsfrei ein.
-	_Bedeutung der Lichtintensität:_ Eine höhere Bestrahlungsstärke bedeutet mehr Photonen pro Sekunde und erhöht die Stromstärke $I_{\text{Photo}}$, nicht jedoch die Einzelenergie $h \cdot f$.
-	_Welle-Teilchen-Dualismus:_ Bei der Ausbreitung im Raum (Beugung am Doppelspalt und Gitter) zeigt Licht Welleneigenschaften; bei der Wechselwirkung mit Materie (Emission und Absorption) tritt sein Teilchencharakter in Form unteilbarer Lichtquanten (Photonen) hervor.
-	_Umrechnung der Energieeinheit Elektronenvolt:_ $1\,\text{eV} = 1{,}602 \cdot 10^{-19}\,\text{J}$.
-	_Impuls eines Photons:_ $p = \frac{E}{c} = \frac{h}{\lambda}$ (experimentell bestätigt durch den Compton-Effekt).
</Rahmen>
