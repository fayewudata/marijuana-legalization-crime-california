# Recreational Marijuana Legalization and Crime: Evidence from California

Did California's 2016 legalization of recreational marijuana (Proposition 64) increase crime? This project compares 959 California and control-state cities over 2013–2019 in a two-way fixed-effects difference-in-differences design, using FBI Uniform Crime Reporting data. The control group is cities in Idaho, Kansas, South Carolina, and Wyoming, which allowed neither medical nor recreational marijuana during the period.

**Tools:** R (fixest, dplyr, ggplot2), Python (pandas, pyfixest), Stata

**Date:** Economics Honors Thesis, University of California, Irvine, 2024–2025

**Paper:** [`paper/Faye_Wu_Marijuana_Legalization_Crime_Thesis.pdf`](paper/Faye_Wu_Marijuana_Legalization_Crime_Thesis.pdf)

## Key Findings

| Finding | Evidence |
|---|---|
| **No evidence that legalization increased violent crime.** With controls the estimate is +7.6 per 100,000 (p = 0.69), and the population-weighted estimate is −0.5 (p = 0.99). | `table3_did_estimates.csv` |
| **The apparent rise in property crime is not credibly due to legalization.** Simple difference-in-differences shows larceny-theft up 343 per 100,000 (p < 0.01), but the event study shows California's property crime and larceny had already risen relative to the control states between 2013 and 2015, *before* legalization, and did not diverge further in 2016–2018. | `event_study.png`, `event_study.csv` |
| **The pre-2016 divergence lines up with Proposition 47.** In population-weighted estimates, California's relative larceny rate jumped between 2014 and 2015, the first full year after Proposition 47 reduced penalties for theft under $950. The thesis flagged this reform as a likely confounder. | `event_study.csv` |
| **Only 2019 shows a relative larceny increase** (+202 per 100,000, p = 0.02, population-weighted), the second year of licensed retail sales. A single-state design cannot separate this from other 2019 changes. | `event_study.csv` |

![Event study](outputs/figures/event_study.png)

## Main Estimates

Two-way fixed-effects difference-in-differences, offenses per 100,000 residents. Standard errors clustered by city; p-values in parentheses.

| Specification | Violent crime | Property crime | Larceny-theft |
|---|---|---|---|
| (1) City and year FE, 2013–2019 | 43.1 (0.10) | 485.4 (0.04) | 343.2 (0.00) |
| (2) City and year FE, 2014–2019 | 22.8 (0.23) | 406.9 (0.10) | 247.1 (0.03) |
| (3) + population, county unemployment | 7.6 (0.69) | 416.7 (0.10) | 276.3 (0.04) |
| (4) + county income proxy (excl. Kansas) | 8.5 (0.69) | 518.3 (0.09) | 338.6 (0.02) |
| (5) City and year FE, population-weighted | −0.5 (0.99) | 121.5 (0.12) | 170.0 (0.00) |

Specifications (2)–(4) start in 2014 because the county unemployment files begin that year. All six outcomes, standard errors, and sample sizes are in [`outputs/tables/table3_did_estimates.csv`](outputs/tables/table3_did_estimates.csv). With one treated state, city-clustered p-values likely overstate precision (Conley & Taber, 2011).

## Data Notes

Building a reproducible pipeline from the raw spreadsheets surfaced four data-construction issues in the files behind the submitted PDF. The code corrects them, so some results here differ from the PDF. [`R/02_audit_original_data.R`](R/02_audit_original_data.R) documents each issue with evidence ([`audit_checks.csv`](outputs/tables/audit_checks.csv)).

1. **Rate units.** The PDF tables are labeled per 100,000 residents but match rates per 10,000 exactly. Multiplying PDF coefficients by 10 converts them; all tables here use per 100,000.
2. **Covariates were not matched to cities.** The income and unemployment columns were pasted in list order next to an alphabetical city list rather than merged by city: 87% of income values and 98% of unemployment values equal the entry in the same row of the source list. The unemployment values were also shifted one year, and the 2017–2019 "income" values are household counts from a column that moved when the Census Bureau restructured the ACS table in 2017.
3. **City names with FBI footnote digits** (for example "Aiken3") split 157 city-years into 154 spurious extra cities, weakening the city fixed effects.
4. **The covariate specification in the PDF cannot be reproduced.** With the original covariate columns, only 1,136 city-years have all controls; the PDF reports 5,678.

The pipeline here merges county unemployment by name and year through a city-to-county crosswalk, cleans city names, and adds the event study, timing split, and population weighting that the PDF proposes as extensions.

| | Submitted PDF | This repository |
|---|---|---|
| Violent crime | No significant effect with controls | No effect in any specification |
| Property crime | Controls cut the estimate by about two-thirds | Correctly merged controls leave it unchanged (406.9 → 416.7 on the same sample) |
| Larceny-theft | Weak evidence of a 7% increase | Positive in every specification, but driven by a divergence that began before legalization |
| Parallel trends | Untested; event study proposed | Tested; rejected for property crime and larceny |
| Overall conclusion | No support for a large increase in crime | Unchanged, now backed by the pre-trend evidence |

Panel A of PDF Table 3 (no covariates) reproduces closely: five of six coefficients are within about 11% of the PDF values, and aggravated assault is near zero in both ([`audit_panel_a_reproduction.csv`](outputs/tables/audit_panel_a_reproduction.csv)). City-clustered p-values are larger than those printed in the PDF.

## Repository Structure

```
├── paper/                              # submitted thesis (PDF)
├── R/                                  # main pipeline
│   ├── 00_setup.R                      # packages, paths, constants
│   ├── 01_build_panel.R                # clean, merge by name, compute rates
│   ├── 02_audit_original_data.R        # checks on the original spreadsheets
│   ├── 03_analysis.R                   # tables, event study, figures
│   └── run_all.R                       # rebuilds everything
├── python/                             # independent implementation of the same pipeline
├── data/
│   ├── raw/
│   │   ├── ucr_city_workbooks/         # FBI UCR city crime counts, one sheet per year
│   │   ├── laus_county_unemployment/   # BLS county unemployment rates (via FRED)
│   │   ├── acs_s1903_ccd/              # ACS median income by county subdivision
│   │   └── original_covariate_lists/   # lists used to fill the original covariate columns (audit only)
│   ├── external/city_county_crosswalk.csv
│   └── processed/city_year_panel.csv   # generated analysis panel
└── outputs/
    ├── tables/
    └── figures/
```

## How to Run

**R (main pipeline):**

```r
install.packages(c("dplyr", "tidyr", "readr", "readxl", "stringr", "purrr", "fixest", "ggplot2"))
```

```bash
Rscript R/run_all.R
```

**Python (cross-check):** the `python/` folder implements the same pipeline with pandas and pyfixest and produces identical estimates. It writes to `outputs/python/` so the two never overwrite each other.

```bash
pip install -r requirements.txt
python python/run_all.py
```

`python/make_crosswalk.py` builds the city-to-county crosswalk. It downloads its source list, so it is not part of either `run_all` script; its output is committed.

## Data Sources

- **Crime and population:** FBI Uniform Crime Reporting Program, *Crime in the United States*, offenses known to law enforcement by city, 2013–2019.
- **Unemployment:** U.S. Bureau of Labor Statistics, Local Area Unemployment Statistics, annual county rates (downloaded from FRED), 2014–2020.
- **Income:** U.S. Census Bureau, American Community Survey 5-year estimates, table S1903, median household income for householders aged 25–44, by county subdivision. These are aggregated to a household-weighted county proxy; no files are available for Kansas or for California in 2013.
- **City-to-county crosswalk:** derived from the public [USA-cities-and-states](https://github.com/grammakov/USA-cities-and-states) list, with 29 cities assigned by hand to their principal county.

## Limitations

- One treated state and four control states make inference fragile; synthetic control or randomization inference would be stronger tests.
- Covariates are measured at the county level, and the income measure is a proxy.
- Only three pre-legalization years are available, and 2013 lacks unemployment data.
- UCR participation is voluntary, so the panel is unbalanced and recorded crime can change with reporting practices.
