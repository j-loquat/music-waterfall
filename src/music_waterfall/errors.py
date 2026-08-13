"""Application-specific exceptions with user-facing messages."""


class MusicWaterfallError(RuntimeError):
    """Base exception for an actionable Music Waterfall failure."""


class ValidationError(MusicWaterfallError):
    """Raised when input or saved state is invalid."""


class ToolUnavailableError(MusicWaterfallError):
    """Raised when a required local executable cannot be found."""


class ReviewRequiredError(MusicWaterfallError):
    """Raised when PDF-derived music has not been explicitly reviewed."""


class ExternalToolError(MusicWaterfallError):
    """Raised when a local external process fails."""
