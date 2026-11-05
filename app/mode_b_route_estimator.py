"""Road-aware ETA estimation for Mode B emergency dispatch.

This module does not modify or replace Mode A routing. It calls the existing
Dynamic A* implementation to select a route, then estimates travel time from
its road segments using a configurable road-class speed profile, OSM maxspeed
metadata where available, and a separate configurable traffic-speed factor.

IMPORTANT: speeds and traffic factors are modelling assumptions, not measured
ambulance speeds or live-traffic data. Dynamic A* cost_multiplier is used only
by the existing route-selection algorithm; it is not treated as a speed factor.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from routing.dynamic_astar_router import dynamic_astar
except ImportError:  # Allows isolated unit tests with an injected route_function.
    try:
        from ..routing.dynamic_astar_router import dynamic_astar  # type: ignore
    except ImportError:
        dynamic_astar = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BASE_SPEEDS_KMH = {
    # Configurable simulation assumptions; not official speed limits.
    "motorway": 65.0,
    "motorway_link": 40.0,
    "trunk": 55.0,
    "trunk_link": 35.0,
    "primary": 40.0,
    "primary_link": 30.0,
    "secondary": 35.0,
    "secondary_link": 27.0,
    "tertiary": 30.0,
    "tertiary_link": 23.0,
    "unclassified": 25.0,
    "residential": 20.0,
    "living_street": 10.0,
    "service": 12.0,
    "road": 20.0,
}
_DEFAULT_CONDITION_SPEED_FACTORS = {
    # Keep separate from routing cost_multiplier in dynamic_conditions.json.
    "normal": 1.0,
    "congested": 0.55,  # Explicitly a configurable simulation assumption.
    "blocked": 0.0,
}
_DEFAULT_CONDITION_PENALTIES = {
    "normal": 0.0,
    "congested": 0.5,
    "blocked": 1.0,
}
_SPEED_TAG_RE = re.compile(r'"maxspeed"\s*=>\s*"([^"]+)"', re.IGNORECASE)
_SPEED_VALUE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|mi/?h|km/?h|kph)?\s*$", re.IGNORECASE)


class ModeBRouteEstimator:
    """Estimate road-based route ETAs for ambulance-response and transport legs.

    Parameters can be injected for integration and unit testing. In the real
    application, pass a shared graph instance when one is already loaded to
    avoid loading the large statewide graph twice.
    """

    def __init__(
        self,
        graph: Optional[Mapping[str, Any]] = None,
        condition_map: Optional[Mapping[tuple[str, str], Mapping[str, Any]]] = None,
        road_speed_map: Optional[Mapping[str, float]] = None,
        graph_path: Optional[str | Path] = None,
        condition_path: Optional[str | Path] = None,
        road_database_path: Optional[str | Path] = None,
        base_speeds_kmh: Optional[Mapping[str, float]] = None,
        condition_speed_factors: Optional[Mapping[str, float]] = None,
        condition_penalties: Optional[Mapping[str, float]] = None,
        grid_size_degrees: float = 0.02,
        max_snap_distance_km: float = 10.0,
        off_network_speed_kmh: float = 15.0,
        route_function: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.graph_path = Path(graph_path) if graph_path else PROJECT_ROOT / "routing" / "tamil_nadu_graph.json"
        self.condition_path = Path(condition_path) if condition_path else PROJECT_ROOT / "routing" / "dynamic_conditions.json"
        self.road_database_path = Path(road_database_path) if road_database_path else PROJECT_ROOT / "data" / "tamil_nadu_routable_roads.gpkg"

        self._graph = graph
        self._condition_map = dict(condition_map) if condition_map is not None else None
        self._road_speed_map = dict(road_speed_map) if road_speed_map is not None else None
        self._route_function = route_function or dynamic_astar

        self.base_speeds_kmh = dict(_DEFAULT_BASE_SPEEDS_KMH)
        if base_speeds_kmh:
            self.base_speeds_kmh.update({str(k): float(v) for k, v in base_speeds_kmh.items()})
        self.condition_speed_factors = dict(_DEFAULT_CONDITION_SPEED_FACTORS)
        if condition_speed_factors:
            self.condition_speed_factors.update({str(k).lower(): float(v) for k, v in condition_speed_factors.items()})
        self.condition_penalties = dict(_DEFAULT_CONDITION_PENALTIES)
        if condition_penalties:
            self.condition_penalties.update({str(k).lower(): float(v) for k, v in condition_penalties.items()})

        if not math.isfinite(grid_size_degrees) or grid_size_degrees <= 0:
            raise ValueError("grid_size_degrees must be a positive finite number.")
        if not math.isfinite(max_snap_distance_km) or max_snap_distance_km <= 0:
            raise ValueError("max_snap_distance_km must be a positive finite number.")
        if not math.isfinite(off_network_speed_kmh) or off_network_speed_kmh <= 0:
            raise ValueError("off_network_speed_kmh must be a positive finite number.")
        if any(not math.isfinite(v) or v <= 0 for v in self.base_speeds_kmh.values()):
            raise ValueError("All road-class baseline speeds must be positive finite values.")
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in self.condition_speed_factors.values()):
            raise ValueError("Condition speed factors must be between 0 and 1.")
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in self.condition_penalties.values()):
            raise ValueError("Condition penalties must be between 0 and 1.")

        self.grid_size_degrees = float(grid_size_degrees)
        self.max_snap_distance_km = float(max_snap_distance_km)
        self.off_network_speed_kmh = float(off_network_speed_kmh)
        self._spatial_index: Optional[dict[tuple[int, int], list[str]]] = None
        self._graph_bounds: Optional[tuple[float, float, float, float]] = None
        self._snap_cache: dict[tuple[float, float], tuple[Optional[str], float]] = {}

    @staticmethod
    def _valid_coordinates(latitude: Any, longitude: Any) -> bool:
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180

    @staticmethod
    def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius_km = 6371.0088
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        return radius_km * 2 * math.atan2(math.sqrt(max(0.0, a)), math.sqrt(max(0.0, 1.0 - a)))

    @classmethod
    def parse_maxspeed_kmh(cls, value: Any) -> Optional[float]:
        """Parse simple OSM maxspeed values; unknown/symbolic values return None."""
        if value is None:
            return None
        match = _SPEED_VALUE_RE.fullmatch(str(value))
        if not match:
            return None
        speed = float(match.group(1))
        unit = (match.group(2) or "km/h").lower()
        if speed <= 0 or not math.isfinite(speed):
            return None
        if unit in {"mph", "mi/h", "mih"}:
            speed *= 1.609344
        # km/h, kmh, kph and bare numeric OSM values are treated as km/h.
        return speed if math.isfinite(speed) and speed > 0 else None

    @staticmethod
    def _condition_map_from_file(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        records = data.get("conditions", []) if isinstance(data, dict) else []
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                continue
            start = str(record.get("from", "")).strip()
            end = str(record.get("to", "")).strip()
            if start and end:
                result[(start, end)] = dict(record)
        return result

    def _ensure_graph(self) -> None:
        if self._graph is None:
            if not self.graph_path.exists():
                raise FileNotFoundError(f"Road graph not found: {self.graph_path}")
            with self.graph_path.open("r", encoding="utf-8") as handle:
                graph = json.load(handle)
            if not isinstance(graph, dict) or not isinstance(graph.get("vertices"), dict) or not isinstance(graph.get("adjacency"), dict):
                raise ValueError("Graph JSON must contain dictionary fields 'vertices' and 'adjacency'.")
            self._graph = graph
        if self._condition_map is None:
            if not self.condition_path.exists():
                raise FileNotFoundError(f"Dynamic condition file not found: {self.condition_path}")
            self._condition_map = self._condition_map_from_file(self.condition_path)
        if self._road_speed_map is None:
            self._road_speed_map = self._load_road_speeds(self.road_database_path)

    @classmethod
    def _load_road_speeds(cls, path: Path) -> dict[str, float]:
        """Load numeric OSM maxspeed tags keyed by OSM way ID from the GeoPackage."""
        if not path.exists():
            return {}
        result: dict[str, float] = {}
        connection = sqlite3.connect(str(path))
        try:
            # The checked project file uses the 'roads' feature table.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(roads)")}
            if not {"osm_id", "other_tags"}.issubset(columns):
                return {}
            rows = connection.execute(
                "SELECT osm_id, other_tags FROM roads "
                "WHERE lower(coalesce(other_tags, '')) LIKE '%maxspeed%'"
            )
            for osm_id, other_tags in rows:
                if not osm_id or not other_tags:
                    continue
                match = _SPEED_TAG_RE.search(other_tags)
                if not match:
                    continue
                speed = cls.parse_maxspeed_kmh(match.group(1))
                if speed is None:
                    continue
                key = str(osm_id)
                # Repeated OSM way IDs should normally have the same tag. If
                # they differ, choosing the lower value is the conservative cap.
                result[key] = min(result.get(key, speed), speed)
        finally:
            connection.close()
        return result

    def _build_spatial_index(self) -> None:
        self._ensure_graph()
        assert self._graph is not None
        vertices = self._graph["vertices"]
        index: dict[tuple[int, int], list[str]] = defaultdict(list)
        min_lat = min_lon = math.inf
        max_lat = max_lon = -math.inf
        cell_size = self.grid_size_degrees
        for node_id, coordinate in vertices.items():
            try:
                lat = float(coordinate["latitude"])
                lon = float(coordinate["longitude"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            index[(math.floor(lat / cell_size), math.floor(lon / cell_size))].append(str(node_id))
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
        if not index:
            raise ValueError("The road graph has no vertices with valid coordinates.")
        self._spatial_index = dict(index)
        self._graph_bounds = (min_lat, max_lat, min_lon, max_lon)

    def _nearest_vertex(self, latitude: float, longitude: float) -> tuple[Optional[str], float]:
        self._ensure_graph()
        if self._spatial_index is None or self._graph_bounds is None:
            self._build_spatial_index()
        assert self._spatial_index is not None and self._graph_bounds is not None and self._graph is not None

        # Rounded-key cache avoids repeated snapping of the same operational site.
        cache_key = (round(latitude, 6), round(longitude, 6))
        if cache_key in self._snap_cache:
            return self._snap_cache[cache_key]

        min_lat, max_lat, min_lon, max_lon = self._graph_bounds
        clamped_lat = min(max(latitude, min_lat), max_lat)
        clamped_lon = min(max(longitude, min_lon), max_lon)
        lower_bound = self._haversine_km(latitude, longitude, clamped_lat, clamped_lon)
        if lower_bound > self.max_snap_distance_km:
            self._snap_cache[cache_key] = (None, math.inf)
            return None, math.inf

        size = self.grid_size_degrees
        base_i = math.floor(latitude / size)
        base_j = math.floor(longitude / size)
        best_node: Optional[str] = None
        best_distance = math.inf
        vertices = self._graph["vertices"]

        # Expand the search grid until a conservative lower bound proves that
        # no unvisited cell can contain a closer vertex.
        max_rings = max(8, int(math.ceil((self.max_snap_distance_km / 100.0) / size)) + 4)
        max_rings = max(max_rings, 16)
        for ring in range(max_rings):
            if ring == 0:
                cells = [(base_i, base_j)]
            else:
                cells = []
                for di in range(-ring, ring + 1):
                    cells.append((base_i + di, base_j - ring))
                    cells.append((base_i + di, base_j + ring))
                for dj in range(-ring + 1, ring):
                    cells.append((base_i - ring, base_j + dj))
                    cells.append((base_i + ring, base_j + dj))
            for cell in cells:
                for node_id in self._spatial_index.get(cell, ()):
                    coordinate = vertices.get(node_id)
                    if coordinate is None:
                        continue
                    distance = self._haversine_km(
                        latitude, longitude,
                        float(coordinate["latitude"]), float(coordinate["longitude"]),
                    )
                    if distance < best_distance:
                        best_distance = distance
                        best_node = node_id

            lat_low = (base_i - ring) * size
            lat_high = (base_i + ring + 1) * size
            lon_low = (base_j - ring) * size
            lon_high = (base_j + ring + 1) * size
            lat_border_km = min(abs(latitude - lat_low), abs(lat_high - latitude)) * 111.195
            max_abs_lat = min(89.9, max(abs(lat_low), abs(lat_high)))
            lon_km_per_degree = 111.195 * max(0.0, math.cos(math.radians(max_abs_lat)))
            lon_border_km = min(abs(longitude - lon_low), abs(lon_high - longitude)) * lon_km_per_degree
            outside_lower_bound = max(0.0, min(lat_border_km, lon_border_km))
            if best_node is not None and best_distance <= outside_lower_bound * 0.95:
                break

        if best_node is None or best_distance > self.max_snap_distance_km:
            result = (None, math.inf)
        else:
            result = (best_node, best_distance)
        self._snap_cache[cache_key] = result
        return result

    def _edge_routing_cost(self, start: str, end: str, distance_km: float) -> float:
        assert self._condition_map is not None
        condition = self._condition_map.get((start, end))
        if not condition:
            return distance_km
        status = str(condition.get("status", "")).lower()
        if status == "blocked":
            return math.inf
        if status in {"normal", "congested"}:
            multiplier = self._number(condition.get("cost_multiplier"), 1.0)
            if multiplier is not None:
                return distance_km * multiplier
        return distance_km

    def _edge_for_path(self, start: str, end: str) -> Optional[Mapping[str, Any]]:
        assert self._graph is not None
        choices = []
        for edge in self._graph["adjacency"].get(start, []):
            if str(edge.get("to", "")) != end:
                continue
            distance = self._number(edge.get("distance_km"))
            if distance is None or distance < 0:
                continue
            cost = self._edge_routing_cost(start, end, distance)
            if math.isfinite(cost):
                choices.append((cost, distance, edge))
        if not choices:
            return None
        # Stable ordering follows the route cost first, then physical distance.
        choices.sort(key=lambda item: (item[0], item[1]))
        return choices[0][2]

    def _segment_speed(self, edge: Mapping[str, Any], start: str, end: str) -> tuple[float, str, float]:
        assert self._condition_map is not None and self._road_speed_map is not None
        highway = str(edge.get("highway", "road")).strip().lower() or "road"
        baseline = self.base_speeds_kmh.get(highway, self.base_speeds_kmh.get("road", 20.0))
        road_id = str(edge.get("road_id", ""))
        posted_speed = self._road_speed_map.get(road_id)
        # Treat mapped OSM maxspeed as an upper bound. The road-class baseline
        # remains a modelling assumption about typical ambulance travel speed.
        chosen = min(baseline, posted_speed) if posted_speed is not None else baseline
        condition = self._condition_map.get((start, end), {})
        status = str(condition.get("status", "normal")).strip().lower() or "normal"
        factor = self.condition_speed_factors.get(status, 1.0)
        effective = chosen * factor
        return effective, status, chosen

    def estimate_route(
        self,
        start_latitude: Any,
        start_longitude: Any,
        end_latitude: Any,
        end_longitude: Any,
    ) -> dict[str, Any]:
        """Return route distance, estimated travel time and route diagnostics."""
        if not all((
            self._valid_coordinates(start_latitude, start_longitude),
            self._valid_coordinates(end_latitude, end_longitude),
        )):
            return self._unreachable("Invalid start or destination coordinates.")
        self._ensure_graph()
        assert self._graph is not None and self._condition_map is not None

        start_lat, start_lon = float(start_latitude), float(start_longitude)
        end_lat, end_lon = float(end_latitude), float(end_longitude)
        start_node, start_snap_km = self._nearest_vertex(start_lat, start_lon)
        end_node, end_snap_km = self._nearest_vertex(end_lat, end_lon)
        if start_node is None:
            return self._unreachable("No graph vertex is within the configured start snapping distance.")
        if end_node is None:
            return self._unreachable("No graph vertex is within the configured destination snapping distance.")

        if start_node == end_node:
            path = [start_node]
            dynamic_cost = 0.0
        else:
            if self._route_function is None:
                raise ImportError(
                    "Could not import routing.dynamic_astar_router.dynamic_astar. "
                    "Run from the project root or inject route_function explicitly."
                )
            route_result = self._route_function(self._graph, start_node, end_node, self._condition_map)
            if not isinstance(route_result, tuple) or len(route_result) < 2:
                return self._unreachable("The routing function returned an invalid result.")
            path, dynamic_cost = route_result[0], route_result[1]
            numeric_dynamic_cost = self._number(dynamic_cost, math.inf)
            if not path or numeric_dynamic_cost is None or not math.isfinite(numeric_dynamic_cost):
                return self._unreachable("No traversable route was found between the snapped vertices.")
            path = list(path)

        total_graph_distance = 0.0
        graph_travel_minutes = 0.0
        weighted_condition_penalty = 0.0
        segment_count = 0
        used_speed_limits = 0
        segment_summaries: list[dict[str, Any]] = []
        for start, end in zip(path, path[1:]):
            edge = self._edge_for_path(str(start), str(end))
            if edge is None:
                return self._unreachable(f"Route path contains a missing or blocked edge: {start} -> {end}.")
            distance = self._number(edge.get("distance_km"))
            if distance is None or distance < 0:
                return self._unreachable(f"Route path contains an invalid distance on {start} -> {end}.")
            effective_speed, status, chosen_pretraffic_speed = self._segment_speed(edge, str(start), str(end))
            if effective_speed <= 0 or not math.isfinite(effective_speed):
                return self._unreachable(f"Route segment {start} -> {end} has no usable estimated speed.")
            segment_minutes = (distance / effective_speed) * 60.0
            total_graph_distance += distance
            graph_travel_minutes += segment_minutes
            weighted_condition_penalty += distance * self.condition_penalties.get(status, 0.0)
            segment_count += 1
            if str(edge.get("road_id", "")) in (self._road_speed_map or {}):
                used_speed_limits += 1
            segment_summaries.append({
                "from": str(start),
                "to": str(end),
                "distance_km": distance,
                "road_id": edge.get("road_id"),
                "highway": edge.get("highway", "road"),
                "posted_maxspeed_kmh": (self._road_speed_map or {}).get(str(edge.get("road_id", ""))),
                "baseline_speed_kmh": chosen_pretraffic_speed,
                "condition_status": status,
                "effective_speed_kmh": effective_speed,
                "estimated_time_minutes": segment_minutes,
            })

        # Identical start and destination coordinates require no travel.
        same_coordinates = start_lat == end_lat and start_lon == end_lon
        connector_distance = (
            0.0 if same_coordinates else start_snap_km + end_snap_km
        )
        connector_minutes = (connector_distance / self.off_network_speed_kmh) * 60.0
        total_distance = total_graph_distance + connector_distance
        total_minutes = graph_travel_minutes + connector_minutes
        condition_penalty = (weighted_condition_penalty / total_graph_distance) if total_graph_distance > 0 else 0.0
        return {
            "reachable": True,
            "start_vertex": start_node,
            "end_vertex": end_node,
            "path_vertices": path,
            "distance_km": total_distance,
            "graph_distance_km": total_graph_distance,
            "start_snap_distance_km": start_snap_km,
            "end_snap_distance_km": end_snap_km,
            "estimated_time_minutes": total_minutes,
            "graph_travel_time_minutes": graph_travel_minutes,
            "connector_time_minutes": connector_minutes,
            "dynamic_astar_route_cost": dynamic_cost,
            "route_condition_penalty": min(1.0, max(0.0, condition_penalty)),
            "segment_count": segment_count,
            "segments_using_osm_maxspeed": used_speed_limits,
            "segments": segment_summaries,
            "estimate_type": "modelled road-aware ETA; not live traffic",
            "speed_assumptions": {
                "road_class_baselines_kmh": dict(self.base_speeds_kmh),
                "congestion_speed_factors": dict(self.condition_speed_factors),
                "off_network_speed_kmh": self.off_network_speed_kmh,
                "maxspeed_policy": "OSM maxspeed caps the configurable road-class baseline",
            },
        }

    @staticmethod
    def _unreachable(reason: str) -> dict[str, Any]:
        return {"reachable": False, "reason": reason}

    def estimate_candidate(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Add response/transport ETA fields to a Mode B candidate record.

        Unreachable candidates are marked route_feasible=False and intentionally
        do not receive finite cost-model input fields. Callers must filter them
        before invoking ModeBCostModel.score_candidates.
        """
        if not isinstance(candidate, Mapping):
            raise ValueError("Candidate must be a mapping or dictionary.")
        required = (
            "ambulance_latitude", "ambulance_longitude",
            "emergency_latitude", "emergency_longitude",
            "hospital_latitude", "hospital_longitude",
        )
        missing = [name for name in required if name not in candidate]
        if missing:
            raise ValueError("Candidate is missing coordinates: " + ", ".join(missing))

        result = dict(candidate)
        response = self.estimate_route(
            candidate["ambulance_latitude"], candidate["ambulance_longitude"],
            candidate["emergency_latitude"], candidate["emergency_longitude"],
        )
        transport = self.estimate_route(
            candidate["emergency_latitude"], candidate["emergency_longitude"],
            candidate["hospital_latitude"], candidate["hospital_longitude"],
        )
        result["response_route"] = response
        result["transport_route"] = transport
        if not response.get("reachable") or not transport.get("reachable"):
            reasons = []
            if not response.get("reachable"):
                reasons.append("Response route: " + str(response.get("reason", "unreachable")))
            if not transport.get("reachable"):
                reasons.append("Transport route: " + str(transport.get("reason", "unreachable")))
            result["route_feasible"] = False
            result["route_infeasibility_reasons"] = reasons
            return result

        response_time = float(response["estimated_time_minutes"])
        transport_time = float(transport["estimated_time_minutes"])
        response_distance = float(response["distance_km"])
        transport_distance = float(transport["distance_km"])
        total_route_distance = response_distance + transport_distance
        if total_route_distance > 0:
            route_penalty = (
                float(response["route_condition_penalty"]) * response_distance
                + float(transport["route_condition_penalty"]) * transport_distance
            ) / total_route_distance
        else:
            route_penalty = 0.0

        result.update({
            "route_feasible": True,
            "response_time_minutes": response_time,
            "transport_time_minutes": transport_time,
            "response_distance_km": response_distance,
            "transport_distance_km": transport_distance,
            "route_condition_penalty": min(1.0, max(0.0, route_penalty)),
            "route_estimation_method": "Dynamic A* path + segment distance / modelled speed",
        })
        return result

    def estimate_candidates(self, candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Estimate a supplied shortlist; this method does not create candidate pairs."""
        if candidates is None:
            raise ValueError("Candidates cannot be None.")
        estimated: list[dict[str, Any]] = []
        unreachable = 0
        for candidate in candidates:
            item = self.estimate_candidate(candidate)
            if item.get("route_feasible"):
                estimated.append(item)
            else:
                unreachable += 1
        return {
            "candidates": estimated,
            "input_candidate_count": len(candidates),
            "route_feasible_count": len(estimated),
            "unreachable_candidate_count": unreachable,
        }
