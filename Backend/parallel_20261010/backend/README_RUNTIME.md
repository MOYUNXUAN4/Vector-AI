# Isolated model-warning engine

This directory is a prototype, not an installed UDP service. Nothing here
changes Unity controls, the original yellow warning, or the live receiver.

## Activation contract

1. Freeze a reviewed deployment artifact and its manifest. A cross-validation
   fold is not a final deployment model. No historical artifact is auto-selected.
2. Construct `ModelWarningRuntime`. It starts disabled.
3. Call `load(manifest, pinnedhash, allow_experimental=True)` and check success.
   The independently supplied digest must identify the approved model bytes.
4. Explicitly enable and `begin_run(current_run_id)`. Do not discover ownership
   from an arbitrary UDP packet. Restart must explicitly begin a new run.
5. Pass Unity packets to `ingest(packet, time.monotonic())` in arrival order.
6. `attach(existing_realtime_packet, time.monotonic())` returns an additive
   copy. It does not send a packet or advance confirmation.

The model must have the exact 24 reviewed features, fixed training medians,
explicit calibrated threshold, binary LightGBM objective and matching hash.
Do not unpickle an unrelated legacy model or impute required geometry.

## Policy and output semantics

- A prediction is evaluated only on a new eligible input, at least 0.05 source
  seconds after the previous evaluation. This is a minimum cadence, not a
  promise of exactly 20 Hz under irregular input or load.
- Two consecutive evaluated points above threshold confirm strong warning.
  They must be at most 0.1 seconds apart in the same valid stream segment.
- Probability below threshold clears the alarm immediately. No added hold or
  hysteresis is used.
- Recovery cancellation requires inward ball velocity below -0.05 sustained
  for at least 0.1 seconds, positive clearance, and at least 0.02 clearance gain
  relative to the causal sample at least 0.1 seconds earlier. COP alone cannot
  cancel a warning. Raw confirmation continuity follows the reviewed offline
  policy even during recovery suppression.
- `SAFE` means **no active model alarm**, not that the ball is physically safe.
  Nonpositive clearance is outside model eligibility and outputs `UNKNOWN`;
  the existing geometric yellow warning must remain independent.
- Missing model, invalid identity, insufficient history, stream gaps, stale
  input, inference failure and disabled mode are not safety predictions.
- Source timestamps establish feature/decision order. Monotonic receipt time
  establishes freshness. Do not subtract clocks from different systems.
- Attention is not implemented here: there is no independently frozen
  attention target/artifact. Lowering the strong threshold does not create one.
- The 24-feature model does not consume COP. Adding COP requires a separate
  controlled model experiment and a freshness contract.

The nested `model_warning` is finite JSON with validity flags, model identity,
run/platform/layer/version, prediction input identity, probability and state.
Transition events are bounded in-memory evidence, not persistent telemetry.
Later integration must write them safely and add receiver-side expiry checks.

## Remaining deployment gates

Freeze/refit/export the approved model and one deployment threshold using only
development data; replay its predictions and states against offline references;
then attach to the live backend loop and add minimal opt-in Unity display.
Finally measure actual latency and test disconnect, Restart, layer transition,
completion and recovery in formal gameplay. Prototype tests do not establish
F1, earlier warnings, player benefit, or successful Unity integration.
