
"""Mode B multi-criteria dispatch integration.

Mode B is an opt-in path. Existing Mode A calls do not provide a
mode_b_candidate and therefore retain their current selection behavior.

ETAs are modelled estimates based on the project road graph, configurable
road-class speed assumptions, and configured edge conditions. They are not
live-traffic predictions. When the compact Mode B estimator is injected, the
Ambulance-to-Patient leg keeps Dynamic A*, while Patient-to-Hospital can use
Time-aware A* to minimize modelled travel time.

Branch and Bound selects the final pair from candidates that have already
passed the existing feasibility and route-reachability checks.
"""
from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any, Optional

try:
    from app.mode_b_data_adapter import ModeBDataAdapter
    from app.mode_b_candidate_generator import ModeBCandidateGenerator
    from app.mode_b_constraints import ModeBConstraints
    from app.mode_b_cost_model import ModeBCostModel
    from app.mode_b_candidate_ranker import ModeBCandidateRanker
    from app.mode_b_route_estimator import ModeBRouteEstimator
    from app.mode_b.branch_bound_selector import select_best_pair
except ImportError:
    from .mode_b_data_adapter import ModeBDataAdapter
    from .mode_b_candidate_generator import ModeBCandidateGenerator
    from .mode_b_constraints import ModeBConstraints
    from .mode_b_cost_model import ModeBCostModel
    from .mode_b_candidate_ranker import ModeBCandidateRanker
    from .mode_b_route_estimator import ModeBRouteEstimator
    from .mode_b.branch_bound_selector import select_best_pair

try:
    from routing.dynamic_astar_router import load_conditions
except ImportError:
    from ..routing.dynamic_astar_router import load_conditions


class _PrecomputedSelectionContext:
    """Adapter allowing the generator to use a validated shortlist."""

    def __init__(self, context: Mapping[str, Any]) -> None:
        self.context = dict(context)

    def get_selection_context(
        self, emergency: Mapping[str, Any]
    ) -> dict[str, Any]:
        return dict(self.context)


class ModeBDispatchService:
    """Recommend and commit an ambulance-hospital pair using Mode B.

    Workflow:
        1. Obtain eligible ambulance and hospital records.
        2. Build a bounded shortlist.
        3. Generate candidates and apply feasibility constraints.
        4. Estimate response and transport routes.
        5. Score route-feasible candidates.
        6. Use Branch and Bound to select the final pair.
        7. Retain sorted alternatives for display.
        8. Commit the selected pair through the existing dispatch service.
    """

    def __init__(
        self,
        live_dispatch_service: Any,
        *,
        max_ambulances: int = 6,
        max_hospitals: int = 8,
        priority_hospital_slots: int = 2,
        return_top_candidates: int = 5,
        route_estimator: Optional[Any] = None,
        condition_map: Optional[
            Mapping[tuple[str, str], Mapping[str, Any]]
        ] = None,
        cost_model: Optional[Any] = None,
        constraints: Optional[Any] = None,
        ranker: Optional[Any] = None,
    ) -> None:
        if max_ambulances < 1 or max_hospitals < 1:
            raise ValueError("Candidate shortlist limits must be positive.")

        if priority_hospital_slots < 0 or return_top_candidates < 1:
            raise ValueError(
                "priority_hospital_slots must be non-negative "
                "and return_top_candidates positive."
            )

        self.live_service = live_dispatch_service
        self.workflow = live_dispatch_service.workflow
        self.integration = self.workflow.integration
        self.dispatcher = self.integration.dispatcher
        self.coordinator = self.dispatcher.coordinator
        self.ambulance_manager = self.coordinator.ambulance_manager
        self.hospital_manager = self.coordinator.hospital_manager

        self.max_ambulances = int(max_ambulances)
        self.max_hospitals = int(max_hospitals)
        self.priority_hospital_slots = int(priority_hospital_slots)
        self.return_top_candidates = int(return_top_candidates)

        self.data_adapter = ModeBDataAdapter(
            self.ambulance_manager,
            self.hospital_manager,
        )
        self.candidate_generator = ModeBCandidateGenerator(
            self.data_adapter
        )
        self.constraints = constraints or ModeBConstraints()
        self.cost_model = cost_model or ModeBCostModel()
        self.ranker = ranker or ModeBCandidateRanker()

        self.condition_map = (
            dict(condition_map)
            if condition_map is not None
            else load_conditions()
        )

        self.route_estimator = route_estimator or ModeBRouteEstimator(
            graph=self.dispatcher.graph,
            condition_map=self.condition_map,
        )

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None

        return result if math.isfinite(result) else None

    @staticmethod
    def _direct_distance_km(
        lat1: Any, lon1: Any, lat2: Any, lon2: Any
    ) -> float:
        values = []

        for item in (lat1, lon1, lat2, lon2):
            try:
                number = float(item)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Candidate coordinates must be numeric."
                ) from exc

            if not math.isfinite(number):
                raise ValueError(
                    "Candidate coordinates must be finite."
                )

            values.append(number)

        a_lat, a_lon, b_lat, b_lon = values

        if not (
            -90 <= a_lat <= 90
            and -90 <= b_lat <= 90
            and -180 <= a_lon <= 180
            and -180 <= b_lon <= 180
        ):
            raise ValueError(
                "Candidate coordinates are outside valid latitude/"
                "longitude ranges."
            )

        radius = 6371.0088
        p1 = math.radians(a_lat)
        p2 = math.radians(b_lat)
        dlat = math.radians(b_lat - a_lat)
        dlon = math.radians(b_lon - a_lon)

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(p1)
            * math.cos(p2)
            * math.sin(dlon / 2) ** 2
        )

        return radius * 2 * math.atan2(
            math.sqrt(max(0.0, a)),
            math.sqrt(max(0.0, 1.0 - a)),
        )

    @staticmethod
    def _identifier(
        record: Mapping[str, Any], field: str
    ) -> str:
        return str(record.get(field, "")).strip()

    @classmethod
    def _hospital_priority(
        cls, record: Mapping[str, Any]
    ) -> Optional[float]:
        for field in (
            "policy_priority",
            "facility_priority",
            "priority",
            "hospital_priority",
        ):
            value = cls._number(record.get(field))
            if value is not None:
                return value

        return None

    @staticmethod
    def _priority_penalties(
        hospitals: list[Mapping[str, Any]]
    ) -> dict[str, float]:
        priorities: dict[str, float] = {}

        for hospital in hospitals:
            identifier = str(hospital.get("id", "")).strip()
            value = ModeBDispatchService._hospital_priority(hospital)

            if identifier:
                # Lower policy priority means a stronger preference.
                priorities[identifier] = (
                    value if value is not None else math.nan
                )

        known = sorted(
            {
                value
                for value in priorities.values()
                if math.isfinite(value)
            }
        )

        if len(known) <= 1:
            return {
                key: (0.0 if math.isfinite(value) else 0.5)
                for key, value in priorities.items()
            }

        rank = {
            value: index / (len(known) - 1)
            for index, value in enumerate(known)
        }

        return {
            key: (
                rank[value]
                if math.isfinite(value)
                else 0.5
            )
            for key, value in priorities.items()
        }

    def _shortlist_context(
        self, context: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        emergency = context["emergency"]
        emergency_lat = emergency["latitude"]
        emergency_lon = emergency["longitude"]

        all_ambulances = list(context.get("ambulances") or [])
        all_hospitals = list(context.get("hospitals") or [])

        ambulances_with_distance = []

        for ambulance in all_ambulances:
            distance = self._direct_distance_km(
                ambulance["latitude"],
                ambulance["longitude"],
                emergency_lat,
                emergency_lon,
            )

            clean = dict(ambulance)
            clean["response_cost"] = distance

            ambulances_with_distance.append(
                (
                    distance,
                    self._identifier(clean, "ambulance_id"),
                    clean,
                )
            )

        ambulances_with_distance.sort(
            key=lambda item: (item[0], item[1])
        )

        selected_ambulances = [
            item[2]
            for item in ambulances_with_distance[
                : self.max_ambulances
            ]
        ]

        hospitals_with_distance = []

        for hospital in all_hospitals:
            distance = self._direct_distance_km(
                hospital["latitude"],
                hospital["longitude"],
                emergency_lat,
                emergency_lon,
            )

            clean = dict(hospital)
            clean["mode_b_haversine_distance_km"] = distance

            hospitals_with_distance.append(
                (
                    distance,
                    self._identifier(clean, "id"),
                    clean,
                )
            )

        nearest = sorted(
            hospitals_with_distance,
            key=lambda item: (item[0], item[1]),
        )

        priority_count = min(
            self.priority_hospital_slots,
            self.max_hospitals,
            len(hospitals_with_distance),
        )

        priority_sorted = sorted(
            hospitals_with_distance,
            key=lambda item: (
                (
                    self._hospital_priority(item[2])
                    if self._hospital_priority(item[2]) is not None
                    else math.inf
                ),
                item[0],
                item[1],
            ),
        )

        selected_hospital_rows = []
        seen_hospital_ids: set[str] = set()

        for item in priority_sorted[:priority_count] + nearest:
            identifier = item[1]

            if not identifier or identifier in seen_hospital_ids:
                continue

            selected_hospital_rows.append(item[2])
            seen_hospital_ids.add(identifier)

            if len(selected_hospital_rows) >= self.max_hospitals:
                break

        short_context = dict(context)
        short_context["ambulances"] = selected_ambulances
        short_context["hospitals"] = selected_hospital_rows
        short_context["shortlisted_ambulance_count"] = len(
            selected_ambulances
        )
        short_context["shortlisted_hospital_count"] = len(
            selected_hospital_rows
        )

        counts = {
            "eligible_ambulances": len(all_ambulances),
            "eligible_hospitals": len(all_hospitals),
            "shortlisted_ambulances": len(selected_ambulances),
            "shortlisted_hospitals": len(selected_hospital_rows),
        }

        return short_context, counts

    def _currently_assigned_ambulance_ids(self) -> set[str]:
        fleet = getattr(self.integration, "live_fleet", {}) or {}
        assigned = set()

        for identifier, ambulance in fleet.items():
            if not isinstance(ambulance, Mapping):
                continue

            status = str(ambulance.get("status", "")).strip()
            assigned_emergency = str(
                ambulance.get("assigned_emergency_id", "")
            ).strip()

            if status != "Available at Base" or assigned_emergency:
                assigned.add(str(identifier).strip())

        return assigned

    def _public_candidate(
        self, candidate: Mapping[str, Any]
    ) -> dict[str, Any]:
        response = candidate.get("response_route") or {}
        transport = candidate.get("transport_route") or {}

        return {
            "rank": candidate.get("mode_b_rank"),
            "ambulance_id": candidate.get("ambulance_id"),
            "ambulance_type": candidate.get("ambulance_type"),
            "hospital_id": candidate.get("hospital_id"),
            "hospital_name": candidate.get("hospital_name"),
            "hospital_class": candidate.get("hospital_class"),
            "response_time_minutes": candidate.get(
                "response_time_minutes"
            ),
            "transport_time_minutes": candidate.get(
                "transport_time_minutes"
            ),
            "response_route_distance_km": candidate.get(
                "response_route_distance_km"
            ),
            "transport_route_distance_km": candidate.get(
                "transport_route_distance_km"
            ),
            "estimated_total_travel_minutes": (
                float(candidate.get("response_time_minutes", 0.0))
                + float(candidate.get("transport_time_minutes", 0.0))
            ),
            "facility_suitability_penalty": candidate.get(
                "facility_suitability_penalty"
            ),
            "route_condition_penalty": candidate.get(
                "route_condition_penalty"
            ),
            "mode_b_total_cost": candidate.get("mode_b_total_cost"),
            "selection_algorithm": candidate.get(
                "mode_b_selection_algorithm",
                "Branch and Bound",
            ),
            "response_route": {
                "start_vertex": response.get("start_vertex"),
                "end_vertex": response.get("end_vertex"),
                "distance_km": response.get("distance_km"),
                "estimated_time_minutes": response.get(
                    "estimated_time_minutes"
                ),
                "segment_count": response.get("segment_count"),
            },
            "transport_route": {
                "start_vertex": transport.get("start_vertex"),
                "end_vertex": transport.get("end_vertex"),
                "distance_km": transport.get("distance_km"),
                "estimated_time_minutes": transport.get(
                    "estimated_time_minutes"
                ),
                "segment_count": transport.get("segment_count"),
            },
            "eta_type": "modelled estimate; not live traffic",
        }

    def _select_with_branch_and_bound(
        self,
        scored: list[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], float, float]:
        """Select the best scored feasible pair using Branch and Bound.

        Returns:
            selected candidate,
            search statistics,
            input-preparation time in milliseconds,
            selector execution time in milliseconds.
        """
        if not scored:
            raise ValueError(
                "Branch and Bound requires at least one feasible candidate."
            )

        preparation_started = time.perf_counter()

        ambulance_inputs: dict[str, dict[str, Any]] = {}
        hospital_inputs: dict[str, dict[str, Any]] = {}
        pair_condition_penalties: dict[tuple[str, str], float] = {}
        feasible_pairs: set[tuple[str, str]] = set()

        for candidate in scored:
            ambulance_id = str(
                candidate.get("ambulance_id", "")
            ).strip()
            hospital_id = str(
                candidate.get("hospital_id", "")
            ).strip()

            if not ambulance_id or not hospital_id:
                raise ValueError(
                    "Every feasible candidate requires ambulance_id "
                    "and hospital_id."
                )

            response_time = float(
                candidate["response_time_minutes"]
            )
            transport_time = float(
                candidate["transport_time_minutes"]
            )
            facility_penalty = float(
                candidate["facility_suitability_penalty"]
            )
            route_penalty = float(
                candidate["route_condition_penalty"]
            )

            # An ambulance's response estimate should be consistent
            # across candidates using that ambulance.
            if ambulance_id not in ambulance_inputs:
                ambulance_inputs[ambulance_id] = {
                    "ambulance_id": ambulance_id,
                    "response_time_minutes": response_time,
                }
            elif not math.isclose(
                ambulance_inputs[ambulance_id][
                    "response_time_minutes"
                ],
                response_time,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    "Inconsistent response times for ambulance "
                    f"{ambulance_id!r}."
                )

            # A hospital's transport estimate and facility penalty
            # should be consistent across candidates using that hospital.
            if hospital_id not in hospital_inputs:
                hospital_inputs[hospital_id] = {
                    "hospital_id": hospital_id,
                    "transport_time_minutes": transport_time,
                    "facility_suitability_penalty": facility_penalty,
                }
            else:
                existing = hospital_inputs[hospital_id]

                if not (
                    math.isclose(
                        existing["transport_time_minutes"],
                        transport_time,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                    and math.isclose(
                        existing["facility_suitability_penalty"],
                        facility_penalty,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                ):
                    raise ValueError(
                        "Inconsistent transport time or facility "
                        f"penalty for hospital {hospital_id!r}."
                    )

            pair = (ambulance_id, hospital_id)

            # Only pairs that survived the existing constraints and
            # route checks are eligible for Branch-and-Bound selection.
            feasible_pairs.add(pair)
            pair_condition_penalties[pair] = route_penalty

        preparation_time_ms = (
            time.perf_counter() - preparation_started
        ) * 1000.0

        selector_started = time.perf_counter()

        bb_result = select_best_pair(
            ambulances=list(ambulance_inputs.values()),
            hospitals=list(hospital_inputs.values()),
            pair_condition_penalties=pair_condition_penalties,
            feasible_pairs=feasible_pairs,
            weights=self.cost_model.weights,
            reference_minutes=self.cost_model.reference_minutes,
        )

        selector_time_ms = (
            time.perf_counter() - selector_started
        ) * 1000.0

        selected_pair = (
            str(bb_result["ambulance_id"]).strip(),
            str(bb_result["hospital_id"]).strip(),
        )

        # Find the original enriched candidate so route geometry,
        # distances, ETA fields and other data remain intact.
        selected_candidate = next(
            (
                dict(candidate)
                for candidate in scored
                if (
                    str(candidate.get("ambulance_id", "")).strip(),
                    str(candidate.get("hospital_id", "")).strip(),
                ) == selected_pair
            ),
            None,
        )

        if selected_candidate is None:
            raise RuntimeError(
                "Branch and Bound selected a pair outside the "
                "scored feasible candidate set."
            )

        # Verify that both implementations use the same objective.
        if not math.isclose(
            float(selected_candidate["mode_b_total_cost"]),
            float(bb_result["mode_b_total_cost"]),
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise RuntimeError(
                "Branch-and-Bound cost does not match the existing "
                "Mode B cost model. Selection has been stopped."
            )

        stats = dict(bb_result["branch_and_bound_stats"])

        selected_candidate["mode_b_selection_algorithm"] = (
            "Branch and Bound"
        )
        selected_candidate["branch_and_bound_stats"] = stats

        return (
            selected_candidate,
            stats,
            preparation_time_ms,
            selector_time_ms,
        )

    def recommend(self, emergency_id: str) -> dict[str, Any]:
        recommendation_started = time.perf_counter()
        emergency_id = str(emergency_id).strip()

        emergency = self.dispatcher.live_emergency_records.get(
            emergency_id
        )

        if not isinstance(emergency, Mapping):
            return {
                "status": "Emergency Not Found",
                "emergency_id": emergency_id,
            }

        if (
            emergency.get("status") == "Dispatched"
            or emergency.get("ambulance_id")
        ):
            return {
                "status": "Emergency Already Dispatched",
                "emergency_id": emergency_id,
            }

        context = self.data_adapter.get_selection_context(
            dict(emergency)
        )

        short_context, counts = self._shortlist_context(context)

        if not short_context.get("ambulances"):
            return {
                "status": "No Feasible Candidate",
                "message": (
                    "No currently available ambulance satisfies "
                    "the existing suitability policy."
                ),
                "emergency_id": emergency_id,
                "counts": counts,
                "candidate_pair_count": 0,
            }

        if not short_context.get("hospitals"):
            return {
                "status": "No Feasible Candidate",
                "message": (
                    "No eligible hospital is available under "
                    "the existing hospital policy."
                ),
                "emergency_id": emergency_id,
                "counts": counts,
                "candidate_pair_count": 0,
            }

        bounded_generator = ModeBCandidateGenerator(
            _PrecomputedSelectionContext(short_context)
        )

        generated = bounded_generator.generate_candidates(
            dict(short_context["emergency"])
        )
        generated_candidates = generated.get("candidates", [])
        assigned_ids = self._currently_assigned_ambulance_ids()

        constraint_feasible = []
        constraint_rejected = 0

        for candidate in generated_candidates:
            feasible, _reasons = self.constraints.check_candidate(
                candidate,
                assigned_ambulance_ids=assigned_ids,
            )

            if feasible:
                constraint_feasible.append(candidate)
            else:
                constraint_rejected += 1

        if not constraint_feasible:
            return {
                "status": "No Feasible Candidate",
                "message": (
                    "All shortlisted ambulance-hospital pairs failed "
                    "Mode B feasibility constraints."
                ),
                "emergency_id": emergency_id,
                "counts": {
                    **counts,
                    "generated_pairs": len(generated_candidates),
                    "constraint_rejected_pairs": constraint_rejected,
                },
                "candidate_pair_count": len(generated_candidates),
            }

        emergency_lat = float(
            short_context["emergency"]["latitude"]
        )
        emergency_lon = float(
            short_context["emergency"]["longitude"]
        )

        ambulance_records = {
            self._identifier(item, "ambulance_id"): item
            for item in short_context["ambulances"]
        }
        hospital_records = {
            self._identifier(item, "id"): item
            for item in short_context["hospitals"]
        }

        # Compute each ambulance's response route once.
        response_routes: dict[str, dict[str, Any]] = {}

        for ambulance_id, ambulance in ambulance_records.items():
            if any(
                str(candidate.get("ambulance_id")) == ambulance_id
                for candidate in constraint_feasible
            ):
                response_routes[ambulance_id] = (
                    self.route_estimator.estimate_route(
                        ambulance["latitude"],
                        ambulance["longitude"],
                        emergency_lat,
                        emergency_lon,
                    )
                )

        # Compute each hospital's transport route once. The compact estimator
        # exposes estimate_transport_route() for Time-aware A*. Other estimator
        # implementations retain their existing estimate_route() behavior.
        transport_routes: dict[str, dict[str, Any]] = {}
        transport_route_estimator = getattr(
            self.route_estimator, "estimate_transport_route", None
        )
        if not callable(transport_route_estimator):
            transport_route_estimator = self.route_estimator.estimate_route

        for hospital_id, hospital in hospital_records.items():
            if any(
                str(candidate.get("hospital_id")) == hospital_id
                for candidate in constraint_feasible
            ):
                transport_routes[hospital_id] = transport_route_estimator(
                    emergency_lat,
                    emergency_lon,
                    hospital["latitude"],
                    hospital["longitude"],
                )

        facility_penalties = self._priority_penalties(
            list(hospital_records.values())
        )

        routed_candidates = []
        route_rejected = 0

        for candidate in constraint_feasible:
            ambulance_id = str(candidate.get("ambulance_id", ""))
            hospital_id = str(candidate.get("hospital_id", ""))

            response = response_routes.get(ambulance_id, {})
            transport = transport_routes.get(hospital_id, {})

            if (
                not response.get("reachable")
                or not transport.get("reachable")
            ):
                route_rejected += 1
                continue

            result = dict(candidate)
            result["response_route"] = response
            result["transport_route"] = transport
            result["route_feasible"] = True

            result["response_time_minutes"] = float(
                response["estimated_time_minutes"]
            )
            result["transport_time_minutes"] = float(
                transport["estimated_time_minutes"]
            )
            result["response_route_distance_km"] = float(
                response["distance_km"]
            )
            result["transport_route_distance_km"] = float(
                transport["distance_km"]
            )

            result["hospital_distance_km"] = (
                self._direct_distance_km(
                    emergency_lat,
                    emergency_lon,
                    result["hospital_latitude"],
                    result["hospital_longitude"],
                )
            )

            result["facility_suitability_penalty"] = (
                facility_penalties.get(hospital_id, 0.5)
            )

            response_distance = float(
                response.get("distance_km", 0.0)
            )
            transport_distance = float(
                transport.get("distance_km", 0.0)
            )
            total_distance = response_distance + transport_distance

            if total_distance > 0:
                route_penalty = (
                    float(
                        response.get("route_condition_penalty", 0.0)
                    ) * response_distance
                    + float(
                        transport.get("route_condition_penalty", 0.0)
                    ) * transport_distance
                ) / total_distance
            else:
                route_penalty = 0.0

            result["route_condition_penalty"] = min(
                1.0, max(0.0, route_penalty)
            )
            if callable(getattr(self.route_estimator, "estimate_transport_route", None)):
                result["route_estimation_method"] = (
                    "Dynamic A* for Ambulance-to-Patient; Time-aware A* "
                    "for Patient-to-Hospital (modelled ETA; not live traffic)"
                )
                result["response_route_objective"] = response.get(
                    "route_objective", "condition_weighted_distance"
                )
                result["transport_route_objective"] = transport.get(
                    "route_objective", "modelled_travel_time"
                )
            else:
                result["route_estimation_method"] = (
                    "Dynamic A* routes with road-segment modelled speeds"
                )

            routed_candidates.append(result)

        if not routed_candidates:
            return {
                "status": "No Feasible Candidate",
                "message": (
                    "Every shortlisted pair had at least one "
                    "unreachable route."
                ),
                "emergency_id": emergency_id,
                "counts": {
                    **counts,
                    "generated_pairs": len(generated_candidates),
                    "constraint_rejected_pairs": constraint_rejected,
                    "route_rejected_pairs": route_rejected,
                },
                "candidate_pair_count": len(generated_candidates),
            }

        # Score the feasible candidates using the existing cost model.
        scored = [
            self.cost_model.score_candidate(candidate)
            for candidate in routed_candidates
        ]

        # Branch and Bound now selects the actual recommended pair.
        (
            selected_candidate,
            bb_stats,
            bb_preparation_time_ms,
            bb_execution_time_ms,
        ) = self._select_with_branch_and_bound(scored)

        # Retain sorted alternatives for existing dashboard compatibility.
        # Sorting is for displaying alternatives, not for deciding the winner.
        ranked = self.ranker.rank_candidates(scored)

        # Attach the displayed rank of the Branch-and-Bound winner.
        selected_pair = (
            str(selected_candidate.get("ambulance_id", "")).strip(),
            str(selected_candidate.get("hospital_id", "")).strip(),
        )

        for candidate in ranked:
            candidate_pair = (
                str(candidate.get("ambulance_id", "")).strip(),
                str(candidate.get("hospital_id", "")).strip(),
            )

            if candidate_pair == selected_pair:
                selected_candidate["mode_b_rank"] = candidate.get(
                    "mode_b_rank"
                )
                break

        recommendation_time_ms = (
            time.perf_counter() - recommendation_started
        ) * 1000.0

        selected_candidate["mode_b_selection_algorithm"] = (
            "Branch and Bound"
        )
        selected_candidate["branch_and_bound_stats"] = bb_stats

        return {
            "status": "Recommended",
            "mode": "B",
            "emergency_id": emergency_id,
            "selected_candidate": selected_candidate,
            "ranked_candidates": ranked,
            "top_candidates": [
                self._public_candidate(candidate)
                for candidate in ranked[:self.return_top_candidates]
            ],
            "selection_algorithm": "Branch and Bound",
            "branch_and_bound_preparation_time_ms": round(
                bb_preparation_time_ms, 3
            ),
            "branch_and_bound_execution_time_ms": round(
                bb_execution_time_ms, 3
            ),
            "recommendation_execution_time_ms": round(
                recommendation_time_ms, 3
            ),
            "branch_and_bound_stats": bb_stats,
            "counts": {
                **counts,
                "generated_pairs": len(generated_candidates),
                "constraint_rejected_pairs": constraint_rejected,
                "route_rejected_pairs": route_rejected,
                "route_feasible_pairs": len(routed_candidates),
            },
            "eta_type": (
                "modelled road-aware estimate; not live traffic"
            ),
        }

    def _priority_queue_allows(
        self, emergency_id: str
    ) -> tuple[bool, Optional[str]]:
        """Respect the existing emergency priority queue."""

        manager = getattr(
            self.coordinator, "emergency_manager", None
        )
        waiting = getattr(manager, "waiting_emergencies", None)

        if not isinstance(waiting, list) or not waiting:
            return True, None

        first = waiting[0]

        if not isinstance(first, Mapping):
            return True, None

        first_id = str(first.get("emergency_id", "")).strip()

        if first_id and first_id != str(emergency_id).strip():
            return False, first_id

        return True, None

    def dispatch_emergency(
        self, emergency_id: str
    ) -> dict[str, Any]:
        emergency_id = str(emergency_id).strip()

        # Report unknown IDs before checking priority.
        if not isinstance(
            self.dispatcher.live_emergency_records.get(emergency_id),
            Mapping,
        ):
            return {
                "status": "Emergency Not Found",
                "emergency_id": emergency_id,
            }

        priority_ok, blocking_id = self._priority_queue_allows(
            emergency_id
        )

        if not priority_ok:
            return {
                "status": "Higher Priority Emergency Pending",
                "emergency_id": emergency_id,
                "blocking_emergency_id": blocking_id,
                "message": (
                    "Mode B did not dispatch because another emergency "
                    "is at the head of the existing priority queue."
                ),
                "dispatch_mode": "Mode B",
                "mode_b_selection_committed": False,
            }

        # Recommendation includes the Branch-and-Bound selection.
        recommendation = self.recommend(emergency_id)

        if recommendation.get("status") != "Recommended":
            return recommendation

        best = recommendation["selected_candidate"]

        # Commit the exact selected pair through the existing workflow.
        result = self.live_service.dispatch_emergency(
            str(emergency_id),
            condition_map=self.condition_map,
            mode_b_candidate=best,
        )

        if result is None:
            result = {
                "status": "Dispatch Returned No Result",
                "emergency_id": str(emergency_id),
            }

        actual_ambulance = str(
            result.get("ambulance_id", "")
        ).strip()
        actual_hospital = str(
            result.get("hospital_id", "")
        ).strip()

        expected_ambulance = str(
            best.get("ambulance_id", "")
        ).strip()
        expected_hospital = str(
            best.get("hospital_id", "")
        ).strip()

        committed = (
            result.get("status") == "Dispatched"
            and actual_ambulance == expected_ambulance
            and actual_hospital == expected_hospital
        )

        if not isinstance(result, dict):
            result = dict(result)

        result.update({
            "dispatch_mode": "Mode B",
            "mode_b_selection_committed": committed,
            "mode_b_recommendation": self._public_candidate(best),
            "mode_b_candidate_counts": recommendation.get(
                "counts", {}
            ),
            "mode_b_total_cost": best.get("mode_b_total_cost"),
            "mode_b_rank": best.get("mode_b_rank"),
            "mode_b_selection_algorithm": recommendation.get(
                "selection_algorithm",
                "Branch and Bound",
            ),
            "mode_b_branch_and_bound_preparation_time_ms": (
                recommendation.get(
                    "branch_and_bound_preparation_time_ms"
                )
            ),
            "mode_b_branch_and_bound_execution_time_ms": (
                recommendation.get(
                    "branch_and_bound_execution_time_ms"
                )
            ),
            "mode_b_recommendation_execution_time_ms": (
                recommendation.get(
                    "recommendation_execution_time_ms"
                )
            ),
            "mode_b_branch_and_bound_stats": recommendation.get(
                "branch_and_bound_stats", {}
            ),
            "estimated_response_time_minutes": best.get(
                "response_time_minutes"
            ),
            "estimated_transport_time_minutes": best.get(
                "transport_time_minutes"
            ),
            "estimated_response_route_distance_km": best.get(
                "response_route_distance_km"
            ),
            "estimated_transport_route_distance_km": best.get(
                "transport_route_distance_km"
            ),
            "eta_type": (
                "modelled road-aware estimate; not live traffic"
            ),
        })

        if result.get("status") == "Dispatched" and not committed:
            result["mode_b_selection_warning"] = (
                "The legacy dispatcher returned different ambulance/"
                "hospital IDs; Mode B does not report this as a "
                "committed selection."
            )

        # Synchronize the live emergency record with the returned result.
        stored = self.dispatcher.live_emergency_records.get(
            str(emergency_id)
        )

        if isinstance(stored, dict):
            stored.update(result)

        return result
