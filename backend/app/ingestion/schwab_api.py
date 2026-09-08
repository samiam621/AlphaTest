import requests
import os
from backend.app.config import ALPHA_VANTAGE_KEY
#switching to schwab since alpha vantage free api is too limited

#fetch data using api


base_url = 'https://www.alphavantage.co/query'


def get_OHLCV_daily():
    #OHLCV fetch
    response = requests.get(f"{base_url}", params={"function": "TIME_SERIES_DAILY",
            "outputsize":"compact",
            "datatype":"json",
            "api_key":ALPHA_VANTAGE_KEY
            })
    response.raise_for_status()

    #response is json by default
    data= response