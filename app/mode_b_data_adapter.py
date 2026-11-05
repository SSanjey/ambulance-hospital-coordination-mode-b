
"""Data adapter for Mode B multi-criteria emergency dispatch.

This module reads candidates from the existing ambulance and hospital
managers. It does not assign ambulances, select hospitals, or mutate
the manager records.
"""

import math
from collections.abc import Mapping


class ModeBDataAdapter:
    """Read and validate candidate records for Mode B."""

    VALID_SEVERITIES = {
        "Critical",
        "Urgent",
        "Less Urgent",
        "Non-Urgent",
    }

    AVAILABLE_STATUS = "Available at Base"

    EXCLUDED_FACILITY_CLASSES = {
        "SUBCENTRE",
        "SUB-CENTRE",
        "SUB CENTRE",
        "OTHER",
    }

    def __init__(self, ambulance_manager, hospital_manager):
        if ambulance_manager is None:
            raise ValueError("An ambulance manager is required.")

        if hospital_manager is None:
            raise ValueError("A hospital manager is required.")

        self.ambulance_manager = ambulance_manager
        self.hospital_manager = hospital_manager

    @classmethod
    def _validate_severity(cls, severity):
        """Validate the emergency severity used by existing policies."""
        if not isinstance(severity, str):
            raise ValueError("Severity must be a string.")

        severity = severity.strip()

        if severity not in cls.VALID_SEVERITIES:
            raise ValueError(
                f"Unsupported severity: {severity!r}"
            )

        return severity

    @staticmethod
    def _valid_coordinates(record):
        """Return validated float coordinates, or None if invalid."""
        try:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
        except (KeyError, TypeError, ValueError):
            return None

        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90.0 <= latitude <= 90.0
            and -180.0 <= longitude <= 180.0
        ):
            return None

        return latitude, longitude

    @classmethod
    def _validate_emergency(cls, emergency):
        """Validate and copy the emergency data without mutating input."""
        if not isinstance(emergency, Mapping):
            raise ValueError("Emergency must be a mapping or dictionary.")

        if "latitude" not in emergency or "longitude" not in emergency:
            raise ValueError(
                "Emergency latitude and longitude are required."
            )

        coordinates = cls._valid_coordinates(emergency)

        if coordinates is None:
            raise ValueError("Emergency coordinates are invalid.")

        if "severity" not in emergency:
            raise ValueError("Emergency severity is required.")

        clean_emergency = dict(emergency)
        clean_emergency["latitude"] = coordinates[0]
        clean_emergency["longitude"] = coordinates[1]
        clean_emergency["severity"] = cls._validate_severity(
            emergency["severity"]
        )

        return clean_emergency

    def get_ambulance_candidates(self, severity):
        """Return valid, available ambulances suitable for the severity.

        The existing manager applies Mode A's ambulance-type suitability
        rules. This adapter reads the result but does not assign an ambulance.
        """
        severity = self._validate_severity(severity)

        candidates = self.ambulance_manager.get_suitable_ambulances(
            severity
        )

        if candidates is None:
            return []

        clean_candidates = []
        seen_ids = set()

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue

            ambulance_id = str(
                candidate.get("ambulance_id", "")
            ).strip()

            if not ambulance_id or ambulance_id in seen_ids:
                continue

            if candidate.get("status") != self.AVAILABLE_STATUS:
                continue

            coordinates = self._valid_coordinates(candidate)

            if coordinates is None:
                continue

            clean_candidate = dict(candidate)
            clean_candidate["latitude"] = coordinates[0]
            clean_candidate["longitude"] = coordinates[1]

            clean_candidates.append(clean_candidate)
            seen_ids.add(ambulance_id)

        return clean_candidates

    def get_hospital_candidates(self, emergency):
        """Return eligible hospital candidates without choosing one.

        Existing HospitalManager policy remains responsible for filtering
        ambulance destinations and applying severity suitability.
        """
        clean_emergency = self._validate_emergency(emergency)

        candidates = self.hospital_manager.get_candidate_hospitals(
            required_facility=clean_emergency.get("required_facility"),
            severity=clean_emergency["severity"],
        )

        if candidates is None:
            return []

        clean_candidates = []
        seen_ids = set()

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue

            facility_id = str(candidate.get("id", "")).strip()

            if not facility_id or facility_id in seen_ids:
                continue

            # Defensive check for explicitly classified ineligible records.
            facility_class = str(
                candidate.get("facility_class", "")
            ).strip().upper()

            if facility_class in self.EXCLUDED_FACILITY_CLASSES:
                continue

            coordinates = self._valid_coordinates(candidate)

            if coordinates is None:
                continue

            clean_candidate = dict(candidate)
            clean_candidate["id"] = facility_id
            clean_candidate["latitude"] = coordinates[0]
            clean_candidate["longitude"] = coordinates[1]

            clean_candidates.append(clean_candidate)
            seen_ids.add(facility_id)

        return clean_candidates

    def get_selection_context(self, emergency):
        """Collect the validated emergency and its feasible candidate pools.

        This method deliberately does not create ambulance-hospital pairs
        or choose a winner. Those operations belong to later Mode B modules.
        """
        clean_emergency = self._validate_emergency(emergency)

        ambulances = self.get_ambulance_candidates(
            clean_emergency["severity"]
        )

        hospitals = self.get_hospital_candidates(clean_emergency)

        return {
            "emergency": clean_emergency,
            "ambulances": ambulances,
            "hospitals": hospitals,
            "ambulance_candidate_count": len(ambulances),
            "hospital_candidate_count": len(hospitals),
        }
