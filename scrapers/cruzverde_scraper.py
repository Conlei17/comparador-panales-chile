"""
Scraper para Cruz Verde (https://www.cruzverde.cl)
Extrae productos de panales, toallitas humedas y formulas infantiles.

Cruz Verde usa Salesforce Commerce Cloud (Demandware) con una API REST
publica (OCAPI v19.1) que retorna JSON limpio.

Endpoint: https://beta.cruzverde.cl/s/Chile/dw/shop/v19_1/product_search
"""

import csv
import os
import re
import time
import unicodedata
from datetime import datetime

import requests

# --- CONFIGURACION ---

# Endpoint de la API OCAPI de Cruz Verde
API_URL = "https://beta.cruzverde.cl/s/Chile/dw/shop/v19_1/product_search"

# Client ID publico para acceder a la API
CLIENT_ID = "c19ce24d-1677-4754-b9f7-c193997c5a92"

# Cantidad de productos por pagina
PRODUCTOS_POR_PAGINA = 24

# Queries de busqueda por categoria
QUERIES = [
    {"q": "pañales", "refine": "c_Genero=Infantil"},
    {"q": "pampers"},
    {"q": "babysec"},
    {"q": "toallitas humedas bebe"},
    {"q": "formula infantil"},
    {"q": "formula lactea"},
]

# Palabras clave para filtrar productos de adulto que se cuelan
EXCLUIR_ADULTO = [
    "adulto", "adultos", "incontinencia", "plenitud",
    "cotidian", "tena ", "sabanilla",
]

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "cruzverde_precios.csv"

# Headers HTTP
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Tiempo maximo de espera por cada peticion (en segundos)
TIMEOUT = 20

# Pausa entre peticiones (en segundos)
PAUSA_ENTRE_PAGINAS = 2

# URL base para construir URLs de productos
URL_BASE_PRODUCTO = "https://www.cruzverde.cl"

# Marcas conocidas para deteccion
MARCAS_CONOCIDAS = [
    "Pampers", "Huggies", "Babysec", "Cotidian", "Goodnites",
    "Win", "Tutte", "Pequenin", "Tena", "Plenitud",
    "Ladysoft", "Aiwibi", "Emubaby", "Moltex", "Chelino",
    "Bambo", "Pingo", "Naty", "Eco Boom", "Biobaby",
    "Nan", "Similac", "Nidal", "Enfamil", "S-26", "Alula",
    "Nutrilon", "Blemil", "Nestogen",
    "Johnsons", "Johnson",
    "WaterWipes", "Waterwipes",
]

# SKUs de Cruz Verde cuyo nombre generico no identifica la marca
# Mapeo: fragmento de URL -> marca correcta
URL_MARCA_OVERRIDE = {
    "526896": "WaterWipes",  # Toallitas Húmedas Para Bebe X60
    "526897": "WaterWipes",  # Toallitas Húmedas Para Bebe X180
    "526898": "WaterWipes",  # Toallitas Húmedas Para Bebe 720 Toallitas
}


def buscar_productos_api(query, count=PRODUCTOS_POR_PAGINA, start=0, refine=None):
    """
    Realiza una busqueda en la API OCAPI de Cruz Verde.

    Args:
        query: termino de busqueda
        count: cantidad de resultados por pagina
        start: offset de inicio
        refine: filtro de refinamiento (ej: "c_Genero=Infantil")

    Retorna:
        dict con la respuesta JSON o None si hubo error.
    """
    params = {
        "client_id": CLIENT_ID,
        "q": query,
        "expand": "images,prices",
        "count": count,
        "start": start,
    }
    if refine:
        params["refine"] = refine

    try:
        print(f"  API: q={query}, start={start}, count={count}" + (f", refine={refine}" if refine else ""))
        respuesta = requests.get(API_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
        respuesta.raise_for_status()
        return respuesta.json()
    except requests.exceptions.Timeout:
        print(f"  ERROR: Tiempo de espera agotado")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  ERROR: No se pudo conectar a la API")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  ERROR: Respuesta HTTP {e.response.status_code}")
        return None
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"  ERROR inesperado: {e}")
        return None


def extraer_marca(nombre_producto):
    """
    Intenta detectar la marca del producto a partir de su nombre.
    Usa marcas conocidas, luego sublíneas de producto, luego primera palabra.
    """
    nombre_lower = nombre_producto.lower()
    for marca in MARCAS_CONOCIDAS:
        if marca.lower() in nombre_lower:
            return marca

    # Sublíneas que identifican marca cuando el nombre no contiene la marca directa
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

    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def extraer_cantidad(nombre_producto):
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
        match = re.search(patron, nombre_producto, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def procesar_hit(hit):
    """
    Convierte un hit de la API OCAPI al formato estandar del proyecto.

    Args:
        hit: diccionario de un resultado de busqueda de la API

    Retorna:
        dict con el producto en formato estandar o None si no se pudo procesar.
    """
    try:
        nombre = hit.get("product_name", "")
        if not nombre or len(nombre) < 3:
            return None

        # Filtrar productos de adulto que no corresponden
        nombre_lower = nombre.lower()
        if any(palabra in nombre_lower for palabra in EXCLUIR_ADULTO):
            return None

        product_id = hit.get("product_id", "")

        # Precio de venta
        precio = None
        prices = hit.get("prices", {})
        if prices:
            precio = prices.get("price-sale-cl")
            if precio is None:
                precio = prices.get("usd-sale-prices")
        if precio is None:
            precio = hit.get("price")
        if precio is not None:
            precio = int(round(precio))

        # Precio lista (antes del descuento)
        precio_lista = None
        if prices:
            precio_lista = prices.get("price-list-cl")
            if precio_lista is not None:
                precio_lista = int(round(precio_lista))
            # Solo guardar precio_lista si es mayor al precio de venta
            if precio_lista and precio and precio_lista <= precio:
                precio_lista = None

        # Imagen
        imagen = None
        image = hit.get("image")
        if image:
            imagen = image.get("dis_base_link") or image.get("link")

        # URL del producto (formato: /slug-del-nombre/ID.html)
        if product_id:
            slug = unicodedata.normalize("NFD", nombre)
            slug = slug.encode("ascii", "ignore").decode("ascii")
            slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
            url = f"{URL_BASE_PRODUCTO}/{slug}/{product_id}.html"
        else:
            url = ""

        # Marca y cantidad
        marca = URL_MARCA_OVERRIDE.get(product_id, extraer_marca(nombre))
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
            "tienda": "Cruz Verde",
            "fecha_extraccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    except Exception as e:
        print(f"  AVISO: Error procesando hit: {e}")
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
    Funcion principal que ejecuta el scraping de Cruz Verde.

    1. Itera sobre las queries de busqueda
    2. Pagina cada query hasta obtener todos los resultados
    3. Deduplica por product_id
    4. Guarda en CSV
    """
    print("=" * 60)
    print("SCRAPER CRUZ VERDE - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Queries: {len(QUERIES)}")
    print()

    todos_los_productos = []
    product_ids_vistos = set()

    for idx_query, query_config in enumerate(QUERIES, 1):
        query = query_config["q"]
        refine = query_config.get("refine")
        print(f"\n[Query {idx_query}/{len(QUERIES)}] q={query}" + (f" refine={refine}" if refine else ""))
        print("-" * 60)

        start = 0

        while True:
            data = buscar_productos_api(query, count=PRODUCTOS_POR_PAGINA, start=start, refine=refine)
            if not data:
                print("  No se pudo obtener datos. Saltando.")
                break

            hits = data.get("hits", [])
            total = data.get("total", 0)

            print(f"  Resultados: {len(hits)} hits (total: {total})")

            if not hits:
                break

            nuevos = 0
            for hit in hits:
                product_id = hit.get("product_id", "")

                # Deduplicar por product_id
                if product_id in product_ids_vistos:
                    continue

                producto = procesar_hit(hit)
                if producto:
                    product_ids_vistos.add(product_id)
                    todos_los_productos.append(producto)
                    nuevos += 1

            print(f"  Nuevos productos agregados: {nuevos}")

            # Avanzar paginacion
            start += len(hits)
            if start >= total:
                break

            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

        # Pausa entre queries
        if idx_query < len(QUERIES):
            time.sleep(PAUSA_ENTRE_PAGINAS)

    print(f"\n  Total de productos extraidos (deduplicados): {len(todos_los_productos)}")

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
