# iRobot Advanced for Home Assistant

[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/sam3gp8/ha-irobot-advanced/actions/workflows/validate.yml/badge.svg)](https://github.com/sam3gp8/ha-irobot-advanced/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow.svg?logo=buymeacoffee)](https://www.buymeacoffee.com/sam3gp8)

A local-first Home Assistant integration for Wi-Fi iRobot vacuums and mops.
Maps, room-targeted cleaning, schedules, obstacle snapshots, and live robot
position — the things the app can do but the built-in integration doesn't
expose.

Control and state run **directly over your LAN**. The cloud is optional and only
used for data that genuinely lives there: map geometry, mission history and
obstacle images.

---

## Why this exists

Home Assistant ships a `roomba` integration that gives you start, stop, dock and
a battery percentage. That covers the basics, but everything the app is actually
useful for — the map, per-room cleaning, the photos of things your robot decided
not to run over, the schedule editor — goes through protocol paths that were
never wired up.

This integration implements those paths. The protocol was reconstructed from the
official Android app; the full write-up is in [PROTOCOL.md](PROTOCOL.md).

## Features

| | |
|---|---|
| **Local push** | State arrives over MQTT on your LAN. No polling, no cloud round-trip for control. |
| **Maps** | Persistent map rendered as a camera entity, with the robot's live position drawn on it. |
| **Room cleaning** | Clean named rooms via a service call or a `select` entity. |
| **Schedules** | Read and write the robot's weekly schedule from Home Assistant. |
| **Obstacle snapshots** | The photos the robot takes of obstacles, as `image` entities. |
| **Auto-discovery** | Robots are found via DHCP hostname and mDNS. Usually nothing to configure. |
| **Automatic sign-in** | No token capture, no proxying, nothing to renew by hand. |
| **Diagnostics** | Redacted diagnostics dump for troubleshooting and bug reports. |

## Compatibility

Built for Wi-Fi connected iRobot robots that speak the modern MQTT protocol —
broadly the 600 series and newer, including the i, j, m, s and Combo lines, and
Braava jet mops.

Testing so far is limited. If your model works, or doesn't, please
[open an issue](https://github.com/sam3gp8/ha-irobot-advanced/issues) with a
diagnostics dump — it's the fastest way to widen support.

Requires Home Assistant 2025.1 or newer.

## Installation

### HACS

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/sam3gp8/ha-irobot-advanced` as an **Integration**
3. Install, then restart Home Assistant

### Manual

Copy `custom_components/irobot_advanced/` into your Home Assistant `config/`
directory and restart.

## Setup

In most cases setup starts on its own. Home Assistant matches robots by DHCP
hostname (`roomba-*`, `irobot-*`, `braava-*`) and by their mDNS `_mqtt._tcp`
advertisement, then shows them as discovered devices.

Click **Configure** on the discovered card:

- If another robot on the same account is already set up, there is nothing to
  answer — the existing credentials are reused and the device is added.
- Otherwise you're offered a choice between signing in and manual pairing.

To start manually: **Settings → Devices & Services → Add Integration →
iRobot Advanced**.

### Option 1 — Sign in (recommended)

Enter the email and password you use for the iRobot app.

The integration fetches its login configuration from iRobot's own
unauthenticated discovery endpoint, authenticates the same way the app does, and
reads each robot's local key from the response. That means **no HOME-button
pairing** and nothing to re-enter later — sessions renew themselves.

If the account has several robots, the first is added immediately and the rest
appear as discovered cards, one click each. They share a single login and a
single credential-refresh cycle.

Your account password is stored in the config entry so sessions can be renewed
unattended. If you change it, Home Assistant raises a normal reauthentication
prompt.

### Option 2 — Local only

Choose this to keep your account password out of Home Assistant. Cloud-backed
features (maps, mission history, obstacle snapshots) will be unavailable.

1. Put the robot on its dock
2. Press and hold **HOME** until it plays a series of tones (about two seconds)
3. Release, then submit the form within roughly 30 seconds

This performs the robot's password exchange once and stores the result.

> **Note on TLS.** Robot firmware speaks TLS 1.0 with weak ciphers. The
> integration lowers OpenSSL to `SECLEVEL=1` for that one socket. On a host with
> a hardened OpenSSL policy this is the most likely cause of pairing failures.

### After setup

- **IP changes are handled automatically.** DHCP discovery rewrites the stored
  address in place. A **Reconfigure** option exists for setting it by hand.
- **Diagnostics** are available from the device page. Credentials, BLIDs, MAC
  addresses and network names are redacted.

## Icons

The integration ships its own icon and logo in `custom_components/irobot_advanced/brand/`.
On Home Assistant 2026.3 and newer these are served automatically — the robot
shows the iRobot icon on the Integrations page, device pages and in the sidebar
with no extra steps. Light and dark theme variants are both included.

On older Home Assistant versions the integration page falls back to a generic
icon, but the dashboard card always shows the iRobot mark regardless.

## Dashboard

The integration ships its own interface — no extra HACS frontend plugin to
install.

**Sidebar panel.** An **iRobot** entry appears in the sidebar showing every
configured robot side by side.

**Dashboard card.** Add **iRobot Advanced** from the card picker, or by YAML:

```yaml
type: custom:irobot-advanced-card
entity: vacuum.roomba   # optional — auto-detected if omitted
```

Four tabs:

- **Control** — start, pause, stop, dock, locate, empty bin; suction level; a
  chip per mapped room that starts a targeted clean; live status tiles
- **Map** — the rendered map with the robot's current position, refreshed while
  the tab is open
- **Obstacles** — snapshot gallery with obstacle type, timestamp and map
  coordinates; click to enlarge
- **History** — recent missions with start time, duration, area and result

The card is plain JavaScript with no build step and uses Home Assistant's CSS
variables, so it follows your active theme.

## Entities

| Platform | Entities |
|---|---|
| `vacuum` | Full state machine, fan speed, raw `send_command` passthrough |
| `sensor` | Battery, phase, cycle, error, area cleaned, mission runtime, last mission start, total missions, total runtime, Wi-Fi signal, obstacle count, map count, schedule |
| `binary_sensor` | Bin full, bin present, docked, error, child lock, cloud connected |
| `switch` | Child lock, edge clean, two passes, hold schedule, carpet boost |
| `select` | Clean room — selecting a room starts a targeted run |
| `camera` | Map, with live robot position |
| `image` | Five rolling obstacle snapshot slots, newest first |

## Services

### `irobot_advanced.clean_rooms`

Clean specific mapped regions.

```yaml
action: irobot_advanced.clean_rooms
target:
  entity_id: vacuum.roomba
data:
  regions: [3, 7]
```

Region IDs are listed in the `regions` attribute of the vacuum entity and on the
`map_count` sensor.

### `irobot_advanced.set_schedule`

Write the weekly schedule.

```yaml
action: irobot_advanced.set_schedule
target:
  entity_id: vacuum.roomba
data:
  schedule:
    - day: mon
      enabled: true
      hour: 9
      minute: 30
    - day: thu
      enabled: true
      hour: 14
      minute: 0
```

Room-aware scheduling (newer robots) — add `pmap_id` and `regions` to a slot,
which switches that write to the `cleanSchedule2` format automatically:

```yaml
action: irobot_advanced.set_schedule
target:
  entity_id: vacuum.roomba
data:
  schedule:
    - day: sat
      enabled: true
      hour: 10
      minute: 0
      pmap_id: "MYMAPID"
      regions: [3, 7]
```

> The `cleanSchedule2` structure is inferred from the app schema rather than a
> captured sample, so room-aware scheduling is best-effort until confirmed
> against a real payload. Plain time-only schedules use the long-proven legacy
> format and are unaffected.

### Others

| Service | Effect |
|---|---|
| `irobot_advanced.empty_bin` | Evacuate to the Clean Base |
| `irobot_advanced.locate_robot` | Make the robot announce itself |
| `irobot_advanced.refresh_maps` | Force a cloud refresh of maps, history and snapshots |

### Raw passthrough

`vacuum.send_command` goes straight to the robot, which is useful for settings
this integration doesn't expose yet:

```yaml
action: vacuum.send_command
target:
  entity_id: vacuum.roomba
data:
  command: set
  params:
    suctionLevel: 3
```

`command: pose` requests the robot's position and subscribes to its live
position stream. `command: timeline` requests the mission timeline.

## Live camera view

Camera-equipped robots stream over **AWS Kinesis Video Streams WebRTC**, with
the robot as the stream master and Home Assistant as a viewer.

The full control-plane handshake is implemented: the integration asks the robot
to start its camera, resolves the signalling channel and its viewer endpoints,
and fetches the STUN/TURN servers — all authenticated with your account
credentials. A live camera entity (disabled by default) turns the camera on and
off, and the `get_live_view_config` service returns the resolved signalling
endpoint and ICE servers.

**Playback is not yet wired end-to-end.** KVS negotiates media over a
bidirectional signalling WebSocket where the robot originates the offer, which
doesn't fit Home Assistant's built-in offer/answer WebRTC path. Finishing it
needs a backend WebRTC peer (aiortc) or a go2rtc source that speaks KVS
signalling. Until then the handshake is fully resolved and exposed through the
service, so the stream can be opened with an external WebRTC tool.

## How it works## How it works

Briefly, with detail in [PROTOCOL.md](PROTOCOL.md):

- **Discovery** — UDP broadcast on port 5678; robots reply with their hostname,
  BLID and IP.
- **Local control** — MQTT over TLS on port 8883, authenticated with the BLID
  and the robot's key. Commands are `{"command": ..., "time": ..., "initiator":
  "localApp"}`; settings go through a delta channel.
- **Cloud sign-in** — an unauthenticated discovery endpoint returns the identity
  provider configuration; from there a standard login yields short-lived AWS
  credentials plus the robot list.
- **Cloud API** — AWS SigV4-signed requests to API Gateway for maps, mission
  history and obstacle images. The signer is verified against AWS's published
  `get-vanilla` test vector.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.irobot_advanced: debug
```

Every MQTT publish is logged with its topic and payload, which is usually the
quickest way to see what a given robot accepts.

| Symptom | Likely cause |
|---|---|
| Pairing fails with "did not hand over a key" | HOME wasn't held long enough, or the host's OpenSSL policy blocks TLS 1.0 |
| Robot not discovered | It's on a different VLAN or subnet — add it by IP manually |
| Entity unavailable | The local MQTT session dropped; check the robot is on Wi-Fi and reachable on port 8883 |
| No maps or snapshots | Cloud sign-in isn't enabled, or the account has no map data yet |

## Known limitations

- **Limited real-world testing.** The protocol was reconstructed from the app
  rather than from vendor documentation. Some field names are inferred and may
  differ across models and firmware.
- **UMF map parsing is heuristic.** The renderer walks the map's layer tree
  looking for coordinate rings rather than implementing the format completely.
  The cloud's own rendered raster is preferred where available.
- **Obstacle snapshot extraction probes several key names**, because the exact
  field naming couldn't be determined statically. If `obstacle_count` reads zero
  on a robot that should have snapshots, a diagnostics dump will pin it down.
- **`cleanSchedule2`** (newer room-aware schedules) is read and exposed as an
  attribute, but writes use the legacy schedule format, which robots still
  accept.
- **Live view is not implemented**, as described above.

## Versioning

The project stays in the `0.x` series until the live camera view streams video
end-to-end. Releases still increment within `0.x`; there will be no `1.0.0`
until that feature is complete.

## Changelog

Release notes are in [CHANGELOG.md](CHANGELOG.md).

## Contributing

Issues and pull requests are welcome. Please add an entry under `Unreleased` in
[CHANGELOG.md](CHANGELOG.md) with any user-visible change. For anything
model-specific, please attach a diagnostics dump from the device page — it is redacted by design and includes
the field names the cloud returned, which is exactly what's needed to fix the
heuristic parsers above.

## Support

If this integration is useful to you, you can
[buy me a coffee](https://www.buymeacoffee.com/sam3gp8). Entirely optional and
always appreciated.

## Credits

Prior reverse-engineering work that this builds on:

- [koalazak/dorita980](https://github.com/koalazak/dorita980) — the original
  local protocol and password exchange
- [mjg59/python-irobotapi](https://github.com/mjg59/python-irobotapi) — the
  cloud authentication sequence

## Legal

Independent project for interoperability with hardware you own. Not affiliated
with, endorsed by, or supported by iRobot Corporation. iRobot, Roomba and Braava
are trademarks of iRobot Corporation.

Licensed under the [MIT License](LICENSE).
