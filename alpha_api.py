import requests
import os


class AlphaVantage: 
    base_url = 'https://www.alphavantage.co'
    def __init__(self):
        self.ALPHA_VANTAGE_KEY= os.getenv("ALPHA_VANTAGE_KEY")
        

