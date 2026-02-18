#!/bin/bash
# ============================================================
# setup_cron.sh - Configura ejecucion automatica diaria
#
# Este script agrega una tarea al cron de macOS para que
# main.py se ejecute automaticamente todos los dias a las 6:00 AM.
#
# Uso:
#   chmod +x setup_cron.sh
#   ./setup_cron.sh
#
# Para desinstalar:
#   ./setup_cron.sh --remove
# ============================================================

# Ruta absoluta al directorio del proyecto
DIR_PROYECTO="$(cd "$(dirname "$0")" && pwd)"

# Ruta al ejecutable de Python
# Usamos el Python del sistema; si usas venv, cambia esta linea
PYTHON="$(which python3)"

# Archivo de log donde se guardan las salidas de cada ejecucion
LOG_FILE="${DIR_PROYECTO}/logs/scraper.log"

# Comando que ejecutara el cron
CRON_CMD="cd ${DIR_PROYECTO} && ${PYTHON} main.py >> ${LOG_FILE} 2>&1"

# Comentario identificador para encontrar/eliminar esta tarea
CRON_ID="# comparador-panales-chile"

# --- FUNCION: Desinstalar ---
if [ "$1" = "--remove" ]; then
    echo "Eliminando cron job..."
    # Filtramos la linea que contiene nuestro identificador
    crontab -l 2>/dev/null | grep -v "${CRON_ID}" | crontab -
    echo "Cron job eliminado."
    echo "Puedes verificar con: crontab -l"
    exit 0
fi

# --- FUNCION: Instalar ---

# 1. Crear carpeta de logs si no existe
mkdir -p "${DIR_PROYECTO}/logs"
echo "Carpeta de logs: ${DIR_PROYECTO}/logs/"

# 2. Verificar que Python existe
if [ ! -f "${PYTHON}" ] && ! command -v python3 &> /dev/null; then
    echo "ERROR: No se encontro python3. Instala Python primero."
    exit 1
fi
echo "Python: ${PYTHON}"

# 3. Verificar que main.py existe
if [ ! -f "${DIR_PROYECTO}/main.py" ]; then
    echo "ERROR: No se encontro main.py en ${DIR_PROYECTO}"
    exit 1
fi
echo "Script: ${DIR_PROYECTO}/main.py"

# 4. Verificar que no exista ya el cron job
if crontab -l 2>/dev/null | grep -q "${CRON_ID}"; then
    echo ""
    echo "AVISO: Ya existe un cron job para este proyecto."
    echo "Si quieres reinstalarlo, primero eliminalo con:"
    echo "  ./setup_cron.sh --remove"
    exit 0
fi

# 5. Agregar el cron job
# Formato cron: minuto hora dia mes dia_semana comando
# 0 6 * * * = a las 06:00 todos los dias
(crontab -l 2>/dev/null; echo "0 6 * * * ${CRON_CMD} ${CRON_ID}") | crontab -

echo ""
echo "============================================"
echo "  Cron job instalado correctamente"
echo "============================================"
echo ""
echo "  Horario: Todos los dias a las 06:00 AM"
echo "  Logs:    ${LOG_FILE}"
echo ""
echo "  Comandos utiles:"
echo "    Ver cron activo:     crontab -l"
echo "    Ver logs:            cat ${LOG_FILE}"
echo "    Logs en tiempo real: tail -f ${LOG_FILE}"
echo "    Desinstalar:         ./setup_cron.sh --remove"
echo ""
