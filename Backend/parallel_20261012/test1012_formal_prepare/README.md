# TEST1012 formal preparation

This workspace contains a no-fit preparation of the current TEST1012 runs. It preserves actual outcomes, associates raw CSVs and diagnostic JSONL by unique run_id, and uses the current-run lifecycle receipts to bound snapshot inputs.

The reviewed 24 causal features use 0.5 seconds of past history, a 0.05-second evaluation stride, a 0.1-second maximum segment gap, and a geometry identity/validity mask. Invalid rows, layer changes, identity changes, sequence gaps, and time gaps break segments. Feature rows retain their exact CSV row and sequence.

Geometry anchors use full diagnostic snapshots at query time, bridged by the same run's median Unity clock offset. Missing or invalid query times remain unknown. The independent fingerprint version and ordinary geometry generation are retained separately. A terminal anchor additionally requires an exact edge-exit event matching terminal raw platform, last-support platform, layer, and generation, with no observed same-identity positive return.

`calibration_mode=True` is retained as recorded. Layers 1–3 at scale <=2 are treated as gameplay-compatible; layer 4 is excluded. This preparation does not claim calibration mode was false. Actual `calibration_completed` outcomes remain unchanged; `normalized_outcome=complete` is only assigned to ended runs with passed_count=3 and selected_session_layers=3.

Sensitivity context is user-provided: current 0.55, prior 0.66. Both experimental AI and geometry banners were on, and original yellow attention was unchanged. No models were trained and no thresholds were selected.

Run `python prepare_formal.py` with the bundled Python runtime to reproduce. All derived files stay in this folder; source logs are read-only.
