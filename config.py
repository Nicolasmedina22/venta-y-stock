"""
Configuración global del sistema Venta y Stock.

Aquí se definen rutas, constantes y parámetros que la app usa
en distintos módulos. Si necesitas cambiar dónde se guarda la
base de datos o la carpeta de respaldos, este es el único
archivo que deberías tocar.
"""

import os
import sys

# En el ejecutable, los datos deben persistir junto al .exe y no en _MEIPASS.
if getattr(sys, "frozen", False):
	BASE_DIR = os.path.dirname(sys.executable)
else:
	BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# En hosting, DATABASE_URL selecciona PostgreSQL. Sin ella se conserva SQLite local.
HOSTED_MODE = os.environ.get("HOSTED_MODE", "").strip().lower() in {"1", "true", "yes"}
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Nicoloco22")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Nicoloco22")
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
	DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

if HOSTED_MODE:
	variables_requeridas = {
		"FLASK_SECRET_KEY": FLASK_SECRET_KEY,
		"ADMIN_USERNAME": os.environ.get("ADMIN_USERNAME"),
		"ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD"),
		"DATABASE_URL": DATABASE_URL,
	}
	variables_faltantes = [nombre for nombre, valor in variables_requeridas.items() if not valor]
	if variables_faltantes:
		raise RuntimeError(
			"Faltan variables de entorno para hosting: " + ", ".join(variables_faltantes)
		)

# SQLite local y copias de seguridad locales.
DATA_DIR = os.path.abspath(os.environ.get("APP_DATA_DIR", os.path.join(BASE_DIR, "data")))
DB_PATH = os.path.join(DATA_DIR, "pos_ferreteria.db")

# ---------------------------------------------------------------------
# CONFIGURACIÓN DE RESPALDO EN LA NUBE
# ---------------------------------------------------------------------
# Por defecto respaldamos a una carpeta local dentro del proyecto
# (data/respaldos_nube). En un negocio real, esta ruta debe apuntar
# a una carpeta SINCRONIZADA por Dropbox, Google Drive o OneDrive,
# por ejemplo:
#
#   Windows + Dropbox:
#     C:\\Users\\TU_USUARIO\\Dropbox\\RespaldosFerreteria
#
#   Windows + OneDrive:
#     C:\\Users\\TU_USUARIO\\OneDrive\\RespaldosFerreteria
#
#   Windows + Google Drive (Streaming/Escritorio):
#     G:\\Mi unidad\\RespaldosFerreteria
#
# Con solo cambiar la carpeta que sincroniza esa app, el respaldo
# "sube a la nube" automáticamente sin que el negocio tenga que
# hacer nada más. Ver MANUAL_INSTALACION.md sección "Configurar
# respaldo en la nube".
BACKUP_DIR = os.path.abspath(
	os.environ.get("BACKUP_DIR", os.path.join(DATA_DIR, "respaldos_nube"))
)

# Cuántas copias de respaldo mantener (rotación). Al superar este
# número se borra automáticamente la copia más antigua.
BACKUP_MAX_COPIAS = 7

# Nombre de la app (se usa en títulos de ventana, reportes, etc.)
NOMBRE_APP = "Venta y Stock"
VERSION_APP = "1.0.0"

# Moneda para mostrar en pantalla (símbolo)
MONEDA = "$"

# Asegura que las carpetas necesarias existan al importar config
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
