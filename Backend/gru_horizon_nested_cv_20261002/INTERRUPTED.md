# Run status: interrupted

The run loaded the development pool and wrote `eligible_sessions_and_outer_folds.csv`, then the Python process ended before producing fold metrics, threshold selections, or `summary.json`. The available evidence does not identify why the process ended. Treat this directory as an incomplete run; it contains no horizon performance results.

The development manifest scope was TEST9282, TEST930, and TEST931 only. `TEST1001` was not included. The partial eligibility table lists 117 sessions: 48 fall sessions and 69 non-fall sessions, with causal windows at all four horizons.
