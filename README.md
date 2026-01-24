# esios_request

Easily obtain data published by REE in its public ESIOS API as a pandas.DataFrame.

This module was created mainly to obtain time series, there are features and endpoints that are not included in this version. They will be added as needed.

The data is obtained by calling one of the following functions:
```bash
esios_get_indicator(
    token:str,
    id:str,
    params:dict,
    headers:dict,
    ) -> pd.DataFrame:

esios_get_archive(
    token:str,
    id:str,
    params:dict,
    headers:dict,
    ) -> pd.DataFrame:
```

## Instalación

```bash
pip install git+https://github.com/RiverAndres/esios_request.git
```
