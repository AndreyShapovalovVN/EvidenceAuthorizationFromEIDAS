"""Compatibility workaround for letter-coded assurance from the eIDAS connector."""

EIDAS_ASSURANCE_MAPPING = {
    "A": "low",
    "B": "low",
    "C": "substantial",
    "D": "substantial",
    "E": "high",
}


def map_eidas_assurance(value: str) -> str:
    """Translate connector letter codes, preserving other assurance values."""
    return EIDAS_ASSURANCE_MAPPING.get(value, value)
