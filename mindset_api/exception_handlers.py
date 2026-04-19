"""DRF exception handler: logs unexpected failures and returns JSON for non-DRF exceptions (avoids bare 500 HTML)."""
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .debug_session_log import debug_session_log


def debug_aware_exception_handler(exc, context):
    # #region agent log
    if isinstance(exc, APIException):
        code = getattr(exc, "status_code", 500)
        if code < 500:
            return drf_exception_handler(exc, context)
    request = context.get("request")
    view = context.get("view")
    view_name = view.__class__.__name__ if view is not None else None
    action = getattr(view, "action", None) if view is not None else None
    debug_session_log(
        "H_DRF_HANDLER",
        f"{view_name}.{action}",
        type(exc).__name__,
        data={
            "path": getattr(request, "path", None) if request else None,
            "method": getattr(request, "method", None) if request else None,
            "view": view_name,
            "action": action,
        },
        exc=exc,
    )
    # #endregion
    response = drf_exception_handler(exc, context)
    if response is None:
        payload = {"error": "internal_server_error", "message": "An unexpected error occurred."}
        if settings.DEBUG:
            payload["detail"] = str(exc)
            payload["exception"] = type(exc).__name__
        return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return response
