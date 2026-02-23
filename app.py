"""
Aplicacion web del Comparador de Panales Chile.

Permite buscar y comparar precios de panales entre tiendas chilenas
filtrando por marca, talla, tienda, precio maximo y busqueda libre.
Incluye pagina de historico de precios y seccion de consejos de ahorro.

Uso:
    python app.py

Luego abre http://localhost:8080 en tu navegador.
"""

import json
import os
import re
import sqlite3
import unicodedata
from flask import Flask, render_template, request, jsonify, Response, redirect
from urllib.parse import urlencode, urljoin

# --- CONFIGURACION ---

DIR_PROYECTO = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_DB = os.path.join(DIR_PROYECTO, "data", "precios.db")

app = Flask(__name__)

# Allowlist: productos validos deben contener al menos una de estas palabras
INCLUIR_PATRONES = [
    "%pañal%", "%panal%", "%toalla%", "%toallita%",
    "%huggies%", "%pampers%", "%babysec%",
    "%leche%", "%fórmula%", "%formula%", "%nan %", "%similac%",
    "%enfamil%", "%s-26%", "%purita%", "%nido%",
    "%splasher%", "%goodnites%", "%emubaby%",
    "%waterwipes%", "%aqua baby%", "%merries%", "%terra %",
    "%nenitos%", "%neniwipes%", "%althera%", "%cell skin%",
]

# Excluir productos de adulto (incontinencia, pañales adulto, etc.)
EXCLUIR_ADULTO = [
    "%adulto%", "%incontinencia%", "%plenitud%", "%tena %",
    "%cotidian%", "%ladysoft%", "%emumed%", "%emuprotect%",
    "%proactive%", "% win %", "%win plus%", "%win premium%",
]

# Palabras clave para detectar panales de agua
PANALES_AGUA_KEYWORDS = ["swimmer", "agua", "acuatic", "piscina", "splasher"]

# Palabras clave para detectar toallitas humedas de bebe
TOALLITAS_KEYWORDS = ["toalla húmeda", "toallas húmedas", "toalla humeda", "toallas humedas", "toallita"]

# Palabras clave para detectar formulas infantiles
FORMULAS_KEYWORDS = [
    "fórmula", "formula", "leche infantil", "leche en polvo",
    "nan ", "nido", "similac", "enfamil", "s-26", "s26",
    "alula", "nidal", "nutrilon", "blemil",
]

# Tallas en orden logico (de mas chico a mas grande)
ORDEN_TALLAS = [
    "RN", "RN+", "P", "S-M", "M", "G", "P-M",
    "XG", "G-XG", "L", "XXG", "L-XL", "XL", "XXXG",
]

# Mapeo de rango de edad del bebe a tallas de panal
EDAD_A_TALLAS = {
    "0-1 mes": ["RN", "RN+"],
    "1-3 meses": ["RN+", "P"],
    "3-6 meses": ["P", "M"],
    "6-12 meses": ["M", "G"],
    "12-18 meses": ["G", "XG"],
    "18-24 meses": ["XG", "XXG"],
    "+2 anos": ["XXG", "XXXG"],
}

# Logos de tiendas (nombre de tienda -> archivo en static/logos/)
LOGOS_TIENDAS = {
    "Liquimax": "liquimax.png",
    "Distribuidora Pepito": "pepito.png",
    "La Pañalera": "lapanalera.png",
    "Pañales Tin Tin": "tintin.png",
    "Santa Isabel": "santaisabel.png",
    "Jumbo": "jumbo.png",
    "Farmacias Ahumada": "ahumada.png",
    "Cruz Verde": "cruzverde.png",
    "Salcobrand": "salcobrand.svg",
}

# Columnas permitidas para ordenar (whitelist contra SQL injection)
ORDEN_PERMITIDO = {
    "precio_por_unidad": "CASE WHEN pr.precio_por_unidad IS NULL THEN 1 ELSE 0 END, pr.precio_por_unidad ASC, pr.precio ASC",
    "precio": "pr.precio ASC",
    "marca": "p.marca ASC, pr.precio ASC",
    "tienda": "t.nombre ASC, pr.precio ASC",
}


# --- URLs amigables: mapeo de slugs a categorias ---
CATEGORIAS_SLUG = {
    "panales": "Pañales",
    "panales-de-agua": "Pañales de Agua",
    "toallitas": "Toallitas Humedas",
    "formulas": "Fórmulas Infantiles",
}

# Inverso: categoria real -> slug
CATEGORIAS_SLUG_INV = {v: k for k, v in CATEGORIAS_SLUG.items()}


def slugify(texto):
    """Convierte texto a slug URL-friendly: 'Pañales' -> 'panales', 'RN+' -> 'rn-plus'."""
    if not texto:
        return ""
    texto = texto.strip()
    # Normalizar unicode (quitar acentos)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = texto.replace("+", "-plus")
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    texto = texto.strip("-")
    return texto


def deslugify_talla(slug):
    """Convierte slug de talla a valor real: 'talla-g' -> 'G', 'talla-rn-plus' -> 'RN+'."""
    if not slug or not slug.startswith("talla-"):
        return None
    talla_part = slug[6:]  # quitar "talla-"
    talla_part = talla_part.replace("-plus", "+")
    talla_part = talla_part.upper()
    # Validar contra tallas conocidas
    if talla_part in ORDEN_TALLAS:
        return talla_part
    return None


def deslugify_marca(slug, marcas_disponibles):
    """Busca la marca real que corresponde al slug."""
    for marca in marcas_disponibles:
        if slugify(marca) == slug:
            return marca
    return None


def construir_url_amigable(categoria=None, marca=None, talla=None):
    """Construye la URL amigable a partir de los filtros."""
    cat_slug = CATEGORIAS_SLUG_INV.get(categoria, "")
    if not cat_slug:
        # Sin categoria, no podemos hacer URL amigable
        return None
    path = f"/{cat_slug}/"
    if marca:
        path = f"/{cat_slug}/{slugify(marca)}/"
        if talla:
            path = f"/{cat_slug}/{slugify(marca)}/talla-{slugify(talla)}/"
    return path


def conectar_db():
    """Abre conexion a la base de datos SQLite."""
    conn = sqlite3.connect(ARCHIVO_DB)
    conn.row_factory = sqlite3.Row
    return conn


MARCA_ALIASES = {
    "Nan Optipro": "Nan",
}


def normalizar_marca(marca):
    """Normaliza 'PAMPERS' -> 'Pampers' y unifica variantes como 'Nan Optipro' -> 'Nan'."""
    if not marca:
        return ""
    norm = marca.strip().title()
    return MARCA_ALIASES.get(norm, norm)


def detectar_categoria(nombre):
    """Detecta la categoria del producto: Fórmulas Infantiles, Toallitas Humedas, Pañales de Agua, o Pañales."""
    if not nombre:
        return "Pañales"
    nombre_lower = nombre.lower()
    for keyword in FORMULAS_KEYWORDS:
        if keyword in nombre_lower:
            return "Fórmulas Infantiles"
    for keyword in TOALLITAS_KEYWORDS:
        if keyword in nombre_lower:
            return "Toallitas Humedas"
    for keyword in PANALES_AGUA_KEYWORDS:
        if keyword in nombre_lower:
            return "Pañales de Agua"
    return "Pañales"


def detectar_talla(nombre):
    """Extrae la talla de un producto a partir de su nombre."""
    if not nombre:
        return None

    nombre_upper = nombre.upper()

    match = re.search(r"TALLA\s+(RN\+?|S[/-]?M|P|M|G|XG|XXG|XXXG|L[/-]?XL)", nombre_upper)
    if match:
        return match.group(1).replace("/", "-")

    match = re.search(r"(?:PREMIUM|COMFORT|CARE|SEC|COOL|PLUS)\s+(RN\+?|P|M|G|XG|XXG|XXXG)\b", nombre_upper)
    if match:
        return match.group(1)

    match = re.search(r"PANTS\s+(RN|P|M|G|XG|XXG|XXXG|P[/-]M|G[/-]XG)\b", nombre_upper)
    if match:
        return match.group(1).replace("/", "-")

    match = re.search(r"ADULTO\s+.*?(M|G|L|XG|XL)\b", nombre_upper)
    if match:
        return match.group(1)

    return None


def query_excluir_no_panales():
    """Retorna clausula SQL allowlist + exclusion de productos de adulto."""
    incluir = " OR ".join(f"LOWER(p.nombre) LIKE '{pat}'" for pat in INCLUIR_PATRONES)
    excluir = " AND ".join(f"LOWER(p.nombre) NOT LIKE '{pat}'" for pat in EXCLUIR_ADULTO)
    return f"AND ({incluir}) AND {excluir}"


def obtener_marcas():
    """Retorna lista de marcas de panales, normalizadas y sin duplicados."""
    conn = conectar_db()
    cursor = conn.cursor()

    query = f"""
        SELECT DISTINCT p.marca FROM productos p
        JOIN precios pr ON pr.producto_id = p.id
        WHERE pr.precio_por_unidad IS NOT NULL {query_excluir_no_panales()}
        ORDER BY p.marca
    """
    cursor.execute(query)
    marcas_raw = [row["marca"] for row in cursor.fetchall() if row["marca"]]
    conn.close()

    vistas = set()
    marcas = []
    for m in marcas_raw:
        norm = normalizar_marca(m)
        if norm and norm not in vistas:
            vistas.add(norm)
            marcas.append(norm)
    return sorted(marcas)


def obtener_tallas():
    """Retorna lista de tallas disponibles, ordenadas de chica a grande."""
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM productos")
    nombres = [row["nombre"] for row in cursor.fetchall()]
    conn.close()

    tallas_set = set()
    for nombre in nombres:
        talla = detectar_talla(nombre)
        if talla:
            tallas_set.add(talla)

    def orden_talla(t):
        try:
            return ORDEN_TALLAS.index(t)
        except ValueError:
            return 999

    return sorted(tallas_set, key=orden_talla)


def obtener_opciones_filtros():
    """
    Construye un mapping de opciones para filtros en cascada:
    categoria -> marcas disponibles, y (categoria, marca) -> tallas disponibles.
    Solo usa productos de la ultima fecha de scraping.
    """
    conn = conectar_db()
    cursor = conn.cursor()

    # Fecha del ultimo scraping
    cursor.execute("SELECT MAX(fecha_scraping) FROM precios")
    ultima_fecha = cursor.fetchone()[0]
    if not ultima_fecha:
        conn.close()
        return {"": {"marcas": [], "tallas_por_marca": {"": []}}}

    query = f"""
        SELECT p.nombre, p.marca, pr.precio_por_unidad
        FROM precios pr
        JOIN productos p ON p.id = pr.producto_id
        WHERE pr.fecha_scraping = ?
          AND pr.precio IS NOT NULL
          {query_excluir_no_panales()}
    """
    cursor.execute(query, [ultima_fecha])
    rows = cursor.fetchall()
    conn.close()

    def orden_talla(t):
        try:
            return ORDEN_TALLAS.index(t)
        except ValueError:
            return 999

    # Recopilar datos: categoria -> marca -> set de tallas
    datos = {}  # {categoria: {marca: set(tallas)}}
    productos_formulas = {}  # {marca: set(nombres)}
    for row in rows:
        nombre = row["nombre"]
        marca = normalizar_marca(row["marca"])
        if not marca:
            continue
        categoria = detectar_categoria(nombre)
        # Para categorías que no son fórmulas, exigir precio_por_unidad
        if categoria != "Fórmulas Infantiles" and not row["precio_por_unidad"]:
            continue
        talla = detectar_talla(nombre)

        if categoria not in datos:
            datos[categoria] = {}
        if marca not in datos[categoria]:
            datos[categoria][marca] = set()
        if talla:
            datos[categoria][marca].add(talla)

        # Recopilar nombres de productos para Fórmulas Infantiles
        if categoria == "Fórmulas Infantiles":
            if marca not in productos_formulas:
                productos_formulas[marca] = set()
            productos_formulas[marca].add(nombre)

    opciones = {}

    # Por cada categoria
    for cat, marcas_dict in datos.items():
        marcas_lista = sorted(marcas_dict.keys())
        tallas_por_marca = {}
        # Todas las tallas de la categoria (marca = "")
        todas_tallas = set()
        for m, tallas_set in marcas_dict.items():
            todas_tallas.update(tallas_set)
            tallas_por_marca[m] = sorted(tallas_set, key=orden_talla)
        tallas_por_marca[""] = sorted(todas_tallas, key=orden_talla)

        # Para Toallitas Humedas y Fórmulas Infantiles, no hay tallas
        if cat in ("Toallitas Humedas", "Fórmulas Infantiles"):
            tallas_por_marca = {}

        cat_opciones = {
            "marcas": marcas_lista,
            "tallas_por_marca": tallas_por_marca,
        }

        # Para Fórmulas Infantiles, agregar productos_por_marca
        if cat == "Fórmulas Infantiles":
            productos_por_marca = {}
            todos_productos = set()
            for m, nombres_set in productos_formulas.items():
                productos_por_marca[m] = sorted(nombres_set)
                todos_productos.update(nombres_set)
            productos_por_marca[""] = sorted(todos_productos)
            cat_opciones["productos_por_marca"] = productos_por_marca

        opciones[cat] = cat_opciones

    # Entrada global (sin filtro de categoria, key = "")
    todas_marcas = set()
    todas_tallas_global = set()
    tallas_por_marca_global = {}
    for cat, marcas_dict in datos.items():
        for m, tallas_set in marcas_dict.items():
            todas_marcas.add(m)
            todas_tallas_global.update(tallas_set)
            if m not in tallas_por_marca_global:
                tallas_por_marca_global[m] = set()
            tallas_por_marca_global[m].update(tallas_set)

    tallas_por_marca_global_sorted = {"": sorted(todas_tallas_global, key=orden_talla)}
    for m, tallas_set in tallas_por_marca_global.items():
        tallas_por_marca_global_sorted[m] = sorted(tallas_set, key=orden_talla)

    opciones[""] = {
        "marcas": sorted(todas_marcas),
        "tallas_por_marca": tallas_por_marca_global_sorted,
    }

    return opciones


def obtener_tiendas():
    """Retorna lista de tiendas disponibles."""
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM tiendas ORDER BY nombre")
    tiendas = [row["nombre"] for row in cursor.fetchall()]
    conn.close()
    return tiendas


def obtener_precio_maximo():
    """Retorna el precio maximo entre todos los productos."""
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(precio) FROM precios WHERE precio IS NOT NULL")
    resultado = cursor.fetchone()[0]
    conn.close()
    return resultado or 50000


def buscar_productos(marca=None, talla=None, tallas_edad=None,
                     tiendas_sel=None, precio_max=None, busqueda=None,
                     categoria=None, producto_param=None, orden="precio_por_unidad"):
    """
    Busca productos con los filtros aplicados.
    Solo retorna precios de la ultima ejecucion del scraper.
    """
    conn = conectar_db()
    cursor = conn.cursor()

    # Fecha del ultimo scraping
    cursor.execute("SELECT MAX(fecha_scraping) FROM precios")
    ultima_fecha = cursor.fetchone()[0]
    if not ultima_fecha:
        conn.close()
        return [], None

    query = f"""
        SELECT p.nombre, p.marca, p.tamano_unidades, p.url, p.imagen_url,
               pr.precio, pr.precio_por_unidad, pr.precio_lista, t.nombre as tienda
        FROM precios pr
        JOIN productos p ON p.id = pr.producto_id
        JOIN tiendas t ON t.id = pr.tienda_id
        WHERE pr.fecha_scraping = ?
          AND pr.precio IS NOT NULL
          {query_excluir_no_panales()}
    """
    params = [ultima_fecha]

    # Filtro por marca
    if marca:
        query += " AND LOWER(p.marca) = LOWER(?)"
        params.append(marca)

    # Filtro por tiendas seleccionadas
    if tiendas_sel:
        placeholders = ",".join("?" for _ in tiendas_sel)
        query += f" AND t.nombre IN ({placeholders})"
        params.extend(tiendas_sel)

    # Filtro por precio maximo
    if precio_max:
        query += " AND pr.precio <= ?"
        params.append(precio_max)

    # Filtro por busqueda de texto libre
    if busqueda:
        palabras = busqueda.strip().split()
        for palabra in palabras:
            query += " AND p.nombre LIKE ?"
            params.append(f"%{palabra}%")

    # Deduplicar (mismo producto + tienda) y ordenar
    query += " GROUP BY p.id, t.id"
    orden_sql = ORDEN_PERMITIDO.get(orden, ORDEN_PERMITIDO["precio_por_unidad"])
    query += f" ORDER BY {orden_sql}"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Filtramos por talla en Python (regex es mas flexible)
    resultados = []
    for row in rows:
        producto = dict(row)
        producto["talla"] = detectar_talla(producto["nombre"])
        producto["marca_normalizada"] = normalizar_marca(producto["marca"])
        producto["categoria"] = detectar_categoria(producto["nombre"])

        # Calcular descuento
        precio_lista = producto.get("precio_lista")
        precio = producto.get("precio")
        if precio_lista and precio and precio_lista > precio:
            descuento = round((precio_lista - precio) / precio_lista * 100)
            producto["descuento_pct"] = descuento
        else:
            producto["descuento_pct"] = None
            producto["precio_lista"] = None

        if talla and producto["talla"] != talla:
            continue

        if tallas_edad and producto["talla"] not in tallas_edad:
            continue

        if categoria and producto["categoria"] != categoria:
            continue

        if producto_param and producto["nombre"] != producto_param:
            continue

        # Para categorías que no son fórmulas, exigir precio_por_unidad
        if producto["categoria"] != "Fórmulas Infantiles" and not producto.get("precio_por_unidad"):
            continue

        resultados.append(producto)

    conn.close()
    return resultados, ultima_fecha


def calcular_ahorro(productos):
    """
    Calcula el ahorro potencial comparando el producto mas barato
    vs el mas caro en los resultados actuales.
    """
    if len(productos) < 2:
        return None

    con_ppu = [p for p in productos if p.get("precio_por_unidad")]
    if len(con_ppu) < 2:
        return None

    mejor = con_ppu[0]  # Ya estan ordenados por ppu
    peor = con_ppu[-1]

    diferencia_por_unidad = peor["precio_por_unidad"] - mejor["precio_por_unidad"]
    porcentaje = (diferencia_por_unidad / peor["precio_por_unidad"]) * 100

    # Estimamos ahorro mensual (asumiendo ~6 panales/dia = ~180/mes)
    panales_mes = 180
    ahorro_mensual = diferencia_por_unidad * panales_mes
    ahorro_anual = ahorro_mensual * 12

    return {
        "mejor": mejor,
        "peor": peor,
        "diferencia_por_unidad": diferencia_por_unidad,
        "porcentaje": porcentaje,
        "panales_mes": panales_mes,
        "ahorro_mensual": ahorro_mensual,
        "ahorro_anual": ahorro_anual,
    }


def obtener_top_por_talla(marca=None, tiendas_sel=None, precio_max=None,
                          busqueda=None, categoria=None):
    """
    Retorna el producto con menor PPU de cada talla.
    Dict {talla: producto} ordenado por ORDEN_TALLAS.
    """
    productos, _ = buscar_productos(
        marca=marca, talla=None, tallas_edad=None,
        tiendas_sel=tiendas_sel, precio_max=precio_max,
        busqueda=busqueda, categoria=categoria,
        orden="precio_por_unidad",
    )

    mejor_por_talla = {}
    for p in productos:
        t = p.get("talla")
        if not t:
            continue
        if t not in mejor_por_talla:
            mejor_por_talla[t] = p

    def orden_talla(item):
        try:
            return ORDEN_TALLAS.index(item[0])
        except ValueError:
            return 999

    return dict(sorted(mejor_por_talla.items(), key=orden_talla))


def formatear_precio(precio):
    """16690 -> '$16.690'"""
    if precio is None:
        return "-"
    return f"${precio:,}".replace(",", ".")


app.jinja_env.filters["precio"] = formatear_precio


def construir_sort_urls(request_args, orden_actual):
    """Construye URLs para cada columna de ordenamiento, preservando filtros."""
    sort_urls = {}
    for col in ORDEN_PERMITIDO:
        params = {}
        for key in request_args:
            if key != "orden":
                valores = request_args.getlist(key)
                if len(valores) == 1:
                    params[key] = valores[0]
                else:
                    params[key] = valores
        params["orden"] = col
        # Build URL preserving multi-value params (tiendas)
        parts = []
        for k, v in params.items():
            if isinstance(v, list):
                for item in v:
                    parts.append(f"{k}={item}")
            else:
                parts.append(f"{k}={v}")
        sort_urls[col] = "/?" + "&".join(parts)
    return sort_urls


# =============================================================
# RUTAS
# =============================================================

def _render_index(categoria_path="", marca_path="", talla_path=""):
    """Logica compartida para la pagina principal (/ y URLs amigables)."""
    opciones_filtros = obtener_opciones_filtros()
    marcas = opciones_filtros.get("", {}).get("marcas", [])
    tallas = opciones_filtros.get("", {}).get("tallas_por_marca", {}).get("", [])
    tiendas = obtener_tiendas()
    precio_max_global = obtener_precio_maximo()

    # Filtros del path tienen prioridad, luego query params (backward compat)
    marca_sel = marca_path or request.args.get("marca", "")
    talla_sel = talla_path or request.args.get("talla", "")
    categoria_sel = categoria_path or request.args.get("categoria", "")
    producto_sel = request.args.get("producto", "")
    tiendas_sel = request.args.getlist("tiendas")
    precio_max_str = request.args.get("precio_max", "")
    orden_actual = request.args.get("orden", "precio_por_unidad")

    # Validar orden contra whitelist
    if orden_actual not in ORDEN_PERMITIDO:
        orden_actual = "precio_por_unidad"

    precio_max = None
    if precio_max_str:
        try:
            precio_max = int(precio_max_str)
        except ValueError:
            pass

    # Determinar si hay algun filtro activo
    hay_filtro = bool(marca_sel or talla_sel or categoria_sel or producto_sel or tiendas_sel or precio_max)

    # Buscar productos
    productos = []
    ultima_fecha = None
    ahorro = None

    top_por_talla = {}

    if hay_filtro:
        productos, ultima_fecha = buscar_productos(
            marca=marca_sel or None,
            talla=talla_sel or None,
            tiendas_sel=tiendas_sel or None,
            precio_max=precio_max,
            categoria=categoria_sel or None,
            producto_param=producto_sel or None,
            orden=orden_actual,
        )
        ahorro = calcular_ahorro(productos)

        # Top por talla: solo cuando NO hay filtro de talla
        if not talla_sel:
            top_por_talla = obtener_top_por_talla(
                marca=marca_sel or None,
                tiendas_sel=tiendas_sel or None,
                precio_max=precio_max,
                categoria=categoria_sel or None,
            )
    else:
        # Sin filtros, mostramos la fecha de actualizacion
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(fecha_scraping) FROM precios")
        ultima_fecha = cursor.fetchone()[0]
        conn.close()

    # Construir URLs de ordenamiento
    sort_urls = construir_sort_urls(request.args, orden_actual)

    # --- SEO: titulo, meta description, canonical ---
    if categoria_sel and marca_sel and talla_sel:
        titulo_pagina = f"{marca_sel} Talla {talla_sel} - Compara precios | BabyAhorro"
    elif marca_sel and talla_sel:
        titulo_pagina = f"{marca_sel} Talla {talla_sel} - Compara precios | BabyAhorro"
    elif categoria_sel and marca_sel:
        titulo_pagina = f"{marca_sel} {categoria_sel} - Compara precios | BabyAhorro"
    elif marca_sel:
        titulo_pagina = f"Panales {marca_sel} - Precios y comparacion | BabyAhorro"
    elif categoria_sel:
        titulo_pagina = f"{categoria_sel} - Compara precios | BabyAhorro"
    else:
        titulo_pagina = "BabyAhorro - Comparador de precios de panales en Chile"

    if hay_filtro and productos:
        mejor = productos[0]
        partes_desc = []
        if marca_sel:
            partes_desc.append(f"Panales {marca_sel}")
        if talla_sel:
            partes_desc.append(f"Talla {talla_sel}")
        nombre_filtro = " ".join(partes_desc) if partes_desc else "Panales"
        ppu = formatear_precio(mejor.get("precio_por_unidad"))
        meta_descripcion = f"{nombre_filtro} desde {ppu}/unidad. Compara precios en 9 tiendas chilenas."
    elif hay_filtro:
        meta_descripcion = "Compara precios de panales, toallitas y formulas infantiles en 9 tiendas de Chile."
    else:
        meta_descripcion = ("Compara precios de panales, toallitas y formulas infantiles en 9 tiendas de Chile. "
                            "Encuentra el mas barato entre Jumbo, Cruz Verde, Salcobrand y mas.")

    # Canonical: apunta siempre a la URL amigable si es posible
    base = request.url_root.rstrip("/")
    url_amigable = construir_url_amigable(
        categoria=categoria_sel or None,
        marca=marca_sel or None,
        talla=talla_sel or None,
    )
    if url_amigable:
        canonical_url = base + url_amigable
    elif categoria_sel or marca_sel or talla_sel:
        canonical_params = {}
        if categoria_sel:
            canonical_params["categoria"] = categoria_sel
        if marca_sel:
            canonical_params["marca"] = marca_sel
        if talla_sel:
            canonical_params["talla"] = talla_sel
        canonical_url = base + "/?" + urlencode(canonical_params)
    else:
        canonical_url = base + "/"

    # Descripcion OG dinamica para compartir
    og_partes = []
    if marca_sel:
        og_partes.append(marca_sel)
    if talla_sel:
        og_partes.append(f"Talla {talla_sel}")
    if hay_filtro and productos:
        mejor = productos[0]
        og_partes.append(
            f"Desde {formatear_precio(mejor['precio_por_unidad'])}/unidad"
        )
    og_descripcion = " - ".join(og_partes) if og_partes else (
        "Compara precios de panales entre tiendas chilenas y encuentra el mas barato."
    )

    return render_template(
        "index.html",
        marcas=marcas,
        tallas=tallas,
        tiendas=tiendas,
        marca_sel=marca_sel,
        talla_sel=talla_sel,
        categoria_sel=categoria_sel,
        producto_sel=producto_sel,
        tiendas_sel=tiendas_sel,
        precio_max=precio_max,
        precio_max_global=precio_max_global,
        productos=productos,
        ultima_fecha=ultima_fecha,
        total=len(productos),
        ahorro=ahorro,
        hay_filtro=hay_filtro,
        logos_tiendas=LOGOS_TIENDAS,
        sort_urls=sort_urls,
        orden_actual=orden_actual,
        top_por_talla=top_por_talla,
        og_descripcion=og_descripcion,
        opciones_filtros=opciones_filtros,
        titulo_pagina=titulo_pagina,
        meta_descripcion=meta_descripcion,
        canonical_url=canonical_url,
        construir_url_amigable=construir_url_amigable,
        slugify=slugify,
    )


@app.route("/")
def index():
    """Pagina principal: buscador y resultados."""
    return _render_index()


@app.route("/<cat_slug>/")
def index_categoria(cat_slug):
    """URL amigable por categoria: /panales/, /toallitas/, /formulas/"""
    categoria = CATEGORIAS_SLUG.get(cat_slug)
    if not categoria:
        return redirect("/"), 302
    return _render_index(categoria_path=categoria)


@app.route("/<cat_slug>/<marca_slug>/")
def index_categoria_marca(cat_slug, marca_slug):
    """URL amigable por categoria + marca: /panales/pampers/"""
    categoria = CATEGORIAS_SLUG.get(cat_slug)
    if not categoria:
        return redirect("/"), 302
    # Buscar marca real
    opciones = obtener_opciones_filtros()
    marcas_cat = opciones.get(categoria, {}).get("marcas", [])
    marcas_all = opciones.get("", {}).get("marcas", [])
    marca = deslugify_marca(marca_slug, marcas_cat) or deslugify_marca(marca_slug, marcas_all)
    if not marca:
        return redirect(f"/{cat_slug}/"), 302
    return _render_index(categoria_path=categoria, marca_path=marca)


@app.route("/<cat_slug>/<marca_slug>/<talla_slug>/")
def index_categoria_marca_talla(cat_slug, marca_slug, talla_slug):
    """URL amigable por categoria + marca + talla: /panales/pampers/talla-g/"""
    categoria = CATEGORIAS_SLUG.get(cat_slug)
    if not categoria:
        return redirect("/"), 302
    opciones = obtener_opciones_filtros()
    marcas_cat = opciones.get(categoria, {}).get("marcas", [])
    marcas_all = opciones.get("", {}).get("marcas", [])
    marca = deslugify_marca(marca_slug, marcas_cat) or deslugify_marca(marca_slug, marcas_all)
    if not marca:
        return redirect(f"/{cat_slug}/"), 302
    talla = deslugify_talla(talla_slug)
    if not talla:
        return redirect(f"/{cat_slug}/{marca_slug}/"), 302
    return _render_index(categoria_path=categoria, marca_path=marca, talla_path=talla)


@app.route("/historico")
def historico():
    """Pagina de historico de precios."""
    opciones_filtros = obtener_opciones_filtros()
    tiendas = obtener_tiendas()

    conn = conectar_db()
    cursor = conn.cursor()

    # Leer filtros de selects
    producto_id = request.args.get("producto_id", "")
    categoria_sel = request.args.get("categoria", "")
    marca_sel = request.args.get("marca", "")
    talla_sel = request.args.get("talla", "")
    producto_sel = request.args.get("producto", "")
    tienda_sel = request.args.get("tienda", "")

    hay_filtro = bool(categoria_sel or marca_sel or talla_sel or producto_sel or tienda_sel)

    # Buscar productos para el selector (usando selects en cascada)
    productos_lista = []
    if hay_filtro:
        query = f"""
            SELECT DISTINCT p.id, p.nombre, p.marca, t.nombre as tienda
            FROM productos p
            JOIN precios pr ON pr.producto_id = p.id
            JOIN tiendas t ON t.id = pr.tienda_id
            WHERE pr.precio IS NOT NULL
              {query_excluir_no_panales()}
        """
        params = []

        if marca_sel:
            query += " AND LOWER(p.marca) = LOWER(?)"
            params.append(marca_sel)

        if tienda_sel:
            query += " AND t.nombre = ?"
            params.append(tienda_sel)

        query += " ORDER BY p.nombre LIMIT 50"
        cursor.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]

        # Post-filtro por categoria y talla en Python
        for row in rows:
            row["categoria"] = detectar_categoria(row["nombre"])
            row["talla"] = detectar_talla(row["nombre"])

        for row in rows:
            if categoria_sel and row["categoria"] != categoria_sel:
                continue
            if talla_sel and row["talla"] != talla_sel:
                continue
            if producto_sel and row["nombre"] != producto_sel:
                continue
            productos_lista.append(row)

    # Datos historicos del producto seleccionado
    datos_historico = []
    producto_info = None
    if producto_id:
        cursor.execute("""
            SELECT p.nombre, p.marca, p.tamano_unidades, t.nombre as tienda
            FROM productos p
            JOIN precios pr ON pr.producto_id = p.id
            JOIN tiendas t ON t.id = pr.tienda_id
            WHERE p.id = ?
            LIMIT 1
        """, (producto_id,))
        row = cursor.fetchone()
        if row:
            producto_info = dict(row)

        cursor.execute("""
            SELECT pr.precio, pr.precio_por_unidad, pr.fecha_scraping
            FROM precios pr
            WHERE pr.producto_id = ?
            ORDER BY pr.fecha_scraping ASC
        """, (producto_id,))
        datos_historico = [dict(row) for row in cursor.fetchall()]

    # Estadisticas generales del historico
    cursor.execute("SELECT COUNT(DISTINCT fecha_scraping) FROM precios")
    total_dias = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(fecha_scraping), MAX(fecha_scraping) FROM precios")
    fechas = cursor.fetchone()
    fecha_inicio = fechas[0][:10] if fechas[0] else None
    fecha_fin = fechas[1][:10] if fechas[1] else None

    conn.close()

    # SEO variables for historico
    titulo_pagina = "Historico de Precios - BabyAhorro"
    meta_descripcion = ("Historico de precios de panales en Chile. Revisa como cambian "
                        "los precios dia a dia y encuentra el mejor momento para comprar.")
    canonical_url = request.url_root.rstrip("/") + "/historico"

    return render_template(
        "historico.html",
        opciones_filtros=opciones_filtros,
        tiendas=tiendas,
        categoria_sel=categoria_sel,
        marca_sel=marca_sel,
        talla_sel=talla_sel,
        producto_sel=producto_sel,
        tienda_sel=tienda_sel,
        hay_filtro=hay_filtro,
        productos_lista=productos_lista,
        producto_id=producto_id,
        producto_info=producto_info,
        datos_historico=datos_historico,
        total_dias=total_dias,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        titulo_pagina=titulo_pagina,
        meta_descripcion=meta_descripcion,
        canonical_url=canonical_url,
    )


@app.route("/robots.txt")
def robots_txt():
    """Genera robots.txt para SEO."""
    base_url = request.url_root.rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /?precio_max=\n"
        "Disallow: /?orden=\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """Genera sitemap XML dinamico con URLs amigables."""
    base_url = request.url_root.rstrip("/")

    urls = [
        (f"{base_url}/", "1.0", "daily"),
        (f"{base_url}/historico", "0.8", "daily"),
    ]

    # Categorias con URLs amigables
    for cat_slug, cat_nombre in CATEGORIAS_SLUG.items():
        priority = "0.9" if cat_nombre == "Pañales" else "0.7"
        urls.append((f"{base_url}/{cat_slug}/", priority, "daily"))

    # Agregar marcas desde la DB con URLs amigables
    try:
        opciones = obtener_opciones_filtros()
        for cat_slug, cat_nombre in CATEGORIAS_SLUG.items():
            cat_data = opciones.get(cat_nombre, {})
            marcas_cat = cat_data.get("marcas", [])
            tallas_por_marca = cat_data.get("tallas_por_marca", {})

            for marca in marcas_cat:
                marca_s = slugify(marca)
                urls.append((f"{base_url}/{cat_slug}/{marca_s}/", "0.8", "daily"))

                # Combinaciones marca+talla
                tallas = tallas_por_marca.get(marca, [])
                for talla in tallas:
                    talla_s = slugify(talla)
                    urls.append((f"{base_url}/{cat_slug}/{marca_s}/talla-{talla_s}/", "0.6", "daily"))
    except Exception:
        pass

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, priority, changefreq in urls:
        xml_parts.append("  <url>")
        xml_parts.append(f"    <loc>{loc}</loc>")
        xml_parts.append(f"    <changefreq>{changefreq}</changefreq>")
        xml_parts.append(f"    <priority>{priority}</priority>")
        xml_parts.append("  </url>")
    xml_parts.append("</urlset>")

    return Response("\n".join(xml_parts), mimetype="application/xml")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
