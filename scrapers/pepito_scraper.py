"""
Scraper para Distribuidora Pepito (https://www.distribuidorapepito.cl)
Extrae productos de panales de las categorias de panales bebe y adulto.

Pepito usa la plataforma Jumpseller. Los productos se listan en:
  https://www.distribuidorapepito.cl/panales-bebe
con paginacion: ?page=2, ?page=3, etc.

Estructura HTML clave (Jumpseller):
  - .product-block          -> contenedor de cada producto
  - .product-block__name    -> nombre del producto (dentro de un <a>)
  - .product-block__brand   -> marca del producto
  - .product-block__price   -> precio (puede tener --new y --old si hay descuento)
  - .product-block__anchor  -> link al producto
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

# --- CONFIGURACION ---

# URLs de las categorias de panales que queremos scrapear
# Pepito separa panales bebe y panales adulto en secciones distintas
CATEGORIAS = [
    {
        "nombre": "Pañales Bebé",
        "url": "https://www.distribuidorapepito.cl/panales-bebe",
    },
    {
        "nombre": "Pañales Adulto",
        "url": "https://www.distribuidorapepito.cl/para-el-adulto",
    },
]

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "pepito_precios.csv"

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
TIMEOUT = 15

# Pausa entre peticiones para no sobrecargar el servidor (en segundos)
PAUSA_ENTRE_PAGINAS = 2

# Pausa entre peticiones a paginas individuales de producto (mas corta)
PAUSA_ENTRE_PRODUCTOS = 0.5




def detectar_total_paginas(soup):
    """
    Detecta cuantas paginas de productos hay.

    En Jumpseller, la paginacion usa links con ?page=N.
    Buscamos el link "Último" o el numero mas alto entre los links de pagina.
    """
    max_pagina = 1

    # Buscamos todos los links que tengan ?page= en el href
    links_pagina = soup.select('a[href*="page="]')

    for link in links_pagina:
        href = link.get("href", "")
        # Extraemos el numero de pagina del parametro ?page=N
        match = re.search(r"page=(\d+)", href)
        if match:
            numero = int(match.group(1))
            if numero > max_pagina:
                max_pagina = numero

    return max_pagina


def limpiar_precio(texto_precio):
    """
    Convierte un texto de precio como "$14.990 CLP" en un numero entero: 14990.

    Retorna:
        int o None si no se pudo convertir.
    """
    if not texto_precio:
        return None

    # Eliminamos todo excepto digitos
    solo_numeros = re.sub(r"[^\d]", "", texto_precio)

    if solo_numeros:
        return int(solo_numeros)
    return None


def extraer_marca_del_nombre(nombre_producto):
    """
    Intenta detectar la marca del producto a partir de su nombre.
    Se usa como respaldo si no se encuentra la marca en el HTML.
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
    ]

    nombre_lower = nombre_producto.lower()
    for marca in marcas_conocidas:
        if marca.lower() in nombre_lower:
            return marca

    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def extraer_cantidad_del_nombre(nombre_producto):
    """
    Intenta extraer la cantidad de panales del nombre del producto.

    IMPORTANTE: En Pepito, "(X3)" o "(X6)" significan PACKS de paquetes,
    NO panales individuales. Por ejemplo:
      - "Pañal Aiwibi Premium P (X3)" = 3 paquetes de 32 = 96 panales
      - "52 UNIDADES" = 52 panales individuales

    Esta funcion solo extrae cantidades cuando dice "unidades" explicitamente.
    Para el resto, se usa extraer_cantidad_desde_detalle() que visita la pagina
    del producto y lee la ficha tecnica.
    """
    # Solo confiamos en "N unidades" que si indica panales individuales
    patron = re.search(r"(\d+)\s*(?:unidades|unid|und)\b", nombre_producto, re.IGNORECASE)
    if patron:
        return int(patron.group(1))

    return None


def extraer_detalle_producto(url):
    """
    Visita la pagina individual de un producto para obtener la cantidad
    real de panales desde la ficha tecnica y el estado de stock.

    En Pepito, la ficha tecnica usa un formato de lista de definiciones (<dl>):
      - "CANTIDAD POR PACK: 96"  -> para packs (X3, X6, etc.)
      - "CANTIDAD POR ENVASE: 32" -> para productos unitarios

    El stock se detecta del JSON embebido ("stock": 0) o del Schema.org
    (availability: OutOfStock).

    Retorna:
        dict con {"cantidad": int|None, "en_stock": int (1 o 0)}
    """
    if not url:
        return {"cantidad": None, "en_stock": 1}

    try:
        soup = obtener_pagina(url, HEADERS, TIMEOUT)
        if not soup:
            return {"cantidad": None, "en_stock": 1}

        texto = soup.get_text()

        # --- STOCK ---
        en_stock = 1
        # Buscar "stock": 0 en scripts JSON
        for script in soup.select("script"):
            script_text = script.string or ""
            if '"stock"' in script_text:
                match_stock = re.search(r'"stock"\s*:\s*(\d+)', script_text)
                if match_stock and int(match_stock.group(1)) == 0:
                    en_stock = 0
                    break
        # Fallback: Schema.org OutOfStock
        if en_stock and "OutOfStock" in texto:
            en_stock = 0

        # --- CANTIDAD ---
        cantidad = None

        # Prioridad 1: "CANTIDAD POR PACK" (total de panales en packs multiples)
        match_pack = re.search(
            r"CANTIDAD\s+POR\s+PACK\s*:\s*(\d+)", texto, re.IGNORECASE
        )
        if match_pack:
            cantidad = int(match_pack.group(1))

        # Prioridad 2: "CANTIDAD POR ENVASE" (panales en un paquete individual)
        if not cantidad:
            match_envase = re.search(
                r"CANTIDAD\s+POR\s+ENVASE\s*:\s*(\d+)", texto, re.IGNORECASE
            )
            if match_envase:
                cantidad = int(match_envase.group(1))

        # Prioridad 3: "N PAÑALES POR PAQUETE" en la descripcion
        if not cantidad:
            match_desc = re.search(
                r"(\d+)\s*(?:pa[ñn]ales|unidades)\s+por\s+paquete", texto, re.IGNORECASE
            )
            if match_desc:
                cantidad = int(match_desc.group(1))

        return {"cantidad": cantidad, "en_stock": en_stock}

    except Exception:
        return {"cantidad": None, "en_stock": 1}


def extraer_productos(soup):
    """
    Extrae la informacion de todos los productos de una pagina.

    Usa las clases de Jumpseller:
    - .product-block: contenedor de cada producto
    - .product-block__name: nombre (link al producto)
    - .product-block__brand: marca
    - .product-block__price--new o .product-block__price: precio actual
    - .product-block__price--old: precio anterior (si hay descuento)

    Retorna:
        Lista de diccionarios con los datos de cada producto.
    """
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Jumpseller usa <article class="product-block"> como contenedor
    bloques = soup.select(".product-block")

    if not bloques:
        print("  AVISO: No se encontraron productos en esta pagina.")
        return productos

    for bloque in bloques:
        try:
            # --- STOCK ---
            agotado = False
            stock_elem = bloque.select_one('.product-stock[data-label="out-of-stock"]')
            if stock_elem:
                agotado = True
            elif "agotado" in bloque.get_text(separator=" ", strip=True).lower():
                agotado = True

            # --- NOMBRE DEL PRODUCTO ---
            nombre_elem = bloque.select_one(".product-block__name")
            if not nombre_elem:
                continue

            nombre = nombre_elem.get_text(strip=True)
            if not nombre or len(nombre) < 3:
                continue

            # --- URL DEL PRODUCTO ---
            href = nombre_elem.get("href", "")
            if href.startswith("/"):
                url = f"https://www.distribuidorapepito.cl{href}"
            else:
                url = href

            # --- MARCA ---
            # Jumpseller la pone en un span con clase .product-block__brand
            marca_elem = bloque.select_one(".product-block__brand")
            if marca_elem:
                marca = marca_elem.get_text(strip=True)
            else:
                marca = extraer_marca_del_nombre(nombre)

            # --- PRECIO ---
            # Si hay descuento, el precio actual esta en .product-block__price--new
            # Si no hay descuento, esta en .product-block__price (sin modificador)
            precio = None

            # Primero intentamos el precio con descuento
            precio_nuevo_elem = bloque.select_one(".product-block__price--new")
            if precio_nuevo_elem:
                precio = limpiar_precio(precio_nuevo_elem.get_text())

            # Si no hay precio con descuento, buscamos el precio normal
            if not precio:
                precio_elem = bloque.select_one(".product-block__price")
                if precio_elem:
                    precio = limpiar_precio(precio_elem.get_text())

            # --- CANTIDAD ---
            # Solo extraemos del nombre si dice "N UNIDADES" explicitamente.
            # La cantidad real se obtiene despues visitando cada producto.
            cantidad = extraer_cantidad_del_nombre(nombre)

            # --- IMAGEN ---
            img_elem = bloque.select_one("img")
            imagen = img_elem.get("src") or img_elem.get("data-src") if img_elem else None

            producto = {
                "nombre": nombre,
                "precio": precio,
                "marca": marca,
                "cantidad_unidades": cantidad,
                "precio_por_unidad": None,
                "imagen": imagen,
                "precio_lista": None,
                "url": url,
                "tienda": "Distribuidora Pepito",
                "fecha_extraccion": timestamp,
                "en_stock": 0 if agotado else 1,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


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
        "en_stock",
    ]

    with open(ruta_archivo, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(productos)

    print(f"\nDatos guardados en: {ruta_archivo}")
    print(f"Total de productos guardados: {len(productos)}")


def scrapear_categoria(nombre_categoria, url_base):
    """
    Scrapea todas las paginas de una categoria especifica.

    1. Descarga la primera pagina para detectar paginacion
    2. Recorre todas las paginas extrayendo productos

    Retorna:
        Lista de todos los productos encontrados en la categoria.
    """
    print(f"\n{'─' * 50}")
    print(f"Categoria: {nombre_categoria}")
    print(f"URL: {url_base}")
    print(f"{'─' * 50}")

    # Descargar primera pagina
    soup_primera = obtener_pagina(url_base, HEADERS, TIMEOUT)
    if not soup_primera:
        print(f"  ERROR: No se pudo descargar {nombre_categoria}. Saltando...")
        return []

    # Detectar paginacion
    total_paginas = detectar_total_paginas(soup_primera)
    print(f"  Paginas detectadas: {total_paginas}")

    todos_los_productos = []

    for num_pagina in range(1, total_paginas + 1):
        print(f"\n  --- Pagina {num_pagina} de {total_paginas} ---")

        if num_pagina == 1:
            soup = soup_primera
        else:
            url_pagina = f"{url_base}?page={num_pagina}"
            soup = obtener_pagina(url_pagina, HEADERS, TIMEOUT)
            if not soup:
                print(f"  No se pudo descargar pagina {num_pagina}. Continuando...")
                continue

        productos_pagina = extraer_productos(soup)
        print(f"  Productos encontrados: {len(productos_pagina)}")
        todos_los_productos.extend(productos_pagina)

        # Pausa entre peticiones
        if num_pagina < total_paginas:
            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

    return todos_los_productos


def enriquecer_con_detalle(productos):
    """
    Visita la pagina individual de cada producto para obtener la
    cantidad real de panales desde la ficha tecnica.

    Esto es necesario porque en Pepito:
    - "(X3)" en el nombre significa 3 PAQUETES, no 3 panales
    - La cantidad real esta en la ficha: "CANTIDAD POR PACK: 96"
    - Los productos unitarios dicen: "CANTIDAD POR ENVASE: 32"

    Solo visita productos que aun no tienen cantidad definida
    (los que ya tienen "N UNIDADES" en el nombre se saltan).
    """
    con_url = [p for p in productos if p["url"]]

    print(f"\n  Visitando {len(con_url)} paginas individuales (cantidad + stock)...")

    for i, producto in enumerate(con_url, 1):
        if i % 10 == 1 or i == len(con_url):
            print(f"    Progreso: {i}/{len(con_url)}...")

        detalle = extraer_detalle_producto(producto["url"])
        if detalle:
            if detalle["cantidad"] and producto["cantidad_unidades"] is None:
                producto["cantidad_unidades"] = detalle["cantidad"]
            producto["en_stock"] = detalle["en_stock"]

        time.sleep(PAUSA_ENTRE_PRODUCTOS)

    # Recalculamos precio por unidad para TODOS los productos
    for producto in productos:
        cantidad = producto["cantidad_unidades"]
        precio = producto["precio"]
        if precio and cantidad and cantidad > 0:
            producto["precio_por_unidad"] = round(precio / cantidad)

    # Resumen
    total_con_cantidad = sum(1 for p in productos if p["cantidad_unidades"] is not None)
    agotados = sum(1 for p in productos if not p.get("en_stock", 1))
    print(f"  Cantidad obtenida para {total_con_cantidad} de {len(productos)} productos")
    if agotados:
        print(f"  Productos agotados detectados: {agotados}")


def main():
    """
    Funcion principal que ejecuta todo el proceso de scraping.

    Recorre todas las categorias de panales (bebe y adulto),
    extrae los productos de cada una, y guarda todo en un CSV.
    """
    print("=" * 60)
    print("SCRAPER DISTRIBUIDORA PEPITO - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    todos_los_productos = []

    # Recorremos cada categoria
    for categoria in CATEGORIAS:
        productos = scrapear_categoria(categoria["nombre"], categoria["url"])
        todos_los_productos.extend(productos)

    print(f"\n\nTotal de productos extraidos de todas las categorias: {len(todos_los_productos)}")

    # Visitamos cada producto para obtener la cantidad real de panales
    print("\n[PASO EXTRA] Obteniendo cantidad real de panales por paquete...")
    enriquecer_con_detalle(todos_los_productos)

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

    marcas = set(p["marca"] for p in todos_los_productos if p["marca"])
    print(f"Marcas encontradas: {', '.join(sorted(marcas))}")

    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
