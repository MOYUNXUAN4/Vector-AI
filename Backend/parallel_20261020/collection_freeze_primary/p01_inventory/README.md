# P01 read-only inventory

Run from this directory with `python inventory.py`; use `--source` and `--output` to select alternate paths. The script uses only Python's standard library and never writes under the source tree. It snapshots SHA-256 values for every file under each session directory before parsing and recomputes them after the scan. Results include aggregate and per-session CSV/JSON evidence.

The confirmed participant cohort is limited to the first ten 2026-10-19 sessions listed in `inventory.py`, based on the primary agent's user-confirmed context. Other sessions remain cohort `unknown`; this does not infer that they are non-participants. Directory name P01 and Wii empty/unloaded/uncentered flags are not identity evidence.

Recommendations reproduce specific prior evidence only. They are review flags, not inclusion or exclusion decisions. The confirmed battery-displacement annotation applies to the exact 10:57:34 run/session only. The 15:10:34 terminal mismatch is retained as an unresolved evidence conflict. Timing flags do not establish cause or participant status. No session is automatically enrolled in training or evaluation.

Historical report sources (paths relative to the `fyp_Backend` root; all verified present):

- `parallel_20261019/p01_review/REPORT.md`
- `parallel_20261019/p01_review/user_annotations.json`
- `parallel_20261019/p01_new_gap_review/REPORT.md`
- `parallel_20261019/p01_new_gap_review/result_v2.json`

Unity gap counts use only consecutive Unity rows for which both adjacent source timestamps are finite. A missing timestamp breaks adjacency; the affected interval is reported as unknown and never bridged. Nonpositive adjacent deltas are counted separately and excluded from positive gap thresholds. Field distributions are split by `source` (`unity` vs `wii`) so Wii control flags describe Wii rows and run configuration fields describe their own source rows.

The checked inputs are under `telemetry_logs/P01/`. No raw file, report, model, Unity artifact, or launcher is changed by this inventory.
