# Falling realtime warning bridge

## Master startup update (2026-10-12)

The master-server entry point now opts in by default and calls public
`preload()` before starting Falling UDP reception. It passes that same bridge
into `UDPRecevier.start_backend(warning_bridge=...)`; Start/Restart does not
reload the native model or reset the reply counter. Only the master entry
defaults both model enablement and audited three-layer compatibility to ON.
The direct standalone receiver and `bridge_from_environment()` retain their
previous default-OFF semantics. Explicit environment values such as `0`,
`false` or `off` override the master defaults. A missing/failed model is
reported as unavailable and does not authorize an experimental prediction.

Double-click project-root `Start_Master_With_Model.cmd` to use the verified
Python 3.14 executable and the correct backend copy. No manual opt-in command
is needed for normal master startup. The launcher does not modify inherited
environment overrides, so a deliberately disabled model stays disabled.
Look for `[EXPERIMENTAL] Falling warning model loaded:` with the locked model
ID. The old aggregate `All 4 ... online` banner is not proof of model loading
or individual service health. Unity's independent display switch must still
be enabled, and only the audited three-layer gameplay is eligible, not an
arbitrary 25-layer run. Restarting the backend requires a new Unity run.

The implementation was tested without opening live listeners. Real gameplay
acceptance is planned separately in `../LIVE_ACCEPTANCE_1012.md`.

This bridge is experimental and disabled by default. It consumes the live
Falling `UDPRecevier.py` `unity_game` packets and adds `model_warning` to the
existing `realtime` response. It does not change RMSE, difficulty, the Q-agent,
COP values, or logger inputs. Both the calibration (`passedCount == 0`) and
ordinary reply paths attach the same additive field when enabled. With the
default configuration, the existing response dictionary is returned unchanged
and the model runtime is not imported or loaded.

Enable it for an explicit run with:

```powershell
$env:FALLING_WARNING_MODEL_ENABLED = "1"
```

The native LightGBM artifact is hash pinned to
`01addaa225b0400cea73069adbb070ffb54d8209f87e4bcb75781a01a0536068`.
Artifact/import/inference failures leave warning state `UNKNOWN`; they do not
stop gameplay. Experimental calibration-session compatibility has its own
opt-in and remains off unless `FALLING_WARNING_ALLOW_CALIBRATION_GAMEPLAY=1`.

Lifecycle ownership follows the live receiver's explicit `start_session`
command and its `run_id` from `UdpFrontendReceiver.SendStartSession`. The
bridge binds to that exact ID before accepting telemetry. Duplicate start
commands for the active ID are idempotent; a fresh ID ends the old run and
starts the new one without restarting the backend. Missing IDs leave warning
ownership unset, and previously closed IDs cannot reclaim ownership. Gameplay
packets never switch the owner. Old or out-of-order packets are ignored before
terminal/schema handling, so a delayed terminal packet cannot close a newer
stream. Invalid geometry or malformed owner telemetry resets the warning
segment to `UNKNOWN` but retains run ownership, allowing a later valid packet
from that run to warm up again. The Unity enum serializes its terminal state
as `ended`; other unknown or missing state values invalidate the warning
segment without closing the run. Invalid numeric timestamps do not advance
the ordering fence. A valid `ended` packet closes the owner.

The live receiver contains pre-existing local edits outside this bridge task.
The scoped hook changes in `UDPRecevier.py` are: lazy bridge initialization in
`start_backend`, a `start_session` lifecycle call, an early `unity_game` ingest
before the calibration early-return, and additive attachment at both existing
realtime sends. No full-file baseline copy was made.
Malformed-segment reset uses the warning runtime's internal stream-clear and
unknown-state helpers, coupling this bridge to the matching
`parallel_20261010/backend/warning_runtime.py` and `stream_guard.py` versions.

The bridge only changes the next outgoing realtime reply; it does not send
heartbeats. Consumers should honor the warning `feature_age_seconds` and treat
missing updates as stale. Run the focused checks from this directory with:

```powershell
python -m unittest -v test_bridge.py
```

## Ordered warning replies (2026-10-11)

Every enabled `attach()` reply now includes a positive C#-long-compatible
`model_warning.warning_update_sequence`. It orders reply construction, not
model inference, and advances for UNKNOWN/failure replies as well. It never
resets for run/layer changes within this bridge instance. Backend restart
starts a new counter and requires a fresh Unity run; same-run hot recovery is
not supported. Counter exhaustion omits `model_warning` without wrapping or
interrupting the legacy reply. Default OFF is unchanged.

Fallback UNKNOWN replies retain known runtime identity and supply neutral
values where identity is unavailable. They never declare unknown geometry
safe. This is an additive protocol change; model hash, threshold, feature
code, prediction sequence and alarm policy are unchanged.

Self-contained frontend contract and synthetic fixture:
`WARNING_ORDER_PROTOCOL.md`. The Unity agent does not need backend access.
The new suite is `test_warning_order.py`; independent primary checks are
`test_warning_order_primary.py`. Actual UDP HUD acceptance remains separate.
