((412))

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
