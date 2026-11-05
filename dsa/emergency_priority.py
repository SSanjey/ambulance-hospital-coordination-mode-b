from datetime import datetime


# ---------------------------------------------------------
# Baseline model parameter
# ---------------------------------------------------------

DEFAULT_XI = 0.04


# ---------------------------------------------------------
# Proposed bounded aging parameters
# ---------------------------------------------------------

AGING_ALPHA = 0.20
AGING_TAU = 10.0


# ---------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------

def severity_to_kappa(severity):
    """
    Convert emergency severity into its numerical
    severity value.

    Critical       -> 2.5
    Urgent         -> 2.0
    Less Urgent    -> 1.5
    Non-Urgent     -> 1.0
    """

    severity_mapping = {
        "Critical": 2.5,
        "Urgent": 2.0,
        "Less Urgent": 1.5,
        "Non-Urgent": 1.0
    }

    if severity not in severity_mapping:
        raise ValueError(
            f"Unknown severity level: {severity}"
        )

    return severity_mapping[severity]


# ---------------------------------------------------------
# Waiting-time calculation
# ---------------------------------------------------------

def calculate_waiting_time(request_time, current_time):
    """
    Calculate emergency waiting time in minutes.

    Input format:
        YYYY-MM-DD HH:MM:SS
    """

    request_datetime = datetime.strptime(
        request_time,
        "%Y-%m-%d %H:%M:%S"
    )

    current_datetime = datetime.strptime(
        current_time,
        "%Y-%m-%d %H:%M:%S"
    )

    waiting_time_seconds = (
        current_datetime - request_datetime
    ).total_seconds()

    if waiting_time_seconds < 0:
        raise ValueError(
            "Current time cannot be earlier than request time"
        )

    return waiting_time_seconds / 60


# ---------------------------------------------------------
# Baseline priority
# ---------------------------------------------------------

def calculate_baseline_priority(
    kappa,
    waiting_time,
    xi=DEFAULT_XI
):
    """
    Calculate the original research-based priority.

    P_baseline =
        xi * kappa / [1 + xi * waiting_time]^2
    """

    if kappa <= 0:
        raise ValueError(
            "Kappa must be greater than zero"
        )

    if waiting_time < 0:
        raise ValueError(
            "Waiting time cannot be negative"
        )

    if xi <= 0:
        raise ValueError(
            "Xi must be greater than zero"
        )

    priority = (
        xi * kappa
    ) / (
        (1 + xi * waiting_time) ** 2
    )

    return priority


# ---------------------------------------------------------
# Proposed bounded aging factor
# ---------------------------------------------------------

def calculate_aging_factor(
    waiting_time,
    alpha=AGING_ALPHA,
    tau=AGING_TAU
):
    """
    Calculate the bounded aging factor.

    Aging factor =
        1 + alpha * waiting_time / (waiting_time + tau)

    The factor starts at 1 and approaches
    (1 + alpha) as waiting time increases.
    """

    if waiting_time < 0:
        raise ValueError(
            "Waiting time cannot be negative"
        )

    if alpha <= 0:
        raise ValueError(
            "Alpha must be greater than zero"
        )

    if tau <= 0:
        raise ValueError(
            "Tau must be greater than zero"
        )

    aging_factor = (
        1
        + alpha
        * (
            waiting_time
            / (waiting_time + tau)
        )
    )

    return aging_factor


# ---------------------------------------------------------
# Proposed severity-safe aging priority
# ---------------------------------------------------------

def calculate_priority(
    kappa,
    waiting_time,
    xi=DEFAULT_XI,
    alpha=AGING_ALPHA,
    tau=AGING_TAU
):
    """
    Calculate the proposed severity-safe aging priority.

    P_proposed =
        kappa *
        [1 + alpha * W / (W + tau)]

    The proposed model preserves severity as the
    primary factor and introduces bounded waiting-time
    aging.

    Waiting time increases priority, while the aging
    contribution approaches a finite upper bound.
    """

    if kappa <= 0:
        raise ValueError(
            "Kappa must be greater than zero"
        )

    if waiting_time < 0:
        raise ValueError(
            "Waiting time cannot be negative"
        )

    if xi <= 0:
        raise ValueError(
            "Xi must be greater than zero"
        )

    # Validate the original model parameters even
    # though the proposed formula does not use xi.
    baseline_priority = calculate_baseline_priority(
        kappa,
        waiting_time,
        xi
    )

    # Keep the baseline calculation available for
    # comparison and validation.
    _ = baseline_priority

    aging_factor = calculate_aging_factor(
        waiting_time,
        alpha,
        tau
    )

    priority = kappa * aging_factor

    return priority


# ---------------------------------------------------------
# Complete priority record
# ---------------------------------------------------------

def create_priority_record(
    emergency,
    current_time,
    xi=DEFAULT_XI
):
    """
    Create a complete priority record.

    Required emergency fields:
        emergency_id
        severity
        request_time
    """

    emergency_id = emergency["emergency_id"]
    severity = emergency["severity"]
    request_time = emergency["request_time"]

    kappa = severity_to_kappa(
        severity
    )

    waiting_time = calculate_waiting_time(
        request_time,
        current_time
    )

    baseline_priority = calculate_baseline_priority(
        kappa,
        waiting_time,
        xi
    )

    aging_factor = calculate_aging_factor(
        waiting_time
    )

    priority = calculate_priority(
        kappa,
        waiting_time,
        xi
    )

    priority_record = {
        "emergency_id": emergency_id,
        "severity": severity,
        "kappa": kappa,
        "request_time": request_time,
        "waiting_time_minutes": waiting_time,

        # Original model
        "baseline_priority": baseline_priority,

        # Proposed model
        "aging_factor": aging_factor,
        "priority": priority
    }

    return priority_record