"""Phone classification using the phonenumbers library."""
from __future__ import annotations

import logging

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

from src.models.enums import PhoneType

log = logging.getLogger(__name__)

_TYPE_MAP: dict[int, PhoneType] = {
    PhoneNumberType.MOBILE: PhoneType.MOBILE,
    PhoneNumberType.FIXED_LINE: PhoneType.OFFICE,
    PhoneNumberType.FIXED_LINE_OR_MOBILE: PhoneType.OFFICE,
}


def classify_phone(raw_number: str, country_hint: str = "GB") -> PhoneType:
    """Parse *raw_number* and return the appropriate :class:`PhoneType`.

    Returns ``PhoneType.UNKNOWN`` for any parse error or unrecognised type.
    """
    if not raw_number:
        return PhoneType.UNKNOWN

    try:
        parsed = phonenumbers.parse(raw_number, country_hint)
    except NumberParseException:
        return PhoneType.UNKNOWN

    number_type = phonenumbers.number_type(parsed)
    return _TYPE_MAP.get(number_type, PhoneType.UNKNOWN)
