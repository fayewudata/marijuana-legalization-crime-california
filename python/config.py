"""Paths and constants shared by every Python script."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EXTERNAL = ROOT / "data" / "external"
# The main pipeline is in R/. This Python implementation is an independent
# cross-check and writes to its own folders so the two never overwrite each other.
PROCESSED = ROOT / "data" / "processed" / "python"
TABLES = ROOT / "outputs" / "python" / "tables"
FIGURES = ROOT / "outputs" / "python" / "figures"

STATES = {
    "CA": "california",
    "ID": "idaho",
    "KS": "kansas",
    "SC": "south_carolina",
    "WY": "wyoming",
}
TREATED_STATE = "CA"
YEARS = list(range(2013, 2020))
POST_START = 2016          # thesis coding: 2016-2019 = post-legalization
RETAIL_START = 2018        # licensed recreational retail opened Jan 1, 2018
EVENT_REFERENCE_YEAR = 2015

OUTCOMES = {
    "violent": "Violent crime",
    "agg_assault": "Aggravated assault",
    "property": "Property crime",
    "burglary": "Burglary",
    "larceny": "Larceny-theft",
    "mvt": "Motor vehicle theft",
}
RATE_PER = 100_000         # all corrected rates are per 100,000 residents
