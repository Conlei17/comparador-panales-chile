# Comparador de Panales - Chile

Proyecto de web scraping para comparar precios de panales en tiendas chilenas.
Incluye historico de precios en base de datos SQLite y ejecucion automatica diaria.

## Estructura del proyecto

```
comparador-panales-chile/
├── scrapers/                     # Scrapers individuales por tienda
│   ├── __init__.py
│   ├── liquimax_scraper.py       # Scraper para Liquimax (plataforma Bootic)
│   └── pepito_scraper.py         # Scraper para Distribuidora Pepito (Jumpseller)
├── data/                         # Datos extraidos
│   ├── liquimax_precios.csv      # Resultados de Liquimax (ultima ejecucion)
│   ├── pepito_precios.csv        # Resultados de Pepito (ultima ejecucion)
│   ├── precios_consolidados.csv  # Todo combinado (ultima ejecucion)
│   └── precios.db                # Base de datos SQLite (historico completo)
├── analysis/                     # Reportes generados
│   └── reporte.txt               # Ultimo reporte de analisis
├── logs/                         # Logs de ejecucion automatica
│   └── scraper.log               # Salida de cada ejecucion del cron
├── main.py                       # Script principal: ejecuta todo y consolida
├── analysis.py                   # Script de analisis y reporte
├── setup_cron.sh                 # Instala/desinstala ejecucion automatica
├── requirements.txt              # Librerias necesarias
├── app.py                        # Aplicacion web Flask
├── templates/
│   └── index.html                # Pagina principal de la web app
├── static/
│   └── style.css                 # Estilos de la web app
├── .gitignore                    # Archivos ignorados por Git
└── README.md                     # Este archivo
```

## Que hace cada libreria

| Libreria         | Para que sirve                                                    |
|------------------|-------------------------------------------------------------------|
| `requests`       | Descarga paginas web (como cuando tu navegador abre una URL)      |
| `beautifulsoup4` | Lee el HTML descargado y extrae la informacion que necesitamos    |
| `pandas`         | Organiza los datos en tablas y permite exportar a CSV/Excel       |
| `lxml`           | Hace que BeautifulSoup procese el HTML mas rapido                 |
| `flask`          | Crea la aplicacion web para consultar los precios desde el navegador |

## Como instalar

### 1. Asegurate de tener Python instalado

```bash
python3 --version
```

Deberias ver algo como `Python 3.10.x` o superior.

### 2. Crea un entorno virtual

Un entorno virtual es una "burbuja" donde se instalan las librerias sin afectar el resto de tu computador.

```bash
python3 -m venv venv
```

### 3. Activa el entorno virtual

```bash
source venv/bin/activate
```

Vas a ver que tu terminal ahora muestra `(venv)` al inicio.

### 4. Instala las dependencias

```bash
pip install -r requirements.txt
```

### 5. Cuando termines de trabajar

```bash
deactivate
```

## Como ejecutar

### Opcion 1: Ejecutar todo junto (recomendado)

```bash
python main.py
```

Esto va a:
1. Ejecutar el scraper de Liquimax
2. Ejecutar el scraper de Distribuidora Pepito
3. Guardar los precios en la base de datos SQLite (historico acumulativo)
4. Combinar resultados en `data/precios_consolidados.csv`
5. Marcar que productos tienen el precio mas bajo
6. Mostrar un resumen comparativo

Si un scraper falla (por ejemplo, si un sitio esta caido), el otro sigue funcionando.

### Opcion 2: Ejecutar scrapers individuales

```bash
# Solo Liquimax
python scrapers/liquimax_scraper.py

# Solo Distribuidora Pepito
python scrapers/pepito_scraper.py
```

### Opcion 3: Solo generar el reporte de analisis

```bash
python analysis.py
```

## Base de datos SQLite

Cada vez que ejecutas `main.py`, los precios se guardan en `data/precios.db`.
A diferencia del CSV (que se sobreescribe), la base de datos **acumula datos**,
permitiendo ver como cambian los precios con el tiempo.

### Esquema de la base de datos

```
tiendas                    productos                   precios
┌──────────────────┐      ┌──────────────────────┐    ┌─────────────────────────┐
│ id (PK)          │      │ id (PK)              │    │ id (PK)                 │
│ nombre           │◄─────│ nombre               │    │ producto_id (FK)  ──────┤►productos.id
│ url_base         │      │ marca                │    │ tienda_id (FK)  ────────┤►tiendas.id
└──────────────────┘      │ tamano_unidades       │    │ precio                  │
                          │ url (UNIQUE)          │    │ precio_por_unidad       │
                          └──────────────────────┘    │ fecha_scraping          │
                                                      └─────────────────────────┘
```

- **tiendas**: Cada tienda scrapeada (Liquimax, Pepito)
- **productos**: Cada producto unico, identificado por su URL
- **precios**: Un registro por producto por ejecucion (esta tabla crece cada dia)

### Consultar la base de datos

Puedes explorar los datos con el comando `sqlite3`:

```bash
# Abrir la base de datos
sqlite3 data/precios.db

# Ver cuantos dias de datos hay
SELECT COUNT(DISTINCT fecha_scraping) FROM precios;

# Ver precios historicos de un producto
SELECT p.nombre, pr.precio, pr.fecha_scraping
FROM precios pr
JOIN productos p ON p.id = pr.producto_id
WHERE p.nombre LIKE '%Pampers Premium Care%XG%'
ORDER BY pr.fecha_scraping;

# Ver el producto mas barato hoy
SELECT p.nombre, pr.precio, pr.precio_por_unidad, t.nombre as tienda
FROM precios pr
JOIN productos p ON p.id = pr.producto_id
JOIN tiendas t ON t.id = pr.tienda_id
WHERE pr.fecha_scraping = (SELECT MAX(fecha_scraping) FROM precios)
  AND pr.precio_por_unidad IS NOT NULL
ORDER BY pr.precio_por_unidad
LIMIT 10;

# Salir
.quit
```

## Ejecucion automatica (cron)

El script `setup_cron.sh` configura una tarea automatica que ejecuta el scraper
todos los dias a las 6:00 AM, sin que tu tengas que hacer nada.

### Instalar el cron job

```bash
# 1. Dale permisos de ejecucion al script (solo la primera vez)
chmod +x setup_cron.sh

# 2. Instala el cron job
./setup_cron.sh
```

Eso es todo. A partir de ahora, el scraper se ejecutara solo a las 6 AM cada dia.

### Ver los logs de ejecucion

Cada ejecucion automatica guarda su salida en `logs/scraper.log`:

```bash
# Ver todo el log
cat logs/scraper.log

# Ver solo las ultimas 50 lineas
tail -50 logs/scraper.log

# Ver el log en tiempo real (se actualiza solo)
tail -f logs/scraper.log
```

### Verificar que el cron esta activo

```bash
crontab -l
```

Deberias ver una linea que dice algo como:
```
0 6 * * * cd /ruta/al/proyecto && python3 main.py >> logs/scraper.log 2>&1 # comparador-panales-chile
```

### Detener la ejecucion automatica

```bash
./setup_cron.sh --remove
```

Esto elimina el cron job. Los datos ya recopilados en la base de datos se mantienen.

### Nota sobre macOS

La primera vez que el cron intente ejecutarse, macOS puede pedirte permiso
en Preferencias del Sistema > Privacidad y Seguridad > Acceso completo a disco.
Debes agregar `/usr/sbin/cron` para que funcione correctamente.

## Archivos de salida

| Archivo | Se sobreescribe? | Contenido |
|---------|:---:|-----------|
| `data/liquimax_precios.csv` | Si | Ultima extraccion de Liquimax |
| `data/pepito_precios.csv` | Si | Ultima extraccion de Pepito |
| `data/precios_consolidados.csv` | Si | Todo combinado (ultima ejecucion) |
| `data/precios.db` | **No** | Historico completo de precios |
| `analysis/reporte.txt` | Si | Ultimo reporte de analisis |
| `logs/scraper.log` | No (append) | Log acumulativo de ejecuciones |

## Aplicacion web

La app web permite buscar y comparar precios desde el navegador, ideal para compartir con otras mamas.

### Ejecutar la app

```bash
python app.py
```

Luego abre en tu navegador: **http://localhost:8080**

### Que puedes hacer

- Filtrar por **marca** (Pampers, Huggies, Babysec, etc.)
- Filtrar por **talla** (RN, P, M, G, XG, XXG, XXXG)
- Ver una tabla ordenada por **precio por unidad** (mas barato primero)
- El mejor precio se destaca con un badge verde **"MEJOR PRECIO"**
- Cada producto tiene un link directo a la tienda para comprarlo
- Funciona bien desde el celular (responsive)

### Notas

- La app lee los datos de `data/precios.db` (la base de datos SQLite)
- Para que haya datos, debes haber ejecutado `python main.py` al menos una vez
- Los datos se actualizan automaticamente si tienes el cron configurado

## Tiendas soportadas

| Tienda | Sitio web | Plataforma |
|--------|-----------|------------|
| Liquimax | liquimax.cl | Bootic |
| Distribuidora Pepito | distribuidorapepito.cl | Jumpseller |
