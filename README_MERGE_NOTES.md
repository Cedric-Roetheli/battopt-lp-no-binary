# battopt_lp – LP-only (no binaries) + rich report
Date: 2025-09-22

This package is based on `option4_battopt_lp-main` (clean minimal project),
with the richer HTML report copied from `option4_battopt_lp (3)`.

## Key points
- **No binary/integer variables**: monthly and annual demand charges are modeled with continuous peak variables.
- **Reporting**: uses the larger project's `battopt_lp/reporting/html_report.py` for a richer HTML output.
- **CLI**: unchanged from the clean project. Run the optimizer via:
  ```bash
  python -m battopt_lp.cli.optimize_year --config <your.yaml> --report-html report.html --series-csv series.csv --solver CBC
  ```

If you want time limits / threads: set solver to `HiGHS` in CLI and adapt model if needed.
