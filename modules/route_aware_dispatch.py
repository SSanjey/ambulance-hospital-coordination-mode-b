import csv
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


class RouteAwareDispatch:

    def __init__(self):

        from modules.integrated_dispatch_coordinator import (
            IntegratedDispatchCoordinator
        )

        self.coordinator = (
            IntegratedDispatchCoordinator()
        )

        # Original GPS data is preserved independently
        # from EmergencyManager priority records.
        self.ambulance_locations = {}
        self.emergency_records = {}

    # ---------------------------------------------------------
    # Load original ambulance GPS records
    # ---------------------------------------------------------

    def load_ambulance_locations(
        self,
        file_path
    ):

        self.ambulance_locations = {}

        with open(
            file_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                ambulance_id = row.get(
                    "ambulance_id"
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

                self.ambulance_locations[
                    ambulance_id
                ] = {
                    "latitude": latitude,
                    "longitude": longitude
                }

        return len(
            self.ambulance_locations
        )

    # ---------------------------------------------------------
    # Preserve original emergency records
    # ---------------------------------------------------------

    def load_original_emergency_records(
        self,
        file_path,
        limit=None
    ):

        self.emergency_records = {}

        loaded = 0

        with open(
            file_path,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                if (
                    limit is not None
                    and
                    loaded >= limit
                ):
                    break

                emergency_id = row.get(
                    "emergency_id"
                )

                if not emergency_id:
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

                # Preserve the complete original row.
                record = dict(row)

                # Store validated numeric coordinates.
                record["latitude"] = latitude
                record["longitude"] = longitude

                self.emergency_records[
                    emergency_id
                ] = record

                loaded += 1

        return loaded

    # ---------------------------------------------------------
    # Load datasets
    # ---------------------------------------------------------

    def load_datasets(
        self,
        ambulance_file,
        hospital_file,
        emergency_file,
        limit=None
    ):

        ambulance_count = (
            self.coordinator
            .load_ambulances(
                ambulance_file
            )
        )

        hospital_count = (
            self.coordinator
            .load_hospitals(
                hospital_file
            )
        )

        emergency_counts = (
            self.coordinator
            .load_emergencies(
                emergency_file,
                limit=limit
            )
        )

        ambulance_location_count = (
            self.load_ambulance_locations(
                ambulance_file
            )
        )

        emergency_record_count = (
            self.load_original_emergency_records(
                emergency_file,
                limit=limit
            )
        )

        return {
            "ambulances": ambulance_count,
            "hospitals": hospital_count,
            "emergencies": emergency_counts,
            "ambulance_locations": (
                ambulance_location_count
            ),
            "emergency_records": (
                emergency_record_count
            )
        }

    # ---------------------------------------------------------
    # Retrieve preserved original emergency
    # ---------------------------------------------------------

    def _find_emergency(
        self,
        emergency_id
    ):

        return self.emergency_records.get(
            emergency_id
        )

    # ---------------------------------------------------------
    # Find nearest road-network vertices
    # ---------------------------------------------------------

    def find_nearest_vertices(
        self,
        ambulance_id,
        emergency
    ):

        from routing.find_nearest_vertex import (
            find_nearest_vertex
        )

        from routing.astar_router import (
            load_graph
        )

        graph = load_graph()

        ambulance = (
            self.ambulance_locations.get(
                ambulance_id
            )
        )

        if ambulance is None:

            raise ValueError(
                "Ambulance GPS location not found: "
                f"{ambulance_id}"
            )

        if (
            "latitude" not in emergency
            or
            "longitude" not in emergency
        ):

            raise ValueError(
                "Original emergency GPS coordinates "
                "are unavailable."
            )

        ambulance_vertex = (
            find_nearest_vertex(
                graph["vertices"],
                float(
                    ambulance["latitude"]
                ),
                float(
                    ambulance["longitude"]
                )
            )
        )

        emergency_vertex = (
            find_nearest_vertex(
                graph["vertices"],
                float(
                    emergency["latitude"]
                ),
                float(
                    emergency["longitude"]
                )
            )
        )

        return (
            graph,
            ambulance_vertex,
            emergency_vertex
        )

    # ---------------------------------------------------------
    # Static A*
    # ---------------------------------------------------------

    def calculate_static_route(
        self,
        graph,
        start_vertex,
        goal_vertex
    ):

        from routing.astar_router import (
            astar
        )

        return astar(
            graph,
            start_vertex,
            goal_vertex
        )

    # ---------------------------------------------------------
    # Dynamic A*
    # ---------------------------------------------------------

    def calculate_dynamic_route(
        self,
        graph,
        start_vertex,
        goal_vertex,
        condition_map
    ):

        from routing.dynamic_astar_router import (
            dynamic_astar
        )

        return dynamic_astar(
            graph,
            start_vertex,
            goal_vertex,
            condition_map
        )

    # ---------------------------------------------------------
    # Process one route-aware dispatch
    # ---------------------------------------------------------

    def dispatch_one(self):

        # Use the already-validated integrated
        # dispatch coordinator.
        result = (
            self.coordinator
            .process_one_emergency()
        )

        if result is None:
            return None

        ambulance_id = result.get(
            "ambulance_id"
        )

        if ambulance_id is None:

            return {
                **result,
                "route_status": "Not Available"
            }

        emergency_id = result.get(
            "emergency_id"
        )

        # Retrieve the ORIGINAL CSV emergency record,
        # not EmergencyManager's priority record.
        emergency = self._find_emergency(
            emergency_id
        )

        if emergency is None:

            return {
                **result,
                "route_status": (
                    "Original Emergency Record "
                    "Not Found"
                )
            }

        # -----------------------------------------------------
        # GPS -> road-network vertices
        # -----------------------------------------------------

        (
            graph,
            ambulance_vertex_data,
            emergency_vertex_data
        ) = self.find_nearest_vertices(
            ambulance_id,
            emergency
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
                **result,
                "route_status": (
                    "Road Vertex Not Found"
                )
            }

        # -----------------------------------------------------
        # Static road-network route
        # -----------------------------------------------------

        static_result = (
            self.calculate_static_route(
                graph,
                ambulance_vertex,
                emergency_vertex
            )
        )

        if static_result is None:

            return {
                **result,
                "route_status": "No Static Route",
                "route_start_vertex": (
                    ambulance_vertex
                ),
                "route_goal_vertex": (
                    emergency_vertex
                )
            }

        static_path, static_cost = (
            static_result
        )

        if static_path is None:

            return {
                **result,
                "route_status": "No Static Route",
                "route_start_vertex": (
                    ambulance_vertex
                ),
                "route_goal_vertex": (
                    emergency_vertex
                )
            }

        # -----------------------------------------------------
        # Complete route-aware dispatch result
        # -----------------------------------------------------

        return {
            **result,

            "route_status": (
                "Static Route Found"
            ),

            "route_start_vertex": (
                ambulance_vertex
            ),

            "route_goal_vertex": (
                emergency_vertex
            ),

            "ambulance_vertex_latitude": (
                ambulance_vertex_latitude
            ),

            "ambulance_vertex_longitude": (
                ambulance_vertex_longitude
            ),

            "emergency_vertex_latitude": (
                emergency_vertex_latitude
            ),

            "emergency_vertex_longitude": (
                emergency_vertex_longitude
            ),

            "ambulance_vertex_distance_km": (
                round(
                    float(
                        ambulance_vertex_distance
                    ),
                    6
                )
            ),

            "emergency_vertex_distance_km": (
                round(
                    float(
                        emergency_vertex_distance
                    ),
                    6
                )
            ),

            "static_route_vertices": (
                len(static_path)
            ),

            "static_route_edges": (
                len(static_path) - 1
            ),

            "static_route_distance_km": (
                round(
                    float(static_cost),
                    6
                )
            ),

            "static_route": static_path
        }