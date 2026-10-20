# Despliegue en hosting

La aplicación incluye un servidor WSGI de producción (`serve.py`) y un `Procfile` para proveedores que aceptan ese formato. Está preparada para un hosting Python que permita ejecutar procesos web y montar almacenamiento persistente.

> **Guía paso a paso y plataformas gratuitas: ver [DEPLOY.md](DEPLOY.md).**

## Requisitos

- Python 3.10 o superior (la versión exacta está en `runtime.txt`).
- PostgreSQL: en modo hosting la app **exige** `DATABASE_URL`, porque SQLite no
  sobrevive a los reinicios de disco del hosting. El driver `psycopg` ya viene
  en `requirements.txt` con wheels precompilados (`psycopg[binary]`), así que no
  hace falta compilador ni librerías del sistema.
- `pytest` y `pyinstaller` viven en `requirements-dev.txt`: el hosting solo
  instala `requirements.txt`.

## Configuración requerida

1. Sube el repositorio a GitHub o al proveedor de hosting y configura la raíz del proyecto como directorio de la aplicación.
2. Usa Python 3.10 o superior. El proveedor instalará las dependencias con `pip install -r requirements.txt` y arrancará la app con `python serve.py` (o detectará el `Procfile`).
3. Configura estas variables de entorno en el panel del proveedor:

   | Variable | Valor |
   |---|---|
   | `HOSTED_MODE` | `1` |
   | `FLASK_SECRET_KEY` | Secreto aleatorio largo y privado. Puedes generarlo con `python -c "import secrets; print(secrets.token_hex(32))"`. |
   | `ADMIN_USERNAME` | Usuario administrador inicial, distinto de las credenciales de ejemplo. |
   | `ADMIN_PASSWORD` | Contraseña inicial larga y única. |
   | `DATABASE_URL` | Cadena de conexión PostgreSQL del proveedor. |
   | `APP_DATA_DIR` | Ruta del volumen persistente que proporciona el hosting. |
   | `PORT` | Normalmente lo define automáticamente el hosting. |

   `BACKUP_DIR` es opcional; por defecto se crea `respaldos_nube` dentro de `APP_DATA_DIR`. Guarda los respaldos en un volumen persistente también.

   `SESSION_COOKIE_SECURE` va en `1` en producción (HTTPS obligatorio). Ponlo en
   `0` únicamente para pruebas locales servidas por HTTP plano, porque el
   navegador no devuelve las cookies `Secure` fuera de HTTPS.

4. Despliega la aplicación y abre la URL HTTPS asignada por el proveedor. En modo hosting se exige iniciar sesión en cada navegador; no se usa la autorización por huella del servidor compartido.
5. Verifica el despliegue con la sonda de salud `GET /health`, que no requiere
   credenciales ni toca datos de negocio. Configura esa misma ruta como
   *health check path* en el panel del proveedor.

## Persistencia y límites actuales

En el ejecutable de escritorio la app usa SQLite: `APP_DATA_DIR` debe ser una
ruta escribible en un disco persistente; si el proveedor borra el disco al
reiniciar o desplegar, también se perderán ventas e inventario. No uses
almacenamiento efímero ni una carpeta sincronizada como Dropbox para operar.

En hosting la app usa PostgreSQL (`DATABASE_URL`). PostgreSQL sí tolera varias
instancias, pero la app está pensada para una sola instancia que escribe.
Para escalar horizontalmente o usar alta disponibilidad, revisá la
concurrencia de las consultas de stock.

## Antes de publicar

- No publiques `FLASK_SECRET_KEY` ni las credenciales de administrador en el repositorio. El `.gitignore` ya excluye `data/`, `build/`, `.env` y las bases de datos.
- Conserva una copia de seguridad fuera del volumen principal y verifica que pueda restaurarse.
- El hosting debe proporcionar HTTPS; las cookies de sesión quedan marcadas como seguras en modo hosting.
- El acceso inicial de administrador se configura mediante `ADMIN_USERNAME` y `ADMIN_PASSWORD`. La contraseña configurada se aplica al administrador al iniciar la app.
