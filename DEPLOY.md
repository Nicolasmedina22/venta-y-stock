# Despliegue en hosting gratuito

Guía práctica para subir **Venta y Stock** a un hosting Python gratuito.
Todo lo que sigue está probado contra PostgreSQL 16 real.

---

## 1. Requisitos que ya cumple el proyecto

| Pieza | Estado |
|---|---|
| Servidor WSGI de producción (`serve.py` con waitress) | Listo |
| `Procfile` para proveedores tipo Heroku/Render | Listo |
| `requirements.txt` solo con dependencias de runtime | Listo |
| `requirements-dev.txt` con pytest y pyinstaller | Listo |
| `runtime.txt` con la versión de Python | Listo |
| `.gitignore` (no sube la base ni `build/`) | Listo |
| `.env.example` con todas las variables | Listo |
| Sonda de salud `GET /health` para los health checks | Listo |
| `render.yaml` (despliegue en un clic en Render) | Listo |
| Driver PostgreSQL (`psycopg[binary]`) en requirements | Listo |

---

## 2. Variables de entorno obligatorias

| Variable | Valor | Nota |
|---|---|---|
| `HOSTED_MODE` | `1` | Exige login en cada navegador y cookies seguras |
| `FLASK_SECRET_KEY` | secreto aleatorio | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_USERNAME` | tu usuario | Admin inicial del sistema |
| `ADMIN_PASSWORD` | tu contraseña | Se aplica al admin al arrancar |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL del proveedor |

Opcionales:

| Variable | Para qué sirve |
|---|---|
| `PORT` | Lo define el hosting (por defecto 8000) |
| `APP_DATA_DIR` | Ruta del volumen persistente (respaldos) |
| `BACKUP_DIR` | Carpeta de respaldos dentro del volumen |
| `SESSION_COOKIE_SECURE` | `1` en producción. Pon `0` solo para pruebas locales por HTTP plano |

> **Importante:** con `HOSTED_MODE=1` la app **exige PostgreSQL**. SQLite no
> sirve en hosting porque el disco es efímero y se pierde en cada despliegue.

---

## 3. Opción A — Render.com (web + PostgreSQL)

1. Sube el proyecto a GitHub:
   ```powershell
   cd "C:\Users\Nicolas\Desktop\Venta y Stock - Flask-pc"
   git add -A
   git commit -m "Preparacion para hosting"
   git remote add origin https://github.com/TU_USUARIO/venta-y-stock.git
   git push -u origin main
   ```
2. En Render: **New → Blueprint**, elige el repositorio.
3. Render lee `render.yaml` y crea el servicio web + la base.
4. Completa `ADMIN_USERNAME` y `ADMIN_PASSWORD` cuando te los pida.
5. Abrir la URL HTTPS que asigna Render.

**Limitación:** el PostgreSQL gratuito de Render **caduca a los 30 días**.
Para producción, mira la opción B.

---

## 4. Opción B — Base gratuita permanente (Neon) + hosting

Neon da PostgreSQL gratuito **sin caducidad** (se pausa solo tras 5 min de
inactividad, y wakes up al primer=request).

1. Crear una cuenta en <https://neon.tech> y un proyecto.
2. Copiar el **connection string** (pooled) → es tu `DATABASE_URL`.
3. Crear el servicio web donde prefieras (Render, Koyeb, Railway…) con:
   - `HOSTED_MODE=1`
   - `FLASK_SECRET_KEY=<secreto>`
   - `ADMIN_USERNAME` / `ADMIN_PASSWORD`
   - `DATABASE_URL=<el de Neon>`
   - `SESSION_COOKIE_SECURE=1`
   - Start command: `python serve.py`
   - Health check path: `/health`

---

## 5. Probar el despliegue antes de tocar datos reales

```powershell
# 1. Chequeo de salud
curl https://TU-URL/health

# 2. Login (debe redirigir a /venta)
curl -i -X POST https://TU-URL/login -d "usuario=ADMIN&password=CLAVE"
```

Checks manuales en el navegador:

- [ ] `/health` devuelve `{"ok": true, ...}`
- [ ] El login pide credenciales en cada navegador nuevo
- [ ] `/venta` carga con el catálogo
- [ ] El botón dice **"Otros F10"** y la tecla F10 abre el modal de producto manual
- [ ] Crear un producto y registrar una venta
- [ ] `/ventas_dia` muestra la venta y el total correcto
- [ ] `/historial_caja` y `/api/caja/historial` cuadran

---

## 6. Datos iniciales

Al arrancar contra una base vacía, la app **siembra datos de ejemplo**
(productos de ferretería, un cliente y el usuario admin). Para un negocio
real, lo correcto es:

1. Entrar con `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
2. Importar el catálogo real desde **Productos → Importar Excel** (hay
   plantilla descargable).
3. Borrar los productos de ejemplo que no apliquen.

---

## 7. Respaldos

- `BACKUP_DIR` debe apuntar a almacenamiento **persistente**, no a la carpeta
  efímera del proyecto.
- En Render/Koyeb/Railway, monta un disco persistente y apunta ahí
  `APP_DATA_DIR` y `BACKUP_DIR`.
- La rotación conserva las últimas `BACKUP_MAX_COPIAS` (7) copias.
- Copia la base fuera del hosting de forma periódica: el respaldo dentro del
  mismo servicio no te protege si te borran la cuenta.

---

## 8. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `RuntimeError: Faltan variables de entorno` | Falta `DATABASE_URL` o `FLASK_SECRET_KEY` | Completá las variables en el panel |
| `no such table: ...` | La base está vacía y falló la creación del esquema | Revisá los logs de arranque |
| `cannot connect to server` | `DATABASE_URL` mal escrita o red bloqueada | Copiá la cadena tal cual la da el proveedor |
| Login se reinicia en bucle | Falta HTTPS y la cookie es `Secure` | Usá siempre la URL HTTPS |
| 415 Unsupported Media Type | Endpoint que espera JSON y recibe form | Mandá `Content-Type: application/json` |
