"""Exception types and the mapping from response status to them."""

from __future__ import annotations

from portable.ccapi.vocabulary import ErrorBody


class CcapiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class LinkError(CcapiError): ...


class NotConnectedError(LinkError): ...


class UnreachableError(LinkError): ...


class NotActivatedError(LinkError): ...


class UnacceptableVersionError(LinkError): ...


class ProtocolError(CcapiError): ...


class InvalidRequestError(ProtocolError): ...


class AuthenticationError(ProtocolError): ...


class ForbiddenError(ProtocolError): ...


class FeatureMissingError(ProtocolError): ...


class MethodNotAllowedError(ProtocolError): ...


class StorageError(ProtocolError): ...


class RangeError(ProtocolError): ...


class DeviceError(CcapiError): ...


class DeviceBusyError(DeviceError): ...


class InvalidStateError(DeviceError): ...


class ShootingError(DeviceError): ...


DEVICE_BUSY = "Device busy"
DURING_SHOOTING = "During shooting or recording"
TAKEN_IN_PREPARATION = "Taken in preparation"
MODE_NOT_SUPPORTED = "Mode not supported"
LIVE_VIEW_NOT_STARTED = "Live view not started"
ALREADY_STARTED = "Already started"
NOT_STARTED = "Not started"
OUT_OF_FOCUS = "Out of focus"
CANNOT_WRITE = "Can not write to card"
CARD_NOT_AVAILABLE = "Card not available"
CARD_PROTECTED = "Card protected"
FILE_PROTECTED = "File protected"

CLEARS_ON_ITS_OWN = frozenset({DEVICE_BUSY, DURING_SHOOTING, TAKEN_IN_PREPARATION})

SHOOTING_FAILURES = frozenset({OUT_OF_FOCUS, CANNOT_WRITE})

STORAGE_REFUSALS = frozenset({CARD_NOT_AVAILABLE, CARD_PROTECTED, FILE_PROTECTED})

BY_STATUS: dict[int, type[CcapiError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: FeatureMissingError,
    405: MethodNotAllowedError,
    409: StorageError,
    416: RangeError,
}


def error_for(status: int, body: ErrorBody | None) -> CcapiError:
    message = body.message if body is not None else ""
    text = f"{status}: {message}" if message else str(status)
    if status == 503:
        return _refusal(message, text)
    kind = BY_STATUS.get(status, ProtocolError if status < 500 else DeviceError)
    return kind(text, status)


def _refusal(message: str, text: str) -> CcapiError:
    if message in CLEARS_ON_ITS_OWN:
        return DeviceBusyError(text, 503)
    if message in SHOOTING_FAILURES:
        return ShootingError(text, 503)
    if message in STORAGE_REFUSALS:
        return StorageError(text, 503)
    return InvalidStateError(text, 503)


def worth_retrying(exc: BaseException) -> bool:
    return isinstance(exc, DeviceBusyError)
