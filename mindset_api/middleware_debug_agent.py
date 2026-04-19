"""Logs unhandled exceptions that reach Django middleware (non-DRF or outside DRF handler)."""
from django.core.exceptions import DisallowedHost

from .debug_session_log import debug_session_log


class DebugAgentExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # #region agent log
        if isinstance(exception, DisallowedHost):
            return None
        debug_session_log(
            "H_MW_PROCESS_EXCEPTION",
            "DebugAgentExceptionMiddleware.process_exception",
            type(exception).__name__,
            data={"path": getattr(request, "path", None)},
            exc=exception,
        )
        # #endregion
        return None
