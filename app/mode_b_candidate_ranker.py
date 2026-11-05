"""Sorting-based candidate ranking and selection for Mode B."""

import math
from collections.abc import Mapping


class ModeBCandidateRanker:
    """Rank already-scored feasible candidates by total cost."""

    COST_FIELD = "mode_b_total_cost"

    @staticmethod
    def _read_finite_number(candidate, field):
        try:
            value = float(candidate[field])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                f"Candidate requires a valid {field!r} value."
            ) from None

        if not math.isfinite(value):
            raise ValueError(
                f"Candidate field {field!r} must be finite."
            )

        return value

    def rank_candidates(self, candidates):
        """Return copied candidates sorted from lowest to highest cost.

        Ties are resolved deterministically using response time,
        transport time, ambulance ID and hospital ID.
        The input sequence and its records are not modified.
        """
        if candidates is None:
            raise ValueError("Candidates cannot be None.")

        prepared = []

        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise ValueError(
                    "Every candidate must be a mapping or dictionary."
                )

            total_cost = self._read_finite_number(
                candidate, self.COST_FIELD
            )

            if total_cost < 0:
                raise ValueError("Candidate cost cannot be negative.")

            response_time = self._read_finite_number(
                candidate, "response_time_minutes"
            )
            transport_time = self._read_finite_number(
                candidate, "transport_time_minutes"
            )

            if response_time < 0 or transport_time < 0:
                raise ValueError("Travel times cannot be negative.")

            ambulance_id = str(
                candidate.get("ambulance_id", "")
            ).strip()
            hospital_id = str(
                candidate.get("hospital_id", "")
            ).strip()

            if not ambulance_id or not hospital_id:
                raise ValueError(
                    "Each candidate requires ambulance_id and hospital_id."
                )

            copied = dict(candidate)

            sort_key = (
                total_cost,
                response_time,
                transport_time,
                ambulance_id,
                hospital_id,
            )

            prepared.append((sort_key, copied))

        # Python's list sort uses Timsort: O(n log n) worst-case time.
        prepared.sort(key=lambda item: item[0])

        ranked = []

        for rank, (_, candidate) in enumerate(prepared, start=1):
            candidate["mode_b_rank"] = rank
            ranked.append(candidate)

        return ranked

    def select_best(self, candidates):
        """Return the lowest-cost candidate, or None for an empty list."""
        ranked = self.rank_candidates(candidates)

        if not ranked:
            return None

        return ranked[0]