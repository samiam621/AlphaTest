from google import generativeai
from google.generativeai import types
from config import GEMINI_API_KEY



#ai will summarize backetesting performance

client=generativeai.Client(api_key=GEMINI_API_KEY)