# Causal online feature kernel

`causal_features.compute_latest_features(samples)` computes the reviewed
24-feature vector for the newest observation in one already isolated,
chronological telemetry segment. It is a pure feature calculation: there is no
model inference, fitting, calibration, event classification, or packet
serialization in this module.

Each input mapping uses `source_timestamp` in seconds plus the geometry and
motion fields named by the feature kernel. The selected history uses the newest
sample at or before `latest_timestamp - 0.5`. Acceleration is differentiated
before history slicing, so the selected lower-boundary sample can use its
preceding sample. The 0.2-second inward displacement uses the equivalent
latest sample at or before `latest_timestamp - 0.2`. Samples must be strictly
increasing and adjacent gaps may not exceed 0.1 seconds.

The returned mapping begins with the 24 model features in the reviewed order.
It then includes `ready`, `not_ready_reason`, `history_start_timestamp`, and
`history_span_seconds`. A non-ready result carries NaN feature values; callers
must check `ready` and own any downstream JSON NaN conversion. Missing optional
velocity or position components retain NumPy NaN behavior, including the
reviewed `nansum` vector-consistency convention. Nonfinite distance or radial
velocity in the selected window prevents a ready vector. Current physical
radii must be finite and positive. Current tilt/difficulty can remain
NaN, as in the offline generator.

The parity tests import `telemetry_logs/Test10052/model_comparison_20261005/
prepare_features.py` as a module and call only its `feature_rows` function on
small synthetic dataframes. They compare all 24 fields, including NaNs, at
the latest matching offline decision. No raw telemetry files are opened and
the helper's `main()` is not called.

The offline selected model configurations vary by fold and model family; the
feature kernel deliberately has no embedded threshold, temporal confirmation,
or cancellation policy. Its scope is feature parity only. Epoch timestamps
serialized to milliseconds can also introduce ordinary floating-point rounding
differences at the sub-microsecond scale; parity assertions allow a 2e-10
absolute tolerance for synthetic epoch-second inputs.
