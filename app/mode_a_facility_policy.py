"""
Mode A Facility Classification and Severity Policy
===================================================

Purpose
-------
Classifies Tamil Nadu government healthcare facilities from the
Wowsome government-facility dataset and determines whether a facility
is suitable as an ambulance destination for a given emergency severity.

Mode A emergency severity terminology
--------------------------------------
Critical
Urgent
Less Urgent
Non-Urgent

Internal facility-policy terminology
-------------------------------------
CRITICAL
HIGH
MODERATE
LOW

Severity mapping
----------------
Critical    -> CRITICAL
Urgent      -> HIGH
Less Urgent -> MODERATE
Non-Urgent  -> LOW

Important rule
--------------
Sub-Centres are retained in the complete dataset but are NOT ambulance
destinations.
"""

from collections import Counter
from pathlib import Path
import csv


# ============================================================================
# PROJECT PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

WOWSOME_FACILITY_FILE = (
    PROJECT_ROOT
    / "results"
    / "wowsome_verification"
    / "tamil_nadu_government_facilities_11494.csv"
)


# ============================================================================
# FACILITY CLASS CONSTANTS
# ============================================================================

SUBCENTRE = "SUBCENTRE"

PHC = "PHC"

UPHC = "UPHC"

UCHC = "UCHC"

TALUK_HOSPITAL = "TALUK_HOSPITAL"

NON_TALUK_HOSPITAL = "NON_TALUK_HOSPITAL"

HEADQUARTERS_HOSPITAL = "HEADQUARTERS_HOSPITAL"

SPECIALTY_HOSPITAL = "SPECIALTY_HOSPITAL"

MATERNITY_HOSPITAL = "MATERNITY_HOSPITAL"

OTHER = "OTHER"


VALID_FACILITY_CLASSES = {
    SUBCENTRE,
    PHC,
    UPHC,
    UCHC,
    TALUK_HOSPITAL,
    NON_TALUK_HOSPITAL,
    HEADQUARTERS_HOSPITAL,
    SPECIALTY_HOSPITAL,
    MATERNITY_HOSPITAL,
    OTHER,
}


# ============================================================================
# AMBULANCE DESTINATION POLICY
# ============================================================================

AMBULANCE_ELIGIBLE_CLASSES = {
    PHC,
    UPHC,
    UCHC,
    TALUK_HOSPITAL,
    NON_TALUK_HOSPITAL,
    HEADQUARTERS_HOSPITAL,
    SPECIALTY_HOSPITAL,
    MATERNITY_HOSPITAL,
}


# ============================================================================
# SEVERITY POLICY
# ============================================================================
#
# The lists below define the preferred facility-level order for each
# severity. Eligibility and priority are kept separate:
#
#   is_suitable_for_severity()
#       -> determines whether a facility class may be used
#
#   get_facility_priority()
#       -> determines the preference order among eligible classes
#
# Sub-Centres and OTHER are never ambulance destinations.
#

SEVERITY_FACILITY_POLICY = {
    "LOW": [
        PHC,
        UPHC,
        UCHC,
        TALUK_HOSPITAL,
        NON_TALUK_HOSPITAL,
        HEADQUARTERS_HOSPITAL,
        SPECIALTY_HOSPITAL,
        MATERNITY_HOSPITAL,
    ],
    "MODERATE": [
        PHC,
        UPHC,
        UCHC,
        TALUK_HOSPITAL,
        NON_TALUK_HOSPITAL,
        HEADQUARTERS_HOSPITAL,
        SPECIALTY_HOSPITAL,
        MATERNITY_HOSPITAL,
    ],
    "HIGH": [
        UCHC,
        TALUK_HOSPITAL,
        NON_TALUK_HOSPITAL,
        HEADQUARTERS_HOSPITAL,
        SPECIALTY_HOSPITAL,
        MATERNITY_HOSPITAL,
        PHC,
        UPHC,
    ],
    "CRITICAL": [
        HEADQUARTERS_HOSPITAL,
        SPECIALTY_HOSPITAL,
        NON_TALUK_HOSPITAL,
        TALUK_HOSPITAL,
        UCHC,
        MATERNITY_HOSPITAL,
        PHC,
        UPHC,
    ],
}


# ============================================================================
# MODE A SEVERITY MAPPING
# ============================================================================

MODE_A_SEVERITY_MAP = {
    "Critical": "CRITICAL",
    "Urgent": "HIGH",
    "Less Urgent": "MODERATE",
    "Non-Urgent": "LOW",
}


# ============================================================================
# GENERAL SEVERITY ALIASES
# ============================================================================

SEVERITY_ALIASES = {
    # Mode A terminology
    "CRITICAL": "CRITICAL",
    "URGENT": "HIGH",
    "LESS URGENT": "MODERATE",
    "NON-URGENT": "LOW",

    # Internal terminology
    "HIGH": "HIGH",
    "MODERATE": "MODERATE",
    "LOW": "LOW",

    # Common aliases
    "MEDIUM": "MODERATE",
    "SEVERE": "HIGH",
    "EMERGENCY": "CRITICAL",

    # Numeric aliases
    "1": "CRITICAL",
    "2": "HIGH",
    "3": "MODERATE",
    "4": "LOW",
}


# ============================================================================
# TEXT NORMALIZATION
# ============================================================================

def _normalise(value):
    """
    Normalize a text value for reliable comparison.
    """
    if value is None:
        return ""

    value = str(value).strip().lower()

    value = value.replace("&", " and ")

    value = value.replace("_", " ")

    value = value.replace("/", " ")

    value = value.replace("-", " ")

    value = " ".join(value.split())

    return value


# ============================================================================
# SEVERITY NORMALIZATION
# ============================================================================

def normalise_severity(severity):
    """
    Normalize Mode A severity labels to internal policy levels.

    Supported Mode A values
    -----------------------
    Critical
    Urgent
    Less Urgent
    Non-Urgent

    Internal values
    ---------------
    CRITICAL
    HIGH
    MODERATE
    LOW
    """

    value = str(severity).strip().upper()

    if value not in SEVERITY_ALIASES:
        raise ValueError(
            "Invalid severity. Expected Critical, Urgent, "
            "Less Urgent, Non-Urgent, LOW, MODERATE, HIGH, or CRITICAL."
        )

    return SEVERITY_ALIASES[value]


# ============================================================================
# FACILITY FIELD HELPER
# ============================================================================

def _field(record, field_name):
    """
    Safely retrieve a field from a facility record.

    The project primarily uses dictionaries loaded from CSV.
    This helper keeps the classifier robust to missing fields.
    """
    if record is None:
        return ""

    if isinstance(record, dict):
        return record.get(field_name, "") or ""

    return getattr(record, field_name, "") or ""


# ============================================================================
# FACILITY CLASSIFICATION
# ============================================================================

def classify_facility(facility):
    """
    Classify one Wowsome facility record.

    Classification order is intentional. More specific facility types
    are checked before broader categories.

    Priority of checks
    ------------------
    1. Sub-Centre
    2. UPHC
    3. PHC
    4. UCHC
    5. Headquarters Hospital
    6. Specialty Hospital
    7. Maternity Hospital
    8. District / Taluk Hospital
    9. Government Hospital
    10. Other
    """

    facility_name = _normalise(
        _field(facility, "facility_name")
    )

    facility_type = _normalise(
        _field(facility, "facility_type")
    )

    asha_vhn_tier = _normalise(
        _field(facility, "asha_vhn_tier")
    )

    # ------------------------------------------------------------------------
    # 1. SUB-CENTRE
    # ------------------------------------------------------------------------
    #
    # Sub-Centres must be identified before PHC-related checks because some
    # source fields are broad and may otherwise classify them incorrectly.
    #

    subcentre_patterns = {
        "subcentre",
        "sub center",
        "sub centre",
        "sub health center",
        "sub health centre",
        "sub health care center",
        "sub health care centre",
    }

    if any(pattern in facility_name for pattern in subcentre_patterns):
        return SUBCENTRE

    # ------------------------------------------------------------------------
    # 2. URBAN PRIMARY HEALTH CENTRE
    # ------------------------------------------------------------------------

    if (
        "urban primary health center" in facility_name
        or "urban primary health centre" in facility_name
        or "uphc" in facility_name
        or "urban phc" in facility_name
    ):
        return UPHC

    # ------------------------------------------------------------------------
    # 3. PRIMARY HEALTH CENTRE
    # ------------------------------------------------------------------------

    if (
        "primary health center" in facility_name
        or "primary health centre" in facility_name
        or "primary health centre" in asha_vhn_tier
    ):
        return PHC

    # ------------------------------------------------------------------------
    # 4. URBAN / COMMUNITY HEALTH CENTRE
    # ------------------------------------------------------------------------

    if (
        "community health center" in facility_name
        or "community health centre" in facility_name
        or "uchc" in facility_name
        or "uchc" in facility_type
    ):
        return UCHC

    # ------------------------------------------------------------------------
    # 5. HEADQUARTERS HOSPITAL
    # ------------------------------------------------------------------------

    if (
        "head quarters hospital" in facility_name
        or "headquarters hospital" in facility_name
        or "head quarter hospital" in facility_name
    ):
        return HEADQUARTERS_HOSPITAL

    # ------------------------------------------------------------------------
    # 6. SPECIALTY HOSPITAL
    # ------------------------------------------------------------------------

    if (
        facility_type == "government specialty hospital"
        or asha_vhn_tier == "tertiary medical college referral level"
    ):
        return SPECIALTY_HOSPITAL

    # ------------------------------------------------------------------------
    # 7. MATERNITY HOSPITAL
    # ------------------------------------------------------------------------

    if (
        "maternity hospital" in facility_name
        or "government maternity hospital" in facility_type
    ):
        return MATERNITY_HOSPITAL

    # ------------------------------------------------------------------------
    # 8. DISTRICT / TALUK HOSPITAL
    # ------------------------------------------------------------------------

    district_taluk_source = (
        facility_type
        == "government district taluk hospital"
    )

    district_secondary_referral = (
        "district secondary referral level" in asha_vhn_tier
    )

    if district_taluk_source or district_secondary_referral:

        if (
            "head quarters hospital" in facility_name
            or "headquarters hospital" in facility_name
            or "head quarter hospital" in facility_name
        ):
            return HEADQUARTERS_HOSPITAL

        return TALUK_HOSPITAL

    # ------------------------------------------------------------------------
    # 9. GOVERNMENT HOSPITAL
    # ------------------------------------------------------------------------

    if (
        "government hospital" in facility_type
        or facility_type == "government hospital"
        or "government hospital" in facility_name
        or "govt hospital" in facility_name
    ):
        return NON_TALUK_HOSPITAL

    # ------------------------------------------------------------------------
    # 10. OTHER
    # ------------------------------------------------------------------------

    return OTHER


# ============================================================================
# AMBULANCE DESTINATION TEST
# ============================================================================

def is_ambulance_destination(facility):
    """
    Return True when a facility can be used as an ambulance destination.

    Sub-Centres are explicitly excluded even though they remain in the
    master dataset.
    """

    facility_class = classify_facility(facility)

    return facility_class in AMBULANCE_ELIGIBLE_CLASSES


# ============================================================================
# SEVERITY SUITABILITY TEST
# ============================================================================

def is_suitable_for_severity(facility, severity):
    """
    Determine whether a facility is suitable for a given emergency severity.

    The function first normalizes the Mode A severity and then checks whether
    the classified facility belongs to the permitted facility classes.
    """

    severity = normalise_severity(severity)

    facility_class = classify_facility(facility)

    if facility_class == SUBCENTRE:
        return False

    if facility_class == OTHER:
        return False

    return facility_class in SEVERITY_FACILITY_POLICY[severity]


# ============================================================================
# FACILITY PRIORITY
# ============================================================================

def get_facility_priority(facility, severity):
    """
    Return the numerical facility priority for the requested severity.

    Lower numerical values represent higher preference.
    """

    severity = normalise_severity(severity)

    facility_class = classify_facility(facility)

    priority_list = SEVERITY_FACILITY_POLICY[severity]

    try:
        return priority_list.index(facility_class)
    except ValueError:
        return 999


# ============================================================================
# POLICY INFORMATION
# ============================================================================

def get_severity_facility_classes(severity):
    """
    Return the ordered facility-class list for a severity.
    """

    severity = normalise_severity(severity)

    return list(SEVERITY_FACILITY_POLICY[severity])


def get_mode_a_severity_mapping():
    """
    Return a copy of the Mode A severity mapping.
    """

    return dict(MODE_A_SEVERITY_MAP)


# ============================================================================
# DATASET LOADING
# ============================================================================

def load_wowsome_facilities(path=None):
    """
    Load the Wowsome government-facility dataset.
    """

    dataset_path = Path(path) if path else WOWSOME_FACILITY_FILE

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Wowsome facility dataset not found:\n{dataset_path}"
        )

    with dataset_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        return list(csv.DictReader(file))


# ============================================================================
# CLASSIFICATION SUMMARY
# ============================================================================

def get_classification_summary(records):
    """
    Return facility counts by classified facility class.
    """

    counts = Counter(
        classify_facility(record)
        for record in records
    )

    return dict(
        sorted(counts.items())
    )


# ============================================================================
# VALIDATION HELPERS
# ============================================================================

def _validate_expected_count(
    records,
    classifier,
    expected,
    description,
):
    actual = sum(
        1
        for record in records
        if classifier(record)
    )

    if actual != expected:
        raise AssertionError(
            f"{description}: expected {expected}, got {actual}"
        )

    print(
        f"PASS: {description} = {actual:,}"
    )


def validate_facility_policy():
    """
    Validate the complete facility policy against the 11,494-record
    Wowsome dataset used by Mode A.
    """

    records = load_wowsome_facilities()

    total = len(records)

    if total != 11494:
        raise AssertionError(
            f"Expected 11,494 records, got {total}"
        )

    print(
        f"PASS: Dataset contains {total:,} records"
    )

    # ------------------------------------------------------------------------
    # Expected classification counts from the validated 11,494-record
    # Wowsome dataset
    # ------------------------------------------------------------------------

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == SUBCENTRE,
        8000,
        "Sub-Centres",
    )

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == PHC,
        1480,
        "PHCs",
    )

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == UPHC,
        111,
        "UPHCs",
    )

    phc_plus_uphc = sum(
        1
        for record in records
        if classify_facility(record) in {PHC, UPHC}
    )

    if phc_plus_uphc != 1591:
        raise AssertionError(
            f"PHC + UPHC: expected 1591, got {phc_plus_uphc}"
        )

    print(
        f"PASS: PHC + UPHC = {phc_plus_uphc:,}"
    )

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == UCHC,
        349,
        "UCHCs",
    )

    taluk_hq = sum(
        1
        for record in records
        if classify_facility(record)
        in {TALUK_HOSPITAL, HEADQUARTERS_HOSPITAL}
    )

    if taluk_hq != 251:
        raise AssertionError(
            f"Taluk + Headquarters hospitals: "
            f"expected 251, got {taluk_hq}"
        )

    print(
        f"PASS: Taluk + Headquarters hospitals = {taluk_hq:,}"
    )

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == SPECIALTY_HOSPITAL,
        33,
        "Specialty hospitals",
    )

    _validate_expected_count(
        records,
        lambda r: classify_facility(r) == MATERNITY_HOSPITAL,
        9,
        "Maternity hospitals",
    )

    # ------------------------------------------------------------------------
    # Sub-Centre exclusion validation
    # ------------------------------------------------------------------------

    subcentre_destination_count = sum(
        1
        for record in records
        if classify_facility(record) == SUBCENTRE
        and is_ambulance_destination(record)
    )

    if subcentre_destination_count != 0:
        raise AssertionError(
            "Sub-Centres were incorrectly accepted as ambulance destinations."
        )

    print(
        "PASS: Sub-Centres excluded from ambulance destinations"
    )

    # ------------------------------------------------------------------------
    # Classification validity
    # ------------------------------------------------------------------------

    invalid_classes = []

    for record in records:
        facility_class = classify_facility(record)

        if facility_class not in VALID_FACILITY_CLASSES:
            invalid_classes.append(
                (
                    record.get("id"),
                    record.get("facility_name"),
                    facility_class,
                )
            )

    if invalid_classes:
        raise AssertionError(
            f"Invalid facility classifications found: "
            f"{invalid_classes[:10]}"
        )

    print(
        "PASS: All facility classifications are valid"
    )

    # ------------------------------------------------------------------------
    # Ambulance destination class validation
    # ------------------------------------------------------------------------

    for facility_class in AMBULANCE_ELIGIBLE_CLASSES:

        if facility_class == SUBCENTRE:
            raise AssertionError(
                "SUBCENTRE must never be ambulance eligible."
            )

        sample = next(
            (
                record
                for record in records
                if classify_facility(record) == facility_class
            ),
            None,
        )

        if sample is not None and not is_ambulance_destination(sample):
            raise AssertionError(
                f"Ambulance-eligible class rejected: {facility_class}"
            )

    print(
        "PASS: All ambulance-eligible classes accepted"
    )

    # ------------------------------------------------------------------------
    # Severity policy validation
    # ------------------------------------------------------------------------

    expected_severities = {
        "Critical": "CRITICAL",
        "Urgent": "HIGH",
        "Less Urgent": "MODERATE",
        "Non-Urgent": "LOW",
    }

    for mode_a_value, internal_value in expected_severities.items():

        normalized = normalise_severity(mode_a_value)

        if normalized != internal_value:
            raise AssertionError(
                f"Severity mapping error: "
                f"{mode_a_value} -> {normalized}, "
                f"expected {internal_value}"
            )

        classes = get_severity_facility_classes(
            mode_a_value
        )

        if not classes:
            raise AssertionError(
                f"No facility classes configured for {mode_a_value}"
            )

        for facility_class in classes:

            if facility_class not in AMBULANCE_ELIGIBLE_CLASSES:
                raise AssertionError(
                    f"Severity {mode_a_value} contains "
                    f"non-eligible class {facility_class}"
                )

    print(
        "PASS: Severity policies validated"
    )

    # ------------------------------------------------------------------------
    # Print classification summary
    # ------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("FACILITY CLASSIFICATION SUMMARY")
    print("=" * 80)

    summary = get_classification_summary(records)

    for facility_class in sorted(summary):
        print(
            f"{facility_class:<25}: {summary[facility_class]:,}"
        )

    print("=" * 80)

    # ------------------------------------------------------------------------
    # Display severity policy
    # ------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("MODE A FACILITY SEVERITY POLICY")
    print("=" * 80)

    for severity in [
        "LOW",
        "MODERATE",
        "HIGH",
        "CRITICAL",
    ]:

        print()
        print(f"{severity}:")

        for facility_class in SEVERITY_FACILITY_POLICY[severity]:
            print(
                f"  - {facility_class}"
            )

    print()
    print("Sub-Centres:")
    print("  - Retained in dataset")
    print("  - NOT ambulance destinations")

    print("=" * 80)

    return True


# ============================================================================
# MODULE ENTRY POINT
# ============================================================================

if __name__ == "__main__":

    print("=" * 80)
    print("MODE A FACILITY POLICY VALIDATION")
    print("=" * 80)

    validate_facility_policy()

    print("=" * 80)
    print("PASS: Facility policy validation completed.")
    print("=" * 80)