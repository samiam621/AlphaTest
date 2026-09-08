import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


ALPHA_VANTAGE_KEY= os.getenv("ALPHA_VANTAGE_KEY")
GEMINI_API_KEY= os.getenv("GEMINI_API_KEY")
