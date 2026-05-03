import requests
import requests_cache
import pandas as pd

from datetime import datetime, UTC, timedelta
from dateutil.relativedelta import relativedelta
from .indicators import common_indicators, common_archives
from .req_cache import get_session


def esios_get_request(
    token:str,
    url:str,
    headers:dict,
    params:dict,
    session:requests.sessions.Session | requests_cache.CachedSession = requests.sessions.Session(),
    max_cache_entries: int | None = 100,
    ) -> requests.Response:
    """
    Get request with token type ``x-api-key``.

    Returns
    -----
    ``object`` requests.get.response
    """

    headers["x-api-key"] = token
    
    response = session.get(url = url, headers = headers, params = params, timeout = (5, 180))
    return response

def esios_get_indicator(
    token:str,
    id:str,
    params:dict,
    headers:dict = {
        "Accept":"application/json; application/vnd.esios-api-v1+json",
        "Content-Type":"application/json",
        "User-Agent": "PostmanRuntime/7.39.1",
        },
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios indicator by specifiying the ``id``:``int``.
    The function can handle time intervals of any size.

    Parameters
    -----
    - ``token``:str --> 
    - ``id``:str -->
    - ``params``: dict --> Params must contyain at least: {"start_date": "%Y/%m/%dT%H:%M:%SZ", "end_date": "%Y/%m/%dT%H:%M:%SZ"}
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent".
    - ``use_cache``: bool --> By default "False". Uses the module requests_cache to store the request an avoid doing the same GET request.
    Returns
    -----
    ``pd.DataFrame`` containing the values of the id specified.
    """

    session = get_session(use_cache)
    indicator = common_indicators(id)
    endpoint = f"https://api.esios.ree.es/indicators/{str(indicator)}"
    fmt = "%Y/%m/%dT%H:%M:%SZ"
    start_date = datetime.strptime(params.get("start_date"), fmt)
    end_date = datetime.strptime(params.get("end_date"), fmt)
    start_interval_date = start_date
    df = pd.DataFrame()

    while start_interval_date < end_date:
        end_interval_date = start_interval_date + relativedelta(months = 6)
        if end_interval_date > end_date:
            end_interval_date = end_date

        params.update({"start_date": start_interval_date.strftime(fmt), "end_date": end_interval_date.strftime(fmt)})
        res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = params)
        res.raise_for_status()
        try:
            dfs = pd.DataFrame(res.json()["indicator"]["values"]).set_index("datetime_utc")
            dfs.index = pd.to_datetime(dfs.index)
        except:
            dfs = pd.DataFrame()
        df = pd.concat([df, dfs])

        start_interval_date = end_interval_date

    df = df[~df.index.duplicated(keep="first")]

    return df

def esios_get_archive(
    token:str,
    id:str,
    params:dict = {},
    headers:dict = {
        "Accept":"application/json; application/vnd.esios-api-v1+json",
        "Content-Type":"application/json",
        "User-Agent": "PostmanRuntime/7.39.1",
        },
    use_cache: bool = False,
    ) -> pd.DataFrame:
    """
    Get request to an e·sios archive by specifiying the ``id``:``int``.

    Parameters
    -----
    - ``token``:str --> 
    - ``id``:str -->
    - ``params``: dict --> Params must contyain at least: {"start_date": "%Y/%m/%dT%H:%M:%SZ", "end_date": "%Y/%m/%dT%H:%M:%SZ"}
    - ``headers``: dict --> By default contains "Accept", "Content-Type", & "User-Agent".

    Returns
    -----
    ``pd.DataFrame`` containing the values of the id specified.
    """

    session = get_session(use_cache)
    archive = common_archives(id)
    endpoint = f"https://api.esios.ree.es/archives/{str(archive)}/download_json"
    df = pd.DataFrame()

    res = esios_get_request(session = session, token = token, url = endpoint, headers = headers, params = params)
    res.raise_for_status()
    try:
        df = pd.DataFrame(next(iter(res.json().values())))
    except:
        df = pd.DataFrame()

    return df