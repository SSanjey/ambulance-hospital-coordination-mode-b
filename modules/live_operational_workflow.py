import time


class LiveOperationalWorkflow:

    def __init__(
        self,
        ambulance_file,
        hospital_file,
        demand_threshold=2
    ):

        from modules.live_demand_fleet_integration import (
            LiveDemandFleetIntegration
        )

        self.integration = (
            LiveDemandFleetIntegration(
                ambulance_file,
                hospital_file,
                demand_threshold=demand_threshold
            )
        )

        self.workflow_events = []

        self.completed_dispatches = []

        self.workflow_start_time = (
            time.perf_counter()
        )

    # ---------------------------------------------------------
    # Record workflow event
    # ---------------------------------------------------------

    def _record_event(
        self,
        event_type,
        emergency_id=None,
        status="PASS",
        details=None
    ):

        event = {

            "event_number":
                len(self.workflow_events) + 1,

            "event_type":
                event_type,

            "emergency_id":
                emergency_id,

            "status":
                status,

            "details":
                details
                if details is not None
                else {}
        }

        self.workflow_events.append(
            event
        )

        return event

    # ---------------------------------------------------------
    # Submit one live emergency
    # ---------------------------------------------------------

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
            self.integration
            .submit_live_emergency(
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

        emergency_id = (
            result["emergency_id"]
        )

        self._record_event(
            "Emergency Arrival",
            emergency_id,
            "PASS",
            {
                "severity":
                    severity,

                "priority":
                    result.get(
                        "priority"
                    ),

                "status":
                    result.get(
                        "status"
                    )
            }
        )

        return result

    # ---------------------------------------------------------
    # Dispatch one live emergency
    # ---------------------------------------------------------

    def dispatch_emergency(
        self,
        emergency_id,
        condition_map=None,
        mode_b_candidate=None
    ):

        result = (
            self.integration
            .dispatch_live_emergency(
                emergency_id,
                condition_map,
                mode_b_candidate=mode_b_candidate
            )
        )

        status = (
            result.get(
                "status"
            )
        )

        dispatch_pass = (
            status == "Dispatched"
            and
            result.get(
                "ambulance_id"
            ) is not None
            and
            result.get(
                "hospital_id"
            ) is not None
        )

        self._record_event(
            "Emergency Dispatch",
            emergency_id,
            "PASS"
            if dispatch_pass
            else "FAIL",
            {
                "ambulance_id":
                    result.get(
                        "ambulance_id"
                    ),

                "hospital_id":
                    result.get(
                        "hospital_id"
                    ),

                "route_status":
                    result.get(
                        "route_status"
                    ),

                "static_route_vertices":
                    result.get(
                        "static_route_vertices"
                    ),

                "dynamic_route_vertices":
                    result.get(
                        "dynamic_route_vertices"
                    ),

                "status":
                    status
            }
        )

        if dispatch_pass:

            self.completed_dispatches.append(
                result
            )

        return result

    # ---------------------------------------------------------
    # Validate one route
    # ---------------------------------------------------------

    def validate_route(
        self,
        result
    ):

        start_vertex = (
            result.get(
                "route_start_vertex"
            )
        )

        goal_vertex = (
            result.get(
                "route_goal_vertex"
            )
        )

        route = (
            result.get(
                "static_route"
            )
        )

        vertices = (
            result.get(
                "static_route_vertices"
            )
        )

        edges = (
            result.get(
                "static_route_edges"
            )
        )

        distance = (
            result.get(
                "static_route_distance_km"
            )
        )

        if start_vertex is None:
            return False

        if goal_vertex is None:
            return False

        if not isinstance(
            route,
            list
        ):
            return False

        if len(route) < 1:
            return False

        if vertices != len(route):
            return False

        if edges != len(route) - 1:
            return False

        if distance is None:
            return False

        if float(distance) < 0:
            return False

        if start_vertex == goal_vertex:

            return (
                len(route) == 1
                and
                edges == 0
                and
                float(distance) == 0.0
            )

        return (
            len(route) >= 2
            and
            edges >= 1
            and
            float(distance) > 0
        )

    # ---------------------------------------------------------
    # Run live demand update
    # ---------------------------------------------------------

    def update_demand(self):

        demand = (
            self.integration
            .rebuild_live_demand()
        )

        high_demand = (
            self.integration
            .high_demand_zones
        )

        self._record_event(
            "Demand Update",
            None,
            "PASS"
            if len(demand) > 0
            else "FAIL",
            {
                "zone_count":
                    len(demand),

                "high_demand_zone_count":
                    len(high_demand)
            }
        )

        return demand

    # ---------------------------------------------------------
    # Run fleet repositioning
    # ---------------------------------------------------------

    def reposition_fleet(self):

        plan = (
            self.integration
            .create_live_repositioning_plan()
        )

        applied = (
            self.integration
            .apply_repositioning_plan()
        )

        reposition_pass = (
            len(plan) > 0
            and
            applied == len(plan)
        )

        self._record_event(
            "Fleet Repositioning",
            None,
            "PASS"
            if reposition_pass
            else "FAIL",
            {
                "planned":
                    len(plan),

                "applied":
                    applied
            }
        )

        return plan, applied

    # ---------------------------------------------------------
    # Run complete operational cycle
    # ---------------------------------------------------------

    def run_cycle(
        self,
        emergencies,
        condition_maps=None
    ):

        if condition_maps is None:

            condition_maps = []

        submitted = []

        dispatched = []

        # -----------------------------------------------------
        # Phase 1: live emergency arrivals
        # -----------------------------------------------------

        for emergency in emergencies:

            result = (
                self.submit_emergency(
                    latitude=
                        emergency["latitude"],

                    longitude=
                        emergency["longitude"],

                    severity=
                        emergency["severity"],

                    condition=
                        emergency["condition"],

                    required_facility=
                        emergency["required_facility"],

                    patient_location=
                        emergency["patient_location"],

                    area_address=
                        emergency.get(
                            "area_address",
                            "Live Emergency Location"
                        ),

                    patient_id=
                        emergency.get(
                            "patient_id"
                        )
                )
            )

            submitted.append(
                result
            )

        # -----------------------------------------------------
        # Phase 2: verify all emergencies are retained
        # -----------------------------------------------------

        retained = (
            len(
                self.integration
                .dispatcher
                .live_emergency_records
            )
        )

        retention_pass = (
            retained
            >= len(submitted)
        )

        self._record_event(
            "Live State Retention",
            None,
            "PASS"
            if retention_pass
            else "FAIL",
            {
                "submitted":
                    len(submitted),

                "retained":
                    retained
            }
        )

        # -----------------------------------------------------
        # Phase 3: dispatch each emergency
        # -----------------------------------------------------

        for index, submission in enumerate(
            submitted
        ):

            emergency_id = (
                submission[
                    "emergency_id"
                ]
            )

            condition_map = None

            if index < len(
                condition_maps
            ):

                condition_map = (
                    condition_maps[index]
                )

            result = (
                self.dispatch_emergency(
                    emergency_id,
                    condition_map
                )
            )

            dispatched.append(
                result
            )

            route_pass = (
                self.validate_route(
                    result
                )
            )

            self._record_event(
                "Route Validation",
                emergency_id,
                "PASS"
                if route_pass
                else "FAIL",
                {
                    "start":
                        result.get(
                            "route_start_vertex"
                        ),

                    "goal":
                        result.get(
                            "route_goal_vertex"
                        ),

                    "vertices":
                        result.get(
                            "static_route_vertices"
                        ),

                    "edges":
                        result.get(
                            "static_route_edges"
                        ),

                    "distance_km":
                        result.get(
                            "static_route_distance_km"
                        )
                }
            )

        # -----------------------------------------------------
        # Phase 4: demand analysis
        # -----------------------------------------------------

        demand = (
            self.update_demand()
        )

        # -----------------------------------------------------
        # Phase 5: fleet refresh
        # -----------------------------------------------------

        fleet_count = (
            self.integration
            .refresh_live_fleet()
        )

        fleet_pass = (
            fleet_count
            == len(
                self.integration
                .live_fleet
            )
        )

        self._record_event(
            "Fleet Refresh",
            None,
            "PASS"
            if fleet_pass
            else "FAIL",
            {
                "location_count":
                    fleet_count,

                "fleet_count":
                    len(
                        self.integration
                        .live_fleet
                    )
            }
        )

        # -----------------------------------------------------
        # Phase 6: repositioning
        # -----------------------------------------------------

        reposition_plan = []

        applied_repositioning = 0

        if (
            len(
                self.integration
                .high_demand_zones
            )
            > 0
        ):

            (
                reposition_plan,
                applied_repositioning
            ) = (
                self.reposition_fleet()
            )

        # -----------------------------------------------------
        # Runtime
        # -----------------------------------------------------

        runtime = (
            time.perf_counter()
            - self.workflow_start_time
        )

        return {

            "submitted":
                submitted,

            "dispatched":
                dispatched,

            "demand":
                demand,

            "repositioning_plan":
                reposition_plan,

            "applied_repositioning":
                applied_repositioning,

            "workflow_events":
                self.workflow_events,

            "runtime_seconds":
                round(
                    runtime,
                    6
                )
        }

    # ---------------------------------------------------------
    # Workflow validation
    # ---------------------------------------------------------

    def validate_workflow(
        self,
        result
    ):

        submitted = (
            result.get(
                "submitted",
                []
            )
        )

        dispatched = (
            result.get(
                "dispatched",
                []
            )
        )

        events = (
            result.get(
                "workflow_events",
                []
            )
        )

        if len(submitted) == 0:
            return False

        if len(dispatched) != len(
            submitted
        ):
            return False

        emergency_ids = []

        ambulance_ids = []

        for dispatch in dispatched:

            if (
                dispatch.get(
                    "status"
                )
                != "Dispatched"
            ):
                return False

            emergency_id = (
                dispatch.get(
                    "emergency_id"
                )
            )

            ambulance_id = (
                dispatch.get(
                    "ambulance_id"
                )
            )

            hospital_id = (
                dispatch.get(
                    "hospital_id"
                )
            )

            if emergency_id is None:
                return False

            if ambulance_id is None:
                return False

            if hospital_id is None:
                return False

            if not self.validate_route(
                dispatch
            ):
                return False

            emergency_ids.append(
                emergency_id
            )

            ambulance_ids.append(
                ambulance_id
            )

        if len(
            set(emergency_ids)
        ) != len(emergency_ids):
            return False

        if len(
            set(ambulance_ids)
        ) != len(ambulance_ids):
            return False

        for event in events:

            if event.get(
                "status"
            ) != "PASS":
                return False

        return True