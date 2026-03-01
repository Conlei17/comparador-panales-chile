"""
Helper HTTP centralizado con reintentos y backoff exponencial.

Todos los scrapers del proyecto usan este modulo en vez de hacer
requests.get() directamente, para obtener reintentos automaticos
ante errores transitorios (timeouts, 503, etc.).
"""

import random
import time

import requests
from bs4 import BeautifulSoup

ERRORES_REINTENTABLES = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)

CODIGOS_REINTENTABLES = {429, 500, 502, 503, 504}

# Pool de User-Agents reales para rotar entre requests.
# Evita fingerprinting por UA estatico.
_USER_AGENTS = [
    # Chrome 120 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome 122 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome 123 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome 124 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 125 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox 124 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox 125 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Safari 17 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    # Edge 122 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    # Chrome 124 – Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _hacer_request(url, headers, timeout=15, max_reintentos=3, params=None):
    """
    GET con reintentos y backoff exponencial.
    Rota el User-Agent en cada intento.

    Retorna el objeto Response o None si todos los intentos fallaron.
    """
    for intento in range(max_reintentos):
        try:
            # Copiar headers y rotar User-Agent
            h = dict(headers) if headers else {}
            h["User-Agent"] = random.choice(_USER_AGENTS)
            resp = requests.get(url, headers=h, timeout=timeout, params=params)
            if resp.status_code in CODIGOS_REINTENTABLES:
                espera = 2 ** (intento + 1)
                print(f"  HTTP {resp.status_code}, reintentando en {espera}s...")
                time.sleep(espera)
                continue
            resp.raise_for_status()
            return resp
        except ERRORES_REINTENTABLES as e:
            espera = 2 ** (intento + 1)
            print(f"  {type(e).__name__}, reintentando en {espera}s...")
            time.sleep(espera)
        except requests.exceptions.HTTPError as e:
            print(f"  ERROR HTTP {e.response.status_code} para {url}")
            return None
    print(f"  ERROR: {max_reintentos} reintentos fallidos para {url}")
    return None


def obtener_pagina(url, headers, timeout=15, max_reintentos=3):
    """GET con reintentos. Retorna BeautifulSoup o None."""
    resp = _hacer_request(url, headers, timeout, max_reintentos)
    if resp is None:
        return None
    return BeautifulSoup(resp.text, "lxml")


def obtener_json(url, headers, params=None, timeout=15, max_reintentos=3):
    """GET que retorna JSON con reintentos. Para Cruz Verde y APIs."""
    resp = _hacer_request(url, headers, timeout, max_reintentos, params=params)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError as e:
        print(f"  ERROR parseando JSON de {url}: {e}")
        return None


def obtener_texto(url, headers, timeout=15, max_reintentos=3):
    """GET que retorna texto con reintentos. Para Salcobrand y paginas raw."""
    resp = _hacer_request(url, headers, timeout, max_reintentos)
    if resp is None:
        return None
    return resp.text
