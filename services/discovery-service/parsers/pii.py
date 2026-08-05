"""
PII anonymization utilities for the Discovery Service.

Replaces PII field values with SHA-256 hex digests before persistence,
ensuring plaintext PII never reaches the database.
"""

import hashlib
from typing import Any


def anonymize_pii_fields(data: dict[str, Any], pii_fields: list[str]) -> dict[str, Any]:
    """
    Anonymize PII fields in a dictionary by replacing values with SHA-256 hashes.

    For each key in *pii_fields* that is present in *data*, the corresponding
    value is replaced with ``hashlib.sha256(str(value).encode()).hexdigest()``.
    All other fields are left unchanged.

    Args:
        data: Input dictionary potentially containing PII values.
        pii_fields: List of field names whose values should be anonymized.

    Returns:
        A new dictionary with PII field values replaced by their SHA-256 hex digests.
        Non-PII fields are copied as-is. The original dictionary is not mutated.

    Example::

        >>> anonymize_pii_fields({"email": "alice@example.com", "name": "Alice"}, ["email"])
        {"email": "<sha256-hex>", "name": "Alice"}
    """
    pii_set = set(pii_fields)
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in pii_set:
            result[key] = hashlib.sha256(str(value).encode()).hexdigest()
        else:
            result[key] = value
    return result
