"""
Scraper para Liquimax (https://www.liquimax.cl)
Extrae productos de panales de la seccion de panales del sitio.

Liquimax usa la plataforma Bootic. Los productos se listan en:
  https://www.liquimax.cl/collections/panales
con paginacion: /collections/panales/2, /collections/panales/3, etc.
"""

import csv
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# --- CONFIGURACION ---

# URL base de la coleccion de panales
URL_BASE = "https://www.liquimax.cl/collections/panales"

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "liquimax_precios.csv"

# Headers que simulan un navegador real para que el sitio no bloquee las peticiones
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


def obtener_pagina(url):
    """
    Descarga el HTML de una URL y lo convierte en un objeto BeautifulSoup.

    Retorna:
        BeautifulSoup o None si hubo un error.
    """
    try:
        print(f"  Descargando: {url}")
        respuesta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)

        # Lanza un error si el codigo HTTP indica un problema (404, 500, etc.)
        respuesta.raise_for_status()

        # Parseamos el HTML con lxml (mas rapido que el parser por defecto)
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
    """
    Detecta cuantas paginas de productos hay mirando los links de paginacion.

    En Bootic, la paginacion se ve como:
        « Anterior 1 2 3 Siguiente »
    Buscamos el numero mas alto entre esos links.
    """
    # Buscamos links dentro de la navegacion de paginacion
    paginacion = soup.select("nav.pagination a, .pagination a, ul.pagination a")

    max_pagina = 1
    for link in paginacion:
        texto = link.get_text(strip=True)
        # Si el texto del link es un numero, lo comparamos con el maximo
        if texto.isdigit():
            numero = int(texto)
            if numero > max_pagina:
                max_pagina = numero

    return max_pagina


def limpiar_precio(texto_precio):
    """
    Convierte un texto de precio como "$16.690" en un numero entero: 16690.

    Retorna:
        int o None si no se pudo convertir.
    """
    if not texto_precio:
        return None

    # Eliminamos todo excepto digitos (sacamos $, puntos, espacios, etc.)
    solo_numeros = re.sub(r"[^\d]", "", texto_precio)

    if solo_numeros:
        return int(solo_numeros)
    return None


def extraer_marca(nombre_producto):
    """
    Intenta detectar la marca del producto a partir de su nombre.

    Busca marcas conocidas de panales en Chile al inicio del nombre.
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
    ]

    nombre_lower = nombre_producto.lower()
    for marca in marcas_conocidas:
        if marca.lower() in nombre_lower:
            return marca

    # Si no encontramos una marca conocida, usamos la primera palabra
    primera_palabra = nombre_producto.split()[0] if nombre_producto.split() else "Desconocida"
    return primera_palabra


def extraer_cantidad(nombre_producto):
    """
    Intenta extraer la cantidad de unidades del nombre del producto.

    Busca patrones como "52 Unidades", "128u", "48 Un", etc.
    """
    # Patron: numero seguido de "unidades", "un", "u", "und"
    patron = re.search(r"(\d+)\s*(?:unidades|unid|und|un\b|u\b)", nombre_producto, re.IGNORECASE)
    if patron:
        return int(patron.group(1))

    # Patron alternativo: "x" seguido de numero (ej: "x48")
    patron_x = re.search(r"x\s*(\d+)", nombre_producto, re.IGNORECASE)
    if patron_x:
        return int(patron_x.group(1))

    return None


def extraer_productos(soup):
    """
    Extrae la informacion de todos los productos de una pagina.

    Busca los contenedores de productos en el HTML y extrae:
    - Nombre del producto
    - Precio
    - Marca
    - Cantidad de unidades
    - URL del producto

    Retorna:
        Lista de diccionarios, cada uno con los datos de un producto.
    """
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Bootic usa .product-with-dynamic-price como contenedor de cada producto
    # Si no los encuentra, intentamos con otros selectores comunes
    contenedores = soup.select(".product-with-dynamic-price")

    if not contenedores:
        # Intentamos selectores alternativos
        contenedores = soup.select(".product-item, .product-card, .grid-item")

    if not contenedores:
        print("  AVISO: No se encontraron contenedores de productos en esta pagina.")
        # Como ultimo recurso, buscamos todos los links que apunten a /products/
        links_productos = soup.select('a[href*="/products/"]')
        # Eliminamos duplicados basandonos en el href
        urls_vistas = set()
        for link in links_productos:
            href = link.get("href", "")
            if href not in urls_vistas and link.get_text(strip=True):
                urls_vistas.add(href)
                nombre = link.get_text(strip=True)
                if len(nombre) > 5:  # Filtrar links muy cortos que no son nombres
                    img_elem_fb = link.find_parent().select_one("img") if link.find_parent() else None
                    imagen_fb = img_elem_fb.get("src") or img_elem_fb.get("data-src") if img_elem_fb else None
                    producto = {
                        "nombre": nombre,
                        "precio": None,
                        "marca": extraer_marca(nombre),
                        "cantidad_unidades": extraer_cantidad(nombre),
                        "precio_por_unidad": None,
                        "imagen": imagen_fb,
                        "precio_lista": None,
                        "url": f"https://www.liquimax.cl{href}" if href.startswith("/") else href,
                        "tienda": "Liquimax",
                        "fecha_extraccion": timestamp,
                    }
                    productos.append(producto)
        return productos

    # Procesamos cada contenedor de producto
    for contenedor in contenedores:
        try:
            # --- NOMBRE DEL PRODUCTO ---
            # Buscamos en links, titulos h2/h3, o spans con clase de titulo
            nombre_elem = (
                contenedor.select_one("h2 a, h3 a, .product-title a, .product-name a, a[title]")
            )

            if nombre_elem:
                nombre = nombre_elem.get("title") or nombre_elem.get_text(strip=True)
            else:
                # Intentamos obtener el nombre de cualquier link a /products/
                link_prod = contenedor.select_one('a[href*="/products/"]')
                nombre = link_prod.get_text(strip=True) if link_prod else None

            if not nombre or len(nombre) < 3:
                continue  # Saltamos productos sin nombre valido

            # --- URL DEL PRODUCTO ---
            link_elem = contenedor.select_one('a[href*="/products/"]')
            if link_elem:
                href = link_elem.get("href", "")
                url = f"https://www.liquimax.cl{href}" if href.startswith("/") else href
            else:
                url = ""

            # --- PRECIO ---
            # Buscamos el precio en varios selectores posibles
            precio = None
            selectores_precio = [
                ".price",
                ".product-price",
                ".current-price",
                "span.money",
                "[data-price]",
            ]
            for selector in selectores_precio:
                precio_elem = contenedor.select_one(selector)
                if precio_elem:
                    precio = limpiar_precio(precio_elem.get_text())
                    if precio:
                        break

            # Si no encontramos precio con selectores, buscamos patron de precio en texto
            if not precio:
                texto_completo = contenedor.get_text()
                precio_match = re.search(r"\$[\d.,]+", texto_completo)
                if precio_match:
                    precio = limpiar_precio(precio_match.group())

            # --- MARCA ---
            marca_elem = contenedor.select_one(".product-vendor, .vendor, .brand")
            if marca_elem:
                marca = marca_elem.get_text(strip=True)
            else:
                marca = extraer_marca(nombre)

            # --- CANTIDAD ---
            cantidad = extraer_cantidad(nombre)

            # --- PRECIO POR UNIDAD ---
            precio_por_unidad = None
            if precio and cantidad and cantidad > 0:
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
                "tienda": "Liquimax",
                "fecha_extraccion": timestamp,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def guardar_csv(productos, ruta_archivo):
    """
    Guarda la lista de productos en un archivo CSV.

    Si el archivo ya existe, lo sobreescribe con datos frescos.
    """
    if not productos:
        print("No hay productos para guardar.")
        return

    # Creamos la carpeta si no existe
    os.makedirs(os.path.dirname(ruta_archivo), exist_ok=True)

    # Definimos las columnas del CSV
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
        escritor.writeheader()  # Escribe la fila de encabezados
        escritor.writerows(productos)  # Escribe todos los productos

    print(f"\nDatos guardados en: {ruta_archivo}")
    print(f"Total de productos guardados: {len(productos)}")


def main():
    """
    Funcion principal que ejecuta todo el proceso de scraping.

    1. Descarga la primera pagina para detectar cuantas paginas hay
    2. Recorre todas las paginas extrayendo productos
    3. Guarda todo en un CSV
    """
    print("=" * 60)
    print("SCRAPER LIQUIMAX - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"URL: {URL_BASE}")
    print()

    # Paso 1: Descargar la primera pagina
    print("[1/3] Descargando primera pagina para detectar paginacion...")
    soup_primera = obtener_pagina(URL_BASE)

    if not soup_primera:
        print("ERROR FATAL: No se pudo descargar la pagina principal. Abortando.")
        return

    # Paso 2: Detectar cuantas paginas hay
    total_paginas = detectar_total_paginas(soup_primera)
    print(f"  Paginas detectadas: {total_paginas}")
    print()

    # Paso 3: Extraer productos de todas las paginas
    print("[2/3] Extrayendo productos de todas las paginas...")
    todos_los_productos = []

    for num_pagina in range(1, total_paginas + 1):
        print(f"\n--- Pagina {num_pagina} de {total_paginas} ---")

        if num_pagina == 1:
            # Ya tenemos la primera pagina descargada
            soup = soup_primera
        else:
            # Descargamos las paginas siguientes
            url_pagina = f"{URL_BASE}/{num_pagina}"
            soup = obtener_pagina(url_pagina)

            if not soup:
                print(f"  No se pudo descargar la pagina {num_pagina}. Continuando...")
                continue

        # Extraemos los productos de esta pagina
        productos_pagina = extraer_productos(soup)
        print(f"  Productos encontrados en esta pagina: {len(productos_pagina)}")

        todos_los_productos.extend(productos_pagina)

        # Esperamos un poco antes de la siguiente peticion (buena practica)
        if num_pagina < total_paginas:
            print(f"  Esperando {PAUSA_ENTRE_PAGINAS}s antes de la siguiente pagina...")
            time.sleep(PAUSA_ENTRE_PAGINAS)

    print(f"\n  Total de productos extraidos: {len(todos_los_productos)}")

    # Paso 4: Guardar en CSV
    print("\n[3/3] Guardando datos en CSV...")
    ruta_csv = os.path.join(CARPETA_DATOS, ARCHIVO_SALIDA)
    guardar_csv(todos_los_productos, ruta_csv)

    # Resumen final
    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Productos totales: {len(todos_los_productos)}")

    # Contamos productos con precio encontrado
    con_precio = sum(1 for p in todos_los_productos if p["precio"] is not None)
    print(f"Con precio: {con_precio}")
    print(f"Sin precio: {len(todos_los_productos) - con_precio}")

    # Mostramos las marcas encontradas
    marcas = set(p["marca"] for p in todos_los_productos if p["marca"])
    print(f"Marcas encontradas: {', '.join(sorted(marcas))}")

    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# Este bloque permite ejecutar el scraper directamente con:
#   python scrapers/liquimax_scraper.py
if __name__ == "__main__":
    main()
