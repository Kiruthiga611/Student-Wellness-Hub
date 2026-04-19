"""Debug-session NDJSON logger (workspace root: debug-7e5c21.log)."""
import json
import time
from pathlib import Path

_SESSION_ID = "7e5c21"
# mindset_api -> mental_health_backend -> workspace root
_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "debug-7e5c21.log"


def debug_session_log(hypothesis_id, location, message, data=None, exc=None):
    # #region agent log
    payload = {
        "sessionId": _SESSION_ID,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
    }
    if exc is not None:
        import traceback

        payload["data"]["exc_type"] = type(exc).__name__
        payload["data"]["exc_str"] = str(exc)[:800]
        payload["data"]["traceback"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )[-4500:]
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass
    # #endregion
