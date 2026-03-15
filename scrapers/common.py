"""
Funciones comunes compartidas entre todos los scrapers.

Centraliza la logica duplicada de:
- Limpieza de precios
- Deteccion de marcas
- Extraccion de cantidad de unidades
- Deteccion de formulas infantiles
- Guardado de CSV
"""

import csv
import os
import re


# --- CONSTANTES ---

# Marcas conocidas de panales, toallitas y formulas en Chile
MARCAS_CONOCIDAS = [
    "Pampers", "Huggies", "Babysec", "Cotidian", "Goodnites",
    "Win", "Tutte", "Pequenin", "Tena", "Plenitud",
    "Ladysoft", "Aiwibi", "Emubaby", "Moltex", "Chelino",
    "Bambo", "Pingo", "Naty", "Eco Boom", "Biobaby",
    "Nan", "Similac", "Nidal", "Enfamil", "S-26", "Alula",
    "Nutrilon", "Blemil", "Nestogen",
    "Johnsons", "Johnson",
    "WaterWipes", "Waterwipes",
    "Nenitos", "Neniwipes", "Merries",
    "Terra", "Althera", "Twistshake",
    "Cell Skin", "Simond",
    "Emuwipes", "Toddler", "Simonds",
    "Aqua Baby", "Bubu",
]

# Sublineas de producto que identifican marca cuando el nombre no la contiene
SUBLINEAS_MARCA = [
    ("premium care", "Pampers"),
    ("confort sec", "Pampers"),
    ("super premium", "Babysec"),
    ("ultrasuave", "Emubaby"),
]

# Palabras clave para detectar formulas infantiles
FORMULAS_KEYWORDS = [
    "fórmula", "formula", "leche infantil", "leche en polvo",
    "nan ", "nido", "similac", "enfamil", "s-26", "s26",
    "alula", "nidal", "nutrilon", "blemil",
]

# Columnas estandar del CSV de salida
COLUMNAS_CSV = [
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


# --- FUNCIONES ---

def limpiar_precio(texto_precio):
    """
    Convierte un texto de precio como "$16.690" en un numero entero: 16690.
    Tambien acepta valores int/float directamente.

    Retorna:
        int o None si no se pudo convertir.
    """
    if not texto_precio:
        return None

    if isinstance(texto_precio, (int, float)):
        return int(texto_precio)

    solo_numeros = re.sub(r"[^\d]", "", str(texto_precio))

    if solo_numeros:
        return int(solo_numeros)
    return None


def extraer_marca(nombre_producto, marca_api=None):
    """
    Intenta detectar la marca del producto.

    Prioriza marca_api (de la API de la tienda) si esta disponible,
    luego busca marcas conocidas en el nombre, luego sublineas,
    y finalmente usa la primera palabra del nombre.

    Args:
        nombre_producto: nombre del producto
        marca_api: marca proporcionada por la API de la tienda (opcional)

    Retorna:
        str con la marca detectada.
    """
    if marca_api and marca_api.strip() and marca_api.lower() not in ("", "sin marca"):
        marca_api = marca_api.strip()
        for marca in MARCAS_CONOCIDAS:
            if marca.lower() == marca_api.lower():
                return marca
        return marca_api

    nombre_lower = nombre_producto.lower()
    for marca in MARCAS_CONOCIDAS:
        if marca.lower() in nombre_lower:
            return marca

    for sublinea, marca in SUBLINEAS_MARCA:
        if sublinea in nombre_lower:
            return marca

    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def es_formula(nombre):
    """Detecta si el producto es una formula infantil."""
    nombre_lower = nombre.lower()
    return any(kw in nombre_lower for kw in FORMULAS_KEYWORDS)


def extraer_cantidad(nombre_producto):
    """
    Intenta extraer la cantidad de unidades del nombre del producto.
    Para formulas infantiles, extrae el peso en gramos.

    Retorna:
        int o None si no se encontro cantidad.
    """
    # Para formulas: extraer peso en gramos o kilogramos
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


def calcular_precio_por_unidad(precio, cantidad, nombre):
    """
    Calcula el precio por unidad (o precio por kg para formulas).

    Retorna:
        int o None si no se pudo calcular.
    """
    if not precio or not cantidad or cantidad <= 0:
        return None
    if es_formula(nombre):
        return round(precio / cantidad * 1000)
    return round(precio / cantidad)


def guardar_csv(productos, ruta_archivo):
    """
    Guarda la lista de productos en un archivo CSV.

    Si el archivo ya existe, lo sobreescribe con datos frescos.
    """
    if not productos:
        print("No hay productos para guardar.")
        return

    os.makedirs(os.path.dirname(ruta_archivo), exist_ok=True)

    with open(ruta_archivo, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_CSV)
        escritor.writeheader()
        escritor.writerows(productos)

    print(f"\nDatos guardados en: {ruta_archivo}")
    print(f"Total de productos guardados: {len(productos)}")
