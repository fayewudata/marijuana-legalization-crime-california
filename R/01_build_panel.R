# =====================================================================
# 01_build_panel.R
# Build the city-year analysis panel from the raw files.
#
# 1. Read the 35 UCR city sheets (5 states x 7 years), standardize columns.
# 2. Clean city names: strip FBI footnote digits ("Aiken3" -> "Aiken") so
#    each city keeps one identifier across years.
# 3. Convert counts to rates per 100,000 residents.
# 4. Merge county-level covariates BY NAME through a city-to-county crosswalk:
#    - unemployment rate (BLS LAUS annual county series, 2014-2020)
#    - income proxy: household-weighted mean of ACS S1903 median household
#      income (householder 25-44) across the county's census county
#      subdivisions. Available for CA (2014-2019), ID, SC, WY; not Kansas.
# 5. Write data/processed/city_year_panel.csv and a data-quality log.
# =====================================================================

source("R/00_setup.R")

UCR_COLUMNS <- c(
  "city" = "city", "population" = "population", "violent crime" = "violent",
  "aggravated assault" = "agg_assault", "property crime" = "property",
  "burglary" = "burglary", "larceny-theft" = "larceny",
  "motor vehicle theft" = "mvt", "state" = "state_label",
  "mhi" = "workbook_mhi", "median household income(25-44)" = "workbook_mhi",
  "unemployment rate" = "workbook_unemp"
)

standardize_names <- function(x) {
  x <- str_to_lower(str_squish(x))
  x <- str_replace_all(x, "- ", "-")
  unname(ifelse(x %in% names(UCR_COLUMNS), UCR_COLUMNS[x], x))
}

# ------------------------------------------------------------- UCR crime data
load_ucr <- function(keep_workbook_covariates = FALSE) {
  ucr <- imap_dfr(STATES, function(stem, state) {
    path <- file.path(RAW, "ucr_city_workbooks", paste0(stem, ".xls"))
    map_dfr(excel_sheets(path), function(sheet) {
      df <- read_excel(path, sheet = sheet, col_types = "text", .name_repair = "minimal")
      names(df) <- standardize_names(names(df))
      df |> mutate(state = state, year = as.integer(sheet))
    })
  })

  ucr <- ucr |>
    # drop blank rows and repeated header rows inside the sheets
    filter(str_trim(state_label) %in% names(STATES)) |>
    mutate(
      city_as_published = str_trim(city),
      city = str_trim(str_remove(city_as_published, "[\\d,]+$")),
      across(c(population, all_of(names(OUTCOMES))), to_num)   # "v  m" -> NA
    )

  keep <- c("state", "city", "city_as_published", "year", "population", names(OUTCOMES))
  if (keep_workbook_covariates) keep <- c(keep, "workbook_mhi", "workbook_unemp")
  select(ucr, all_of(keep))
}

# ------------------------------------------------------ county unemployment
excel_year <- function(x) {
  serial <- suppressWarnings(as.numeric(x))
  ifelse(!is.na(serial) & serial > 20000,
         as.integer(format(as.Date(serial, origin = "1899-12-30"), "%Y")),
         as.integer(substr(x, 1, 4)))
}

load_unemployment <- function() {
  skipped <- character()
  rows <- imap_dfr(STATES, function(stem, state) {
    path <- file.path(RAW, "laus_county_unemployment", paste0(stem, ".xls"))
    map_dfr(excel_sheets(path), function(sheet) {
      df <- read_excel(path, sheet = sheet, col_names = FALSE, col_types = "text",
                       .name_repair = "minimal")
      title <- if (nrow(df) >= 8) df[[2]][8] else NA_character_
      m <- str_match(title, "Unemployment Rate in (.+?), ([A-Z]{2}),")
      if (is.na(m[1, 2])) {
        skipped <<- c(skipped, sprintf("%s.xls / %s: no county identifier", stem, sheet))
        return(NULL)
      }
      start <- which(str_trim(df[[1]]) == "observation_date")[1] + 1
      obs <- df[start:nrow(df), 1:2]
      names(obs) <- c("date", "value")
      obs |>
        filter(!is.na(date), !is.na(value)) |>
        transmute(state = state, county_key = county_key(m[1, 2]),
                  year = excel_year(date), unemp_rate = to_num(value))
    })
  })
  list(data = distinct(rows, state, county_key, year, .keep_all = TRUE), skipped = skipped)
}

# -------------------------------------------------------- county income proxy
read_s1903 <- function(path) {
  first <- str_remove(readLines(path, n = 1, warn = FALSE), "^\ufeff")
  skip <- if (str_starts(first, '"?GEO_ID')) 1 else 0   # two header rows: codes, then labels
  df <- read_csv(path, skip = skip, col_types = cols(.default = "c"),
                 name_repair = "minimal", show_col_types = FALSE)
  name_col <- intersect(c("Geographic Area Name", "NAME"), names(df))[1]

  pick <- function(...) {
    must <- c(...)
    lower <- str_to_lower(names(df))
    ok <- str_detect(names(df), fixed("25 to 44")) &
      reduce(map(must, ~ str_detect(lower, fixed(.x))), `&`) &
      !str_detect(lower, fixed("margin of error")) & !str_detect(lower, fixed("moe"))
    stopifnot(sum(ok) == 1)
    names(df)[ok]
  }
  # Median income moved from column C02 (2013-2016) to C03 (2017+);
  # selecting by label instead of position avoids that trap.
  median_col <- pick("median income (dollars)")
  households_col <- if (any(str_detect(names(df), "Number"))) pick("number") else pick("total")

  tibble(
    geo_name      = df[[name_col]],
    median_income = to_num(df[[median_col]]),
    households    = to_num(df[[households_col]])
  ) |>
    mutate(county_key = county_key(str_match(geo_name, ", (.+?) County,")[, 2]))
}

load_income_proxy <- function() {
  files <- unlist(map(c("CA", "ID", "SC", "WY"), function(st) {
    list.files(file.path(RAW, "acs_s1903_ccd", st), pattern = "-Data\\.csv$", full.names = TRUE)
  }))
  map_dfr(files, function(path) {
    read_s1903(path) |>
      filter(!is.na(median_income), !is.na(households), households > 0) |>
      group_by(county_key) |>
      summarise(county_income_proxy = sum(median_income * households) / sum(households),
                .groups = "drop") |>
      mutate(state = basename(dirname(path)),
             year = as.integer(str_match(basename(path), "ACSST5Y(\\d{4})")[, 2]))
  })
}

# ----------------------------------------------------------------------- build
build_panel <- function() {
  ucr <- load_ucr()
  log <- c(sprintf("UCR city-year rows after dropping blank/header rows: %s",
                   format(nrow(ucr), big.mark = ",")),
           sprintf("City names with FBI footnote digits removed: %d",
                   sum(ucr$city != ucr$city_as_published)))
  stopifnot(!any(duplicated(ucr[c("state", "city", "year")])))

  panel <- ucr |>
    mutate(across(all_of(names(OUTCOMES)), ~ .x / population * RATE_PER),
           treated_state = as.integer(state == TREATED_STATE)) |>
    left_join(read_csv(file.path(EXTERNAL, "city_county_crosswalk.csv"), show_col_types = FALSE) |>
                select(state, city, county),
              by = c("state", "city")) |>
    mutate(county_key = county_key(county))
  log <- c(log, sprintf("City-years without a county match: %d", sum(is.na(panel$county))))

  unemp <- load_unemployment()
  log <- c(log, paste("Skipped unemployment sheet:", unemp$skipped))

  panel <- panel |>
    left_join(unemp$data, by = c("state", "county_key", "year")) |>
    left_join(load_income_proxy(), by = c("state", "county_key", "year")) |>
    mutate(city_id = paste(state, city, sep = "_")) |>
    select(-county_key) |>
    arrange(state, city, year)

  write_csv(panel, file.path(PROCESSED, "city_year_panel.csv"), na = "")

  coverage <- panel |>
    group_by(state, year) |>
    summarise(has_unemp = round(100 * mean(!is.na(unemp_rate)), 1),
              has_income = round(100 * mean(!is.na(county_income_proxy)), 1),
              .groups = "drop")
  write_csv(coverage, file.path(TABLES, "covariate_coverage.csv"))
  writeLines(log, file.path(TABLES, "build_log.txt"))

  cat(log, sep = "\n")
  cat(sprintf("\nPanel: %s city-years, %s cities\n",
              format(nrow(panel), big.mark = ","), format(n_distinct(panel$city_id), big.mark = ",")))
  print(as.data.frame(pivot_wider(select(coverage, -has_income), names_from = year, values_from = has_unemp)))
  invisible(panel)
}

if (sys.nframe() == 0) build_panel()
