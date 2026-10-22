# Unified UI source-only replay

This is offline source evidence only; it is not real UI/client integration or a render validation.
The UIManager reads the current run's bound, enabled player's `EdgeWarningState` for local yellow, gates all sources by running presentation context, and uses receiver getters for orange/model, TTE/proximity, and red/geometry.
The historical raw CSV `edge_warning_state` is the closest direct local field in scope; it does not prove current player binding, enabled state, receiver state, draw invocation, or pixels on screen.

Packets: 129; exact local true: 127; false: 2; aggregate/local mismatches: 2.
Orange decisions: 34; confirmed: 14; decision rows whose exact source packet has local true: 34.

TTE exact run+sequence packet matches: 35; orange-decision matches: 34; at those decision rows available=false: 34, active=false: 34; packet identity mismatches: 0. These are historical source rows, not proof of the Unity receiver getter state.

| Case | Packets | Exact local true/false | Aggregate/local mismatches | Orange decisions (confirmed) | Local true contiguous segments |
|---|---:|---:|---:|---:|---:|
| C01 | 14 | 14/0 | 0 | 4 (3) | 1 |
| C02 | 16 | 16/0 | 0 | 5 (3) | 1 |
| C03 | 29 | 29/0 | 0 | 8 (0) | 1 |
| C04 | 17 | 16/1 | 1 | 4 (3) | 1 |
| C05 | 15 | 14/1 | 1 | 4 (3) | 1 |
| C06 | 25 | 25/0 | 0 | 6 (0) | 1 |
| C07 | 13 | 13/0 | 0 | 3 (2) | 1 |

Every orange result is a decision-time snapshot; no state is carried between rows and no client warning lease is inferred. `c<=0` does not activate the red source. Geometry receiver active, TTE receiver active, and actual client render are unknown for all historical packets. Missing source fields remain blank/unknown.

Input hashes unchanged before/after replay: True.

C04 field discrepancies: line 2247 seq 1093 (exact edge_warning_state=False, aggregate warning_active=True).
C05 field discrepancies: line 4464 seq 2166 (exact edge_warning_state=False, aggregate warning_active=True).
