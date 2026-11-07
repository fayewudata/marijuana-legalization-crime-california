# =====================================================================
# 03_analysis.R
# Estimate the effect of California's 2016 legalization on city crime.
#
# Outputs (outputs/tables, outputs/figures)
#   table1_summary_stats.csv         means and SDs by group and period
#   table2_unadjusted_did.csv        2x2 difference in means
#   table3_did_estimates.csv         two-way fixed effects, five specifications
#   table4_possession_vs_retail.csv  separate effects for 2016-17 and 2018-19
#   event_study.csv / event_study.png   California x year effects (2015 = 0)
#   trends.png                       population-weighted rates by group
#
# Rates are per 100,000 residents; standard errors are clustered by city.
# With one treated state, clustered p-values likely overstate precision.
# =====================================================================

source("R/00_setup.R")

load_panel <- function() {
  read_csv(file.path(PROCESSED, "city_year_panel.csv"), show_col_types = FALSE) |>
    mutate(
      post           = as.integer(year >= POST_START),
      treat          = treated_state * post,
      possession     = as.integer(treated_state == 1 & year >= POST_START & year < RETAIL_START),
      retail         = as.integer(treated_state == 1 & year >= RETAIL_START),
      population_10k = population / 1e4
    )
}

summary_tables <- function(p) {
  periods <- list("2013-2019" = p, "2013-2015" = filter(p, post == 0), "2016-2019" = filter(p, post == 1))
  t1 <- imap_dfr(periods, function(d, period) {
    d |>
      mutate(group = if_else(treated_state == 1, "California", "Control states")) |>
      pivot_longer(all_of(names(OUTCOMES)), names_to = "y") |>
      group_by(group, y) |>
      summarise(n = sum(!is.na(value)), mean = round(mean(value, na.rm = TRUE), 1),
                sd = round(sd(value, na.rm = TRUE), 1), .groups = "drop") |>
      mutate(period = period, outcome = OUTCOMES[y])
  }) |>
    arrange(match(period, names(periods)), desc(group == "Control states"), match(y, names(OUTCOMES))) |>
    select(period, group, outcome, n, mean, sd)
  write_csv(t1, file.path(TABLES, "table1_summary_stats.csv"))

  t2 <- p |>
    pivot_longer(all_of(names(OUTCOMES)), names_to = "y") |>
    group_by(y, treated_state, post) |>
    summarise(m = mean(value, na.rm = TRUE), .groups = "drop") |>
    pivot_wider(names_from = c(treated_state, post), values_from = m, names_prefix = "g") |>
    transmute(outcome = OUTCOMES[y],
              ca_pre = g1_0, ca_post = g1_1, ca_change = g1_1 - g1_0,
              control_pre = g0_0, control_post = g0_1, control_change = g0_1 - g0_0,
              difference = ca_change - control_change) |>
    mutate(across(where(is.numeric), ~ round(.x, 1))) |>
    arrange(match(outcome, OUTCOMES))
  write_csv(t2, file.path(TABLES, "table2_unadjusted_did.csv"))
}

did_estimates <- function(p) {
  s <- filter(p, year >= 2014)   # county unemployment files start in 2014
  specs <- list(
    list("(1) City and year FE, 2013-2019", "treat", p, NULL),
    list("(2) City and year FE, 2014-2019", "treat", s, NULL),
    list("(3) + population, county unemployment", "treat + population_10k + unemp_rate", s, NULL),
    list("(4) + county income proxy (excl. Kansas)",
         "treat + population_10k + unemp_rate + county_income_proxy", filter(s, state != "KS"), NULL),
    list("(5) City and year FE, population-weighted", "treat", p, ~population)
  )
  pre_mean <- p |> filter(treated_state == 1, post == 0) |>
    summarise(across(all_of(names(OUTCOMES)), ~ mean(.x, na.rm = TRUE)))

  out <- map_dfr(names(OUTCOMES), function(y) {
    map_dfr(specs, function(sp) {
      m <- fit_twfe(as.formula(paste(y, "~", sp[[2]], "| city_id + year")), sp[[3]], sp[[4]])
      b <- unname(coef(m)["treat"])
      tibble(outcome = OUTCOMES[[y]], specification = sp[[1]], coef = round(b, 1),
             se = round(unname(se(m)["treat"]), 1), p_value = round(unname(pvalue(m)["treat"]), 3),
             n = nobs(m), pct_of_ca_pre_mean = round(100 * b / pre_mean[[y]], 1))
    })
  })
  write_csv(out, file.path(TABLES, "table3_did_estimates.csv"))
  out
}

timing <- function(p) {
  out <- map_dfr(names(OUTCOMES), function(y) {
    m <- fit_twfe(as.formula(paste(y, "~ possession + retail | city_id + year")), p)
    tibble(outcome = OUTCOMES[[y]],
           period = c("2016-2017 (possession only)", "2018-2019 (retail sales)"),
           coef = round(unname(coef(m)[c("possession", "retail")]), 1),
           se = round(unname(se(m)[c("possession", "retail")]), 1),
           p_value = round(unname(pvalue(m)[c("possession", "retail")]), 3))
  })
  write_csv(out, file.path(TABLES, "table4_possession_vs_retail.csv"))
}

event_study <- function(p) {
  es <- map_dfr(names(OUTCOMES), function(y) {
    map_dfr(list(unweighted = NULL, `population-weighted` = ~population), .id = "weighting", function(w) {
      m <- fit_twfe(as.formula(paste0(y, " ~ i(year, treated_state, ref = ", REF_YEAR, ") | city_id + year")), p, w)
      ct <- as.data.frame(coeftable(m))
      ci <- confint(m)
      est <- tibble(year = as.integer(str_match(rownames(ct), "year::(\\d{4})")[, 2]),
                    coef = ct[, 1], ci_low = ci[, 1], ci_high = ci[, 2], p_value = ct[, 4])
      bind_rows(est, tibble(year = REF_YEAR, coef = 0, ci_low = 0, ci_high = 0, p_value = NA)) |>
        arrange(year)
    }) |> mutate(outcome = OUTCOMES[[y]])
  }) |>
    select(outcome, weighting, year, coef, ci_low, ci_high, p_value)
  write_csv(mutate(es, across(where(is.double), ~ round(.x, 3))), file.path(TABLES, "event_study.csv"), na = "")

  g <- es |>
    mutate(outcome = factor(outcome, levels = OUTCOMES),
           weighting = factor(weighting, levels = c("unweighted", "population-weighted"))) |>
    ggplot(aes(year, coef, colour = weighting, shape = weighting)) +
    geom_hline(yintercept = 0, colour = "grey50", linewidth = 0.4) +
    geom_vline(xintercept = POST_START - 0.5, linetype = "dashed", colour = "grey50", linewidth = 0.4) +
    geom_pointrange(aes(ymin = ci_low, ymax = ci_high), position = position_dodge(width = 0.35), size = 0.3) +
    facet_wrap(~outcome, scales = "free_y", ncol = 3) +
    scale_x_continuous(breaks = YEARS) +
    scale_colour_manual(values = c("#1f77b4", "#ff7f0e")) +
    labs(title = "Event Study: Did California Diverge Before Legalization?",
         x = NULL, y = sprintf("California vs. control, per 100,000 (relative to %d)", REF_YEAR),
         colour = NULL, shape = NULL) +
    theme_minimal(base_size = 11) +
    theme(legend.position = "bottom", panel.grid.minor = element_blank(),
          axis.text.x = element_text(angle = 45, hjust = 1))
  ggsave(file.path(FIGURES, "event_study.png"), g, width = 11, height = 7, dpi = 150, bg = "white")
  es
}

trends <- function(p) {
  g <- p |>
    pivot_longer(c(violent, property, larceny), names_to = "y") |>
    filter(!is.na(value)) |>
    group_by(y, year, group = if_else(treated_state == 1, "California", "Control states")) |>
    summarise(rate = weighted.mean(value, population), .groups = "drop") |>
    mutate(y = factor(OUTCOMES[y], levels = OUTCOMES[c("violent", "property", "larceny")])) |>
    ggplot(aes(year, rate, colour = group)) +
    geom_vline(xintercept = POST_START - 0.5, linetype = "dashed", colour = "grey50", linewidth = 0.4) +
    geom_line() + geom_point() +
    facet_wrap(~y, scales = "free_y") +
    scale_x_continuous(breaks = YEARS) +
    scale_colour_manual(values = c("#1f77b4", "#ff7f0e")) +
    labs(x = NULL, y = "Per 100,000 (population-weighted)", colour = NULL) +
    theme_minimal(base_size = 11) +
    theme(legend.position = "bottom", panel.grid.minor = element_blank(),
          axis.text.x = element_text(angle = 45, hjust = 1))
  ggsave(file.path(FIGURES, "trends.png"), g, width = 11, height = 4, dpi = 150, bg = "white")
}

run_analysis <- function() {
  p <- load_panel()
  summary_tables(p)
  est <- did_estimates(p)
  timing(p)
  es <- event_study(p)
  trends(p)

  cat("Difference-in-differences estimates (per 100,000; p-value in parentheses)\n")
  est |>
    mutate(cell = sprintf("%s (%.2f)", format(coef, nsmall = 1, big.mark = ","), p_value)) |>
    select(specification, outcome, cell) |>
    pivot_wider(names_from = outcome, values_from = cell) |>
    as.data.frame() |> print()
  cat("\nPre-period event-study coefficients:\n")
  es |> filter(year < REF_YEAR) |> select(outcome, weighting, year, coef) |>
    mutate(coef = round(coef, 1)) |>
    pivot_wider(names_from = year, values_from = coef) |> as.data.frame() |> print()
}

if (sys.nframe() == 0) run_analysis()
