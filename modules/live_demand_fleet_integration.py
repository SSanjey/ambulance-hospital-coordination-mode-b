import csv
import math
import os
import sys


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


from modules.live_emergency_dispatch import (
    LiveEmergencyDispatch
)


class LiveDemandFleetIntegration:

    # ---------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------

    def __init__(
        self,
        ambulance_file,
        hospital_file,
        demand_threshold=2
    ):

        self.ambulance_file = (
            ambulance_file
        )

        self.hospital_file = (
            hospital_file
        )

        self.demand_threshold = int(
            demand_threshold
        )

        # -----------------------------------------------------
        # Reuse Stage 12 live dispatch system.
        # The statewide graph is loaded once by this object.
        # -----------------------------------------------------

        self.dispatcher = (
            LiveEmergencyDispatch(
                ambulance_file,
                hospital_file
            )
        )

        # -----------------------------------------------------
        # Live demand state
        # -----------------------------------------------------

        self.live_zone_demand = {}

        self.live_zone_coordinates = {}

        self.high_demand_zones = []

        # -----------------------------------------------------
        # Build the live fleet from the actual ambulance
        # dataset ONCE.
        #
        # RouteAwareDispatch.ambulance_locations contains only
        # GPS coordinates, so status and assignment information
        # must come from the ambulance CSV.
        # -----------------------------------------------------

        self.live_fleet = {}

        self._load_initial_live_fleet()

        # -----------------------------------------------------
        # Current repositioning plan
        # -----------------------------------------------------

        self.repositioning_plan = []

    # ---------------------------------------------------------
    # Load complete initial fleet state
    # ---------------------------------------------------------

    def _load_initial_live_fleet(self):

        self.live_fleet = {}

        with open(
            self.ambulance_file,
            mode="r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                ambulance_id = (
                    row.get(
                        "ambulance_id"
                    )
                )

                if not ambulance_id:
                    continue

                try:

                    latitude = float(
                        row["latitude"]
                    )

                    longitude = float(
                        row["longitude"]
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError
                ):

                    continue

                self.live_fleet[
                    ambulance_id
                ] = {

                    "ambulance_id":
                        ambulance_id,

                    "ambulance_type":
                        row.get(
                            "ambulance_type",
                            ""
                        ),

                    "current_location":
                        row.get(
                            "current_location",
                            ""
                        ),

                    "district":
                        row.get(
                            "district",
                            ""
                        ),

                    "area":
                        row.get(
                            "area",
                            ""
                        ),

                    "latitude":
                        latitude,

                    "longitude":
                        longitude,

                    "status":
                        row.get(
                            "status",
                            ""
                        ),

                    "equipment_level":
                        row.get(
                            "equipment_level",
                            ""
                        ),

                    "assigned_emergency_id":
                        row.get(
                            "assigned_emergency_id",
                            ""
                        ),

                    "nearest_hospital_id":
                        row.get(
                            "nearest_hospital_id",
                            ""
                        ),

                    "nearest_hospital_name":
                        row.get(
                            "nearest_hospital_name",
                            ""
                        )
                }

        return len(
            self.live_fleet
        )

    # ---------------------------------------------------------
    # Haversine distance
    # ---------------------------------------------------------

    def calculate_distance(
        self,
        lat1,
        lon1,
        lat2,
        lon2
    ):

        radius = 6371.0

        lat1 = math.radians(
            float(lat1)
        )

        lon1 = math.radians(
            float(lon1)
        )

        lat2 = math.radians(
            float(lat2)
        )

        lon2 = math.radians(
            float(lon2)
        )

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = (
            math.sin(dlat / 2) ** 2
            +
            math.cos(lat1)
            * math.cos(lat2)
            * math.sin(dlon / 2) ** 2
        )

        c = (
            2
            * math.atan2(
                math.sqrt(a),
                math.sqrt(1 - a)
            )
        )

        return radius * c

    # ---------------------------------------------------------
    # Add one live emergency to demand analysis
    # ---------------------------------------------------------

    def _add_live_emergency_to_demand(
        self,
        emergency
    ):

        zone = (
            emergency.get(
                "patient_location",
                ""
            )
            .strip()
        )

        if not zone:

            zone = (
                emergency.get(
                    "area_address",
                    ""
                )
                .strip()
            )

        if not zone:

            zone = "Unknown Zone"

        if zone not in self.live_zone_demand:

            self.live_zone_demand[
                zone
            ] = 0

            self.live_zone_coordinates[
                zone
            ] = []

        self.live_zone_demand[
            zone
        ] += 1

        self.live_zone_coordinates[
            zone
        ].append(
            (
                float(
                    emergency["latitude"]
                ),
                float(
                    emergency["longitude"]
                )
            )
        )

    # ---------------------------------------------------------
    # Rebuild demand using only live emergency records
    # ---------------------------------------------------------

    def rebuild_live_demand(self):

        self.live_zone_demand = {}

        self.live_zone_coordinates = {}

        for emergency in (
            self.dispatcher
            .live_emergency_records
            .values()
        ):

            self._add_live_emergency_to_demand(
                emergency
            )

        self._calculate_high_demand_zones()

        return self.get_live_demand()

    # ---------------------------------------------------------
    # Calculate high-demand zones
    # ---------------------------------------------------------

    def _calculate_high_demand_zones(self):

        self.high_demand_zones = []

        for zone, count in (
            self.live_zone_demand.items()
        ):

            if count < self.demand_threshold:
                continue

            coordinates = (
                self.live_zone_coordinates[
                    zone
                ]
            )

            latitude = (
                sum(
                    point[0]
                    for point in coordinates
                )
                / len(coordinates)
            )

            longitude = (
                sum(
                    point[1]
                    for point in coordinates
                )
                / len(coordinates)
            )

            self.high_demand_zones.append(
                {
                    "zone":
                        zone,

                    "emergency_count":
                        count,

                    "latitude":
                        latitude,

                    "longitude":
                        longitude
                }
            )

        self.high_demand_zones.sort(
            key=lambda item: (
                item["emergency_count"],
                item["zone"]
            ),
            reverse=True
        )

        return self.high_demand_zones

    # ---------------------------------------------------------
    # Return all live demand
    # ---------------------------------------------------------

    def get_live_demand(self):

        results = []

        for zone, count in (
            self.live_zone_demand.items()
        ):

            coordinates = (
                self.live_zone_coordinates[
                    zone
                ]
            )

            latitude = (
                sum(
                    point[0]
                    for point in coordinates
                )
                / len(coordinates)
            )

            longitude = (
                sum(
                    point[1]
                    for point in coordinates
                )
                / len(coordinates)
            )

            results.append(
                {
                    "zone":
                        zone,

                    "emergency_count":
                        count,

                    "latitude":
                        latitude,

                    "longitude":
                        longitude
                }
            )

        results.sort(
            key=lambda item: (
                item["emergency_count"],
                item["zone"]
            ),
            reverse=True
        )

        return results

    # ---------------------------------------------------------
    # Submit live emergency
    # ---------------------------------------------------------

    def submit_live_emergency(
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
            self.dispatcher
            .submit_emergency(
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

        emergency = (
            self.dispatcher
            .live_emergency_records[
                result["emergency_id"]
            ]
        )

        self._add_live_emergency_to_demand(
            emergency
        )

        self._calculate_high_demand_zones()

        return result

    # ---------------------------------------------------------
    # Dispatch a live emergency
    # ---------------------------------------------------------

    def dispatch_live_emergency(
        self,
        emergency_id,
        condition_map=None,
        mode_b_candidate=None
    ):

        result = (
            self.dispatcher
            .dispatch_live_emergency(
                emergency_id,
                condition_map,
                mode_b_candidate=mode_b_candidate
            )
        )

        ambulance_id = (
            result.get(
                "ambulance_id"
            )
        )

        if mode_b_candidate is None:
            # Preserve existing Mode A fleet-state behavior.
            if ambulance_id is not None:
                ambulance = self.live_fleet.get(ambulance_id)
                if ambulance is not None:
                    ambulance["status"] = "Dispatched"
                    ambulance["assigned_emergency_id"] = emergency_id
        else:
            # Only commit the live-fleet mirror when the exact Mode B resource
            # was actually dispatched successfully.
            expected_ambulance_id = str(
                mode_b_candidate.get("ambulance_id", "")
            ).strip()
            if (
                result.get("status") == "Dispatched"
                and str(ambulance_id).strip() == expected_ambulance_id
            ):
                ambulance = self.live_fleet.get(ambulance_id)
                if ambulance is not None:
                    ambulance["status"] = "Dispatched"
                    ambulance["assigned_emergency_id"] = emergency_id

        return result

    # ---------------------------------------------------------
    # Refresh only GPS coordinates.
    #
    # IMPORTANT:
    # Do not overwrite the live status or assignment fields.
    # Those fields are maintained by the live integration.
    # ---------------------------------------------------------

    def refresh_live_fleet(self):

        location_count = 0

        for (
            ambulance_id,
            location
        ) in (
            self.dispatcher
            .route_dispatch
            .ambulance_locations
            .items()
        ):

            if ambulance_id not in self.live_fleet:

                self.live_fleet[
                    ambulance_id
                ] = {

                    "ambulance_id":
                        ambulance_id,

                    "ambulance_type":
                        "",

                    "district":
                        "",

                    "area":
                        "",

                    "latitude":
                        float(
                            location["latitude"]
                        ),

                    "longitude":
                        float(
                            location["longitude"]
                        ),

                    "status":
                        "Unknown",

                    "assigned_emergency_id":
                        ""
                }

            else:

                self.live_fleet[
                    ambulance_id
                ]["latitude"] = float(
                    location["latitude"]
                )

                self.live_fleet[
                    ambulance_id
                ]["longitude"] = float(
                    location["longitude"]
                )

            location_count += 1

        return location_count

    # ---------------------------------------------------------
    # Get currently available live ambulances
    #
    # Available at Base:
    # initial fleet availability.
    #
    # Repositioned:
    # an ambulance that has already been moved to a
    # high-demand location and is again available.
    # ---------------------------------------------------------

    def _get_available_live_ambulances(self):

        available = []

        for ambulance in (
            self.live_fleet.values()
        ):

            status = (
                ambulance.get(
                    "status",
                    ""
                )
            )

            assigned_id = (
                ambulance.get(
                    "assigned_emergency_id",
                    ""
                )
            )

            if (
                status in {
                    "Available at Base",
                    "Repositioned"
                }
                and
                not assigned_id
            ):

                available.append(
                    ambulance
                )

        return available

    # ---------------------------------------------------------
    # Create live fleet repositioning plan
    #
    # Greedy selection:
    #
    # 1. Highest-demand zone first.
    # 2. Find nearest currently available ambulance.
    # 3. Remove selected ambulance from the remaining pool.
    # 4. Continue for remaining high-demand zones.
    # ---------------------------------------------------------

    def create_live_repositioning_plan(self):

        if not self.high_demand_zones:

            self._calculate_high_demand_zones()

        remaining_ambulances = (
            self._get_available_live_ambulances()
        )

        self.repositioning_plan = []

        for zone_info in (
            self.high_demand_zones
        ):

            if not remaining_ambulances:

                break

            best_ambulance = None

            best_distance = float(
                "inf"
            )

            for ambulance in (
                remaining_ambulances
            ):

                distance = (
                    self.calculate_distance(
                        ambulance["latitude"],
                        ambulance["longitude"],
                        zone_info["latitude"],
                        zone_info["longitude"]
                    )
                )

                if distance < best_distance:

                    best_distance = distance

                    best_ambulance = (
                        ambulance
                    )

            if best_ambulance is None:

                continue

            self.repositioning_plan.append(
                {
                    "zone":
                        zone_info["zone"],

                    "emergency_count":
                        zone_info[
                            "emergency_count"
                        ],

                    "ambulance_id":
                        best_ambulance[
                            "ambulance_id"
                        ],

                    "ambulance_type":
                        best_ambulance[
                            "ambulance_type"
                        ],

                    "from_district":
                        best_ambulance[
                            "district"
                        ],

                    "from_area":
                        best_ambulance[
                            "area"
                        ],

                    "from_latitude":
                        best_ambulance[
                            "latitude"
                        ],

                    "from_longitude":
                        best_ambulance[
                            "longitude"
                        ],

                    "target_latitude":
                        zone_info[
                            "latitude"
                        ],

                    "target_longitude":
                        zone_info[
                            "longitude"
                        ],

                    "distance_km":
                        best_distance
                }
            )

            remaining_ambulances.remove(
                best_ambulance
            )

        return self.repositioning_plan

    # ---------------------------------------------------------
    # Apply the repositioning plan
    # ---------------------------------------------------------

    def apply_repositioning_plan(self):

        applied_count = 0

        for assignment in (
            self.repositioning_plan
        ):

            ambulance_id = (
                assignment[
                    "ambulance_id"
                ]
            )

            ambulance = (
                self.live_fleet.get(
                    ambulance_id
                )
            )

            if ambulance is None:
                continue

            ambulance[
                "latitude"
            ] = assignment[
                "target_latitude"
            ]

            ambulance[
                "longitude"
            ] = assignment[
                "target_longitude"
            ]

            ambulance[
                "status"
            ] = "Repositioned"

            ambulance[
                "assigned_emergency_id"
            ] = ""

            applied_count += 1

        return applied_count

    # ---------------------------------------------------------
    # Runtime summary
    # ---------------------------------------------------------

    def get_runtime_summary(self):

        return {

            "live_emergency_count":
                len(
                    self.dispatcher
                    .live_emergency_records
                ),

            "live_zone_count":
                len(
                    self.live_zone_demand
                ),

            "high_demand_zone_count":
                len(
                    self.high_demand_zones
                ),

            "repositioning_assignment_count":
                len(
                    self.repositioning_plan
                ),

            "fleet_count":
                len(
                    self.live_fleet
                ),

            "graph_load_time":
                self.dispatcher
                .graph_load_time
        }