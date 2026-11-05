import csv

from dsa.hash_table import HashTable
from dsa.geo_distance import haversine_distance
from dsa.min_heap import MinHeap

from modules.coverage_manager import CoverageManager


class AmbulanceManager:

    def __init__(self, capacity=211):

        self.ambulances = HashTable(
            capacity
        )

        self.coverage_manager = CoverageManager()

    # --------------------------------------------------
    # Load ambulance dataset
    # --------------------------------------------------

    def load_ambulances_from_csv(
        self,
        csv_file_path
    ):
        """
        Load all ambulance records from the CSV file
        and insert them into the Hash Table.
        """

        loaded_count = 0

        with open(
            csv_file_path,
            mode="r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(
                file
            )

            for ambulance in reader:

                ambulance_id = ambulance[
                    "ambulance_id"
                ]

                self.ambulances.insert(
                    ambulance_id,
                    ambulance
                )

                loaded_count += 1

        return loaded_count

    # --------------------------------------------------
    # Get ambulance by ID
    # --------------------------------------------------

    def get_ambulance(
        self,
        ambulance_id
    ):
        """
        Search for an ambulance using its ID.
        """

        return self.ambulances.search(
            ambulance_id
        )

    # --------------------------------------------------
    # Update ambulance
    # --------------------------------------------------

    def update_ambulance(
        self,
        ambulance_id,
        updates
    ):
        """
        Update selected fields of an existing
        ambulance record.
        """

        ambulance = self.ambulances.search(
            ambulance_id
        )

        if ambulance is None:
            return False

        updated_ambulance = ambulance.copy()

        for field, value in updates.items():

            if field in updated_ambulance:

                updated_ambulance[
                    field
                ] = value

        return self.ambulances.update(
            ambulance_id,
            updated_ambulance
        )

    # --------------------------------------------------
    # Get ambulance count
    # --------------------------------------------------

    def get_ambulance_count(
        self
    ):
        """
        Return the number of ambulances stored
        in the Hash Table.
        """

        return self.ambulances.get_size()

    # --------------------------------------------------
    # Get available ambulances
    # --------------------------------------------------

    def get_available_ambulances(
        self
    ):
        """
        Return all ambulances whose status is
        'Available at Base'.
        """

        available_ambulances = []

        for index in range(
            self.ambulances.capacity
        ):

            current = (
                self.ambulances.table[index]
            )

            while current is not None:

                ambulance = current.value

                if (
                    ambulance["status"]
                    == "Available at Base"
                ):

                    available_ambulances.append(
                        ambulance
                    )

                current = current.next

        return available_ambulances

    # --------------------------------------------------
    # Get suitable ambulances
    # --------------------------------------------------

    def get_suitable_ambulances(
        self,
        severity
    ):
        """
        Return available ambulances suitable for
        the given emergency severity.
        """

        suitability_rules = {

            "Critical": {
                "ALS",
                "VVIP"
            },

            "Urgent": {
                "ALS",
                "BLS",
                "VVIP"
            },

            "Less Urgent": {
                "BLS",
                "ALS",
                "FRB",
                "NLS",
                "VVIP"
            },

            "Non-Urgent": {
                "BLS",
                "FRB",
                "NLS",
                "ALS",
                "VVIP"
            }
        }

        if severity not in suitability_rules:

            raise ValueError(
                f"Unknown severity level: {severity}"
            )

        suitable_ambulances = []

        available_ambulances = (
            self.get_available_ambulances()
        )

        for ambulance in available_ambulances:

            if (
                ambulance["ambulance_type"]
                in suitability_rules[severity]
            ):

                suitable_ambulances.append(
                    ambulance
                )

        return suitable_ambulances

    # --------------------------------------------------
    # Prepare assignment candidates
    # --------------------------------------------------

    def prepare_assignment_candidates(
        self,
        severity
    ):
        """
        Prepare available and suitable ambulances
        as candidates for later ambulance assignment.
        """

        suitable_ambulances = (
            self.get_suitable_ambulances(
                severity
            )
        )

        candidates = []

        for ambulance in suitable_ambulances:

            candidate = {

                "ambulance_id":
                    ambulance[
                        "ambulance_id"
                    ],

                "ambulance_type":
                    ambulance[
                        "ambulance_type"
                    ],

                "current_location":
                    ambulance[
                        "current_location"
                    ],

                "district":
                    ambulance[
                        "district"
                    ],

                "area":
                    ambulance[
                        "area"
                    ],

                "latitude":
                    ambulance[
                        "latitude"
                    ],

                "longitude":
                    ambulance[
                        "longitude"
                    ],

                "status":
                    ambulance[
                        "status"
                    ],

                "response_cost":
                    None
            }

            candidates.append(
                candidate
            )

        return candidates

    # --------------------------------------------------
    # Calculate response cost
    # --------------------------------------------------

    def calculate_response_cost(
        self,
        ambulance,
        emergency
    ):
        """
        Calculate provisional geographic response cost
        between an ambulance and an emergency.

        Current implementation uses straight-line
        Haversine geographic distance in kilometres.

        Later, the road-network A* module will provide
        actual road-network travel cost.
        """

        ambulance_latitude = float(
            ambulance[
                "latitude"
            ]
        )

        ambulance_longitude = float(
            ambulance[
                "longitude"
            ]
        )

        emergency_latitude = float(
            emergency[
                "latitude"
            ]
        )

        emergency_longitude = float(
            emergency[
                "longitude"
            ]
        )

        distance_km = haversine_distance(
            ambulance_latitude,
            ambulance_longitude,
            emergency_latitude,
            emergency_longitude
        )

        return distance_km

    # --------------------------------------------------
    # Prepare candidates for one emergency
    # --------------------------------------------------

    def prepare_candidates_for_emergency(
        self,
        emergency
    ):
        """
        Prepare suitable ambulance candidates for
        one emergency and calculate geographic
        response cost for each candidate.
        """

        severity = emergency[
            "severity"
        ]

        suitable_ambulances = (
            self.get_suitable_ambulances(
                severity
            )
        )

        candidates = []

        for ambulance in suitable_ambulances:

            response_cost = (
                self.calculate_response_cost(
                    ambulance,
                    emergency
                )
            )

            candidate = {

                "ambulance_id":
                    ambulance[
                        "ambulance_id"
                    ],

                "ambulance_type":
                    ambulance[
                        "ambulance_type"
                    ],

                "current_location":
                    ambulance[
                        "current_location"
                    ],

                "district":
                    ambulance[
                        "district"
                    ],

                "area":
                    ambulance[
                        "area"
                    ],

                "latitude":
                    ambulance[
                        "latitude"
                    ],

                "longitude":
                    ambulance[
                        "longitude"
                    ],

                "status":
                    ambulance[
                        "status"
                    ],

                "response_cost":
                    response_cost
            }

            candidates.append(
                candidate
            )

        return candidates

    # ==================================================
    # BASELINE ALGORITHM
    # ==================================================

    def assign_ambulance_greedy(
        self,
        emergency
    ):
        """
        Baseline ambulance assignment.

        Assign the suitable available ambulance
        with the minimum response distance.

        Objective:

            Minimize response_distance

        The Min Heap provides the minimum-cost
        feasible ambulance.
        """

        candidates = (
            self.prepare_candidates_for_emergency(
                emergency
            )
        )

        if not candidates:
            return None

        heap = MinHeap()

        for candidate in candidates:

            heap.insert(
                candidate
            )

        selected_ambulance = (
            heap.extract_min()
        )

        if selected_ambulance is None:
            return None

        ambulance_id = (
            selected_ambulance[
                "ambulance_id"
            ]
        )

        self.update_ambulance(
            ambulance_id,
            {
                "status":
                    "Dispatched",

                "assigned_emergency_id":
                    emergency[
                        "emergency_id"
                    ]
            }
        )

        selected_ambulance[
            "status"
        ] = "Dispatched"

        selected_ambulance[
            "assigned_emergency_id"
        ] = (
            emergency[
                "emergency_id"
            ]
        )

        return selected_ambulance

    # ==================================================
    # PROPOSED COVERAGE-AWARE ALGORITHM
    # ==================================================

    # --------------------------------------------------
    # Build ambulance coverage map
    # --------------------------------------------------

    def build_coverage_map(
        self
    ):
        """
        Build the coverage map using currently
        available ambulances.
        """

        available_ambulances = (
            self.get_available_ambulances()
        )

        return (
            self.coverage_manager
            .build_coverage_map(
                available_ambulances
            )
        )

    # --------------------------------------------------
    # Prepare coverage-aware candidates
    # --------------------------------------------------

    def prepare_coverage_aware_candidates(
        self,
        emergency,
        coverage_weight=10.0
    ):
        """
        Prepare suitable ambulance candidates using
        both response distance and coverage loss.

        Baseline objective:

            response_distance

        Proposed objective:

            coverage_aware_score =
                response_distance
                +
                coverage_weight * coverage_loss

        A higher coverage loss means that dispatching
        the ambulance has a larger effect on the
        remaining area coverage.
        """

        # Make sure the coverage map represents the
        # current available ambulance state.

        self.build_coverage_map()

        candidates = (
            self.prepare_candidates_for_emergency(
                emergency
            )
        )

        coverage_candidates = []

        for candidate in candidates:

            coverage_loss = (
                self.coverage_manager
                .get_coverage_loss(
                    candidate
                )
            )

            coverage_after = (
                self.coverage_manager
                .get_coverage_after_dispatch(
                    candidate
                )
            )

            marginal_benefit = (
                self.coverage_manager
                .get_marginal_coverage_benefit(
                    candidate
                )
            )

            response_distance = (
                candidate[
                    "response_cost"
                ]
            )

            coverage_penalty = (
                coverage_weight
                * coverage_loss
            )

            coverage_aware_score = (
                response_distance
                + coverage_penalty
            )

            coverage_candidate = (
                candidate.copy()
            )

            coverage_candidate[
                "response_distance"
            ] = response_distance

            coverage_candidate[
                "coverage_count"
            ] = (
                self.coverage_manager
                .get_coverage_count(
                    candidate[
                        "district"
                    ],
                    candidate[
                        "area"
                    ]
                )
            )

            coverage_candidate[
                "coverage_after_dispatch"
            ] = coverage_after

            coverage_candidate[
                "coverage_loss"
            ] = coverage_loss

            coverage_candidate[
                "marginal_coverage_benefit"
            ] = marginal_benefit

            coverage_candidate[
                "coverage_penalty"
            ] = coverage_penalty

            coverage_candidate[
                "coverage_aware_score"
            ] = coverage_aware_score

            # MinHeap minimizes response_cost.
            #
            # Therefore response_cost is temporarily
            # replaced by the proposed score.

            coverage_candidate[
                "response_cost"
            ] = coverage_aware_score

            coverage_candidates.append(
                coverage_candidate
            )

        return coverage_candidates

    # --------------------------------------------------
    # Coverage-aware ambulance assignment
    # --------------------------------------------------

    def assign_ambulance_coverage_aware(
        self,
        emergency,
        coverage_weight=10.0
    ):
        """
        Proposed coverage-aware greedy ambulance
        assignment algorithm.

        Objective:

            response_distance
            +
            coverage_weight * coverage_loss

        The original assign_ambulance_greedy()
        remains unchanged as the baseline.
        """

        candidates = (
            self.prepare_coverage_aware_candidates(
                emergency,
                coverage_weight
            )
        )

        if not candidates:
            return None

        heap = MinHeap()

        for candidate in candidates:

            heap.insert(
                candidate
            )

        selected_ambulance = (
            heap.extract_min()
        )

        if selected_ambulance is None:
            return None

        ambulance_id = (
            selected_ambulance[
                "ambulance_id"
            ]
        )

        self.update_ambulance(
            ambulance_id,
            {
                "status":
                    "Dispatched",

                "assigned_emergency_id":
                    emergency[
                        "emergency_id"
                    ]
            }
        )

        # Remove the dispatched ambulance from
        # the coverage map.

        self.coverage_manager.remove_ambulance(
            selected_ambulance
        )

        selected_ambulance[
            "status"
        ] = "Dispatched"

        selected_ambulance[
            "assigned_emergency_id"
        ] = (
            emergency[
                "emergency_id"
            ]
        )

        return selected_ambulance

