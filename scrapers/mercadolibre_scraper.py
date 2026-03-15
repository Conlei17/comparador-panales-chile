"""
Scraper para MercadoLibre Chile (https://listado.mercadolibre.cl)
Extrae productos de panales, toallitas humedas y formulas infantiles.

MercadoLibre tiene un challenge SHA-256 proof-of-work anti-bot que se
resuelve programaticamente con hashlib en ~300ms, sin necesidad de
Selenium ni headless browser.

Estrategia:
1. Hacer request inicial y detectar si hay challenge (cookie _bmstate)
2. Resolver challenge SHA-256 (encontrar nonce tal que sha256(seed+nonce)
   empiece con N ceros)
3. Parsear HTML con selectores CSS de la pagina de listado
4. Paginar con parametro _Desde_49, _Desde_97, etc.
5. Deduplicar por MLC ID extraido de la URL del producto
"""

import hashlib
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import unquote, quote

import requests
from bs4 import BeautifulSoup

try:
    from scrapers.common import (limpiar_precio, extraer_marca, extraer_cantidad,
                                  calcular_precio_por_unidad, guardar_csv)
except ImportError:
    from common import (limpiar_precio, extraer_marca, extraer_cantidad,
                        calcular_precio_por_unidad, guardar_csv)

# --- CONFIGURACION ---

# URL base para busquedas en MercadoLibre Chile
URL_BASE = "https://listado.mercadolibre.cl"

# Carpeta donde se guardara el CSV con los resultados
CARPETA_DATOS = os.path.join(os.path.dirname(__file__), "..", "data")

# Nombre del archivo de salida
ARCHIVO_SALIDA = "mercadolibre_precios.csv"

# Headers HTTP
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}

# Tiempo maximo de espera por cada peticion (en segundos)
TIMEOUT = 20

# Pausa entre peticiones para no sobrecargar el servidor (en segundos)
# MercadoLibre es agresivo con rate limiting — pausas cortas causan
# redirect a account-verification (CAPTCHA). 4s es un buen balance.
PAUSA_ENTRE_PAGINAS = 4

# Maximo de productos por query (para evitar ruido en paginas lejanas)
MAX_PRODUCTOS_POR_QUERY = 500

# Incremento de paginacion de MercadoLibre (48 productos por pagina)
INCREMENTO_PAGINACION = 48

# Queries de busqueda para productos relevantes
QUERIES = [
    "panales-bebe",
    "toallitas-humedas-bebe",
    "formula-infantil",
]

# Palabras clave para excluir productos no relevantes
EXCLUIR = [
    # Adulto / incontinencia
    "adulto", "incontinencia", "plenitud", "cotidian", "tena",
    "ladysoft", "emumed", "emuprotect", "proactive",
    # Mascotas
    "perro", "gato", "mascota",
    # Accesorios (no son panales/toallitas/formulas)
    "pañalero", "torta de pañales", "bolsa para pañales",
    "calentador", "dispensador", "basurero", "sangenic",
    "twist & click", "contenedor de pañales",
    # Cosmeticos / otros
    "crema", "colonia", "shampoo", "jabon", "jabón", "talco",
    "desmaquillant", "micelar", "antibacterial",
    # Suplementos (no formulas infantiles estandar)
    "pediasure", "ensure",
]


def resolver_challenge(session):
    """
    Resuelve el challenge SHA-256 proof-of-work de MercadoLibre.

    La cookie _bmstate contiene 'seed;difficulty;...' (URL-encoded con %3B).
    Se debe encontrar un nonce tal que sha256(seed + str(nonce)) empiece
    con `difficulty` ceros en hex. El resultado se setea en la cookie _bmc
    con formato 'seed;nonce', igual que hace el JS del challenge page.

    Retorna True si se resolvio el challenge, False si no habia challenge.
    """
    bmstate_raw = session.cookies.get("_bmstate")
    if not bmstate_raw:
        return False

    try:
        bmstate = unquote(bmstate_raw)
        partes = bmstate.split(";")
        if len(partes) < 2:
            return False

        seed = partes[0]
        difficulty = int(partes[1])
    except (ValueError, IndexError):
        return False

    print(f"  Resolviendo challenge SHA-256 (difficulty={difficulty})...")

    # Si difficulty es 0, la respuesta es nonce=0 directamente
    if difficulty == 0:
        nonce = 0
    else:
        prefijo_requerido = "0" * difficulty
        nonce = None
        for n in range(10_000_000):
            candidato = seed + str(n)
            digest = hashlib.sha256(candidato.encode()).hexdigest()
            if digest.startswith(prefijo_requerido):
                nonce = n
                break

        if nonce is None:
            print("  AVISO: No se pudo resolver el challenge")
            return False

    print(f"  Challenge resuelto: nonce={nonce}")

    # Setear cookie _bmc con formato "seed;nonce" URL-encoded (como hace el JS)
    respuesta = f"{seed};{nonce}"
    session.cookies.set("_bmc", quote(respuesta, safe=""),
                        domain=".mercadolibre.cl", path="/")
    return True


def obtener_pagina_ml(session, url):
    """
    Hace un GET a MercadoLibre con la session (que mantiene cookies).
    Si recibe un challenge page, lo resuelve y reintenta.

    Retorna BeautifulSoup o None.
    Retorna "RATE_LIMITED" (string) si MercadoLibre bloqueo nuestra IP.
    """
    for intento in range(3):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT,
                               allow_redirects=False)

            # Detectar rate limit: redirect a account-verification (CAPTCHA)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if "account-verification" in location:
                    print("  BLOQUEADO: MercadoLibre requiere CAPTCHA (rate limit).")
                    print("  Espera unas horas antes de volver a ejecutar.")
                    return "RATE_LIMITED"
                # Seguir otros redirects normalmente
                resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)

            # Detectar challenge page: HTML corto con spinner y verifyChallenge()
            if resp.status_code == 200 and "verifyChallenge" in resp.text:
                print("  Challenge detectado, resolviendo...")
                resuelto = resolver_challenge(session)
                if resuelto:
                    time.sleep(0.3)
                    resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                    # Si sigue siendo challenge, reintentar
                    if "verifyChallenge" in resp.text:
                        print("  Challenge persiste despues de resolver, reintentando...")
                        time.sleep(1)
                        continue

            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code} para {url}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    espera = 2 ** (intento + 1)
                    print(f"  Reintentando en {espera}s...")
                    time.sleep(espera)
                    continue
                return None

            # Verificar que el HTML tiene contenido real (no una pagina vacia)
            if "account-verification" in resp.url:
                print("  BLOQUEADO: Redirigido a account-verification.")
                return "RATE_LIMITED"

            return BeautifulSoup(resp.text, "lxml")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            espera = 2 ** (intento + 1)
            print(f"  {type(e).__name__}, reintentando en {espera}s...")
            time.sleep(espera)

    print(f"  ERROR: 3 reintentos fallidos para {url}")
    return None


def extraer_total_resultados(soup):
    """
    Extrae el total de resultados de la pagina de busqueda.
    Selector: .ui-search-search-result__quantity-results
    """
    elem = soup.select_one(".ui-search-search-result__quantity-results")
    if elem:
        texto = elem.get_text(strip=True)
        match = re.search(r"[\d.,]+", texto)
        if match:
            return int(match.group().replace(".", "").replace(",", ""))
    return None


def extraer_mlc_id(url):
    """Extrae el MLC ID de una URL de producto de MercadoLibre."""
    match = re.search(r"MLC[- ]?(\d+)", url)
    if match:
        return f"MLC{match.group(1)}"
    return None


def extraer_productos(soup):
    """
    Extrae productos del HTML de una pagina de listado de MercadoLibre.

    Selectores CSS validados:
    - Productos: .ui-search-result
    - Titulo: .poly-component__title
    - Precio: .andes-money-amount__fraction (dentro de .poly-price__current)
    - Precio original: .andes-money-amount--previous .andes-money-amount__fraction
    - Imagen: img (atributo data-src o src)
    - URL: a[href*="mercadolibre.cl/"]
    """
    productos = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    contenedores = soup.select(".ui-search-result")
    if not contenedores:
        contenedores = soup.select(".ui-search-layout__item")

    for contenedor in contenedores:
        try:
            # --- NOMBRE ---
            titulo_elem = contenedor.select_one(".poly-component__title")
            if not titulo_elem:
                titulo_elem = contenedor.select_one("h2")
            nombre = titulo_elem.get_text(strip=True) if titulo_elem else None

            if not nombre or len(nombre) < 5:
                continue

            # --- FILTRO DE EXCLUSION ---
            nombre_lower = nombre.lower()
            if any(palabra in nombre_lower for palabra in EXCLUIR):
                continue

            # --- URL ---
            # Preferir links directos (www.mercadolibre.cl) sobre tracking (click1.)
            link_directo = contenedor.select_one('a[href*="www.mercadolibre.cl/"]')
            link_elem = link_directo or contenedor.select_one('a[href*="mercadolibre.cl/"]')
            if not link_elem:
                link_elem = contenedor.select_one("a[href]")
            url = link_elem.get("href", "") if link_elem else ""

            # Limpiar tracking params de la URL
            if "?" in url:
                url = url.split("?")[0]

            # --- PRECIO ACTUAL ---
            precio = None
            precio_container = contenedor.select_one(".poly-price__current")
            if precio_container:
                fraccion = precio_container.select_one(".andes-money-amount__fraction")
                if fraccion:
                    precio = limpiar_precio(fraccion.get_text(strip=True))

            if not precio:
                fraccion = contenedor.select_one(".andes-money-amount__fraction")
                if fraccion:
                    precio = limpiar_precio(fraccion.get_text(strip=True))

            # --- PRECIO ORIGINAL (lista) ---
            precio_lista = None
            prev_container = contenedor.select_one(".andes-money-amount--previous")
            if prev_container:
                fraccion_prev = prev_container.select_one(".andes-money-amount__fraction")
                if fraccion_prev:
                    precio_lista = limpiar_precio(fraccion_prev.get_text(strip=True))

            # Solo guardar precio_lista si es mayor al precio actual
            if precio_lista and precio and precio_lista <= precio:
                precio_lista = None

            # --- IMAGEN ---
            img_elem = contenedor.select_one("img")
            imagen = None
            if img_elem:
                imagen = img_elem.get("data-src") or img_elem.get("src")

            # --- MARCA ---
            marca = extraer_marca(nombre)

            # --- CANTIDAD ---
            cantidad = extraer_cantidad(nombre)

            # --- PRECIO POR UNIDAD ---
            precio_por_unidad = calcular_precio_por_unidad(precio, cantidad, nombre)

            # URLs de tracking (click1.mercadolibre) no sirven como ID
            # unico en la DB. Generar URL sintetica unica.
            if "click1.mercadolibre" in url or url.endswith("/count"):
                unique = hashlib.md5(
                    f"{nombre}|{precio}|{imagen}".encode()
                ).hexdigest()[:8]
                slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")[:70]
                url = f"https://www.mercadolibre.cl/p/{slug}-{unique}"

            producto = {
                "nombre": nombre,
                "precio": precio,
                "marca": marca,
                "cantidad_unidades": cantidad,
                "precio_por_unidad": precio_por_unidad,
                "imagen": imagen,
                "precio_lista": precio_lista,
                "url": url,
                "tienda": "MercadoLibre",
                "fecha_extraccion": timestamp,
                "en_stock": 1,
            }
            productos.append(producto)

        except Exception as e:
            print(f"  AVISO: Error procesando un producto: {e}")
            continue

    return productos


def seleccionar_mejor_precio(productos):
    """
    Dado que MercadoLibre tiene muchos sellers vendiendo el mismo producto,
    agrupa por nombre normalizado y se queda con el de menor precio.

    Esto maximiza la captura (se scrapea todo) y muestra siempre el mejor
    precio disponible para cada producto unico.
    """
    por_nombre = defaultdict(list)
    for p in productos:
        clave = p["nombre"].strip().lower()
        por_nombre[clave].append(p)

    mejores = []
    for nombre, variantes in por_nombre.items():
        con_precio = [v for v in variantes if v["precio"] is not None]
        if con_precio:
            mejor = min(con_precio, key=lambda x: x["precio"])
        else:
            mejor = variantes[0]
        mejores.append(mejor)

    return mejores


def main():
    """
    Funcion principal que ejecuta el scraping de MercadoLibre Chile.

    1. Para cada query de busqueda, obtiene la primera pagina
    2. Pagina con _Desde_49, _Desde_97, etc. hasta agotar resultados
    3. Deduplica por MLC ID (mismo listing en distintas paginas)
    4. Selecciona el mejor precio por producto unico (multiples sellers)
    5. Guarda en CSV
    """
    print("=" * 60)
    print("SCRAPER MERCADOLIBRE - Comparador de Panales Chile")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Queries: {len(QUERIES)}")
    print()

    session = requests.Session()
    todos_los_productos = []
    ids_vistos = set()  # MLC IDs para dedup de listings repetidos entre paginas

    for idx_query, query in enumerate(QUERIES, 1):
        print(f"\n[Query {idx_query}/{len(QUERIES)}] {query}")
        print("-" * 60)

        productos_query = 0
        offset = 0
        pagina = 1

        while True:
            # Construir URL con paginacion
            if offset == 0:
                url = f"{URL_BASE}/{query}"
            else:
                url = f"{URL_BASE}/{query}_Desde_{offset + 1}"

            print(f"\n  Pagina {pagina} (offset {offset})...")
            soup = obtener_pagina_ml(session, url)

            if soup == "RATE_LIMITED":
                print("  Abortando todo el scraping por rate limit.")
                pagina = -1  # Señal para salir del loop de queries
                break

            if not soup:
                print("  No se pudo obtener la pagina. Terminando query.")
                break

            # En la primera pagina, mostrar total de resultados
            if pagina == 1:
                total = extraer_total_resultados(soup)
                if total:
                    print(f"  Total resultados para '{query}': {total:,}")

            productos_pagina = extraer_productos(soup)
            print(f"  Productos extraidos: {len(productos_pagina)}")

            if not productos_pagina:
                print("  Sin productos en esta pagina. Terminando query.")
                break

            # Dedup solo por MLC ID: evita contar el mismo listing
            # que aparece en multiples paginas de paginacion.
            # NO deduplicamos por nombre aqui — eso lo hace
            # seleccionar_mejor_precio() al final.
            nuevos = 0
            for producto in productos_pagina:
                mlc_id = extraer_mlc_id(producto["url"])
                if mlc_id and mlc_id in ids_vistos:
                    continue
                if mlc_id:
                    ids_vistos.add(mlc_id)
                todos_los_productos.append(producto)
                nuevos += 1

            productos_query += nuevos
            print(f"  Nuevos (sin duplicados de listing): {nuevos}")

            # Verificar limites
            if productos_query >= MAX_PRODUCTOS_POR_QUERY:
                print(f"  Limite de {MAX_PRODUCTOS_POR_QUERY} productos alcanzado.")
                break

            # Siguiente pagina
            offset += INCREMENTO_PAGINACION
            pagina += 1

            time.sleep(PAUSA_ENTRE_PAGINAS)

        print(f"\n  Productos acumulados para '{query}': {productos_query}")

        # Si fue rate limited, salir de todas las queries
        if pagina == -1:
            break

        # Pausa entre queries
        if idx_query < len(QUERIES):
            time.sleep(PAUSA_ENTRE_PAGINAS)

    print(f"\n  Total productos capturados: {len(todos_los_productos)}")

    # Seleccionar mejor precio por producto unico
    productos_finales = seleccionar_mejor_precio(todos_los_productos)
    print(f"  Productos unicos (mejor precio por nombre): {len(productos_finales)}")

    # Guardar en CSV
    print("\n[Guardando] Datos en CSV...")
    ruta_csv = os.path.join(CARPETA_DATOS, ARCHIVO_SALIDA)
    guardar_csv(productos_finales, ruta_csv)

    # Resumen final
    print()
    print("=" * 60)
    print("RESUMEN")
    print("=" * 60)
    print(f"Productos capturados: {len(todos_los_productos)}")
    print(f"Productos unicos (mejor precio): {len(productos_finales)}")

    con_precio = sum(1 for p in productos_finales if p["precio"] is not None)
    print(f"Con precio: {con_precio}")
    print(f"Sin precio: {len(productos_finales) - con_precio}")

    con_cantidad = sum(1 for p in productos_finales if p["cantidad_unidades"] is not None)
    print(f"Con cantidad: {con_cantidad}")

    marcas = set(p["marca"] for p in productos_finales if p["marca"])
    print(f"Marcas encontradas: {', '.join(sorted(marcas))}")

    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
