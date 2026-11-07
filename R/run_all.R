# =====================================================================
# run_all.R
# Rebuild the panel, rerun the audit, and regenerate every table and figure.
#
# Usage (from the repository root):
#   Rscript R/run_all.R
#
# Required packages:
#   install.packages(c("dplyr", "tidyr", "readr", "readxl", "stringr",
#                      "purrr", "fixest", "ggplot2"))
# =====================================================================

source("R/01_build_panel.R")
source("R/02_audit_original_data.R")
source("R/03_analysis.R")

cat("== Building panel ==\n");             build_panel()
cat("\n== Auditing original workbooks ==\n"); audit()
cat("\n== Estimating ==\n");                run_analysis()
