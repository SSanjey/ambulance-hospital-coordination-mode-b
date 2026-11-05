import os
import sys
import time
from datetime import datetime


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(
        0,
        PROJECT_ROOT
    )


class LiveEmergencyDispatch:

    # ---------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------

    def __init__(
        self,
        ambulance_file,
        hospital_file
    ):

        from modules.route_aware_dispatch import (
            RouteAwareDispatch
        )

        from routing.astar_router import (
            load_graph
        )

        self.ambulance_file = ambulance_file
        self.hospital_file = hospital_file

        # -----------------------------------------------------
        # Existing validated dispatch system
        # -----------------------------------------------------

        self.route_dispatch = (
            RouteAwareDispatch()
        )

        self.coordinator = (
            self.route_dispatch.coordinator
        )

        # -----------------------------------------------------
        # Live emergency records
        #
        # These are maintained independently from
        # emergencies.csv.
        # -----------------------------------------------------

        self.live_emergency_records = {}

        # -----------------------------------------------------
        # Load ambulance dataset once
        # -----------------------------------------------------

        self.ambulance_count = (
            self.coordinator.load_ambulances(
                ambulance_file
            )
        )

        # -----------------------------------------------------
        # Load hospital dataset once
        # -----------------------------------------------------

        self.hospital_count = (
            self.coordinator.load_hospitals(
                hospital_file
            )
        )

        # -----------------------------------------------------
        # Load ambulance GPS locations once
        # -----------------------------------------------------

        self.ambulance_location_count = (
            self.route_dispatch
            .load_ambulance_locations(
                ambulance_file
            )
        )

        # -----------------------------------------------------
        # Load statewide road graph ONCE
        # -----------------------------------------------------

        graph_start = time.perf_counter()

        self.graph = load_graph()

        self.graph_load_time = (
            time.perf_counter()
            - graph_start
        )

        # -----------------------------------------------------
        # Live emergency sequence
        # -----------------------------------------------------

        self.live_sequence = 0

    # ---------------------------------------------------------
    # Generate a unique live emergency ID
    # ---------------------------------------------------------

    def _generate_emergency_id(self):

        self.live_sequence += 1

        timestamp = (
            datetime.now()
            .strftime(
                "%Y%m%d%H%M%S"
            )
        )

        return (
            "LIVE-"
            + timestamp
            + "-"
            + f"{self.live_sequence:04d}"
        )

    # ---------------------------------------------------------
    # Validate severity
    # ---------------------------------------------------------

    def _validate_severity(
        self,
        severity
    ):

        valid_severities = {
            "Critical",
            "Urgent",
            "Less Urgent",
            "Non-Urgent"
        }

        if severity not in valid_severities:

            raise ValueError(
                "Invalid severity. "
                "Use Critical, Urgent, Less Urgent, "
                "or Non-Urgent."
            )

    # ---------------------------------------------------------
    # Validate GPS coordinates
    # ---------------------------------------------------------

    def _validate_coordinates(
        self,
        latitude,
        longitude
    ):

        try:

            latitude = float(
                latitude
            )

            longitude = float(
                longitude
            )

        except (
            TypeError,
            ValueError
        ):

            raise ValueError(
                "Latitude and longitude "
                "must be numeric."
            )

        if not (
            -90.0
            <= latitude
            <= 90.0
        ):

            raise ValueError(
                "Latitude must be between "
                "-90 and 90."
            )

        if not (
            -180.0
            <= longitude
            <= 180.0
        ):

            raise ValueError(
                "Longitude must be between "
                "-180 and 180."
            )

        return (
            latitude,
            longitude
        )

    # ---------------------------------------------------------
    # Normalize live request time
    #
    # A live request cannot occur before the current simulation
    # time. When a new request arrives later, its request time
    # becomes the new simulation time.
    # ---------------------------------------------------------

    def _normalize_request_time(
        self,
        request_time
    ):

        # -----------------------------------------------------
        # Convert the supplied or current wall-clock time.
        # -----------------------------------------------------

        if request_time is None:

            candidate_time = (
                datetime.now()
            )

        elif isinstance(
            request_time,
            datetime
        ):

            candidate_time = (
                request_time
            )

        else:

            try:

                candidate_time = (
                    datetime.strptime(
                        str(request_time),
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

            except ValueError:

                raise ValueError(
                    "request_time must use "
                    "YYYY-MM-DD HH:MM:SS format."
                )

        # -----------------------------------------------------
        # Read existing simulation time.
        # -----------------------------------------------------

        current_time = (
            self.coordinator
            .emergency_manager
            .current_time
        )

        if current_time is not None:

            if isinstance(
                current_time,
                datetime
            ):

                current_datetime = (
                    current_time
                )

            else:

                current_datetime = (
                    datetime.strptime(
                        str(current_time),
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

            # -------------------------------------------------
            # Do not allow a live request to be earlier than
            # the current simulation time.
            # -------------------------------------------------

            if candidate_time < current_datetime:

                candidate_time = (
                    current_datetime
                )

        return candidate_time

    # ---------------------------------------------------------
    # Advance the simulation clock for a live request
    # ---------------------------------------------------------

    def _update_simulation_time(
        self,
        request_datetime
    ):

        emergency_manager = (
            self.coordinator
            .emergency_manager
        )

        current_time = (
            emergency_manager.current_time
        )

        if current_time is None:

            emergency_manager.current_time = (
                request_datetime.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            return

        if isinstance(
            current_time,
            datetime
        ):

            current_datetime = (
                current_time
            )

        else:

            current_datetime = (
                datetime.strptime(
                    str(current_time),
                    "%Y-%m-%d %H:%M:%S"
                )
            )

        # -----------------------------------------------------
        # Advance only when the live request is newer.
        # -----------------------------------------------------

        if request_datetime > current_datetime:

            emergency_manager.current_time = (
                request_datetime.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

        else:

            emergency_manager.current_time = (
                current_datetime.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

    # ---------------------------------------------------------
    # Submit a new live emergency
    # ---------------------------------------------------------

    def submit_emergency(
        self,
        latitude,
        longitude,
        severity,
        condition,
        required_facility,
        patient_location="Live User Location",
        area_address="Live Emergency Location",
        patient_id=None,
        request_time=None
    ):

        # -----------------------------------------------------
        # Validate input
        # -----------------------------------------------------

        self._validate_severity(
            severity
        )

        (
            latitude,
            longitude
        ) = self._validate_coordinates(
            latitude,
            longitude
        )

        if not condition:

            raise ValueError(
                "Emergency condition "
                "cannot be empty."
            )

        if not required_facility:

            raise ValueError(
                "Required facility "
                "cannot be empty."
            )

        # -----------------------------------------------------
        # Determine request time.
        # -----------------------------------------------------

        request_datetime = (
            self._normalize_request_time(
                request_time
            )
        )

        request_time_string = (
            request_datetime.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # -----------------------------------------------------
        # Move the simulation clock forward BEFORE inserting
        # the emergency.
        #
        # This is required because EmergencyManager's
        # add_emergency() rebuilds priorities using current_time.
        # -----------------------------------------------------

        self._update_simulation_time(
            request_datetime
        )

        # -----------------------------------------------------
        # Generate unique ID
        # -----------------------------------------------------

        emergency_id = (
            self._generate_emergency_id()
        )

        if patient_id is None:

            patient_id = (
                "LIVE-PATIENT-"
                + emergency_id
            )

        # -----------------------------------------------------
        # Complete live emergency record
        # -----------------------------------------------------

        emergency = {

            "emergency_id":
                emergency_id,

            "patient_id":
                patient_id,

            "patient_location":
                patient_location,

            "area_address":
                area_address,

            "latitude":
                latitude,

            "longitude":
                longitude,

            "severity":
                severity,

            "triage_category":
                severity,

            "condition":
                condition,

            "required_facility":
                required_facility,

            "request_time":
                request_time_string,

            "status":
                "Waiting",

            "assigned_ambulance_id":
                "",

            "is_duplicate":
                False,

            "duplicate_of_emergency_id":
                ""
        }

        # -----------------------------------------------------
        # Preserve the COMPLETE live record.
        #
        # This keeps latitude, longitude, required facility,
        # condition, and all user-entered fields available
        # after priority processing.
        # -----------------------------------------------------

        self.live_emergency_records[
            emergency_id
        ] = dict(emergency)

        # -----------------------------------------------------
        # Insert into the existing EmergencyManager.
        # -----------------------------------------------------

        priority_record = (
            self.coordinator
            .emergency_manager
            .add_emergency(
                emergency
            )
        )

        if priority_record is None:

            raise RuntimeError(
                "Live emergency could not "
                "be inserted into the priority queue."
            )

        return {

            "emergency_id":
                emergency_id,

            "patient_id":
                patient_id,

            "severity":
                severity,

            "priority":
                priority_record.get(
                    "priority"
                ),

            "priority_record":
                priority_record,

            "status":
                "Waiting"
        }

    # ---------------------------------------------------------
    # Get ambulance GPS location
    # ---------------------------------------------------------

    def _get_ambulance_location(
        self,
        ambulance_id
    ):

        return (
            self.route_dispatch
            .ambulance_locations
            .get(
                ambulance_id
            )
        )

    # ---------------------------------------------------------
    # Find nearest road vertices
    # ---------------------------------------------------------

    def _find_nearest_vertices(
        self,
        ambulance_id,
        emergency
    ):

        from routing.find_nearest_vertex import (
            find_nearest_vertex
        )

        ambulance = (
            self._get_ambulance_location(
                ambulance_id
            )
        )

        if ambulance is None:

            raise ValueError(
                "Ambulance GPS location "
                "not found."
            )

        # -----------------------------------------------------
        # Ambulance GPS -> nearest road vertex
        # -----------------------------------------------------

        ambulance_vertex_data = (
            find_nearest_vertex(
                self.graph["vertices"],
                float(
                    ambulance["latitude"]
                ),
                float(
                    ambulance["longitude"]
                )
            )
        )

        # -----------------------------------------------------
        # Emergency GPS -> nearest road vertex
        # -----------------------------------------------------

        emergency_vertex_data = (
            find_nearest_vertex(
                self.graph["vertices"],
                float(
                    emergency["latitude"]
                ),
                float(
                    emergency["longitude"]
                )
            )
        )

        return (
            ambulance_vertex_data,
            emergency_vertex_data
        )

    # ---------------------------------------------------------
    # Calculate static A* route
    # ---------------------------------------------------------

    def _calculate_static_route(
        self,
        start_vertex,
        goal_vertex
    ):

        from routing.astar_router import (
            astar
        )

        return astar(
            self.graph,
            start_vertex,
            goal_vertex
        )

    # ---------------------------------------------------------
    # Dispatch one live emergency
    # ---------------------------------------------------------

    def dispatch_live_emergency(
        self,
        emergency_id,
        condition_map=None,
        mode_b_candidate=None
    ):

        start_time = (
            time.perf_counter()
        )

        # -----------------------------------------------------
        # Find the requested emergency in the waiting list.
        # -----------------------------------------------------

        emergency = None

        for item in (
            self.coordinator
            .emergency_manager
            .waiting_emergencies
        ):

            if (
                item["emergency_id"]
                == emergency_id
            ):

                emergency = item

                break

        if emergency is None:

            return {

                "emergency_id":
                    emergency_id,

                "status":
                    "Emergency Not Found"
            }

        # -----------------------------------------------------
        # Optional Mode B preflight. Mode A does not enter this branch.
        # Validate both resources before changing ambulance state.
        # -----------------------------------------------------
        mode_b_ambulance_record = None
        mode_b_hospital_record = None

        if mode_b_candidate is not None:
            if not isinstance(mode_b_candidate, dict):
                return {
                    "emergency_id": emergency_id,
                    "status": "Invalid Mode B Candidate"
                }

            selected_ambulance_id = str(
                mode_b_candidate.get("ambulance_id", "")
            ).strip()
            selected_hospital_id = str(
                mode_b_candidate.get("hospital_id", "")
            ).strip()

            if not selected_ambulance_id or not selected_hospital_id:
                return {
                    "emergency_id": emergency_id,
                    "status": "Invalid Mode B Candidate IDs"
                }

            waiting_records = getattr(
                self.coordinator.emergency_manager,
                "waiting_emergencies",
                None
            )
            if isinstance(waiting_records, list) and waiting_records:
                queue_head = waiting_records[0]
                if isinstance(queue_head, dict):
                    queue_head_id = str(
                        queue_head.get("emergency_id", "")
                    ).strip()
                    if queue_head_id and queue_head_id != str(emergency_id).strip():
                        return {
                            "emergency_id": emergency_id,
                            "blocking_emergency_id": queue_head_id,
                            "status": "Higher Priority Emergency Pending"
                        }

            suitable_ambulances = (
                self.coordinator.ambulance_manager.get_suitable_ambulances(
                    emergency.get("severity")
                )
            )
            mode_b_ambulance_record = next(
                (
                    item for item in suitable_ambulances
                    if str(item.get("ambulance_id", "")).strip() == selected_ambulance_id
                    and str(item.get("status", "")).strip() == "Available at Base"
                ),
                None
            )
            if mode_b_ambulance_record is None:
                return {
                    "emergency_id": emergency_id,
                    "ambulance_id": selected_ambulance_id,
                    "status": "Mode B Ambulance No Longer Eligible"
                }

            eligible_hospitals = (
                self.coordinator.hospital_manager.get_candidate_hospitals(
                    required_facility=emergency.get("required_facility"),
                    severity=emergency.get("severity")
                )
            )
            mode_b_hospital_record = next(
                (
                    item for item in eligible_hospitals
                    if str(item.get("id", "")).strip() == selected_hospital_id
                ),
                None
            )
            if mode_b_hospital_record is None:
                return {
                    "emergency_id": emergency_id,
                    "hospital_id": selected_hospital_id,
                    "status": "Mode B Hospital No Longer Eligible"
                }

        # -----------------------------------------------------
        # Dispatch the highest-priority waiting emergency.
        # -----------------------------------------------------

        dispatched = (
            self.coordinator
            .emergency_manager
            .dispatch_highest_priority_emergency()
        )

        if dispatched is None:

            return {

                "emergency_id":
                    emergency_id,

                "status":
                    "Dispatch Failed"
            }

        dispatched_id = (
            dispatched[
                "emergency_id"
            ]
        )

        # -----------------------------------------------------
        # Protect against dispatching a different emergency.
        # -----------------------------------------------------

        if dispatched_id != emergency_id:

            return {

                "emergency_id":
                    emergency_id,

                "dispatched_emergency_id":
                    dispatched_id,

                "status":
                    "Higher Priority Emergency Dispatched"
            }

        # -----------------------------------------------------
        # Recover complete original live record.
        # -----------------------------------------------------

        original_live_emergency = (
            self.live_emergency_records.get(
                emergency_id
            )
        )

        if original_live_emergency is None:

            return {

                "emergency_id":
                    emergency_id,

                "status":
                    "Live Emergency Record Not Found"
            }

        # -----------------------------------------------------
        # Merge original emergency information with the
        # priority/dispatched record.
        # -----------------------------------------------------

        dispatch_record = {

            **original_live_emergency,

            **dispatched
        }

        # -----------------------------------------------------
        # Ambulance assignment
        # -----------------------------------------------------

        if mode_b_candidate is None:
            # Existing Mode A/default behavior remains unchanged.
            ambulance_result = (
                self.coordinator
                .ambulance_manager
                .assign_ambulance_greedy(
                    dispatch_record
                )
            )
        else:
            # Commit the exact ambulance selected and ranked by Mode B.
            ambulance_result = dict(mode_b_ambulance_record)
            ambulance_id_for_update = str(
                mode_b_candidate.get("ambulance_id", "")
            ).strip()
            updated = self.coordinator.ambulance_manager.update_ambulance(
                ambulance_id_for_update,
                {
                    "status": "Dispatched",
                    "assigned_emergency_id": emergency_id
                }
            )
            if not updated:
                return {
                    "emergency_id": emergency_id,
                    "ambulance_id": ambulance_id_for_update,
                    "status": "Mode B Ambulance Assignment Failed"
                }
            ambulance_result["status"] = "Dispatched"
            ambulance_result["assigned_emergency_id"] = emergency_id
            selected_response_distance = mode_b_candidate.get("response_distance_km")
            if selected_response_distance is not None:
                ambulance_result["response_cost"] = selected_response_distance

        if ambulance_result is None:

            return {

                "emergency_id":
                    emergency_id,

                "status":
                    "No Ambulance Available"
            }

        ambulance_id = (
            ambulance_result[
                "ambulance_id"
            ]
        )

        ambulance_type = (
            ambulance_result.get(
                "ambulance_type"
            )
        )

        response_cost = (
            ambulance_result.get(
                "response_cost"
            )
        )

        # -----------------------------------------------------
        # Hospital selection
        #
        # Existing HospitalManager uses:
        # id
        # facility_name
        # distance_km
        # -----------------------------------------------------

        if mode_b_candidate is None:
            # Existing Mode A/default hospital policy remains unchanged.
            hospital_result = (
                self.coordinator
                .hospital_manager
                .select_hospital_for_emergency(
                    dispatch_record
                )
            )
        else:
            # Use the exact eligible hospital selected by Mode B.
            hospital_result = dict(mode_b_hospital_record)
            selected_hospital_distance = mode_b_candidate.get("hospital_distance_km")
            if selected_hospital_distance is not None:
                hospital_result["distance_km"] = selected_hospital_distance

        hospital_id = None
        hospital_name = None
        hospital_distance = None

        if hospital_result is not None:

            hospital_id = (
                hospital_result.get(
                    "id"
                )
            )

            hospital_name = (
                hospital_result.get(
                    "facility_name"
                )
            )

            hospital_distance = (
                hospital_result.get(
                    "distance_km"
                )
            )

        # -----------------------------------------------------
        # GPS -> road vertices
        # -----------------------------------------------------

        (
            ambulance_vertex_data,
            emergency_vertex_data
        ) = self._find_nearest_vertices(
            ambulance_id,
            dispatch_record
        )

        (
            ambulance_vertex,
            ambulance_vertex_latitude,
            ambulance_vertex_longitude,
            ambulance_vertex_distance
        ) = ambulance_vertex_data

        (
            emergency_vertex,
            emergency_vertex_latitude,
            emergency_vertex_longitude,
            emergency_vertex_distance
        ) = emergency_vertex_data

        if (
            ambulance_vertex is None
            or
            emergency_vertex is None
        ):

            return {

                "emergency_id":
                    emergency_id,

                "ambulance_id":
                    ambulance_id,

                "status":
                    "Road Vertex Not Found"
            }

        # -----------------------------------------------------
        # Static A*
        # -----------------------------------------------------

        static_result = (
            self._calculate_static_route(
                ambulance_vertex,
                emergency_vertex
            )
        )

        if static_result is None:

            return {

                "emergency_id":
                    emergency_id,

                "ambulance_id":
                    ambulance_id,

                "status":
                    "No Static Route"
            }

        (
            static_path,
            static_cost
        ) = static_result

        # -----------------------------------------------------
        # Dynamic A*
        #
        # If the caller supplies a condition_map, use it.
        # Otherwise load the project's current dynamic
        # road-condition dataset.
        #
        # This keeps Dynamic A* active during normal
        # Live Emergency Dispatch while still allowing
        # external real-time traffic conditions to be
        # supplied later.
        # -----------------------------------------------------

        dynamic_path = None
        dynamic_cost = None

        dynamic_status = (
            "Not Requested"
        )

        from routing.dynamic_astar_router import (
            dynamic_astar,
            load_conditions
        )

        if condition_map is None:

            condition_map = load_conditions()

        if condition_map:

            dynamic_result = (
                dynamic_astar(
                    self.graph,
                    ambulance_vertex,
                    emergency_vertex,
                    condition_map
                )
            )

            if dynamic_result is not None:

                (
                    dynamic_path,
                    dynamic_cost
                ) = dynamic_result

                dynamic_status = (
                    "Dynamic Route Found"
                )

            else:

                dynamic_status = (
                    "No Dynamic Route"
                )

        else:

            dynamic_status = (
                "No Dynamic Conditions"
            )

        # -----------------------------------------------------
        # Processing time
        # -----------------------------------------------------

        processing_time = (
            time.perf_counter()
            - start_time
        )

        # -----------------------------------------------------
        # Final result
        # -----------------------------------------------------

        result = {

            "emergency_id":
                emergency_id,

            "severity":
                dispatch_record[
                    "severity"
                ],

            "ambulance_id":
                ambulance_id,

            "ambulance_type":
                ambulance_type,

            "response_cost":
                response_cost,

            "hospital_id":
                hospital_id,

            "hospital_name":
                hospital_name,

            "hospital_distance":
                hospital_distance,

            "status":
                "Dispatched",

            "route_status":
                "Static Route Found",

            "route_start_vertex":
                ambulance_vertex,

            "route_goal_vertex":
                emergency_vertex,

            "ambulance_vertex_distance_km":
                round(
                    float(
                        ambulance_vertex_distance
                    ),
                    6
                ),

            "emergency_vertex_distance_km":
                round(
                    float(
                        emergency_vertex_distance
                    ),
                    6
                ),

            "static_route_vertices":
                len(static_path),

            "static_route_edges":
                len(static_path) - 1,

            "static_route_distance_km":
                round(
                    float(static_cost),
                    6
                ),

            "static_route":
                static_path,

            "dynamic_status":
                dynamic_status,

            "dynamic_route_vertices":
                (
                    len(dynamic_path)
                    if dynamic_path is not None
                    else 0
                ),

            "dynamic_route_distance_km":
                (
                    round(
                        float(dynamic_cost),
                        6
                    )
                    if dynamic_cost is not None
                    else None
                ),

            "dynamic_route":
                dynamic_path,

            "graph_load_time_seconds":
                round(
                    self.graph_load_time,
                    6
                ),

            "processing_time_seconds":
                round(
                    processing_time,
                    6
                )
        }

        # -----------------------------------------------------
        # Preserve final live emergency state.
        # -----------------------------------------------------

        self.live_emergency_records[
            emergency_id
        ] = {

            **self.live_emergency_records.get(
                emergency_id,
                {}
            ),

            **result
        }

        return result

    # ---------------------------------------------------------
    # Runtime information
    # ---------------------------------------------------------

    def get_runtime_info(self):

        return {

            "ambulances":
                self.ambulance_count,

            "hospitals":
                self.hospital_count,

            "ambulance_gps_locations":
                self.ambulance_location_count,

            "graph_nodes":
                len(
                    self.graph[
                        "adjacency"
                    ]
                ),

            "graph_vertices":
                len(
                    self.graph[
                        "vertices"
                    ]
                ),

            "graph_load_time_seconds":
                round(
                    self.graph_load_time,
                    6
                ),

            "live_emergency_count":
                len(
                    self.live_emergency_records
                )
        }