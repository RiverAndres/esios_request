import requests
import requests_cache

_cached_session = requests_cache.CachedSession(
    cache_name = "esios_req_cache",
    expire_after = 86400,
    ignored_parameters = ["x-api-key"],
    use_temp = True,
)

def get_session(use_cache = False) -> requests.sessions.Session | requests_cache.CachedSession:
    """
    Return the session to make requests, with cache optional.
    """

    if use_cache:
        return _cached_session
    return requests.sessions.Session()