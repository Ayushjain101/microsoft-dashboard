"""Application exception hierarchy."""


class AppError(Exception):
    """Base application error."""
    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class WorkflowError(AppError):
    """Workflow execution error."""
    pass


class StepError(AppError):
    """Individual step execution error."""
    def __init__(self, message: str, step_index: int, step_name: str, detail: str | None = None, retryable: bool = True):
        self.step_index = step_index
        self.step_name = step_name
        self.retryable = retryable
        super().__init__(message, detail)


class StepPreconditionError(StepError):
    """Step precondition not met."""
    def __init__(self, message: str, step_index: int, step_name: str):
        super().__init__(message, step_index, step_name, retryable=False)


class LockError(AppError):
    """Failed to acquire distributed lock."""
    pass


class IdempotencyError(AppError):
    """Operation already completed (idempotent guard)."""
    pass


class PowerShellError(AppError):
    """PowerShell execution error."""
    def __init__(self, message: str, stdout: str = "", stderr: str = "", exit_code: int | None = None):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        super().__init__(message)


class GraphAPIError(AppError):
    """Microsoft Graph API error."""
    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class CloudflareError(AppError):
    """Cloudflare API error."""
    pass


class TenantNotFoundError(AppError):
    """Tenant not found in database."""
    pass


class JobNotFoundError(AppError):
    """Workflow job not found."""
    pass


class InvalidStateTransition(AppError):
    """Invalid workflow state transition."""
    def __init__(self, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Cannot transition from '{current_status}' to '{target_status}'")
