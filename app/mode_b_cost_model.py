"""Multi-criteria cost model for Mode B ambulance dispatch."""

import math
from collections.abc import Mapping


class ModeBCostModel:
    """Calculate a weighted cost for an enriched dispatch candidate.

    Required candidate fields:
        response_time_minutes
        transport_time_minutes
        facility_suitability_penalty
        route_condition_penalty

    Penalties use the range 0.0 to 1.0, where lower is better.
    Time values must come from route/ETA estimation, not straight-line
    geographic distance.
    """

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

    def __init__(self, weights=None, reference_minutes=None):
        self.weights = self._prepare_weights(weights)
        self.reference_minutes = self._prepare_reference_minutes(
            reference_minutes
        )

    @staticmethod
    def _number(value, field_name):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field_name} must be a valid number."
            ) from None

        if not math.isfinite(number):
            raise ValueError(
                f"{field_name} must be finite."
            )

        return number

    def _prepare_weights(self, weights):
        supplied = dict(weights or {})
        unknown = set(supplied) - set(self.DEFAULT_WEIGHTS)

        if unknown:
            raise ValueError(
                f"Unknown cost weight(s): {sorted(unknown)}"
            )

        merged = dict(self.DEFAULT_WEIGHTS)
        merged.update(supplied)

        for name, value in merged.items():
            number = self._number(value, f"Weight {name}")

            if number < 0:
                raise ValueError("Cost weights cannot be negative.")

            merged[name] = number

        total = sum(merged.values())

        if total <= 0:
            raise ValueError(
                "At least one cost weight must be positive."
            )

        # Normalize weights so that their sum is exactly 1,
        # apart from normal floating-point rounding.
        return {
            name: value / total
            for name, value in merged.items()
        }

    def _prepare_reference_minutes(self, reference_minutes):
        supplied = dict(reference_minutes or {})
        unknown = set(supplied) - set(self.DEFAULT_REFERENCE_MINUTES)

        if unknown:
            raise ValueError(
                f"Unknown reference field(s): {sorted(unknown)}"
            )

        merged = dict(self.DEFAULT_REFERENCE_MINUTES)
        merged.update(supplied)

        for name, value in merged.items():
            number = self._number(value, name)

            if number <= 0:
                raise ValueError(
                    f"{name} must be greater than zero."
                )

            merged[name] = number

        return merged

    def score_candidate(self, candidate):
        """Return a copied candidate enriched with cost components."""
        if not isinstance(candidate, Mapping):
            raise ValueError("Candidate must be a mapping or dictionary.")

        required_fields = (
            "response_time_minutes",
            "transport_time_minutes",
            "facility_suitability_penalty",
            "route_condition_penalty",
        )

        missing = [
            field
            for field in required_fields
            if field not in candidate
        ]

        if missing:
            raise ValueError(
                "Candidate is missing cost inputs: "
                + ", ".join(missing)
            )

        response_time = self._number(
            candidate["response_time_minutes"],
            "response_time_minutes",
        )
        transport_time = self._number(
            candidate["transport_time_minutes"],
            "transport_time_minutes",
        )
        facility_penalty = self._number(
            candidate["facility_suitability_penalty"],
            "facility_suitability_penalty",
        )
        route_penalty = self._number(
            candidate["route_condition_penalty"],
            "route_condition_penalty",
        )

        if response_time < 0 or transport_time < 0:
            raise ValueError("Travel times cannot be negative.")

        if not 0.0 <= facility_penalty <= 1.0:
            raise ValueError(
                "facility_suitability_penalty must be between 0 and 1."
            )

        if not 0.0 <= route_penalty <= 1.0:
            raise ValueError(
                "route_condition_penalty must be between 0 and 1."
            )

        # Normalize times against configured reference values.
        # These are reference scales, not hard time limits.
        normalized_response = (
            response_time
            / self.reference_minutes["response_time_minutes"]
        )

        normalized_transport = (
            transport_time
            / self.reference_minutes["transport_time_minutes"]
        )

        components = {
            "response_time": normalized_response,
            "transport_time": normalized_transport,
            "facility_suitability": facility_penalty,
            "route_condition": route_penalty,
        }

        total_cost = sum(
            self.weights[name] * components[name]
            for name in self.weights
        )

        result = dict(candidate)
        result["mode_b_cost_components"] = components
        result["mode_b_cost_weights"] = dict(self.weights)
        result["mode_b_total_cost"] = total_cost

        return result

    def score_candidates(self, candidates):
        """Score a sequence of candidates without sorting or selecting."""
        return [
            self.score_candidate(candidate)
            for candidate in candidates
        ]