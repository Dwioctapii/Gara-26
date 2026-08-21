"""Perhitungan navigasi lokal presisi tanpa membulatkan koordinat MAVLink."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def _local_xy(lat: float, lon: float, origin_lat: float, origin_lon: float):
    north = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    east = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    return east, north


def _distance_bearing(lat1: float, lon1: float, lat2: float, lon2: float):
    east, north = _local_xy(lat2, lon2, lat1, lon1)
    return math.hypot(east, north), (math.degrees(math.atan2(east, north)) + 360.0) % 360.0


def navigation_snapshot(gps: dict, mission: dict) -> dict:
    lat, lon = gps.get("lat"), gps.get("lon")
    route = [w for w in mission.get("waypoints", []) if w.get("lat") is not None and w.get("lon") is not None]
    if lat is None or lon is None or not route:
        return {"valid": False, "routePoints": len(route)}

    current_seq = int(mission.get("current", 0))
    target_index = next((i for i, w in enumerate(route) if int(w["seq"]) >= current_seq), len(route) - 1)
    target = route[target_index]
    distance, bearing = _distance_bearing(lat, lon, target["lat"], target["lon"])
    cross_track = 0.0
    progress = 0.0
    if target_index > 0:
        previous = route[target_index - 1]
        tx, ty = _local_xy(target["lat"], target["lon"], previous["lat"], previous["lon"])
        px, py = _local_xy(lat, lon, previous["lat"], previous["lon"])
        length2 = tx * tx + ty * ty
        if length2 > 1e-6:
            t = max(0.0, min(1.0, (px * tx + py * ty) / length2))
            cross_track = (tx * py - ty * px) / math.sqrt(length2)
            progress = t * 100.0
    radius = float(target.get("acceptanceRadius") or 1.5)
    return {"valid": True, "targetSeq": target["seq"], "distanceToNextM": distance,
            "bearingToNextDeg": bearing, "crossTrackErrorM": cross_track,
            "legProgressPct": progress, "reachedRadiusM": radius,
            "insideReachedRadius": distance <= radius, "routePoints": len(route)}
