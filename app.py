"""
Aplicacion web del Comparador de Panales Chile.

Permite buscar y comparar precios de panales entre tiendas chilenas
filtrando por marca, talla, tienda, precio maximo y busqueda libre.
Incluye pagina de historico de precios y seccion de consejos de ahorro.

Uso:
    python app.py

Luego abre http://localhost:8080 en tu navegador.
"""

import os
import re
import sqlite3
from flask import Flask, render_template, request, jsonify

# --- CONFIGURACION ---

DIR_PROYECTO = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_DB = os.path.join(DIR_PROYECTO, "data", "precios.db")

app = Flask(__name__)

# Productos que NO son panales (para excluir de resultados)
EXCLUIR_PATRONES = [
    "%Toalla%", "%Jabón%", "%Jabon%", "%Shampoo%", "%Acondicionador%",
    "%Crema%", "%Pantalla%", "%Protector solar%", "%Protector Mamario%",
    "%Aposito%", "%Apósito%", "%Colonia%", "%Mamadera%", "%Chupete%",
    "%Calzon%", "%Calzón%", "%Pants%",
]

# Palabras clave para detectar panales de agua
PANALES_AGUA_KEYWORDS = ["swimmer", "agua", "acuatic"]

# Tallas en orden logico (de mas chico a mas grande)
ORDEN_TALLAS = [
    "RN", "RN+", "P", "S-M", "M", "G", "P-M",
    "XG", "G-XG", "L", "XXG", "L-XL", "XL", "XXXG",
]


def conectar_db():
    """Abre conexion a la base de datos SQLite."""
    conn = sqlite3.connect(ARCHIVO_DB)
    conn.row_factory = sqlite3.Row
    return conn


def normalizar_marca(marca):
    """Normaliza 'PAMPERS' -> 'Pampers'."""
    if not marca:
        return ""
    return marca.strip().title()


def detectar_categoria(nombre):
    """Retorna 'Pañales de Agua' si el nombre contiene keywords de swimmers, o 'Pañales'."""
    if not nombre:
        return "Pañales"
    nombre_lower = nombre.lower()
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
    """Retorna clausulas SQL para excluir productos que no son panales."""
    clausulas = " AND ".join(f"p.nombre NOT LIKE '{pat}'" for pat in EXCLUIR_PATRONES)
    return f"AND {clausulas}"


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


def buscar_productos(marca=None, talla=None, tiendas_sel=None,
                     precio_max=None, busqueda=None, categoria=None):
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
        SELECT p.nombre, p.marca, p.tamano_unidades, p.url,
               pr.precio, pr.precio_por_unidad, t.nombre as tienda
        FROM precios pr
        JOIN productos p ON p.id = pr.producto_id
        JOIN tiendas t ON t.id = pr.tienda_id
        WHERE pr.fecha_scraping = ?
          AND pr.precio IS NOT NULL
          AND pr.precio_por_unidad IS NOT NULL
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

    query += " ORDER BY pr.precio_por_unidad ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Filtramos por talla en Python (regex es mas flexible)
    resultados = []
    for row in rows:
        producto = dict(row)
        producto["talla"] = detectar_talla(producto["nombre"])
        producto["marca_normalizada"] = normalizar_marca(producto["marca"])
        producto["categoria"] = detectar_categoria(producto["nombre"])

        if talla and producto["talla"] != talla:
            continue

        if categoria and producto["categoria"] != categoria:
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


def formatear_precio(precio):
    """16690 -> '$16.690'"""
    if precio is None:
        return "-"
    return f"${precio:,}".replace(",", ".")


app.jinja_env.filters["precio"] = formatear_precio


# =============================================================
# RUTAS
# =============================================================

@app.route("/")
def index():
    """Pagina principal: buscador y resultados."""
    marcas = obtener_marcas()
    tallas = obtener_tallas()
    tiendas = obtener_tiendas()
    precio_max_global = obtener_precio_maximo()

    # Leer filtros
    marca_sel = request.args.get("marca", "")
    talla_sel = request.args.get("talla", "")
    categoria_sel = request.args.get("categoria", "")
    busqueda = request.args.get("busqueda", "")
    tiendas_sel = request.args.getlist("tiendas")
    precio_max_str = request.args.get("precio_max", "")

    precio_max = None
    if precio_max_str:
        try:
            precio_max = int(precio_max_str)
        except ValueError:
            pass

    # Determinar si hay algun filtro activo
    hay_filtro = bool(marca_sel or talla_sel or categoria_sel or busqueda or tiendas_sel or precio_max)

    # Buscar productos
    productos = []
    ultima_fecha = None
    ahorro = None

    if hay_filtro:
        productos, ultima_fecha = buscar_productos(
            marca=marca_sel or None,
            talla=talla_sel or None,
            tiendas_sel=tiendas_sel or None,
            precio_max=precio_max,
            busqueda=busqueda or None,
            categoria=categoria_sel or None,
        )
        ahorro = calcular_ahorro(productos)
    else:
        # Sin filtros, mostramos la fecha de actualizacion
        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(fecha_scraping) FROM precios")
        ultima_fecha = cursor.fetchone()[0]
        conn.close()

    return render_template(
        "index.html",
        marcas=marcas,
        tallas=tallas,
        tiendas=tiendas,
        marca_sel=marca_sel,
        talla_sel=talla_sel,
        categoria_sel=categoria_sel,
        busqueda=busqueda,
        tiendas_sel=tiendas_sel,
        precio_max=precio_max,
        precio_max_global=precio_max_global,
        productos=productos,
        ultima_fecha=ultima_fecha,
        total=len(productos),
        ahorro=ahorro,
        hay_filtro=hay_filtro,
    )


@app.route("/historico")
def historico():
    """Pagina de historico de precios."""
    conn = conectar_db()
    cursor = conn.cursor()

    # Producto seleccionado
    producto_id = request.args.get("producto_id", "")
    busqueda = request.args.get("busqueda", "")

    # Buscar productos para el selector
    productos_lista = []
    if busqueda:
        query = f"""
            SELECT DISTINCT p.id, p.nombre, p.marca, t.nombre as tienda
            FROM productos p
            JOIN precios pr ON pr.producto_id = p.id
            JOIN tiendas t ON t.id = pr.tienda_id
            WHERE p.nombre LIKE ?
              {query_excluir_no_panales()}
            ORDER BY p.nombre
            LIMIT 20
        """
        cursor.execute(query, (f"%{busqueda}%",))
        productos_lista = [dict(row) for row in cursor.fetchall()]

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

    return render_template(
        "historico.html",
        busqueda=busqueda,
        productos_lista=productos_lista,
        producto_id=producto_id,
        producto_info=producto_info,
        datos_historico=datos_historico,
        total_dias=total_dias,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
