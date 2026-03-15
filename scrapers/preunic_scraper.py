"""
Scraper para Preunic (https://preunic.cl)
Extrae productos de panales y toallitas humedas.

Preunic usa Spree Commerce con una API REST publica (v2 Storefront)
que retorna JSON:API sin autenticacion.

Endpoint: https://backend.preunic.cl/api/v2/storefront/products
"""

import csv
import os
import re
import time
from datetime import datetime

try:
    from scrapers.http_utils import obtener_json
except ImportError:
    from http_utils import obtener_json

# --- CONFIGURACION ---

# Endpoint de la API Spree Storefront
API_URL = "https://backend.preunic.cl/api/v2/storefront/products"

# Taxons (categorias) a scrapear
TAXONS = [
    {"id": 913, "nombre": "Panales para Bebe y Nino"},
    {"id": 914, "nombre": "Toallitas Humedas"},
]

# Productos por pagina (max soportado por la API)
PRODUCTOS_POR_PAGINA = 100

# Palabras clave para filtrar productos que no corresponden
EXCLUIR = [
    "adulto", "adultos", "incontinencia",
    "crema", "talco", "shampoo", "jabon", "colonia",
    "mamadera", "chupo", "chupete",
]

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "preunic_precios.csv"

# Headers HTTP
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/vnd.api+json",
}

# Timeout por peticion (segundos)
TIMEOUT = 20

# Pausa entre peticiones (segundos)
PAUSA_ENTRE_PAGINAS = 2

# URL base para construir URLs de productos
URL_BASE_PRODUCTO = "https://preunic.cl/products"

# Marcas conocidas para deteccion
MARCAS_CONOCIDAS = [
    "Pampers", "Huggies", "Babysec", "Cotidian", "Goodnites",
    "Win", "Tutte", "Pequenin", "Tena", "Plenitud",
    "Ladysoft", "Aiwibi", "Emubaby", "Moltex", "Chelino",
    "Bambo", "Pingo", "Naty", "Eco Boom", "Biobaby",
    "Nenitos", "Simmons", "Coombs",
    "Johnsons", "Johnson",
    "WaterWipes", "Waterwipes",
    "Emuwipes", "Toddler", "Simonds",
]

FORMULAS_KEYWORDS = [
    "fórmula", "formula", "leche infantil", "leche en polvo",
    "nan ", "nido", "similac", "enfamil", "s-26", "s26",
    "alula", "nidal", "nutrilon", "blemil",
]


def es_formula(nombre):
    """Detecta si el producto es una formula infantil."""
    nombre_lower = nombre.lower()
    return any(kw in nombre_lower for kw in FORMULAS_KEYWORDS)


def extraer_marca(nombre_producto, marca_api=None):
    """
    Detecta la marca del producto.
    Prioriza la marca de la API, luego busca en el nombre.
    """
    if marca_api and marca_api.strip() and marca_api.lower() != "sin marca":
        marca_api = marca_api.strip()
        # Normalizar mayusculas: buscar en marcas conocidas por match case-insensitive
        for marca in MARCAS_CONOCIDAS:
            if marca.lower() == marca_api.lower():
                return marca
        # title() capitaliza despues de apostrofes; preservar original
        return marca_api

    nombre_lower = nombre_producto.lower()
    for marca in MARCAS_CONOCIDAS:
        if marca.lower() in nombre_lower:
            return marca

    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def extraer_cantidad(nombre_producto):
    """
    Extrae la cantidad de unidades del nombre del producto.
    Para formulas infantiles, extrae el peso en gramos.
    """
    if es_formula(nombre_producto):
        match_kg = re.search(r"(\d+(?:[.,]\d+)?)\s*kg\b", nombre_producto, re.IGNORECASE)
        if match_kg:
            return int(float(match_kg.group(1).replace(",", ".")) * 1000)
        match_gramos = re.search(r"(\d+)\s*(?:g|grs|gr|gramos)\b", nombre_producto, re.IGNORECASE)
        if match_gramos:
            return int(match_gramos.group(1))

    patrones = [
        r"(\d+)\s*(?:pa[ñn]ales)\b",
        r"(\d+)\s*(?:toallitas|toallas)\b",
        r"(\d+)\s*(?:unidades|unid|und|uds)\b",
        r"(\d+)\s*(?:hojas)\b",
        r"x\s*(\d+)\s*(?:un|u)\b",
        r"[xX]\s*(\d+)\b",
        r"(\d+)\s*[uU]n\b",
        r"(\d+)\s*[uU]\b",
    ]
    for patron in patrones:
        match = re.search(patron, nombre_producto, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def buscar_productos_api(taxon_id, page=1):
    """
    Consulta la API Spree de Preunic para un taxon dado.

    Retorna:
        dict con la respuesta JSON:API o None si hubo error.
    """
    params = {
        "filter[taxons]": taxon_id,
        "per_page": PRODUCTOS_POR_PAGINA,
        "page": page,
        "include": "images,default_variant",
        "sort": "name",
    }

    print(f"  API: taxon={taxon_id}, page={page}, per_page={PRODUCTOS_POR_PAGINA}")
    return obtener_json(API_URL, HEADERS, params=params, timeout=TIMEOUT)


def construir_included_map(included):
    """Construye un mapa de recursos incluidos por tipo_id."""
    mapa = {}
    for item in (included or []):
        key = f"{item['type']}_{item['id']}"
        mapa[key] = item
    return mapa


def procesar_producto(producto, included_map):
    """
    Convierte un producto de la API Spree al formato estandar del proyecto.

    Retorna:
        dict con el producto en formato estandar o None si no se pudo procesar.
    """
    try:
        attrs = producto.get("attributes", {})
        nombre = attrs.get("name", "")

        if not nombre or len(nombre) < 3:
            return None

        # Filtrar productos que no corresponden
        nombre_lower = nombre.lower()
        if any(palabra in nombre_lower for palabra in EXCLUIR):
            return None

        # Precio: usar offer_price del variant si existe, sino price del producto
        precio = None
        precio_lista = None

        # Obtener default_variant para marca y offer_price
        marca_api = None
        relationships = producto.get("relationships", {})
        dv_data = relationships.get("default_variant", {}).get("data")
        if dv_data:
            variant = included_map.get(f"variant_{dv_data['id']}", {})
            variant_attrs = variant.get("attributes", {})
            marca_api = variant_attrs.get("brand")

            offer_price = variant_attrs.get("offer_price")
            if offer_price:
                offer_price = float(offer_price)
                if offer_price > 0:
                    precio = int(round(offer_price))

        # Precio regular del producto
        price_str = attrs.get("price")
        if price_str:
            precio_regular = int(round(float(price_str)))
            if precio is None:
                precio = precio_regular
            elif precio_regular > precio:
                precio_lista = precio_regular

        # Imagen
        imagen = None
        img_refs = relationships.get("images", {}).get("data", [])
        if img_refs:
            img = included_map.get(f"image_{img_refs[0]['id']}", {})
            img_attrs = img.get("attributes", {})
            # Preferir CDN (blob_styles)
            blob_styles = img_attrs.get("blob_styles", [])
            for bs in blob_styles:
                if bs.get("style") == "product":
                    imagen = bs.get("url")
                    break
            if not imagen:
                imagen = img_attrs.get("original_url")

        # URL del producto
        slug = attrs.get("slug", "")
        url = f"{URL_BASE_PRODUCTO}/{slug}" if slug else ""

        # Marca y cantidad
        marca = extraer_marca(nombre, marca_api)
        cantidad = extraer_cantidad(nombre)

        # Precio por unidad
        precio_por_unidad = None
        if precio and cantidad and cantidad > 0:
            if es_formula(nombre):
                precio_por_unidad = round(precio / cantidad * 1000)
            else:
                precio_por_unidad = round(precio / cantidad)

        en_stock = 1 if attrs.get("in_stock", True) else 0

        return {
            "nombre": nombre,
            "precio": precio,
            "marca": marca,
            "cantidad_unidades": cantidad,
            "precio_por_unidad": precio_por_unidad,
            "imagen": imagen,
            "precio_lista": precio_lista,
            "url": url,
            "tienda": "Preunic",
            "fecha_extraccion": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "en_stock": en_stock,
        }

    except Exception as e:
        print(f"  AVISO: Error procesando producto: {e}")
        return None


def guardar_csv(productos, ruta_archivo):
    """Guarda la lista de productos en un archivo CSV."""
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


def main():
    """
    Funcion principal que ejecuta el scraping de Preunic.

    1. Itera sobre los taxons (categorias)
    2. Pagina cada taxon hasta obtener todos los resultados
    3. Deduplica por slug
    4. Guarda en CSV
    """
    print("=" * 60)
    print("SCRAPER PREUNIC - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Categorias: {len(TAXONS)}")
    print()

    todos_los_productos = []
    slugs_vistos = set()

    for idx_taxon, taxon in enumerate(TAXONS, 1):
        taxon_id = taxon["id"]
        taxon_nombre = taxon["nombre"]
        print(f"\n[Categoria {idx_taxon}/{len(TAXONS)}] {taxon_nombre} (taxon={taxon_id})")
        print("-" * 60)

        page = 1

        while True:
            data = buscar_productos_api(taxon_id, page=page)
            if not data:
                print("  No se pudo obtener datos. Saltando.")
                break

            productos = data.get("data", [])
            included = data.get("included", [])
            meta = data.get("meta", {})
            total_count = meta.get("total_count", 0)
            total_pages = meta.get("total_pages", 1)

            included_map = construir_included_map(included)

            print(f"  Resultados: {len(productos)} productos (total: {total_count}, pagina {page}/{total_pages})")

            if not productos:
                break

            nuevos = 0
            for prod in productos:
                slug = prod.get("attributes", {}).get("slug", "")

                # Deduplicar por slug
                if slug in slugs_vistos:
                    continue

                producto = procesar_producto(prod, included_map)
                if producto:
                    slugs_vistos.add(slug)
                    todos_los_productos.append(producto)
                    nuevos += 1

            print(f"  Nuevos productos agregados: {nuevos}")

            # Avanzar paginacion
            if page >= total_pages:
                break
            page += 1

            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

        # Pausa entre categorias
        if idx_taxon < len(TAXONS):
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
