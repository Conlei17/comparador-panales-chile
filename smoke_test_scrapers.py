"""
Chequeo de salud de los scrapers (smoke test).

Ejecuta la LOGICA REAL de cada scraper sobre su primera pagina/categoria y
reporta cuantos productos extrae. A diferencia de mirar el HTML "a ojo", esto
ejerce el mismo codigo que usa main.py, asi que detecta de verdad cuando un
sitio cambio de estructura y el parser dejo de funcionar.

Uso:
    python smoke_test_scrapers.py

Pensado para correr ANTES de cada deploy / corrida completa. Es rapido
(~1-2 min) porque solo pide la primera pagina de cada tienda.

Veredicto por tienda:
    OK    -> extrajo productos con precio (parser sano)
    WARN  -> extrajo productos pero ninguno con precio (revisar)
    FAIL  -> 0 productos (estructura cambio o sitio caido)
"""
import warnings
warnings.filterwarnings("ignore")

import requests
from scrapers.http_utils import obtener_pagina

resultados = {}


def verdicto(prods):
    if not prods:
        return "FAIL"
    if any(p.get("precio") for p in prods):
        return "OK"
    return "WARN"


def reportar(nombre, prods, extra=""):
    v = verdicto(prods)
    resultados[nombre] = v
    con_precio = sum(1 for p in prods if p.get("precio"))
    ej = prods[0]["nombre"][:38] if prods else "--"
    marca = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]", "ERR": "[ERR ]"}[v]
    print(f"{marca} {nombre:14} {len(prods):>3} prod | con_precio={con_precio:>3} | {ej} {extra}")


def correr(nombre, fn):
    try:
        prods, extra = fn()
        reportar(nombre, prods, extra)
    except Exception as e:
        resultados[nombre] = "ERR"
        print(f"[ERR ] {nombre:14} excepcion: {type(e).__name__}: {e}")


def t_ahumada():
    from scrapers import ahumada_scraper as A
    soup = A.obtener_pagina_api(0, "infantil-y-maternidad-mundo-pa%C3%B1ales")
    return (A.extraer_productos(soup) if soup else []), ""


def t_cruzverde():
    from scrapers import cruzverde_scraper as C
    # buscar_productos_api devuelve la respuesta COMPLETA; los hits van en .hits
    data = C.buscar_productos_api("pañales", count=24, start=0)
    hits = data.get("hits", []) if data else []
    prods = [C.procesar_hit(h) for h in hits if isinstance(h, dict)]
    return [p for p in prods if p], ""


def t_jumbo():
    from scrapers import jumbo_scraper as J
    soup = obtener_pagina(J.URLS_CATEGORIAS[0], J.HEADERS, J.TIMEOUT)
    data = J.extraer_json_datos(soup) if soup else None
    return (J.extraer_productos_de_json(data) if data else []), ""


def t_liquimax():
    from scrapers import liquimax_scraper as L
    soup = obtener_pagina("https://www.liquimax.cl/collections/panales", L.HEADERS, 20)
    return (L.extraer_productos(soup) if soup else []), ""


def t_pepito():
    from scrapers import pepito_scraper as P
    soup = obtener_pagina("https://www.distribuidorapepito.cl/panales-bebe", P.HEADERS, 20)
    return (P.extraer_productos(soup) if soup else []), ""


def t_preunic():
    from scrapers import preunic_scraper as PR
    data = PR.buscar_productos_api(913, page=1)
    inc = PR.construir_included_map(data.get("included", [])) if data else {}
    prods = [PR.procesar_producto(p, inc) for p in (data.get("data", []) if data else [])]
    return [p for p in prods if p], ""


def t_salcobrand():
    from scrapers import salcobrand_scraper as S
    from scrapers.http_utils import obtener_texto
    url = "https://salcobrand.cl/products/panales-huggies-natural-care-g-66-unidades"
    html = obtener_texto(url, S.HEADERS, 20)
    data = S.extraer_product_data(html) if html else None
    prod = S.procesar_producto(url, data) if data else None
    return ([prod] if prod else []), "(1 URL semilla)"


def t_santaisabel():
    from scrapers import santaisabel_scraper as SI
    soup = obtener_pagina("https://www.santaisabel.cl/mi-bebe/panales-y-toallas-humedas/panales", SI.HEADERS, 20)
    data = SI.extraer_json_renderdata(soup) if soup else None
    return (SI.extraer_productos_de_json(data) if data else []), ""


def t_tintin():
    from scrapers import tintin_scraper as T
    soup = obtener_pagina("https://www.panalestintin.cl/categoria-producto/bebes-y-ninos/panales-bebes-y-ninos/", T.HEADERS, 20)
    return (T.extraer_productos(soup) if soup else []), ""


def t_lapanalera():
    from scrapers import lapanalera_scraper as LP
    soup = obtener_pagina("https://www.lapanalera.cl/panales", LP.HEADERS, 20)
    return (LP.extraer_productos(soup) if soup else []), "(tienda Jumpseller; si 0, puede estar bloqueada)"


def t_mercadolibre():
    from scrapers import mercadolibre_scraper as M
    session = requests.Session()
    soup = M.obtener_pagina_ml(session, f"{M.URL_BASE}/panales-bebe")
    if soup == "RATE_LIMITED":
        return [], "(rate-limited; reintentar mas tarde)"
    return (M.extraer_productos(soup) if soup else []), ""


PRUEBAS = [
    ("Ahumada", t_ahumada), ("CruzVerde", t_cruzverde), ("Jumbo", t_jumbo),
    ("Liquimax", t_liquimax), ("Pepito", t_pepito), ("Preunic", t_preunic),
    ("Salcobrand", t_salcobrand), ("SantaIsabel", t_santaisabel),
    ("TinTin", t_tintin), ("LaPanalera", t_lapanalera),
    ("MercadoLibre", t_mercadolibre),
]


if __name__ == "__main__":
    print("=== CHEQUEO DE SALUD DE SCRAPERS (pagina 1, logica real) ===\n")
    for nombre, fn in PRUEBAS:
        correr(nombre, fn)
    print("\n=== RESUMEN ===")
    for estado in ("OK", "WARN", "FAIL", "ERR"):
        nombres = [n for n, s in resultados.items() if s == estado]
        if nombres:
            print(f"{estado}: {', '.join(nombres)}")
    n_fail = sum(1 for s in resultados.values() if s in ("FAIL", "ERR"))
    if n_fail:
        print(f"\n⚠  {n_fail} scraper(s) con problemas. Revisar antes de deploy.")
    else:
        print("\n✓ Todos los scrapers extraen productos.")
