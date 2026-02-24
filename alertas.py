"""
Modulo de alertas de precio por email.

Permite a los usuarios suscribirse a alertas cuando un producto
o grupo de productos baja de un precio objetivo.
Usa Resend para envio de emails.
"""

import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta

try:
    import resend
except ImportError:
    resend = None

from flask import render_template

DIR_PROYECTO = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_DB = os.path.join(DIR_PROYECTO, "data", "precios.db")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = "Alertas BabyAhorro <alertas@babyahorro.cl>"
BASE_URL = os.environ.get("BASE_URL", "https://babyahorro.cl")


def inicializar_alertas(db_path=None):
    """Crea las tablas de alertas si no existen."""
    db = db_path or ARCHIVO_DB
    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            tipo TEXT NOT NULL,
            producto_id INTEGER,
            marca TEXT,
            talla TEXT,
            cantidad INTEGER,
            categoria TEXT,
            nombre_display TEXT,
            precio_objetivo INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            confirmada INTEGER DEFAULT 0,
            activa INTEGER DEFAULT 1,
            fecha_creacion TEXT NOT NULL,
            FOREIGN KEY (producto_id) REFERENCES productos(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alertas_enviadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alerta_id INTEGER NOT NULL,
            precio_encontrado INTEGER NOT NULL,
            tienda TEXT,
            fecha_envio TEXT NOT NULL,
            FOREIGN KEY (alerta_id) REFERENCES alertas(id)
        )
    """)

    conn.commit()
    conn.close()


def validar_email(email):
    """Validacion basica de email."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))


def crear_alerta(db_path, email, tipo, precio_objetivo, nombre_display,
                 producto_id=None, marca=None, talla=None, cantidad=None,
                 categoria=None):
    """Crea una alerta pendiente de confirmacion. Retorna el token."""
    db = db_path or ARCHIVO_DB
    token = str(uuid.uuid4())
    ahora = datetime.now().isoformat()

    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alertas (email, tipo, producto_id, marca, talla, cantidad,
                            categoria, nombre_display, precio_objetivo, token,
                            confirmada, activa, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
    """, (email, tipo, producto_id, marca, talla, cantidad,
          categoria, nombre_display, precio_objetivo, token, ahora))
    conn.commit()
    conn.close()

    return token


def confirmar_alerta(db_path, token):
    """Marca una alerta como confirmada. Retorna dict con datos o None."""
    db = db_path or ARCHIVO_DB
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alertas WHERE token = ?", (token,))
    alerta = cursor.fetchone()
    if not alerta:
        conn.close()
        return None

    cursor.execute("UPDATE alertas SET confirmada = 1 WHERE token = ?", (token,))
    conn.commit()

    resultado = dict(alerta)
    conn.close()
    return resultado


def cancelar_alerta(db_path, token):
    """Desactiva una alerta. Retorna dict con datos o None."""
    db = db_path or ARCHIVO_DB
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alertas WHERE token = ?", (token,))
    alerta = cursor.fetchone()
    if not alerta:
        conn.close()
        return None

    cursor.execute("UPDATE alertas SET activa = 0 WHERE token = ?", (token,))
    conn.commit()

    resultado = dict(alerta)
    conn.close()
    return resultado


def enviar_email_confirmacion(token, email, nombre_display, precio_objetivo):
    """Envia email de confirmacion de alerta."""
    if not RESEND_API_KEY or not resend:
        print(f"    [Alertas] Email de confirmacion no enviado (sin API key o sin resend)")
        return False

    resend.api_key = RESEND_API_KEY

    link_confirmar = f"{BASE_URL}/alerta/confirmar/{token}/"
    precio_fmt = f"${precio_objetivo:,}".replace(",", ".")

    try:
        html = render_template("email_confirmacion.html",
                               nombre_display=nombre_display,
                               precio_objetivo=precio_fmt,
                               link_confirmar=link_confirmar)
    except Exception:
        # Fallback si no hay contexto Flask
        html = f"""
        <h2>Confirma tu alerta de precio</h2>
        <p>Producto: {nombre_display}</p>
        <p>Precio objetivo: {precio_fmt}</p>
        <p><a href="{link_confirmar}">Confirmar alerta</a></p>
        """

    try:
        link_cancelar = f"{BASE_URL}/alerta/cancelar/{token}/"
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [email],
            "subject": f"Confirma tu alerta - {nombre_display}",
            "html": html,
            "headers": {
                "List-Unsubscribe": f"<{link_cancelar}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        })
        return True
    except Exception as e:
        print(f"    [Alertas] Error enviando email de confirmacion: {e}")
        return False


def enviar_email_alerta(alerta, precio_actual, tienda, nombre_producto,
                        url_producto=None, url_tienda=None):
    """Envia email de alerta de precio."""
    if not RESEND_API_KEY or not resend:
        print(f"    [Alertas] Email de alerta no enviado (sin API key o sin resend)")
        return False

    resend.api_key = RESEND_API_KEY

    precio_fmt = f"${precio_actual:,}".replace(",", ".")
    link_cancelar = f"{BASE_URL}/alerta/cancelar/{alerta['token']}/"

    # Links con UTM
    link_producto_utm = ""
    if url_producto:
        sep = "&" if "?" in url_producto else "?"
        link_producto_utm = f"{BASE_URL}{url_producto}{sep}utm_source=alerta&utm_medium=email&utm_campaign=alerta"
    else:
        link_producto_utm = f"{BASE_URL}/?utm_source=alerta&utm_medium=email&utm_campaign=alerta"

    link_tienda_utm = ""
    if url_tienda:
        sep = "&" if "?" in url_tienda else "?"
        link_tienda_utm = f"{url_tienda}{sep}utm_source=babyahorro&utm_medium=referral&utm_campaign=alerta"

    try:
        html = render_template("email_alerta.html",
                               nombre=nombre_producto,
                               precio=precio_fmt,
                               tienda=tienda,
                               link_producto=link_producto_utm,
                               link_tienda=link_tienda_utm,
                               link_cancelar=link_cancelar)
    except Exception:
        html = f"""
        <h2>{nombre_producto} bajo a {precio_fmt}!</h2>
        <p>Tienda: {tienda}</p>
        <p><a href="{link_producto_utm}">Ver en BabyAhorro</a></p>
        <p><a href="{link_cancelar}">Cancelar alerta</a></p>
        """

    try:
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [alerta["email"]],
            "subject": f"{nombre_producto} bajo a {precio_fmt}!",
            "html": html,
            "headers": {
                "List-Unsubscribe": f"<{link_cancelar}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        })
        return True
    except Exception as e:
        print(f"    [Alertas] Error enviando email de alerta: {e}")
        return False


def verificar_alertas(db_path=None):
    """
    Verifica alertas activas y confirmadas contra precios actuales.
    Envia emails cuando el precio baja del objetivo.
    Llamar despues de cada scraping.
    """
    db = db_path or ARCHIVO_DB
    inicializar_alertas(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Obtener alertas activas y confirmadas
    cursor.execute("""
        SELECT * FROM alertas
        WHERE confirmada = 1 AND activa = 1
    """)
    alertas = [dict(row) for row in cursor.fetchall()]

    if not alertas:
        print("    [Alertas] No hay alertas activas")
        conn.close()
        return

    # Obtener ultima fecha de scraping
    cursor.execute("SELECT MAX(fecha_scraping) FROM precios")
    ultima_fecha = cursor.fetchone()[0]
    if not ultima_fecha:
        print("    [Alertas] No hay datos de precios")
        conn.close()
        return

    ahora = datetime.now()
    hace_24h = (ahora - timedelta(hours=24)).isoformat()

    total_verificadas = 0
    total_enviadas = 0

    for alerta in alertas:
        total_verificadas += 1

        # Verificar si ya se envio en las ultimas 24h
        cursor.execute("""
            SELECT COUNT(*) FROM alertas_enviadas
            WHERE alerta_id = ? AND fecha_envio > ?
        """, (alerta["id"], hace_24h))
        ya_enviada = cursor.fetchone()[0] > 0
        if ya_enviada:
            continue

        precio_actual = None
        tienda = None
        nombre_producto = None
        url_tienda = None
        url_producto_page = None

        if alerta["tipo"] == "producto" and alerta["producto_id"]:
            # Buscar precio actual del producto especifico
            cursor.execute("""
                SELECT pr.precio, pr.precio_por_unidad, t.nombre as tienda,
                       p.nombre, p.url, p.marca, p.tamano_unidades
                FROM precios pr
                JOIN productos p ON p.id = pr.producto_id
                JOIN tiendas t ON t.id = pr.tienda_id
                WHERE pr.producto_id = ? AND pr.fecha_scraping = ?
                ORDER BY pr.precio_por_unidad ASC
                LIMIT 1
            """, (alerta["producto_id"], ultima_fecha))
            row = cursor.fetchone()
            if row:
                precio_actual = row["precio_por_unidad"] or row["precio"]
                tienda = row["tienda"]
                nombre_producto = row["nombre"]
                url_tienda = row["url"]

        elif alerta["tipo"] == "grupo":
            # Buscar mejor PPU en grupo marca+talla+cantidad
            query = """
                SELECT pr.precio, pr.precio_por_unidad, t.nombre as tienda,
                       p.nombre, p.url, p.marca, p.tamano_unidades
                FROM precios pr
                JOIN productos p ON p.id = pr.producto_id
                JOIN tiendas t ON t.id = pr.tienda_id
                WHERE pr.fecha_scraping = ?
                  AND pr.precio IS NOT NULL
                  AND LOWER(p.marca) = LOWER(?)
            """
            params = [ultima_fecha, alerta["marca"]]

            if alerta["cantidad"]:
                query += " AND p.tamano_unidades = ?"
                params.append(alerta["cantidad"])

            query += " ORDER BY COALESCE(pr.precio_por_unidad, pr.precio) ASC LIMIT 1"
            cursor.execute(query, params)
            row = cursor.fetchone()

            if row:
                # Verificar talla si aplica (en Python, como hace el resto del sitio)
                from app import detectar_talla
                talla_producto = detectar_talla(row["nombre"])
                if alerta["talla"] and talla_producto != alerta["talla"]:
                    # Buscar en todos los resultados del grupo
                    cursor.execute(query.replace("LIMIT 1", ""), params)
                    rows = cursor.fetchall()
                    for r in rows:
                        if detectar_talla(r["nombre"]) == alerta["talla"]:
                            row = r
                            break
                    else:
                        row = None

                if row:
                    precio_actual = row["precio_por_unidad"] or row["precio"]
                    tienda = row["tienda"]
                    nombre_producto = row["nombre"]
                    url_tienda = row["url"]

        if precio_actual is None:
            continue

        # Verificar si el precio esta por debajo del objetivo
        if precio_actual <= alerta["precio_objetivo"]:
            enviado = enviar_email_alerta(
                alerta=alerta,
                precio_actual=precio_actual,
                tienda=tienda,
                nombre_producto=nombre_producto or alerta["nombre_display"],
                url_tienda=url_tienda,
            )

            if enviado:
                cursor.execute("""
                    INSERT INTO alertas_enviadas (alerta_id, precio_encontrado, tienda, fecha_envio)
                    VALUES (?, ?, ?, ?)
                """, (alerta["id"], precio_actual, tienda, ahora.isoformat()))
                conn.commit()
                total_enviadas += 1

    conn.close()
    print(f"    [Alertas] {total_verificadas} alertas verificadas, {total_enviadas} emails enviados")
