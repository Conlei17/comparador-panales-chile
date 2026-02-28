"""
Scraper para Farmacias Ahumada (https://www.farmaciasahumada.cl)
Extrae productos de panales de la seccion de panales del sitio.

Farmacias Ahumada usa la plataforma Salesforce Commerce Cloud (Demandware).
Los productos se listan con HTML estatico y paginacion offset-based.

URL: https://www.farmaciasahumada.cl/infantil-y-maternidad/pa-ales.html
API paginacion: /on/demandware.store/Sites-ahumada-cl-Site/default/Search-UpdateGrid
"""

import csv
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# --- CONFIGURACION ---

# Categorias a scrapear (URL + CGID para API Demandware)
CATEGORIAS = [
    {
        "url": "https://www.farmaciasahumada.cl/infantil-y-maternidad/pa-ales.html",
        "cgid": "infantil-y-maternidad-mundo-pa%C3%B1ales",
    },
    {
        "url": "https://www.farmaciasahumada.cl/infantil-y-maternidad/lactancia-y-alimentacion/formulas-infantiles",
        "cgid": "infantil-y-maternidad-lactancia-y-alimentacion-formulas-infantiles",
    },
    {
        "url": "https://www.farmaciasahumada.cl/infantil-y-maternidad/higiene-infantil/toallas-h%C3%BAmedas",
        "cgid": "infantil-y-maternidad-higiene-infantil-toallas-humedas",
    },
]

# URL de la API de paginacion (Demandware Search-UpdateGrid)
URL_API_GRID = (
    "https://www.farmaciasahumada.cl/on/demandware.store/"
    "Sites-ahumada-cl-Site/default/Search-UpdateGrid"
)

# Cantidad de productos por pagina
PRODUCTOS_POR_PAGINA = 24

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "ahumada_precios.csv"

# Headers que simulan un navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Tiempo maximo de espera por cada peticion (en segundos)
TIMEOUT = 20

# Pausa entre peticiones para no sobrecargar el servidor (en segundos)
PAUSA_ENTRE_PAGINAS = 2


def obtener_pagina(url):
    """
    Descarga el HTML de una URL y lo convierte en un objeto BeautifulSoup.

    Retorna:
        BeautifulSoup o None si hubo un error.
    """
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


def obtener_pagina_api(start, cgid):
    """
    Obtiene una pagina de productos usando la API de paginacion de Demandware.

    Args:
        start: offset desde donde empezar (0, 24, 48, ...)
        cgid: categoria ID para la API de Demandware

    Retorna:
        BeautifulSoup o None si hubo un error.
    """
    url = f"{URL_API_GRID}?cgid={cgid}&start={start}&sz={PRODUCTOS_POR_PAGINA}"
    return obtener_pagina(url)


def limpiar_precio(texto_precio):
    """
    Convierte un texto de precio como "$16.690" en un numero entero: 16690.

    Retorna:
        int o None si no se pudo convertir.
    """
    if not texto_precio:
        return None

    solo_numeros = re.sub(r"[^\d]", "", texto_precio)

    if solo_numeros:
        return int(solo_numeros)
    return None


def extraer_marca(nombre_producto):
    """
    Intenta detectar la marca del producto a partir de su nombre.
    """
    marcas_conocidas = [
        "Pampers",
        "Huggies",
        "Babysec",
        "Cotidian",
        "Goodnites",
        "Win",
        "Tutte",
        "Pequenin",
        "Tena",
        "Plenitud",
        "Ladysoft",
        "Aiwibi",
        "Emubaby",
        "Moltex",
        "Chelino",
        "Bambo",
        "Pingo",
        "Naty",
        "Eco Boom",
        "Biobaby",
    ]

    nombre_lower = nombre_producto.lower()
    for marca in marcas_conocidas:
        if marca.lower() in nombre_lower:
            return marca

    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


FORMULAS_KEYWORDS = [
    "fórmula", "formula", "leche infantil", "leche en polvo",
    "nan ", "nido", "similac", "enfamil", "s-26", "s26",
    "alula", "nidal", "nutrilon", "blemil",
]


def es_formula(nombre):
    """Detecta si el producto es una fórmula infantil."""
    nombre_lower = nombre.lower()
    return any(kw in nombre_lower for kw in FORMULAS_KEYWORDS)


def extraer_cantidad(nombre_producto):
    """
    Intenta extraer la cantidad de unidades del nombre del producto.
    Para fórmulas infantiles, extrae el peso en gramos.
    """
    # Para fórmulas: extraer peso en gramos o kilogramos
    if es_formula(nombre_producto):
        match_kg = re.search(r"(\d+(?:[.,]\d+)?)\s*kg\b", nombre_producto, re.IGNORECASE)
        if match_kg:
            return int(float(match_kg.group(1).replace(",", ".")) * 1000)
        match_gramos = re.search(r"(\d+)\s*(?:g|grs|gr|gramos)\b", nombre_producto, re.IGNORECASE)
        if match_gramos:
            return int(match_gramos.group(1))

    patrones = [
        r"(\d+)\s*(?:pa[ñn]ales)\b",
        r"(\d+)\s*(?:unidades|unid|und)\b",
        r"x\s*(\d+)\s*(?:un|u)\b",
        r"(\d+)\s*(?:un)\b",
    ]
    for patron in patrones:
        match = re.search(patron, nombre_producto, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def extraer_precio_por_unidad_texto(texto):
    """
    Extrae el precio por unidad del texto con formato "$ XXX x Unidad".

    Farmacias Ahumada muestra el precio fraccionado con formato:
    "$ 180 x Unidad" o similar.
    """
    if not texto:
        return None

    match = re.search(r"\$\s*([\d.,]+)\s*x\s*(?:unidad|un)\b", texto, re.IGNORECASE)
    if match:
        return limpiar_precio(match.group(1))
    return None


def extraer_productos(soup):
    """
    Extrae la informacion de todos los productos de una pagina.

    Farmacias Ahumada (Demandware) usa estos selectores:
    - Contenedor: .product.product-tile-wrapper con data-pid
    - Nombre: .pdp-link > a
    - Marca: .product-tile-brand .link
    - Precio: .promotion-badge-container (primer div)
    - Precio por unidad: .preccio-fracionado ($ XXX x Unidad)
    - URL: .pdp-link > a[href]

    Retorna:
        Lista de diccionarios, cada uno con los datos de un producto.
    """
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Selector principal del contenedor de producto
    contenedores = soup.select(".product.product-tile-wrapper, .product-tile-wrapper, [data-pid]")

    if not contenedores:
        # Selectores alternativos
        contenedores = soup.select(".product-tile, .product-item, .grid-tile")

    if not contenedores:
        print("  AVISO: No se encontraron contenedores de productos en esta pagina.")
        return productos

    for contenedor in contenedores:
        try:
            # --- NOMBRE DEL PRODUCTO ---
            nombre_elem = contenedor.select_one(".pdp-link > a, .pdp-link a, .product-name a, h3 a")
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else None

            if not nombre or len(nombre) < 3:
                continue

            # --- URL DEL PRODUCTO ---
            url = ""
            link_elem = contenedor.select_one(".pdp-link > a, .pdp-link a, a[href]")
            if link_elem:
                href = link_elem.get("href", "")
                if href.startswith("/"):
                    url = f"https://www.farmaciasahumada.cl{href}"
                elif href.startswith("http"):
                    url = href

            # --- MARCA ---
            marca_elem = contenedor.select_one(
                ".product-tile-brand .link, .product-tile-brand, "
                ".brand, [class*='brand']"
            )
            if marca_elem:
                marca = marca_elem.get_text(strip=True)
            else:
                marca = extraer_marca(nombre)

            # --- PRECIO ---
            precio = None

            # Intentar con promotion-badge-container (primer div con precio)
            precio_container = contenedor.select_one(
                ".promotion-badge-container, .price, .product-price"
            )
            if precio_container:
                # Buscar el primer texto que parezca un precio
                texto_precio = precio_container.get_text()
                match = re.search(r"\$\s*[\d.,]+", texto_precio)
                if match:
                    precio = limpiar_precio(match.group())

            # Fallback: buscar cualquier patron de precio en el contenedor
            if not precio:
                selectores_precio = [
                    ".sales .value",
                    ".price .sales",
                    ".price-sales",
                    "[class*='price']",
                ]
                for selector in selectores_precio:
                    elem = contenedor.select_one(selector)
                    if elem:
                        # Intentar atributo content o data-value primero
                        valor = elem.get("content") or elem.get("data-value") or elem.get_text()
                        precio = limpiar_precio(valor)
                        if precio:
                            break

            if not precio:
                texto_completo = contenedor.get_text()
                match = re.search(r"\$\s*[\d.,]+", texto_completo)
                if match:
                    precio = limpiar_precio(match.group())

            # --- CANTIDAD ---
            cantidad = extraer_cantidad(nombre)

            # --- PRECIO POR UNIDAD ---
            precio_por_unidad = None

            if es_formula(nombre):
                # Para fórmulas: calcular precio por kilo
                if precio and cantidad and cantidad > 0:
                    precio_por_unidad = round(precio / cantidad * 1000)
            else:
                # Intentar extraer del texto de precio fraccionado
                ppu_elem = contenedor.select_one(
                    ".preccio-fracionado, .precio-fraccionado, "
                    "[class*='fracionado'], [class*='fraccionado']"
                )
                if ppu_elem:
                    precio_por_unidad = extraer_precio_por_unidad_texto(ppu_elem.get_text())

                # Si no se encontro el precio por unidad, calcularlo
                if not precio_por_unidad and precio and cantidad and cantidad > 0:
                    precio_por_unidad = round(precio / cantidad)

            # --- IMAGEN ---
            img_elem = contenedor.select_one("img")
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
                "tienda": "Farmacias Ahumada",
                "fecha_extraccion": timestamp,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def detectar_total_paginas(soup):
    """
    Detecta el total de paginas disponibles.

    En Demandware, la paginacion puede indicar el total de productos
    o el total de paginas.
    """
    # Buscar el total de productos mostrado en la pagina
    total_elem = soup.select_one(
        ".result-count, .results-hits, [class*='result-count']"
    )
    if total_elem:
        texto = total_elem.get_text()
        match = re.search(r"(\d+)\s*(?:productos|resultados|items)", texto, re.IGNORECASE)
        if match:
            total_productos = int(match.group(1))
            total_paginas = (total_productos + PRODUCTOS_POR_PAGINA - 1) // PRODUCTOS_POR_PAGINA
            return total_paginas

    # Buscar en links de paginacion
    paginacion = soup.select(
        ".pagination a, nav.pagination a, ul.pagination a, "
        "[class*='paginat'] a, .page-item a"
    )

    max_pagina = 1
    for link in paginacion:
        texto = link.get_text(strip=True)
        if texto.isdigit():
            numero = int(texto)
            if numero > max_pagina:
                max_pagina = numero

    return max_pagina


def guardar_csv(productos, ruta_archivo):
    """
    Guarda la lista de productos en un archivo CSV.
    """
    if not productos:
        print("No hay productos para guardar.")
        return

    os.makedirs(os.path.dirname(ruta_archivo), exist_ok=True)

    columnas = [
        "nombre",
        "precio",
        "marca",
        "cantidad_unidades",
        "precio_por_unidad",
        "imagen",
        "precio_lista",
        "url",
        "tienda",
        "fecha_extraccion",
    ]

    with open(ruta_archivo, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(productos)

    print(f"\nDatos guardados en: {ruta_archivo}")
    print(f"Total de productos guardados: {len(productos)}")


def main():
    """
    Funcion principal que ejecuta todo el proceso de scraping de Farmacias Ahumada.

    1. Descarga la primera pagina para detectar paginacion
    2. Recorre todas las paginas usando la API offset-based de Demandware
    3. Guarda todo en un CSV
    """
    print("=" * 60)
    print("SCRAPER FARMACIAS AHUMADA - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categorias: {len(CATEGORIAS)}")
    print()

    todos_los_productos = []

    for idx_cat, cat_info in enumerate(CATEGORIAS, 1):
        url_cat = cat_info["url"]
        cgid = cat_info["cgid"]

        print(f"\n[Categoria {idx_cat}/{len(CATEGORIAS)}] {url_cat}")
        print("-" * 60)

        # Paso 1: Descargar la primera pagina
        print("  Descargando primera pagina para detectar paginacion...")
        soup_primera = obtener_pagina(url_cat)

        if not soup_primera:
            print(f"  ERROR: No se pudo descargar {url_cat}. Saltando categoria.")
            continue

        # Paso 2: Detectar paginacion y extraer productos
        total_paginas = detectar_total_paginas(soup_primera)
        print(f"  Paginas detectadas: {total_paginas}")

        # Primera pagina: extraer del HTML ya descargado
        print("\n  --- Pagina 1 ---")
        productos_pagina = extraer_productos(soup_primera)
        print(f"  Productos encontrados en esta pagina: {len(productos_pagina)}")
        todos_los_productos.extend(productos_pagina)

        # Paginas siguientes: usar la API de paginacion
        MAX_PAGINAS = 20
        pagina_actual = 2

        while pagina_actual <= max(total_paginas, MAX_PAGINAS):
            start = (pagina_actual - 1) * PRODUCTOS_POR_PAGINA
            print(f"\n  --- Pagina {pagina_actual} (offset {start}) ---")

            soup = obtener_pagina_api(start, cgid)
            if not soup:
                print("  No se pudo descargar. Deteniendo paginacion.")
                break

            productos_pagina = extraer_productos(soup)
            print(f"  Productos encontrados en esta pagina: {len(productos_pagina)}")

            if not productos_pagina:
                print("  No se encontraron mas productos. Fin de la paginacion.")
                break

            todos_los_productos.extend(productos_pagina)
            pagina_actual += 1

            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s antes de la siguiente pagina...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

        print(f"  Subtotal categoria: {len(productos_pagina)} productos")

        # Pausa entre categorias
        if idx_cat < len(CATEGORIAS):
            time.sleep(PAUSA_ENTRE_PAGINAS)

    print(f"\n  Total de productos extraidos: {len(todos_los_productos)}")

    # Paso 3: Guardar en CSV
    print("\n[3/3] Guardando datos en CSV...")
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
