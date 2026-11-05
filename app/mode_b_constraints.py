
"""Feasibility and hard-constraint checking for Mode B."""

import math
from collections.abc import Mapping


class ModeBConstraints:
    """Reject invalid ambulance-hospital candidate pairs."""

    AVAILABLE_STATUS = "Available at Base"

    AMBULANCE_TYPES_BY_SEVERITY = {
        "Critical": {"ALS", "VVIP"},
        "Urgent": {"ALS", "BLS", "VVIP"},
        "Less Urgent": {"BLS", "ALS", "FRB", "NLS", "VVIP"},
        "Non-Urgent": {"BLS", "FRB", "NLS", "ALS", "VVIP"},
    }

    EXCLUDED_FACILITY_CLASSES = {
        "SUBCENTRE",
        "OTHER",
    }

    REQUIRED_COORDINATES = (
        "ambulance_latitude",
        "ambulance_longitude",
        "hospital_latitude",
        "hospital_longitude",
        "emergency_latitude",
        "emergency_longitude",
    )

    def __init__(self):
        pass

    @staticmethod
    def _valid_coordinate_pair(latitude, longitude):
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return False

        return (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90.0 <= latitude <= 90.0
            and -180.0 <= longitude <= 180.0
        )

    @staticmethod
    def _normalize_facility_class(value):
        return (
            str(value or "")
            .strip()
            .upper()
            .replace("_", "")
            .replace("-", "")
            .replace(" ", "")
        )

    def check_candidate(self, candidate, assigned_ambulance_ids=None):
        """Return (is_feasible, reasons) for one candidate pair."""
        reasons = []

        if not isinstance(candidate, Mapping):
            return False, ["Candidate must be a dictionary-like record."]

        ambulance_id = str(
            candidate.get("ambulance_id", "")
        ).strip()

        hospital_id = str(
            candidate.get("hospital_id", "")
        ).strip()

        if not ambulance_id:
            reasons.append("Missing ambulance ID.")

        if not hospital_id:
            reasons.append("Missing hospital ID.")

        severity = str(candidate.get("severity", "")).strip()

        allowed_types = self.AMBULANCE_TYPES_BY_SEVERITY.get(severity)

        if allowed_types is None:
            reasons.append("Unknown or missing emergency severity.")

        ambulance = candidate.get("ambulance")
        hospital = candidate.get("hospital")

        if not isinstance(ambulance, Mapping):
            reasons.append("Missing ambulance record.")
        else:
            status = str(ambulance.get("status", "")).strip()

            if status != self.AVAILABLE_STATUS:
                reasons.append("Ambulance is not available at base.")

            ambulance_type = str(
                candidate.get(
                    "ambulance_type",
                    ambulance.get("ambulance_type", ""),
                )
            ).strip().upper()

            if allowed_types is not None and ambulance_type not in allowed_types:
                reasons.append(
                    "Ambulance type is not suitable for this severity."
                )

            if (
                assigned_ambulance_ids is not None
                and ambulance_id in {
                    str(item).strip()
                    for item in assigned_ambulance_ids
                }
            ):
                reasons.append(
                    "Ambulance is already assigned to another emergency."
                )

        if not isinstance(hospital, Mapping):
            reasons.append("Missing hospital record.")
        else:
            facility_class = self._normalize_facility_class(
                candidate.get(
                    "hospital_class",
                    hospital.get("facility_class", ""),
                )
            )

            if not facility_class:
                reasons.append(
                    "Facility class is missing; eligibility cannot be verified."
                )
            elif facility_class in self.EXCLUDED_FACILITY_CLASSES:
                reasons.append(
                    "Facility is not an eligible ambulance destination."
                )

        for key in self.REQUIRED_COORDINATES:
            if key not in candidate:
                reasons.append(f"Missing coordinate: {key}.")

        if all(key in candidate for key in self.REQUIRED_COORDINATES):
            if not self._valid_coordinate_pair(
                candidate["ambulance_latitude"],
                candidate["ambulance_longitude"],
            ):
                reasons.append("Ambulance coordinates are invalid.")

            if not self._valid_coordinate_pair(
                candidate["hospital_latitude"],
                candidate["hospital_longitude"],
            ):
                reasons.append("Hospital coordinates are invalid.")

            if not self._valid_coordinate_pair(
                candidate["emergency_latitude"],
                candidate["emergency_longitude"],
            ):
                reasons.append("Emergency coordinates are invalid.")

        return not reasons, reasons

    def filter_candidates(self, candidates, assigned_ambulance_ids=None):
        """Split candidates into feasible and rejected records."""
        feasible = []
        rejected = []

        for candidate in candidates:
            is_feasible, reasons = self.check_candidate(
                candidate,
                assigned_ambulance_ids=assigned_ambulance_ids,
            )

            if is_feasible:
                feasible.append(candidate)
            else:
                rejected.append({
                    "candidate": candidate,
                    "reasons": reasons,
                })

        return {
            "feasible_candidates": feasible,
            "rejected_candidates": rejected,
            "input_count": len(candidates),
            "feasible_count": len(feasible),
            "rejected_count": len(rejected),
        }
