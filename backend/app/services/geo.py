"""SRP: Distance Calculation.

Only responsibility: given two lat/lng points, return the distance in miles.
Does not know about job specs, movers, or pricing — those live elsewhere.
"""

from math import atan2, cos, radians, sin, sqrt

_EARTH_RADIUS_MILES = 3958.8


def haversine_distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1_r, lng1_r, lat2_r, lng2_r = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2_r - lat1_r
    dlng = lng2_r - lng1_r
    a = sin(dlat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return round(_EARTH_RADIUS_MILES * c, 1)
