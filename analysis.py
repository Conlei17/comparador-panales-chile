"""
Script de analisis del Comparador de Panales Chile.

Lee el archivo consolidado (data/precios_consolidados.csv) y genera
un reporte legible con estadisticas de precios, mejores ofertas,
y comparacion entre tiendas.

Uso:
    python analysis.py

El reporte se muestra en pantalla y se guarda en analysis/reporte.txt
"""

import csv
import os
from datetime import datetime


# --- CONFIGURACION ---

ARCHIVO_CONSOLIDADO = os.path.join("data", "precios_consolidados.csv")
CARPETA_REPORTES = "analysis"
ARCHIVO_REPORTE = os.path.join(CARPETA_REPORTES, "reporte.txt")

# Ancho de linea para el reporte
ANCHO = 70

# Palabras clave para identificar productos que NO son panales
# (Pepito incluye toallas higienicas, toallas humedas, apositos, etc.)
EXCLUIR_SI_CONTIENE = [
    "toalla higienica",
    "toalla higiénica",
    "toalla humeda",
    "toalla húmeda",
    "aposito",
    "apósito",
    "protector diario",
    "herbal essences",
    "shampoo",
    "acondicionador",
    "jabon",
    "jabón",
    "crema",
    "colonia",
    "mamadera",
    "chupete",
    "biberón",
    "biberon",
]


def es_panal(producto):
    """
    Determina si un producto es un panal (bebe o adulto).

    Filtra productos que no son panales como toallas higienicas,
    toallas humedas, apositos, shampoo, etc.
    """
    nombre = (producto.get("nombre") or "").lower()
    for excluir in EXCLUIR_SI_CONTIENE:
        if excluir in nombre:
            return False
    return True


def leer_datos():
    """
    Lee el CSV consolidado y retorna la lista de productos.

    Convierte los campos numericos de texto a int para poder
    hacer calculos (promedios, comparaciones, etc.).
    """
    if not os.path.exists(ARCHIVO_CONSOLIDADO):
        print(f"ERROR: No se encontro el archivo {ARCHIVO_CONSOLIDADO}")
        print("Ejecuta primero: python main.py")
        return []

    productos = []
    with open(ARCHIVO_CONSOLIDADO, "r", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        for fila in lector:
            # Convertimos campos numericos
            for campo in ("precio", "cantidad_unidades", "precio_por_unidad"):
                if fila.get(campo):
                    try:
                        fila[campo] = int(fila[campo])
                    except ValueError:
                        fila[campo] = None
                else:
                    fila[campo] = None

            productos.append(fila)

    return productos


def formatear_precio(precio):
    """
    Formatea un numero como precio chileno: 16690 -> "$16.690"
    """
    if precio is None:
        return "Sin precio"
    return f"${precio:,.0f}".replace(",", ".")


def seccion(titulo):
    """Genera un encabezado de seccion bonito para el reporte."""
    lineas = []
    lineas.append("")
    lineas.append("=" * ANCHO)
    lineas.append(f"  {titulo}")
    lineas.append("=" * ANCHO)
    return "\n".join(lineas)


def subseccion(titulo):
    """Genera un subtitulo para el reporte."""
    lineas = []
    lineas.append("")
    lineas.append(f"  {titulo}")
    lineas.append(f"  {'-' * len(titulo)}")
    return "\n".join(lineas)


def generar_resumen_general(productos):
    """
    Genera las estadisticas generales:
    - Total de productos por tienda
    - Fecha de extraccion
    """
    lineas = []
    lineas.append(seccion("RESUMEN GENERAL"))

    # Agrupar por tienda
    por_tienda = {}
    for p in productos:
        tienda = p["tienda"]
        if tienda not in por_tienda:
            por_tienda[tienda] = []
        por_tienda[tienda].append(p)

    lineas.append("")
    lineas.append(f"  Total de productos analizados: {len(productos)}")
    lineas.append("")

    for tienda in sorted(por_tienda):
        prods = por_tienda[tienda]
        con_precio = [p for p in prods if p["precio"] is not None]
        lineas.append(f"  - {tienda}: {len(prods)} productos ({len(con_precio)} con precio)")

    # Fecha de los datos
    fechas = [p.get("fecha_extraccion", "") for p in productos if p.get("fecha_extraccion")]
    if fechas:
        lineas.append("")
        lineas.append(f"  Datos extraidos el: {fechas[0][:10]}")

    return "\n".join(lineas), por_tienda


def generar_precio_promedio(por_tienda):
    """
    Calcula y muestra el precio promedio por tienda.

    Separa el analisis en panales bebe y panales adulto
    para que la comparacion sea mas justa.
    """
    lineas = []
    lineas.append(seccion("PRECIO PROMEDIO POR TIENDA"))

    # Precio promedio general
    lineas.append(subseccion("Promedio general (todos los productos)"))
    lineas.append("")

    for tienda in sorted(por_tienda):
        prods = por_tienda[tienda]
        precios = [p["precio"] for p in prods if p["precio"] is not None]
        if precios:
            promedio = sum(precios) / len(precios)
            minimo = min(precios)
            maximo = max(precios)
            lineas.append(f"  {tienda}:")
            lineas.append(f"    Precio promedio: {formatear_precio(promedio)}")
            lineas.append(f"    Precio minimo:   {formatear_precio(minimo)}")
            lineas.append(f"    Precio maximo:   {formatear_precio(maximo)}")
            lineas.append("")

    # Precio promedio por unidad (solo productos con cantidad conocida)
    lineas.append(subseccion("Promedio por unidad (precio/cantidad de panales)"))
    lineas.append("  * Solo incluye productos donde se conoce la cantidad")
    lineas.append("")

    for tienda in sorted(por_tienda):
        prods = por_tienda[tienda]
        ppus = [p["precio_por_unidad"] for p in prods if p["precio_por_unidad"] is not None]
        if ppus:
            promedio_ppu = sum(ppus) / len(ppus)
            lineas.append(f"  {tienda}:")
            lineas.append(f"    Precio promedio por panal: {formatear_precio(promedio_ppu)}")
            lineas.append(f"    Productos con dato: {len(ppus)} de {len(prods)}")
            lineas.append("")

    return "\n".join(lineas)


def generar_mas_barato_por_tienda(por_tienda):
    """
    Muestra el producto mas barato de cada tienda.
    """
    lineas = []
    lineas.append(seccion("PRODUCTO MAS BARATO EN CADA TIENDA"))

    for tienda in sorted(por_tienda):
        prods = por_tienda[tienda]
        con_precio = [p for p in prods if p["precio"] is not None]

        if not con_precio:
            continue

        # Mas barato por precio total
        mas_barato = min(con_precio, key=lambda p: p["precio"])
        lineas.append(subseccion(tienda))
        lineas.append("")
        lineas.append(f"  Mas barato por precio total:")
        lineas.append(f"    {mas_barato['nombre']}")
        lineas.append(f"    Precio: {formatear_precio(mas_barato['precio'])}")
        if mas_barato["cantidad_unidades"]:
            lineas.append(f"    Cantidad: {mas_barato['cantidad_unidades']} unidades")
        lineas.append(f"    Marca: {mas_barato['marca']}")
        lineas.append("")

        # Mas barato por unidad
        con_ppu = [p for p in prods if p["precio_por_unidad"] is not None]
        if con_ppu:
            mas_barato_ppu = min(con_ppu, key=lambda p: p["precio_por_unidad"])
            lineas.append(f"  Mas barato por unidad (mejor rendimiento):")
            lineas.append(f"    {mas_barato_ppu['nombre']}")
            lineas.append(f"    Precio: {formatear_precio(mas_barato_ppu['precio'])}")
            lineas.append(f"    Cantidad: {mas_barato_ppu['cantidad_unidades']} unidades")
            lineas.append(f"    Precio por panal: {formatear_precio(mas_barato_ppu['precio_por_unidad'])}")
            lineas.append(f"    Marca: {mas_barato_ppu['marca']}")
            lineas.append("")

    return "\n".join(lineas)


def generar_mejor_tienda(por_tienda):
    """
    Determina cual tienda tiene mejores precios en general.

    Compara los precios promedio por unidad, que es la forma
    mas justa de comparar (un paquete de 128 panales no se puede
    comparar directamente con uno de 20).
    """
    lineas = []
    lineas.append(seccion("TIENDA CON MEJORES PRECIOS EN GENERAL"))
    lineas.append("")

    # Calculamos promedio por unidad para cada tienda
    promedios = {}
    for tienda in sorted(por_tienda):
        prods = por_tienda[tienda]
        ppus = [p["precio_por_unidad"] for p in prods if p["precio_por_unidad"] is not None]
        if ppus:
            promedios[tienda] = sum(ppus) / len(ppus)

    if len(promedios) < 2:
        lineas.append("  No hay suficientes datos para comparar tiendas.")
        return "\n".join(lineas)

    # Ordenamos de menor a mayor
    ranking = sorted(promedios.items(), key=lambda x: x[1])

    ganadora = ranking[0]
    segunda = ranking[1]
    diferencia = segunda[1] - ganadora[1]
    porcentaje = (diferencia / segunda[1]) * 100

    lineas.append(f"  Comparando el precio promedio por panal individual:")
    lineas.append("")

    for i, (tienda, promedio) in enumerate(ranking, 1):
        medalla = " <-- Mas barata" if i == 1 else ""
        lineas.append(f"    {i}. {tienda}: {formatear_precio(promedio)} por panal{medalla}")

    lineas.append("")
    lineas.append(f"  Conclusion: {ganadora[0]} es en promedio")
    lineas.append(f"  {formatear_precio(diferencia)} mas barata por panal ({porcentaje:.1f}% menos)")
    lineas.append(f"  que {segunda[0]}.")
    lineas.append("")
    lineas.append("  IMPORTANTE: Este promedio mezcla panales de bebe y adulto,")
    lineas.append("  packs grandes y chicos, y distintas marcas. Para una comparacion")
    lineas.append("  mas precisa, revisa el Top 10 de ofertas mas abajo o filtra")
    lineas.append("  por marca/talla en el CSV consolidado.")

    return "\n".join(lineas)


def generar_top_ofertas(productos, n=10):
    """
    Muestra las N mejores ofertas de panales ordenadas por
    precio por unidad (de mas barato a mas caro).
    """
    lineas = []
    lineas.append(seccion(f"TOP {n} MEJORES OFERTAS DE PANALES"))
    lineas.append("")
    lineas.append("  Ordenado por precio por panal (de mas barato a mas caro).")
    lineas.append("  Solo incluye productos donde se conoce la cantidad.")
    lineas.append("")

    # Filtramos solo productos con precio por unidad
    con_ppu = [p for p in productos if p["precio_por_unidad"] is not None]

    # Ordenamos de mas barato a mas caro por unidad
    con_ppu.sort(key=lambda p: p["precio_por_unidad"])

    for i, p in enumerate(con_ppu[:n], 1):
        lineas.append(f"  {i:>2}. {p['nombre']}")
        lineas.append(f"      Tienda:          {p['tienda']}")
        lineas.append(f"      Precio total:     {formatear_precio(p['precio'])}")
        lineas.append(f"      Cantidad:         {p['cantidad_unidades']} unidades")
        lineas.append(f"      Precio por panal: {formatear_precio(p['precio_por_unidad'])}")
        lineas.append(f"      Marca:            {p['marca']}")
        lineas.append("")

    return "\n".join(lineas)


def generar_comparacion_marcas(productos):
    """
    Compara precios promedio de las marcas mas populares
    entre las distintas tiendas.
    """
    lineas = []
    lineas.append(seccion("COMPARACION POR MARCA"))
    lineas.append("")
    lineas.append("  Precio promedio por panal, por marca y tienda.")
    lineas.append("  Solo marcas presentes en al menos una tienda con cantidad conocida.")
    lineas.append("")

    # Agrupar por marca normalizada -> tienda -> precios por unidad
    marcas_normalizadas = {
        "pampers": "Pampers",
        "huggies": "Huggies",
        "babysec": "Babysec",
        "cotidian": "Cotidian",
        "win": "Win",
        "plenitud": "Plenitud",
        "tena": "Tena",
    }

    datos_marca = {}
    for p in productos:
        if p["precio_por_unidad"] is None:
            continue

        marca_lower = (p.get("marca") or "").lower()
        marca_display = None
        for clave, nombre in marcas_normalizadas.items():
            if clave in marca_lower:
                marca_display = nombre
                break

        if not marca_display:
            continue

        tienda = p["tienda"]
        clave = (marca_display, tienda)

        if clave not in datos_marca:
            datos_marca[clave] = []
        datos_marca[clave].append(p["precio_por_unidad"])

    # Organizamos por marca
    marcas_con_datos = sorted(set(m for m, t in datos_marca))
    tiendas = sorted(set(t for m, t in datos_marca))

    for marca in marcas_con_datos:
        lineas.append(f"  {marca}:")
        for tienda in tiendas:
            clave = (marca, tienda)
            if clave in datos_marca:
                ppus = datos_marca[clave]
                promedio = sum(ppus) / len(ppus)
                minimo = min(ppus)
                lineas.append(
                    f"    {tienda:25s} promedio {formatear_precio(promedio)}/u"
                    f"  (minimo {formatear_precio(minimo)}/u, {len(ppus)} productos)"
                )
            else:
                lineas.append(f"    {tienda:25s} No disponible")
        lineas.append("")

    return "\n".join(lineas)


def main():
    """
    Funcion principal: lee datos, genera el reporte y lo guarda.
    """
    print("Leyendo datos consolidados...")
    productos = leer_datos()

    if not productos:
        return

    # Filtramos solo panales (excluimos toallas, apositos, shampoo, etc.)
    total_original = len(productos)
    productos = [p for p in productos if es_panal(p)]
    excluidos = total_original - len(productos)

    print(f"Se encontraron {total_original} productos.")
    if excluidos > 0:
        print(f"Se excluyeron {excluidos} que no son panales (toallas, apositos, etc.)")
    print(f"Analizando {len(productos)} panales.")
    print("Generando reporte...\n")

    # --- Generamos cada seccion del reporte ---
    secciones = []

    # Encabezado
    secciones.append("*" * ANCHO)
    secciones.append("  COMPARADOR DE PANALES CHILE")
    secciones.append("  Reporte de Analisis de Precios")
    secciones.append(f"  Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    secciones.append("*" * ANCHO)

    # Resumen general
    resumen, por_tienda = generar_resumen_general(productos)
    secciones.append(resumen)

    # Precio promedio
    secciones.append(generar_precio_promedio(por_tienda))

    # Mas barato por tienda
    secciones.append(generar_mas_barato_por_tienda(por_tienda))

    # Mejor tienda
    secciones.append(generar_mejor_tienda(por_tienda))

    # Top 10 ofertas
    secciones.append(generar_top_ofertas(productos, n=10))

    # Comparacion por marca
    secciones.append(generar_comparacion_marcas(productos))

    # Pie de pagina
    secciones.append("")
    secciones.append("-" * ANCHO)
    secciones.append("  Fin del reporte.")
    secciones.append("  Datos extraidos de: liquimax.cl, distribuidorapepito.cl")
    secciones.append("-" * ANCHO)

    # --- Unimos todo ---
    reporte = "\n".join(secciones)

    # Mostramos en pantalla
    print(reporte)

    # Guardamos en archivo
    os.makedirs(CARPETA_REPORTES, exist_ok=True)
    with open(ARCHIVO_REPORTE, "w", encoding="utf-8") as f:
        f.write(reporte)

    print(f"\nReporte guardado en: {ARCHIVO_REPORTE}")


if __name__ == "__main__":
    main()
