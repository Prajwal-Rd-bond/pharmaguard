"""
Typed errors for the ML service.

Every error carries a stable machine-readable `code` and a `public_message` that is safe to
return to callers. Neither may contain patient text, prompts, model output, or credentials.
"""


class PharmaGuardError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500
    public_message = "Internal error"

    def __init__(self, public_message: str | None = None):
        if public_message:
            self.public_message = public_message
        super().__init__(self.public_message)


class ConfigError(PharmaGuardError):
    code = "CONFIG_ERROR"
    public_message = "Service configuration is invalid"


class DeidentificationError(PharmaGuardError):
    code = "DEID_FAILED"
    public_message = "De-identification could not be completed; nothing was sent to external services"


class PrivacyViolation(PharmaGuardError):
    """Raised when text that has not passed the de-identification boundary is about to leave the service."""

    code = "PRIVACY_BLOCKED"
    public_message = "Outgoing request blocked by the privacy boundary"


class LLMUnavailable(PharmaGuardError):
    code = "LLM_UNAVAILABLE"
    http_status = 503
    public_message = "Language model is unavailable"


class LLMResponseError(PharmaGuardError):
    code = "LLM_BAD_RESPONSE"
    http_status = 502
    public_message = "Language model returned an invalid response"


class ExternalServiceError(PharmaGuardError):
    code = "EXTERNAL_SERVICE_ERROR"
    http_status = 502
    public_message = "An external service request failed"

    def __init__(self, service: str, public_message: str | None = None):
        self.service = service
        super().__init__(public_message or f"{service} request failed")


class EvidenceStoreError(PharmaGuardError):
    code = "EVIDENCE_STORE_ERROR"
    http_status = 503
    public_message = "Evidence store is unavailable"

