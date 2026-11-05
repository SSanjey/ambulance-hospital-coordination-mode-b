from collections import defaultdict


class CoverageManager:

    def __init__(self):
        self.coverage_map = defaultdict(set)

    # --------------------------------------------------
    # Build coverage map
    # --------------------------------------------------

    def build_coverage_map(
        self,
        ambulances
    ):
        self.coverage_map = defaultdict(set)

        for ambulance in ambulances:

            ambulance_id = ambulance[
                "ambulance_id"
            ]

            district = ambulance[
                "district"
            ].strip()

            area = ambulance[
                "area"
            ].strip()

            coverage_key = (
                district
                + "|"
                + area
            )

            self.coverage_map[
                coverage_key
            ].add(
                ambulance_id
            )

        return self.coverage_map

    # --------------------------------------------------
    # Get coverage key
    # --------------------------------------------------

    def get_coverage_key(
        self,
        ambulance
    ):

        district = ambulance[
            "district"
        ].strip()

        area = ambulance[
            "area"
        ].strip()

        return (
            district
            + "|"
            + area
        )

    # --------------------------------------------------
    # Number of ambulances covering an area
    # --------------------------------------------------

    def get_coverage_count(
        self,
        district,
        area
    ):

        coverage_key = (
            district.strip()
            + "|"
            + area.strip()
        )

        return len(
            self.coverage_map.get(
                coverage_key,
                set()
            )
        )

    # --------------------------------------------------
    # Coverage after dispatch
    # --------------------------------------------------

    def get_coverage_after_dispatch(
        self,
        ambulance
    ):

        coverage_key = (
            self.get_coverage_key(
                ambulance
            )
        )

        current_count = len(
            self.coverage_map.get(
                coverage_key,
                set()
            )
        )

        return max(
            0,
            current_count - 1
        )

    # --------------------------------------------------
    # Coverage loss
    # --------------------------------------------------

    def get_coverage_loss(
        self,
        ambulance
    ):

        coverage_key = (
            self.get_coverage_key(
                ambulance
            )
        )

        current_count = len(
            self.coverage_map.get(
                coverage_key,
                set()
            )
        )

        if current_count == 0:
            return 0

        return (
            1 / current_count
        )

    # --------------------------------------------------
    # Marginal coverage benefit
    # --------------------------------------------------

    def get_marginal_coverage_benefit(
        self,
        ambulance
    ):
        """
        Calculate the marginal benefit of preserving
        the ambulance in its current coverage area.

        Areas with fewer available ambulances have
        greater marginal coverage importance.

        Formula:

            marginal_benefit = 1 / coverage_count

        Therefore:

            coverage_count = 1  -> 1.0000
            coverage_count = 2  -> 0.5000
            coverage_count = 10 -> 0.1000
        """

        coverage_count = (
            self.get_coverage_count(
                ambulance["district"],
                ambulance["area"]
            )
        )

        if coverage_count == 0:
            return 0

        return (
            1 / coverage_count
        )

    # --------------------------------------------------
    # Remove ambulance from coverage map
    # --------------------------------------------------

    def remove_ambulance(
        self,
        ambulance
    ):
        """
        Remove a dispatched ambulance from the
        coverage map.
        """

        coverage_key = (
            self.get_coverage_key(
                ambulance
            )
        )

        ambulance_id = ambulance[
            "ambulance_id"
        ]

        if coverage_key not in self.coverage_map:
            return False

        if ambulance_id not in self.coverage_map[
            coverage_key
        ]:
            return False

        self.coverage_map[
            coverage_key
        ].remove(
            ambulance_id
        )

        # Remove empty coverage areas.
        if not self.coverage_map[
            coverage_key
        ]:
            del self.coverage_map[
                coverage_key
            ]

        return True

