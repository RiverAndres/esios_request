import requests
import requests_cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Status codes that are retried: rate limiting and transient server errors.
RETRY_STATUSES = (429, 500, 502, 503, 504)


def make_retry() -> Retry:
    """
    Retry policy: up to 5 retries with exponential backoff (waits of 0, 2, 4, 8 and 16 s; max. 60 s),
    GET only, honouring the API's ``Retry-After`` header. When retries are exhausted the last
    response is returned (``raise_on_status=False``) so the library can raise its own exception.
    """
    return Retry(
        total = 5,
        connect = 3,
        read = 3,
        status = 5,
        backoff_factor = 1,
        backoff_max = 60,
        status_forcelist = RETRY_STATUSES,
        allowed_methods = frozenset({"GET"}),
        respect_retry_after_header = True,
        raise_on_status = False,
    )


def mount_retries(session:requests.Session) -> requests.Session:
    """Mount an ``HTTPAdapter`` with the retry policy on ``session``."""
    adapter = HTTPAdapter(max_retries = make_retry())
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_cached_session = mount_retries(requests_cache.CachedSession(
    cache_name = "esios_req_cache",
    expire_after = 86400,
    ignored_parameters = ["x-api-key"],
    use_temp = True,
))


def get_session(use_cache:bool = False) -> requests.Session | requests_cache.CachedSession:
    """
    Return the session to make requests (with retries), with cache optional.
    """

    if use_cache:
        return _cached_session
    return mount_retries(requests.Session())
