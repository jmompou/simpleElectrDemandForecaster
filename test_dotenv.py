import os
from dotenv import load_dotenv
load_dotenv()
print("RUTA_BASE:", os.getenv("RUTA_BASE", os.path.dirname(os.path.abspath(__file__))))
