"""
``esios_request`` exceptions.

Hierarchy (all inherit from ``EsiosError``)::

    EsiosError
    ├── EsiosConfigError (ValueError)       missing token, invalid dates…
    ├── EsiosSchemaError (ValueError)       the API returned an unexpected format
    └── EsiosHTTPError (requests.HTTPError) HTTP error response
        ├── EsiosAuthError                  401 / 403
        ├── EsiosNotFound                   404
        └── EsiosRateLimited                429 (after retries are exhausted)

They also inherit from ``ValueError`` / ``requests.HTTPError`` so that code which already caught
those exceptions (v1.1.x) keeps working.
"""

import requests


class EsiosError(Exception):
    """Base class for all the library's exceptions."""


class EsiosConfigError(EsiosError, ValueError):
    """Invalid or incomplete input parameters (token, dates…)."""


class EsiosSchemaError(EsiosError, ValueError):
    """The API response does not have the expected format."""


class EsiosHTTPError(requests.HTTPError, EsiosError):
    """The API answered with an HTTP error status. ``.response`` holds the response."""


class EsiosAuthError(EsiosHTTPError):
    """401/403: invalid or expired token, or insufficient permissions."""


class EsiosNotFound(EsiosHTTPError):
    """404: the indicator or archive does not exist."""


class EsiosRateLimited(EsiosHTTPError):
    """429: too many requests (retries have been exhausted)."""
