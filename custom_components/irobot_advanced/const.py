"""Constants for the iRobot Advanced integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "irobot_advanced"

CONF_BLID: Final = "blid"
CONF_ROBOT_PASSWORD: Final = "robot_password"
CONF_CONTINUOUS: Final = "continuous"
CONF_ENABLE_CLOUD: Final = "enable_cloud"
CONF_CLOUD_USERNAME: Final = "cloud_username"
CONF_CLOUD_PASSWORD: Final = "cloud_password"
CONF_COUNTRY: Final = "country_code"
CONF_APP_ID: Final = "app_id"

# Sent to {httpBase}/v2/login. Not a literal in 7.18.0 -- the app builds it at
# runtime -- but the service still accepts this well-known Android app id.
# Overridable in the options flow in case iRobot rotates it.
DEFAULT_APP_ID: Final = "ANDROID-C7FB240E-DF34-42D7-AE4E-A8C17079A294"

DEFAULT_PORT: Final = 8883
DISCOVERY_PORT: Final = 5678
DISCOVERY_MAGIC: Final = b"irobotmcs"
PASSWORD_REQUEST: Final = bytes([0xF0, 0x05, 0xEF, 0xCC, 0x3B, 0x29, 0x00])
PASSWORD_HEADER_LEN: Final = 13

# Service discovery -- see PROTOCOL.md section 1.
DISCOVERY_URL: Final = (
    "https://disc-{env}.iot.irobotapi.com/v1/discover/endpoints?country_code={cc}"
)
DISCOVERY_URL_CN: Final = (
    "https://disc-{env}.iot.irobot.cn/v1/discover/endpoints?country_code={cc}"
)
ROBOT_DISCOVERY_URL: Final = "https://disc-{env}.iot.irobotapi.com/v1/robot/discover/{blid}"

# MQTT topics. First %s is the BLID / thing name.
TOPIC_CMD: Final = "cmd"
TOPIC_DELTA: Final = "delta"
TOPIC_WIFISTAT: Final = "wifistat"
TOPIC_SHADOW_UPDATE: Final = "$aws/things/{blid}/shadow/update"
TOPIC_RRTP_REQUEST: Final = "/things/{blid}/mission/rrtp/request"
TOPIC_RRTP_REPORT: Final = "/things/{blid}/mission/rrtp/report/update"
TOPIC_TIMELINE_REQUEST: Final = "/things/{blid}/mission/timeline/request"
TOPIC_TIMELINE_REPORT: Final = "/things/{blid}/mission/timeline/report"

# Cloud REST paths, appended to the API Gateway host + deployment stage
# taken from httpBaseAuth. Authenticated with SigV4, not a bearer token.
PATH_PMAPS: Final = "/v1/{blid}/pmaps"
PATH_PMAP_VERSIONS: Final = "/v1/{blid}/pmaps/{pmap_id}/versions"
PATH_PMAP_VERSION: Final = "/v1/{blid}/pmaps/{pmap_id}/versions/{version}"
PATH_PMAP_UMF: Final = "/v1/{blid}/pmaps/{pmap_id}/versions/{version}/umf"
PATH_PMAP_SETTINGS: Final = "/v1/{blid}/pmaps/{pmap_id}/settings"
PATH_MISSION_HISTORY: Final = "/v1/{blid}/missionhistory"
PATH_EVAC_HISTORY: Final = "/v1/evachistory"
PATH_OMAPS: Final = "/v1/omaps"
PATH_OMAP_SPATIAL: Final = "/v1/omaps/{omap_id}/versions/{version}/spatialdata"
PATH_MAP_RENDERED: Final = "/v1/map/{map_id}/spatial/rendered"
PATH_ROBOTS_OWNED: Final = "/v1/robots/owned"
PATH_IMAGE_REMOVAL: Final = "/v1/user/imageupload/removalRequest"

# Mission phase -> friendly. Values come straight off cleanMissionStatus.phase.
PHASE_MAP: Final[dict[str, str]] = {
    "charge": "charging",
    "run": "cleaning",
    "evac": "emptying_bin",
    "stop": "paused",
    "stuck": "stuck",
    "hmUsrDock": "returning_user",
    "hmMidMsn": "returning_mid_mission",
    "hmPostMsn": "returning_done",
    "new": "starting",
    "dock": "docking",
    "dockend": "docked",
    "cancelled": "cancelled",
    "pause": "paused",
    "chargingerror": "charging_error",
}

CYCLE_MAP: Final[dict[str, str]] = {
    "none": "idle",
    "clean": "clean",
    "spot": "spot",
    "quick": "quick",
    "dock": "dock",
    "evac": "evac",
    "train": "mapping_run",
}

# cleanMissionStatus.error -> human text. Trimmed to the ones users actually hit.
ERROR_MAP: Final[dict[int, str]] = {
    0: "None",
    1: "Left wheel off floor",
    2: "Main brush stuck",
    3: "Right wheel off floor",
    4: "Left wheel stuck",
    5: "Right wheel stuck",
    6: "Stuck near a cliff",
    7: "Left wheel error",
    8: "Brush error",
    9: "Bumper stuck",
    10: "Right wheel error",
    11: "Bin error",
    12: "Cliff sensor issue",
    13: "Both wheels off floor",
    14: "Bin missing",
    15: "Reboot required",
    16: "Bumped unexpectedly",
    17: "Path blocked",
    18: "Docking issue",
    19: "Undocking issue",
    20: "Docking issue",
    21: "Navigation problem",
    22: "Navigation problem",
    23: "Battery issue",
    24: "Navigation problem",
    25: "Reboot required",
    26: "Vacuum problem",
    27: "Vacuum problem",
    29: "Software update in progress",
    30: "Vacuum problem",
    31: "Reboot required",
    32: "Smart map problem",
    33: "Path blocked",
    34: "Reboot required",
    35: "Unrecognised cleaning pad",
    36: "Bin full",
    37: "Tank needed refilling",
    38: "Vacuum problem",
    39: "Reboot required",
    40: "Navigation problem",
    41: "Timed out",
    42: "Localisation problem",
    43: "Navigation problem",
    44: "Pump issue",
    45: "Reboot required",
    46: "Battery low",
    47: "Reboot required",
    48: "Path blocked",
    52: "Pad required attention",
    65: "Hardware problem detected",
    66: "Low memory",
    68: "Hardware problem detected",
    73: "Pad type changed",
    74: "Max area reached",
    75: "Not all rooms finished",
    76: "Hardware problem detected",
}

SUCTION_LEVELS: Final[dict[str, int]] = {
    "eco": 1,
    "standard": 2,
    "performance": 3,
}

WEEKDAYS: Final = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

ATTR_PMAP_ID: Final = "pmap_id"
ATTR_REGIONS: Final = "regions"
ATTR_USER_PMAPV_ID: Final = "user_pmapv_id"

SERVICE_CLEAN_ROOMS: Final = "clean_rooms"
SERVICE_SET_SCHEDULE: Final = "set_schedule"
SERVICE_EMPTY_BIN: Final = "empty_bin"
SERVICE_LOCATE: Final = "locate_robot"
SERVICE_REFRESH_MAPS: Final = "refresh_maps"
