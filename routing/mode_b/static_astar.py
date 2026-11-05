"""Memory-mapped Static A* router for the Mode B compact Tamil Nadu graph.

Run from the project root:
    python routing\\mode_b\\static_astar.py --self-test
    python routing\\mode_b\\static_astar.py --start-node V8903 --goal-node V180670
    python routing\\mode_b\\static_astar.py --start-node V8903 --goal-node V180670 --geojson results\\mode_b\\static_test_route.geojson

This module reads only the compact .npy files created by build_compact_graph.py.
It does not load the 493 MB graph JSON or modify Mode A files.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "routing" / "mode_b" / "graph_data"
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS84 coordinate pairs."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    a = min(1.0, max(0.0, a))
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def parse_vertex_id(value: str, vertex_count: int) -> int:
    """Convert V123 to a zero-based CSR node index."""
    text = value.strip().upper()
    if not text.startswith("V") or not text[1:].isdigit():
        raise ValueError(f"Invalid vertex ID {value!r}; expected a value such as V8903")
    numeric = int(text[1:])
    if numeric < 1 or numeric > vertex_count:
        raise ValueError(f"Vertex {text} is outside the indexed range V1..V{vertex_count}")
    return numeric - 1


class CompactRoadGraph:
    """Read-only memory-mapped CSR graph with coordinates indexed by vertex ID."""

    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        metadata_path = data_dir / "graph_metadata.json"
        if not metadata_path.is_file():
            raise FileNotFoundError(
                f"Compact graph metadata not found: {metadata_path}. "
                "Build it first using build_compact_graph.py --build."
            )
        self.metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        required = (
            "indptr.npy",
            "edge_targets.npy",
            "edge_distances_km.npy",
            "latitudes_by_id.npy",
            "longitudes_by_id.npy",
        )
        missing = [name for name in required if not (data_dir / name).is_file()]
        if missing:
            raise FileNotFoundError("Compact graph files missing: " + ", ".join(missing))

        # mmap_mode='r' keeps the large arrays disk-backed until pages are accessed.
        self.indptr = np.load(data_dir / "indptr.npy", mmap_mode="r")
        self.targets = np.load(data_dir / "edge_targets.npy", mmap_mode="r")
        self.distances = np.load(data_dir / "edge_distances_km.npy", mmap_mode="r")
        self.latitudes = np.load(data_dir / "latitudes_by_id.npy", mmap_mode="r")
        self.longitudes = np.load(data_dir / "longitudes_by_id.npy", mmap_mode="r")
        self.vertex_count = int(self.metadata["vertex_count"])
        self.edge_count = int(self.metadata["directed_edge_count"])

        if len(self.indptr) != self.vertex_count + 1:
            raise ValueError("CSR indptr length does not match vertex_count + 1")
        if len(self.targets) != len(self.distances) or len(self.targets) != self.edge_count:
            raise ValueError("CSR edge target/distance lengths do not match metadata")
        if int(self.indptr[-1]) != self.edge_count:
            raise ValueError("CSR final indptr offset does not match edge count")
        if len(self.latitudes) != self.vertex_count or len(self.longitudes) != self.vertex_count:
            raise ValueError("Coordinate array lengths do not match vertex_count")

    def neighbors(self, node: int):
        start = int(self.indptr[node])
        end = int(self.indptr[node + 1])
        for edge_index in range(start, end):
            yield int(self.targets[edge_index]), float(self.distances[edge_index])

    def heuristic(self, node: int, goal: int) -> float:
        # A 0.99-scaled great-circle estimate is deliberately conservative with
        # respect to rounding in source edge distances. Costs remain kilometres.
        return 0.99 * haversine_km(
            float(self.latitudes[node]), float(self.longitudes[node]),
            float(self.latitudes[goal]), float(self.longitudes[goal]),
        )

    def coordinates(self, node: int) -> tuple[float, float]:
        return float(self.latitudes[node]), float(self.longitudes[node])


def astar(graph: CompactRoadGraph, start: int, goal: int) -> dict[str, Any] | None:
    """Return a road-node path and route stats, or None if no path exists."""
    started = time.perf_counter()
    if start == goal:
        return {
            "path": [start], "distance_km": 0.0, "expanded_nodes": 0,
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        }

    open_heap: list[tuple[float, int]] = [(graph.heuristic(start, goal), start)]
    g_score: dict[int, float] = {start: 0.0}
    came_from: dict[int, int] = {}
    closed: set[int] = set()
    expanded = 0

    while open_heap:
        current_f, current = heapq.heappop(open_heap)
        current_g = g_score.get(current)
        if current_g is None or current in closed:
            continue
        # Old heap entries can remain after a node receives a better score.
        if current_f > current_g + graph.heuristic(current, goal) + 1e-9:
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
                "distance_km": current_g,
                "expanded_nodes": expanded,
                "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            }

        closed.add(current)
        expanded += 1
        for neighbor, edge_km in graph.neighbors(current):
            if neighbor in closed:
                continue
            tentative_g = current_g + edge_km
            previous = g_score.get(neighbor)
            if previous is None or tentative_g < previous:
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                priority = tentative_g + graph.heuristic(neighbor, goal)
                heapq.heappush(open_heap, (priority, neighbor))

    return None


def save_geojson(graph: CompactRoadGraph, path_nodes: list[int], distance_km: float, output: Path) -> None:
    """Save the route geometry as a GeoJSON LineString (longitude, latitude)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    coordinates = []
    for node in path_nodes:
        lat, lon = graph.coordinates(node)
        coordinates.append([lon, lat])
    feature = {
        "type": "Feature",
        "properties": {
            "algorithm": "Static A*",
            "distance_km": round(distance_km, 6),
            "node_count": len(path_nodes),
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }
    output.write_text(json.dumps(feature, separators=(",", ":")), encoding="utf-8")


def _self_test() -> None:
    """Synthetic test independent of the statewide graph and its index files."""
    class TinyGraph:
        vertex_count = 4
        indptr = np.asarray([0, 2, 3, 4, 4], dtype=np.int64)
        targets = np.asarray([1, 2, 3, 3], dtype=np.int32)
        distances = np.asarray([1.0, 5.0, 1.0, 1.0], dtype=np.float32)
        latitudes = np.asarray([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        longitudes = np.asarray([0.0, 0.01, 0.02, 0.03], dtype=np.float32)

        def neighbors(self, node: int):
            for i in range(int(self.indptr[node]), int(self.indptr[node + 1])):
                yield int(self.targets[i]), float(self.distances[i])

        def heuristic(self, node: int, goal: int) -> float:
            return 0.0  # Dijkstra-equivalent heuristic to make fixture exact.

        def coordinates(self, node: int):
            return float(self.latitudes[node]), float(self.longitudes[node])

    result = astar(TinyGraph(), 0, 3)  # type: ignore[arg-type]
    assert result is not None, "Expected a path in the synthetic graph"
    assert result["path"] == [0, 1, 3], result
    assert abs(result["distance_km"] - 2.0) < 1e-9, result
    same = astar(TinyGraph(), 2, 2)  # type: ignore[arg-type]
    assert same is not None and same["path"] == [2] and same["distance_km"] == 0.0
    print("Static A* self-test passed on a four-node synthetic graph.")
    print("The Tamil Nadu graph and compact graph files were not loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true", help="Run a small synthetic test only")
    group.add_argument("--start-node", help="Start node ID, e.g. V8903")
    parser.add_argument("--goal-node", help="Goal node ID, e.g. V180670")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Compact graph output directory")
    parser.add_argument("--geojson", type=Path, help="Optional path to save route geometry as GeoJSON")
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.goal_node:
        parser.error("--goal-node is required with --start-node")

    graph = CompactRoadGraph(args.data_dir)
    start = parse_vertex_id(args.start_node, graph.vertex_count)
    goal = parse_vertex_id(args.goal_node, graph.vertex_count)
    print("Mode B Static A*")
    print(f"Graph vertices: {graph.vertex_count:,}")
    print(f"Directed edges: {graph.edge_count:,}")
    print(f"Start node: V{start + 1}; coordinates={graph.coordinates(start)}")
    print(f"Goal node:  V{goal + 1}; coordinates={graph.coordinates(goal)}")
    print("Searching compact road graph...")
    result = astar(graph, start, goal)
    if result is None:
        print("NO ROUTE FOUND")
        return 2

    route_ids = [f"V{node + 1}" for node in result["path"]]
    print("\nSTATIC A* ROUTE RESULT")
    print(f"Route nodes: {len(route_ids):,}")
    print(f"Route edges: {max(0, len(route_ids) - 1):,}")
    print(f"Road distance: {result['distance_km']:.6f} km")
    print(f"Expanded nodes: {result['expanded_nodes']:,}")
    print(f"Search runtime: {result['elapsed_ms']:.3f} ms")
    print("First 10 route nodes:", " -> ".join(route_ids[:10]))
    if len(route_ids) > 10:
        print("Last 10 route nodes: ", " -> ".join(route_ids[-10:]))
    if args.geojson:
        save_geojson(graph, result["path"], result["distance_km"], args.geojson)
        print(f"GeoJSON route saved to: {args.geojson.resolve()}")
    print("Note: distance is road distance; ETA is not yet calculated by this module.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
