# Option 4 – Battery LP Optimizer (EV + Peak Shaving)

Jahres-LP (linear, ohne Binärvariablen) zur gleichzeitigen Optimierung von Eigenverbrauch, Peak Shaving (Demand Charges) und Einspeisevergütung mit Cap.

## Installation
```bash
python -m venv .venv
# Windows: . .venv/Scripts/activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
python -m battopt_lp.cli.optimize_year       --config configs/site_timeseries.yaml       --report-html reports/site_2024_opt.html       --series-csv reports/site_2024_opt.csv
```

## YAML (Beispiel)
Siehe `configs/site_timeseries.yaml`.
