"""Validation adapter between immutable application state and LangGraph state."""

from __future__ import annotations

from pydantic import ValidationError

from app.schemas.assessment_state import AssessmentState


class AssessmentGraphValidationError(ValueError):
    """Raised when graph input is not a valid AssessmentState snapshot."""


def validate_assessment_state(value: object) -> AssessmentState:
    """Revalidate an input snapshot, including models built without validation."""
    raw_value = value.model_dump(mode="python") if isinstance(value, AssessmentState) else value
    try:
        return AssessmentState.model_validate(raw_value)
    except ValidationError as exc:
        raise AssessmentGraphValidationError(
            "assessment graph requires a valid AssessmentState"
        ) from exc
