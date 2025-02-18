# gizwits_lan/errors.py

class GizwitsError(Exception):
    """Base exception class for all Gizwits LAN protocol errors."""

class ProtocolError(GizwitsError):
    """Raised when protocol parsing fails or unexpected responses received."""

class PasscodeError(GizwitsError):
    """
    Raised during connection when device is not in binding mode.
    """

class LoginError(GizwitsError):
    """Raised when login handshake fails after receiving passcode."""
