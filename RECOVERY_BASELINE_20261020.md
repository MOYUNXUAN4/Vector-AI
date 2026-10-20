# Recoverable current-state snapshot (2026-10-20)

This commit records existing project work, not a newly approved gameplay, model,
performance or participant-collection release. It is not a claim that all changes
since the initial commit have been independently reviewed or validated.

## Limited Git scope

- Custom Assets C# sources, Editor tools, tests and assembly definitions, with their
  existing Unity metadata and parent-folder metadata.
- Active Stage scenes, falling-platform and car prefabs, calibration-platform
  source asset, rendering/build settings, ProjectSettings and package version locks.
- This recovery note and existing repository ignore/attributes files if present.

Historical model/texture/font changes, recovery scenes, profiler recordings,
generated caches and the local third-party Editor bridge are not swept into this
commit. The external source snapshot additionally preserves the complete existing
Assets, Packages and ProjectSettings trees, including files outside this Git scope.
Use that snapshot for a byte-for-byte reconstruction of the current source project.

## Recovery boundaries

The external snapshot includes a per-file SHA-256 manifest, exact scoped-file list,
Git history bundle and verification receipt. Restore into a NEW directory, verify
the bundle and file hashes, then open with Unity 6000.3.9f1. Do not overwrite an
active working project or use a hard reset as a routine restore method.

Library, Temp, Logs, obj, ProfilerCaptures, UserSettings, machine registry state,
backend/data directories and deployed game executables are outside the source
snapshot. Package locks retain dependency versions but do not vendor every remote
registry/Git dependency. Runtime sensitivity and device calibration must be checked
separately after restore; they are not guaranteed by source-file recovery.

The unified UI experiment is default-off in code. This snapshot does not enable it,
change saved scenes, apply staged patches, rebuild the collection game or change
the backend model and thresholds. Previously reported tests are evidence only for
their stated scope, not acceptance of the whole current workspace.
