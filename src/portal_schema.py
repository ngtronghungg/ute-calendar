"""
Portal Payload Schema Validation and Error Definitions
Protects schedule feeds against malformed, unreadable, or unexpected portal schemas.
"""

from typing import Any, List, Dict


class PortalFormatError(Exception):
    """Raised when portal JSON payload has an invalid or unrecognized structure."""
    pass


KNOWN_COURSE_KEYS = {
    "tenhp", "tenhocphan", "subjectname", "subject",
    "classcoursename", "curriculumname", "tenmonhoc"
}

KNOWN_DAY_KEYS = {
    "thu", "dayofweek"
}

KNOWN_PERIOD_KEYS = {
    "periodid", "tiet", "tiethoc", "cahoc"
}

KNOWN_EXAM_DATE_KEYS = {
    "ngaythi", "examdate", "ngay"
}


def extract_items_list(data: Any) -> List[Dict[str, Any]]:
    """Extract list of items from dict wrapper or raw list."""
    if isinstance(data, list):
        return [it for it in data if isinstance(it, dict)]
    if isinstance(data, dict):
        if "result" in data and isinstance(data["result"], list):
            return [it for it in data["result"] if isinstance(it, dict)]
        if "data" in data and isinstance(data["data"], list):
            return [it for it in data["data"] if isinstance(it, dict)]
        for k, v in data.items():
            if isinstance(v, list):
                return [it for it in v if isinstance(it, dict)]
    return []


def validate_semester_payload(data: Any) -> List[Dict[str, Any]]:
    """
    Validate that semester schedule payload conforms to minimum readable requirements.
    - data must be a list or dict wrapping a list.
    - empty payload ([]) is considered 'no schedule yet', valid.
    - if items exist, each valid item must have course name and session info (day and period).
    - if total items > 0 but readable items < 50% or 0, raise PortalFormatError.
    """
    if data is None:
        return []

    if not isinstance(data, (list, dict)):
        raise PortalFormatError("Portal response is neither a list nor a dict wrapper.")

    items = extract_items_list(data)
    if not items:
        # Truly empty list is valid (not format error)
        return []

    readable_count = 0
    missing_course = 0
    missing_session = 0

    for it in items:
        keys_lower = {str(k).lower(): k for k in it.keys()}
        has_course = bool(KNOWN_COURSE_KEYS.intersection(keys_lower.keys()))
        has_day = bool(KNOWN_DAY_KEYS.intersection(keys_lower.keys()))
        has_period = bool(KNOWN_PERIOD_KEYS.intersection(keys_lower.keys()))

        if has_course and has_day and has_period:
            readable_count += 1
        else:
            if not has_course:
                missing_course += 1
            if not (has_day and has_period):
                missing_session += 1

    ratio = readable_count / len(items)
    if readable_count == 0 or ratio < 0.5:
        # Log 1-line error without student data or MSSV
        import logging
        logging.getLogger("portal_schema").warning(
            f"PortalFormatError: items={len(items)}, readable={readable_count}, missing_course={missing_course}, missing_session={missing_session}"
        )
        raise PortalFormatError(
            f"Portal schedule payload format unrecognized (readable {readable_count}/{len(items)})"
        )

    return items


def validate_exam_payload(data: Any) -> List[Dict[str, Any]]:
    """
    Validate that exam schedule payload conforms to minimum readable requirements.
    - empty payload ([]) is considered 'no exam schedule yet', valid.
    - if items exist, each valid item must have course name and exam date.
    - if total items > 0 but readable items < 50% or 0, raise PortalFormatError.
    """
    if data is None:
        return []

    if not isinstance(data, (list, dict)):
        raise PortalFormatError("Portal exam response is neither a list nor a dict wrapper.")

    items = extract_items_list(data)
    if not items:
        return []

    readable_count = 0
    missing_course = 0
    missing_date = 0

    for it in items:
        keys_lower = {str(k).lower(): k for k in it.keys()}
        has_course = bool(KNOWN_COURSE_KEYS.intersection(keys_lower.keys()))
        has_date = bool(KNOWN_EXAM_DATE_KEYS.intersection(keys_lower.keys()))

        if has_course and has_date:
            readable_count += 1
        else:
            if not has_course:
                missing_course += 1
            if not has_date:
                missing_date += 1

    ratio = readable_count / len(items)
    if readable_count == 0 or ratio < 0.5:
        import logging
        logging.getLogger("portal_schema").warning(
            f"PortalFormatError(Exam): items={len(items)}, readable={readable_count}, missing_course={missing_course}, missing_date={missing_date}"
        )
        raise PortalFormatError(
            f"Portal exam payload format unrecognized (readable {readable_count}/{len(items)})"
        )

    return items
