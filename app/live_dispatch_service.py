from pathlib import Path

from modules.live_operational_workflow import LiveOperationalWorkflow


class LiveDispatchService:

    def __init__(self, project_root=None):

        if project_root is None:
            project_root = (
                Path(__file__).resolve().parent.parent
            )

        self.project_root = Path(project_root)

        self.data_directory = (
            self.project_root / "data"
        )

        self.ambulance_file = (
            self.data_directory /
            "ambulances (2).csv"
        )

        self.hospital_file = (
            self.project_root /
	    "results" /
	    "wowsome_verification" /
            "tamil_nadu_government_facilities_11494.csv"
        )

        if not self.ambulance_file.exists():
            raise FileNotFoundError(
                f"Ambulance dataset not found: "
                f"{self.ambulance_file}"
            )

        if not self.hospital_file.exists():
            raise FileNotFoundError(
                f"Hospital dataset not found: "
                f"{self.hospital_file}"
            )

        self.workflow = LiveOperationalWorkflow(
            str(self.ambulance_file),
            str(self.hospital_file),
            demand_threshold=2
        )

        self.submitted_emergencies = []

        self.dispatched_emergencies = []


    def submit_emergency(
        self,
        latitude,
        longitude,
        severity,
        condition,
        required_facility,
        patient_location,
        area_address="Live Emergency Location",
        patient_id=None,
        request_time=None
    ):

        result = (
            self.workflow.submit_emergency(
                latitude=latitude,
                longitude=longitude,
                severity=severity,
                condition=condition,
                required_facility=required_facility,
                patient_location=patient_location,
                area_address=area_address,
                patient_id=patient_id,
                request_time=request_time
            )
        )

        emergency_id = result["emergency_id"]

        self.submitted_emergencies.append(
            emergency_id
        )

        return result


    def dispatch_emergency(
        self,
        emergency_id,
        condition_map=None,
        mode_b_candidate=None
    ):

        result = (
            self.workflow.dispatch_emergency(
                emergency_id,
                condition_map=condition_map,
                mode_b_candidate=mode_b_candidate
            )
        )

        if (
            result is not None
            and result.get("status") == "Dispatched"
        ):
            self.dispatched_emergencies.append(
                emergency_id
            )

        return result


    def validate_route(self, result):

        return self.workflow.validate_route(
            result
        )


    def get_runtime_info(self):

        dispatcher = (
            self.workflow
            .integration
            .dispatcher
        )

        if hasattr(
            dispatcher,
            "get_runtime_info"
        ):
            return dispatcher.get_runtime_info()

        return {
            "submitted_emergencies":
                len(self.submitted_emergencies),

            "dispatched_emergencies":
                len(self.dispatched_emergencies)
        }


    def get_status(self):

        return {
            "service": "Live Dispatch Service",

            "status": "ready",

            "ambulance_file":
                str(self.ambulance_file),

            "hospital_file":
                str(self.hospital_file),

            "submitted_emergencies":
                len(self.submitted_emergencies),

            "dispatched_emergencies":
                len(self.dispatched_emergencies)
        }