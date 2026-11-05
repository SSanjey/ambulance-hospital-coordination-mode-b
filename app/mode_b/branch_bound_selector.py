"""Branch-and-Bound selector for Mode B ambulance-hospital pairs.

This module selects among already feasible ambulance/hospital records whose
route ETAs have been estimated. Route searches should be shared by ambulance
and hospital, not repeated for every pair. The lower bound omits the
non-negative route-condition penalty, so it cannot overestimate a pair's
best possible score.

Expected ambulance record fields:
    ambulance_id, response_time_minutes
Expected hospital record fields:
    hospital_id, transport_time_minutes, facility_suitability_penalty
Optional pair_condition_penalties:
    mapping {(ambulance_id, hospital_id): penalty}, penalty in [0, 1]
Optional feasible_pairs:
    set of (ambulance_id, hospital_id) pairs already validated by hard
    constraints. If omitted, every ambulance/hospital pair is considered.

Weights/reference scales match the project's existing ModeBCostModel defaults.
"""
from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_WEIGHTS = {
    "response_time": 0.40,
    "transport_time": 0.30,
    "facility_suitability": 0.20,
    "route_condition": 0.10,
}
DEFAULT_REFERENCE_MINUTES = {
    "response_time_minutes": 60.0,
    "transport_time_minutes": 180.0,
}


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be numeric") from None
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _penalty(value: Any, field: str) -> float:
    number = _finite_number(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


def _cost_components(ambulance: Mapping, hospital: Mapping, road_penalty: float,
                     weights: Mapping, references: Mapping) -> dict:
    response = _finite_number(ambulance["response_time_minutes"], "response_time_minutes")
    transport = _finite_number(hospital["transport_time_minutes"], "transport_time_minutes")
    facility = _penalty(hospital["facility_suitability_penalty"], "facility_suitability_penalty")
    if response < 0 or transport < 0:
        raise ValueError("Travel times cannot be negative")
    road = _penalty(road_penalty, "route_condition_penalty")
    components = {
        "response_time": response / references["response_time_minutes"],
        "transport_time": transport / references["transport_time_minutes"],
        "facility_suitability": facility,
        "route_condition": road,
    }
    total = sum(weights[name] * components[name] for name in weights)
    return {
        "response_time_minutes": response,
        "transport_time_minutes": transport,
        "facility_suitability_penalty": facility,
        "route_condition_penalty": road,
        "mode_b_cost_components": components,
        "mode_b_cost_weights": dict(weights),
        "mode_b_total_cost": total,
    }


def select_best_pair(
    ambulances: Sequence[Mapping],
    hospitals: Sequence[Mapping],
    *,
    pair_condition_penalties: Mapping | None = None,
    feasible_pairs: set[tuple[str, str]] | None = None,
    weights: Mapping | None = None,
    reference_minutes: Mapping | None = None,
) -> dict:
    """Return the minimum-cost feasible pair using Branch and Bound.

    The search branches by ambulance. The bound for a pair includes response,
    transport, and facility cost, but omits the route-condition contribution,
    which is non-negative. Hospitals and ambulance branches are ordered by
    their lower bounds. Pruning is strict (bound > incumbent) to preserve ties.
    """
    if not ambulances or not hospitals:
        raise ValueError("At least one ambulance and one hospital are required")

    w = dict(DEFAULT_WEIGHTS)
    if weights:
        unknown = set(weights) - set(w)
        if unknown:
            raise ValueError(f"Unknown weight(s): {sorted(unknown)}")
        w.update({key: _finite_number(value, f"weight {key}") for key, value in weights.items()})
    if any(value < 0 for value in w.values()) or sum(w.values()) <= 0:
        raise ValueError("Weights must be non-negative and at least one must be positive")
    weight_total = sum(w.values())
    w = {key: value / weight_total for key, value in w.items()}

    refs = dict(DEFAULT_REFERENCE_MINUTES)
    if reference_minutes:
        unknown = set(reference_minutes) - set(refs)
        if unknown:
            raise ValueError(f"Unknown reference field(s): {sorted(unknown)}")
        refs.update({key: _finite_number(value, key) for key, value in reference_minutes.items()})
    if any(value <= 0 for value in refs.values()):
        raise ValueError("Reference times must be positive")

    penalties = pair_condition_penalties or {}
    prepared_ambulances = []
    for raw in ambulances:
        if not isinstance(raw, Mapping):
            raise ValueError("Each ambulance must be a mapping")
        item = dict(raw)
        item["ambulance_id"] = str(item.get("ambulance_id", "")).strip()
        if not item["ambulance_id"]:
            raise ValueError("Every ambulance requires ambulance_id")
        response = _finite_number(item.get("response_time_minutes"), "response_time_minutes")
        if response < 0:
            raise ValueError("response_time_minutes cannot be negative")
        item["response_time_minutes"] = response
        prepared_ambulances.append(item)

    prepared_hospitals = []
    for raw in hospitals:
        if not isinstance(raw, Mapping):
            raise ValueError("Each hospital must be a mapping")
        item = dict(raw)
        item["hospital_id"] = str(item.get("hospital_id", "")).strip()
        if not item["hospital_id"]:
            raise ValueError("Every hospital requires hospital_id")
        transport = _finite_number(item.get("transport_time_minutes"), "transport_time_minutes")
        if transport < 0:
            raise ValueError("transport_time_minutes cannot be negative")
        item["transport_time_minutes"] = transport
        item["facility_suitability_penalty"] = _penalty(
            item.get("facility_suitability_penalty"), "facility_suitability_penalty"
        )
        prepared_hospitals.append(item)

    feasible = None
    if feasible_pairs is not None:
        feasible = {(str(a).strip(), str(h).strip()) for a, h in feasible_pairs}

    # Since the route-condition term is in [0, 1] and its weight is
    # non-negative, omitting it gives a valid lower bound for a pair.
    hospital_records = []
    for hospital in prepared_hospitals:
        hospital_base = (
            w["transport_time"] * hospital["transport_time_minutes"] / refs["transport_time_minutes"]
            + w["facility_suitability"] * hospital["facility_suitability_penalty"]
        )
        hospital_records.append((hospital_base, hospital))
    hospital_records.sort(key=lambda entry: (entry[0], entry[1]["hospital_id"]))

    ambulance_branches = []
    for ambulance in prepared_ambulances:
        response_component = (
            w["response_time"] * ambulance["response_time_minutes"] / refs["response_time_minutes"]
        )
        valid_hospital_bounds = [
            response_component + base
            for base, hospital in hospital_records
            if feasible is None or (ambulance["ambulance_id"], hospital["hospital_id"]) in feasible
        ]
        if valid_hospital_bounds:
            ambulance_branches.append((min(valid_hospital_bounds), response_component, ambulance))
    ambulance_branches.sort(key=lambda entry: (entry[0], entry[2]["ambulance_id"]))

    best = None
    evaluated_pairs = 0
    pruned_pairs = 0
    infeasible_pairs = 0
    total_pairs = len(prepared_ambulances) * len(prepared_hospitals)

    for ambulance_bound, response_component, ambulance in ambulance_branches:
        if best is not None and ambulance_bound > best["mode_b_total_cost"]:
            pruned_pairs += sum(
                1 for _base, hospital in hospital_records
                if feasible is None or (ambulance["ambulance_id"], hospital["hospital_id"]) in feasible
            )
            continue

        for hospital_base, hospital in hospital_records:
            pair_ids = (ambulance["ambulance_id"], hospital["hospital_id"])
            if feasible is not None and pair_ids not in feasible:
                infeasible_pairs += 1
                continue

            lower_bound = response_component + hospital_base
            if best is not None and lower_bound > best["mode_b_total_cost"]:
                # Sorted hospital lower bounds mean later eligible hospitals
                # cannot beat the incumbent for this ambulance either.
                pruned_pairs += sum(
                    1 for _later_base, later_hospital in hospital_records
                    if _later_base >= hospital_base
                    and (feasible is None or (ambulance["ambulance_id"], later_hospital["hospital_id"]) in feasible)
                )
                break

            road_penalty = _penalty(
                penalties.get(pair_ids, 0.0), "route_condition_penalty"
            )
            candidate = {
                "ambulance_id": ambulance["ambulance_id"],
                "hospital_id": hospital["hospital_id"],
                **_cost_components(ambulance, hospital, road_penalty, w, refs),
            }
            evaluated_pairs += 1
            tie_key = (
                candidate["mode_b_total_cost"],
                candidate["response_time_minutes"],
                candidate["transport_time_minutes"],
                candidate["ambulance_id"],
                candidate["hospital_id"],
            )
            if best is None or tie_key < best["_tie_key"]:
                candidate["_tie_key"] = tie_key
                best = candidate

    if best is None:
        raise ValueError("No feasible ambulance-hospital pair was found")

    best.pop("_tie_key", None)
    best["branch_and_bound_stats"] = {
        "total_pairs": total_pairs,
        "evaluated_pairs": evaluated_pairs,
        "pruned_pairs": pruned_pairs,
        "infeasible_pairs": infeasible_pairs,
        "bounds_used": "response + transport + facility; non-negative route-condition term omitted",
    }
    return best


def _brute_force(ambulances, hospitals, penalties=None):
    """Test-only exhaustive reference to validate the selector result."""
    penalties = penalties or {}
    records = []
    w = DEFAULT_WEIGHTS
    refs = DEFAULT_REFERENCE_MINUTES
    for ambulance in ambulances:
        for hospital in hospitals:
            road = penalties.get((ambulance["ambulance_id"], hospital["hospital_id"]), 0.0)
            row = {
                "ambulance_id": ambulance["ambulance_id"],
                "hospital_id": hospital["hospital_id"],
                **_cost_components(ambulance, hospital, road, w, refs),
            }
            row["_tie_key"] = (
                row["mode_b_total_cost"], row["response_time_minutes"],
                row["transport_time_minutes"], row["ambulance_id"], row["hospital_id"]
            )
            records.append(row)
    return min(records, key=lambda item: item["_tie_key"])


def self_test() -> None:
    ambulances = [
        {"ambulance_id": "A1", "response_time_minutes": 5.0},
        {"ambulance_id": "A2", "response_time_minutes": 30.0},
        {"ambulance_id": "A3", "response_time_minutes": 50.0},
    ]
    hospitals = [
        {"hospital_id": "H1", "transport_time_minutes": 140.0, "facility_suitability_penalty": 0.1},
        {"hospital_id": "H2", "transport_time_minutes": 20.0, "facility_suitability_penalty": 0.0},
    ]
    penalties = {
        ("A1", "H1"): 0.0,
        ("A1", "H2"): 0.2,
        ("A2", "H1"): 0.1,
        ("A2", "H2"): 0.0,
        ("A3", "H1"): 0.0,
        ("A3", "H2"): 0.0,
    }
    got = select_best_pair(ambulances, hospitals, pair_condition_penalties=penalties)
    expected = _brute_force(ambulances, hospitals, penalties)
    assert got["ambulance_id"] == expected["ambulance_id"]
    assert got["hospital_id"] == expected["hospital_id"]
    assert math.isclose(got["mode_b_total_cost"], expected["mode_b_total_cost"], rel_tol=1e-12)
    assert got["branch_and_bound_stats"]["pruned_pairs"] > 0, got["branch_and_bound_stats"]

    constrained = select_best_pair(
        ambulances,
        hospitals,
        pair_condition_penalties=penalties,
        feasible_pairs={("A2", "H1"), ("A3", "H2")},
    )
    assert (constrained["ambulance_id"], constrained["hospital_id"]) == ("A3", "H2")
    print("Branch-and-Bound self-test passed: optimum matches exhaustive search.")
    print("Verified: safe lower-bound pruning, deterministic tie-breaking and feasible-pair constraints.")
    print("No Tamil Nadu graph, Mode A files or live dispatch records were loaded.")
    print("Example search stats:", json.dumps(got["branch_and_bound_stats"], sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="Run synthetic unit tests only")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("This module is a selector library; use --self-test or import select_best_pair().")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
