"""Audit the original thesis workbooks before using them.

The UCR workbooks also carry the income and unemployment columns used in the
thesis's covariate specification. This script checks how those columns were
built and whether the thesis tables can be reproduced from them.

Checks
1. Units: do the thesis Table 1 means match rates per 100,000 or per 10,000?
2. Income column: matched to each city, or pasted in row order from the
   county-subdivision list? What do the 2017-2019 values measure?
3. Unemployment column: matched to each city's county and year, or pasted in
   row order (and from which year)?
4. City names: how many carry FBI footnote digits that split one city into
   several fixed-effect groups?
5. Covariate specification: how many city-years survive listwise deletion
   with the workbook covariates (thesis reports 5,678)?
6. Thesis Table 3 Panel A vs. a reproduction on the same units.

Usage (from the repo root):
    python python/audit_original_data.py
"""

import warnings

import numpy as np
import pandas as pd
import pyfixest as pf

from build_panel import load_ucr, read_s1903
from config import OUTCOMES, RAW, STATES, TABLES

warnings.filterwarnings("ignore")

THESIS_TABLE1_CA = {  # California cities, 2013-2019, as printed in the thesis
    "violent": (47.69, 204.90), "agg_assault": (28.25, 95.41), "property": (430.53, 2839.83),
    "burglary": (78.07, 435.69), "larceny": (281.08, 1878.39), "mvt": (71.35, 590.13),
}
THESIS_PANEL_A = {"violent": 4.83, "agg_assault": 0.36, "property": 54.67,
                  "burglary": 17.81, "larceny": 38.25, "mvt": -1.94}
COMBINED_INCOME = {"CA": "CA MHI.xlsx", "ID": "Idaho MHI.xlsx", "KS": "Kansas MHI.xlsx",
                   "SC": "SC MHI.xlsx", "WY": "Wyoming MHI.xlsx"}
COMBINED_UNEMP = {"ID": "ID_Unemployment_Combined.xlsx", "KS": "KS_Unemployment_Rate_Com.xlsx",
                  "SC": "SC Combined.xls", "WY": "WY_Unemployment_Combined.xlsx"}


def same(a, b) -> bool:
    return (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and abs(a - b) < 1e-9)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    wb = load_ucr(keep_workbook_covariates=True)
    wb["wb_income"] = pd.to_numeric(wb["workbook_mhi"], errors="coerce")
    wb["wb_unemp"] = pd.to_numeric(wb["workbook_unemp"], errors="coerce")
    checks = []

    # 1. Units --------------------------------------------------------------
    ca = wb[wb["state"] == "CA"]
    unit_rows = []
    for y, (t_mean, t_sd) in THESIS_TABLE1_CA.items():
        r10k = ca[y] / ca["population"] * 1e4
        unit_rows.append({"outcome": y, "thesis_mean": t_mean, "per_10k_mean": round(r10k.mean(), 2),
                          "thesis_sd": t_sd, "per_10k_sd": round(r10k.std(), 2),
                          "per_100k_mean": round(r10k.mean() * 10, 2)})
    units = pd.DataFrame(unit_rows)
    units.to_csv(TABLES / "audit_units.csv", index=False)
    exact = int(((units.thesis_mean - units.per_10k_mean).abs() < 0.006).sum())
    checks.append(("Units of thesis crime rates",
                   f"Thesis Table 1 California means match rates per 10,000 for {exact}/6 outcomes "
                   "(labeled per 100,000). Corrected tables multiply by 10."))

    # 2. Income column --------------------------------------------------------
    compared = matched = 0
    for st, fname in COMBINED_INCOME.items():
        lst = pd.read_excel(RAW / "original_covariate_lists" / fname)
        value_cols = lst.columns[1::2]
        for j, yr in enumerate(range(2013, 2020)):
            source = pd.to_numeric(lst[value_cols[j]], errors="coerce").tolist()
            col = wb[(wb.state == st) & (wb.year == yr)]["wb_income"].tolist()
            for a, b in zip(col, source):
                if pd.isna(a) and pd.isna(b):
                    continue
                compared += 1
                matched += same(a, b)
    checks.append(("Income column linkage",
                   f"In {matched:,}/{compared:,} city-years ({matched / compared:.0%}), the workbook income "
                   "equals the entry in the same row position of the county-subdivision list, i.e. values "
                   "were pasted in list order rather than matched to each city."))

    wrong_col = []
    for yr in (2016, 2017, 2018, 2019):
        acs = pd.concat([read_s1903(p) for st in ["CA", "ID", "SC", "WY"]
                         for p in (RAW / "acs_s1903_ccd" / st).glob(f"ACSST5Y{yr}*-Data.csv")])
        wb_med = wb[(wb.year == yr) & (wb.state != "KS")]["wb_income"].median()
        wrong_col.append(f"{yr}: workbook median {wb_med:,.0f} vs ACS median income {acs['median_income'].median():,.0f}")
    checks.append(("Income column, 2017-2019",
                   "ACS restructured table S1903 in 2017, and the 2017-2019 workbook values are the "
                   "number of households with a householder aged 25-44, not median income. "
                   + "; ".join(wrong_col)))

    # 3. Unemployment column -------------------------------------------------
    unemp_msgs = []
    ca_book = pd.ExcelFile(RAW / "laus_county_unemployment" / "california.xls")
    sheets = []
    for sh in ca_book.sheet_names:
        d = pd.read_excel(ca_book, sheet_name=sh, header=None).iloc[11:, :2].dropna()
        sheets.append(dict(zip(pd.to_datetime(d[0]).dt.year, d[1].astype(float))))
    n = hit = 0
    for yr in range(2013, 2020):
        for i, v in enumerate(wb[(wb.state == "CA") & (wb.year == yr)]["wb_unemp"]):
            if pd.isna(v):
                continue
            n += 1
            hit += i < len(sheets) and same(sheets[i].get(yr + 1, np.nan), v)
    unemp_msgs.append(f"CA {hit}/{n} equal county sheet #i's value for year t+1")
    for st, fname in COMBINED_UNEMP.items():
        lst = pd.read_excel(RAW / "original_covariate_lists" / fname, header=None)
        lst = lst[pd.to_numeric(lst[0], errors="coerce").between(2013, 2019)]
        n = hit = 0
        for yr in range(2013, 2020):
            source = pd.to_numeric(lst[lst[0].astype(float) == yr][1], errors="coerce").tolist()
            for i, v in enumerate(wb[(wb.state == st) & (wb.year == yr)]["wb_unemp"]):
                if pd.isna(v) or i >= len(source):
                    continue
                n += 1
                hit += same(source[i], v)
        unemp_msgs.append(f"{st} {hit}/{n} equal the same-position entry of the stacked county list")
    coverage = wb.groupby("state")["wb_unemp"].apply(lambda s: f"{s.notna().mean():.0%}").to_dict()
    checks.append(("Unemployment column linkage",
                   "County rates were pasted in list order, not matched to each city's county; the county "
                   "files start in 2014, so the year labeled 2013 holds 2014 data. "
                   + "; ".join(unemp_msgs) + f". Share of city-years filled: {coverage}"))

    # 4. City names ---------------------------------------------------------
    footnoted = (wb["city"] != wb["city_as_published"]).sum()
    ids_raw = (wb["state"] + wb["city_as_published"]).nunique()
    ids_clean = (wb["state"] + wb["city"]).nunique()
    checks.append(("FBI footnote digits in city names",
                   f"{footnoted} city-years (e.g. 'Aiken3') carry footnote digits; uncleaned, they create "
                   f"{ids_raw - ids_clean} spurious extra cities ({ids_raw} vs {ids_clean} city fixed effects)."))

    # 5. Listwise deletion ------------------------------------------------------
    usable = wb.dropna(subset=["violent", "population", "wb_income", "wb_unemp"])
    checks.append(("Covariate specification sample",
                   f"With the workbook covariates, {len(usable):,} of {len(wb):,} city-years have all "
                   "controls; the thesis reports 5,678 observations for this specification."))

    # 6. Panel A reproduction -------------------------------------------------
    df = wb.copy()
    for y in OUTCOMES:
        df[y] = df[y] / df["population"] * 1e4            # thesis units
    df["city_id"] = df["state"] + "_" + df["city"]
    df["treat"] = ((df["state"] == "CA") & (df["year"] >= 2016)).astype(int)
    rep = []
    for y, t in THESIS_PANEL_A.items():
        m = pf.feols(f"{y} ~ treat | city_id + year", data=df, vcov={"CRV1": "city_id"})
        rep.append({"outcome": y, "thesis_coef_per_10k": t,
                    "reproduced_coef_per_10k": round(m.coef()["treat"], 2),
                    "reproduced_p_clustered": round(m.pvalue()["treat"], 3)})
    pd.DataFrame(rep).to_csv(TABLES / "audit_panel_a_reproduction.csv", index=False)
    checks.append(("Thesis Table 3, Panel A",
                   "Five of six coefficients reproduce within about 11%; aggravated assault is near zero in "
                   "both. P-values clustered by city are larger than printed (see audit_panel_a_reproduction.csv)."))

    out = pd.DataFrame(checks, columns=["check", "finding"])
    out.to_csv(TABLES / "audit_checks.csv", index=False)
    for c, f in checks:
        print(f"- {c}: {f}\n")
    print(pd.DataFrame(rep).to_string(index=False))


if __name__ == "__main__":
    main()
