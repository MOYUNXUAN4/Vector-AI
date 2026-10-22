# Direct Wii Balance Board telemetry

Updated: 2026-10-19. WiiBalanceWalker sends UDP JSON directly to
`127.0.0.1:5005` using a separate `System.Threading.Timer` requested at 10 ms.
Earlier Windows checks observed about 60–64 packets/s; this is not a guaranteed
hardware sampling rate. Measure packet intervals for the actual recording.

The BalanceBoard HID callback updates the latest four-corner raw-weight snapshot.
The send timer reads that snapshot independently. The WinForms timer requested
at 20 ms updates the UI and control/action snapshot. The send timestamp and
sequence are generated at send time, not hardware acquisition time. A packet
may reuse a snapshot, but the duplicate proportion cannot be inferred from the
10 ms and 20 ms timer settings. Raw COP and issued controls are explicitly not
one-to-one; `wii_control_v1` includes its own sequence, timestamp and age.

Unity and vJoy are not relays for this direct telemetry path. HID report rate,
UI/control update rate, requested send period and measured packet rate must be
reported separately in analysis and papers.

Example packet:

```json
{
  "type": "wii_balance",
  "timestamp": "2026-10-19T00:00:00.0000000Z",
  "sequence": 1,
  "tl": 12.3,
  "tr": 11.9,
  "bl": 13.1,
  "br": 12.7,
  "weight": 50.0,
  "offset_tl": 12.0,
  "offset_tr": 11.6,
  "offset_bl": 12.8,
  "offset_br": 12.4,
  "ratio_tl": 24.0,
  "ratio_tr": 23.2,
  "ratio_bl": 25.6,
  "ratio_br": 24.8
}
```

The JSON example shows raw fields only; the actual packet also carries the
`wii_control_v1` fields. Missing/invalid controls must not be assumed to be
valid zero input.

The existing `UDPRecevier.py` accepts `type: "wii_balance"` packets on port
5005 and keeps the latest values in `latest_wii_balance`. It also includes the
latest sensor values in its normal realtime response packets.

Use the root `Start_WiiBalanceWalker_Verified.cmd` entry point and see
`../DEPLOYMENT_README.md` and `../deployment_manifest.json`. The stale pre-control
`bin/x86/Release` output was archived on 2026-10-19. Do not copy archived or
unverified `bin`/`obj` files into the root deployment.

Future builds need an isolated staging directory, a matching EXE/PDB identity
check, configuration/dependency verification and a reviewed deployment manifest.
Do not rebuild or change timer/control settings during an ongoing collection batch.
