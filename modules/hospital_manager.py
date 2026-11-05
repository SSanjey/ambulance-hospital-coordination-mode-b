"""
Hospital / Healthcare Facility Manager
======================================

Mode A integration for Tamil Nadu government healthcare facilities.

Responsibilities
----------------
1. Load government healthcare facilities into the project's Hash Table.
2. Support the validated 11,494-record Wowsome master dataset.
3. Classify facilities through the Mode A facility policy.
4. Exclude Sub-Centres from ambulance destinations.
5. Filter facilities according to emergency severity.
6. Calculate Haversine distance.
7. Perform severity-aware greedy hospital selection.

Selection strategy
------------------
For Mode A hospital selection:

    Severity
        |
        v
    Facility suitability
        |
        v
    Facility priority
        |
        v
    Haversine distance
        |
        v
    Greedy selection

The facility priority comes from app.mode_a_facility_policy.

The original emergency-facing interface is preserved:

    select_hospital_for_emergency(emergency)

The Wowsome dataset remains the primary facility dataset when
load_wowsome_facilities() is explicitly called.

Important
---------
Sub-Centres remain in the master dataset but are never returned as
ambulance destinations.
"""

import csv
import math
from pathlib import Path

from dsa.hash_table import HashTable

from app.mode_a_facility_policy import (
    classify_facility,
    is_suitable_for_severity,
    is_ambulance_destination,
    get_facility_priority,
    normalise_severity,
)


# ============================================================================
# PROJECT PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

WOWSOME_FACILITY_FILE = (
    PROJECT_ROOT
    / "results"
    / "wowsome_verification"
    / "tamil_nadu_government_facilities_11494.csv"
)


# ============================================================================
# HOSPITAL MANAGER
# ============================================================================

class HospitalManager:
    """
    Manage Tamil Nadu government healthcare facilities using a Hash Table.

    The Hash Table remains the primary DSA storage structure.

    A secondary Python list is maintained only for deterministic iteration
    during candidate filtering. The Hash Table remains responsible for
    direct hospital/facility lookup.
    """

    # ------------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------------

    def __init__(self, capacity=15001):
        """
        Initialize the hospital manager.

        Capacity is larger than the 11,494-record Wowsome dataset to provide
        reasonable space for hash-table storage.
        """

        self.hospitals = HashTable(capacity)

        # Deterministic record collection used during candidate filtering.
        #
        # This avoids depending on implementation-specific internals of the
        # HashTable such as bucket-array names or node structure.
        self._facility_records = []

        # Metadata about the active dataset.
        self.active_dataset = None

    # ========================================================================
    # INTERNAL STORAGE RESET
    # ========================================================================

    def _reset_storage(self):
        """
        Clear the current hospital/facility storage.
        """

        self.hospitals = HashTable(15001)

        self._facility_records = []

        self.active_dataset = None

    # ========================================================================
    # GENERIC CSV LOADING
    # ========================================================================

    def load_hospitals_from_csv(self, csv_file_path):
        """
        Load healthcare facilities from a CSV file.

        Expected minimum fields:
            id
            facility_name
            facility_type
            asha_vhn_tier
            district
            pincode
            latitude
            longitude

        Returns
        -------
        int
            Number of records loaded.
        """

        csv_path = Path(csv_file_path)

        if not csv_path.exists():
            raise FileNotFoundError(
                f"Hospital/facility CSV not found:\n{csv_path}"
            )

        self._reset_storage()

        loaded_count = 0

        with csv_path.open(
            mode="r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise ValueError(
                    f"CSV contains no header:\n{csv_path}"
                )

            required_columns = {
                "id",
                "facility_name",
                "facility_type",
                "asha_vhn_tier",
                "district",
                "pincode",
                "latitude",
                "longitude",
            }

            missing_columns = (
                required_columns
                - set(reader.fieldnames)
            )

            if missing_columns:
                raise ValueError(
                    "Missing required facility columns: "
                    + ", ".join(sorted(missing_columns))
                )

            for facility in reader:

                facility_id = str(
                    facility.get("id", "")
                ).strip()

                if not facility_id:
                    continue

                facility_record = dict(facility)

                # ------------------------------------------------------------
                # Store in project's Hash Table.
                # ------------------------------------------------------------

                self.hospitals.insert(
                    facility_id,
                    facility_record
                )

                # ------------------------------------------------------------
                # Store for deterministic candidate filtering.
                # ------------------------------------------------------------

                self._facility_records.append(
                    facility_record
                )

                loaded_count += 1

        self.active_dataset = str(
            csv_path
        )

        return loaded_count

    # ========================================================================
    # LOAD WOWSOME MASTER FACILITIES
    # ========================================================================

    def load_wowsome_facilities(self, csv_file_path=None):
        """
        Load the validated 11,494-record Wowsome government-facility dataset.

        Default:
            results\\wowsome_verification\\
            tamil_nadu_government_facilities_11494.csv

        Returns
        -------
        int
            Number of records loaded.
        """

        dataset_path = (
            Path(csv_file_path)
            if csv_file_path is not None
            else WOWSOME_FACILITY_FILE
        )

        return self.load_hospitals_from_csv(
            dataset_path
        )

    # ========================================================================
    # GET HOSPITAL / FACILITY
    # ========================================================================

    def get_hospital(self, hospital_id):
        """
        Retrieve a facility directly from the Hash Table.

        Returns
        -------
        dict or None
        """

        return self.hospitals.search(
            str(hospital_id)
        )

    # ========================================================================
    # GET HOSPITAL COUNT
    # ========================================================================

    def get_hospital_count(self):
        """
        Return the number of facilities stored in the Hash Table.
        """

        return self.hospitals.get_size()

    # ========================================================================
    # HAVERSINE DISTANCE
    # ========================================================================

    def calculate_haversine_distance(
        self,
        emergency_latitude,
        emergency_longitude,
        hospital_latitude,
        hospital_longitude
    ):
        """
        Calculate straight-line geographic distance between two coordinates.

        Parameters
        ----------
        emergency_latitude : float
        emergency_longitude : float
        hospital_latitude : float
        hospital_longitude : float

        Returns
        -------
        float
            Distance in kilometres.
        """

        earth_radius_km = 6371.0

        latitude1 = math.radians(
            float(emergency_latitude)
        )

        longitude1 = math.radians(
            float(emergency_longitude)
        )

        latitude2 = math.radians(
            float(hospital_latitude)
        )

        longitude2 = math.radians(
            float(hospital_longitude)
        )

        delta_latitude = (
            latitude2
            - latitude1
        )

        delta_longitude = (
            longitude2
            - longitude1
        )

        a = (
            math.sin(delta_latitude / 2.0) ** 2
            +
            math.cos(latitude1)
            *
            math.cos(latitude2)
            *
            math.sin(delta_longitude / 2.0) ** 2
        )

        c = (
            2.0
            *
            math.atan2(
                math.sqrt(a),
                math.sqrt(1.0 - a)
            )
        )

        return (
            earth_radius_km
            * c
        )

    # ========================================================================
    # GET CANDIDATE FACILITIES
    # ========================================================================

    def get_candidate_hospitals(
        self,
        required_facility=None,
        severity=None
    ):
        """
        Return ambulance-eligible candidate facilities.

        Parameters
        ----------
        required_facility : str or None
            Preserved for compatibility with the existing emergency
            interface.

            The Wowsome facility dataset does not contain a dedicated
            clinical-capability field such as "Trauma Center capability".
            Therefore this field is not used as a strict clinical filter.

        severity : str or None
            Mode A severity:
                Critical
                Urgent
                Less Urgent
                Non-Urgent

        Filtering process
        -----------------
        1. Exclude Sub-Centres and OTHER facilities.
        2. Apply the Mode A severity suitability policy.
        3. Attach facility class.
        4. Attach policy priority.

        Returns
        -------
        list[dict]
        """

        candidates = []

        if not self._facility_records:
            return candidates

        # --------------------------------------------------------------------
        # Normalize severity once.
        # --------------------------------------------------------------------

        normalized_severity = None

        if severity is not None and str(severity).strip():
            normalized_severity = normalise_severity(
                severity
            )

        # --------------------------------------------------------------------
        # Scan all loaded facilities.
        # --------------------------------------------------------------------

        for facility in self._facility_records:

            # ---------------------------------------------------------------
            # Ambulance destination rule.
            # ---------------------------------------------------------------

            if not is_ambulance_destination(
                facility
            ):
                continue

            # ---------------------------------------------------------------
            # Severity suitability rule.
            # ---------------------------------------------------------------

            if normalized_severity is not None:

                if not is_suitable_for_severity(
                    facility,
                    normalized_severity
                ):
                    continue

            # ---------------------------------------------------------------
            # Classify facility.
            # ---------------------------------------------------------------

            facility_class = classify_facility(
                facility
            )

            # Defensive protection.
            #
            # is_ambulance_destination() should already prevent these, but
            # keeping the checks here protects the hospital-selection layer
            # from future policy changes.
            #

            if facility_class in {
                "SUBCENTRE",
                "OTHER",
            }:
                continue

            # ---------------------------------------------------------------
            # Create a copy so the source dataset is not modified.
            # ---------------------------------------------------------------

            hospital_record = facility.copy()

            hospital_record[
                "facility_class"
            ] = facility_class

            # ---------------------------------------------------------------
            # Facility policy priority.
            #
            # Lower numerical value = higher preference.
            # ---------------------------------------------------------------

            if normalized_severity is not None:

                hospital_record[
                    "facility_priority"
                ] = get_facility_priority(
                    facility,
                    normalized_severity
                )

                hospital_record[
                    "policy_severity"
                ] = normalized_severity

            else:

                hospital_record[
                    "facility_priority"
                ] = 999

                hospital_record[
                    "policy_severity"
                ] = ""

            # ---------------------------------------------------------------
            # Preserve the requested clinical facility text for traceability.
            # ---------------------------------------------------------------

            hospital_record[
                "required_facility"
            ] = (
                ""
                if required_facility is None
                else str(required_facility).strip()
            )

            candidates.append(
                hospital_record
            )

        return candidates

    # ========================================================================
    # CALCULATE CANDIDATE DISTANCES
    # ========================================================================

    def calculate_candidate_distances(
        self,
        emergency_latitude,
        emergency_longitude,
        candidate_hospitals
    ):
        """
        Calculate Haversine distance from the emergency location to every
        candidate facility.

        Existing candidate records are copied before the distance field is
        added.

        Returns
        -------
        list[dict]
            Candidate records containing distance_km.
        """

        candidates_with_distance = []

        # --------------------------------------------------------------------
        # Validate emergency coordinates first.
        # --------------------------------------------------------------------

        try:
            emergency_latitude = float(
                emergency_latitude
            )

            emergency_longitude = float(
                emergency_longitude
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Emergency latitude and longitude "
                "must be numeric."
            )

        if not (
            -90.0
            <= emergency_latitude
            <= 90.0
        ):
            raise ValueError(
                "Emergency latitude must be between "
                "-90 and 90."
            )

        if not (
            -180.0
            <= emergency_longitude
            <= 180.0
        ):
            raise ValueError(
                "Emergency longitude must be between "
                "-180 and 180."
            )

        # --------------------------------------------------------------------
        # Calculate facility distances.
        # --------------------------------------------------------------------

        for hospital in candidate_hospitals:

            latitude = hospital.get(
                "latitude"
            )

            longitude = hospital.get(
                "longitude"
            )

            try:

                hospital_latitude = float(
                    latitude
                )

                hospital_longitude = float(
                    longitude
                )

            except (
                TypeError,
                ValueError
            ):

                # Facilities without coordinates cannot participate in
                # geographic selection.
                continue

            # ---------------------------------------------------------------
            # Validate facility latitude.
            # ---------------------------------------------------------------

            if not (
                -90.0
                <= hospital_latitude
                <= 90.0
            ):
                continue

            # ---------------------------------------------------------------
            # Validate facility longitude.
            # ---------------------------------------------------------------

            if not (
                -180.0
                <= hospital_longitude
                <= 180.0
            ):
                continue

            distance_km = (
                self.calculate_haversine_distance(
                    emergency_latitude,
                    emergency_longitude,
                    hospital_latitude,
                    hospital_longitude
                )
            )

            hospital_record = hospital.copy()

            hospital_record[
                "distance_km"
            ] = distance_km

            candidates_with_distance.append(
                hospital_record
            )

        return candidates_with_distance

    # ========================================================================
    # GREEDY FACILITY SELECTION
    # ========================================================================

    def select_nearest_hospital(
        self,
        candidates_with_distance
    ):
        """
        Greedy hospital/facility selection.

        Selection rule
        --------------
        When facility_priority is available:

            1. Lowest facility_priority
            2. Lowest distance_km

        This gives:

            Severity-aware facility priority
                         +
            Geographic proximity

        When facility_priority is absent:

            Lowest distance_km

        This preserves compatibility with older callers that only provide
        distance values.

        Returns
        -------
        dict or None
        """

        if not candidates_with_distance:
            return None

        selected_hospital = (
            candidates_with_distance[0]
        )

        for hospital in candidates_with_distance[1:]:

            current_priority = (
                selected_hospital.get(
                    "facility_priority"
                )
            )

            candidate_priority = (
                hospital.get(
                    "facility_priority"
                )
            )

            # ---------------------------------------------------------------
            # Priority-aware comparison.
            # ---------------------------------------------------------------

            if (
                current_priority is not None
                and candidate_priority is not None
            ):

                try:

                    current_priority_value = int(
                        current_priority
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    current_priority_value = 999

                try:

                    candidate_priority_value = int(
                        candidate_priority
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    candidate_priority_value = 999

                # -----------------------------------------------------------
                # Lower facility priority is preferred.
                # -----------------------------------------------------------

                if (
                    candidate_priority_value
                    <
                    current_priority_value
                ):
                    selected_hospital = hospital
                    continue

                # -----------------------------------------------------------
                # Same facility priority:
                # use nearest distance.
                # -----------------------------------------------------------

                if (
                    candidate_priority_value
                    ==
                    current_priority_value
                    and
                    hospital["distance_km"]
                    <
                    selected_hospital["distance_km"]
                ):
                    selected_hospital = hospital

                continue

            # ---------------------------------------------------------------
            # Compatibility mode:
            # if priority is absent, choose nearest by distance.
            # ---------------------------------------------------------------

            if (
                hospital["distance_km"]
                <
                selected_hospital["distance_km"]
            ):
                selected_hospital = hospital

        return selected_hospital

    # ========================================================================
    # SELECT HOSPITAL FOR EMERGENCY
    # ========================================================================

    def select_hospital_for_emergency(
        self,
        emergency
    ):
        """
        Select the most appropriate ambulance destination for an emergency.

        Complete process
        ----------------
        1. Read emergency coordinates.
        2. Read Mode A severity.
        3. Read required facility text.
        4. Filter ambulance-eligible facilities.
        5. Exclude Sub-Centres.
        6. Apply severity suitability.
        7. Calculate Haversine distances.
        8. Apply greedy facility-priority selection.
        9. Use distance as the tie-breaker.

        Existing interface preserved:
            select_hospital_for_emergency(emergency)

        Returns
        -------
        dict or None
            Selected facility record.
        """

        if not isinstance(
            emergency,
            dict
        ):
            raise TypeError(
                "Emergency must be a dictionary."
            )

        # --------------------------------------------------------------------
        # Emergency coordinates.
        # --------------------------------------------------------------------

        if "latitude" not in emergency:
            raise KeyError(
                "Emergency is missing latitude."
            )

        if "longitude" not in emergency:
            raise KeyError(
                "Emergency is missing longitude."
            )

        emergency_latitude = emergency[
            "latitude"
        ]

        emergency_longitude = emergency[
            "longitude"
        ]

        # --------------------------------------------------------------------
        # Existing Mode A severity terminology.
        # --------------------------------------------------------------------

        severity = emergency.get(
            "severity",
            "Moderate"
        )

        severity = str(
            severity
        ).strip()

        # --------------------------------------------------------------------
        # Required facility.
        # --------------------------------------------------------------------

        required_facility = emergency.get(
            "required_facility",
            ""
        )

        required_facility = (
            ""
            if required_facility is None
            else str(required_facility).strip()
        )

        # --------------------------------------------------------------------
        # Normalize severity.
        # --------------------------------------------------------------------

        normalized_severity = normalise_severity(
            severity
        )

        # --------------------------------------------------------------------
        # Candidate facilities.
        # --------------------------------------------------------------------

        candidate_hospitals = (
            self.get_candidate_hospitals(
                required_facility=required_facility,
                severity=severity
            )
        )

        if not candidate_hospitals:
            return None

        # --------------------------------------------------------------------
        # Geographic distance.
        # --------------------------------------------------------------------

        candidates_with_distance = (
            self.calculate_candidate_distances(
                emergency_latitude,
                emergency_longitude,
                candidate_hospitals
            )
        )

        if not candidates_with_distance:
            return None

        # --------------------------------------------------------------------
        # Greedy severity-aware selection.
        # --------------------------------------------------------------------

        selected_hospital = (
            self.select_nearest_hospital(
                candidates_with_distance
            )
        )

        if selected_hospital is None:
            return None

        # --------------------------------------------------------------------
        # Add traceability information.
        # --------------------------------------------------------------------

        selected_hospital[
            "selection_severity"
        ] = severity

        selected_hospital[
            "selection_policy_level"
        ] = normalized_severity

        selected_hospital[
            "selection_method"
        ] = (
            "Facility Priority + "
            "Haversine Distance + Greedy"
        )

        return selected_hospital


# ============================================================================
# MODULE SELF-TEST
# ============================================================================

if __name__ == "__main__":

    print("=" * 80)
    print("HOSPITAL MANAGER SELF-TEST")
    print("=" * 80)

    manager = HospitalManager()

    loaded = manager.load_wowsome_facilities()

    print(
        f"Loaded facilities : {loaded:,}"
    )

    print(
        f"Hash table size   : "
        f"{manager.get_hospital_count():,}"
    )

    # ------------------------------------------------------------------------
    # Candidate counts for all actual Mode A severities.
    # ------------------------------------------------------------------------

    for severity in [
        "Critical",
        "Urgent",
        "Less Urgent",
        "Non-Urgent",
    ]:

        candidates = (
            manager.get_candidate_hospitals(
                severity=severity
            )
        )

        print(
            f"{severity:<12} candidates : "
            f"{len(candidates):,}"
        )

    # ------------------------------------------------------------------------
    # Sub-Centre exclusion.
    # ------------------------------------------------------------------------

    critical_candidates = (
        manager.get_candidate_hospitals(
            severity="Critical"
        )
    )

    subcentre_count = sum(
        1
        for facility in critical_candidates
        if classify_facility(facility) == "SUBCENTRE"
    )

    print(
        f"Critical Sub-Centres : "
        f"{subcentre_count}"
    )

    if subcentre_count != 0:
        raise AssertionError(
            "Sub-Centres must never be ambulance destinations."
        )

    # ------------------------------------------------------------------------
    # Example emergency.
    #
    # This is only a functional self-test. The coordinates are used to
    # exercise the selection algorithm and do not represent a live incident.
    # ------------------------------------------------------------------------

    test_emergency = {
        "latitude": 12.655564,
        "longitude": 80.000000,
        "severity": "Critical",
        "required_facility": "Trauma Center",
    }

    selected = (
        manager.select_hospital_for_emergency(
            test_emergency
        )
    )

    if selected is None:
        raise RuntimeError(
            "Hospital selection returned no result."
        )

    print()
    print("Selected facility:")
    print(
        "ID                :",
        selected.get("id")
    )
    print(
        "Facility name     :",
        selected.get("facility_name")
    )
    print(
        "Facility class    :",
        selected.get("facility_class")
    )
    print(
        "Facility type     :",
        selected.get("facility_type")
    )
    print(
        "District          :",
        selected.get("district")
    )
    print(
        "Severity          :",
        selected.get("selection_severity")
    )
    print(
        "Policy level      :",
        selected.get("selection_policy_level")
    )
    print(
        "Facility priority :",
        selected.get("facility_priority")
    )
    print(
        "Distance          :",
        round(
            float(
                selected.get(
                    "distance_km",
                    0
                )
            ),
            3
        ),
        "km"
    )
    print(
        "Selection method  :",
        selected.get("selection_method")
    )

    print()
    print("=" * 80)
    print("HOSPITAL MANAGER SELF-TEST: PASS")
    print("=" * 80)