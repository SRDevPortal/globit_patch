from __future__ import annotations


class SyncError(Exception):
	def __init__(
		self,
		message: str,
		*,
		code: str = "SYNC_ERROR",
		http_status: int = 422,
		requires_manual_review: bool = False,
	):
		super().__init__(message)
		self.message = message
		self.code = code
		self.http_status = http_status
		self.requires_manual_review = requires_manual_review


class ContractError(SyncError):
	def __init__(self, message: str, *, code: str = "INVALID_PAYLOAD"):
		super().__init__(message, code=code, http_status=422)


class SecurityError(SyncError):
	def __init__(self, message: str, *, code: str = "INVALID_SIGNATURE", http_status: int = 401):
		super().__init__(message, code=code, http_status=http_status)


class PatientIdentityConflict(SyncError):
	def __init__(self, message: str = "The patient identity is ambiguous on the destination site."):
		super().__init__(
			message,
			code="PATIENT_IDENTITY_CONFLICT",
			http_status=409,
			requires_manual_review=True,
		)


class SyncConflict(SyncError):
	def __init__(self, message: str, *, code: str):
		super().__init__(message, code=code, http_status=409, requires_manual_review=True)
