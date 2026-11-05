import json
import math
import heapq
import os

# ============================================================
# A* ROUTE FINDER
# Intelligent Emergency Ambulance Dispatch System
# ============================================================

GRAPH_FILE = "routing/tamil_nadu_graph.json"


# ------------------------------------------------------------
# HAVERSINE DISTANCE
# ------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate geographic distance between two coordinates.
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
# HEURISTIC FUNCTION
# ------------------------------------------------------------

def heuristic(vertices, current, goal):
    """
    A* heuristic.

    Uses straight-line geographic distance between
    the current vertex and goal vertex.
    """

    current_coord = vertices[current]
    goal_coord = vertices[goal]

    return haversine(
        current_coord["latitude"],
        current_coord["longitude"],
        goal_coord["latitude"],
        goal_coord["longitude"]
    )


# ------------------------------------------------------------
# A* SEARCH
# ------------------------------------------------------------

def astar(graph, start, goal):

    vertices = graph["vertices"]
    adjacency = graph["adjacency"]

    # --------------------------------------------------------
    # Open set
    # --------------------------------------------------------

    open_set = []

    start_h = heuristic(
        vertices,
        start,
        goal
    )

    heapq.heappush(
        open_set,
        (start_h, start)
    )

    # --------------------------------------------------------
    # Cost from start
    # --------------------------------------------------------

    g_score = {
        start: 0.0
    }

    # --------------------------------------------------------
    # Parent tracking
    # --------------------------------------------------------

    came_from = {}

    # --------------------------------------------------------
    # Closed set
    # --------------------------------------------------------

    closed_set = set()

    # --------------------------------------------------------
    # A* search
    # --------------------------------------------------------

    while open_set:

        current_f, current = heapq.heappop(
            open_set
        )

        # Ignore already processed vertices

        if current in closed_set:
            continue

        # Goal reached

        if current == goal:

            return reconstruct_path(
                came_from,
                current,
                g_score[current]
            )

        closed_set.add(current)

        current_g = g_score[current]

        # ----------------------------------------------------
        # Examine neighbouring vertices
        # ----------------------------------------------------

        for edge in adjacency.get(
            current,
            []
        ):

            neighbour = edge["to"]

            edge_distance = edge[
                "distance_km"
            ]

            tentative_g = (
                current_g
                + edge_distance
            )

            # ------------------------------------------------
            # Better path found
            # ------------------------------------------------

            if (
                neighbour not in g_score
                or tentative_g < g_score[neighbour]
            ):

                came_from[
                    neighbour
                ] = current

                g_score[
                    neighbour
                ] = tentative_g

                h = heuristic(
                    vertices,
                    neighbour,
                    goal
                )

                f = tentative_g + h

                heapq.heappush(
                    open_set,
                    (
                        f,
                        neighbour
                    )
                )

    # --------------------------------------------------------
    # No route
    # --------------------------------------------------------

    return None, float("inf")


# ------------------------------------------------------------
# PATH RECONSTRUCTION
# ------------------------------------------------------------

def reconstruct_path(
    came_from,
    current,
    total_distance
):

    path = [current]

    while current in came_from:

        current = came_from[
            current
        ]

        path.append(current)

    path.reverse()

    return path, total_distance


# ------------------------------------------------------------
# LOAD GRAPH
# ------------------------------------------------------------

def load_graph():

    if not os.path.exists(
        GRAPH_FILE
    ):

        raise FileNotFoundError(
            f"Graph file not found: "
            f"{GRAPH_FILE}"
        )

    print()
    print("Loading statewide graph...")

    with open(
        GRAPH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        graph = json.load(file)

    print(
        "Graph loaded successfully."
    )

    print(
        f"Graph nodes: "
        f"{len(graph['adjacency']):,}"
    )

    return graph


# ------------------------------------------------------------
# MAIN TEST
# ------------------------------------------------------------

def main():

    print("=" * 70)
    print("A* ROUTE FINDER")
    print("=" * 70)

    graph = load_graph()

    # --------------------------------------------------------
    # Temporary test vertices
    # --------------------------------------------------------
    #
    # These are only for the first A* algorithm test.
    # We will later replace them with:
    #
    # GPS → nearest vertex
    #
    # --------------------------------------------------------

    start = "V8903"
    goal = "V180670"

    print()
    print("A* TEST")
    print("-" * 70)

    print(
        f"Start vertex : {start}"
    )

    print(
        f"Goal vertex  : {goal}"
    )

    print()
    print("Searching route...")

    result = astar(
        graph,
        start,
        goal
    )

    if result is None:

        print()
        print(
            "NO ROUTE FOUND"
        )

        return

    path, total_distance = result

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("A* ROUTE RESULT")
    print("=" * 70)

    print()
    print(
        f"Number of vertices : "
        f"{len(path):,}"
    )

    print(
        f"Number of edges    : "
        f"{len(path) - 1:,}"
    )

    print(
        f"Route distance     : "
        f"{total_distance:.3f} km"
    )

    print()
    print("ROUTE")
    print("-" * 70)

    for index, vertex in enumerate(
        path,
        start=1
    ):

        print(
            f"{index:5} : {vertex}"
        )

    print()
    print("=" * 70)
    print("A* SEARCH COMPLETED")
    print("=" * 70)


# ------------------------------------------------------------
# PROGRAM ENTRY
# ------------------------------------------------------------

if __name__ == "__main__":
    main()