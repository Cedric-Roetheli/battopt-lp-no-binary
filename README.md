
# Battery LP Optimizer (EV + Peak Shaving)

**Jahres-LP (linear, ohne Binärvariablen)** zur gleichzeitigen Optimierung von:

- **Eigenverbrauch** (PV → Last/Batterie, weniger Netzbezug)
- **Peak Shaving** / **Demand Charges** (Reduktion von Lastspitzen)
- **Einspeisevergütung mit Cap** (Exportvergütung begrenzt / gekappt)

Das Projekt löst eine lineare Optimierung über ein ganzes Jahr (oder generell lange Zeitreihen) – explizit ohne Binärvariablen, um robust und schnell auf Standard-LP-Solvern (z. B. CBC) laufen zu können.

---

## Inhaltsverzeichnis

- [Motivation & Zielsetzung](#motivation--zielsetzung)
- [Was bedeutet „LP ohne Binärvariablen“?](#was-bedeutet-lp-ohne-binärvariablen)
- [Funktionsumfang](#funktionsumfang)
- [Projektstruktur](#projektstruktur)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [CLIENT](#cli)
- [Konfiguration (YAML)](#konfiguration-yaml)
  - [1) Überblick](#1-überblick)
  - [2) Zeitreihen-Format](#2-zeitreihen-format)
  - [3) Beispiel](#3-beispiel)
  - [4) Solver-Optionen](#4-solver-optionen)
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
- [eniwa_EV_LSK_tool_v4_onefile.exe](#eniwa-EV-LSK-tool-v4-onefile)
- [Entwicklung](#entwicklung)

---

## Motivation & Zielsetzung

Energie-Optimierung im Gebäude-/Site-Kontext hat typischerweise mehrere (teils konkurrierende) Ziele:

1. **Kosten minimieren:** Netzbezug reduzieren (Eigenverbrauch erhöhen)
2. **Lastspitzen vermeiden** (Demand Charges).
3. **Erlöse maximieren:** Einspeisung kann vergütet werden – jedoch oft mit **Cap** (z. B. ab einer gewissen Einspeiseleistung oder Energiemenge sinkt/endet die Vergütung).
4. **Technische Restriktionen einhalten:** Batteriekapazität, Lade-/Entladeleistung, Wirkungsgrade, SOC-Grenzen, ggf. Netzanschlusslimit.

Dieses Projekt richtet sich auf einen Jahreshorizont (oder allgemein lange Zeitreihen) und nutzt ein lineares Programm (LP), um eine global konsistente Lösung über den gesamten Zeitraum zu finden. 

---

## Was bedeutet „LP ohne Binärvariablen“?

Viele Batteriemodelle verwenden Binärvariablen, um z. B. **gleichzeitiges Laden und Entladen** strikt zu verhindern (`charge_on ∈ {0,1}` etc.). Das macht das Problem zu einem **MIP/MILP** und kann bei Jahreshorizonten (viele Zeitschritte!) schnell sehr langsam werden.

Dieses Projekt bleibt bewusst bei einem **LP**:
- schnellere Solve-Zeiten
- bessere Skalierbarkeit (365 Tage × 96 Viertelstunden = 35’040 Schritte)
- robust auf frei verfügbaren Solvern (z. B. CBC)


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

Top-Level:
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

Tipp: Für reproduzierbare Ergebnisse empfiehlt sich zusätzlich das Pinning von Solver-Versionen und Python-Version (z. B. via python==3.11.*).

---


## Quickstart


Minimaler Run mit Beispielkonfiguration:
```bash
python -m battopt_lp.cli.optimize_year \
  --config configs/site_timeseries.yaml \
  --report-html out/report.html \
  --series-csv out/series.csv \
  --solver CBC
```
Genau dieses Kommando (inkl. Parameter) ist im Repo als „Run“ dokumentiert. 

---

## CLI: 
**battopt_lp.cli.optimize_year**

Zweck

- Lädt eine YAML-Konfiguration mit Site-/Tarif-/Batterie-Parametern und Zeitreihen
- Baut das LP-Modell
- Löst es mit dem angegebenen Solver
- Schreibt:
`--report-html` … (HTML-Report)
`--series-csv` … (Zeitreihen als CSV)	



Parameter



`--config`	Pfad zur YAML-Konfiguration	Bsp. configs/site_timeseries.yaml

`--report-html`	Output-Pfad für HTML-Report Bsp. out/report.html

`--series-csv`	Output-Pfad für CSV-Zeitreihe Bsp. out/series.csv

`--solver`	Solver-Backend (String) Bsp. CBC


---


## Konfiguration (YAML)



### 1) Überblick


Die zentrale Konfiguration ist eine YAML-Datei (Beispiel):

- configs/site_timeseries.yaml  


Sie enthält typischerweise:

- Metadaten (Zeitzone, Zeitschritt)
- Zeitreihen (Load, PV, Preise, ggf. Exportpreise)
- Batterie- und Netzparameter
- Demand-Charge-/Peak-Shaving-Settings
- Exportvergütung inkl. Cap
- Solver-/Report-Optionen (optional)



---


### 2) Zeitreihen-Format


Zeitreihen in einem der folgenden Formate:

A) Inline in YAML (nicht empfohlen)

		timeseries:
		
			ts: "2025-01-01T00:00:00+01:00"
    		load_kw: 120.0
    		pv_kw: 0.0
    		import_price_chf_per_kwh: 0.18
    		export_price_chf_per_kwh: 0.07

			
			ts: "2025-01-01T00:15:00+01:00"
			load_kw: 110.0
    		pv_kw: 0.0
    		import_price_chf_per_kwh: 0.18
    		export_price_chf_per_kwh: 0.07
			
    
B) Externes CSV als Quelle (empfohlen)

		timeseries:
 			consumption_csv: "data/filename"
 			pv_csv: "data/filename"
  			datetime_col: "ts"
			
  		columns:
    		load_kw: "load_kw"
    		pv_kw: "pv_kw"
    		import_price: "import_price_chf_per_kwh"
    		export_price: "export_price_chf_per_kwh"
	
Wichtig bei Jahresdaten:

- konstantes Zeitraster (z. B. 15 min)
- keine Lücken / Duplikate
- konsistente Zeitzone (DST sauber behandelt)


---


### 3) Beispiel

```bash
timeseries:
  consumption_csv: data/2024_Gesamtverbrauch_HIHO_python.csv
  pv_csv:          data/2024_PV-Produktion_HIHO_python.csv
  step_seconds:    900
  start_datetime:  "2024-01-01T00:00:00"
  tz:              "Europe/Zurich"

energy_prices:
  import_chf_per_kWh: 0.19
  grid_chf_per_kWh:   0.19
  feed_in_chf_per_kWh: 0.06

demand_tariff:
  enabled: true
  basis: monthly
  charge_chf_per_kW: 12.0
  allow_grid_charging: true

storage:
  simulate:
    capacity_kwh:   64
    p_charge_kw:    30
    p_discharge_kw: 30
    roundtrip_eff:  0.92
    soc_min:        0.15
    soc_max:        0.95
    soc0:           0.50

remuneration:
  paid_feed_in_cap_kW: 30.0

economics:
  capex_battery_chf:       32000
  capex_installation_chf:   2000
  opex_annual_chf:             0
  lifetime_years:             15
  discount_rate_pct:           2
  subsidy_upfront_chf:         0
```


### 4) Solver-Optionen


Im CLI wird der Solver als String angegeben, 

z. B.: `--solver CBC`


Allgemeine Hinweise:

- CBC: gute Default-Wahl, frei verfügbar
- HiGHS: kann deutlich schneller sein (empfohlen)
- GLPK: Fallback


---


## Mathematisches Modell (Konzept)


Das folgende ist eine konzeptuelle Beschreibung des LP-Modells. Die konkrete Implementierung kann je nach Repo-Stand leicht variieren.
! Variabeln können im Code anders benannt sein !

---


### Entscheidungsvariablen


Für jeden Zeitschritt t:

- `import_kw[t]` ≥ 0  (Netzbezug)
- `export_kw[t]` ≥ 0  (Netzeinspeisung)
- `charge_kw[t]` ≥ 0  (Batterie laden)
- `discharge_kw[t]` ≥ 0 (Batterie entladen)
- `soc_kwh[t]` (State of Charge)


Optional:

- `export_paid_kw[t]`, `export_spill_kw[t]` (für Cap)
- `peak_p` je Periode p (Demand Charge Peak)

---

### Nebenbedingungen


#### (1) Energiebilanz (Leistung)
Typisch:

`pv_kw[t]` + `import_kw[t]` + `discharge_kw[t]` = `load_kw[t]` + `export_kw[t]` + `charge_kw[t]`

#### (2) SOC-Dynamik
Mit Zeitschritt Δh:

`soc[t+1]` = `soc[t]` + (`eta_charge` * `charge_kw[t]` - (1/`eta_discharge`) * `discharge_kw[t])` * `Δh`

#### (3) SOC-Grenzen
`soc_min` ≤ `soc[t]` ≤ `soc_max`

#### (4) Leistungsgrenzen
0 ≤ `charge_kw[t]` ≤ `max_charge_kw`

0 ≤ `discharge_kw[t]` ≤ `max_discharge_kw`

Optional:

- `import_kw[t]` ≤ `import_limit_kw`
- `export_kw[t]` ≤ `export_limit_kw`


#### (5) Demand Charge Peak
Für Periode p:

`peak[p]` ≥ `import_kw[t]`  für alle t ∈ p

#### (6) Export-Cap
Z. B. Leistungs-Cap:

`export_paid_kw[t]` ≤ `cap_kw`

`export_kw[t]` = `export_paid_kw[t]` + `export_spill_kw[t]`


---


### Zielfunktion


Minimiere:

- Energiebezugskosten: Σ_t `import_kw[t]` * `import_price[t]` * `Δh`
- minus Einspeiseerlöse: - Σ_t `export_paid_kw[t]` * `export_price[t]` * `Δh`
- plus Demand Charges: Σ_p `peak[p]` * `dc_price[p]`
- plus optionale Regularisierung: Σ_t (`charge_kw[t]` + `discharge_kw[t]`) * `throughput_penalty` * `Δh`



---


### Outputs



#### HTML-Report


`--report-html` out/report.html erzeugt einen HTML-Report. 

Typischer Inhalt (je nach Implementierung):

- Kennzahlen: Importkosten, Exporterlöse, Demand Charges, Gesamt
- Peak-Vergleich: vorher/nachher
- Plot/Tabellen: SOC, Import/Export, Charge/Discharge
- ggf. Monats-/Quartalsaggregation


---


#### CSV-Zeitreihe


`--series-csv` out/series.csv schreibt die Zeitreihen als CSV. 

Übliche Spalten:

- timestamp
- load_kw, pv_kw
- import_kw, export_kw
- charge_kw, discharge_kw
- soc_kwh
- ggf. export_paid_kw/export_spill_kw
- ggf. period_peak / peak_binding (modellabhängig)


---


### Tipps zur Datenqualität

Orientierung an Beispieldaten

1.	Einheiten konsequent halten (kW für Leistung, kWh für Energie, CHF/kWh für Arbeitspreise)

2.	Zeitstempel (ideal: Sekundenschritte oder ISO 8601 mit Zeitzone, DST-Umstellung sauber oder in UTC rechnen)

3.	Negativwerte vermeiden

4.	Spalten Bennenung ( #Zeit [s] ; Verbrauch [kWh oder kW])

5.	csv Format ist präferiert, excel funktioniert auch

6.	Plausibilitätschecks (Plots im Output)



---



### Performance & Skalierung


Ein Jahresmodell kann leicht zehntausende Zeitschritte haben. LP ist dafür gut geeignet, aber:

- Achte auf effizientes I/O (CSV statt Inline-YAML für große Zeitreihen)
- Bei 15-min Raster: 35’040 Schritte/Jahr
- Solverwahl kann Unterschied machen



---



### Reproduzierbarkeit


Empfohlen:

- Python-Version fixieren
- Dependencies pinnen (z. B. requirements.lock)
- Solver-Version dokumentieren
- Konfiguration + Input-Zeitreihe versionieren




---




## Entwicklung


Typischer Workflow:

### venv aktivieren
```bash
pip install -r requirements.txt #oder pip install e .
```

**Gegebenenfalls fehlende packages installieren**


### Run lokal
```bash
python -m battopt_lp.cli.optimize_year \
  --config configs/site_timeseries.yaml \
  --report-html out/report.html \
  --series-csv out/series.csv \
  --solver CBC
```
 


---



## Projekt ergänzen:

1.	Fork erstellen
2.	Feature-Branch
3.	PR mit kurzer Beschreibung + Beispielrun (Report/CSV)




---



## eniwa EV LSK tool v4 onefile

Das Programm eniwa_EV_LSK_tool_v4_onefile.exe basiert auf exakt diesem python programm (battopt-lp-no-binary).
Es wurde mit streamlit (https://streamlit.io/) erstellt. Für die Wiederholung einer Implementation mit Streamlit sind zusätzliche Schritte nötig.
Alle nötigen Schritte, files und packages sind auf der streamlit website dokumentiert. beide Programme haben dieselbe Funktionalität und Logik.
Einzig die Benutzeroberfläche verändert sich.




---


## Kurzfassung (für „Ich will nur laufen lassen“)
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
