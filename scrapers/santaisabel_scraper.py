"""
Scraper para Santa Isabel (https://www.santaisabel.cl)
Extrae productos de panales de la seccion de panales del sitio.

Santa Isabel usa la plataforma Cencosud/VTEX. Los datos de productos
vienen embebidos en el HTML como JSON dentro de window.__renderData.

URL: https://www.santaisabel.cl/mi-bebe/panales-y-toallas-humedas/panales
"""

import csv
import json
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
                                  es_formula, calcular_precio_por_unidad, guardar_csv)
except ImportError:
    from common import (limpiar_precio, extraer_marca, extraer_cantidad,
                        es_formula, calcular_precio_por_unidad, guardar_csv)

# --- CONFIGURACION ---

# URLs de categorias a scrapear
URLS_CATEGORIAS = [
    "https://www.santaisabel.cl/mi-bebe/panales-y-toallas-humedas/panales",
    "https://www.santaisabel.cl/mi-bebe/panales-y-toallas-humedas/toallas-humedas",
    "https://www.santaisabel.cl/mi-bebe/leche-y-suplementos-infantiles",
]

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "santaisabel_precios.csv"

# Headers que simulan un navegador real
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9",
}

# Tiempo maximo de espera por cada peticion (en segundos)
TIMEOUT = 20

# Pausa entre peticiones para no sobrecargar el servidor (en segundos)
PAUSA_ENTRE_PAGINAS = 3




def extraer_json_renderdata(soup):
    """
    Extrae el JSON embebido en window.__renderData del HTML.

    La plataforma Cencosud/VTEX almacena los datos de productos
    como JSON dentro de un tag <script> en el HTML.
    El valor suele estar doblemente codificado (JSON string que contiene JSON).

    Retorna:
        dict con los datos o None si no se encontro.
    """
    scripts = soup.find_all("script")
    for script in scripts:
        texto = script.string or ""
        if "window.__renderData" not in texto and "__renderData" not in texto:
            continue

        # Extraer el valor despues de window.__renderData =
        match = re.search(r"window\.__renderData\s*=\s*(.+?);\s*$", texto, re.DOTALL)
        if not match:
            match = re.search(r"__renderData\s*=\s*(.+?);\s*$", texto, re.DOTALL)
        if not match:
            continue

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        # Si el resultado es un string, esta doblemente codificado
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue

        return data

    return None


def buscar_productos_en_json(data):
    """
    Busca los productos dentro del JSON de renderData.

    En Cencosud/VTEX, los productos estan en:
    - data["plp"]["plp_products"]["products"]
    - O recursivamente en claves "products"

    Retorna:
        Lista de diccionarios con los datos de cada producto.
    """
    # Ruta directa conocida para Cencosud: plp -> plp_products -> products
    if isinstance(data, dict):
        plp = data.get("plp")
        if isinstance(plp, dict):
            plp_products = plp.get("plp_products")
            if isinstance(plp_products, dict):
                products = plp_products.get("products")
                if isinstance(products, list) and products:
                    return products

    # Fallback: busqueda recursiva
    return _buscar_productos_recursivo(data)


def _buscar_productos_recursivo(data):
    """Busca recursivamente listas de productos en el JSON."""
    productos_encontrados = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key == "products" and isinstance(value, list) and value:
                # Verificar que los items parecen productos (tienen productName o name)
                if any(isinstance(v, dict) and ("productName" in v or "name" in v) for v in value):
                    productos_encontrados.extend(value)
                    continue
            if isinstance(value, (dict, list)):
                productos_encontrados.extend(_buscar_productos_recursivo(value))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                productos_encontrados.extend(_buscar_productos_recursivo(item))

    return productos_encontrados


def extraer_precio_de_producto_json(producto):
    """
    Extrae el precio de un producto del JSON de Cencosud/VTEX.

    El precio puede estar en diferentes ubicaciones:
    - producto["Price"]
    - producto["items"][0]["sellers"][0]["commertialOffer"]["Price"]
    - producto["price"]
    """
    # Intentar precio directo
    for campo in ("Price", "price", "bestPrice", "sellingPrice"):
        precio = producto.get(campo)
        if precio and isinstance(precio, (int, float)) and precio > 0:
            return int(precio)

    # Intentar en items -> sellers -> commertialOffer
    items = producto.get("items", [])
    if items and isinstance(items, list):
        for item in items:
            sellers = item.get("sellers", [])
            if sellers and isinstance(sellers, list):
                for seller in sellers:
                    oferta = seller.get("commertialOffer", {})
                    precio = oferta.get("Price") or oferta.get("price")
                    if precio and isinstance(precio, (int, float)) and precio > 0:
                        return int(precio)

    return None


def extraer_productos_de_json(data):
    """
    Extrae productos del JSON de renderData y los convierte al formato estandar.
    """
    productos_json = buscar_productos_en_json(data)
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for p in productos_json:
        if not isinstance(p, dict):
            continue

        nombre = p.get("productName") or p.get("name") or p.get("productTitle", "")
        if not nombre or len(nombre) < 3:
            continue

        # Evitar duplicados por productId
        marca_json = p.get("brand") or p.get("brandName", "")
        marca = extraer_marca(nombre, marca_api=marca_json)

        precio = extraer_precio_de_producto_json(p)

        # URL del producto
        link = p.get("link") or p.get("linkText") or p.get("slug", "")
        if link and not link.startswith("http"):
            link = f"https://www.santaisabel.cl/{link.lstrip('/')}"
        # La plataforma Cencosud/VTEX requiere el sufijo /p para paginas de producto
        if link and not link.endswith("/p"):
            link = link.rstrip("/") + "/p"
        url = link or ""

        cantidad = extraer_cantidad(nombre)

        precio_por_unidad = calcular_precio_por_unidad(precio, cantidad, nombre)

        # Imagen del producto
        imagen = ""
        items = p.get("items", [])
        if items and isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                images = item.get("images", [])
                if images and isinstance(images, list):
                    img = images[0]
                    if isinstance(img, dict):
                        imagen = img.get("imageUrl", "") or img.get("imageUrl", "")
                    elif isinstance(img, str):
                        imagen = img
                    break

        # Precio lista (para descuento)
        precio_lista = None
        if items and isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                sellers = item.get("sellers", [])
                if sellers and isinstance(sellers, list):
                    for seller in sellers:
                        oferta = seller.get("commertialOffer", {})
                        lp = oferta.get("ListPrice") or oferta.get("PriceWithoutDiscount")
                        if lp and isinstance(lp, (int, float)) and lp > 0:
                            precio_lista = int(lp)
                            break
                    if precio_lista:
                        break
        # Solo guardar precio_lista si es diferente al precio de venta
        if precio_lista and precio and precio_lista <= precio:
            precio_lista = None

        # Disponibilidad: AvailableQuantity en commertialOffer
        en_stock = 1
        if items and isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                sellers = item.get("sellers", [])
                if sellers and isinstance(sellers, list):
                    for seller in sellers:
                        oferta = seller.get("commertialOffer", {})
                        qty = oferta.get("AvailableQuantity", 0)
                        if isinstance(qty, (int, float)) and qty > 0:
                            en_stock = 1
                            break
                        else:
                            en_stock = 0
                    break

        producto = {
            "nombre": nombre,
            "precio": precio,
            "marca": marca,
            "cantidad_unidades": cantidad,
            "precio_por_unidad": precio_por_unidad,
            "url": url,
            "tienda": "Santa Isabel",
            "fecha_extraccion": timestamp,
            "imagen": imagen,
            "precio_lista": precio_lista,
            "en_stock": en_stock,
        }
        productos.append(producto)

    return productos


def extraer_productos_de_html(soup):
    """
    Fallback: extrae productos directamente del HTML usando CSS selectors.
    Se usa si no se encuentra el JSON embebido.
    """
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    contenedores = soup.select(
        ".product-card, .productCard, [class*='product-card'], "
        "[class*='ProductCard'], .shelf-product-item"
    )

    for contenedor in contenedores:
        try:
            nombre_elem = contenedor.select_one(
                ".product-card__name, .productCard-name, "
                "[class*='product-name'], [class*='productName'], h3, h2"
            )
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else None
            if not nombre or len(nombre) < 3:
                continue

            precio = None
            precio_elem = contenedor.select_one(
                ".product-card__price, .productCard-price, "
                "[class*='product-price'], [class*='Price'], .price"
            )
            if precio_elem:
                precio = limpiar_precio(precio_elem.get_text())

            if not precio:
                texto = contenedor.get_text()
                match = re.search(r"\$[\d.,]+", texto)
                if match:
                    precio = limpiar_precio(match.group())

            marca = extraer_marca(nombre)
            cantidad = extraer_cantidad(nombre)

            link_elem = contenedor.select_one("a[href]")
            url = ""
            if link_elem:
                href = link_elem.get("href", "")
                if href.startswith("/"):
                    url = f"https://www.santaisabel.cl{href}"
                elif href.startswith("http"):
                    url = href

            precio_por_unidad = calcular_precio_por_unidad(precio, cantidad, nombre)

            # Imagen
            imagen = ""
            img_elem = contenedor.select_one("img")
            if img_elem:
                imagen = img_elem.get("src") or img_elem.get("data-src") or ""

            producto = {
                "nombre": nombre,
                "precio": precio,
                "marca": marca,
                "cantidad_unidades": cantidad,
                "precio_por_unidad": precio_por_unidad,
                "url": url,
                "tienda": "Santa Isabel",
                "fecha_extraccion": timestamp,
                "imagen": imagen,
                "precio_lista": None,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def detectar_total_paginas(soup):
    """
    Detecta el total de paginas disponibles.

    En la plataforma Cencosud, la paginacion puede estar en el JSON
    o en links de paginacion del HTML.
    """
    # Buscar en links de paginacion
    paginacion = soup.select("nav.pagination a, .pagination a, ul.pagination a, [class*='paginat'] a")

    max_pagina = 1
    for link in paginacion:
        texto = link.get_text(strip=True)
        if texto.isdigit():
            numero = int(texto)
            if numero > max_pagina:
                max_pagina = numero

    return max_pagina


def main():
    """
    Funcion principal que ejecuta todo el proceso de scraping de Santa Isabel.

    1. Descarga la pagina de panales
    2. Intenta extraer productos del JSON embebido (renderData)
    3. Si no encuentra JSON, usa extraccion HTML como fallback
    4. Intenta paginar si hay mas de una pagina
    5. Guarda todo en un CSV
    """
    print("=" * 60)
    print("SCRAPER SANTA ISABEL - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categorias: {len(URLS_CATEGORIAS)}")
    print()

    todos_los_productos = []

    for idx_cat, url_cat in enumerate(URLS_CATEGORIAS, 1):
        print(f"\n[Categoria {idx_cat}/{len(URLS_CATEGORIAS)}] {url_cat}")
        print("-" * 60)

        # Paso 1: Descargar la primera pagina
        print("  Descargando primera pagina...")
        soup_primera = obtener_pagina(url_cat, HEADERS, TIMEOUT)

        if not soup_primera:
            print(f"  ERROR: No se pudo descargar {url_cat}. Saltando categoria.")
            continue

        # Paso 2: Intentar extraer productos del JSON
        render_data = extraer_json_renderdata(soup_primera)
        if render_data:
            print("  JSON renderData encontrado. Extrayendo productos del JSON...")
            productos_pagina = extraer_productos_de_json(render_data)
            print(f"  Productos encontrados en JSON: {len(productos_pagina)}")
            todos_los_productos.extend(productos_pagina)
        else:
            print("  No se encontro JSON renderData. Usando extraccion HTML...")
            productos_pagina = extraer_productos_de_html(soup_primera)
            print(f"  Productos encontrados en HTML: {len(productos_pagina)}")
            todos_los_productos.extend(productos_pagina)

        # Paso 2b: Intentar paginar
        total_paginas = detectar_total_paginas(soup_primera)
        if total_paginas > 1:
            print(f"\n  Paginas detectadas: {total_paginas}")
            for num_pagina in range(2, total_paginas + 1):
                print(f"\n  --- Pagina {num_pagina} de {total_paginas} ---")
                url_pagina = f"{url_cat}?page={num_pagina}"
                soup = obtener_pagina(url_pagina, HEADERS, TIMEOUT)
                if not soup:
                    continue

                render_data = extraer_json_renderdata(soup)
                if render_data:
                    productos_pagina = extraer_productos_de_json(render_data)
                else:
                    productos_pagina = extraer_productos_de_html(soup)

                print(f"  Productos encontrados: {len(productos_pagina)}")
                todos_los_productos.extend(productos_pagina)

                if num_pagina < total_paginas:
                    print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s...")
                    time.sleep(PAUSA_ENTRE_PAGINAS)

        print(f"  Subtotal categoria: {len(productos_pagina)} productos")

        # Pausa entre categorias
        if idx_cat < len(URLS_CATEGORIAS):
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
