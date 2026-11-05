from modules.ambulance_manager import AmbulanceManager
from modules.emergency_manager import EmergencyManager
from modules.hospital_manager import HospitalManager


class IntegratedDispatchCoordinator:

    def __init__(self):
        self.ambulance_manager = AmbulanceManager()
        self.emergency_manager = EmergencyManager()
        self.hospital_manager = HospitalManager()

        self.dispatch_results = []
        self.assigned_ambulance_ids = set()

    # ---------------------------------------------------------
    # Load datasets
    # ---------------------------------------------------------

    def load_ambulances(self, file_path):
        return self.ambulance_manager.load_ambulances_from_csv(
            file_path
        )

    def load_hospitals(self, file_path):
        return self.hospital_manager.load_hospitals_from_csv(
            file_path
        )

    def load_emergencies(self, file_path, limit=None):
        total_loaded = (
            self.emergency_manager.load_emergencies_from_csv(
                file_path
            )
        )

        if limit is not None:
            self.emergency_manager.emergencies = (
                self.emergency_manager.emergencies[:limit]
            )

        return (
            total_loaded,
            len(self.emergency_manager.emergencies)
        )

    # ---------------------------------------------------------
    # Find original emergency record
    # ---------------------------------------------------------

    def _get_waiting_emergency(self, emergency_id):
        for emergency in self.emergency_manager.waiting_emergencies:
            if emergency["emergency_id"] == emergency_id:
                return emergency

        return None

    # ---------------------------------------------------------
    # Validate emergency coordinates
    # ---------------------------------------------------------

    def _has_valid_coordinates(self, emergency):
        try:
            float(emergency["latitude"])
            float(emergency["longitude"])

            return True

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            return False

    # ---------------------------------------------------------
    # Process one emergency
    # ---------------------------------------------------------

    def process_one_emergency(self):

        # -----------------------------------------------------
        # Step 1: Process the next emergency chronologically
        # -----------------------------------------------------

        priority_record = (
            self.emergency_manager
            .process_next_emergency()
        )

        if priority_record is None:
            return None

        # -----------------------------------------------------
        # Step 2: Get emergency ID from priority record
        # -----------------------------------------------------

        emergency_id = priority_record["emergency_id"]

        # -----------------------------------------------------
        # Step 3: Retrieve original emergency record
        #
        # The original record contains:
        # latitude
        # longitude
        # severity
        # required_facility
        # request_time
        # and other emergency fields.
        # -----------------------------------------------------

        emergency = self._get_waiting_emergency(
            emergency_id
        )

        if emergency is None:
            return None

        # -----------------------------------------------------
        # Step 4: Validate emergency coordinates
        # -----------------------------------------------------

        if not self._has_valid_coordinates(emergency):

            dispatched_record = (
                self.emergency_manager
                .dispatch_highest_priority_emergency()
            )

            if dispatched_record is None:
                return None

            result = {
                "emergency_id": emergency["emergency_id"],
                "severity": emergency["severity"],
                "ambulance_id": None,
                "ambulance_type": None,
                "response_cost": None,
                "hospital_id": None,
                "hospital_name": None,
                "hospital_distance": None,
                "status": "Invalid Emergency Location",
                "reason": (
                    "Emergency latitude/longitude is "
                    "missing or invalid"
                )
            }

            self.dispatch_results.append(result)

            return result

        # -----------------------------------------------------
        # Step 5: Dispatch highest-priority emergency
        # -----------------------------------------------------

        dispatched_record = (
            self.emergency_manager
            .dispatch_highest_priority_emergency()
        )

        if dispatched_record is None:
            return None

        # -----------------------------------------------------
        # Step 6: Assign suitable ambulance
        #
        # IMPORTANT:
        # Use the ORIGINAL emergency record here.
        # This record contains latitude and longitude.
        # -----------------------------------------------------

        selected_ambulance = (
            self.ambulance_manager
            .assign_ambulance_greedy(
                emergency
            )
        )

        # -----------------------------------------------------
        # Step 7: Handle unavailable ambulance
        # -----------------------------------------------------

        if selected_ambulance is None:

            result = {
                "emergency_id": emergency["emergency_id"],
                "severity": emergency["severity"],
                "ambulance_id": None,
                "ambulance_type": None,
                "response_cost": None,
                "hospital_id": None,
                "hospital_name": None,
                "hospital_distance": None,
                "status": "Unassigned",
                "reason": (
                    "No suitable available ambulance"
                )
            }

            self.dispatch_results.append(result)

            return result

        # -----------------------------------------------------
        # Step 8: Get selected ambulance ID
        # -----------------------------------------------------

        ambulance_id = selected_ambulance["ambulance_id"]

        # -----------------------------------------------------
        # Step 9: Prevent duplicate ambulance assignment
        # -----------------------------------------------------

        if ambulance_id in self.assigned_ambulance_ids:

            result = {
                "emergency_id": emergency["emergency_id"],
                "severity": emergency["severity"],
                "ambulance_id": None,
                "ambulance_type": None,
                "response_cost": None,
                "hospital_id": None,
                "hospital_name": None,
                "hospital_distance": None,
                "status": "Conflict",
                "reason": (
                    "Duplicate ambulance assignment detected"
                )
            }

            self.dispatch_results.append(result)

            return result

        self.assigned_ambulance_ids.add(ambulance_id)

        # -----------------------------------------------------
        # Step 10: Select nearest suitable hospital
        #
        # IMPORTANT:
        # Use the ORIGINAL emergency record because
        # hospital selection requires latitude/longitude.
        # -----------------------------------------------------

        selected_hospital = (
            self.hospital_manager
            .select_hospital_for_emergency(
                emergency
            )
        )

        # -----------------------------------------------------
        # Step 11: Handle unavailable hospital
        # -----------------------------------------------------

        if selected_hospital is None:

            result = {
                "emergency_id": emergency["emergency_id"],
                "severity": emergency["severity"],
                "ambulance_id": ambulance_id,
                "ambulance_type": (
                    selected_ambulance["ambulance_type"]
                ),
                "response_cost": round(
                    selected_ambulance["response_cost"],
                    3
                ),
                "hospital_id": None,
                "hospital_name": None,
                "hospital_distance": None,
                "status": "Hospital Unavailable",
                "reason": (
                    "No suitable candidate hospital"
                )
            }

            self.dispatch_results.append(result)

            return result

        # -----------------------------------------------------
        # Step 12: Store complete integrated result
        # -----------------------------------------------------

        result = {
            "emergency_id": emergency["emergency_id"],
            "severity": emergency["severity"],
            "ambulance_id": ambulance_id,
            "ambulance_type": (
                selected_ambulance["ambulance_type"]
            ),
            "response_cost": round(
                selected_ambulance["response_cost"],
                3
            ),
            "hospital_id": selected_hospital["id"],
            "hospital_name": (
                selected_hospital["facility_name"]
            ),
            "hospital_distance": round(
                selected_hospital["distance_km"],
                3
            ),
            "status": "Dispatched",
            "reason": (
                "Ambulance and nearest suitable "
                "hospital selected"
            )
        }

        self.dispatch_results.append(result)

        return result

    # ---------------------------------------------------------
    # Process multiple emergencies
    # ---------------------------------------------------------

    def process_all(self, limit=None):
        processed = 0

        while (
            self.emergency_manager
            .get_remaining_emergency_count()
            > 0
        ):

            if (
                limit is not None
                and processed >= limit
            ):
                break

            result = self.process_one_emergency()

            if result is not None:
                processed += 1

        return self.dispatch_results

    # ---------------------------------------------------------
    # Get results
    # ---------------------------------------------------------

    def get_results(self):
        return self.dispatch_results

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def validate_results(self):

        successful = [
            result
            for result in self.dispatch_results
            if result["status"] == "Dispatched"
        ]

        # -----------------------------------------------------
        # Check duplicate ambulance assignments
        # -----------------------------------------------------

        ambulance_ids = [
            result["ambulance_id"]
            for result in successful
        ]

        unique_ambulances = set(ambulance_ids)

        no_duplicate_ambulances = (
            len(ambulance_ids)
            == len(unique_ambulances)
        )

        # -----------------------------------------------------
        # Check hospital assignment
        # -----------------------------------------------------

        all_have_hospital = all(
            result["hospital_id"] is not None
            for result in successful
        )

        # -----------------------------------------------------
        # Check hospital distance
        # -----------------------------------------------------

        all_have_distance = all(
            result["hospital_distance"] is not None
            for result in successful
        )

        # -----------------------------------------------------
        # Check ambulance response cost
        # -----------------------------------------------------

        all_have_response_cost = all(
            result["response_cost"] is not None
            for result in successful
        )

        # -----------------------------------------------------
        # Final validation
        # -----------------------------------------------------

        return (
            no_duplicate_ambulances
            and all_have_hospital
            and all_have_distance
            and all_have_response_cost
        )

