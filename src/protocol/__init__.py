"""Shared protocol definitions for agent-runner communication."""

from src.protocol.schema import (
    DEFAULT_REQUESTS_DIR,
    STATUS_BUILDING,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    StatusLiteral,
    TestRequest,
    extract_metric,
    request_fields,
    validate_status,
    validate_transition,
)

__all__ = [
    "DEFAULT_REQUESTS_DIR",
    "STATUS_BUILDING",
    "STATUS_CLAIMED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "VALID_STATUSES",
    "VALID_TRANSITIONS",
    "StatusLiteral",
    "TestRequest",
    "extract_metric",
    "request_fields",
    "validate_status",
    "validate_transition",
]
