# iRobot protocol notes

Reference notes for the protocol used by iRobot's Wi-Fi robots, reconstructed
from version 7.18.0 of the official Android app. These document what the
integration in this repository implements, and are published so others don't
have to repeat the work.

The Java/Kotlin layer is
almost entirely a thin [djinni](https://github.com/dropbox/djinni) binding shell —
the real protocol lives in the native libraries in `split_0.apk`:

| Library | Size | Contains |
|---|---|---|
| `libcore_jni.so` | 103 MB | JNI trampolines, everything statically linked |
| `libdata_module.so` | 16 MB | REST client, serializers, deserializers |
| `libcore_base.so` | 9.6 MB | MQTT/IoT protocol adapters, state machines |
| `libmapping_module.so` | 3.3 MB | pmap/UMF parsing, hazards, GEOS geometry |

---

## 1. Service discovery

Everything bootstraps from one unauthenticated endpoint:

```
GET https://disc-{env}.iot.irobotapi.com/v1/discover/endpoints?country_code={CC}
GET https://disc-{env}.iot.irobot.cn/v1/discover/endpoints?country_code={CC}   # China
```

`{env}` is `prod` / `int-test` / `dev`. The response is deserialized by
`RoombaServiceEndpointsDeserializer` and yields the per-region HTTP base, the AWS
IoT ATS endpoint and the deployment id. The robot itself also reports its own
endpoints in the shadow under `svcEndpoints` (schema field `ServiceEndpoints`) —
`"Robot does not have reported endpoints"` is the fallback log line.

Second discovery endpoint, per-robot:

```
GET https://disc-{env}.iot.irobotapi.com/v1/robot/discover/{blid}
```

Other fixed hosts seen: `axlite-prod.iot.irobotapi.com`,
`integrate-prod.iot.irobotapi.com` (IFTTT / account-linking),
`appcontent.irobot.cn`, `{0..3}.irobot.pool.ntp.org`.

## 2. Authentication — fully automatable

The identity-provider API key is not a literal anywhere in the APK — scanning
every `.so` and `classes*.dex` for the `3_<43 chars>` key shape returns nothing,
and the SDK is initialised programmatically (`config!!.apiKey`, no
`gigyaSdkConfiguration.json`, no manifest meta-data).

It does not need capturing, however. The key is *served* by the unauthenticated
discovery endpoint from §1:

```
GET https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US

{
  "current_deployment": "v011",
  "deployments": {
    "v011": {
      "httpBase":     "https://unauth2.prod.iot.irobotapi.com",
      "httpBaseAuth": "https://<id>.execute-api.us-east-1.amazonaws.com/dev",
      "awsRegion":    "us-east-1",
      ...
    }
  },
  "gigya": {
    "api_key":           "3_...",
    "datacenter_domain": "us1.gigya.com"
  }
}
```

Every one of `deployments`, `httpBaseAuth`, `awsRegion`, `datacenter_domain`
and `api_key` appears verbatim in 7.18.0's native core, so this schema is
current for this build. Nothing needs capturing by hand.

### Full flow

1. `GET /v1/discover/endpoints?country_code=<CC>` → Gigya key + datacenter,
   `httpBase`, `httpBaseAuth`, `awsRegion`.
2. `POST https://accounts.<datacenter>/accounts.login`
   form: `apiKey`, `targetEnv=mobile`, `loginID`, `password`, `format=json`
   → `UID`, `UIDSignature`, `signatureTimestamp`, `sessionInfo`.
3. `POST <httpBase>/v2/login`
   ```json
   { "app_id": "ANDROID-...",
     "assume_robot_ownership": "0",
     "gigya": { "signature": "<UIDSignature>",
                "timestamp": <signatureTimestamp>,
                "uid": "<UID>" } }
   ```
   → `credentials` (`AccessKeyId`, `SecretKey`, `SessionToken`) **and the robot
   list, including each robot's local MQTT password**.
4. Every subsequent API call is **SigV4-signed** against the `httpBaseAuth`
   host with service `execute-api` — *not* a bearer token. The API Gateway
   stage (`/dev` on the current deployment) prefixes the paths in §6; take it
   from `httpBaseAuth`'s path rather than hardcoding it.

Two consequences worth stating plainly:

- **Tokens never need re-capturing.** The STS credentials from step 3 expire in
  about an hour, but steps 1–3 are cheap and fully automatic, so the client
  just re-runs them.
- **The HOME-button pairing dance is optional.** Step 3 already returns each
  robot's local password, so an account login provisions LAN control for every
  robot at once.

The `app_id` is the one soft spot: it is *not* a literal in 7.18.0 (the app
builds it at runtime via `core::AppId`), so the value above is the long-known
Android id rather than something recovered from this build. The endpoint still
accepts it; if iRobot ever rotates it, it is one string to change.

## 3. MQTT topic map

Recovered format strings (`%s` = BLID / thing name):

```
$aws/things/%s/shadow/update
      /things/%s/shadow/get
      /things/%s/shadow/get/accepted
      /things/%s/shadow/update/accepted
      /things/%s/shadow/update/rejected
      /things/%s/shadow/name/%s/get
      /things/%s/shadow/name/%s/get/accepted
      /things/%s/shadow/name/%s/update
      /things/%s/shadow/name/%s/update/accepted
      /things/%s/shadow/name/%s/update/rejected
      /things/%s/cmd
      /things/%s/rejected/report
      /things/%s/mission/rrtp/request
      /things/%s/mission/rrtp/report/update
      /things/%s/mission/timeline/request
      /things/%s/mission/timeline/report
```

Topic factories in `core::protocol`: `ClassicThingShadowTopicFactory`,
`NamedThingShadowTopicFactory`, `AssetIotTopicFactory`, `AccountIotTopicFactory`.
The log line `"Migrated to Named Shadow, do reconnect"` confirms newer robots
moved from the classic shadow to named shadows.

**`mission/rrtp/*` is the live position stream** ("real-time robot telemetry
position"). There is also a local variant — the symbol
`BaseSecureSocketProtocolSerializer::kMessageTopicForLocalRrtpRequest` exists, so
the same request works over the LAN socket without the cloud.

## 4. Local (LAN) protocol — still intact

The LAN protocol is unchanged from earlier firmware generations, and is what
the integration is built on.

**Discovery** — UDP broadcast the literal string `irobotmcs` to
`255.255.255.255:5678`. Robots answer with a JSON blob containing `robotname`,
`hostname` (`Roomba-<blid>` / `iRobot-<blid>`), `ip`, `sku`, `ver`, `cap`.

**Password exchange** — `"PassWord eXchange"`, `EncodePasswordRequest`,
`GetPasswordStatus` are all still present, as is the literal
`"passwd",{"passwd":"`. Flow is unchanged: with the robot on its dock, hold HOME
until it chimes, open a TLS socket to `:8883`, send
`f0 05 ef cc 3b 29 00`, and read the reply — the password is the payload after
the first 13 bytes. Error strings confirm the failure modes:
`"Incorrect V1 password length OR robot not in add user mode."`,
`"Failed password exchange: invalid password"`,
`"PasswordHash not in either V0 or V1 format"`.

**Session** — MQTT over TLS on `:8883`, client id = username = BLID, password =
the exchanged secret. Old TLS: you must drop OpenSSL to `SECLEVEL=1` and allow
TLSv1.

**Commands** — published to `cmd`:

```json
{ "command": "start", "time": 1721700000, "initiator": "localApp" }
```

`initiator` is `localApp` on LAN and `rmtApp` via cloud. Settings go through the
delta channel:

```json
{"do": "set", "args": [ {"suctionLevel": 2} ]}
{"do": "get", "args": ["pose"], "id": 2}
```

Single-field helpers seen verbatim: `{ "suctionLevel" : %d}`,
`{ "flushSluice" : %d}`, `{ "language" : %s }`.

## 5. Schedules

Two formats coexist. Legacy:

```json
{"cycle":["none","none","none","none","none","none","none"],
 "h":[0,0,0,0,0,0,0],
 "m":[0,0,0,0,0,0,0]}
```

Index 0 = Sunday. `cycle` entries are `none` or `start`. Newer robots use
`cleanSchedule2` (a list of objects, room/favorite-aware) alongside
`scheduleOnHold` and the dnd pair `dndEnd,returnHomeEnd`.

## 6. Maps

REST paths recovered (`{blid}` first `%s` unless noted):

```
GET  /v1/{blid}/pmaps
GET  /v1/{blid}/pmaps/{pmap_id}/versions
GET  /v1/{blid}/pmaps/{pmap_id}/versions/{ver}
GET  /v1/{blid}/pmaps/{pmap_id}/versions/{ver}/umf     <- the actual geometry
PUT  /v1/{blid}/pmaps/{pmap_id}/settings
GET  /v1/households/{household}/pmaps
GET  /v1/omaps?robotId={blid}
GET  /v1/omaps/{omap_id}?robotId={blid}
GET  /v1/omaps/{omap_id}/versions/{ver}/spatialdata?robotId={blid}
GET  /v1/map/{id}/umf
GET  /v1/map/{id}/spatial/rendered                      <- server-rendered PNG
GET  /v1/v4maps/{id}/umf
GET  /v1/pmaps/clean-score
```

**UMF** is iRobot's own vector map container, parsed by `libmapping_module.so`
(which links GEOS for the geometry ops). Layer types seen include `hazards`;
errors like `"%s layerType hazards is not a found in layer json object"` and
`"Invalid mapPoint Json format: %s"` show it's plain JSON wrapping coordinate
arrays, not a binary blob. `/spatial/rendered` is the shortcut — the cloud will
hand you a finished raster, which is far cheaper than reimplementing the
renderer.

## 7. Obstacle snapshots — the SecureAssetData service

Decompiling the native core settles how the app actually does this. It is **not**
a REST list endpoint — the complete REST inventory (§6 and below) contains no
obstacle-image path at all, only a deletion route
(`/v1/user/imageupload/removalRequest`).

Instead the app drives an internal service, `SecureAssetDataUIService`, over its
UIService bus (`registerUISubscriber` / `sendCommand`). The data object exposes:

```
SecureAssetDataUIServiceData
  setHouseholdId(...)         <- scope
  setMissionId(...)           <- obstacle captures are per-mission
  setMissionNumber(...)
  setImageId(...)             <- individual capture
  getBundleId()               <- see "encryption" below
  getAllObstacleMetadata()    -> List<ObstacleMetadata>
  getObstacleImageData()      -> the image bytes
  getObstacleReviewStatus()
  getObstacleReviewProgress() / setObstacleReviewProgress(...)
  setObstacleApprovals(...)   -> List<ObstacleImageApproval>
  getLastError()
```

Two conclusions follow, and both are load-bearing:

**1. Captures are keyed by mission, not by robot.** `setMissionId` is a required
input, and `missionId` appears in the binary's query-parameter set alongside
`robotId` — the only two params used for the omap endpoints. A bare
`/v1/omaps?robotId=<blid>` returns nothing on a robot with no *current* observed
map, which is exactly what a live j9 returned (`omap_count: 0`). Querying omaps
per recent mission is therefore the correct shape.

**2. The images are encrypted, and `getBundleId` is why.** The service is named
*Secure*AssetData, and `/v1/app/bundles/%s/latest` sits in the REST inventory
next to it. Independent forensic work on these robots also describes the
obstacle captures as encrypted. So retrieving the bytes is likely not enough —
the bundle supplies key material. This is the part that remains unproven here.

Hazards are a **separate** concern and should not be confused with obstacle
photos:

```
HazardsUseCase::fetchHazardInfos      -> List<HazardsInfo>
HazardsInfo(string, string, Polygon)  <- geometry, not imagery
MapsUIServiceData::getHazardsPolygons / getSelectedHazard /
  setHazardsToConvertToKeepOutZones / setHazardsToConvertToPolicyZones
```

That is map geometry — hazard polygons the user can promote into keep-out or
policy zones. It travels in the UMF map layers (`layerType: hazards`), which is
why `observed_zones` and `keepoutzones` appear as UMF top-level keys.

## 8. Live camera view

Camera-equipped robots support a **Live View** feature in the app:

- `AWSKinesisVideoSignalingClient`, `AWSKinesisVideoArchivedMediaClient` in the dex
- shadow field `StreamingVideoStatus` / `streamingVideoStatus`
- operating modes `OperatingModeVideoStream`, `ACTIVE_STREAMING`, `ACTIVE_NON_STREAMING`
- push notification strings `push_notification_live_view_ready`
- a pile of `live_view_*` layout dimens

So it's **AWS Kinesis Video Streams WebRTC** — the robot is a KVS master, the app
is a viewer. That means: get KVS signalling channel ARN + credentials from the
iRobot cloud, `GetSignalingChannelEndpoint`, open the WSS signalling socket, do
SDP/ICE, receive H.264.

It is *not* available on the LAN and it is *not* reachable without the cloud
credentials from §2 — which, per that section, the integration can now obtain
on its own. In Home Assistant the realistic shape is: a small WebRTC→RTSP bridge
feeding `go2rtc`, which HA already ships. The integration below stubs the entity
and the plumbing; the missing piece is now only the KVS control-plane calls, not the credentials.

## 9. Robot state schema

172 field names recovered from `core::RoombaSchemaField`. The ones worth wiring:

`BatteryPercent BatteryType Bin BinFull BinPause BinPresent BinTypeDetect
CarpetBoost ChargingLightPattern ChildLock ChrgM Chrgs CleanSchedule
CleanScheduleMultipleMapping Cmd Command Connected ConnectedV2 Country Cycle
Date DockKnown Done DoneM EDock EcoCharge EdgeClean Error EvacAllowed Evacs
Flags FlushSluice GentleMode ImageUpload Initiator Language LastCommand
LastDisconnectReason LastSoftwareUpdate LinkedMssnId MacAddress MapIdReq
MissionId MissionStatus MssnM MssnStrtTm NMssn NavStrategy NetworkStatus
NoAutoPasses NoPersistentPasses NumTanks ODOAMode OdoaLite Omaps OperatingMode
PMapLearningAllowed PMapVersions PadDirtyPause PadWetness PadWashAfter
PasswordHash PauseM Phase Pmaps PmapsInfo Pose Position RechrgM RechrgTm
RobotName RunM RuntimeStatistics SKU ScheduleOnHold SoftwareVersion Sqft
StartTime StreamingVideoStatus SuctionLevel TZ Theta TimeZone Timeline
TwoPass VacuumHigh WifiSignalStrength WlBars X Y`

Capability gating is done by `AssetCapabilitiesImpl::supportsX()` —
`supportsPersistentMaps`, `supportsPmapCapability`, `supportsMissionTimelineRequest`,
`supportsGenericTimeline`, `supportsPad*`, `supportsPersistentPasses`, etc. The
robot publishes its own capability set, so the integration should feature-gate off
that rather than off SKU strings.
