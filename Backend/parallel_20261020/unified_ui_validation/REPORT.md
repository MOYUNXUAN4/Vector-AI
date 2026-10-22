# Default-off unified risk UI validation

Date: 2026-10-20. Scope: display-only Unity implementation and synthetic verification.

## Implementation

Changed `Assets/Endness Falling/Scripts/UIManager.cs`; added `Assets/Endness Falling/Tests/Editor/UnifiedRiskPresentationTests.cs` and Unity-generated metadata.

`enableUnifiedRiskPresentation` is serialized and defaults to false. When false, the existing three experimental banner drawing paths remain in use. No scene or collection build was updated.

When enabled, one panel independently lists currently valid AI prediction, TTE rule, geometry danger, and native local edge-warning sources. Native edge state is read from the current active player, without relying on backend availability or debug-HUD visibility. Existing receiver getters retain their confirmation, validity, identity and timeout gates. The UI adds no hold, confirmation, geometry query, probability inference or recovery declaration. A withdrawn AI source removes its probability even when another source remains active. Label/style caches avoid unnecessary repeated construction; no runtime allocation reduction is claimed from this verification.

## Verification

- Unity compilation: successful; final bridge compile result `ok`.
- Edit Mode suite: **180 passed / 180 total**, 0 failed, skipped or inconclusive; UI tests 48, receiver tests 132. Final run ID `a0750bffbddc43f28c244624aa574838`; see `tests_final.json`.
- Actual IMGUI rendering exercised in an isolated temporary Editor window, using synthetic source states and inactive components in a preview scene. Screenshots captured from the window's own Unity render surface, not desktop pixels. All three pages were visually reviewed: `visual_page_1.png`, `visual_page_2.png`, `visual_page_3.png`. Checks include independent and combined sources, removal of stale AI probability, all withdrawn, and 300-pixel-width wrapping.
- Temporary probe/window closed. Final Editor status: Edit Mode, LogIn scene.

## Protection checks

SHA-256 unchanged against the start-of-turn snapshot for UDPManager, UdpFrontendReceiver, LevelManager, EndlessPlayerController, EndlessFallingGeometryDiagnostics, EndlessFalling scene and LogIn scene (7/7). Stored timestamp ticks passed through JavaScript numeric serialization and are not used as exact timestamp evidence; byte hashes are authoritative here.

All 24 backend preflight-lock entries match. All 5 existing standalone collection manifest entries match: executable, UnityPlayer.dll, Assembly-CSharp.dll, globalgamemanagers and boot.config. No lock relaxation, backend startup, model/threshold change, standalone rebuild or deployment occurred.

Targeted Git checks show UIManager was already modified and the new test/metadata are untracked. Full-file `git diff --check` reports whitespace in other existing portions of this dirty UIManager; these were not globally reformatted or overwritten.

## Boundaries

This is not real UDP, physical-board, Play Mode end-to-end, collection-build or runtime performance acceptance. The new display is not enabled in saved scenes. Existing data, models, thresholds, gameplay and collection version remain unchanged. Any later activation during participant collection must be treated as a deliberate presentation-version change, not silently mixed with existing sessions.
