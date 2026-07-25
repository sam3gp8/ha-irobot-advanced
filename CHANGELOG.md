# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Versioning policy.** This project stays in the `0.x` series until the live
> camera view streams video end-to-end. No `1.0.0` release before then —
> `0.x` signals that a headline feature is still incomplete. Releases keep
> incrementing within `0.x` (`0.5.0`, `0.6.0`, …) so updates remain
> distinguishable.

## [Unreleased]

### Planned

- **Live camera media path (blocks 1.0).** Control plane is done; the remaining
  work is a backend WebRTC peer (aiortc) or a go2rtc KVS-signalling source so
  the stream actually plays. Until this lands the project stays on `0.x`.
- Replace heuristic UMF layer parsing once enough map samples are available.

## [0.6.3] — 2026-07-24

Third live dump resolved both items left open in 0.6.2.

### Fixed

- **Obstacle snapshots now read from the right source.** The mission history and
  timeline carry no image URLs (confirmed: `mission_timeline_keys` has no image
  field). Obstacle captures are part of the omap (Mapping Metadata) API, as
  documented in the PyRoomba forensic research. The extractor now pulls them
  from omap spatial data instead of mission history.

### Confirmed working

- **Region names.** `region_object_keys` shows regions carry `id`, `name` and
  `region_type`; named rooms surface correctly. (13 regions detected on the test
  robot.)

### Note

- Obstacle extraction targets the correct API now, but the exact object/URL
  field names within omap spatial data are not yet confirmed against a real
  payload — `_extract_obstacles` probes the likely spellings. If snapshots stay
  empty on a robot that has reviewed obstacles, a diagnostics dump will pin the
  field names down.

## [0.6.2] — 2026-07-24

Verified against a second live dump on 0.6.1. The 0.6.1 fixes held:
`region_count` went from 0 to **13**, and the UMF now loads with
`regions`/`zones`/`keepoutzones` present.

### Fixed

- **Room select no longer hides unnamed regions.** It filtered options to
  regions with a `name`, so a map whose regions lack names would show nothing
  despite existing. Unnamed regions now appear as `Room N`, matching the card.

### Changed

- **Diagnostics goes one level deeper.** It now reports `region_object_keys`,
  `zone_object_keys` and `mission_timeline_keys`, so the region-name field and
  the obstacle-image location can be confirmed from a dump without pasting map
  data. These are the two items still open below.

### Still open

- Region **names**: the parsing path is correct (13 regions found), but whether
  this account's maps carry human names is not yet confirmed — the new
  `region_object_keys` in diagnostics will show it.
- Obstacle snapshots: still `obstacle_count: 0`. The mission `timeline` key is
  the likely home for obstacle images; `mission_timeline_keys` in the next dump
  will confirm.

## [0.6.1] — 2026-07-24

First release audited against a live j-series robot (sku j955020, HA 2026.7.3).
Several bugs that only surface on real hardware are fixed.

### Fixed

- **`cleanSchedule2` shape corrected against a real payload.** The inferred
  structure in 0.6.0 was wrong on every point. The real format groups multiple
  weekdays per entry (`start.day: [ints]`, 0=Sunday), uses `start.hour`/
  `start.min`, and carries the command — including any room targeting — inside a
  stringified `cmdStr`, not as sibling keys. Reading and writing now match what
  the robot stores, verified by round-trip against the live payload.
- **Wi-Fi signal sensor** now reports its unit as `dBm`, fixing a device-class
  validation error on HA 2026.7.
- **Battery deprecation.** The vacuum no longer sets `battery_level` or the
  `BATTERY` feature (removed in HA 2026.8). The dedicated battery sensor already
  covers it.
- **Fan speed now works on j/s-series robots.** These report no `suctionLevel`;
  the control now maps eco/standard/performance onto the `vacHigh`/`carpetBoost`
  pair the robot actually honours, for both reading and writing.
- **Sidebar panel and card buttons.** The card re-rendered its whole body on
  every state push, stealing clicks mid-render — which made the panel unusable.
  Rendering is now gated on a change signature, so the DOM (and its click
  targets) stays stable between updates.
- **Rooms empty despite stored maps.** The pmap→region path walked a versions
  list the API doesn't return in this shape; it now reads the active version and
  region data the pmap actually provides.
- Robot model surfaced on the device (`model_id`).

### Known, still open

- Obstacle snapshots remain empty: the images are not under the mission-summary
  keys probed today. Needs the mission-detail payload to locate them.
- Region names depend on the pmap detail endpoint returning them; confirmed the
  path, not yet the field names on this account.

## [0.6.0] — 2026-07-24

### Added

- **`cleanSchedule2` write support.** The `set_schedule` service now produces
  the newer room-aware schedule format when a slot includes `pmap_id`/`regions`
  (or when `use_v2: true` is passed). Time-only schedules continue to use the
  proven legacy `cleanSchedule` format.
- A dedicated `schedule.py` module with lossless legacy parsing/building and
  tolerant `cleanSchedule2` handling that accepts several key spellings.
- The schedule sensor now summarises either format, including a count of
  room-specific days.
- Buy Me a Coffee support link (badge, README section, and repository Sponsor
  button via `.github/FUNDING.yml`).

### Notes

- The `cleanSchedule2` object shape is **inferred** from the app's schema field
  cluster (`CleanScheduleMultipleMapping`, `Enabled`, `StartTime`, `Cycle`),
  not from a captured payload — the app builds it in a serializer layer that
  isn't statically recoverable. Writes are conservative: legacy is the default,
  v2 is opt-in, and the inferred keys are marked with `TODO(confirm-with-sample)`
  in `schedule.py`. A real `cleanSchedule2` payload (visible in a diagnostics
  dump once cloud access works) will confirm or correct the shape. This is why
  the project remains on `0.x`.

## [0.5.0] — 2026-07-24

### Added

- **Live camera control plane (KVS WebRTC).** `live_view.py` now implements the
  full AWS Kinesis Video Streams viewer handshake: `DescribeSignalingChannel`,
  `GetSignalingChannelEndpoint` (role VIEWER), `GetIceServerConfig`, and a
  presigned WSS signalling URL — all SigV4-signed with the account credentials.
- **Presigned-URL signing** added to `sigv4.py` (`presign_url`), verified to
  carry every required `X-Amz-*` query parameter including `ChannelARN` and
  `ClientId`.
- **Live camera entity** (`camera.*_live`, disabled by default) that starts and
  stops the robot's camera and exposes the resolved endpoints and ICE-server
  count as attributes.
- **`get_live_view_config` service** returning the viewer configuration
  (signalling endpoint + ICE servers) so the stream can be driven by an
  external WebRTC tool while the in-process media path is finished.

### Notes

- The KVS control-plane calls use the standard public AWS API and are
  implemented directly, not reverse engineered.
- **The media path is not yet end-to-end.** KVS uses a bidirectional
  signalling WebSocket with the robot as master originating the SDP offer,
  which does not map onto Home Assistant's simple offer/answer WebRTC provider.
  Completing playback needs a backend WebRTC peer (aiortc) or a go2rtc source
  that speaks KVS signalling; the live camera entity therefore does not yet
  advertise a stream it cannot honour. The handshake data is fully resolved and
  available via the service in the meantime.

## [0.4.0] — 2026-07-24

### Added

- **Self-served brand icons.** The integration now ships its icon and logo in an
  in-tree `brand/` folder, which Home Assistant 2026.3+ serves natively via its
  brands proxy — no submission to the `home-assistant/brands` repository
  required. Light and dark variants (`icon.png`, `dark_icon.png`, `logo.png`,
  `dark_logo.png`, plus `@2x` versions) are included.
- The dashboard card requests the icon from Home Assistant's brands proxy and
  falls back to a bundled copy on older cores.

### Removed

- The top-level `brands/` folder and its manual-submission instructions, made
  obsolete by native brand serving.

### Notes

- Native icon serving requires Home Assistant 2026.3 or newer. On older
  versions the integration page shows a generic icon; the dashboard card shows
  the iRobot mark regardless. The integration's minimum supported version is
  unchanged at 2025.1.

## [0.3.1] — 2026-07-24

### Fixed

- **CI is green.** Ruff findings resolved (combined nested `with`, exception
  classes renamed to the `*Error` convention, `contextlib.suppress`, list
  comprehensions). hassfest and HACS now run with `ignore: brands`, since the
  integration's brand assets are not yet in the `home-assistant/brands`
  repository — every other check still runs.
- Manifest keys reordered to the sequence hassfest expects.

### Added

- Brand icon and logo (`brands/`), sized for a `home-assistant/brands`
  submission, plus instructions in `brands/README.md`.
- The dashboard card header now shows the iRobot icon.
- `pyproject.toml` pins the Ruff ruleset so local and CI linting match.
- `.gitignore` keeps `__pycache__` and build artifacts out of the repo (a stale
  `.pyc` had been tripping the linter).

## [0.3.0] — 2026-07-24

### Added

- **Dashboard card** (`custom:irobot-advanced-card`) with Control, Map,
  Obstacles and History tabs — commands, suction level, per-room cleaning
  chips, the live map, a clickable obstacle gallery, and recent mission
  records.
- **Sidebar panel** showing every configured robot on one page.
- The card is served from the integration itself and registered as a frontend
  module, so it appears in the Lovelace card picker with no separate plugin
  install.
- `sensor.*_total_missions` now carries a `recent_missions` attribute holding
  the ten most recent runs, trimmed to the fields the card renders.

## [0.2.2] — 2026-07-24

### Fixed

- `OptionsFlow` no longer assigns `self.config_entry` in its constructor. That
  attribute is a read-only property on current Home Assistant releases, so
  opening the integration's options raised `AttributeError` — the same class of
  bug as the coordinator's `name` in 0.2.1.
- Discovery service-info imports fall back to their pre-2025.1 locations
  instead of raising at import time, which surfaced in the UI as
  "Config flow could not be loaded: 500 Internal Server Error".

### Changed

- Minimum Home Assistant version corrected to **2025.1**. The previous floor of
  2024.10 was wrong: `VacuumActivity` and the `helpers.service_info` modules
  both arrived in 2025.1.

### Notes

- Upgrading in place can leave stale bytecode behind. If setup fails with a
  traceback whose line numbers don't match the installed files, remove
  `custom_components/irobot_advanced/__pycache__/` and fully restart Home
  Assistant — reloading the integration is not sufficient.

## [0.2.1] — 2026-07-24

### Fixed

- **Setup failed with `property 'name' of 'IRobotCoordinator' object has no
  setter`.** The coordinator exposed a read-only `name` property, which clashed
  with the `self.name` assignment in `DataUpdateCoordinator.__init__`. Renamed
  to `robot_name`. This blocked setup entirely on affected installs.
- The coordinator now passes `config_entry` to its parent constructor, which
  recent Home Assistant releases require before
  `async_config_entry_first_refresh()` will run.
- Added the missing `async_migrate_entry` handler. Config entries created by
  0.1.x declared schema version 1 while the flow advertised version 2, so those
  entries refused to load after upgrading.

## [0.2.0] — 2026-07-24

Cloud authentication is now fully automatic, and setup is largely hands-off.

### Added

- **Automatic sign-in.** The integration retrieves its identity-provider
  configuration from iRobot's unauthenticated discovery endpoint, authenticates
  with an account email and password, and renews credentials on its own.
- **Automatic local key provisioning.** The sign-in response includes each
  robot's local key, so HOME-button pairing is no longer required when signing
  in.
- **Auto-discovery** by DHCP hostname (`roomba-*`, `irobot-*`, `braava-*`) and
  by mDNS `_mqtt._tcp` advertisement.
- **Zero-prompt setup for additional robots.** When one robot from an account is
  already configured, discovered siblings reuse the stored credentials and are
  added without any questions. Remaining robots are queued as discovered devices
  after the first is added.
- **Shared authentication.** All robots on one account share a single sign-in
  and a single credential-refresh cycle, instead of one per robot.
- **Reauthentication flow** when the account password changes.
- **Reconfigure flow** for changing a robot's IP address without removing it.
- **Diagnostics** with credentials, BLIDs, MAC addresses and network names
  redacted, including the field names returned by the cloud to aid debugging.
- `sigv4.py`, a dependency-free AWS Signature V4 signer, verified against AWS's
  published `get-vanilla` test vector.
- CI running Home Assistant hassfest, HACS validation and Ruff.

### Changed

- **BREAKING.** Cloud access no longer uses a manually captured bearer token.
  Existing entries are migrated automatically: the token is discarded and cloud
  features are switched off. Re-enable them from the integration options by
  signing in. Local control is unaffected.
- Cloud requests are now AWS SigV4-signed against API Gateway rather than sent
  with a bearer token — the previous approach would have been rejected by the
  service.
- The API Gateway stage is taken from the discovered endpoint rather than
  hardcoded, so non-default deployments work.
- DHCP discovery updates a robot's stored IP address in place when its lease
  changes.
- Config entry schema version raised to 2.

### Documentation

- README rewritten for a general audience.
- `PROTOCOL.md` section 2 rewritten: the identity-provider key is absent from
  the application binary but is served by the discovery endpoint, so no traffic
  interception is needed.

## [0.1.0] — 2026-07-23

Initial release.

### Added

- Local-push control over the robot's LAN MQTT interface, including UDP
  discovery, the HOME-button key exchange, and a persistent TLS session.
- `vacuum` entity with full state machine, fan speed and raw command
  passthrough.
- 13 sensors: battery, phase, cycle, error, area cleaned, mission runtime, last
  mission start, total missions, total runtime, Wi-Fi signal, obstacle count,
  map count and schedule.
- 6 binary sensors and 5 configuration switches.
- `select` entity for starting a room-targeted clean.
- Map camera rendering the persistent map with the robot's live position.
- Five rolling obstacle snapshot `image` entities.
- Services: `clean_rooms`, `set_schedule`, `empty_bin`, `locate_robot` and
  `refresh_maps`.
- `PROTOCOL.md` documenting the discovery, MQTT, map, schedule and live-view
  protocols.

[Unreleased]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.6.3...HEAD
[0.6.3]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sam3gp8/ha-irobot-advanced/releases/tag/v0.1.0
