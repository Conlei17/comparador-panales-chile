"""
Configuracion centralizada del proyecto Comparador de Panales Chile.

Todas las constantes, paths y variables de entorno se definen aqui
para evitar hardcodearlas en main.py y app.py.
"""

import os
from pathlib import Path

# --- PATHS ---

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "precios.db"

# --- VALIDACION DE PRECIOS ---

# Rangos razonables para precios (CLP)
PRECIO_MIN = 500
PRECIO_MAX = 200000

# Rangos para precio por unidad (panales)
PPU_MIN = 10
PPU_MAX = 2000

# Rangos para formulas infantiles (precio por kg)
PPU_FORMULA_MIN = 5000
PPU_FORMULA_MAX = 80000

# --- VARIABLES DE ENTORNO ---

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "Conlei17/comparador-panales-chile"
GITHUB_ALERTAS_PATH = "data/alertas.db"
MONITOR_EMAIL = os.getenv("MONITOR_EMAIL", "")

# --- URLs ---

BASE_URL = os.getenv("BASE_URL", "https://babyahorro.cl")
PRECIOS_DB_URL = "https://raw.githubusercontent.com/Conlei17/comparador-panales-chile/data/data/precios.db"
ALERTAS_DB_URL = "https://raw.githubusercontent.com/Conlei17/comparador-panales-chile/data/data/alertas.db"

# --- INTERVALOS ---

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "14400"))  # 4 horas

# --- MONITOREO ---

# Umbral para alertar caida de productos (50% del promedio historico)
UMBRAL_ALERTA_PRODUCTOS = 0.5
ARCHIVO_LOG_MONITOREO = str(DATA_DIR / "monitoreo_scrapers.log")
