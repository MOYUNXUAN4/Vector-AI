# Strong alarm policy

`StrongAlarmPolicy(threshold)` requires an explicit finite threshold in `[0, 1]`.
Call `.reset()` at stream or generation boundaries, then call
`.step(probability, clearance, timestamp, context, joint_recovery=False)` for
each decision point. `context` is a stable tuple containing the caller's run,
platform, layer, geometry version, and segment token; it must be nonempty and
cannot be a string or `None`. A changed token resets
confirmation and active alarm state. Timestamps must be strictly increasing;
duplicate or out-of-order points are ignored (`accepted=False`).

Each accepted result is a dictionary with `state`, `raw`, `confirmed`,
`active`, `canceled`, `reason`, and `accepted`. `SAFE` means only that this
model policy is not currently alarming; it does not assert physical safety.
Invalid or boolean probability, clearance, or timestamp, or a non-boolean
`joint_recovery` flag resets the policy and returns `UNKNOWN`. A valid raw alarm requires `probability >= threshold` and finite
positive clearance. Two consecutive qualifying decision points no more than
0.1 seconds apart confirm `STRONG`; any raw OFF point immediately clears it.
There is no hold or hysteresis.

`joint_recovery=True` suppresses an active alarm on that row and emits
`canceled=True` only when the previous post-cancellation state was active.
Raw confirmation continuity still advances during recovery, matching the
reviewed offline order of operations.

`compute_recovery(samples)` accepts chronological mappings with engine-converted
`timestamp` and `clearance`, plus `ball_radial_velocity`. It returns the reviewed
causal recovery metrics and flag. Invalid values, duplicate or reverse time,
or any adjacent gap above `0.1 + 1e-9` fail closed without recovery. The input
should include contiguous history older than 0.1 seconds; the algorithm retains longer inward durations and
requires inward velocity below `-0.05`, contiguous coverage for at least 0.1
seconds, positive latest clearance, and clearance gain of at least `0.02` over
a source sample at least 0.1 seconds earlier. COP-only evidence is not used.

Run the focused policy tests with:

```powershell
& 'C:\Users\QIYUXUAN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest 'C:\Users\QIYUXUAN\Desktop\fyp_Backend (3)\fyp_Backend\parallel_20261010\backend\test_alarm_policy.py'
```
