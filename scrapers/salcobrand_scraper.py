"""
Scraper para Salcobrand (https://salcobrand.cl)
Extrae productos de panales, toallitas humedas y formulas infantiles.

Salcobrand usa Spree Commerce (Rails) y embebe datos del producto
en una variable JavaScript `product_traker_data` en cada pagina.

Estrategia:
1. Obtener URLs de productos desde el sitemap XML
2. Filtrar URLs relevantes (panales, toallitas, formulas)
3. Extraer `product_traker_data` de cada pagina de producto
4. Parsear JSON y guardar en CSV
"""

import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

# --- CONFIGURACION ---

# URL del sitemap principal
SITEMAP_URL = "https://salcobrand.cl/sitemap.xml"

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "salcobrand_precios.csv"

# Headers HTTP
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Tiempo maximo de espera por cada peticion (en segundos)
TIMEOUT = 20

# Pausa entre peticiones a paginas de producto (en segundos)
PAUSA_ENTRE_PAGINAS = 1.5

# Palabras clave en el slug de la URL para identificar productos relevantes
SLUG_KEYWORDS = [
    "panal", "panales", "pañal", "pañales",
    "pampers", "huggies", "babysec",
    "toallita", "toallitas", "toalla-humeda", "toallas-humedas",
    "formula-infantil", "formula-lactea", "leche-infantil",
    "nan-", "similac", "enfamil", "s-26", "nidal", "nutrilon",
    "splasher", "swimmer",
    "emubaby", "goodnites",
]

# Palabras clave para excluir productos no relevantes
EXCLUIR_NOMBRE = [
    # Adulto
    "adulto", "adultos", "incontinencia", "plenitud",
    "cotidian", "tena ", "ladysoft", "emumed", "emuprotect",
    "proactive", "sabanilla",
    # Desmaquillantes y cosmeticos
    "desmaquillant", "micelar",
    # Mascotas
    "mascota", "mascotas", "vetcare",
    # Oftalmicas y medicas
    "oftalmic", "palpebral", "proctowipe",
    # Cremas (no son panales/toallitas/formulas)
    "crema", "locion", "loción", "colonia", "shampoo",
    # Toallitas no de bebe
    "antibacterial", "limpieza facial", "facial celeste", "facial rosado",
    # Manos
    "para manos",
    # Toallitas genericas no infantiles
    "con alcohol", "care up",
    # Oftalmicas con tilde
    "oftálmic",
]

# Marcas conocidas para deteccion
MARCAS_CONOCIDAS = [
    "Pampers", "Huggies", "Babysec", "Goodnites",
    "Tutte", "Pequenin", "Aiwibi", "Emubaby", "Moltex", "Chelino",
    "Bambo", "Pingo", "Naty", "Eco Boom", "Biobaby",
    "Nan", "Similac", "Nidal", "Enfamil", "S-26", "Alula",
    "Nutrilon", "Blemil", "Nestogen",
    "Johnsons", "Johnson",
    "Aqua Baby", "WaterWipes", "Waterwipes",
    "Nenitos", "Neniwipes", "Merries",
    "Terra", "Althera", "Twistshake",
    "Cell Skin", "Simond",
]

# URL base para productos
URL_BASE_PRODUCTO = "https://salcobrand.cl"


def obtener_sitemaps():
    """
    Descarga el sitemap principal y retorna las URLs de los sub-sitemaps.
    """
    print("  Descargando sitemap principal...")
    try:
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"  ERROR descargando sitemap: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"  ERROR parseando XML del sitemap: {e}")
        return []

    # Namespace del sitemap XML
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    urls = []
    for sitemap in root.findall("sm:sitemap", ns):
        loc = sitemap.find("sm:loc", ns)
        if loc is not None and loc.text:
            urls.append(loc.text.strip())

    print(f"  Sub-sitemaps encontrados: {len(urls)}")
    return urls


def obtener_urls_productos(sitemap_urls):
    """
    Descarga cada sub-sitemap y extrae URLs de productos que matchean
    con las palabras clave relevantes.
    """
    urls_productos = set()

    for sitemap_url in sitemap_urls:
        print(f"  Descargando sub-sitemap: {sitemap_url.split('/')[-1]}...")
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"  ERROR: {e}")
            continue

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            continue

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        for url_elem in root.findall("sm:url", ns):
            loc = url_elem.find("sm:loc", ns)
            if loc is None or not loc.text:
                continue

            url = loc.text.strip()

            # Solo URLs de productos (/products/)
            if "/products/" not in url:
                continue

            slug = url.split("/products/")[-1].lower()

            # Verificar si el slug contiene alguna palabra clave
            if any(kw in slug for kw in SLUG_KEYWORDS):
                urls_productos.add(url)

        time.sleep(0.5)

    print(f"  URLs de productos relevantes: {len(urls_productos)}")
    return list(urls_productos)


def extraer_product_data(html):
    """
    Extrae la variable `product_traker_data` del HTML de una pagina de producto.
    Retorna el dict parseado o None si no se encuentra.
    """
    # Buscar la variable product_traker_data en el HTML
    match = re.search(
        r"product_traker_data\s*=\s*(\{.*?\})\s*;",
        html,
        re.DOTALL,
    )
    if not match:
        return None

    json_str = match.group(1)

    # Limpiar posibles comillas simples o problemas de encoding
    try:
        data = json.loads(json_str)
        return data
    except json.JSONDecodeError:
        # Intentar arreglar JSON con comillas simples
        try:
            json_str_fixed = json_str.replace("'", '"')
            data = json.loads(json_str_fixed)
            return data
        except json.JSONDecodeError:
            return None


def extraer_marca(nombre, vendor=None):
    """
    Detecta la marca del producto. Usa el campo vendor de la API si existe,
    luego busca marcas conocidas en el nombre.
    """
    if vendor:
        vendor_clean = vendor.strip()
        if vendor_clean and vendor_clean.lower() not in ("", "salcobrand", "none"):
            return vendor_clean

    if not nombre:
        return "Desconocida"

    nombre_lower = nombre.lower()
    for marca in MARCAS_CONOCIDAS:
        if marca.lower() in nombre_lower:
            return marca

    # Sublíneas de producto
    SUBLINEAS_MARCA = [
        ("premium care", "Pampers"),
        ("confort sec", "Pampers"),
        ("super premium", "Babysec"),
        ("premium", "Babysec"),
        ("ultrasuave", "Emubaby"),
    ]
    for sublinea, marca in SUBLINEAS_MARCA:
        if sublinea in nombre_lower:
            return marca

    return "Desconocida"


def extraer_cantidad(nombre):
    """
    Intenta extraer la cantidad de unidades del nombre del producto.
    """
    patrones = [
        r"(\d+)\s*(?:pa[ñn]ales)\b",
        r"(\d+)\s*(?:toallitas|toallas)\b",
        r"(\d+)\s*(?:unidades|unid|und)\b",
        r"(\d+)\s*(?:hojas)\b",
        r"x\s*(\d+)\s*(?:un|u)\b",
        r"[xX](\d+)\b",
        r"(\d+)\s*[uU]\b",
        r"(\d+)\s*(?:un)\b",
    ]
    for patron in patrones:
        match = re.search(patron, nombre, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def procesar_producto(url, data):
    """
    Convierte los datos extraidos de product_traker_data al formato estandar.
    """
    try:
        nombre = data.get("name", "")
        if not nombre or len(nombre) < 3:
            return None

        # Filtrar productos no relevantes
        nombre_lower = nombre.lower()
        if any(palabra in nombre_lower for palabra in EXCLUIR_NOMBRE):
            return None

        # Precio de venta (internet)
        precio = data.get("price")
        if precio is not None:
            try:
                precio = int(round(float(precio)))
            except (ValueError, TypeError):
                precio = None

        # Precio lista (farmacia/regular)
        precio_lista = data.get("oldPrice")
        if precio_lista is not None:
            try:
                precio_lista = int(round(float(precio_lista)))
            except (ValueError, TypeError):
                precio_lista = None
            # Solo guardar si es mayor al precio de venta
            if precio_lista and precio and precio_lista <= precio:
                precio_lista = None

        # Imagen
        imagen = data.get("pictureUrl", "")

        # Marca
        vendor = data.get("vendor")
        marca = extraer_marca(nombre, vendor)

        # Cantidad
        cantidad = extraer_cantidad(nombre)

        # Precio por unidad
        precio_por_unidad = None
        if precio and cantidad and cantidad > 0:
            precio_por_unidad = round(precio / cantidad)

        return {
            "nombre": nombre,
            "precio": precio,
            "marca": marca,
            "cantidad_unidades": cantidad,
            "precio_por_unidad": precio_por_unidad,
            "imagen": imagen,
            "precio_lista": precio_lista,
            "url": url,
            "tienda": "Salcobrand",
            "fecha_extraccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        print(f"  AVISO: Error procesando producto: {e}")
        return None


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
    Funcion principal que ejecuta el scraping de Salcobrand.

    1. Obtiene URLs de productos desde los sitemaps
    2. Visita cada pagina y extrae product_traker_data
    3. Procesa y deduplica productos
    4. Guarda en CSV
    """
    print("=" * 60)
    print("SCRAPER SALCOBRAND - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Paso 1: Obtener URLs de productos desde sitemaps
    print("[Paso 1] Obteniendo URLs desde sitemaps...")
    sitemap_urls = obtener_sitemaps()
    if not sitemap_urls:
        print("No se encontraron sub-sitemaps. Abortando.")
        return

    urls_productos = obtener_urls_productos(sitemap_urls)
    if not urls_productos:
        print("No se encontraron URLs de productos relevantes. Abortando.")
        return

    # Paso 2: Visitar cada pagina de producto
    print(f"\n[Paso 2] Scrapeando {len(urls_productos)} paginas de producto...")
    print("-" * 60)

    todos_los_productos = []
    urls_vistas = set()
    errores = 0

    for idx, url in enumerate(urls_productos, 1):
        # Deduplicar por URL
        if url in urls_vistas:
            continue
        urls_vistas.add(url)

        slug = url.split("/products/")[-1] if "/products/" in url else url
        print(f"  [{idx}/{len(urls_productos)}] {slug[:60]}...")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"    ERROR: {e}")
            errores += 1
            continue

        data = extraer_product_data(resp.text)
        if not data:
            print(f"    No se encontro product_traker_data")
            continue

        producto = procesar_producto(url, data)
        if producto:
            todos_los_productos.append(producto)
            print(f"    OK: {producto['nombre'][:50]} - ${producto.get('precio', '?')}")
        else:
            print(f"    Filtrado (adulto o sin datos)")

        time.sleep(PAUSA_ENTRE_PAGINAS)

    print(f"\n  Productos extraidos: {len(todos_los_productos)}")
    print(f"  Errores de conexion: {errores}")

    # Paso 3: Guardar en CSV
    print("\n[Paso 3] Guardando datos en CSV...")
    ruta_csv = os.path.join(CARPETA_DATOS, ARCHIVO_SALIDA)
    guardar_csv(todos_los_productos, ruta_csv)

    # Resumen final
    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"URLs de producto encontradas: {len(urls_productos)}")
    print(f"Productos extraidos: {len(todos_los_productos)}")

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
