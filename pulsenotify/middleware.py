import logging
import time

logger = logging.getLogger('pulsenotify.requests')


class RequestLoggingMiddleware:
    """Logs method, path, status and duration only; never bodies, headers or query strings."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        logger.info(
            '%s %s -> %s (%.0f ms)',
            request.method, request.path, response.status_code,
            (time.monotonic() - start) * 1000,
        )
        return response
