# Verified WiiBalanceWalker deployment

Verified on 2026-10-19. For the next session, use `Start_WiiBalanceWalker_Verified.cmd` in this directory. It checks the seven files in `deployment_manifest.json`, then checks executing instances with `Check_WiiInstance.ps1`. It does not start the Python backend or change board settings. An existing running program was not restarted by this repair.

Windows may retain an exited process entry with zero threads, zero handles and no window. A name-only tasklist check used to block startup on such an entry. The instance guard now ignores only an entry at least five seconds old that has zero threads and handles in two snapshots 250 ms apart with the same PID and creation time. Processes with threads, incomplete evidence or failed queries still block startup with their PID. The guard does not terminate a process or claim that the Windows residual entry was removed.

The existing root EXE, configuration and four DLLs are unchanged. The root PDB was replaced with its matching preserved artifact: CodeView/PDB GUID `725ee573-4908-4e80-b2c6-5530a0d3e433`, age 1. The manifest pins both hashes. `Verify_Deployment.ps1` checks file sizes/hashes against that trusted manifest and checks the recorded identity pair; its hash check does not independently parse symbol GUIDs on each launch. Actual GUID matching was checked during the 2026-10-19 repair.

Read-only check without launching:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Verify_Deployment.ps1
```

The original root PDB, old backup files, and stale `bin/x86/Release` output are recoverable under `archive_20261019_deployment_repair/`. Do not launch or copy EXEs from that archive, `obj`, or the preserved research artifact directory. The root deployment and verified launcher are the supported entry point. Archives are evidence, not current releases.

For a future build, produce EXE/PDB/config/dependencies together in a separate staging directory, compare symbols and run the required checks, then explicitly approve and update the deployment manifest. Do not make a mismatch pass by automatically refreshing hashes. `bin` is compiler output, not an authoritative deployment identity; copying whatever is already in it can restore an old version.

For a clean package, copy only the seven manifest-listed files, `deployment_manifest.json`, `Verify_Deployment.ps1`, `Check_WiiInstance.ps1`, `Start_WiiBalanceWalker_Verified.cmd`, this guide and the existing `README.txt` license/credits. Keep research archives, backups and build intermediates out of the package. This is an integrity inventory, not a signed package or proof of runtime behaviour, driver availability or historical source-to-binary equivalence. Source snapshots in the manifest are documented as unverified build provenance.

Telemetry and timing details: `WiiBalanceWalker-src/README_DIRECT_UDP.md`. Packet sending frequency, HID reports and UI/control updates are different quantities; record measured rates for each run.
