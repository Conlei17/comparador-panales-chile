"""
Scraper para Pañales Tin Tin (https://www.panalestintin.cl)
Extrae productos de panales de las categorias de panales y calzones/pants.

Pañales Tin Tin usa WooCommerce. Los productos se listan en:
  /categoria-producto/bebes-y-ninos/panales-bebes-y-ninos/
  /categoria-producto/bebes-y-ninos/calzones-pants/
con paginacion WooCommerce: /page/2/, /page/3/, etc.

Estructura HTML clave (WooCommerce):
  - li.wc-block-product     -> contenedor de cada producto
  - h3 a                    -> nombre y link del producto
  - ins .woocommerce-Price-amount bdi -> precio con descuento
  - .woocommerce-Price-amount bdi     -> precio sin descuento
"""

import csv
import os
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup

try:
    from scrapers.http_utils import obtener_pagina
except ImportError:
    from http_utils import obtener_pagina

try:
    from scrapers.common import (limpiar_precio, extraer_marca, extraer_cantidad,
                                  calcular_precio_por_unidad, guardar_csv)
except ImportError:
    from common import (limpiar_precio, extraer_marca, extraer_cantidad,
                        calcular_precio_por_unidad, guardar_csv)

# --- CONFIGURACION ---

CATEGORIAS = [
    {
        "nombre": "Pañales Bebés y Niños",
        "url": "https://www.panalestintin.cl/categoria-producto/bebes-y-ninos/panales-bebes-y-ninos/",
    },
    {
        "nombre": "Calzones Pants",
        "url": "https://www.panalestintin.cl/categoria-producto/bebes-y-ninos/calzones-pants/",
    },
    {
        "nombre": "Toallas Húmedas",
        "url": "https://www.panalestintin.cl/categoria-producto/bebes-y-ninos/toallas-humedas/",
    },
]

CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")
ARCHIVO_SALIDA = "tintin_precios.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}

TIMEOUT = 15
PAUSA_ENTRE_PAGINAS = 2




def detectar_total_paginas(soup):
    """
    Detecta cuantas paginas hay en WooCommerce.
    Busca links de paginacion con /page/N/.
    """
    max_pagina = 1
    links_pagina = soup.select('a.page-numbers, a[href*="/page/"]')
    for link in links_pagina:
        href = link.get("href", "")
        match = re.search(r"/page/(\d+)/", href)
        if match:
            numero = int(match.group(1))
            if numero > max_pagina:
                max_pagina = numero
    return max_pagina


def extraer_productos(soup):
    """Extrae la informacion de todos los productos de una pagina WooCommerce."""
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # WooCommerce usa li.product o li.wc-block-product
    bloques = soup.select("li.wc-block-product")
    if not bloques:
        bloques = soup.select("li.product")
    if not bloques:
        bloques = soup.select(".wc-block-grid__product")

    if not bloques:
        print("  AVISO: No se encontraron productos en esta pagina.")
        return productos

    for bloque in bloques:
        try:
            # --- NOMBRE Y URL ---
            nombre_elem = bloque.select_one("h3 a")
            if not nombre_elem:
                nombre_elem = bloque.select_one("h2 a")
            if not nombre_elem:
                nombre_elem = bloque.select_one(".wc-block-grid__product-title a")
            if not nombre_elem:
                continue

            nombre = nombre_elem.get_text(strip=True)
            if not nombre or len(nombre) < 3:
                continue

            url = nombre_elem.get("href", "")

            # --- MARCA ---
            marca = extraer_marca(nombre)

            # --- PRECIO ---
            precio = None

            # Precio con descuento (dentro de <ins>)
            precio_ins = bloque.select_one("ins .woocommerce-Price-amount bdi")
            if precio_ins:
                precio = limpiar_precio(precio_ins.get_text())

            # Si no hay descuento, tomar el precio normal
            if not precio:
                precio_elem = bloque.select_one(".woocommerce-Price-amount bdi")
                if precio_elem:
                    precio = limpiar_precio(precio_elem.get_text())

            # Fallback: buscar cualquier precio en el bloque
            if not precio:
                precio_elem = bloque.select_one(".price")
                if precio_elem:
                    precio = limpiar_precio(precio_elem.get_text())

            # --- CANTIDAD ---
            cantidad = extraer_cantidad(nombre)

            # --- PRECIO POR UNIDAD ---
            precio_por_unidad = calcular_precio_por_unidad(precio, cantidad, nombre)

            # --- IMAGEN ---
            img_elem = bloque.select_one("img")
            imagen = img_elem.get("src") or img_elem.get("data-src") if img_elem else None

            producto = {
                "nombre": nombre,
                "precio": precio,
                "marca": marca,
                "cantidad_unidades": cantidad,
                "precio_por_unidad": precio_por_unidad,
                "imagen": imagen,
                "precio_lista": None,
                "url": url,
                "tienda": "Pañales Tin Tin",
                "fecha_extraccion": timestamp,
                "en_stock": 1,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def scrapear_categoria(nombre_categoria, url_base):
    """Scrapea todas las paginas de una categoria WooCommerce."""
    print(f"\n{'─' * 50}")
    print(f"Categoria: {nombre_categoria}")
    print(f"URL: {url_base}")
    print(f"{'─' * 50}")

    soup_primera = obtener_pagina(url_base, HEADERS, TIMEOUT)
    if not soup_primera:
        print(f"  ERROR: No se pudo descargar {nombre_categoria}. Saltando...")
        return []

    total_paginas = detectar_total_paginas(soup_primera)
    print(f"  Paginas detectadas: {total_paginas}")

    todos_los_productos = []

    for num_pagina in range(1, total_paginas + 1):
        print(f"\n  --- Pagina {num_pagina} de {total_paginas} ---")

        if num_pagina == 1:
            soup = soup_primera
        else:
            # WooCommerce usa /page/N/ en la URL
            url_pagina = f"{url_base}page/{num_pagina}/"
            soup = obtener_pagina(url_pagina, HEADERS, TIMEOUT)
            if not soup:
                print(f"  No se pudo descargar pagina {num_pagina}. Continuando...")
                continue

        productos_pagina = extraer_productos(soup)
        print(f"  Productos encontrados: {len(productos_pagina)}")
        todos_los_productos.extend(productos_pagina)

        if num_pagina < total_paginas:
            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

    return todos_los_productos


def main():
    """Funcion principal que ejecuta el scraping de Pañales Tin Tin."""
    print("=" * 60)
    print("SCRAPER PAÑALES TIN TIN - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    todos_los_productos = []

    for categoria in CATEGORIAS:
        productos = scrapear_categoria(categoria["nombre"], categoria["url"])
        todos_los_productos.extend(productos)

    print(f"\n\nTotal de productos extraidos: {len(todos_los_productos)}")

    # Guardar en CSV
    print("\nGuardando datos en CSV...")
    ruta_csv = os.path.join(CARPETA_DATOS, ARCHIVO_SALIDA)
    guardar_csv(todos_los_productos, ruta_csv)

    # Resumen final
    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Productos totales: {len(todos_los_productos)}")

    con_precio = sum(1 for p in todos_los_productos if p["precio"] is not None)
    print(f"Con precio: {con_precio}")
    print(f"Sin precio: {len(todos_los_productos) - con_precio}")

    con_cantidad = sum(1 for p in todos_los_productos if p["cantidad_unidades"] is not None)
    print(f"Con cantidad: {con_cantidad}")

    marcas = set(p["marca"] for p in todos_los_productos if p["marca"])
    print(f"Marcas encontradas: {', '.join(sorted(marcas))}")

    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
