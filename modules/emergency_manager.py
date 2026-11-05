import csv
from datetime import datetime

from dsa.max_heap import MaxHeap
from dsa.emergency_priority import create_priority_record


class EmergencyManager:

    # ---------------------------------------------------------
    # Emergency status lifecycle
    # ---------------------------------------------------------

    ALLOWED_STATUSES = {
        "Waiting",
        "Dispatched",
        "Completed",
        "Cancelled"
    }

    VALID_STATUS_TRANSITIONS = {
        "Waiting": {"Dispatched", "Cancelled"},
        "Dispatched": {"Completed"},
        "Completed": set(),
        "Cancelled": set()
    }

    def __init__(self, current_time=None, xi=0.04):
        self.current_time = current_time
        self.xi = xi
        self.priority_queue = MaxHeap()

        # All emergency records loaded from the CSV file.
        self.emergencies = []

        # Emergencies that have arrived and are waiting for dispatch.
        self.waiting_emergencies = []

        # Emergencies already dispatched.
        self.dispatched_emergencies = []

    def _parse_request_time(self, request_time):
        return datetime.strptime(
            request_time,
            "%Y-%m-%d %H:%M:%S"
        )

    # ---------------------------------------------------------
    # Step 2.14 — Status validation
    # ---------------------------------------------------------

    def is_valid_status(self, status):
        """
        Check whether the supplied status is one of the
        allowed emergency statuses.
        """

        return status in self.ALLOWED_STATUSES

    def update_emergency_status(self, emergency_id, new_status):
        """
        Change the status of an emergency only when the
        requested status transition is valid.

        Waiting -> Dispatched:
            Move emergency from waiting_emergencies
            to dispatched_emergencies.

        Waiting -> Cancelled:
            Remove emergency from waiting_emergencies.

        Dispatched -> Completed:
            Update the status of the emergency in
            dispatched_emergencies.
        """

        # -----------------------------------------------------
        # Check whether the new status is valid.
        # -----------------------------------------------------

        if not self.is_valid_status(new_status):
            return False

        # -----------------------------------------------------
        # Search among waiting emergencies.
        # -----------------------------------------------------

        for index, emergency in enumerate(
            self.waiting_emergencies
        ):

            if emergency["emergency_id"] == emergency_id:

                current_status = emergency.get(
                    "status",
                    "Waiting"
                )

                allowed_statuses = (
                    self.VALID_STATUS_TRANSITIONS[
                        current_status
                    ]
                )

                # Reject invalid transition.
                if new_status not in allowed_statuses:
                    return False

                # -------------------------------------------------
                # Waiting -> Dispatched
                # -------------------------------------------------

                if new_status == "Dispatched":

                    emergency["status"] = "Dispatched"

                    # Remove from waiting emergencies.
                    self.waiting_emergencies.pop(index)

                    # Add to dispatched emergencies.
                    self.dispatched_emergencies.append(
                        emergency
                    )

                    # Rebuild priority queue because this
                    # emergency is no longer waiting.
                    self._rebuild_priority_queue()

                    return True

                # -------------------------------------------------
                # Waiting -> Cancelled
                # -------------------------------------------------

                if new_status == "Cancelled":

                    emergency["status"] = "Cancelled"

                    # Remove from active waiting emergencies.
                    self.waiting_emergencies.pop(index)

                    # Rebuild priority queue because this
                    # emergency is no longer waiting.
                    self._rebuild_priority_queue()

                    return True

                return False

        # ---------------------------------------------------------
        # Search among dispatched emergencies.
        # ---------------------------------------------------------

        for emergency in self.dispatched_emergencies:

            if emergency["emergency_id"] == emergency_id:

                current_status = emergency.get(
                    "status",
                    "Dispatched"
                )

                allowed_statuses = (
                    self.VALID_STATUS_TRANSITIONS[
                        current_status
                    ]
                )

                # Reject invalid transition.
                if new_status not in allowed_statuses:
                    return False

                # -------------------------------------------------
                # Dispatched -> Completed
                # -------------------------------------------------

                if new_status == "Completed":

                    emergency["status"] = "Completed"

                    return True

                return False

        # ---------------------------------------------------------
        # Emergency ID was not found.
        # ---------------------------------------------------------

        return False

    def get_emergency_status(self, emergency_id):
        """
        Return the current status of an emergency.
        """

        # ---------------------------------------------------------
        # Search waiting emergencies.
        # ---------------------------------------------------------

        for emergency in self.waiting_emergencies:

            if emergency["emergency_id"] == emergency_id:
                return emergency.get("status")

        # ---------------------------------------------------------
        # Search dispatched emergencies.
        # ---------------------------------------------------------

        for emergency in self.dispatched_emergencies:

            if emergency["emergency_id"] == emergency_id:
                return emergency.get("status")

        return None

    # ---------------------------------------------------------
    # Emergency insertion
    # ---------------------------------------------------------

    def add_emergency(self, emergency):
        """
        Add an arrived emergency to the waiting set.
        """

        if self.current_time is None:
            self.current_time = emergency["request_time"]

        # Every newly arrived emergency starts in Waiting state.
        emergency["status"] = "Waiting"

        self.waiting_emergencies.append(emergency)

        self._rebuild_priority_queue()

        return self.priority_queue.peek()

    def _rebuild_priority_queue(self):
        """
        Recalculate the priority of every waiting emergency
        using the current simulation time and rebuild the Max Heap.
        """

        self.priority_queue = MaxHeap()

        for emergency in self.waiting_emergencies:

            priority_record = create_priority_record(
                emergency,
                self.current_time,
                self.xi
            )

            self.priority_queue.insert(
                priority_record
            )

    def load_emergencies_from_csv(self, csv_file_path):
        """
        Load emergency records from CSV and sort them
        chronologically by request_time.
        """

        self.emergencies = []

        with open(
            csv_file_path,
            mode="r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for emergency in reader:
                self.emergencies.append(
                    emergency
                )

        self.emergencies.sort(
            key=lambda emergency:
                self._parse_request_time(
                    emergency["request_time"]
                )
        )

        return len(self.emergencies)

    def process_next_emergency(self):
        """
        Process the next emergency according to its
        chronological request time.

        The simulation clock advances to the arrival time,
        and priorities of all currently waiting emergencies
        are recalculated.
        """

        if not self.emergencies:
            return None

        emergency = self.emergencies.pop(0)

        self.current_time = emergency["request_time"]

        # Newly arrived emergency enters the Waiting state.
        emergency["status"] = "Waiting"

        self.waiting_emergencies.append(
            emergency
        )

        # Refresh priorities of all waiting emergencies
        # because the simulation time has advanced.
        self._rebuild_priority_queue()

        return self.priority_queue.peek()

    def get_highest_priority_emergency(self):
        """
        Return the highest-priority waiting emergency
        without removing it from the queue.
        """

        return self.priority_queue.peek()

    def dispatch_highest_priority_emergency(self):
        """
        Dispatch and remove the highest-priority waiting
        emergency from the Max Heap and waiting set.
        """

        emergency = self.priority_queue.extract_max()

        if emergency is None:
            return None

        emergency_id = emergency["emergency_id"]

        self.waiting_emergencies = [
            item
            for item in self.waiting_emergencies
            if item["emergency_id"] != emergency_id
        ]

        # The emergency has now been dispatched.
        emergency["status"] = "Dispatched"

        self.dispatched_emergencies.append(
            emergency
        )

        # Rebuild the heap for the remaining waiting emergencies.
        self._rebuild_priority_queue()

        return emergency

    def get_queue_size(self):
        """
        Return the number of currently waiting emergencies.
        """

        return len(self.priority_queue.heap)

    def get_remaining_emergency_count(self):
        """
        Return the number of emergency records that have
        not yet arrived in the simulation.
        """

        return len(self.emergencies)

    def get_dispatched_count(self):
        """
        Return the number of emergencies dispatched.
        """

        return len(self.dispatched_emergencies)

    def get_waiting_count(self):
        """
        Return the number of emergencies currently waiting.
        """

        return len(self.waiting_emergencies)