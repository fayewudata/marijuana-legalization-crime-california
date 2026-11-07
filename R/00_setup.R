# =====================================================================
# 00_setup.R
# Packages, paths, and constants shared by every R script.
# Run all scripts from the repository root.
# =====================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
  library(readr)
  library(readxl)
  library(stringr)
  library(purrr)
  library(fixest)
  library(ggplot2)
})

if (!file.exists("R/00_setup.R")) {
  stop("Run the R scripts from the repository root, e.g. Rscript R/run_all.R")
}

RAW       <- "data/raw"
EXTERNAL  <- "data/external"
PROCESSED <- "data/processed"
TABLES    <- "outputs/tables"
FIGURES   <- "outputs/figures"
for (d in c(PROCESSED, TABLES, FIGURES)) dir.create(d, recursive = TRUE, showWarnings = FALSE)

STATES <- c(CA = "california", ID = "idaho", KS = "kansas",
            SC = "south_carolina", WY = "wyoming")
TREATED_STATE <- "CA"
YEARS         <- 2013:2019
POST_START    <- 2016   # thesis coding: 2016-2019 = post-legalization
RETAIL_START  <- 2018   # licensed recreational retail opened Jan 1, 2018
REF_YEAR      <- 2015   # event-study reference year
RATE_PER      <- 1e5    # all rates are per 100,000 residents

OUTCOMES <- c(
  violent     = "Violent crime",
  agg_assault = "Aggravated assault",
  property    = "Property crime",
  burglary    = "Burglary",
  larceny     = "Larceny-theft",
  mvt         = "Motor vehicle theft"
)

# Numeric parser that turns stray text such as "v  m", "-", or "(X)" into NA
to_num <- function(x) {
  x <- str_replace_all(as.character(x), ",", "")
  x <- str_replace(x, "[+-]$", "")
  suppressWarnings(as.numeric(x))
}

# Normalized county name used as a join key
county_key <- function(name) {
  name <- str_trim(str_split_fixed(name, "/", 2)[, 1])
  name <- str_remove(name, "\\s+(County|Parish)$")
  str_remove_all(str_to_lower(name), "[^a-z]")
}

# City-clustered two-way fixed-effects regression. Singleton cities are
# dropped because they are perfectly fit by their own fixed effect.
fit_twfe <- function(formula, data, weights = NULL) {
  feols(formula, data = data, cluster = ~city_id, weights = weights,
        fixef.rm = "singleton", notes = FALSE)
}
