import json
import math
import sys
import os

# ============================================================
# FIND NEAREST GRAPH VERTEX
# Intelligent Emergency Ambulance Dispatch System
# ============================================================

GRAPH_FILE = "routing/tamil_nadu_graph.json"


# ------------------------------------------------------------
# HAVERSINE DISTANCE
# ------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two
    latitude/longitude coordinates.

    Returns distance in kilometres.
    """

    R = 6371.0

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)

    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        +
        math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return R * c


# ------------------------------------------------------------
# FIND NEAREST VERTEX
# ------------------------------------------------------------

def find_nearest_vertex(
    vertices,
    latitude,
    longitude
):
    """
    Find the graph vertex geographically closest
    to the supplied GPS coordinate.
    """

    nearest_vertex = None
    nearest_latitude = None
    nearest_longitude = None
    minimum_distance = float("inf")

    for vertex_id, coordinate in vertices.items():

        vertex_latitude = coordinate["latitude"]
        vertex_longitude = coordinate["longitude"]

        distance = haversine(
            latitude,
            longitude,
            vertex_latitude,
            vertex_longitude
        )

        if distance < minimum_distance:

            minimum_distance = distance

            nearest_vertex = vertex_id

            nearest_latitude = vertex_latitude
            nearest_longitude = vertex_longitude

    return (
        nearest_vertex,
        nearest_latitude,
        nearest_longitude,
        minimum_distance
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print("=" * 70)
    print("NEAREST GRAPH VERTEX FINDER")
    print("=" * 70)

    # --------------------------------------------------------
    # CHECK GRAPH FILE
    # --------------------------------------------------------

    if not os.path.exists(GRAPH_FILE):

        print()
        print("ERROR: Graph file not found.")
        print(GRAPH_FILE)

        return

    # --------------------------------------------------------
    # GET GPS COORDINATES
    # --------------------------------------------------------

    if len(sys.argv) != 3:

        print()
        print("Usage:")
        print(
            "python routing\\find_nearest_vertex.py "
            "<latitude> <longitude>"
        )

        print()
        print("Example:")
        print(
            "python routing\\find_nearest_vertex.py "
            "13.0827 80.2707"
        )

        return

    try:

        latitude = float(sys.argv[1])
        longitude = float(sys.argv[2])

    except ValueError:

        print()
        print("ERROR: Latitude and longitude must be numeric.")

        return

    # --------------------------------------------------------
    # BASIC COORDINATE VALIDATION
    # --------------------------------------------------------

    if not -90 <= latitude <= 90:

        print()
        print("ERROR: Invalid latitude.")

        return

    if not -180 <= longitude <= 180:

        print()
        print("ERROR: Invalid longitude.")

        return

    # --------------------------------------------------------
    # LOAD GRAPH
    # --------------------------------------------------------

    print()
    print("Loading statewide graph...")
    print(GRAPH_FILE)

    with open(
        GRAPH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        graph = json.load(file)

    vertices = graph["vertices"]

    print()
    print(
        f"Graph vertices loaded: "
        f"{len(vertices):,}"
    )

    # --------------------------------------------------------
    # FIND NEAREST VERTEX
    # --------------------------------------------------------

    print()
    print("Searching nearest graph vertex...")

    (
        vertex_id,
        vertex_latitude,
        vertex_longitude,
        distance
    ) = find_nearest_vertex(
        vertices,
        latitude,
        longitude
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("NEAREST VERTEX RESULT")
    print("=" * 70)

    print()
    print("INPUT GPS")
    print("-" * 70)

    print(
        f"Latitude              : {latitude}"
    )

    print(
        f"Longitude             : {longitude}"
    )

    print()
    print("NEAREST GRAPH VERTEX")
    print("-" * 70)

    print(
        f"Vertex ID             : {vertex_id}"
    )

    print(
        f"Vertex latitude       : {vertex_latitude}"
    )

    print(
        f"Vertex longitude      : {vertex_longitude}"
    )

    print(
        f"Distance to vertex    : "
        f"{distance:.6f} km"
    )

    print()
    print("=" * 70)


# ------------------------------------------------------------
# PROGRAM ENTRY
# ------------------------------------------------------------

if __name__ == "__main__":
    main()