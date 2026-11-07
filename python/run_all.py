"""Rebuild the panel, rerun the audit, and regenerate every table and figure.

Usage (from the repo root):
    python python/run_all.py

python/make_crosswalk.py is not rerun here because it downloads its source list;
its output, data/external/city_county_crosswalk.csv, is committed.
"""

import analysis
import audit_original_data
import build_panel

if __name__ == "__main__":
    print("== Building panel ==")
    build_panel.build()
    print("\n== Auditing original workbooks ==")
    audit_original_data.main()
    print("\n== Estimating ==")
    analysis.main()
