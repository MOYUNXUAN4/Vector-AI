# Warning reply ordering: primary acceptance

Implemented on 2026-10-11. Scope: bridge metadata/fallbacks and tests/documentation ONLY. No Unity files, original data, model/threshold, runtime feature code, alarm policy, UDP ports or send cadence changed. No listener/service was started.

Implementation by GPT-6 Luna; protocol decisions and independent review by primary. Changed production file: bridge.py. New test files: test_warning_order.py and test_warning_order_primary.py. Existing README documents the additive change; WARNING_ORDER_PROTOCOL.md is a self-contained Unity handoff.

Each enabled reply construction receives a globally increasing positive signed-64-compatible warning_update_sequence within the bridge lifetime. Normal and fault/UNKNOWN branches are all covered. This does not change prediction_sequence or confer new prediction freshness. No reset on run/layer transition. Signed64 exhaustion omits warning output without wrapping or breaking the legacy reply. Backend restart requires a fresh Unity run; transparent same-run backend restart is not implemented.

Fallback UNKNOWN now preserves available runtime identity and supplies neutral values for unknown identity. Explicit run IDs override stale runtime identities. Unknown geometry is never presented as safe.

## Verified by primary

- New ordering suite: 10/10 passed.
- Independent primary ordering suite: 2/2 passed, including a natively loaded model with locally overridden risk score to force real two-point STRONG, then stale UNKNOWN with identical prediction/input identity and a larger update sequence. The score override is a policy test, NOT performance evaluation.
- Existing bridge suite: 10/10 passed.
- Existing primary live/hook suite: 6/6 passed.
- Existing runtime suite: 86 passed, 1 skipped out of 87.
- Total: 115 tests executed; 114 passed, 1 skipped.
- bridge.py syntax compilation passed.
- Native model hash unchanged: 01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068.
- warning_runtime.py hash unchanged: a95cb6def1101e67b1c3c63c35e0924d36606caa7d076e241bc2b72b453672b3.

The initial independent fixture mistakenly compared the last evaluated input (sequence 37) with the later accepted input (39) exposed by stale UNKNOWN. The fixture was corrected to stop ingestion at the evaluated point. No production identity logic was changed to hide that difference; UNKNOWN may legitimately expose the last known input.

## Remaining acceptance

Unity must parse/order the new field according to WARNING_ORDER_PROTOCOL.md, without needing backend source access. Then perform real UDP STRONG appearance, recovery revocation, layer/Restart isolation and complete backend-stop expiry. This change solves reply ordering; it does not improve F1 or count as new model validation. No real UDP testing was performed in this change.
