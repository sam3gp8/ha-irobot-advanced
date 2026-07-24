"""Map camera.

Renders the persistent map as a PNG. Two sources, in order of preference:

1. the cloud's own raster (``/v1/map/{id}/spatial/rendered``) -- cheapest and
   always matches what the app shows;
2. a local Pillow render of the UMF vector layers, with the live pose from the
   rrtp stream drawn on top.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity

_LOGGER = logging.getLogger(__name__)

CANVAS = (900, 900)
PADDING = 40

COLOR_BG = (28, 30, 34)
COLOR_FLOOR = (68, 76, 88)
COLOR_WALL = (150, 158, 172)
COLOR_ROBOT = (86, 200, 120)
COLOR_DOCK = (240, 190, 70)
COLOR_HAZARD = (232, 96, 96)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IRobotMapCamera(coordinator)])


class IRobotMapCamera(IRobotEntity, Camera):
    """Live map view."""

    _attr_translation_key = "map"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: IRobotCoordinator) -> None:
        IRobotEntity.__init__(self, coordinator, "map")
        Camera.__init__(self)
        self._cached: bytes | None = None

    @property
    def available(self) -> bool:
        return bool(self.coordinator.pmap_details) or self.coordinator.local.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "maps": len(self.coordinator.pmaps),
            "position": self.coordinator.position or None,
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # Prefer the server-rendered raster when the cloud is wired up.
        if self.coordinator.cloud is not None and self.coordinator.pmaps:
            map_id = self.coordinator.pmaps[0].get("pmap_id") or self.coordinator.pmaps[0].get("id")
            if map_id:
                try:
                    image = await self.coordinator.cloud.async_get_rendered_map(map_id)
                    if image:
                        self._cached = image
                        return image
                except Exception as err:  # noqa: BLE001 - fall through to local render
                    _LOGGER.debug("Rendered map unavailable, drawing locally: %s", err)

        image = await self.hass.async_add_executor_job(self._render)
        if image:
            self._cached = image
        return image or self._cached

    # ------------------------------------------------------------- rendering

    def _render(self) -> bytes | None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:  # pragma: no cover
            _LOGGER.warning("Pillow is not installed -- cannot render the map")
            return None

        umf = next(iter(self.coordinator.pmap_details.values()), None)
        if not umf:
            return None

        polygons = _collect_polygons(umf)
        if not polygons:
            return None

        bounds = _bounds(p for poly in polygons for p in poly["points"])
        transform = _make_transform(bounds)

        img = Image.new("RGB", CANVAS, COLOR_BG)
        draw = ImageDraw.Draw(img)

        for poly in polygons:
            pts = [transform(x, y) for x, y in poly["points"]]
            if len(pts) < 3:
                continue
            fill = COLOR_HAZARD if poly["layer"] == "hazards" else COLOR_FLOOR
            draw.polygon(pts, fill=fill, outline=COLOR_WALL)

        # Dock
        if dock := umf.get("dock") or umf.get("dock_pose"):
            dx, dy = dock.get("x"), dock.get("y")
            if dx is not None and dy is not None:
                px, py = transform(dx, dy)
                draw.ellipse([px - 9, py - 9, px + 9, py + 9], fill=COLOR_DOCK)

        # Live pose from the rrtp stream
        pos = self.coordinator.position
        if pos.get("x") is not None and pos.get("y") is not None:
            px, py = transform(pos["x"], pos["y"])
            draw.ellipse([px - 11, py - 11, px + 11, py + 11], fill=COLOR_ROBOT)
            theta = pos.get("theta")
            if theta is not None:
                rad = math.radians(theta)
                draw.line(
                    [px, py, px + 22 * math.cos(rad), py - 22 * math.sin(rad)],
                    fill=(255, 255, 255),
                    width=3,
                )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _collect_polygons(umf: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull coordinate rings out of the UMF layer soup.

    UMF wraps GeoJSON-ish geometry per layer; layer names seen in the native
    mapping module include the region layers and ``hazards``.
    """
    out: list[dict[str, Any]] = []

    def walk(node: Any, layer: str) -> None:
        if isinstance(node, dict):
            layer = node.get("layerType") or node.get("layer_type") or layer
            geometry = node.get("geometry") or node.get("coordinates")
            if geometry is not None:
                points = _flatten_ring(geometry)
                if len(points) >= 3:
                    out.append({"layer": layer, "points": points})
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, layer)
        elif isinstance(node, list):
            for item in node:
                walk(item, layer)

    walk(umf, "")
    return out


def _flatten_ring(geometry: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict) and "x" in node and "y" in node:
            points.append((float(node["x"]), float(node["y"])))
        elif isinstance(node, (list, tuple)):
            if (
                len(node) == 2
                and all(isinstance(v, (int, float)) for v in node)
            ):
                points.append((float(node[0]), float(node[1])))
            else:
                for item in node:
                    walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(geometry)
    return points


def _bounds(points) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for x, y in points:
        xs.append(x)
        ys.append(y)
    if not xs:
        return (0.0, 0.0, 1.0, 1.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _make_transform(bounds: tuple[float, float, float, float]):
    min_x, min_y, max_x, max_y = bounds
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    usable_w = CANVAS[0] - 2 * PADDING
    usable_h = CANVAS[1] - 2 * PADDING
    scale = min(usable_w / span_x, usable_h / span_y)
    off_x = PADDING + (usable_w - span_x * scale) / 2
    off_y = PADDING + (usable_h - span_y * scale) / 2

    def transform(x: float, y: float) -> tuple[float, float]:
        # Robot frame is Y-up; image frame is Y-down.
        return (off_x + (x - min_x) * scale, CANVAS[1] - (off_y + (y - min_y) * scale))

    return transform
