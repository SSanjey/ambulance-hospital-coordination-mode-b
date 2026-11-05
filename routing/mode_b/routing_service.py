"""Mode B routing facade integrating Static A*, Dynamic A*, Time-aware A*, and LRU caching.

Run from the project root:
  python routing\\mode_b\\routing_service.py --self-test
  python routing\\mode_b\\routing_service.py --mode static --start-node V8903 --goal-node V180670 --repeat 2
  python routing\\mode_b\\routing_service.py --mode dynamic --start-node V8903 --goal-node V180670 --repeat 2
  python routing\\mode_b\\routing_service.py --mode time --start-node V8903 --goal-node V180670 --repeat 2

Time-aware routing requires the compact graph to have been rebuilt with
build_compact_graph.py so edge_highway_codes.npy and its metadata are present.
Existing Static and Dynamic routing do not require that new file. Mode A is untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from static_astar import (  # noqa: E402
    CompactRoadGraph,
    astar as static_astar,
    parse_vertex_id,
    save_geojson as save_static_geojson,
)
from dynamic_astar import (  # noqa: E402
    dynamic_astar,
    load_conditions,
    save_geojson as save_dynamic_geojson,
)
from route_cache import (  # noqa: E402
    LRURouteCache,
    compact_graph_version,
    file_content_version,
)
from time_astar import (  # noqa: E402
    DEFAULT_BASE_SPEEDS_KMH,
    DEFAULT_CONDITION_SPEED_FACTORS,
    load_highway_codes,
    time_astar as shortest_time_astar,
)

DEFAULT_DATA_DIR = PROJECT_ROOT / "routing" / "mode_b" / "graph_data"
DEFAULT_CONDITION_FILE = PROJECT_ROOT / "routing" / "dynamic_conditions.json"


class ModeBRoutingService:
    """Load shared routing data once and cache successful route results.

    Highway metadata is loaded lazily, only when ``mode='time'`` is requested.
    Therefore the pre-existing static/dynamic routing calls continue to work with
    a compact graph built before edge highway codes were introduced.
    """

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        conditions_path: Path = DEFAULT_CONDITION_FILE,
        cache_max_entries: int = 32,
        cache_max_path_nodes: int = 100_000,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.conditions_path = Path(conditions_path)
        self.graph = CompactRoadGraph(self.data_dir)
        metadata_path = self.data_dir / "graph_metadata.json"
        self.graph_version = compact_graph_version(metadata_path)
        self.conditions, self.min_multiplier = load_conditions(
            self.conditions_path, self.graph.vertex_count
        )
        # Hash the small condition file once at service startup. If conditions
        # are updated while running, create/reload the service to refresh them.
        self.condition_version = file_content_version(self.conditions_path)
        self.cache = LRURouteCache(
            max_entries=cache_max_entries,
            max_total_path_nodes=cache_max_path_nodes,
        )
        self._edge_highway_codes = None
        self._highway_code_to_name: dict[int, str] | None = None
        self._time_objective_version: str | None = None

    def _ensure_time_metadata(self) -> None:
        """Load and validate the per-edge road classes on first time-aware query."""
        if self._edge_highway_codes is not None and self._highway_code_to_name is not None:
            return

        codes, code_to_name = load_highway_codes(str(self.data_dir), self.graph.edge_count)
        metadata_path = self.data_dir / "graph_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        array_name = str(metadata.get("edge_highway_codes_file", "edge_highway_codes.npy"))
        array_stat = (self.data_dir / array_name).stat()
        # Cache time-aware routes under a version that identifies the condition
        # file, speed assumptions, condition-to-speed assumptions, class mapping,
        # and highway-array file version. No giant array is hashed on each query.
        model_descriptor = {
            "base_speeds_kmh": DEFAULT_BASE_SPEEDS_KMH,
            "condition_speed_factors": DEFAULT_CONDITION_SPEED_FACTORS,
            "highway_code_to_name": {str(k): v for k, v in sorted(code_to_name.items())},
            "highway_array_name": array_name,
            "highway_array_size": array_stat.st_size,
            "highway_array_mtime_ns": array_stat.st_mtime_ns,
        }
        model_bytes = json.dumps(
            model_descriptor, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        model_hash = hashlib.sha256(model_bytes).hexdigest()
        self._edge_highway_codes = codes
        self._highway_code_to_name = code_to_name
        self._time_objective_version = hashlib.sha256(
            f"{self.condition_version}:{model_hash}".encode("utf-8")
        ).hexdigest()

    def get_route(
        self,
        mode: str,
        start_node_id: str,
        goal_node_id: str,
    ) -> tuple[dict[str, Any] | None, bool, float]:
        """Return (route result, cache_hit, lookup_or_compute_ms).

        Supported modes are ``static``, ``dynamic``, and ``time``. The time mode
        minimizes estimated travel time from configured road-class speeds and
        configured edge statuses; it does not use live traffic telemetry.
        """
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"static", "dynamic", "time"}:
            raise ValueError("mode must be 'static', 'dynamic', or 'time'")
        start = parse_vertex_id(start_node_id, self.graph.vertex_count)
        goal = parse_vertex_id(goal_node_id, self.graph.vertex_count)

        if normalized_mode == "static":
            compute: Callable[[], dict[str, Any] | None] = lambda: static_astar(
                self.graph, start, goal
            )
            algorithm = "static_astar"
            condition_version = "static"
        elif normalized_mode == "dynamic":
            compute = lambda: dynamic_astar(
                self.graph, start, goal, self.conditions, self.min_multiplier
            )
            algorithm = "dynamic_astar"
            condition_version = self.condition_version
        else:
            self._ensure_time_metadata()
            assert self._edge_highway_codes is not None
            assert self._highway_code_to_name is not None
            assert self._time_objective_version is not None
            compute = lambda: shortest_time_astar(
                self.graph,
                start,
                goal,
                self._edge_highway_codes,
                self._highway_code_to_name,
                conditions=self.conditions,
            )
            algorithm = "time_astar"
            condition_version = self._time_objective_version

        return self.cache.get_or_compute(
            algorithm=algorithm,
            start_node=start,
            goal_node=goal,
            graph_version=self.graph_version,
            condition_version=condition_version,
            compute=compute,
        )

    def save_route_geojson(self, mode: str, result: dict[str, Any], output: Path) -> None:
        """Export a route without mislabelling the time objective as Static A*."""
        normalized_mode = mode.strip().lower()
        if normalized_mode == "static":
            save_static_geojson(
                self.graph, result["path"], float(result["distance_km"]), output
            )
        elif normalized_mode == "dynamic":
            save_dynamic_geojson(
                self.graph,
                result["path"],
                float(result["distance_km"]),
                float(result["dynamic_cost"]),
                output,
            )
        elif normalized_mode == "time":
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            coordinates = []
            for node in result["path"]:
                latitude, longitude = self.graph.coordinates(int(node))
                coordinates.append([longitude, latitude])
            feature = {
                "type": "Feature",
                "properties": {
                    "algorithm": "Time-aware A*",
                    "objective": "modelled_travel_time",
                    "distance_km": float(result["distance_km"]),
                    "estimated_time_minutes": float(result["estimated_time_minutes"]),
                    "node_count": len(result["path"]),
                    "estimate_type": "modelled road-class ETA; not live traffic",
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
            output.write_text(json.dumps(feature, separators=(",", ":")), encoding="utf-8")
        else:
            raise ValueError("mode must be 'static', 'dynamic', or 'time'")


def _self_test() -> None:
    """Exercise cache integration for all objectives without loading graph files."""
    cache = LRURouteCache(max_entries=6, max_total_path_nodes=30)
    compute_calls = {"static": 0, "dynamic": 0, "time": 0}

    def make_compute(mode: str) -> Callable[[], dict[str, Any]]:
        def compute() -> dict[str, Any]:
            compute_calls[mode] += 1
            result: dict[str, Any] = {
                "path": [1, 2, 3],
                "distance_km": 3.5,
                "expanded_nodes": 12,
                "elapsed_ms": 10.0,
                "algorithm": f"{mode}_astar",
            }
            if mode == "dynamic":
                result["dynamic_cost"] = 4.0
            if mode == "time":
                result["estimated_time_minutes"] = 5.0
                result["time_cost_minutes"] = 5.0
            return result
        return compute

    args = dict(start_node=1, goal_node=3, graph_version="self-test-graph")
    first, first_hit, _ = cache.get_or_compute(
        algorithm="static_astar", condition_version="static",
        compute=make_compute("static"), **args
    )
    second, second_hit, _ = cache.get_or_compute(
        algorithm="static_astar", condition_version="static",
        compute=make_compute("static"), **args
    )
    dynamic, dynamic_hit, _ = cache.get_or_compute(
        algorithm="dynamic_astar", condition_version="conditions-A",
        compute=make_compute("dynamic"), **args
    )
    changed, changed_hit, _ = cache.get_or_compute(
        algorithm="dynamic_astar", condition_version="conditions-B",
        compute=make_compute("dynamic"), **args
    )
    timed, time_hit, _ = cache.get_or_compute(
        algorithm="time_astar", condition_version="time-model-A",
        compute=make_compute("time"), **args
    )
    timed_again, time_hit_again, _ = cache.get_or_compute(
        algorithm="time_astar", condition_version="time-model-A",
        compute=make_compute("time"), **args
    )

    assert all(item is not None for item in (first, second, dynamic, changed, timed, timed_again))
    assert not first_hit and second_hit
    assert not dynamic_hit and not changed_hit
    assert not time_hit and time_hit_again
    assert compute_calls == {"static": 1, "dynamic": 2, "time": 1}, compute_calls
    assert cache.stats()["hits"] == 2
    print("Mode B routing-service cache integration self-test passed.")
    print("Verified: Static/Dynamic/Time objective separation, repeated-route cache hits, and condition-version separation.")
    print("No Tamil Nadu graph or compact graph files were loaded.")
    print("Cache stats:", cache.stats())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run integration self-test only")
    parser.add_argument("--mode", choices=("static", "dynamic", "time"), help="Routing objective")
    parser.add_argument("--start-node", help="Start vertex, e.g. V8903")
    parser.add_argument("--goal-node", help="Goal vertex, e.g. V180670")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--conditions", type=Path, default=DEFAULT_CONDITION_FILE)
    parser.add_argument("--geojson", type=Path, help="Optional GeoJSON output path")
    parser.add_argument("--repeat", type=int, default=1, help="Number of identical queries to run (default 1)")
    parser.add_argument("--cache-entries", type=int, default=32)
    parser.add_argument("--cache-path-nodes", type=int, default=100_000)
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.mode or not args.start_node or not args.goal_node:
        parser.error("--mode, --start-node, and --goal-node are required unless --self-test is used")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    service = ModeBRoutingService(
        data_dir=args.data_dir,
        conditions_path=args.conditions,
        cache_max_entries=args.cache_entries,
        cache_max_path_nodes=args.cache_path_nodes,
    )
    print(f"Mode B {args.mode.title()} A* with LRU route cache")
    print(f"Graph vertices: {service.graph.vertex_count:,}; directed edges: {service.graph.edge_count:,}")
    for run_no in range(1, args.repeat + 1):
        result, cache_hit, wall_ms = service.get_route(args.mode, args.start_node, args.goal_node)
        print(f"\nRun {run_no}/{args.repeat}: cache={'HIT' if cache_hit else 'MISS'}; request time={wall_ms:.3f} ms")
        if result is None:
            print("NO ROUTE FOUND")
            return 2
        node_ids = [f"V{node + 1}" for node in result["path"]]
        print(f"Route nodes: {len(node_ids):,}; route edges: {max(0, len(node_ids) - 1):,}")
        print(f"Physical road distance: {float(result['distance_km']):.6f} km")
        if args.mode == "dynamic":
            print(f"Condition-adjusted cost: {float(result['dynamic_cost']):.6f} weighted-km (not ETA)")
        elif args.mode == "time":
            print(f"Estimated travel time: {float(result['estimated_time_minutes']):.3f} modelled minutes (not live traffic)")
        if not cache_hit:
            print(f"Expanded nodes: {int(result['expanded_nodes']):,}; search runtime: {float(result['elapsed_ms']):.3f} ms")
        else:
            print("Route search skipped because a cached result was reused.")
        print("First 10 nodes:", " -> ".join(node_ids[:10]))
        if len(node_ids) > 10:
            print("Last 10 nodes: ", " -> ".join(node_ids[-10:]))
        if args.geojson and run_no == args.repeat:
            service.save_route_geojson(args.mode, result, args.geojson)
            print(f"GeoJSON route saved to: {args.geojson.resolve()}")
    print("\nLRU cache stats:", service.cache.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
