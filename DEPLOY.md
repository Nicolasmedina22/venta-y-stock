# Despliegue en hosting gratuito

Guía práctica para publicar **Venta y Stock** con **Neon** (PostgreSQL) + **Render**
(servicio web Python). Todo el flujo está probado contra PostgreSQL 16 real
con TLS y con el formato exacto de URI que usa Neon.

---

## 1. Arquitectura

```
Navegador (HTTPS)
   │
   ▼
Render  ── web service Python (plan free)  ──►  waitress + Flask
   │                                                 │
   │  DATABASE_URL (con sslmode=require)             │
   ▼                                                 ▼
Neon  ── PostgreSQL (plan free, sin caducidad)  ──►  psycopg 3
```

**Por qué Neon y no el PostgreSQL gratis de Render:** el plan `free` de Render
caduca a los 30 días; el de Neon es gratuito **sin caducidad** y se pausa solo
tras 5 min de inactividad (se despierta sola en el primer request).

---

## 2. Lo que ya está listo en el repo

| Pieza | Archivo |
|---|---|
| Script que crea la base en Neon y da el `DATABASE_URL` | `tools/deploy_neon.py` |
| Script que crea el servicio web en Render | `tools/deploy_render.py` |
| Script que copia los datos del SQLite del escritorio a PostgreSQL | `tools/migrar_sqlite_a_postgres.py` |
| Dependencias de producción | `requirements.txt` |
| Dependencias de desarrollo | `requirements-dev.txt` |
| Versión de Python | `runtime.txt` |
| Variables de entorno documentadas | `.env.example` |
| Plantilla de despliegue en un clic (Render) | `render.yaml` |
| Sonda de salud | `GET /health` |
| `.gitignore` (no sube la base ni `build/`) | `.gitignore` |

---

## 3. Variables de entorno

| Variable | Valor | Nota |
|---|---|---|
| `HOSTED_MODE` | `1` | Exige login en cada navegador y cookies seguras |
| `FLASK_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | Firma las cookies |
| `ADMIN_USERNAME` | tu usuario | Admin inicial |
| `ADMIN_PASSWORD` | tu contraseña | Se aplica al admin al arrancar |
| `DATABASE_URL` | `postgresql://...@...neon.tech/neondb?sslmode=require` | Sale de `tools/deploy_neon.py` |

Opcionales: `PORT`, `APP_DATA_DIR`, `BACKUP_DIR`, `SESSION_COOKIE_SECURE`
(`1` en producción; `0` solo para pruebas locales por HTTP plano).

---

## 4. Despliegue paso a paso

### 4.1 Publicar el código en GitHub

```powershell
cd "C:\Users\Nicolas\Desktop\Venta y Stock - Flask-pc"
git remote add origin https://github.com/TU_USUARIO/venta-y-stock.git
git push -u origin main
```

Ojo: `data/` y `build/` no se suben (está en `.gitignore`).

### 4.2 Crear la base en Neon

1. Crear cuenta en <https://neon.tech>.
2. Generar una API key en **Neon Console → Account Settings → API Keys**.
3. En PowerShell:

```powershell
$env:NEON_API_KEY = "tu_api_key_de_neon"
py tools/deploy_neon.py
```

El script crea el proyecto `venta-y-stock` (PostgreSQL 16), la rama `main` y
devuelve la cadena de conexión **pooled**. También la guarda en
`neon_database_url.txt` (ignorado por git).

### 4.3 Opcional: migrar los datos del escritorio

Si querés llevar el inventario y las ventas reales del `.exe` a la nube:

```powershell
$env:DATABASE_URL = "<la cadena de Neon>"
py tools/migrar_sqlite_a_postgres.py
```

Copia 12 tablas y resincroniza las secuencias de PostgreSQL. El usuario admin
lo reconfigura la app al arrancar con `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

### 4.4 Crear el servicio web en Render

1. Generar una API key en <https://dashboard.render.com/u/settings?add-api-key>.
2. En PowerShell:

```powershell
$env:RENDER_API_KEY = "tu_api_key_de_render"
$env:DATABASE_URL   = "<la cadena de Neon>"
$env:ADMIN_USERNAME = "mi_usuario"
$env:ADMIN_PASSWORD = "mi_clave_larga_y_unica"
py tools/deploy_render.py
```

El script crea el servicio apuntando al repo de GitHub, configura las variables
de entorno, espera el deploy y prueba `/health` en la URL pública.

Si además querés que el script suba el código, agrega:

```powershell
$env:GITHUB_TOKEN = "tu_pat_de_github"   # scope: repo
$env:GITHUB_REPO  = "TU_USUARIO/venta-y-stock"
```

### 4.5 Alternativa sin API (todo desde el panel)

1. Render → **New → Blueprint** → apuntá al repo. Render lee `render.yaml`.
2. En el panel de Neon, copiá la cadena de conexión y ponela como
   `DATABASE_URL` del servicio (el `render.yaml` usa la base de Render;
   si querés Neon, editá esa variable a mano).

---

## 5. Checklist de verificación en el navegador

- [ ] `/health` devuelve `{"ok": true, ...}`
- [ ] El login pide credenciales en cada navegador nuevo
- [ ] `/venta` carga con el catálogo
- [ ] El botón dice **"Otros F10"** y la tecla **F10** abre el modal de producto manual
- [ ] Crear un producto y registrar una venta
- [ ] `/ventas_dia` muestra la venta y el total correcto
- [ ] `/historial_caja` y `/api/caja/historial` cuadran
- [ ] El logo de PostgreSQL de Neon muestra la base conectada

---

## 6. Datos iniciales

Al arrancar contra una base vacía la app **siembra datos de ejemplo**
(productos de ferretería, un cliente y el admin). Para un negocio real:

1. Entrar con `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
2. Importar el catálogo real en **Productos → Importar Excel**.
3. Borrar los productos de ejemplo que no apliquen.

---

## 7. Backups

- `BACKUP_DIR` debe apuntar a almacenamiento persistente, no a la carpeta
  efímera del proyecto.
- La rotación conserva las últimas `BACKUP_MAX_COPIAS` (7) copias.
- En Neon, el historial de la rama permite recuperar datos (Time Travel).
  **Copiá la base fuera de Neon**: un respaldo dentro del mismo servicio no te
  protege si te borran la cuenta.

---

## 8. Cuandoopies hosting de pago

Para vender y distribuir, lo que cambia es el plan del servicio web (Render) y
el de la base (Neon). La app no necesita cambios de código:

- **Render** → plan `starter` o `standard` (sin suspensions ni límites de CPU).
- **Neon** → plan `launch` o `scale` (compute siempre activo, más storage).
- Opcional: dominio propio, backups automáticos y alertas.

En ambos casos el único ajuste es cambiar los planes desde el panel; las
variables de entorno y el código quedan iguales.

---

## 9. Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `RuntimeError: Faltan variables de entorno` | Falta `DATABASE_URL` o `FLASK_SECRET_KEY` | Completá las variables en el panel |
| `no such table: ...` | La base está vacía y falló la creación del esquema | Revisá los logs de arranque |
| `could not translate host name` | `DATABASE_URL` mal escrita | Copiala tal cual la da Neon |
| `SSL connection is required` | Falta `?sslmode=require` en la URI | Usá la cadena *pooled* que entrega Neon |
| Login se reinicia en bucle | Falta HTTPS y la cookie es `Secure` | Usá siempre la URL HTTPS |
| 415 Unsupported Media Type | Endpoint que espera JSON y recibe form | Mandá `Content-Type: application/json` |
| `duplicate key value violates unique constraint` al arrancar | La base se migró a mano y las secuencias quedaron desfasadas | Ejecutá `tools/migrar_sqlite_a_postgres.py` (resincroniza secuencias) |
| El primer request tarda varios segundos | Neon pausó el compute por inactividad | Es normal; se despierta en la primera conexión |
