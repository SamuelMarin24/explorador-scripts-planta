# ============================================================
#  CONFIGURACIÓN - Explorador y Ejecutor de Scripts
#
#  Todo lo específico de tu entorno (rutas, puerto, scripts a
#  destacar) vive en un .env, no aquí. Copia .env.example como
#  .env y ajústalo antes de arrancar.
#
#  Usa rutas UNC (\\servidor\carpeta), no una unidad de red tipo
#  Z:, porque esa letra no existe cuando la app corre como tarea
#  del sistema en vez de una sesión de usuario.
# ============================================================

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # Sin python-dotenv se usan las variables de entorno del sistema

PUERTO = int(os.getenv("PUERTO", "5000"))
NOMBRE_AREA = os.getenv("NOMBRE_AREA", "Explorador de Scripts")

# Carpeta raíz sobre la que se arma todo lo demás
AREA = os.getenv("AREA", r"C:\ruta\a\tu\area")

# ------------------------------------------------------------
#  CARPETAS del explorador
#  ruta     : dónde busca
#  mostrar  : extensiones visibles. [] o sin poner = muestra todo
#  plano    : True junta los archivos de todas las subcarpetas en
#             una sola lista (no hay que entrar carpeta por carpeta)
#  ejecutar : True permite correr los .bat de esa carpeta desde la web
# ------------------------------------------------------------
CARPETAS = {
    # Se navega carpeta por carpeta, pero adentro SOLO se ven los .bat
    "Por carpeta": {
        "ruta": AREA,
        "mostrar": ["bat", "cmd"],
        "ejecutar": True,
    },
    # Lo mismo pero en una sola lista, sin entrar a las carpetas
    "Todos los .bat": {
        "ruta": AREA,
        "mostrar": ["bat", "cmd"],
        "plano": True,
        "ejecutar": True,
    },
    "Informes BI": {
        "ruta": AREA + r"\Informes BI",
        "mostrar": ["pbix"],
        "plano": True,
    },
    "Documentos": {
        "ruta": AREA + r"\Documentos",
    },
}

# ------------------------------------------------------------
#  Procesos destacados: salen como botones grandes arriba.
#  Ejemplo de un proceso con menú (la entrada simula lo que el
#  usuario escribiría en la consola del .bat):
#
#  SCRIPTS = [
#      {
#          "id": "reporte_diario",
#          "nombre": "Reporte diario",
#          "descripcion": "Valida los archivos del día y sube el reporte.",
#          "ruta": AREA + r"\Scripts\reporte_diario\REPORTE.bat",
#          "entrada": "2\n",
#      },
#  ]
# ------------------------------------------------------------
SCRIPTS = []

# ------------------------------------------------------------
#  INFORMES DE POWER BI publicados en Power BI Service.
#  Los .pbix locales no se pueden ver en el navegador; solo
#  los informes publicados. Clave = nombre del .pbix,
#  valor = enlace de "Archivo > Insertar informe > Sitio web".
# ------------------------------------------------------------
INFORMES_POWER_BI = {}

TIEMPO_MAXIMO = int(os.getenv("TIEMPO_MAXIMO", "900"))          # 15 min por defecto
MAX_LINEAS_SALIDA = 3000       # líneas de consola guardadas por ejecución
MAX_HISTORIAL = 30             # ejecuciones recientes que se muestran
MAX_ARCHIVOS_PLANO = 400       # tope al juntar subcarpetas
PROFUNDIDAD_PLANO = 4          # niveles de subcarpetas que recorre

# Con un filtro activo, esconde las carpetas que al entrar
# aparecerían vacías (las que no tienen ningún archivo del tipo pedido)
OCULTAR_CARPETAS_VACIAS = True

# Peso máximo (MB) que se puede previsualizar en la ventana emergente
MAX_MB_VISTA = 25

# "Abrir" lanza el archivo en el PC donde corre Flask.
# Solo aparece para quien navega desde ese mismo equipo.
PERMITIR_ABRIR_EN_SERVIDOR = os.getenv("PERMITIR_ABRIR_EN_SERVIDOR", "true").lower() == "true"

ARCHIVO_LOG = os.getenv("ARCHIVO_LOG", "ejecuciones.log")
