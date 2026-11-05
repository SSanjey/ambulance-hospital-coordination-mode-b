
"""Generate feasible ambulance-hospital pairs for Mode B.

This module enumerates candidates only. It does not calculate the final
multi-criteria score, assign an ambulance, or choose a hospital.
"""

from collections.abc import Mapping


class ModeBCandidateGenerator:
    """Enumerate ambulance-hospital combinations using lists."""

    def __init__(self, data_adapter):
        if data_adapter is None:
            raise ValueError("A Mode B data adapter is required.")

        self.data_adapter = data_adapter

    @staticmethod
    def _numeric_distance(value):
        """Convert a valid non-negative distance to float."""
        try:
            distance = float(value)
        except (TypeError, ValueError):
            return None

        if distance < 0 or distance != distance or distance == float("inf"):
            return None

        return distance

    def generate_candidates(self, emergency):
        """Generate the Cartesian product of feasible ambulances and hospitals.

        Returns a dictionary containing the candidate pairs and counts.
        Candidate records preserve the original manager data in nested
        dictionaries while providing convenient IDs and coordinate fields.
        """
        context = self.data_adapter.get_selection_context(emergency)

        clean_emergency = dict(context["emergency"])
        ambulances = context["ambulances"]
        hospitals = context["hospitals"]

        candidates = []

        # Without either resource, no feasible pair can be constructed.
        if not ambulances or not hospitals:
            return {
                "emergency": clean_emergency,
                "candidates": [],
                "ambulance_candidate_count": len(ambulances),
                "hospital_candidate_count": len(hospitals),
                "candidate_pair_count": 0,
            }

        # Enumerate every feasible ambulance-hospital combination.
        for ambulance in ambulances:
            if not isinstance(ambulance, Mapping):
                continue

            ambulance_id = str(
                ambulance.get("ambulance_id", "")
            ).strip()

            if not ambulance_id:
                continue

            for hospital in hospitals:
                if not isinstance(hospital, Mapping):
                    continue

                hospital_id = str(
                    hospital.get("id", "")
                ).strip()

                if not hospital_id:
                    continue

                raw_response_distance = ambulance.get("response_cost")
                response_distance_km = self._numeric_distance(
                    raw_response_distance
                )

                candidates.append({
                    "emergency_id": clean_emergency.get("emergency_id"),
                    "severity": clean_emergency["severity"],
                    "ambulance_id": ambulance_id,
                    "hospital_id": hospital_id,
                    "ambulance_type": ambulance.get("ambulance_type"),
                    "ambulance_latitude": float(ambulance["latitude"]),
                    "ambulance_longitude": float(ambulance["longitude"]),
                    "hospital_name": hospital.get(
                        "facility_name",
                        hospital.get("name", "Unknown facility"),
                    ),
                    "hospital_class": hospital.get("facility_class"),
                    "hospital_priority": hospital.get(
                        "policy_priority",
                        hospital.get("priority"),
                    ),
                    "hospital_latitude": float(hospital["latitude"]),
                    "hospital_longitude": float(hospital["longitude"]),
                    # The existing response_cost is a Haversine distance
                    # in kilometres, not a travel-time estimate.
                    "response_distance_km": response_distance_km,
                    "emergency_latitude": clean_emergency["latitude"],
                    "emergency_longitude": clean_emergency["longitude"],
                    "ambulance": dict(ambulance),
                    "hospital": dict(hospital),
                })

        return {
            "emergency": clean_emergency,
            "candidates": candidates,
            "ambulance_candidate_count": len(ambulances),
            "hospital_candidate_count": len(hospitals),
            "candidate_pair_count": len(candidates),
        }
