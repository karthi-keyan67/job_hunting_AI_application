import enum


class JobSourceStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"


class ApplicationStatus(str, enum.Enum):
    SAVED = "SAVED"
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED = "APPROVED"
    PREPARING = "PREPARING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_TO_APPLY = "READY_TO_APPLY"
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    ON_HOLD = "ON_HOLD"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    ACCEPTED = "ACCEPTED"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SAVED = "SAVED"


class ApprovalType(str, enum.Enum):
    RESUME = "RESUME"
    COVER_LETTER = "COVER_LETTER"
    ANSWERS = "ANSWERS"
    FINAL = "FINAL"


class RunStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ResumeParsingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_OCR = "NEEDS_OCR"
