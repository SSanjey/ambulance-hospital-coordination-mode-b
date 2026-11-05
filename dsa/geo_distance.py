import math


EARTH_RADIUS_KM = 6371.0


def haversine_distance(
    latitude1,
    longitude1,
    latitude2,
    longitude2
):
    """
    Calculate the great-circle distance between
    two latitude/longitude coordinates in kilometres.
    """

    latitude1 = math.radians(float(latitude1))
    longitude1 = math.radians(float(longitude1))

    latitude2 = math.radians(float(latitude2))
    longitude2 = math.radians(float(longitude2))

    delta_latitude = latitude2 - latitude1
    delta_longitude = longitude2 - longitude1

    a = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude1)
        * math.cos(latitude2)
        * math.sin(delta_longitude / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    distance_km = EARTH_RADIUS_KM * c

    return distance_km