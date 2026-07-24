# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Live camera view via AWS Kinesis Video Streams WebRTC — scaffold exists in
  `live_view.py`; the Kinesis control-plane calls remain
- Write support for `cleanSchedule2`, the newer room-aware schedule format
- Replace heuristic UMF layer parsing once enough map samples are available

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

[Unreleased]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/sam3gp8/ha-irobot-advanced/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sam3gp8/ha-irobot-advanced/releases/tag/v0.1.0
