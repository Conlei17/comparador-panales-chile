"""
Script principal del Comparador de Panales Chile.

Ejecuta todos los scrapers disponibles, combina los resultados
en un CSV consolidado Y en una base de datos SQLite que mantiene
el historico de precios a lo largo del tiempo.

Uso:
    python main.py

La base de datos se guarda en data/precios.db y NUNCA se sobreescribe:
cada ejecucion agrega registros nuevos, permitiendo ver como cambian
los precios dia a dia.
"""

import os
import re
import csv
import sqlite3
from datetime import datetime

# --- CONFIGURACION ---

# Carpeta base del proyecto (donde esta este archivo)
DIR_PROYECTO = os.path.dirname(os.path.abspath(__file__))

# Carpeta donde estan los datos
CARPETA_DATOS = os.path.join(DIR_PROYECTO, "data")

# Archivo de salida consolidado (CSV, se sobreescribe cada vez)
ARCHIVO_CONSOLIDADO = "precios_consolidados.csv"

# Base de datos SQLite (historico, se acumula)
ARCHIVO_DB = os.path.join(CARPETA_DATOS, "precios.db")

# Columnas del CSV
COLUMNAS = [
    "nombre",
    "precio",
    "marca",
    "cantidad_unidades",
    "precio_por_unidad",
    "url",
    "tienda",
    "fecha_extraccion",
    "imagen",
    "precio_lista",
]
COLUMNAS_CONSOLIDADO = COLUMNAS + ["nombre_normalizado", "es_precio_mas_bajo"]


# =============================================================
# BASE DE DATOS SQLITE
# =============================================================

def inicializar_db():
    """
    Crea la base de datos y las tablas si no existen.

    Esquema:
      - tiendas: cada tienda scrapeada (Liquimax, Pepito, etc.)
      - productos: cada producto unico (identificado por nombre + marca + url)
      - precios: registro historico de precios (uno por producto por dia)

    La tabla precios es la que crece con cada ejecucion.
    Las tablas tiendas y productos solo agregan filas nuevas si
    aparecen productos o tiendas que no existian antes.
    """
    os.makedirs(CARPETA_DATOS, exist_ok=True)
    conn = sqlite3.connect(ARCHIVO_DB)
    cursor = conn.cursor()

    cursor.executescript("""
        -- Tabla de tiendas
        CREATE TABLE IF NOT EXISTS tiendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            url_base TEXT
        );

        -- Tabla de productos (cada producto unico)
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            marca TEXT,
            tamano_unidades INTEGER,
            url TEXT,
            -- Un producto se identifica por su URL (unica por tienda)
            UNIQUE(url)
        );

        -- Tabla de precios (historico, crece cada dia)
        CREATE TABLE IF NOT EXISTS precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            tienda_id INTEGER NOT NULL,
            precio INTEGER,
            precio_por_unidad INTEGER,
            fecha_scraping TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos(id),
            FOREIGN KEY (tienda_id) REFERENCES tiendas(id)
        );

        -- Indice para buscar precios por fecha rapidamente
        CREATE INDEX IF NOT EXISTS idx_precios_fecha
            ON precios(fecha_scraping);

        -- Indice para buscar precios por producto
        CREATE INDEX IF NOT EXISTS idx_precios_producto
            ON precios(producto_id);
    """)

    # Agregar columna imagen_url a productos si no existe
    try:
        cursor.execute("ALTER TABLE productos ADD COLUMN imagen_url TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Ya existe

    # Agregar columna precio_lista a precios si no existe
    try:
        cursor.execute("ALTER TABLE precios ADD COLUMN precio_lista INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Ya existe

    conn.commit()
    return conn


def obtener_o_crear_tienda(cursor, nombre, url_base=None):
    """
    Busca una tienda por nombre. Si no existe, la crea.

    Retorna el id de la tienda.
    """
    cursor.execute("SELECT id FROM tiendas WHERE nombre = ?", (nombre,))
    fila = cursor.fetchone()
    if fila:
        return fila[0]

    cursor.execute(
        "INSERT INTO tiendas (nombre, url_base) VALUES (?, ?)",
        (nombre, url_base),
    )
    return cursor.lastrowid


def obtener_o_crear_producto(cursor, nombre, marca, tamano_unidades, url, imagen_url=None):
    """
    Busca un producto por URL (unica). Si no existe, lo crea.
    Si ya existe, actualiza la cantidad de unidades si cambio
    (por ejemplo, si antes no la teniamos y ahora si).

    Retorna el id del producto.
    """
    cursor.execute("SELECT id, tamano_unidades FROM productos WHERE url = ?", (url,))
    fila = cursor.fetchone()

    if fila:
        producto_id, tamano_actual = fila
        # Si ahora tenemos la cantidad y antes no, actualizamos
        if tamano_unidades and not tamano_actual:
            cursor.execute(
                "UPDATE productos SET tamano_unidades = ? WHERE id = ?",
                (tamano_unidades, producto_id),
            )
        # Actualizar imagen si tenemos una nueva
        if imagen_url:
            cursor.execute(
                "UPDATE productos SET imagen_url = ? WHERE id = ?",
                (imagen_url, producto_id),
            )
        return producto_id

    cursor.execute(
        "INSERT INTO productos (nombre, marca, tamano_unidades, url, imagen_url) VALUES (?, ?, ?, ?, ?)",
        (nombre, marca, tamano_unidades, url, imagen_url),
    )
    return cursor.lastrowid


def guardar_en_db(conn, productos, fecha_scraping):
    """
    Guarda todos los productos en la base de datos SQLite.

    Para cada producto:
    1. Busca o crea la tienda
    2. Busca o crea el producto
    3. Inserta un nuevo registro de precio con la fecha actual

    Esto permite tener multiples registros del mismo producto
    en distintas fechas, creando un historico de precios.
    """
    cursor = conn.cursor()

    # Mapa de tiendas conocidas y sus URLs base
    urls_tiendas = {
        "Liquimax": "https://www.liquimax.cl",
        "Distribuidora Pepito": "https://www.distribuidorapepito.cl",
        "La Pañalera": "https://www.lapanalera.cl",
        "Pañales Tin Tin": "https://www.panalestintin.cl",
        "Santa Isabel": "https://www.santaisabel.cl",
        "Jumbo": "https://www.jumbo.cl",
        "Farmacias Ahumada": "https://www.farmaciasahumada.cl",
        "Cruz Verde": "https://www.cruzverde.cl",
    }

    insertados = 0
    for p in productos:
        tienda_nombre = p.get("tienda", "Desconocida")
        url_base = urls_tiendas.get(tienda_nombre)

        tienda_id = obtener_o_crear_tienda(cursor, tienda_nombre, url_base)

        producto_id = obtener_o_crear_producto(
            cursor,
            nombre=p.get("nombre", ""),
            marca=p.get("marca", ""),
            tamano_unidades=p.get("cantidad_unidades"),
            url=p.get("url", ""),
            imagen_url=p.get("imagen", ""),
        )

        # Calculamos precio_por_unidad: precio / cantidad de panales
        precio = p.get("precio")
        cantidad = p.get("cantidad_unidades")
        if precio and cantidad and cantidad > 0:
            precio_por_unidad = round(precio / cantidad)
        else:
            precio_por_unidad = p.get("precio_por_unidad")

        # Precio lista (para indicador de descuento)
        precio_lista = p.get("precio_lista")

        cursor.execute(
            """INSERT INTO precios (producto_id, tienda_id, precio, precio_por_unidad, precio_lista, fecha_scraping)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (producto_id, tienda_id, precio, precio_por_unidad, precio_lista, fecha_scraping),
        )
        insertados += 1

    conn.commit()
    print(f"  Base de datos: {insertados} registros de precio insertados")

    # Mostramos estadisticas del historico
    cursor.execute("SELECT COUNT(DISTINCT fecha_scraping) FROM precios")
    dias = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM precios")
    total_precios = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM productos")
    total_productos = cursor.fetchone()[0]

    print(f"  Historico: {total_precios} registros de precio, "
          f"{total_productos} productos, {dias} dia(s) de datos")


# =============================================================
# EJECUCION DE SCRAPERS
# =============================================================

def ejecutar_scraper_liquimax():
    """
    Ejecuta el scraper de Liquimax.
    Retorna True si se ejecuto correctamente.
    """
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Liquimax")
    print("=" * 60)

    try:
        from scrapers import liquimax_scraper
        liquimax_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Liquimax: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_pepito():
    """
    Ejecuta el scraper de Distribuidora Pepito.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Distribuidora Pepito")
    print("=" * 60)

    try:
        from scrapers import pepito_scraper
        pepito_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Pepito: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_lapanalera():
    """
    Ejecuta el scraper de La Pañalera.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: La Pañalera")
    print("=" * 60)

    try:
        from scrapers import lapanalera_scraper
        lapanalera_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de La Pañalera: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_tintin():
    """
    Ejecuta el scraper de Pañales Tin Tin.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Pañales Tin Tin")
    print("=" * 60)

    try:
        from scrapers import tintin_scraper
        tintin_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Pañales Tin Tin: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_santaisabel():
    """
    Ejecuta el scraper de Santa Isabel.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Santa Isabel")
    print("=" * 60)

    try:
        from scrapers import santaisabel_scraper
        santaisabel_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Santa Isabel: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_jumbo():
    """
    Ejecuta el scraper de Jumbo.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Jumbo")
    print("=" * 60)

    try:
        from scrapers import jumbo_scraper
        jumbo_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Jumbo: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_ahumada():
    """
    Ejecuta el scraper de Farmacias Ahumada.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Farmacias Ahumada")
    print("=" * 60)

    try:
        from scrapers import ahumada_scraper
        ahumada_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Farmacias Ahumada: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


def ejecutar_scraper_cruzverde():
    """
    Ejecuta el scraper de Cruz Verde.
    Retorna True si se ejecuto correctamente.
    """
    print("\n")
    print("=" * 60)
    print("EJECUTANDO SCRAPER: Cruz Verde")
    print("=" * 60)

    try:
        from scrapers import cruzverde_scraper
        cruzverde_scraper.main()
        return True
    except Exception as e:
        print(f"ERROR ejecutando scraper de Cruz Verde: {e}")
        print("Continuando con los demas scrapers...\n")
        return False


# =============================================================
# PROCESAMIENTO DE CSV
# =============================================================

def leer_csv(ruta):
    """
    Lee un archivo CSV y retorna una lista de diccionarios.
    Convierte campos numericos de texto a int.
    """
    productos = []

    if not os.path.exists(ruta):
        print(f"  AVISO: No se encontro el archivo {ruta}")
        return productos

    with open(ruta, "r", encoding="utf-8") as archivo:
        lector = csv.DictReader(archivo)
        for fila in lector:
            for campo in ("precio", "cantidad_unidades", "precio_por_unidad", "precio_lista"):
                if fila.get(campo):
                    try:
                        fila[campo] = int(fila[campo])
                    except ValueError:
                        fila[campo] = None
                else:
                    fila[campo] = None
            productos.append(fila)

    return productos


def normalizar_nombre(nombre):
    """
    Normaliza el nombre de un producto para comparar entre tiendas.
    """
    if not nombre:
        return ""

    texto = nombre.lower()

    palabras_a_eliminar = [
        r"\bpa[ñn]al(es)?\b",
        r"\bbeb[eé]\b",
        r"\badulto\b",
        r"\bunidades\b",
        r"\bunid\b",
        r"\bund\b",
        r"\btalla\b",
        r"\bun\b",
    ]
    for patron in palabras_a_eliminar:
        texto = re.sub(patron, "", texto)

    texto = re.sub(r"[^\w\s]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def marcar_precios_mas_bajos(productos):
    """
    Marca cual producto tiene el precio mas bajo en cada grupo
    de productos similares (mismo nombre normalizado).
    """
    for producto in productos:
        producto["nombre_normalizado"] = normalizar_nombre(producto["nombre"])

    precio_minimo_por_nombre = {}
    for producto in productos:
        nombre_norm = producto["nombre_normalizado"]
        precio = producto["precio"]
        if precio is None:
            continue
        if nombre_norm not in precio_minimo_por_nombre:
            precio_minimo_por_nombre[nombre_norm] = precio
        elif precio < precio_minimo_por_nombre[nombre_norm]:
            precio_minimo_por_nombre[nombre_norm] = precio

    for producto in productos:
        nombre_norm = producto["nombre_normalizado"]
        precio = producto["precio"]
        if precio is not None and nombre_norm in precio_minimo_por_nombre:
            if precio <= precio_minimo_por_nombre[nombre_norm]:
                producto["es_precio_mas_bajo"] = "Si"
            else:
                producto["es_precio_mas_bajo"] = ""
        else:
            producto["es_precio_mas_bajo"] = ""

    return productos


def guardar_consolidado(productos, ruta):
    """Guarda todos los productos combinados en un solo CSV."""
    if not productos:
        print("No hay productos para consolidar.")
        return

    os.makedirs(os.path.dirname(ruta), exist_ok=True)

    with open(ruta, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_CONSOLIDADO)
        escritor.writeheader()
        escritor.writerows(productos)

    print(f"  CSV consolidado guardado en: {ruta}")


def mostrar_resumen(productos):
    """Muestra un resumen comparativo de los datos consolidados."""
    por_tienda = {}
    for p in productos:
        tienda = p.get("tienda", "Desconocida")
        if tienda not in por_tienda:
            por_tienda[tienda] = {"total": 0, "con_precio": 0, "marcas": set()}
        por_tienda[tienda]["total"] += 1
        if p["precio"] is not None:
            por_tienda[tienda]["con_precio"] += 1
        if p.get("marca"):
            por_tienda[tienda]["marcas"].add(p["marca"])

    print()
    print("=" * 60)
    print("RESUMEN CONSOLIDADO")
    print("=" * 60)

    nombres_tiendas = []
    for tienda, datos in sorted(por_tienda.items()):
        print(f"\n  {tienda}:")
        print(f"    Productos: {datos['total']}")
        print(f"    Con precio: {datos['con_precio']}")
        print(f"    Marcas: {len(datos['marcas'])}")
        nombres_tiendas.append(f"{datos['total']} en {tienda}")

    print(f"\n  Se encontraron {' y '.join(nombres_tiendas)}")
    print(f"  Total combinado: {len(productos)} productos")

    mas_baratos = sum(1 for p in productos if p.get("es_precio_mas_bajo") == "Si")
    print(f"  Marcados como precio mas bajo: {mas_baratos}")

    con_ppu = [p for p in productos if p.get("precio_por_unidad") is not None]
    if con_ppu:
        con_ppu.sort(key=lambda p: p["precio_por_unidad"])
        print(f"\n  Top 5 panales mas baratos por unidad:")
        for i, p in enumerate(con_ppu[:5], 1):
            print(
                f"    {i}. ${p['precio_por_unidad']}/u - {p['nombre']}"
                f" ({p['tienda']}) - ${p['precio']:,}"
            )


# =============================================================
# FUNCION PRINCIPAL
# =============================================================

def main():
    """
    Funcion principal:
    1. Ejecuta cada scraper (si uno falla, continua con el otro)
    2. Lee los CSVs generados
    3. Guarda en base de datos SQLite (historico acumulativo)
    4. Combina todo en un CSV consolidado
    5. Marca los precios mas bajos
    6. Muestra resumen
    """
    print()
    print("*" * 60)
    print("  COMPARADOR DE PANALES CHILE")
    print("  Ejecutando todos los scrapers...")
    print("*" * 60)
    fecha_inicio = datetime.now()
    fecha_scraping = fecha_inicio.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  Inicio: {fecha_scraping}")
    print()

    # --- PASO 1: Ejecutar scrapers ---
    resultados = {}
    resultados["liquimax"] = ejecutar_scraper_liquimax()
    resultados["pepito"] = ejecutar_scraper_pepito()
    resultados["lapanalera"] = ejecutar_scraper_lapanalera()
    resultados["tintin"] = ejecutar_scraper_tintin()
    resultados["santaisabel"] = ejecutar_scraper_santaisabel()
    resultados["jumbo"] = ejecutar_scraper_jumbo()
    resultados["ahumada"] = ejecutar_scraper_ahumada()
    resultados["cruzverde"] = ejecutar_scraper_cruzverde()

    if not any(resultados.values()):
        print("\nERROR: Ningun scraper se ejecuto correctamente. Abortando.")
        return

    # --- PASO 2: Leer los CSVs generados ---
    print("\n\n")
    print("=" * 60)
    print("CONSOLIDANDO RESULTADOS")
    print("=" * 60)

    todos_los_productos = []

    archivos_csv = {
        "Liquimax": os.path.join(CARPETA_DATOS, "liquimax_precios.csv"),
        "Pepito": os.path.join(CARPETA_DATOS, "pepito_precios.csv"),
        "La Pañalera": os.path.join(CARPETA_DATOS, "lapanalera_precios.csv"),
        "Pañales Tin Tin": os.path.join(CARPETA_DATOS, "tintin_precios.csv"),
        "Santa Isabel": os.path.join(CARPETA_DATOS, "santaisabel_precios.csv"),
        "Jumbo": os.path.join(CARPETA_DATOS, "jumbo_precios.csv"),
        "Farmacias Ahumada": os.path.join(CARPETA_DATOS, "ahumada_precios.csv"),
        "Cruz Verde": os.path.join(CARPETA_DATOS, "cruzverde_precios.csv"),
    }

    for tienda, ruta in archivos_csv.items():
        print(f"\n  Leyendo datos de {tienda}...")
        productos = leer_csv(ruta)
        print(f"  -> {len(productos)} productos leidos")
        todos_los_productos.extend(productos)

    if not todos_los_productos:
        print("\nNo se encontraron datos para consolidar.")
        return

    # --- PASO 3: Guardar en base de datos SQLite ---
    print(f"\n  Guardando en base de datos SQLite ({ARCHIVO_DB})...")
    conn = inicializar_db()
    guardar_en_db(conn, todos_los_productos, fecha_scraping)
    conn.close()

    # --- PASO 4: Marcar precios mas bajos ---
    print("\n  Analizando precios mas bajos...")
    todos_los_productos = marcar_precios_mas_bajos(todos_los_productos)

    # --- PASO 5: Guardar CSV consolidado ---
    ruta_consolidado = os.path.join(CARPETA_DATOS, ARCHIVO_CONSOLIDADO)
    guardar_consolidado(todos_los_productos, ruta_consolidado)

    # --- PASO 6: Mostrar resumen ---
    mostrar_resumen(todos_los_productos)

    print(f"\n  Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    duracion = datetime.now() - fecha_inicio
    print(f"  Duracion total: {duracion}")
    print()


if __name__ == "__main__":
    main()
