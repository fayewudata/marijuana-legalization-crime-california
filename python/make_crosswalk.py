"""Build data/external/city_county_crosswalk.csv.

Each UCR city is assigned to its county so that county-level covariates
(unemployment, income) can be merged by name instead of by row position.

Source: the public "USA-cities-and-states" city/county list
(github.com/grammakov/USA-cities-and-states), matched on a normalized city
name within state. Cities that match no county, or more than one county,
are resolved with the manual overrides below (principal county).

Usage (from the repo root):
    python python/make_crosswalk.py
"""

import re

import pandas as pd

from config import EXTERNAL
from build_panel import load_ucr

SOURCE_URL = (
    "https://raw.githubusercontent.com/grammakov/USA-cities-and-states/"
    "master/us_cities_states_counties.csv"
)

# Principal county for cities that are ambiguous or missing in the source list.
MANUAL_COUNTIES = {
    ("CA", "Agoura Hills"): "Los Angeles", ("CA", "American Canyon"): "Napa",
    ("CA", "Bishop"): "Inyo", ("CA", "Blythe"): "Riverside",
    ("CA", "Broadmoor"): "San Mateo", ("CA", "Central Marin"): "Marin",
    ("CA", "City of Angels"): "Calaveras", ("CA", "Corcoran"): "Kings",
    ("CA", "Folsom"): "Sacramento", ("CA", "Industry"): "Los Angeles",
    ("CA", "Lake Shastina"): "Siskiyou", ("CA", "Los Gatos"): "Santa Clara",
    ("CA", "Oroville"): "Butte", ("CA", "Riverbank"): "Stanislaus",
    ("CA", "San Francisco"): "San Francisco", ("CA", "Vallejo"): "Solano",
    ("ID", "Challis"): "Custer", ("ID", "Pocatello"): "Bannock",
    ("KS", "Basehor"): "Leavenworth", ("KS", "Grandview Plaza"): "Geary",
    ("SC", "Briarcliffe Acres"): "Horry", ("SC", "Charleston"): "Charleston",
    ("SC", "Columbia"): "Richland", ("SC", "Fort Mill"): "York",
    ("SC", "North Charleston"): "Charleston", ("SC", "West Pelzer"): "Anderson",
    ("WY", "Casper"): "Natrona", ("WY", "Rawlins"): "Carbon",
    ("WY", "Worland"): "Washakie",
}


def name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", str(name).lower().replace("saint", "st"))


def main() -> None:
    src = pd.read_csv(SOURCE_URL, sep="|")
    src = src[src["State short"].isin({s for s, _ in MANUAL_COUNTIES})].dropna(subset=["County"])
    long = pd.concat([
        src.assign(key=src["City"].map(name_key)),
        src.assign(key=src["City alias"].map(name_key)),
    ])
    counts = (
        long.groupby(["State short", "key", "County"]).size()
        .rename("n").reset_index()
    )
    n_counties = counts.groupby(["State short", "key"])["County"].transform("nunique")
    modal = counts.sort_values("n", ascending=False).drop_duplicates(["State short", "key"])
    modal = modal.merge(
        counts.assign(n_counties=n_counties)[["State short", "key", "n_counties"]].drop_duplicates(),
        on=["State short", "key"],
    )

    cities = load_ucr()[["state", "city"]].drop_duplicates()
    cities["key"] = cities["city"].map(name_key)
    xw = cities.merge(
        modal.rename(columns={"State short": "state", "County": "county"})[["state", "key", "county", "n_counties"]],
        on=["state", "key"], how="left",
    )
    xw["county"] = xw["county"].str.title()
    xw["match_method"] = xw["n_counties"].map(lambda n: "unique_name_match" if n == 1 else "modal_county")

    for (state, city), county in MANUAL_COUNTIES.items():
        mask = (xw["state"] == state) & (xw["city"] == city)
        xw.loc[mask, ["county", "match_method"]] = [county, "manual"]
    xw.loc[xw["county"].isna(), "match_method"] = "unmatched"

    out = xw[["state", "city", "county", "match_method"]].sort_values(["state", "city"])
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    out.to_csv(EXTERNAL / "city_county_crosswalk.csv", index=False)
    print(out["match_method"].value_counts().to_string())
    leftover = out[out["match_method"] == "modal_county"]
    if len(leftover):
        print("\nAmbiguous names resolved by modal county (review these):")
        print(leftover.to_string(index=False))


if __name__ == "__main__":
    main()
