# Balance-board data collection protocol

## Research target

The primary event is a Unity game-platform edge exit (`fall_event`), not a clinical or physical human fall.

## Existing analysis groups

- `normal_control`: successful ordinary gameplay; negative control.
- `directional_edge_exit`: smooth or turning movement that ends in a platform edge exit; positive edge-exit data.
- `sway_then_edge_exit`: strong front/back or left/right sway followed by an edge exit; positive dynamic-to-failure data.
- `dynamic_sway`: intense, high-frequency, multidirectional, or mixed sway; keep separate from smooth directional exits.
- `physical_off_board`: weight below 5 kg because the participant left the board; retain earlier valid normal windows only.
- `invalid_excluded`: failed tare or interrupted session; exclude.

## Missing condition

The key missing negative class is `recoverable_directional_shift`: the ball approaches an edge because the participant leans in one direction, but the participant corrects the motion before the ball exits. This is needed to distinguish dangerous-but-recoverable movement from imminent edge exit.

## Recommended next collection

Collect controlled, safe tests while keeping both feet on the board. Do not intentionally fall or leave the board.

| Condition | Tests | Procedure | Keep when |
|---|---:|---|---|
| `normal_control` | 5 | Play naturally and complete the game | No edge exit, no interruption, valid tare |
| `recoverable_directional_shift` | 4 per direction (16 total) | Lean toward left, right, front, and back until the ball is visibly near the edge, then correct and continue | Ball does not exit; record direction and approximate recovery level |
| `directional_edge_exit` | 3 per direction (12 total) | Maintain a controlled lean in one direction until the ball exits | Unity edge exit occurs; feet remain on board |
| `sway_no_exit` | 4 | Perform front/back, left/right, or multidirectional sway, then recover | Strong sway but no edge exit |
| `sway_then_edge_exit` | 2 per pattern (4-6) | Perform a specified sway pattern, then allow a controlled game edge exit | Edge exit occurs; no physical fall |

## Required note after every session

Record: session ID, condition, direction, whether the ball exited, whether recovery succeeded, platform level, and whether both feet stayed on the board. Mark tare failures and interruptions as excluded immediately.

## Analysis rule

Do not pool all positive sessions into one behavioral class. Compare normal control, recoverable directional shift, smooth directional edge exit, and sway-to-edge-exit separately before fitting a model.
