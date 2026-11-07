"""Build the city-year analysis panel from the raw files.

Steps
1. Read the 35 UCR city sheets (5 states x 7 years) and standardize columns.
2. Clean city names: strip FBI footnote digits ("Aiken3" -> "Aiken") so each
   city keeps one identifier across years.
3. Convert counts to rates per 100,000 residents.
4. Merge county-level covariates BY NAME through a city-to-county crosswalk:
   - unemployment rate (BLS LAUS, annual county series, 2014-2020)
   - income proxy: household-weighted mean of ACS S1903 median household
     income (householder 25-44) across the county's census county
     subdivisions. Available for CA (2014-2019), ID, SC, WY; not Kansas.
5. Write data/processed/city_year_panel.csv and a data-quality log.

Usage (from the repo root):
    python python/build_panel.py
"""

import re
import warnings

import numpy as np
import pandas as pd

from config import EXTERNAL, OUTCOMES, PROCESSED, RATE_PER, RAW, STATES, TABLES, TREATED_STATE

warnings.filterwarnings("ignore", category=UserWarning)

UCR_COLUMNS = {
    "city": "city", "population": "population", "violent crime": "violent",
    "aggravated assault": "agg_assault", "property crime": "property",
    "burglary": "burglary", "larceny-theft": "larceny", "motor vehicle theft": "mvt",
    "state": "state_label", "mhi": "workbook_mhi",
    "median household income(25-44)": "workbook_mhi",
    "unemployment rate": "workbook_unemp",
}


def county_key(name: str) -> str:
    name = re.sub(r"\s+(County|Parish)$", "", str(name).split("/")[0].strip())
    return re.sub(r"[^a-z]", "", name.lower())


# ---------------------------------------------------------------- UCR crime data
def load_ucr(keep_workbook_covariates: bool = False) -> pd.DataFrame:
    frames = []
    for state, stem in STATES.items():
        path = RAW / "ucr_city_workbooks" / f"{stem}.xls"
        for sheet in pd.ExcelFile(path).sheet_names:
            df = pd.read_excel(path, sheet_name=sheet)
            df.columns = [
                UCR_COLUMNS.get(re.sub(r"\s+", " ", str(c)).strip().lower().replace("- ", "-"), c)
                for c in df.columns
            ]
            df["state"] = state
            df["year"] = int(sheet)
            frames.append(df)
    ucr = pd.concat(frames, ignore_index=True)

    # Drop blank rows and repeated header rows inside the sheets
    ucr = ucr[ucr["state_label"].astype(str).str.strip().isin(STATES)].copy()

    ucr["city_as_published"] = ucr["city"].astype(str).str.strip()
    ucr["city"] = ucr["city_as_published"].str.replace(r"[\d,]+$", "", regex=True).str.strip()

    for col in ["population", *OUTCOMES]:
        ucr[col] = pd.to_numeric(ucr[col], errors="coerce")   # e.g. a stray "v  m" -> NaN

    keep = ["state", "city", "city_as_published", "year", "population", *OUTCOMES]
    if keep_workbook_covariates:
        keep += ["workbook_mhi", "workbook_unemp"]
    return ucr[keep].reset_index(drop=True)


# ---------------------------------------------------------- county unemployment
def load_unemployment() -> pd.DataFrame:
    rows, skipped = [], []
    for state, stem in STATES.items():
        path = RAW / "laus_county_unemployment" / f"{stem}.xls"
        for sheet in pd.ExcelFile(path).sheet_names:
            df = pd.read_excel(path, sheet_name=sheet, header=None)
            title = str(df.iloc[7, 1]) if len(df) > 7 else ""
            match = re.search(r"Unemployment Rate in (.+?), ([A-Z]{2}),", title)
            if not match:
                skipped.append(f"{stem}.xls / {sheet}: no county identifier")
                continue
            start = df.index[df.iloc[:, 0].astype(str).str.strip() == "observation_date"][0] + 1
            for date, value in df.iloc[start:, :2].dropna().values:
                rows.append({
                    "state": state,
                    "county_key": county_key(match.group(1)),
                    "year": pd.Timestamp(date).year,
                    "unemp_rate": float(value),
                })
    unemp = pd.DataFrame(rows).drop_duplicates(["state", "county_key", "year"])
    return unemp, skipped


# ------------------------------------------------------------ county income proxy
def read_s1903(path) -> pd.DataFrame:
    first = pd.read_csv(path, nrows=1, header=None, encoding="utf-8-sig")
    header_row = 1 if str(first.iloc[0, 0]).strip() == "GEO_ID" else 0
    df = pd.read_csv(path, header=header_row, encoding="utf-8-sig", low_memory=False)
    name_col = "Geographic Area Name" if "Geographic Area Name" in df.columns else "NAME"

    def pick(*must):
        cols = [
            c for c in df.columns
            if "25 to 44" in c and all(m in c.lower() for m in must)
            and "margin of error" not in c.lower() and "moe" not in c.lower()
        ]
        assert len(cols) == 1, (path, must, cols)
        return cols[0]

    # Median income moved from column C02 (2013-2016) to C03 (2017+);
    # selecting by label instead of position avoids that trap.
    median_col = pick("median income (dollars)")
    households_col = pick("number") if any("Number" in c for c in df.columns) else pick("total")

    def to_num(s):
        return pd.to_numeric(
            s.astype(str).str.replace(",", "").str.replace(r"\+$|-$", "", regex=True),
            errors="coerce",
        )

    out = pd.DataFrame({
        "geo_name": df[name_col],
        "median_income": to_num(df[median_col]),
        "households": to_num(df[households_col]),
    })
    out["county_key"] = out["geo_name"].str.extract(r", (.+?) County,")[0].map(county_key)
    return out


def load_income_proxy() -> pd.DataFrame:
    rows = []
    for state in ["CA", "ID", "SC", "WY"]:
        for path in sorted((RAW / "acs_s1903_ccd" / state).glob("*-Data.csv")):
            year = int(re.search(r"ACSST5Y(\d{4})", path.name).group(1))
            ccd = read_s1903(path).dropna(subset=["median_income", "households"])
            ccd = ccd[ccd["households"] > 0]
            agg = (
                ccd.assign(w=ccd["median_income"] * ccd["households"])
                .groupby("county_key")[["w", "households"]].sum()
            )
            for key, r in agg.iterrows():
                rows.append({"state": state, "county_key": key, "year": year,
                             "county_income_proxy": r["w"] / r["households"]})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------- build
def build() -> pd.DataFrame:
    ucr = load_ucr()
    log = [f"UCR city-year rows after dropping blank/header rows: {len(ucr):,}"]
    renamed = (ucr["city"] != ucr["city_as_published"]).sum()
    log.append(f"City names with FBI footnote digits removed: {renamed}")
    dup = ucr.duplicated(["state", "city", "year"]).sum()
    assert dup == 0, f"{dup} duplicate city-years after cleaning"

    for col in OUTCOMES:
        ucr[col] = ucr[col] / ucr["population"] * RATE_PER
    ucr["treated_state"] = (ucr["state"] == TREATED_STATE).astype(int)

    xw = pd.read_csv(EXTERNAL / "city_county_crosswalk.csv")
    panel = ucr.merge(xw[["state", "city", "county"]], on=["state", "city"], how="left")
    panel["county_key"] = panel["county"].map(county_key)
    log.append(f"City-years without a county match: {panel['county'].isna().sum()}")

    unemp, skipped = load_unemployment()
    log += [f"Skipped unemployment sheet: {s}" for s in skipped]
    panel = panel.merge(unemp, on=["state", "county_key", "year"], how="left")

    income = load_income_proxy()
    panel = panel.merge(income, on=["state", "county_key", "year"], how="left")

    panel["city_id"] = panel["state"] + "_" + panel["city"]
    panel = panel.drop(columns="county_key").sort_values(["state", "city", "year"])

    PROCESSED.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PROCESSED / "city_year_panel.csv", index=False)

    coverage = (
        panel.assign(
            has_unemp=panel["unemp_rate"].notna(),
            has_income=panel["county_income_proxy"].notna(),
        )
        .groupby(["state", "year"])[["has_unemp", "has_income"]].mean().mul(100).round(1)
        .reset_index()
    )
    TABLES.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(TABLES / "covariate_coverage.csv", index=False)
    (TABLES / "build_log.txt").write_text("\n".join(log) + "\n")

    print("\n".join(log))
    print(f"\nPanel: {len(panel):,} city-years, {panel['city_id'].nunique():,} cities")
    print(coverage.pivot(index="state", columns="year", values="has_unemp").to_string())
    return panel


if __name__ == "__main__":
    build()
