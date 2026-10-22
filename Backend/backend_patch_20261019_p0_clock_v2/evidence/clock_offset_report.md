# Unity / wall-clock alignment audit

Per run. `offset range` is max-min over all samples; `drift` is the largest within-segment max-min. A gap is unsupported time even when the offset is stable.

| File | Run | Verdict | Offset range (s) | Drift (s) | Steps | Gaps | Lines |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| session_20261019_105632_058608 | 31870bd7101e45a29d78d179f82e06f0 | STEPPED | 0.162 | 0.019 | 1 | 1 | 4-2494 |
| session_20261019_105656_285619 | dc424922ab7a4438809dd72a4b308bb7 | CLEAN | 0.004 | 0.004 | 0 | 0 | 2-1491 |
| session_20261019_105712_007803 | f848f2248b7443d7b740b5b2eda42bc4 | STEPPED | 0.157 | 0.005 | 1 | 1 | 2-1733 |
| session_20261019_105734_310716 | b6f039d1c47a45e89c8f9dd9dd8967a9 | STEPPED | 0.128 | 0.007 | 2 | 1 | 2-665 |
| session_20261019_105912_781089 | 0d93af38d29a499487b66b0c9a6e2199 | CLEAN | 0.014 | 0.014 | 0 | 0 | 4-548 |
| session_20261019_105922_291656 | b0e336b2239b4a8b99d47cf72ef0b5d7 | STEPPED | 0.484 | 0.005 | 2 | 1 | 3-3093 |
| session_20261019_105951_117357 | 5c364258088d4dd2adfdb15e6830f185 | STEPPED | 0.160 | 0.005 | 1 | 1 | 2-3167 |
| session_20261019_110023_567130 | bbe4be8d4fbb4e74b192b0570c12707e | STEPPED | 0.502 | 0.005 | 2 | 1 | 2-3437 |
| session_20261019_110055_533132 | 70bdae08f81a4d1480b9f2b2ccd61125 | CLEAN | 0.004 | 0.004 | 0 | 0 | 3-903 |
| session_20261019_110107_096491 | 3074f1b0189744ad92cc26e1bec71fe0 | STEPPED | 0.167 | 0.004 | 1 | 1 | 2-3052 |

## session_20261019_105632_058608 / 31870bd7101e45a29d78d179f82e06f0

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1965 | 35.541 | +0.161 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1932 | 35.192..35.541 | 0.510 |

## session_20261019_105656_285619 / dc424922ab7a4438809dd72a4b308bb7

No offset step detected.

## session_20261019_105712_007803 / f848f2248b7443d7b740b5b2eda42bc4

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1678 | 71.093 | +0.155 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1645 | 70.753..71.093 | 0.494 |

## session_20261019_105734_310716 / b6f039d1c47a45e89c8f9dd9dd8967a9

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 174 | 77.036 | +0.071 |
| 665 | 85.181 | +0.053 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 157 | 76.694..77.036 | 0.413 |

## session_20261019_105912_781089 / 0d93af38d29a499487b66b0c9a6e2199

No offset step detected.

## session_20261019_105922_291656 / b0e336b2239b4a8b99d47cf72ef0b5d7

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1933 | 26.455 | +0.483 |
| 1934 | 26.788 | -0.325 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1900 | 26.440..26.455 | 0.498 |

## session_20261019_105951_117357 / 5c364258088d4dd2adfdb15e6830f185

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1956 | 54.786 | +0.159 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1924 | 54.453..54.786 | 0.492 |

## session_20261019_110023_567130 / bbe4be8d4fbb4e74b192b0570c12707e

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1769 | 82.551 | +0.500 |
| 1770 | 82.884 | -0.325 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1735 | 82.535..82.551 | 0.515 |

## session_20261019_110055_533132 / 70bdae08f81a4d1480b9f2b2ccd61125

No offset step detected.

## session_20261019_110107_096491 / 3074f1b0189744ad92cc26e1bec71fe0

| After CSV line | Unity time (s) | Step (s) |
| ---: | ---: | ---: |
| 1936 | 124.825 | +0.165 |

| Gap after CSV line | Unity range | Seconds |
| ---: | --- | ---: |
| 1903 | 124.484..124.825 | 0.506 |
