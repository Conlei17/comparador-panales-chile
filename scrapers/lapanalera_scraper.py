"""
Scraper para La Pañalera (https://www.lapanalera.cl)
Extrae productos de panales de la categoria /panales.

La Panalera usa la plataforma Jumpseller (igual que Pepito).
Los productos se listan en:
  https://www.lapanalera.cl/panales
con paginacion: ?page=2, ?page=3, etc.

Estructura HTML clave:
  - .product-block          -> contenedor de cada producto
  - h3 a (dentro de .brand-name) -> nombre del producto
  - span.brand              -> marca
  - span.block-price        -> precio
  - h3 a[href]              -> link al producto
"""

import csv
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# --- CONFIGURACION ---

CATEGORIAS = [
    {
        "nombre": "Pañales",
        "url": "https://www.lapanalera.cl/panales",
    },
]

CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")
ARCHIVO_SALIDA = "lapanalera_precios.csv"

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


def obtener_pagina(url):
    """Descarga el HTML de una URL y lo convierte en BeautifulSoup."""
    try:
        print(f"  Descargando: {url}")
        respuesta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        respuesta.raise_for_status()
        return BeautifulSoup(respuesta.text, "lxml")
    except requests.exceptions.Timeout:
        print(f"  ERROR: Tiempo de espera agotado para {url}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: No se pudo conectar a {url}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  ERROR: Respuesta HTTP {e.response.status_code} para {url}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ERROR inesperado: {e}")
        return None


def detectar_total_paginas(soup):
    """Detecta cuantas paginas de productos hay usando links ?page=N."""
    max_pagina = 1
    links_pagina = soup.select('a[href*="page="]')
    for link in links_pagina:
        href = link.get("href", "")
        match = re.search(r"page=(\d+)", href)
        if match:
            numero = int(match.group(1))
            if numero > max_pagina:
                max_pagina = numero
    return max_pagina


def limpiar_precio(texto_precio):
    """Convierte texto de precio como "$14.990" en entero 14990."""
    if not texto_precio:
        return None
    solo_numeros = re.sub(r"[^\d]", "", texto_precio)
    if solo_numeros:
        return int(solo_numeros)
    return None


def extraer_marca_del_nombre(nombre_producto):
    """Detecta la marca del producto a partir de su nombre."""
    marcas_conocidas = [
        "Pampers", "Huggies", "Babysec", "Cotidian", "Goodnites",
        "Win", "Tutte", "Pequenin", "Tena", "Plenitud",
        "Ladysoft", "Aiwibi", "Emubaby", "Moltex", "Chelino",
        "Bambo", "Pingo", "Naty", "Eco Boom", "Biobaby",
    ]
    nombre_lower = nombre_producto.lower()
    for marca in marcas_conocidas:
        if marca.lower() in nombre_lower:
            return marca
    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def extraer_cantidad_del_nombre(nombre_producto):
    """
    Extrae la cantidad de panales del nombre del producto.

    En La Panalera la cantidad viene directamente en el nombre,
    por ejemplo: "36 unidades", "48 unidades", "70 pañales".
    """
    patrones = [
        r"(\d+)\s*(?:unidades|unid|und)\b",
        r"(\d+)\s*(?:pa[ñn]ales)\b",
        r"x\s*(\d+)\s*(?:un|u)\b",
        r"(\d+)\s*(?:un)\b",
    ]
    for patron in patrones:
        match = re.search(patron, nombre_producto, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def esta_agotado(bloque):
    """Detecta si un producto esta agotado buscando texto 'agotado'."""
    texto = bloque.get_text(separator=" ", strip=True).lower()
    if "agotado" in texto:
        return True
    if not bloque.select_one("form"):
        quick_view = bloque.select_one(".quick-view")
        if quick_view and "agotado" in quick_view.get_text(strip=True).lower():
            return True
    return False


def extraer_productos(soup):
    """Extrae la informacion de todos los productos de una pagina."""
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    bloques = soup.select(".product-block")

    if not bloques:
        print("  AVISO: No se encontraron productos en esta pagina.")
        return productos

    for bloque in bloques:
        try:
            # Excluir productos agotados
            if esta_agotado(bloque):
                continue

            # --- NOMBRE DEL PRODUCTO ---
            nombre_elem = bloque.select_one("h3 a")
            if not nombre_elem:
                nombre_elem = bloque.select_one(".product-block__name")
            if not nombre_elem:
                continue

            nombre = nombre_elem.get_text(strip=True)
            if not nombre or len(nombre) < 3:
                continue

            # --- URL DEL PRODUCTO ---
            href = nombre_elem.get("href", "")
            if href.startswith("/"):
                url = f"https://www.lapanalera.cl{href}"
            else:
                url = href

            # --- MARCA ---
            marca_elem = bloque.select_one("span.brand")
            if not marca_elem:
                marca_elem = bloque.select_one(".product-block__brand")
            if marca_elem:
                marca = marca_elem.get_text(strip=True)
            else:
                marca = extraer_marca_del_nombre(nombre)

            # --- PRECIO ---
            precio = None
            precio_elem = bloque.select_one("span.block-price")
            if precio_elem:
                precio = limpiar_precio(precio_elem.get_text())

            if not precio:
                precio_nuevo = bloque.select_one(".product-block__price--new")
                if precio_nuevo:
                    precio = limpiar_precio(precio_nuevo.get_text())

            if not precio:
                precio_elem2 = bloque.select_one(".product-block__price")
                if precio_elem2:
                    precio = limpiar_precio(precio_elem2.get_text())

            # --- CANTIDAD ---
            cantidad = extraer_cantidad_del_nombre(nombre)

            # --- PRECIO POR UNIDAD ---
            precio_por_unidad = None
            if precio and cantidad and cantidad > 0:
                precio_por_unidad = round(precio / cantidad)

            producto = {
                "nombre": nombre,
                "precio": precio,
                "marca": marca,
                "cantidad_unidades": cantidad,
                "precio_por_unidad": precio_por_unidad,
                "url": url,
                "tienda": "La Pañalera",
                "fecha_extraccion": timestamp,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def guardar_csv(productos, ruta_archivo):
    """Guarda la lista de productos en un archivo CSV."""
    if not productos:
        print("No hay productos para guardar.")
        return

    os.makedirs(os.path.dirname(ruta_archivo), exist_ok=True)

    columnas = [
        "nombre", "precio", "marca", "cantidad_unidades",
        "precio_por_unidad", "url", "tienda", "fecha_extraccion",
    ]

    with open(ruta_archivo, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(productos)

    print(f"\nDatos guardados en: {ruta_archivo}")
    print(f"Total de productos guardados: {len(productos)}")


def scrapear_categoria(nombre_categoria, url_base):
    """Scrapea todas las paginas de una categoria."""
    print(f"\n{'─' * 50}")
    print(f"Categoria: {nombre_categoria}")
    print(f"URL: {url_base}")
    print(f"{'─' * 50}")

    soup_primera = obtener_pagina(url_base)
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
            url_pagina = f"{url_base}?page={num_pagina}"
            soup = obtener_pagina(url_pagina)
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
    """Funcion principal que ejecuta el scraping de La Panalera."""
    print("=" * 60)
    print("SCRAPER LA PAÑALERA - Comparador de Panales Chile")
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
