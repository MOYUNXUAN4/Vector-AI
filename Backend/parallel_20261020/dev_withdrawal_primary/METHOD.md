# Original-development withdrawal replay (20 October 2026)

Scope: 31 INPUT055_CHECK sessions, 7,553 existing ordered decision rows only.
No new labels, fits, threshold selection, model exports, production changes or
participant/holdout reads. Original source hashes must match the saved manifest.

The independent primary replay uses the existing pure StrongAlarmPolicy and
the pinned deployed 24-feature model, its existing medians and 0.65 threshold.
The separate TTE replay uses q = directional distance - 2*radius, q>0, v>0,
q/v<=0.75, binary probability threshold 0.5 and the same two-point policy.
Source-epoch timestamps are kept within their original continuity contexts;
no global Unity/epoch conversion or revised event labels are introduced.

Observe active-to-inactive decisions only across same-context adjacent decisions
with 0<dt<=0.100000001. Context/gap and end-of-file boundaries are censored,
not an observed withdrawal at that instant. Mechanism and motion are independent
axes. Instantaneous inward velocity <-0.05 is not sustained recovery; only the
existing joint_recovery flag supports that policy criterion. Still-outward
slowing is v>0 and v<previous decision v, not proof that danger persists or
the player deliberately corrected. No new tunable hold or recovery rule is tried.

This is saved-feature decision replay, NOT reconstruction of every raw packet,
receive-age guard, client lease, rendered banner or human intervention. Hash
verification of raw files does not validate historical clock alignment. Do not
report timing to a geometric event as newly validated from these traces. Do not
reinterpret unknown/nonentry labels as safe, or completion as successful rescue.
