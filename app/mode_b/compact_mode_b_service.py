"""Mode B service wrapper with Static/Dynamic and Time-aware route geometry.

Place this file at app/mode_b/compact_mode_b_service.py.

Leg 1 (Ambulance -> Patient) compares Static A* with Dynamic A*.
Leg 2 (Patient -> Hospital) compares Static A* with Time-aware A* so the
selected transport route shown on the map uses the same objective as dispatch.
The current front-end consumes the compatibility keys ``dynamic_points`` and
``dynamic_distance_km`` for the selected second route; the payload also emits
explicit selected/time-aware fields so the renderer can label it correctly.

ETA values are modelled from configured road-class speed assumptions and road
conditions. They are not live traffic predictions. Mode A is untouched.
"""
from __future__ import annotations

import argparse
import math
from collections.abc import Mapping
from typing import Any

from app.mode_b_service import ModeBDispatchService
from app.mode_b.compact_route_estimator import CompactModeBRouteEstimator


def _coordinate(
    record: Mapping[str, Any], latitude_key: str, longitude_key: str
) -> tuple[float, float]:
    try:
        latitude = float(record[latitude_key])
        longitude = float(record[longitude_key])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"Map location is missing valid {latitude_key}/{longitude_key} values."
        ) from exc
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("Map coordinates must be finite numbers.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Map coordinates are outside valid latitude/longitude ranges.")
    return latitude, longitude


def _leg_payload(
    compared: Mapping[str, Any], *, objective: str
) -> dict[str, Any]:
    """Normalize the estimator result while preserving existing UI field names."""
    normalized_objective = objective.strip().lower()
    if normalized_objective not in {"dynamic", "time"}:
        raise ValueError("objective must be 'dynamic' or 'time'")
    if not compared.get("reachable"):
        raise RuntimeError(str(compared.get("reason") or "Required route modes were not reachable."))

    static_route = compared.get("static_route") or {}
    selected_route = (
        compared.get("selected_route")
        or compared.get("time_route")
        or compared.get("dynamic_route")
        or {}
    )
    static_points = compared.get("static_points")
    selected_points = (
        compared.get("selected_points")
        or (compared.get("time_points") if normalized_objective == "time" else None)
        or (compared.get("dynamic_points") if normalized_objective == "dynamic" else None)
    )
    if not isinstance(static_points, list) or not isinstance(selected_points, list):
        raise ValueError("Route estimator did not return valid Static and selected route point arrays.")

    static_vertices = len(static_route.get("path_vertices") or [])
    selected_vertices = len(selected_route.get("path_vertices") or [])
    static_distance = float(compared.get("static_distance_km", 0.0))
    static_time = float(compared.get("static_time_minutes", 0.0))
    selected_distance = float(
        compared.get("selected_distance_km", compared.get(
            "time_distance_km" if normalized_objective == "time" else "dynamic_distance_km", 0.0
        ))
    )
    selected_time = float(
        compared.get("selected_time_minutes", compared.get(
            "time_time_minutes" if normalized_objective == "time" else "dynamic_time_minutes", 0.0
        ))
    )
    selected_label = "Time-aware A*" if normalized_objective == "time" else "Dynamic A*"

    payload: dict[str, Any] = {
        "static_points": static_points,
        # Compatibility aliases: the existing dashboard draws its second line
        # from dynamic_points. For leg 2 this intentionally aliases the selected
        # Time-aware A* route; selected_route_label disambiguates its objective.
        "dynamic_points": selected_points,
        "selected_points": selected_points,
        "static_vertices": static_vertices,
        "dynamic_vertices": selected_vertices,
        "selected_vertices": selected_vertices,
        "static_edges": max(0, static_vertices - 1),
        "dynamic_edges": max(0, selected_vertices - 1),
        "selected_edges": max(0, selected_vertices - 1),
        "static_distance_km": static_distance,
        "dynamic_distance_km": selected_distance,
        "selected_distance_km": selected_distance,
        "static_time_minutes": static_time,
        "dynamic_time_minutes": selected_time,
        "selected_time_minutes": selected_time,
        "rerouted": bool(compared.get("static_rerouted", False)),
        "static_cache_hit": bool(static_route.get("cache_hit", False)),
        "dynamic_cache_hit": bool(selected_route.get("cache_hit", False)),
        "selected_cache_hit": bool(selected_route.get("cache_hit", False)),
        "route_objective": normalized_objective,
        "selected_route_label": selected_label,
        "eta_type": "modelled road-aware estimate; not live traffic",
    }
    if normalized_objective == "time":
        payload.update({
            "time_points": selected_points,
            "time_vertices": selected_vertices,
            "time_edges": max(0, selected_vertices - 1),
            "time_distance_km": selected_distance,
            "time_time_minutes": selected_time,
            "time_cache_hit": bool(selected_route.get("cache_hit", False)),
            "time_astar_route_cost_minutes": selected_route.get("time_astar_route_cost_minutes"),
        })
    return payload


def build_map_payload(estimator: Any, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Build map paths with Dynamic A* for leg 1 and Time-aware A* for leg 2."""
    ambulance_lat, ambulance_lon = _coordinate(
        candidate, "ambulance_latitude", "ambulance_longitude"
    )
    patient_lat, patient_lon = _coordinate(
        candidate, "emergency_latitude", "emergency_longitude"
    )
    hospital_lat, hospital_lon = _coordinate(
        candidate, "hospital_latitude", "hospital_longitude"
    )

    # Keep the response route objective unchanged.
    leg1 = estimator.compare_routes(
        ambulance_lat, ambulance_lon, patient_lat, patient_lon, objective="dynamic"
    )
    # Use the same Time-aware A* objective as recommendation scoring for transport.
    leg2 = estimator.compare_routes(
        patient_lat, patient_lon, hospital_lat, hospital_lon, objective="time"
    )

    locations = {
        "ambulance": {"latitude": ambulance_lat, "longitude": ambulance_lon},
        "patient": {"latitude": patient_lat, "longitude": patient_lon},
        "hospital": {"latitude": hospital_lat, "longitude": hospital_lon},
    }
    routes = {
        "leg1": _leg_payload(leg1, objective="dynamic"),
        "leg2": _leg_payload(leg2, objective="time"),
    }
    return {"map_locations": locations, "map_routes": routes}


class CompactModeBDispatchService(ModeBDispatchService):
    """Existing Mode B dispatch service with compact routing and map output."""

    def __init__(self, live_dispatch_service: Any, **service_options: Any) -> None:
        workflow = live_dispatch_service.workflow
        integration = workflow.integration
        dispatcher = integration.dispatcher
        # Share the already-loaded graph by reference for legacy road metadata;
        # never deepcopy the large graph or call load_graph() from this wrapper.
        shared_graph = getattr(dispatcher, "graph", None)
        estimator = CompactModeBRouteEstimator(legacy_graph=shared_graph)
        super().__init__(live_dispatch_service, route_estimator=estimator, **service_options)
        self.compact_route_estimator = estimator

    def recommend(self, emergency_id: str) -> dict[str, Any]:
        recommendation = super().recommend(emergency_id)
        if recommendation.get("status") != "Recommended":
            return recommendation

        selected = recommendation.get("selected_candidate")
        if not isinstance(selected, Mapping):
            recommendation["map_route_status"] = "unavailable"
            recommendation["map_route_error"] = "The recommendation did not contain a selected candidate."
            return recommendation

        try:
            payload = build_map_payload(self.compact_route_estimator, selected)
            recommendation.update(payload)
            recommendation["map_route_status"] = "ready"
        except Exception as exc:
            # Map failure must not silently change a feasible recommendation.
            recommendation["map_route_status"] = "unavailable"
            recommendation["map_route_error"] = f"{type(exc).__name__}: {exc}"
        return recommendation


def create_compact_mode_b_dispatch_service(
    live_dispatch_service: Any, **service_options: Any
) -> CompactModeBDispatchService:
    """Build the compact-routed Mode B service around an existing live service."""
    return CompactModeBDispatchService(live_dispatch_service, **service_options)


def _self_test() -> None:
    class FakeEstimator:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float, float, float, str]] = []

        def compare_routes(
            self,
            slat: float,
            slon: float,
            elat: float,
            elon: float,
            *,
            objective: str = "dynamic",
        ) -> dict[str, Any]:
            self.calls.append((slat, slon, elat, elon, objective))
            points = [{"lat": slat, "lon": slon}, {"lat": elat, "lon": elon}]
            static_route = {"path_vertices": ["V1", "V2"], "cache_hit": False}
            selected_route = {
                "path_vertices": ["V1", "V3", "V2"] if objective == "time" else ["V1", "V2"],
                "cache_hit": False,
                "time_astar_route_cost_minutes": 3.25 if objective == "time" else None,
            }
            selected_distance = 1.8 if objective == "time" else 1.3
            selected_time = 3.25 if objective == "time" else 2.5
            result = {
                "reachable": True,
                "static_route": static_route,
                "selected_route": selected_route,
                "static_points": points,
                "selected_points": points,
                "static_distance_km": 1.2,
                "selected_distance_km": selected_distance,
                "static_time_minutes": 2.0,
                "selected_time_minutes": selected_time,
                "static_rerouted": objective == "time",
                "route_objective": objective,
            }
            if objective == "time":
                result.update({
                    "time_route": selected_route,
                    "time_points": points,
                    "time_distance_km": selected_distance,
                    "time_time_minutes": selected_time,
                })
            else:
                result.update({
                    "dynamic_route": selected_route,
                    "dynamic_points": points,
                    "dynamic_distance_km": selected_distance,
                    "dynamic_time_minutes": selected_time,
                })
            return result

    candidate = {
        "ambulance_latitude": 13.08, "ambulance_longitude": 80.27,
        "emergency_latitude": 13.09, "emergency_longitude": 80.28,
        "hospital_latitude": 13.10, "hospital_longitude": 80.29,
    }
    estimator = FakeEstimator()
    payload = build_map_payload(estimator, candidate)
    assert len(estimator.calls) == 2, estimator.calls
    assert estimator.calls[0][-1] == "dynamic", estimator.calls
    assert estimator.calls[1][-1] == "time", estimator.calls
    assert set(payload["map_locations"]) == {"ambulance", "patient", "hospital"}
    assert set(payload["map_routes"]) == {"leg1", "leg2"}
    assert payload["map_routes"]["leg1"]["route_objective"] == "dynamic"
    assert payload["map_routes"]["leg1"]["dynamic_time_minutes"] == 2.5
    assert payload["map_routes"]["leg2"]["route_objective"] == "time"
    assert payload["map_routes"]["leg2"]["selected_route_label"] == "Time-aware A*"
    assert payload["map_routes"]["leg2"]["dynamic_time_minutes"] == 3.25
    assert payload["map_routes"]["leg2"]["time_time_minutes"] == 3.25
    assert len(payload["map_routes"]["leg2"]["dynamic_points"]) == 2
    print("Compact Mode B service map-payload self-test passed.")
    print("Verified: Leg 1 uses Dynamic A*, Leg 2 uses Time-aware A*, and map payload compatibility aliases are present.")
    print("No Tamil Nadu graph, compact graph, Mode A runtime or live dispatch records were loaded.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run a synthetic map-payload test only")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("Only --self-test is supported; instantiate this service from the Mode B server.")
    _self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
