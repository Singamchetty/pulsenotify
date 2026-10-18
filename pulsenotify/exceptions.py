import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """DRF handles known API errors; anything else returns a generic 500 and logs the detail."""
    response = exception_handler(exc, context)
    if response is None:
        logger.exception('Unhandled error in %s', context['view'].__class__.__name__)
        return Response(
            {'detail': 'Internal server error.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return response
