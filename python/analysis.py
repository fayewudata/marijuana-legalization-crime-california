"""Estimate the effect of California's 2016 legalization on city crime rates.

Outputs (outputs/tables, outputs/figures)
- table1_summary_stats.csv       means and SDs by group and period
- table2_unadjusted_did.csv      2x2 difference in means
- table3_did_estimates.csv       two-way fixed-effects estimates, five specifications
- table4_possession_vs_retail.csv separate effects for 2016-17 and 2018-19
- event_study.csv / event_study.png   California x year coefficients (2015 = 0)
- trends.png                     population-weighted crime rates by group

All rates are per 100,000 residents. Standard errors are clustered by city.
With one treated state, clustered p-values likely overstate precision.

Usage (from the repo root, after python/build_panel.py):
    python python/analysis.py
"""

import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

from config import (EVENT_REFERENCE_YEAR, FIGURES, OUTCOMES, POST_START, PROCESSED,
                    RETAIL_START, TABLES, YEARS)

warnings.filterwarnings("ignore")


def load_panel() -> pd.DataFrame:
    p = pd.read_csv(PROCESSED / "city_year_panel.csv")
    p["post"] = (p["year"] >= POST_START).astype(int)
    p["treat"] = p["treated_state"] * p["post"]
    p["possession"] = (p["treated_state"].eq(1) & p["year"].between(POST_START, RETAIL_START - 1)).astype(int)
    p["retail"] = (p["treated_state"].eq(1) & (p["year"] >= RETAIL_START)).astype(int)
    p["population_10k"] = p["population"] / 1e4
    for yr in YEARS:
        if yr != EVENT_REFERENCE_YEAR:
            p[f"ca_{yr}"] = (p["treated_state"].eq(1) & p["year"].eq(yr)).astype(int)
    return p


def fit(formula: str, data: pd.DataFrame, weights=None):
    return pf.feols(formula, data=data, vcov={"CRV1": "city_id"}, weights=weights)


def summary_tables(p: pd.DataFrame) -> None:
    rows = []
    periods = {"2013-2019": p, "2013-2015": p[p.post == 0], "2016-2019": p[p.post == 1]}
    for period, d in periods.items():
        for group, g in d.groupby("treated_state"):
            for y, label in OUTCOMES.items():
                rows.append({"period": period, "group": "California" if group else "Control states",
                             "outcome": label, "n": int(g[y].count()),
                             "mean": round(g[y].mean(), 1), "sd": round(g[y].std(), 1)})
    pd.DataFrame(rows).to_csv(TABLES / "table1_summary_stats.csv", index=False)

    did = []
    for y, label in OUTCOMES.items():
        m = p.groupby(["treated_state", "post"])[y].mean()
        ca_change, ctrl_change = m[1, 1] - m[1, 0], m[0, 1] - m[0, 0]
        did.append({"outcome": label,
                    "ca_pre": round(m[1, 0], 1), "ca_post": round(m[1, 1], 1), "ca_change": round(ca_change, 1),
                    "control_pre": round(m[0, 0], 1), "control_post": round(m[0, 1], 1),
                    "control_change": round(ctrl_change, 1),
                    "difference": round(ca_change - ctrl_change, 1)})
    pd.DataFrame(did).to_csv(TABLES / "table2_unadjusted_did.csv", index=False)


def did_estimates(p: pd.DataFrame) -> pd.DataFrame:
    s = p[p["year"] >= 2014]   # county unemployment files start in 2014
    specs = [
        ("(1) City and year FE, 2013-2019", "treat", p, None),
        ("(2) City and year FE, 2014-2019", "treat", s, None),
        ("(3) + population, county unemployment", "treat + population_10k + unemp_rate", s, None),
        ("(4) + county income proxy (excl. Kansas)",
         "treat + population_10k + unemp_rate + county_income_proxy", s[s.state != "KS"], None),
        ("(5) City and year FE, population-weighted", "treat", p, "population"),
    ]
    pre = p[(p.treated_state == 1) & (p.post == 0)]
    rows = []
    for y, label in OUTCOMES.items():
        for name, rhs, data, w in specs:
            m = fit(f"{y} ~ {rhs} | city_id + year", data, w)
            b = m.coef()["treat"]
            rows.append({"outcome": label, "specification": name, "coef": round(b, 1),
                         "se": round(m.se()["treat"], 1), "p_value": round(m.pvalue()["treat"], 3),
                         "n": m._N, "pct_of_ca_pre_mean": round(100 * b / pre[y].mean(), 1)})
    out = pd.DataFrame(rows)
    out.to_csv(TABLES / "table3_did_estimates.csv", index=False)
    return out


def timing(p: pd.DataFrame) -> None:
    rows = []
    for y, label in OUTCOMES.items():
        m = fit(f"{y} ~ possession + retail | city_id + year", p)
        for term, period in [("possession", "2016-2017 (possession only)"), ("retail", "2018-2019 (retail sales)")]:
            rows.append({"outcome": label, "period": period, "coef": round(m.coef()[term], 1),
                         "se": round(m.se()[term], 1), "p_value": round(m.pvalue()[term], 3)})
    pd.DataFrame(rows).to_csv(TABLES / "table4_possession_vs_retail.csv", index=False)


def event_study(p: pd.DataFrame) -> pd.DataFrame:
    terms = [f"ca_{yr}" for yr in YEARS if yr != EVENT_REFERENCE_YEAR]
    rows = []
    for y, label in OUTCOMES.items():
        for weighting, w in [("unweighted", None), ("population-weighted", "population")]:
            m = fit(f"{y} ~ {' + '.join(terms)} | city_id + year", p, w)
            ci = m.confint()
            for yr in YEARS:
                t = f"ca_{yr}"
                is_ref = yr == EVENT_REFERENCE_YEAR
                rows.append({"outcome": label, "weighting": weighting, "year": yr,
                             "coef": 0.0 if is_ref else m.coef()[t],
                             "ci_low": 0.0 if is_ref else ci.loc[t].iloc[0],
                             "ci_high": 0.0 if is_ref else ci.loc[t].iloc[1],
                             "p_value": np.nan if is_ref else m.pvalue()[t]})
    es = pd.DataFrame(rows)
    es.round(3).to_csv(TABLES / "event_study.csv", index=False)

    fig, axes = plt.subplots(2, 3, figsize=(13, 7), sharex=True)
    for ax, label in zip(axes.flat, OUTCOMES.values()):
        for (weighting, d), offset, marker in zip(es[es.outcome == label].groupby("weighting", sort=False),
                                                  (-0.08, 0.08), ("o", "s")):
            ax.errorbar(d.year + offset, d.coef, yerr=[d.coef - d.ci_low, d.ci_high - d.coef],
                        fmt=marker, capsize=3, markersize=4, label=weighting)
        ax.axhline(0, color="grey", linewidth=0.8)
        ax.axvline(POST_START - 0.5, color="grey", linestyle="--", linewidth=0.8)
        ax.set_title(label)
        ax.set_xticks(YEARS)
        ax.tick_params(axis="x", rotation=45)
    axes[0, 0].legend(fontsize=8, loc="upper left")
    fig.supylabel(f"California vs. control, per 100,000 (relative to {EVENT_REFERENCE_YEAR})")
    fig.suptitle("Event Study: Did California Diverge Before Legalization?")
    fig.tight_layout()
    fig.savefig(FIGURES / "event_study.png", dpi=150)
    plt.close(fig)
    return es


def trends(p: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, y in zip(axes, ["violent", "property", "larceny"]):
        for group, label in [(1, "California"), (0, "Control states")]:
            g = p[p.treated_state == group].dropna(subset=[y])
            series = g.groupby("year").apply(lambda d: np.average(d[y], weights=d["population"]))
            ax.plot(series.index, series.values, marker="o", label=label)
        ax.axvline(POST_START - 0.5, color="grey", linestyle="--", linewidth=0.8)
        ax.set_title(OUTCOMES[y])
        ax.set_xticks(YEARS)
        ax.tick_params(axis="x", rotation=45)
    axes[0].set_ylabel("Per 100,000 (population-weighted)")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "trends.png", dpi=150)
    plt.close(fig)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    p = load_panel()
    summary_tables(p)
    est = did_estimates(p)
    timing(p)
    es = event_study(p)
    trends(p)

    print("Difference-in-differences estimates (per 100,000; p-value in parentheses)")
    est["cell"] = est["coef"].map("{:,.1f}".format) + " (" + est["p_value"].map("{:.2f}".format) + ")"
    print(est.pivot(index="specification", columns="outcome", values="cell").to_string())
    pre = es[(es.year < EVENT_REFERENCE_YEAR)]
    print("\nPre-period event-study coefficients (2013, 2014):")
    print(pre.pivot_table(index=["outcome", "weighting"], columns="year", values="coef").round(1).to_string())


if __name__ == "__main__":
    main()
