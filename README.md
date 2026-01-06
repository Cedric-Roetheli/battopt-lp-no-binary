
# Battery LP Optimizer (EV + Peak Shaving)

**Jahres-LP (linear, ohne Binärvariablen)** zur gleichzeitigen Optimierung von:

- **Eigenverbrauch** (PV → Last/Batterie, weniger Netzbezug)
- **Peak Shaving** / **Demand Charges** (Reduktion von Lastspitzen)
- **Einspeisevergütung mit Cap** (Exportvergütung begrenzt / gekappt)

Das Projekt löst eine **lineare Optimierung über ein ganzes Jahr** (oder generell lange Zeitreihen) – explizit **ohne Binärvariablen**, um robust und schnell auf Standard-LP-Solvern (z. B. CBC) laufen zu können.
---

## Inhaltsverzeichnis

- [Motivation & Zielsetzung](#motivation--zielsetzung)
- [Was bedeutet „LP ohne Binärvariablen“?](#was-bedeutet-lp-ohne-binärvariablen)
- [Funktionsumfang](#funktionsumfang)
- [Nicht-Ziele & bekannte Einschränkungen](#nicht-ziele--bekannte-einschränkungen)
- [Projektstruktur](#projektstruktur)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [CLI: `battopt_lp.cli.optimize_year`](#cli-battopt_lpclioptimize_year)
- [Konfiguration (YAML)](#konfiguration-yaml)
  - [1) Überblick](#1-überblick)
  - [2) Zeitreihen-Format](#2-zeitreihen-format)
  - [3) Site-/Tarif-Parameter](#3-sitetarif-parameter)
  - [4) Batterie-/Inverter-Parameter](#4-batterieinverter-parameter)
  - [5) Peak-Shaving / Demand Charge](#5-peak-shaving--demand-charge)
  - [6) Einspeisevergütung mit Cap](#6-einspeisevergütung-mit-cap)
  - [7) Solver-Optionen](#7-solver-optionen)
- [Mathematisches Modell (Konzept)](#mathematisches-modell-konzept)
  - [Entscheidungsvariablen](#entscheidungsvariablen)
  - [Nebenbedingungen](#nebenbedingungen)
  - [Zielfunktion](#zielfunktion)
- [Outputs](#outputs)
  - [HTML-Report](#html-report)
  - [CSV-Zeitreihe](#csv-zeitreihe)
- [Tipps zur Datenqualität](#tipps-zur-datenqualität)
- [Performance & Skalierung](#performance--skalierung)
- [Reproduzierbarkeit](#reproduzierbarkeit)
- [Troubleshooting](#troubleshooting)
- [Entwicklung](#entwicklung)
- [Contributing](#contributing)
- [Lizenz](#lizenz)

---

## Motivation & Zielsetzung

Energie-Optimierung im Gebäude-/Site-Kontext hat typischerweise mehrere (teils konkurrierende) Ziele:

1. **Kosten minimieren:** Netzbezug reduzieren (Eigenverbrauch erhöhen) und Lastspitzen vermeiden (Demand Charges).
2. **Erlöse maximieren:** Einspeisung kann vergütet werden – jedoch oft mit **Cap** (z. B. ab einer gewissen Einspeiseleistung oder Energiemenge sinkt/endet die Vergütung).
3. **Technische Restriktionen einhalten:** Batteriekapazität, Lade-/Entladeleistung, Wirkungsgrade, SOC-Grenzen, ggf. Netzanschlusslimit.

Dieses Projekt richtet sich auf einen **Jahreshorizont** (oder allgemein lange Zeitreihen) und nutzt ein **lineares Programm (LP)**, um eine global konsistente Lösung über den gesamten Zeitraum zu finden. 
---

## Was bedeutet „LP ohne Binärvariablen“?

Viele Batteriemodelle verwenden Binärvariablen, um z. B. **gleichzeitiges Laden und Entladen** strikt zu verhindern (`charge_on ∈ {0,1}` etc.). Das macht das Problem zu einem **MIP/MILP** und kann bei Jahreshorizonten (viele Zeitschritte!) schnell teuer werden.

Dieses Projekt bleibt bewusst bei einem **LP**:
- schnellere Solve-Zeiten
- bessere Skalierbarkeit (365 Tage × 96 Viertelstunden = 35’040 Schritte)
- robust auf frei verfügbaren Solvern (z. B. CBC)

**Wichtig:** Ohne Binärvariablen muss man modellseitig damit umgehen, dass „Charge“ und „Discharge“ theoretisch gleichzeitig positiv werden könnten. Typische LP-Strategien (je nach Implementierung) sind:
- geringe zusätzliche Kosten/Verluste, die simultane Flüsse unattraktiv machen
- saubere Wirkungsgradmodellierung
- optionale Regularisierung (z. B. kleine Strafkosten auf Summe der Batterieflüsse)

> Praxistipp: Wenn du in Ergebnissen unerwartet gleichzeitiges Laden/Entladen siehst, ist das meist ein Hinweis auf (a) zu geringe Verlust-/Penalty-Terme oder (b) inkonsistente Zeitreihen/Preise.

---

## Funktionsumfang

- **Optimierung über lange Zeiträume** (insb. „Jahr“)
- **PV + Load + Batterie** Energiebilanz pro Zeitschritt
- **Peak Shaving** über Demand-Charge-Abbildung (typisch: max. Netzbezug pro Abrechnungsperiode)
- **Einspeisevergütung mit Cap** (Exportvergütung begrenzt)
- **HTML-Report** und **CSV-Export** der optimierten Zeitreihen
- Auswahl des **Solvers** via CLI (z. B. `CBC`)

---


## Projektstruktur

Top-Level (laut Repository):
- `battopt_lp/` – Python-Paket (Model, CLI, Report/Export)
- `configs/` – Beispiel-/Template-Konfigurationen (inkl. `site_timeseries.yaml`)
- `requirements.txt` – Python Dependencies
- `pyproject.toml` – Projektmetadaten/Tooling

---

## Installation

```bash
python -m venv .venv
# Windows: . .venv/Scripts/activate
# macOS/Linux: source .venv/bin/activate
pip install e . # oder pip install -r requirements.txt
```
Diese Schritte entsprechen dem im Repo beschriebenen Setup. 

Tipp: Für reproduzierbare Ergebnisse empfiehlt sich zusätzlich das Pinning von Solver-Versionen und Python-Version (z. B. via python==3.11.*).




Quickstart


Minimaler Run mit Beispielkonfiguration:
```bash
python -m battopt_lp.cli.optimize_year \
  --config configs/site_timeseries.yaml \
  --report-html out/report.html \
  --series-csv out/series.csv \
  --solver CBC
```
Genau dieses Kommando (inkl. Parameter) ist im Repo als „Run“ dokumentiert. 


CLI: 
battopt_lp.cli.optimize_year

Zweck

•	Lädt eine YAML-Konfiguration mit Site-/Tarif-/Batterie-Parametern und Zeitreihen
•	Baut das LP-Modell
•	Löst es mit dem angegebenen Solver
•	Schreibt:

o	--report-html … (HTML-Report)
o	--series-csv … (Zeitreihen als CSV)
•	



Parameter

Flag	Beschreibung	Beispiel
--config	Pfad zur YAML-Konfiguration	configs/site_timeseries.yaml
--report-html	Output-Pfad für HTML-Report	out/report.html
--series-csv	Output-Pfad für CSV-Zeitreihe	out/series.csv
--solver	Solver-Backend (String)	CBC
Quelle: README-Snippet im Repository. 




Konfiguration (YAML)



1) Überblick


Die zentrale Konfiguration ist eine YAML-Datei (Beispiel):

•	configs/site_timeseries.yaml  


Sie enthält typischerweise:

•	Metadaten (Zeitzone, Zeitschritt)
•	Zeitreihen (Load, PV, Preise, ggf. Exportpreise)
•	Batterie- und Netzparameter
•	Demand-Charge-/Peak-Shaving-Settings
•	Exportvergütung inkl. Cap
•	Solver-/Report-Optionen (optional)


Bitte gleiche Feldnamen kurz mit dem Beispiel-File ab. Inhaltlich passt die folgende Struktur zu den üblichen Anforderungen dieses Problemtyps.




2) Zeitreihen-Format


Empfehlung: Zeitreihen in einem der folgenden Formate:

A) Inline in YAML (nicht empfohlen)
timeseries:
  - ts: "2025-01-01T00:00:00+01:00"
    load_kw: 120.0
    pv_kw: 0.0
    import_price_chf_per_kwh: 0.18
    export_price_chf_per_kwh: 0.07
  - ts: "2025-01-01T00:15:00+01:00"
    load_kw: 110.0
    pv_kw: 0.0
    import_price_chf_per_kwh: 0.18
    export_price_chf_per_kwh: 0.07
    
B) Externes CSV als Quelle (empfohlen)
timeseries_csv:
  path: "data/site_2025_timeseries.csv"
  datetime_col: "ts"
  columns:
    load_kw: "load_kw"
    pv_kw: "pv_kw"
    import_price: "import_price_chf_per_kwh"
    export_price: "export_price_chf_per_kwh"
Wichtig bei Jahresdaten:

•	konstantes Zeitraster (z. B. 15 min)
•	keine Lücken / Duplikate
•	konsistente Zeitzone (DST sauber behandelt)





3) Site-/Tarif-Parameter


Typische Parameter:
site:
  timezone: "Europe/Zurich"
  timestep_minutes: 15

grid:
  import_limit_kw: 500.0        # optional: Anschlusslimit
  export_limit_kw: 500.0        # optional: Einspeiselimit
Preissignale:

•	import_chf_per_kWh: Kosten für Netzbezug
•	feed_in_chf_per_kWh: Vergütung für Einspeisung





4) Batterie-/Inverter-Parameter

battery:
  capacity_kwh: 500.0
  soc0: 250.0
  soc_min: 50.0
  soc_max: 500.0

  p_charge_kw: 250.0
  p_discharge_kw: 250.0

  roundtrip_eff: 0.92


Hinweise:

•	Achte auf sinnvolle soc0 (Start-SOC)
•	Für Jahresläufe sind oft sinnvolle Endbedingungen wichtig (z. B. End-SOC ≈ Start-SOC), um „Jahresrand-Effekte“ zu vermeiden.





5) Peak-Shaving / Demand Charge


Demand Charges werden als Kosten auf den maximalen Netzbezug in einem Monat modelliert.

Beispiel:
demand_tariff:
  enabled: true
  basis: monthly                # monthly / weekly / daily (je nach Tarif)
  charge_chf_per_kW: 12.0            # CHF pro kW Peak in der Periode
  allow_grid_charging: true         # relevant: Netzbezug (Import)
Interpretation:

•	Für jeden Abrechnungsblock wird eine Peak-Variable eingeführt:

•	peak_month_m >= import_kw[t] für alle t im Monat

•	Kosten: sum_m price * peak_month_m





6) Einspeisevergütung mit Cap (Cap auf vergütete Einspeiseleistung)


•	Einspeisung über cap_kw wird nicht (oder geringer) vergütet.

remuneration:
  paid_feed_in_cap_kW: 30.0

LP-taugliche Modellierung:

•	splitte Export in zwei Flüsse:

o	export_paid_kw <= cap_kw
o	export_spill_kw >= 0
o	export_total_kw = export_paid_kw + export_spill_kw
	




7) Solver-Optionen


Im CLI wird der Solver als String angegeben, z. B.:
--solver CBC


Allgemeine Hinweise:

•	CBC: gute Default-Wahl, frei verfügbar
• HiGHS: kann deutlich schneller sein (empfohlen)
• GLPK: Fallback





Mathematisches Modell (Konzept)


Das folgende ist eine konzeptuelle Beschreibung des LP-Modells. Die konkrete Implementierung kann je nach Repo-Stand leicht variieren.


Entscheidungsvariablen


Für jeden Zeitschritt t:

•	import_kw[t] ≥ 0  (Netzbezug)
•	export_kw[t] ≥ 0  (Netzeinspeisung)
•	charge_kw[t] ≥ 0  (Batterie laden)
•	discharge_kw[t] ≥ 0 (Batterie entladen)
•	soc_kwh[t] (State of Charge)


Optional:

•	export_paid_kw[t], export_spill_kw[t] (für Cap)
•	peak_p je Periode p (Demand Charge Peak)



Nebenbedingungen


(1) Energiebilanz (Leistung)
Typisch:

pv_kw[t] + import_kw[t] + discharge_kw[t] = load_kw[t] + export_kw[t] + charge_kw[t]

(2) SOC-Dynamik
Mit Zeitschritt Δh:

soc[t+1] = soc[t] + (eta_charge * charge_kw[t] - (1/eta_discharge) * discharge_kw[t]) * Δh

(3) SOC-Grenzen
soc_min ≤ soc[t] ≤ soc_max

(4) Leistungsgrenzen
0 ≤ charge_kw[t] ≤ max_charge_kw
0 ≤ discharge_kw[t] ≤ max_discharge_kw

Optional:

•	import_kw[t] ≤ import_limit_kw
•	export_kw[t] ≤ export_limit_kw


(5) Demand Charge Peak
Für Periode p:

peak[p] ≥ import_kw[t]  für alle t ∈ p

(6) Export-Cap
Z. B. Leistungs-Cap:

export_paid_kw[t] ≤ cap_kw
export_kw[t] = export_paid_kw[t] + export_spill_kw[t]




Zielfunktion


Minimiere:

•	Energiebezugskosten: Σ_t import_kw[t] * import_price[t] * Δh
•	minus Einspeiseerlöse: - Σ_t export_paid_kw[t] * export_price[t] * Δh
•	plus Demand Charges: Σ_p peak[p] * dc_price[p]
•	plus optionale Regularisierung: Σ_t (charge_kw[t] + discharge_kw[t]) * throughput_penalty * Δh






Outputs



HTML-Report


--report-html out/report.html erzeugt einen HTML-Report. 

Typischer Inhalt (je nach Implementierung):

•	Kennzahlen: Importkosten, Exporterlöse, Demand Charges, Gesamt
•	Peak-Vergleich: vorher/nachher
•	Plot/Tabellen: SOC, Import/Export, Charge/Discharge
•	ggf. Monats-/Quartalsaggregation



CSV-Zeitreihe


--series-csv out/series.csv schreibt die Zeitreihen als CSV. 

Übliche Spalten:

•	timestamp
•	load_kw, pv_kw
•	import_kw, export_kw
•	charge_kw, discharge_kw
•	soc_kwh
•	ggf. export_paid_kw/export_spill_kw
•	ggf. period_peak / peak_binding (modellabhängig)





Tipps zur Datenqualität

Orientierung an Beispieldaten

1.	Einheiten konsequent halten (kW für Leistung, kWh für Energie, CHF/kWh für Arbeitspreise)

2.	Zeitstempel (ideal: Sekundenschritte oder ISO 8601 mit Zeitzone, DST-Umstellung sauber oder in UTC rechnen)

3.	Negativwerte vermeiden

4.	Spalten Bennenung ( #Zeit [s] ; Verbrauch [kWh oder kW])

5.	csv Format ist präferiert, excel funktioniert auch

6.	Plausibilitätschecks (Plots im Output)






Performance & Skalierung


Ein Jahresmodell kann leicht zehntausende Zeitschritte haben. LP ist dafür gut geeignet, aber:

•	Achte auf effizientes I/O (CSV statt Inline-YAML für große Zeitreihen)
•	Bei 15-min Raster: 35’040 Schritte/Jahr
•	Solverwahl kann Unterschied machen





Reproduzierbarkeit


Empfohlen:

•	Python-Version fixieren
•	Dependencies pinnen (z. B. requirements.lock)
•	Solver-Version dokumentieren
•	Konfiguration + Input-Zeitreihe versionieren









Entwicklung


Typischer Workflow:

# venv aktivieren
```bash
pip install -r requirements.txt #oder pip install e .
```
# Gegebenenfalls fehlende packages installieren

# Run lokal
```bash
python -m battopt_lp.cli.optimize_year \
  --config configs/site_timeseries.yaml \
  --report-html out/report.html \
  --series-csv out/series.csv \
  --solver CBC
```
 






Projekt ergänzen:

1.	Fork erstellen
2.	Feature-Branch
3.	PR mit kurzer Beschreibung + Beispielrun (Report/CSV)








Kurzfassung (für „Ich will nur laufen lassen“)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m battopt_lp.cli.optimize_year \
  --config configs/site_timeseries.yaml \
  --report-html out/report.html \
  --series-csv out/series.csv \
  --solver CBC
```
---
