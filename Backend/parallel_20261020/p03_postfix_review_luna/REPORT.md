# P03 post-fix telemetry review

Read-only audit of the nine requested session CSVs and exact Unity `run_id` matches in the shared `telemetry_logs/proximity_shadow.jsonl`. Every CSV's byte size was unchanged during read; before/after SHA-256 values match. No source data, labels, code, or configuration were changed, and no service or model was started.

## Results

Each CSV contains one Unity run. All have commanded and active difficulty 3, selected layers 5, `calibration_mode=True` on every Unity row, and continuous Unity sequence 1…N with no missing sequence pairs. Unity source timestamp gaps are all below 50 ms (maximum by run: 26–47 ms); none exceed 100 ms. Each run's terminal record is identified below.

| Session | Unity run ID | Unity samples | Terminal | Shadow records | Active true | Causally available true | `unsupported_or_calibration_phase` | Other reason counts |
|---|---|---:|---|---:|---:|---:|---:|---|
| 20261020_214022_086000 | `6c85d23f1b984ec78fffae07c46dca70` | 2119 | calibration_completed | 2119 | 79 | 1593 | 299 | insufficient_0_5s_history 151; outside_proximity_domain 75; ended 1 |
| 20261020_214100_600233 | `4521987dfdc34380ae0d20d9d0e232bd` | 456 | edge_exit | 456 | 32 | 102 | 302 | insufficient_0_5s_history 51; ended 1 |
| 20261020_214112_191029 | `1a893ee7e97f4e8b86450665aa830167` | 2014 | calibration_completed | 2014 | 81 | 1541 | 301 | insufficient_0_5s_history 151; outside_proximity_domain 20; ended 1 |
| 20261020_214149_759405 | `19534b8d13dc4274863daabdd9dc0e05` | 1063 | edge_exit | 1063 | 68 | 613 | 301 | insufficient_0_5s_history 90; outside_proximity_domain 58; ended 1 |
| 20261020_214210_571969 | `e8e6e4276c9947cf9b68a14f929139e7` | 1875 | calibration_completed | 1875 | 36 | 1422 | 302 | insufficient_0_5s_history 150; ended 1 |
| 20261020_214244_551605 | `47823c251f904955be573d9c446875ff` | 2014 | calibration_completed | 2014 | 39 | 1561 | 301 | insufficient_0_5s_history 151; ended 1 |
| 20261020_214320_667777 | `9b554aafb07f42e6829eea9abe97a2ac` | 1927 | calibration_completed | 1927 | 54 | 1473 | 302 | insufficient_0_5s_history 151; ended 1 |
| 20261020_214354_584139 | `aa9c12a7604d4d468df13244c1118b05` | 2445 | calibration_completed | 2445 | 67 | 1810 | 302 | insufficient_0_5s_history 151; outside_proximity_domain 181; ended 1 |
| 20261020_214437_062477 | `b3fa6018951a4a98ae34dc3253f5109e` | 1180 | edge_exit | 1180 | 43 | 717 | 302 | insufficient_0_5s_history 92; outside_proximity_domain 68; ended 1 |

All nine runs have at least one `active=true` shadow record. The `unsupported_or_calibration_phase` rows are confined to the initial platform-scale segment; they do not persist after gameplay scale is reached. Each run also has an `ended` terminal shadow record. The actual schema has `causal_available`; it has no `available` field.

`shadow_sequence` is continuous across the shared file. Per run, the shadow record total happens to equal the Unity row total, but the records are not a one-to-one packet mapping: `input_sequence` covers 1 through N−1, and the final `ended` record repeats the N−1 input key as a terminal annotation. The raw Unity `ended` sample at sequence N is represented by that annotation, not by an input packet with sequence N. Shadow input timestamps have no gaps above 100 ms.

## Exact scale-gate alignment

Each shadow record was compared to the raw Unity row using exact `run_id`, `input_sequence` ↔ `sequence`, and `input_source_timestamp` ↔ `source_timestamp` (numeric timestamps rounded to microsecond precision). The nine runs have 15,093 Unity rows and 15,093 shadow records total. One-to-one triple-key matches cover the 15,084 nonterminal source packets (sum of N−1 per run); the other nine shadow records are `ended` annotations that repeat each run's N−1 source key. Thus there are nine unmatched raw Unity terminal rows at sequence N, and the nine terminal annotations are not additional source samples. For every run, `unsupported_or_calibration_phase` forms one contiguous prefix. Every such row has `platform_level=1`, `selected_session_layers=5`, and `platform_scale=15.884458541870117` (min=max=most common value). The first raw sample with `0 < platform_scale <= 2` has scale about 0.85. No matched row at scale ≤2 has reason `unsupported_or_calibration_phase`.

| Session | Unsupported `input_sequence` range | Relative source-time range (s) | Unsupported scale min=max=mode | First scale ≤2 (`sequence`, t rel s) | First `causal_available=true` (`input_sequence`, t rel s) | Unsupported after scale ≤2 |
|---|---|---|---:|---|---|---:|
| 20261020_214022_086000 | 1–299 | 0.000–4.983 | 15.8844585 | 300, 5.000 | 331, 5.519 | 0 |
| 20261020_214100_600233 | 1–302 | 0.000–5.006 | 15.8844585 | 303, 5.026 | 333, 5.527 | 0 |
| 20261020_214112_191029 | 1–301 | 0.000–4.998 | 15.8844585 | 302, 5.018 | 332, 5.519 | 0 |
| 20261020_214149_759405 | 1–301 | 0.000–4.998 | 15.8844585 | 302, 5.012 | 332, 5.518 | 0 |
| 20261020_214210_571969 | 1–302 | 0.000–4.998 | 15.8844585 | 303, 5.012 | 333, 5.518 | 0 |
| 20261020_214244_551605 | 1–301 | 0.000–4.984 | 15.8844585 | 302, 5.005 | 332, 5.505 | 0 |
| 20261020_214320_667777 | 1–302 | 0.000–4.998 | 15.8844585 | 303, 5.019 | 333, 5.519 | 0 |
| 20261020_214354_584139 | 1–302 | 0.000–5.007 | 15.8844585 | 303, 5.019 | 409, 6.790 | 0 |
| 20261020_214437_062477 | 1–302 | 0.000–5.006 | 15.8844585 | 303, 5.020 | 333, 5.520 | 0 |

The code path used by the receiver supports this attribution: `UDPRecevier.py` imports `ProximityShadow` from `parallel_20261014/proximity_shadow_backend_luna`; that module imports `normalize_unity_packet` from `parallel_20261010/backend/runtime_adapter.py`. The adapter defines `gameplay_phase_valid` with a finite scale condition `0 < scale <= 2` (line 47) and returns `unsupported_or_calibration_phase` when that predicate is false (line 58). Its earlier geometry and ownership checks precede this phase check. In these raw rows, layer 1 is within the selected 5 layers, while scale is 15.8845, so the scale clause is the mismatching phase criterion. After scale falls to about 0.85, the unsupported reason disappears. This is strong direct alignment between telemetry and the receiver's imported adapter rule, not evidence that an experimental display/banner was or was not shown.

The first causally available row comes later than scale transition because history/domain reasons remain: eight runs become available at input sequence 331–333; session 20261020_214354_584139 first becomes available at 409 after its outside-proximity-domain interval. These are distinct from the scale-gate reason.

The primary agent relayed the user's confirmation that these nine sessions continue with the P03 participant, and that the participant saw the banner with sensitivity 0.55. This is user-confirmed context relayed by the primary agent, not a measurement in the CSV. `active=true` is shadow telemetry and does not by itself establish the displayed banner; the reported observation is separate user evidence.

## Provenance

`input_sha256.json` contains before/after SHA-256 hashes for all nine raw CSVs and the shared shadow log. Values are identical. The shared log was matched exclusively by these nine exact Unity run IDs; unrelated records in that file were excluded.
