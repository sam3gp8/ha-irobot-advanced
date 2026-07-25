# Hard audit — v0.6.0 against a live j9 (sku j955020, HA 2026.7.3)

Findings from the diagnostics dump of a real connected robot. Grouped by
severity. Each has a verdict and a fix plan.

## What actually works (confirmed from the dump)

- **Local connection is solid.** `data.local.connected: true`, full shadow
  state flowing: `batPct`, `cleanMissionStatus`, `bin`, `signal`, `bbrun`,
  `cleanSchedule2`, `pmaps`, `dock`, etc. The core local protocol is correct.
- **Cloud auth works.** `data.cloud.enabled: true`, `error: null`,
  `region: us-east-1`, `mission_count: 41`, `pmap_count: 3`. The Gigya →
  `/v2/login` → SigV4 chain built in 0.2.0 is functioning against the live API.
- **Dashboard commands work** (start/stop/dock/suction confirmed by user),
  except fan speed — see BUG 3.

## BUG 1 — Wi-Fi signal sensor crashes validation (confirmed in logs)

`signal_strength` device class with `native_unit_of_measurement = None`. HA
2026.7 rejects it: *"None is not a valid unit … expected one of ['dBm','dB']"*.
The robot reports `signal.rssi: -71` (dBm). The sensor reads `signal.rssi`
already but never sets the unit.

**Fix:** set `native_unit_of_measurement = "dBm"` on the wifi_signal sensor.

## BUG 2 — battery_level on the vacuum is deprecated (confirmed in logs)

*"setting the battery_level which has been deprecated … stops working in
2026.8."* Same for the `BATTERY` supported feature. HA now wants a dedicated
battery **sensor** linked to the device.

**Fix:** drop `VacuumEntityFeature.BATTERY` and the `battery_level` property
from the vacuum. A `battery` sensor already exists in sensor.py, so the data is
covered — just stop the vacuum from advertising it.

## BUG 3 — Fan speed button dead on the dashboard (confirmed by user)

The card sends `vacuum.set_fan_speed` with the current fan_speed_list. But the
vacuum's `fan_speed` maps from `suctionLevel`, and this j-series robot does not
report `suctionLevel` — it uses `vacHigh: true` + `carpetBoost: false`. So
`fan_speed` is computed but `set_fan_speed` writes `suctionLevel`, which the
robot ignores. The button "does nothing" because the write is a no-op on this
model.

**Fix:** on models without `suctionLevel`, translate fan speed to the
`vacHigh`/`carpetBoost` pair the robot actually honours (eco = both false,
standard = vacHigh false + carpetBoost true → auto, performance = vacHigh true).

## BUG 4 — Sidebar panel buttons all dead (confirmed by user)

Root cause: the card's `set hass` calls `_render()` on **every** state update,
which rewrites `body.innerHTML` wholesale. The panel pushes a fresh `hass` on
every tick, so the body is continuously torn down and rebuilt. A click frequently
lands on a node that is replaced microseconds later, so the handler never fires
— or fires against a stale closure. In a dashboard card the update rate is lower
so it *sometimes* works; in the panel it never does.

**Fix:** stop re-rendering the whole body on every hass update. Render the
structure once; on updates only patch the dynamic bits (status text, battery,
active states). Crucially, do **not** rebuild the tab body unless the tab or the
underlying data actually changed. Event handlers are already delegated on a
stable parent, so keeping that parent alive fixes the clicks.

## BUG 5 — 0 rooms despite 3 stored maps — FIXED (0.6.1) ✓

**Confirmed resolved by the second dump: `region_count: 13`, and
`umf_top_level_keys` now shows `regions`, `zones`, `keepoutzones`,
`observed_zones`, `map_header` — the UMF loads and regions parse.** Original
analysis below, kept for the record.



Two compounding problems:

1. **pmap versions/UMF shape mismatch.** `async_refresh_cloud` calls
   `async_get_pmap_versions` then reads `versions[0]`. The real pmap object
   (`pmap_keys`) has `active_pmapv_id` / `active_pmapv_details` /
   `user_pmapv_id` — there is no separate "versions" list in the shape we got.
   The code is walking a structure the API doesn't return here, so
   `pmap_details` stays empty and `regions` is empty.
2. **`umf_top_level_keys: []`** — no UMF was ever fetched, confirming the chain
   above never reached `async_get_pmap_umf`.

**Fix:** rework the pmap→regions path against the real shape. The pmap carries
`active_pmapv_id`; regions come from the pmap detail endpoint, not a `regions`
key on a UMF blob we never loaded. This is Session 3 territory (UMF), now
unblocked by real data — see below.

## BUG 6 — cleanSchedule2 — FIXED (0.6.1) ✓

Real sample captured and the format rewritten to match; round-trips against the
live payload. Original (wrong) inference documented below.



The real payload:

```json
[{"enabled": true, "type": 0,
  "start": {"day": [3,4,5,6], "hour": 12, "min": 30},
  "cmdStr": "{'command':'start','params':{...},'time':...,'initiator':'schedule'}"}]
```

My inferred shape was per-day objects with `start_time:{h,m}` and
`pmap_id`/`regions`. **All three guesses were wrong:**

- entries group **multiple days into one** via `start.day: [int,...]` (0=Sun),
  not one entry per day;
- time is `start.hour` / `start.min`, not `start_time.{h,m}`;
- there is no `pmap_id`/`regions` on a schedule entry — room targeting rides
  inside `cmdStr`, a stringified command blob;
- `type: 0` and a `cmdStr` carrying the full start command are required.

**Fix:** rewrite `build_v2`/`parse_v2` to the real schema. This is the single
most valuable outcome of the dump.

## BUG 7 — obstacle snapshots empty (obstacle_count 0)

`imgUpload: 1` and rich `missionTelemetry` exist, but `obstacle_count: 0` and
`mission_keys` shows the obstacle data is not under the keys the extractor
probes (`obstacles`/`hazards`/`imageUploads`/`detections`). The mission object
has `timeline`, `pmaps_info`, `flags`, `dirt` — obstacle images likely hang off
the `timeline` sub-structure or a per-mission detail endpoint, not the mission
summary. Needs the mission **detail** shape, not present in this dump.

**Verdict:** leave the 5 obstacle image slots but stop showing them when empty;
revisit once a mission-detail payload is available.

## BUG 8 — cosmetics from the dump

- `sku: j955020`, `softwareVer: ruby+24.29.1` — a j9-class robot. Model string
  should surface on the device (currently only sku).
- The card map image alt-text shows a broken-image glyph before load — add a
  loading state.
