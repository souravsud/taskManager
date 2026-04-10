from enum import Enum


class MeshStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    DONE = "DONE"
    FAILED = "FAILED"
    ERROR = "ERROR"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    NO_JOB_ID = "NO_JOB_ID"
