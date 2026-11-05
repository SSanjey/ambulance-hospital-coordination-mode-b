"""Memory-mapped Dynamic A* router for the Mode B compact Tamil Nadu graph.

Run from the project root:
    python routing\\mode_b\\dynamic_astar.py --self-test
    python routing\\mode_b\\dynamic_astar.py --start-node V8903 --goal-node V180670
    python routing\\mode_b\\dynamic_astar.py --start-node V8903 --goal-node V180670 --geojson results\\mode_b\\dynamic_test_route.geojson

Uses the compact CSR files produced by build_compact_graph.py and reads the
small configured condition file. It does not load the large graph JSON or
modify Mode A files. Dynamic cost is a condition-weighted distance score, not
an ETA; physical road distance is reported separately.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

from static_astar import CompactRoadGraph, haversine_km, parse_vertex_id

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "routing" / "mode_b" / "graph_data"
DEFAULT_CONDITION_FILE = PROJECT_ROOT / "routing" / "dynamic_conditions.json"

ConditionMap = dict[tuple[int, int], dict[str, Any]]


def load_conditions(path: Path, vertex_count: int) -> tuple[ConditionMap, float]:
    """Load directed conditions keyed by zero-based numeric node indices.

    Returns (condition_map, min_cost_multiplier). Blocked roads are excluded
    from the heuristic scale; absent/unknown conditions use multiplier 1.0.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Dynamic condition file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("conditions")
    if not isinstance(records, list):
        raise ValueError("Condition JSON must contain a 'conditions' list")

    condition_map: ConditionMap = {}
    min_multiplier = 1.0  # Unlisted edges keep their unweighted distance cost.
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Condition record {index} is not an object")
        try:
            source = parse_vertex_id(str(record["from"]), vertex_count)
            target = parse_vertex_id(str(record["to"]), vertex_count)
            status = str(record["status"]).strip().lower()
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid condition record at index {index}: {record!r}") from exc

        if status not in {"normal", "congested", "blocked"}:
            # Preserve the existing router's behavior: unknown status means
            # the edge keeps its base distance cost.
            status = "unknown"
        normalized = dict(record)
        normalized["status"] = status

        if status in {"normal", "congested"}:
            try:
                multiplier = float(record["cost_multiplier"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Condition record {index} needs a numeric cost_multiplier"
                ) from exc
            if not math.isfinite(multiplier) or multiplier < 0:
                raise ValueError(
                    f"Condition record {index} has invalid cost_multiplier {multiplier!r}"
                )
            normalized["cost_multiplier"] = multiplier
            min_multiplier = min(min_multiplier, multiplier)
        condition_map[(source, target)] = normalized

    # The heuristic is scaled by the minimum valid multiplier so it remains
    # conservative even if a future configuration contains multipliers < 1.
    return condition_map, min_multiplier


def dynamic_edge_cost(
    source: int,
    target: int,
    base_distance_km: float,
    conditions: Mapping[tuple[int, int], Mapping[str, Any]],
) -> float:
    """Return adjusted search cost; infinity marks a blocked directed edge."""
    condition = conditions.get((source, target))
    if condition is None:
        return base_distance_km
    status = condition.get("status", "unknown")
    if status == "blocked":
        return math.inf
    if status in {"normal", "congested"}:
        return base_distance_km * float(condition["cost_multiplier"])
    return base_distance_km


def dynamic_astar(
    graph: CompactRoadGraph,
    start: int,
    goal: int,
    conditions: Mapping[tuple[int, int], Mapping[str, Any]],
    min_multiplier: float = 1.0,
) -> dict[str, Any] | None:
    """Find a condition-aware road path; report physical and adjusted costs."""
    started = time.perf_counter()
    heuristic_scale = 0.99 * min(1.0, max(0.0, min_multiplier))

    def heuristic(node: int) -> float:
        return heuristic_scale * haversine_km(
            float(graph.latitudes[node]), float(graph.longitudes[node]),
            float(graph.latitudes[goal]), float(graph.longitudes[goal]),
        )

    if start == goal:
        return {
            "path": [start], "distance_km": 0.0, "dynamic_cost": 0.0,
            "expanded_nodes": 0, "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        }

    open_heap: list[tuple[float, int]] = [(heuristic(start), start)]
    g_score: dict[int, float] = {start: 0.0}
    physical_distance: dict[int, float] = {start: 0.0}
    came_from: dict[int, int] = {}
    closed: set[int] = set()
    expanded = 0

    while open_heap:
        current_f, current = heapq.heappop(open_heap)
        current_g = g_score.get(current)
        if current_g is None or current in closed:
            continue
        if current_f > current_g + heuristic(current) + 1e-9:
            continue

        if current == goal:
            path = [goal]
            node = goal
            while node in came_from:
                node = came_from[node]
                path.append(node)
            path.reverse()
            return {
                "path": path,
                "distance_km": physical_distance[goal],
                "dynamic_cost": current_g,
                "expanded_nodes": expanded,
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            }

        closed.add(current)
        expanded += 1
        for neighbor, edge_km in graph.neighbors(current):
            if neighbor in closed:
                continue
            adjusted_cost = dynamic_edge_cost(current, neighbor, edge_km, conditions)
            if math.isinf(adjusted_cost):
                continue
            tentative_g = current_g + adjusted_cost
            previous = g_score.get(neighbor)
            if previous is None or tentative_g < previous:
                g_score[neighbor] = tentative_g
                physical_distance[neighbor] = physical_distance[current] + edge_km
                came_from[neighbor] = current
                heapq.heappush(open_heap, (tentative_g + heuristic(neighbor), neighbor))

    return None


def save_geojson(
    graph: CompactRoadGraph,
    path_nodes: list[int],
    distance_km: float,
    dynamic_cost: float,
    output: Path,
) -> None:
    """Save a Dynamic A* route as a GeoJSON LineString (longitude, latitude)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    coordinates = []
    for node in path_nodes:
        lat, lon = graph.coordinates(node)
        coordinates.append([lon, lat])
    feature = {
        "type": "Feature",
        "properties": {
            "algorithm": "Dynamic A*",
            "distance_km": round(distance_km, 6),
            "dynamic_cost": round(dynamic_cost, 6),
            "node_count": len(path_nodes),
            "condition_source": str(DEFAULT_CONDITION_FILE.name),
            "cost_note": "Condition-weighted distance score; not an ETA",
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }
    output.write_text(json.dumps(feature, separators=(",", ":")), encoding="utf-8")


def _self_test() -> None:
    """Test dynamic rerouting on a tiny graph without opening project data."""
    class TinyGraph:
        vertex_count = 4
        # 0->1->3 costs 1 + 1, while 0->2->3 costs 1.5 + 1.5.
        indptr = [0, 2, 3, 4, 4]
        targets = [1, 2, 3, 3]
        distances = [1.0, 1.5, 1.0, 1.5]
        latitudes = [0.0, 0.0, 0.0, 0.0]
        longitudes = [0.0, 0.01, 0.02, 0.03]

        def neighbors(self, node: int):
            for i in range(self.indptr[node], self.indptr[node + 1]):
                yield self.targets[i], self.distances[i]

    # Penalizing 0->1 should make the alternative path win.
    conditions = {(0, 1): {"status": "congested", "cost_multiplier": 5.0}}
    result = dynamic_astar(TinyGraph(), 0, 3, conditions, min_multiplier=1.0)  # type: ignore[arg-type]
    assert result is not None, "Expected a route in the synthetic graph"
    assert result["path"] == [0, 2, 3], result
    assert abs(result["distance_km"] - 3.0) < 1e-9, result
    assert abs(result["dynamic_cost"] - 3.0) < 1e-9, result

    # A blocked edge must not be used; on this fixture it blocks the alternative
    # path as well, leaving the more expensive (but valid) first path.
    blocked_conditions = {
        (0, 1): {"status": "blocked"},
        (0, 2): {"status": "blocked"},
    }
    blocked_result = dynamic_astar(
        TinyGraph(), 0, 3, blocked_conditions, min_multiplier=1.0  # type: ignore[arg-type]
    )
    assert blocked_result is None, blocked_result
    print("Dynamic A* self-test passed: congestion rerouting and blocked-edge handling.")
    print("The Tamil Nadu graph and compact graph files were not loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true", help="Run a synthetic test only")
    group.add_argument("--start-node", help="Start node ID, e.g. V8903")
    parser.add_argument("--goal-node", help="Goal node ID, e.g. V180670")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Compact graph directory")
    parser.add_argument("--conditions", type=Path, default=DEFAULT_CONDITION_FILE, help="Road-condition JSON")
    parser.add_argument("--geojson", type=Path, help="Optional output GeoJSON route path")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.goal_node:
        parser.error("--goal-node is required with --start-node")

    graph = CompactRoadGraph(args.data_dir)
    conditions, min_multiplier = load_conditions(args.conditions, graph.vertex_count)
    start = parse_vertex_id(args.start_node, graph.vertex_count)
    goal = parse_vertex_id(args.goal_node, graph.vertex_count)

    print("Mode B Dynamic A*")
    print(f"Graph vertices: {graph.vertex_count:,}")
    print(f"Directed edges: {graph.edge_count:,}")
    print(f"Configured directed conditions: {len(conditions):,}")
    print(f"Minimum usable condition multiplier: {min_multiplier:g}")
    print(f"Start node: V{start + 1}; coordinates={graph.coordinates(start)}")
    print(f"Goal node:  V{goal + 1}; coordinates={graph.coordinates(goal)}")
    print("Searching compact road graph with configured conditions...")

    result = dynamic_astar(graph, start, goal, conditions, min_multiplier)
    if result is None:
        print("NO ROUTE FOUND under the current road-condition settings")
        return 2

    route_ids = [f"V{node + 1}" for node in result["path"]]
    print("\nDYNAMIC A* ROUTE RESULT")
    print(f"Route nodes: {len(route_ids):,}")
    print(f"Route edges: {max(0, len(route_ids) - 1):,}")
    print(f"Physical road distance: {result['distance_km']:.6f} km")
    print(f"Condition-adjusted route cost: {result['dynamic_cost']:.6f} weighted-km")
    print(f"Expanded nodes: {result['expanded_nodes']:,}")
    print(f"Search runtime: {result['elapsed_ms']:.3f} ms")
    print("First 10 route nodes:", " -> ".join(route_ids[:10]))
    if len(route_ids) > 10:
        print("Last 10 route nodes: ", " -> ".join(route_ids[-10:]))
    print("Note: weighted-km is a ranking cost, not travel time or ETA.")
    if args.geojson:
        save_geojson(graph, result["path"], result["distance_km"], result["dynamic_cost"], args.geojson)
        print(f"GeoJSON route saved to: {args.geojson.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
