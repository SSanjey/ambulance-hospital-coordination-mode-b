import json
import math
import heapq
import os

# ============================================================
# DYNAMIC A* ROUTE FINDER
# Intelligent Emergency Ambulance Dispatch System
# ============================================================

GRAPH_FILE = "routing/tamil_nadu_graph.json"
CONDITION_FILE = "routing/dynamic_conditions.json"


# ------------------------------------------------------------
# HAVERSINE DISTANCE
# ------------------------------------------------------------

def haversine(lat1, lon1, lat2, lon2):

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
# HEURISTIC
# ------------------------------------------------------------

def heuristic(vertices, current, goal):

    current_coord = vertices[current]
    goal_coord = vertices[goal]

    return haversine(
        current_coord["latitude"],
        current_coord["longitude"],
        goal_coord["latitude"],
        goal_coord["longitude"]
    )


# ------------------------------------------------------------
# LOAD DYNAMIC CONDITIONS
# ------------------------------------------------------------

def load_conditions():

    if not os.path.exists(CONDITION_FILE):

        raise FileNotFoundError(
            f"Dynamic condition file not found: "
            f"{CONDITION_FILE}"
        )

    with open(
        CONDITION_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    condition_map = {}

    for condition in data["conditions"]:

        key = (
            condition["from"],
            condition["to"]
        )

        condition_map[key] = condition

    return condition_map


# ------------------------------------------------------------
# GET DYNAMIC EDGE COST
# ------------------------------------------------------------

def get_dynamic_cost(
    from_node,
    to_node,
    edge_distance,
    condition_map
):

    key = (
        from_node,
        to_node
    )

    condition = condition_map.get(key)

    # No special condition
    if condition is None:

        return edge_distance

    status = condition["status"]

    # Normal road
    if status == "normal":

        return (
            edge_distance
            * condition["cost_multiplier"]
        )

    # Congested road
    if status == "congested":

        return (
            edge_distance
            * condition["cost_multiplier"]
        )

    # Blocked road
    if status == "blocked":

        return float("inf")

    # Unknown condition
    return edge_distance


# ------------------------------------------------------------
# DYNAMIC A* SEARCH
# ------------------------------------------------------------

def dynamic_astar(
    graph,
    start,
    goal,
    condition_map
):

    vertices = graph["vertices"]
    adjacency = graph["adjacency"]

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

    g_score = {
        start: 0.0
    }

    came_from = {}

    closed_set = set()

    while open_set:

        current_f, current = heapq.heappop(
            open_set
        )

        if current in closed_set:
            continue

        if current == goal:

            return reconstruct_path(
                came_from,
                current,
                g_score[current]
            )

        closed_set.add(current)

        current_g = g_score[current]

        for edge in adjacency.get(
            current,
            []
        ):

            neighbour = edge["to"]

            edge_distance = edge[
                "distance_km"
            ]

            dynamic_cost = get_dynamic_cost(
                current,
                neighbour,
                edge_distance,
                condition_map
            )

            # Ignore blocked roads
            if math.isinf(dynamic_cost):
                continue

            tentative_g = (
                current_g
                + dynamic_cost
            )

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

    return None, float("inf")


# ------------------------------------------------------------
# PATH RECONSTRUCTION
# ------------------------------------------------------------

def reconstruct_path(
    came_from,
    current,
    total_cost
):

    path = [current]

    while current in came_from:

        current = came_from[
            current
        ]

        path.append(current)

    path.reverse()

    return path, total_cost


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
    print("DYNAMIC A* ROUTE FINDER")
    print("=" * 70)

    graph = load_graph()

    condition_map = load_conditions()

    print(
        f"Dynamic conditions loaded: "
        f"{len(condition_map)}"
    )

    start = "V8903"
    goal = "V180670"

    print()
    print("DYNAMIC A* TEST")
    print("-" * 70)

    print(
        f"Start vertex : {start}"
    )

    print(
        f"Goal vertex  : {goal}"
    )

    print()
    print("Searching route with dynamic road conditions...")

    result = dynamic_astar(
        graph,
        start,
        goal,
        condition_map
    )

    if result[0] is None:

        print()
        print("NO ROUTE FOUND")
        return

    path, total_cost = result

    print()
    print("=" * 70)
    print("DYNAMIC A* ROUTE RESULT")
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
        f"Dynamic route cost : "
        f"{total_cost:.3f}"
    )

    print()
    print("=" * 70)
    print("DYNAMIC A* SEARCH COMPLETED")
    print("=" * 70)


# ------------------------------------------------------------
# PROGRAM ENTRY
# ------------------------------------------------------------

if __name__ == "__main__":
    main()