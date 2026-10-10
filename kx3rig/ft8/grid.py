"""Maidenhead grid squares: position, distance, and bearing."""

from __future__ import annotations

import math


def to_latlon(grid: str) -> tuple[float, float] | None:
    """Center of a 4- or 6-character Maidenhead locator, (lat, lon) in degrees."""
    g = grid.strip()
    if len(g) not in (4, 6):
        return None
    g = g[:2].upper() + g[2:4] + g[4:].lower()
    if not ("A" <= g[0] <= "R" and "A" <= g[1] <= "R" and g[2:4].isdigit()):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        if not ("a" <= g[4] <= "x" and "a" <= g[5] <= "x"):
            return None
        lon += (ord(g[4]) - 97) * 5 / 60 + 2.5 / 60
        lat += (ord(g[5]) - 97) * 2.5 / 60 + 1.25 / 60
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def distance_km(a: str, b: str) -> float | None:
    pa, pb = to_latlon(a), to_latlon(b)
    if pa is None or pb is None:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*pa, *pb))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: str, b: str) -> float | None:
    pa, pb = to_latlon(a), to_latlon(b)
    if pa is None or pb is None:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*pa, *pb))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(bearing: float) -> str:
    points = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return points[int((bearing + 22.5) // 45) % 8]
