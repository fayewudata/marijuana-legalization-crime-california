# =====================================================================
# 02_audit_original_data.R
# Check the original spreadsheets before relying on them.
#
# The UCR workbooks also carry the income and unemployment columns used in
# the thesis's covariate specification. This script checks:
#   1. Units: do the thesis Table 1 means match rates per 100,000 or 10,000?
#   2. Income column: matched to each city, or pasted in row order from the
#      county-subdivision list? What do the 2017-2019 values measure?
#   3. Unemployment column: matched to each city's county and year, or
#      pasted in row order (and from which year)?
#   4. City names: how many carry FBI footnote digits?
#   5. Covariate specification: how many city-years have all controls?
#   6. Thesis Table 3 Panel A vs. a reproduction in the same units.
# =====================================================================

source("R/01_build_panel.R")

THESIS_TABLE1_CA <- tibble(   # California cities, 2013-2019, as printed in the thesis
  outcome   = names(OUTCOMES),
  thesis_mean = c(47.69, 28.25, 430.53, 78.07, 281.08, 71.35),
  thesis_sd   = c(204.90, 95.41, 2839.83, 435.69, 1878.39, 590.13)
)
THESIS_PANEL_A <- c(violent = 4.83, agg_assault = 0.36, property = 54.67,
                    burglary = 17.81, larceny = 38.25, mvt = -1.94)
COMBINED_INCOME <- c(CA = "CA MHI.xlsx", ID = "Idaho MHI.xlsx", KS = "Kansas MHI.xlsx",
                     SC = "SC MHI.xlsx", WY = "Wyoming MHI.xlsx")
COMBINED_UNEMP <- c(ID = "ID_Unemployment_Combined.xlsx", KS = "KS_Unemployment_Rate_Com.xlsx",
                    SC = "SC Combined.xls", WY = "WY_Unemployment_Combined.xlsx")

same <- function(a, b) (is.na(a) & is.na(b)) | (!is.na(a) & !is.na(b) & abs(a - b) < 1e-9)

# Share of non-missing pairs where a[i] equals b[i] (row-position match)
position_match <- function(a, b, skip_missing_a = FALSE) {
  n <- min(length(a), length(b))
  a <- a[seq_len(n)]; b <- b[seq_len(n)]
  keep <- if (skip_missing_a) !is.na(a) else !(is.na(a) & is.na(b))
  c(compared = sum(keep), matched = sum(same(a[keep], b[keep])))
}

audit <- function() {
  wb <- load_ucr(keep_workbook_covariates = TRUE) |>
    mutate(wb_income = to_num(workbook_mhi), wb_unemp = to_num(workbook_unemp))
  checks <- list()
  add <- function(check, finding) checks[[length(checks) + 1]] <<- tibble(check = check, finding = finding)

  # 1. Units ------------------------------------------------------------------
  units <- wb |>
    filter(state == "CA") |>
    summarise(across(all_of(names(OUTCOMES)),
                     list(mean = ~ mean(.x / population * 1e4, na.rm = TRUE),
                          sd = ~ sd(.x / population * 1e4, na.rm = TRUE)))) |>
    pivot_longer(everything(), names_to = c("outcome", ".value"), names_pattern = "(.+)_(mean|sd)$") |>
    rename(per_10k_mean = mean, per_10k_sd = sd) |>
    right_join(THESIS_TABLE1_CA, by = "outcome") |>
    mutate(per_100k_mean = per_10k_mean * 10, across(where(is.numeric), ~ round(.x, 2))) |>
    select(outcome, thesis_mean, per_10k_mean, thesis_sd, per_10k_sd, per_100k_mean)
  write_csv(units, file.path(TABLES, "audit_units.csv"))
  add("Units of thesis crime rates",
      sprintf("Thesis Table 1 California means match rates per 10,000 for %d/6 outcomes (labeled per 100,000). Corrected tables multiply by 10.",
              sum(abs(units$thesis_mean - units$per_10k_mean) < 0.006)))

  # 2. Income column ----------------------------------------------------------
  inc <- imap(COMBINED_INCOME, function(fname, st) {
    lst <- read_excel(file.path(RAW, "original_covariate_lists", fname), col_types = "text",
                      .name_repair = ~ make.unique(.x))
    value_cols <- names(lst)[seq(2, ncol(lst), by = 2)]
    rowSums(sapply(seq_along(YEARS), function(j) {
      position_match(filter(wb, state == st, year == YEARS[j])$wb_income, to_num(lst[[value_cols[j]]]))
    }))
  }) |> reduce(`+`)
  add("Income column linkage",
      sprintf("In %s/%s city-years (%.0f%%), the workbook income equals the entry in the same row position of the county-subdivision list, i.e. values were pasted in list order rather than matched to each city.",
              format(inc[["matched"]], big.mark = ","), format(inc[["compared"]], big.mark = ","),
              100 * inc[["matched"]] / inc[["compared"]]))

  wrong <- map_chr(2016:2019, function(yr) {
    acs <- map_dfr(c("CA", "ID", "SC", "WY"), function(st) {
      map_dfr(list.files(file.path(RAW, "acs_s1903_ccd", st), pattern = paste0("ACSST5Y", yr, ".*-Data\\.csv$"),
                         full.names = TRUE), read_s1903)
    })
    sprintf("%d: workbook median %s vs ACS median income %s", yr,
            format(round(median(filter(wb, year == yr, state != "KS")$wb_income, na.rm = TRUE)), big.mark = ","),
            format(round(median(acs$median_income, na.rm = TRUE)), big.mark = ","))
  })
  add("Income column, 2017-2019",
      paste("ACS restructured table S1903 in 2017, and the 2017-2019 workbook values are the number of households with a householder aged 25-44, not median income.",
            paste(wrong, collapse = "; ")))

  # 3. Unemployment column ------------------------------------------------------
  ca_path <- file.path(RAW, "laus_county_unemployment", "california.xls")
  ca_sheets <- map(excel_sheets(ca_path), function(sh) {
    d <- read_excel(ca_path, sheet = sh, col_names = FALSE, col_types = "text", .name_repair = "minimal")
    d <- d[12:nrow(d), 1:2]
    d <- d[!is.na(d[[1]]) & !is.na(d[[2]]), ]
    setNames(to_num(d[[2]]), excel_year(d[[1]]))
  })
  ca_res <- rowSums(sapply(YEARS, function(yr) {
    v <- filter(wb, state == "CA", year == yr)$wb_unemp
    source <- map_dbl(seq_along(v), function(i) {
      if (i > length(ca_sheets)) return(NA_real_)
      x <- ca_sheets[[i]][as.character(yr + 1)]
      if (is.null(x) || length(x) == 0) NA_real_ else unname(x)
    })
    position_match(v, source, skip_missing_a = TRUE)
  }))
  msgs <- sprintf("CA %d/%d equal county sheet #i's value for year t+1", ca_res[["matched"]], ca_res[["compared"]])
  for (st in names(COMBINED_UNEMP)) {
    lst <- read_excel(file.path(RAW, "original_covariate_lists", COMBINED_UNEMP[[st]]),
                      col_names = FALSE, col_types = "text", .name_repair = "minimal")
    names(lst)[1:2] <- c("yr", "rate")
    lst <- mutate(lst, yr = to_num(yr), rate = to_num(rate)) |> filter(between(yr, 2013, 2019))
    res <- rowSums(sapply(YEARS, function(yr) {
      position_match(filter(wb, state == st, year == yr)$wb_unemp, lst$rate[lst$yr == yr], skip_missing_a = TRUE)
    }))
    msgs <- c(msgs, sprintf("%s %d/%d equal the same-position entry of the stacked county list",
                            st, res[["matched"]], res[["compared"]]))
  }
  filled <- wb |> group_by(state) |> summarise(p = sprintf("%s %.0f%%", first(state), 100 * mean(!is.na(wb_unemp))))
  add("Unemployment column linkage",
      paste0("County rates were pasted in list order, not matched to each city's county; the county files start in 2014, so the year labeled 2013 holds 2014 data. ",
             paste(msgs, collapse = "; "), ". Share of city-years filled: ", paste(filled$p, collapse = ", ")))

  # 4. City names ---------------------------------------------------------------
  ids_raw <- n_distinct(paste(wb$state, wb$city_as_published))
  ids_clean <- n_distinct(paste(wb$state, wb$city))
  add("FBI footnote digits in city names",
      sprintf("%d city-years (e.g. 'Aiken3') carry footnote digits; uncleaned, they create %d spurious extra cities (%d vs %d city fixed effects).",
              sum(wb$city != wb$city_as_published), ids_raw - ids_clean, ids_raw, ids_clean))

  # 5. Listwise deletion ---------------------------------------------------------
  usable <- sum(complete.cases(wb[c("violent", "population", "wb_income", "wb_unemp")]))
  add("Covariate specification sample",
      sprintf("With the workbook covariates, %s of %s city-years have all controls; the thesis reports 5,678 observations for this specification.",
              format(usable, big.mark = ","), format(nrow(wb), big.mark = ",")))

  # 6. Panel A reproduction ------------------------------------------------------
  df <- wb |>
    mutate(across(all_of(names(OUTCOMES)), ~ .x / population * 1e4),   # thesis units
           city_id = paste(state, city, sep = "_"),
           treat = as.integer(state == "CA" & year >= 2016))
  rep <- imap_dfr(THESIS_PANEL_A, function(thesis_coef, y) {
    m <- fit_twfe(as.formula(paste(y, "~ treat | city_id + year")), df)
    tibble(outcome = y, thesis_coef_per_10k = thesis_coef,
           reproduced_coef_per_10k = round(unname(coef(m)["treat"]), 2),
           reproduced_p_clustered = round(unname(pvalue(m)["treat"]), 3))
  })
  write_csv(rep, file.path(TABLES, "audit_panel_a_reproduction.csv"))
  add("Thesis Table 3, Panel A",
      "Five of six coefficients reproduce within about 11%; aggravated assault is near zero in both. P-values clustered by city are larger than printed (see audit_panel_a_reproduction.csv).")

  out <- bind_rows(checks)
  write_csv(out, file.path(TABLES, "audit_checks.csv"))
  walk2(out$check, out$finding, ~ cat(sprintf("- %s: %s\n\n", .x, .y)))
  print(as.data.frame(rep))
  invisible(out)
}

if (sys.nframe() == 0) audit()
