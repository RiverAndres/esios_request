import logging

from .esios_request import esios_get_archive, esios_get_indicator
from .exceptions import (
    EsiosAuthError,
    EsiosConfigError,
    EsiosError,
    EsiosHTTPError,
    EsiosNotFound,
    EsiosRateLimited,
    EsiosSchemaError,
)

__version__ = "1.2.0"

# No output by default: users decide whether to configure the "esios_request" logger.
logging.getLogger("esios_request").addHandler(logging.NullHandler())

__all__ = [
    "EsiosAuthError",
    "EsiosConfigError",
    "EsiosError",
    "EsiosHTTPError",
    "EsiosNotFound",
    "EsiosRateLimited",
    "EsiosSchemaError",
    "__version__",
    "esios_get_archive",
    "esios_get_indicator",
    ]
