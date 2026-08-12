"""Shared safety primitives for remote metadata synchronization."""

from .budget import BudgetExhausted, BudgetTracker, SyncLimits
from .credentials import EnvironmentCredentialResolver, SecretValue
from .executor import (
    BoundedRemoteExecutor,
    PageCommitter,
    RemoteExecutionResult,
    ResponseRetainer,
    RetainedPage,
)
from .request_gate import RequestGate, sanitize_transport_error, semantic_request_identity
from .service import MetadataSyncService, SyncResult

__all__ = [
    "BoundedRemoteExecutor",
    "BudgetExhausted",
    "BudgetTracker",
    "EnvironmentCredentialResolver",
    "MetadataSyncService",
    "PageCommitter",
    "RemoteExecutionResult",
    "RequestGate",
    "ResponseRetainer",
    "RetainedPage",
    "SecretValue",
    "SyncLimits",
    "SyncResult",
    "sanitize_transport_error",
    "semantic_request_identity",
]
