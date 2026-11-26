# Ride Share Cost Splitter

Split a shared ride fairly: equal, weighted shares, percentages or fixed amounts.
Terminal app (zero dependencies) plus a NiceGUI web interface. Data is saved to `data/rides.json`.

## Run

```bash
python cli.py                 # terminal menu, standard library only

pip install -r requirements.txt
python app_gui.py             # web UI at http://localhost:8080
```

Python 3.10+. `data/rides.json` ships with 42 demo rides. Delete it to start empty, or run `python seed.py --install` to regenerate the demo data.

## Why the maths is exact
Money is stored as integer cents and split with the largest-remainder method, so shares always add up to the total
(₹100 three ways is 33.33 + 33.33 + 33.34, never 99.99).

## Layout
- `core/` split engine, validation, JSON storage with corruption recovery, search, summary, exporter, CSV importer
- `cli.py` terminal menu  ·  `app_gui.py` NiceGUI interface
- `data/` sample rides (CSV and JSON) and `sample_bad.csv` for the import error-log demo
- `tests/` run with `python -m unittest discover -s tests -t .`

## Split modes
| Mode | Input per passenger |
|---|---|
| equal | none |
| weighted | shares, e.g. 2 |
| percent | percent, must total 100 |
| fixed | amount; leave one blank so that person covers the rest |

## CSV import format
`date,route,category,fare,extras,split_mode,payer,passengers,settled,notes`, where passengers look like `Asha:2;Ben:1` (value after the colon is optional) and settled is `Ben;Chitra`.

## Demo script
1. Launch and show the welcome screen / header.
2. New ride: enter fare `-5`, then `abc`, and watch validation catch it. Enter `300` with a weighted split.
3. Summary tab: KPIs, monthly chart, warnings.
4. Import / Export: upload `data/sample_bad.csv` to show the row-by-row error log.
5. Close and relaunch to show the data persisted. Export the Markdown report.

## Resilience
Delete or corrupt `data/rides.json`: the app recreates it, and a corrupt file is kept as `rides.corrupt-<time>.json`.
