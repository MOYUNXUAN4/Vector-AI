# Copilot Instructions for Endless Driver Tutorial

- Use Unity Editor version from `ProjectSettings/ProjectVersion.txt`: `m_EditorVersion: 6000.3.9f1`.
- Open the project folder in Unity Hub or via `Endless-Driver-Tutorial - EP9.sln`; restore packages from `Packages/manifest.json` before editing.

## Key runtime boundaries

- `Assets/Scenes/FypHub.unity` is the menu/hub scene.
- `Assets/Scenes/Stage.unity` is the main gameplay scene.
- `ProjectSettings/EditorBuildSettings.asset` includes both scenes in build order.
- `Assets/Scripts/UI/MainMenuCinematicRuntime.cs` is the menu bootstrapper; it persists across scene loads and dynamically reconstructs the menu UI and cinematic visuals.

## Major components

- `Assets/Scripts/Car/CarHandler.cs`: central player/AI car physics, input handling, audio, crash detection, and `OnPlayerCrashed` event.
- `Assets/Scripts/UI/UIHandler.cs`: game-over UI, distance display, restart logic, and event subscription to `CarHandler.OnPlayerCrashed`.
- `Assets/Scripts/AI/AICarSpawner.cs`: object-pooled traffic spawning, dynamic spawn cooldown, and speed adjustment based on player jitter.
- `Assets/Scripts/AI/AIHandler.cs`: AI steering and obstacle detection using `Physics.BoxCastNonAlloc`; AI cars lock to their spawn lane on enable.
- `Assets/Scripts/Endless/EndlessLevelHandler.cs` + `Assets/Scripts/Endless/EndlessSectionHandler.cs`: endless road section pooling and position smoothing near the player.
- `Assets/Scripts/SceneMenuWireup.cs`: button-to-scene wiring helper used in menus to avoid missing-script behavior.

## Project-specific conventions

- Tag-based player detection is pervasive: many scripts rely on `GameObject.FindGameObjectWithTag("Player")` and `CompareTag("Player")`.
- Scene names are hard-coded in `MainMenuCinematicRuntime.cs`: `FypHub` and `Stage`.
- `MainMenuCinematicRuntime` creates runtime `EventSystem`, `Canvas`, and camera fallback if absent.
- `UIHandler` will auto-find missing `CarHandler`/`Button` references at runtime when possible.
- `InputHandler` is designed to only remain on the `Player` object; it self-destructs on non-player instances.
- `ExplodeHandler.cs` detaches fragments and re-tags them as `CarPart`, so collision logic may depend on that tag.

## Useful patterns to preserve

- Prefer scene-based UI wiring through `SceneMenuWireup` rather than hard-coding button callbacks in the editor.
- Keep player/AI car behavior separated: `CarHandler` owns vehicle mechanics, while `InputHandler`/`AIHandler` owns control inputs.
- Maintain object pooling in `AICarSpawner` and endless section pooling in `EndlessLevelHandler`; avoid creating/destroying frequently.
- Keep `MainMenuCinematicRuntime` logic on the menu scene only; it intentionally hides itself when non-menu scenes load.

## Developer workflow notes

- There is no custom build or test script in repository; use Unity Play Mode for behavior verification.
- For code edits, use the generated solution file and let Unity recompile after changes.
- Use `Packages/manifest.json` to understand package dependencies: URP 17.3.0, Cinemachine, Test Framework, Visual Scripting, Unity AI packages.
- Use the Unity Editor to inspect scene object wiring; many serialized fields are expected to be assigned in the inspector.

## What to avoid

- Do not rename `FypHub` or `Stage` scenes without updating `MainMenuCinematicRuntime.cs`.
- Do not remove or change the `Player` tag on the main car without checking all `FindGameObjectWithTag("Player")` usage.
- Do not assume the menu UI is stored in scene assets; it is generated in code by `MainMenuCinematicRuntime`.

## Ask for clarification

If any workflow steps or scene assumptions are unclear, ask for:
- which scene should be the menu entry point,
- whether player input axes or restart hotkeys should change,
- whether new gameplay objects require runtime or inspector wiring.
