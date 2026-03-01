"""
Helper HTTP centralizado con reintentos y backoff exponencial.

Todos los scrapers del proyecto usan este modulo en vez de hacer
requests.get() directamente, para obtener reintentos automaticos
ante errores transitorios (timeouts, 503, etc.).
"""

import time

import requests
from bs4 import BeautifulSoup

ERRORES_REINTENTABLES = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)

CODIGOS_REINTENTABLES = {429, 500, 502, 503, 504}


def _hacer_request(url, headers, timeout=15, max_reintentos=3, params=None):
    """
    GET con reintentos y backoff exponencial.

    Retorna el objeto Response o None si todos los intentos fallaron.
    """
    for intento in range(max_reintentos):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, params=params)
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
