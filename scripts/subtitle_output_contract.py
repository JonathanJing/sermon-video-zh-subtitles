"""Validate model cue identity before merging or publishing subtitle output."""

from typing import Any


def cue_coverage(expected: list[dict[str, Any]], returned: list[dict[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous output; retain missing cues as recoverable partial work."""
    def cue_ids(rows):
        result = []
        for row in rows:
            value = row.get("id") if isinstance(row, dict) else None
            if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
                raise ValueError("Subtitle cue id is missing or invalid")
            result.append(str(value))
        if len(set(result)) != len(result):
            raise ValueError("Duplicate subtitle cue ids")
        return result

    expected_ids, returned_ids = cue_ids(expected), cue_ids(returned)
    if set(returned_ids) - set(expected_ids):
        raise ValueError("Unexpected subtitle cue ids")
    for row in returned:
        if not isinstance(row.get("zh"), str) or not row["zh"].strip():
            raise ValueError("Empty subtitle translation")
    missing = [cue_id for cue_id in expected_ids if cue_id not in set(returned_ids)]
    return {"complete": bool(expected_ids) and not missing,
            "expectedCount": len(expected_ids), "returnedCount": len(returned_ids),
            "missingIds": missing}
