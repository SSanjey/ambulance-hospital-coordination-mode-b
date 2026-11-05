"""Compact-graph route estimator adapter for the Mode B dispatch service.

Place this file at app/mode_b/compact_route_estimator.py.

Implements the ``estimate_route(start_lat, start_lon, end_lat, end_lon)``
interface expected by the existing ModeBDispatchService, but uses Mode B's
memory-mapped compact graph, KD-Tree snapping, Static/Dynamic/Time-aware A*, and LRU cache.
It does not edit or import Flask or modify Mode A files.

By default, candidate scoring uses Dynamic A* (same broad behaviour as the
existing Mode B estimator). Call ``compare_routes`` only for the final selected
route legs to obtain Static plus the selected objective route without running both
algorithms for every candidate. Time-aware routing is intended for the Patient-to-Hospital leg.

ETAs use configurable assumptions, not live traffic. If a shared legacy graph
mapping is supplied, its existing highway metadata is read by reference; it is
not copied. Without that mapping, the fallback road class is ``road``.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_INDEX_DIR = PROJECT_ROOT / "routing" / "mode_b" / "kdtree_data"
DEFAULT_GRAPH_DATA_DIR = PROJECT_ROOT / "routing" / "mode_b" / "graph_data"
DEFAULT_CONDITION_FILE = PROJECT_ROOT / "routing" / "dynamic_conditions.json"

DEFAULT_BASE_SPEEDS_KMH = {
    "motorway": 65.0, "motorway_link": 40.0,
    "trunk": 55.0, "trunk_link": 35.0,
    "primary": 40.0, "primary_link": 30.0,
    "secondary": 35.0, "secondary_link": 27.0,
    "tertiary": 30.0, "tertiary_link": 23.0,
    "unclassified": 25.0, "residential": 20.0,
    "living_street": 10.0, "service": 12.0, "road": 20.0,
}
DEFAULT_CONDITION_SPEED_FACTORS = {"normal": 1.0, "congested": 0.55, "blocked": 0.0}
DEFAULT_CONDITION_PENALTIES = {"normal": 0.0, "congested": 0.5, "blocked": 1.0}


class CompactModeBRouteEstimator:
    """A lazy, cache-aware route estimator compatible with ModeBDispatchService."""

    def __init__(
        self,
        *,
        routing_service: Optional[Any] = None,
        vertex_index: Optional[Any] = None,
        legacy_graph: Optional[Mapping[str, Any]] = None,
        graph_data_dir: str | Path = DEFAULT_GRAPH_DATA_DIR,
        index_dir: str | Path = DEFAULT_INDEX_DIR,
        condition_path: str | Path = DEFAULT_CONDITION_FILE,
        max_snap_distance_km: float = 10.0,
        off_network_speed_kmh: float = 15.0,
        base_speeds_kmh: Optional[Mapping[str, float]] = None,
        condition_speed_factors: Optional[Mapping[str, float]] = None,
        condition_penalties: Optional[Mapping[str, float]] = None,
        road_speed_map: Optional[Mapping[str, float]] = None,
    ) -> None:
        if not math.isfinite(max_snap_distance_km) or max_snap_distance_km <= 0:
            raise ValueError("max_snap_distance_km must be positive and finite")
        if not math.isfinite(off_network_speed_kmh) or off_network_speed_kmh <= 0:
            raise ValueError("off_network_speed_kmh must be positive and finite")

        self.graph_data_dir = Path(graph_data_dir)
        self.index_dir = Path(index_dir)
        self.condition_path = Path(condition_path)
        self.max_snap_distance_km = float(max_snap_distance_km)
        self.off_network_speed_kmh = float(off_network_speed_kmh)
        self.base_speeds_kmh = dict(DEFAULT_BASE_SPEEDS_KMH)
        if base_speeds_kmh:
            self.base_speeds_kmh.update({str(k): float(v) for k, v in base_speeds_kmh.items()})
        self.condition_speed_factors = dict(DEFAULT_CONDITION_SPEED_FACTORS)
        if condition_speed_factors:
            self.condition_speed_factors.update({str(k).lower(): float(v) for k, v in condition_speed_factors.items()})
        self.condition_penalties = dict(DEFAULT_CONDITION_PENALTIES)
        if condition_penalties:
            self.condition_penalties.update({str(k).lower(): float(v) for k, v in condition_penalties.items()})
        self.road_speed_map = dict(road_speed_map or {})
        # Keep a shared reference. Do not deepcopy the large legacy graph.
        self.legacy_graph = legacy_graph
        self._routing_service = routing_service
        self._vertex_index = vertex_index
        self._snap_cache: dict[tuple[float, float], tuple[str | None, float]] = {}

        for table_name, table in (("base_speeds_kmh", self.base_speeds_kmh),):
            if any(not math.isfinite(v) or v <= 0 for v in table.values()):
                raise ValueError(f"All {table_name} values must be positive and finite")
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in self.condition_speed_factors.values()):
            raise ValueError("Condition speed factors must be within [0, 1]")
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in self.condition_penalties.values()):
            raise ValueError("Condition penalties must be within [0, 1]")

    @property
    def routing_service(self) -> Any:
        if self._routing_service is None:
            # Lazy import: synthetic self-tests must not open or load any real graph.
            from routing.mode_b.routing_service import ModeBRoutingService

            self._routing_service = ModeBRoutingService(
                data_dir=self.graph_data_dir,
                conditions_path=self.condition_path,
            )
        return self._routing_service

    @property
    def vertex_index(self) -> Any:
        if self._vertex_index is None:
            # Lazy import: only a real coordinate query loads/builds the KD-Tree.
            from routing.mode_b.kdtree_index import KDTreeVertexIndex

            self._vertex_index = KDTreeVertexIndex(self.index_dir)
        return self._vertex_index

    @staticmethod
    def _valid_coordinates(latitude: Any, longitude: Any) -> bool:
        try:
            lat, lon = float(latitude), float(longitude)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6371.0088
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        return 2.0 * radius * math.atan2(math.sqrt(max(0.0, a)), math.sqrt(max(0.0, 1.0 - a)))

    def _snap(self, latitude: float, longitude: float) -> tuple[str | None, float]:
        key = (round(latitude, 6), round(longitude, 6))
        if key in self._snap_cache:
            return self._snap_cache[key]
        candidate = self.vertex_index.query(latitude, longitude, k=1)[0]
        node_id = str(candidate["vertex_id"])
        distance = float(candidate["distance_km"])
        if distance > self.max_snap_distance_km:
            result: tuple[str | None, float] = (None, math.inf)
        else:
            result = (node_id, distance)
        self._snap_cache[key] = result
        return result

    def _edge_metadata(
        self,
        source_id: str,
        target_id: str,
        mode: str = "dynamic",
        selected_edge_index: int | None = None,
    ) -> dict[str, Any]:
        """Read edge metadata from CSR for time routes, legacy graph otherwise.

        Time-aware route selection uses the compact per-edge highway-code array.
        Its segment ETA must use the same road classes as the A* objective rather
        than independently scanning the legacy graph for possibly missing metadata.
        """
        if mode == "time":
            service = self.routing_service
            codes = getattr(service, "_edge_highway_codes", None)
            code_to_name = getattr(service, "_highway_code_to_name", None)
            if codes is None or code_to_name is None:
                raise RuntimeError(
                    "Time-aware edge metadata was not initialized by the routing service."
                )
            source_index = int(source_id[1:]) - 1
            target_index = int(target_id[1:]) - 1
            graph = service.graph
            row_start = int(graph.indptr[source_index])
            row_end = int(graph.indptr[source_index + 1])
            if selected_edge_index is not None:
                edge_index = int(selected_edge_index)
                if (
                    edge_index < row_start
                    or edge_index >= row_end
                    or int(graph.targets[edge_index]) != target_index
                ):
                    raise ValueError(
                        "Time A* selected edge does not match its "
                        f"path transition: {source_id} -> {target_id}"
                    )
                code = int(codes[edge_index])
                return {
                    "to": target_id,
                    "distance_km": float(graph.distances[edge_index]),
                    "highway": str(code_to_name.get(code, "road")),
                    "road_id": None,
                }
            for edge_index in range(row_start, row_end):
                if int(graph.targets[edge_index]) == target_index:
                    code = int(codes[edge_index])
                    return {
                        "to": target_id,
                        "distance_km": float(graph.distances[edge_index]),
                        "highway": str(code_to_name.get(code, "road")),
                        "road_id": None,
                    }
            raise ValueError(
                f"Compact route contains an edge missing from CSR: "
                f"{source_index} -> {target_index}"
            )

        if self.legacy_graph is None:
            return {"to": target_id, "highway": "road"}
        adjacency = self.legacy_graph.get("adjacency", {})
        for edge in adjacency.get(source_id, ()):
            if str(edge.get("to", "")) == target_id:
                return dict(edge)
        # Missing metadata should not fabricate connectivity or block a valid CSR edge.
        return {"to": target_id, "highway": "road"}

    def _condition(self, source_id: str, target_id: str) -> Mapping[str, Any] | None:
        source = int(source_id[1:]) - 1
        target = int(target_id[1:]) - 1
        return self.routing_service.conditions.get((source, target))

    def _segment_speed(
        self, edge: Mapping[str, Any], source_id: str, target_id: str, mode: str
    ) -> tuple[float, str, float, float]:
        highway = str(edge.get("highway", "road")).strip().lower() or "road"
        baseline = self.base_speeds_kmh.get(highway, self.base_speeds_kmh["road"])
        road_id = str(edge.get("road_id", ""))
        # The compact time-aware search currently optimizes configured road-class
        # baseline speeds; it does not store/import per-road posted speed limits.
        # Do not apply optional posted limits only after route selection, as that
        # would make the reported ETA disagree with the optimization objective.
        posted = None if mode == "time" else self.road_speed_map.get(road_id)
        if posted is not None and math.isfinite(float(posted)) and float(posted) > 0:
            baseline = min(baseline, float(posted))

        if mode == "static":
            status = "normal"
            factor = self.condition_speed_factors["normal"]
        else:
            record = self._condition(source_id, target_id) or {}
            status = str(record.get("status", "normal")).strip().lower()
            if status not in self.condition_speed_factors:
                status = "normal"
            factor = self.condition_speed_factors[status]
        return baseline * factor, status, baseline, float(posted) if posted is not None else math.nan

    def _build_mode_route(
        self,
        mode: str,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float,
        start_snap: tuple[str, float],
        end_snap: tuple[str, float],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        start_node, start_snap_km = start_snap
        end_node, end_snap_km = end_snap
        graph = self.routing_service.graph
        route_result, cache_hit, request_ms = self.routing_service.get_route(mode, start_node, end_node)
        if route_result is None:
            return {"reachable": False, "reason": "No traversable road route between snapped vertices.", "mode": mode}

        path_indices = [int(node) for node in route_result["path"]]
        path_vertices = [f"V{node + 1}" for node in path_indices]
        selected_edge_indices = (
            route_result.get("edge_indices") if mode == "time" else None
        )
        if mode == "time":
            if (
                not isinstance(selected_edge_indices, list)
                or len(selected_edge_indices) != max(0, len(path_indices) - 1)
            ):
                raise RuntimeError(
                    "Time-aware A* must return one exact CSR edge index "
                    "for every route transition."
                )
        graph_distance_km = float(route_result["distance_km"])
        start_lat, start_lon = graph.coordinates(path_indices[0])
        end_lat, end_lon = graph.coordinates(path_indices[-1])

        # Put the GPS locations around the graph path so Leaflet draws the connector legs too.
        points = [{"lat": start_latitude, "lon": start_longitude}]
        points.extend(
            {"lat": float(graph.coordinates(node)[0]), "lon": float(graph.coordinates(node)[1])}
            for node in path_indices
        )
        points.append({"lat": end_latitude, "lon": end_longitude})

        graph_minutes = 0.0
        weighted_penalty = 0.0
        segments: list[dict[str, Any]] = []
        speed_limit_count = 0
        for segment_index, (source_id, target_id) in enumerate(
            zip(path_vertices, path_vertices[1:])
        ):
            selected_edge_index = (
                int(selected_edge_indices[segment_index])
                if selected_edge_indices is not None
                else None
            )
            edge = self._edge_metadata(
                source_id,
                target_id,
                mode,
                selected_edge_index=selected_edge_index,
            )
            try:
                distance = float(edge.get("distance_km", math.nan))
            except (TypeError, ValueError, OverflowError):
                distance = math.nan
            # CSR distance is authoritative if metadata was absent or inconsistent.
            if not math.isfinite(distance) or distance < 0:
                source_index = int(source_id[1:]) - 1
                target_index = int(target_id[1:]) - 1
                distance = self._csr_edge_distance(source_index, target_index)
            speed, status, baseline, posted = self._segment_speed(edge, source_id, target_id, mode)
            if speed <= 0 or not math.isfinite(speed):
                return {
                    "reachable": False,
                    "reason": f"Route segment {source_id} -> {target_id} has no usable modelled speed.",
                    "mode": mode,
                }
            minutes = distance / speed * 60.0
            graph_minutes += minutes
            weighted_penalty += distance * self.condition_penalties.get(status, 0.0)
            if math.isfinite(posted):
                speed_limit_count += 1
            segments.append({
                "from": source_id,
                "to": target_id,
                "distance_km": distance,
                "road_id": edge.get("road_id"),
                "highway": edge.get("highway", "road"),
                "posted_maxspeed_kmh": None if not math.isfinite(posted) else posted,
                "baseline_speed_kmh": baseline,
                "condition_status": status,
                "effective_speed_kmh": speed,
                "estimated_time_minutes": minutes,
            })

        connector_distance_km = start_snap_km + end_snap_km
        connector_minutes = connector_distance_km / self.off_network_speed_kmh * 60.0
        total_distance_km = graph_distance_km + connector_distance_km
        total_minutes = graph_minutes + connector_minutes
        condition_penalty = weighted_penalty / graph_distance_km if graph_distance_km > 0 and mode == "dynamic" else 0.0
        result = {
            "reachable": True,
            "mode": mode,
            "start_vertex": start_node,
            "end_vertex": end_node,
            "path_vertices": path_vertices,
            "path_node_indices": path_indices,
            "points": points,
            "distance_km": total_distance_km,
            "graph_distance_km": graph_distance_km,
            "start_snap_distance_km": start_snap_km,
            "end_snap_distance_km": end_snap_km,
            "estimated_time_minutes": total_minutes,
            "graph_travel_time_minutes": graph_minutes,
            "connector_time_minutes": connector_minutes,
            "dynamic_astar_route_cost": route_result.get("dynamic_cost", graph_distance_km),
            "time_astar_route_cost_minutes": route_result.get("time_cost_minutes") if mode == "time" else None,
            "route_objective": (
                "modelled_travel_time" if mode == "time"
                else ("condition_weighted_distance" if mode == "dynamic" else "physical_distance")
            ),
            "route_condition_penalty": min(1.0, max(0.0, condition_penalty)),
            "segment_count": len(segments),
            "segments_using_osm_maxspeed": speed_limit_count,
            "segments": segments,
            "estimate_type": (
                "modelled road-class travel-time route; configured conditions; not live traffic"
                if mode == "time" else "modelled road-aware ETA; not live traffic"
            ),
            "cache_hit": bool(cache_hit),
            "route_request_ms": float(request_ms),
            "route_search_ms": float(route_result.get("elapsed_ms", 0.0)),
            "expanded_nodes": int(route_result.get("expanded_nodes", 0)),
        }
        result["estimator_elapsed_ms"] = (time.perf_counter() - started) * 1000.0
        return result

    def _csr_edge_distance(self, source_index: int, target_index: int) -> float:
        graph = self.routing_service.graph
        for neighbor, distance in graph.neighbors(source_index):
            if neighbor == target_index:
                return float(distance)
        raise ValueError(f"Compact route contains an edge missing from CSR: {source_index} -> {target_index}")

    def _prepare_snaps(
        self, start_latitude: Any, start_longitude: Any, end_latitude: Any, end_longitude: Any
    ) -> tuple[tuple[str, float], tuple[str, float], tuple[float, float, float, float]] | dict[str, Any]:
        if not all((
            self._valid_coordinates(start_latitude, start_longitude),
            self._valid_coordinates(end_latitude, end_longitude),
        )):
            return {"reachable": False, "reason": "Invalid start or destination coordinates."}
        start_lat, start_lon = float(start_latitude), float(start_longitude)
        end_lat, end_lon = float(end_latitude), float(end_longitude)
        start_snap = self._snap(start_lat, start_lon)
        end_snap = self._snap(end_lat, end_lon)
        if start_snap[0] is None:
            return {"reachable": False, "reason": "No graph vertex is within the configured start snapping distance."}
        if end_snap[0] is None:
            return {"reachable": False, "reason": "No graph vertex is within the configured destination snapping distance."}
        return start_snap, end_snap, (start_lat, start_lon, end_lat, end_lon)

    def estimate_route(
        self, start_latitude: Any, start_longitude: Any, end_latitude: Any, end_longitude: Any
    ) -> dict[str, Any]:
        """Return a Dynamic A* route (preserves existing Ambulance-to-Patient behavior)."""
        prepared = self._prepare_snaps(start_latitude, start_longitude, end_latitude, end_longitude)
        if isinstance(prepared, dict):
            return prepared
        start_snap, end_snap, coords = prepared
        return self._build_mode_route("dynamic", *coords, start_snap, end_snap)

    def estimate_transport_route(
        self, start_latitude: Any, start_longitude: Any, end_latitude: Any, end_longitude: Any
    ) -> dict[str, Any]:
        """Return a Time-aware A* route for the Patient-to-Hospital leg only."""
        prepared = self._prepare_snaps(start_latitude, start_longitude, end_latitude, end_longitude)
        if isinstance(prepared, dict):
            return prepared
        start_snap, end_snap, coords = prepared
        return self._build_mode_route("time", *coords, start_snap, end_snap)

    def compare_routes(
        self,
        start_latitude: Any,
        start_longitude: Any,
        end_latitude: Any,
        end_longitude: Any,
        *,
        objective: str = "dynamic",
    ) -> dict[str, Any]:
        """Compare Static A* with either Dynamic A* or Time-aware A* for a map leg.

        ``objective='dynamic'`` preserves the previous contract. Use
        ``objective='time'`` for the Patient-to-Hospital leg so the displayed
        selected route matches the route objective used during recommendation.
        """
        normalized_objective = objective.strip().lower()
        if normalized_objective not in {"dynamic", "time"}:
            raise ValueError("objective must be 'dynamic' or 'time'")
        prepared = self._prepare_snaps(start_latitude, start_longitude, end_latitude, end_longitude)
        if isinstance(prepared, dict):
            return {"reachable": False, "reason": prepared["reason"]}
        start_snap, end_snap, coords = prepared
        static = self._build_mode_route("static", *coords, start_snap, end_snap)
        selected = self._build_mode_route(normalized_objective, *coords, start_snap, end_snap)
        if not static.get("reachable") or not selected.get("reachable"):
            return {
                "reachable": False,
                "reason": "Could not calculate both route modes.",
                "static_route": static,
                "selected_route": selected,
                "route_objective": normalized_objective,
            }

        result: dict[str, Any] = {
            "reachable": True,
            "static_route": static,
            "selected_route": selected,
            "selected_points": selected["points"],
            "selected_distance_km": selected["distance_km"],
            "selected_time_minutes": selected["estimated_time_minutes"],
            "route_objective": normalized_objective,
            "static_points": static["points"],
            "static_distance_km": static["distance_km"],
            "static_time_minutes": static["estimated_time_minutes"],
            "static_rerouted": static["path_vertices"] != selected["path_vertices"],
        }
        if normalized_objective == "time":
            result.update({
                "time_route": selected,
                "time_points": selected["points"],
                "time_distance_km": selected["distance_km"],
                "time_time_minutes": selected["estimated_time_minutes"],
            })
        else:
            # Preserve old dynamic aliases for existing map/rendering consumers.
            result.update({
                "dynamic_route": selected,
                "dynamic_points": selected["points"],
                "dynamic_distance_km": selected["distance_km"],
                "dynamic_time_minutes": selected["estimated_time_minutes"],
            })
        return result

    @staticmethod
    def _unreachable(reason: str) -> dict[str, Any]:
        return {"reachable": False, "reason": reason}


def create_compact_mode_b_dispatch_service(live_dispatch_service: Any, **service_options: Any) -> Any:
    """Construct the existing ModeBDispatchService with this estimator injected.

    The legacy graph is passed by reference only for road-class metadata; no deepcopy
    or second JSON load is performed here. This factory does not change the existing
    service module or Mode A dispatch path.
    """
    try:
        from app.mode_b_service import ModeBDispatchService
    except ImportError:
        from ..mode_b_service import ModeBDispatchService  # type: ignore[no-redef]

    workflow = live_dispatch_service.workflow
    integration = workflow.integration
    dispatcher = integration.dispatcher
    shared_graph = getattr(dispatcher, "graph", None)
    estimator = CompactModeBRouteEstimator(legacy_graph=shared_graph)
    return ModeBDispatchService(
        live_dispatch_service, route_estimator=estimator, **service_options
    )


def _self_test() -> None:
    """Synthetic tests cover existing dynamic behavior and new time-mode contract."""
    import numpy as np

    class TinyGraph:
        vertex_count = 3
        edge_count = 3
        indptr = np.asarray([0, 2, 3, 3], dtype=np.int64)
        targets = np.asarray([1, 2, 2], dtype=np.int32)
        distances = np.asarray([1.0, 3.0, 1.0], dtype=np.float32)

        def coordinates(self, node: int) -> tuple[float, float]:
            points = [(0.0, 0.0), (0.0, 0.5), (1.0, 1.0)]
            return points[node]

        def neighbors(self, node: int):
            rows = {0: [(1, 1.0), (2, 3.0)], 1: [(2, 1.0)], 2: []}
            yield from rows[node]

    class FakeRoutingService:
        def __init__(self) -> None:
            self.graph = TinyGraph()
            self.vertex_count = 3
            self.conditions = {(0, 2): {"status": "congested", "cost_multiplier": 2.0}}
            self.graph_version = "tiny-graph"
            self.condition_version = "tiny-conditions"
            self._edge_highway_codes = np.asarray([12, 1, 1], dtype=np.uint8)
            self._highway_code_to_name = {0: "road", 1: "motorway", 12: "residential"}
            self.cache = type("FakeCache", (), {"stats": lambda _self: {"hits": 0, "misses": 0}})()

        def get_route(self, mode: str, start: str, goal: str):
            if mode == "static":
                path, distance = [0, 1, 2], 2.0
            elif mode == "time":
                path, distance = [0, 2], 3.0
            else:
                path, distance = [0, 2], 3.0
            result = {
                "path": path,
                "distance_km": distance,
                "elapsed_ms": 1.0,
                "expanded_nodes": 2,
            }
            if mode == "dynamic":
                result["dynamic_cost"] = 6.0
            if mode == "time":
                # TinyGraph edge 0 -> 2 is CSR edge index 1.
                result["edge_indices"] = [1]
                result["time_cost_minutes"] = 60.0
                result["estimated_time_minutes"] = 60.0
            return result, False, 1.0

    class FakeIndex:
        def query(self, lat: float, lon: float, k: int = 1):
            if lat < 0.5:
                return [{"vertex_id": "V1", "distance_km": 0.0}]
            return [{"vertex_id": "V3", "distance_km": 0.0}]

    estimator = CompactModeBRouteEstimator(
        routing_service=FakeRoutingService(), vertex_index=FakeIndex(),
        max_snap_distance_km=10.0,
    )
    dynamic = estimator.estimate_route(0.0, 0.0, 1.0, 1.0)
    assert dynamic.get("reachable") is True, dynamic
    assert dynamic["path_vertices"] == ["V1", "V3"], dynamic
    assert len(dynamic["points"]) == 4, dynamic

    timed = estimator.estimate_transport_route(0.0, 0.0, 1.0, 1.0)
    assert timed.get("reachable") is True, timed
    assert timed["mode"] == "time"
    assert timed["route_objective"] == "modelled_travel_time"
    assert timed["path_vertices"] == ["V1", "V3"]
    assert timed["segments"][0]["highway"] == "motorway"

    compared = estimator.compare_routes(0.0, 0.0, 1.0, 1.0)
    assert compared.get("reachable") is True, compared
    assert compared["static_distance_km"] == 2.0
    assert compared["dynamic_distance_km"] == 3.0
    assert compared["static_rerouted"] is True
    assert compared["static_points"][0] == {"lat": 0.0, "lon": 0.0}
    assert compared["dynamic_points"][-1] == {"lat": 1.0, "lon": 1.0}

    compared_time = estimator.compare_routes(0.0, 0.0, 1.0, 1.0, objective="time")
    assert compared_time.get("reachable") is True, compared_time
    assert compared_time["route_objective"] == "time"
    assert compared_time["time_route"]["mode"] == "time"
    assert compared_time["time_points"][-1] == {"lat": 1.0, "lon": 1.0}

    print("Compact Mode B route-estimator self-test passed.")
    print("Verified: Dynamic A* compatibility, Time-aware A* transport method, compact highway-code metadata, route geometry, and map comparison objectives.")
    print("No Tamil Nadu graph, compact graph files, or live dispatch records were loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run synthetic compatibility checks only")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
