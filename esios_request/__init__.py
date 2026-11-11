import logging

from .client import EsiosClient
from .esios_request import esios_get_archive, esios_get_indicator
from .exceptions import (
    EsiosAuthError,
    EsiosConfigError,
    EsiosError,
    EsiosHTTPError,
    EsiosNotFound,
    EsiosRateLimited,
    EsiosSchemaError,
    EsiosUnknownAlias,
)
from .indicators import archive_catalogue, indicator_catalogue
from .req_cache import clear_cache

__version__ = "1.4.0"

# No output by default: users decide whether to configure the "esios_request" logger.
logging.getLogger("esios_request").addHandler(logging.NullHandler())

__all__ = [
    "EsiosAuthError",
    "EsiosClient",
    "EsiosConfigError",
    "EsiosError",
    "EsiosHTTPError",
    "EsiosNotFound",
    "EsiosRateLimited",
    "EsiosSchemaError",
    "EsiosUnknownAlias",
    "__version__",
    "archive_catalogue",
    "clear_cache",
    "esios_get_archive",
    "esios_get_indicator",
    "indicator_catalogue",
    ]
