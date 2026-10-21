"""
Capa de acceso a datos (PostgreSQL en hosting, SQLite en escritorio).

Contiene:
- Conexión a la base de datos.
- Creación del esquema (tablas) si no existen.
- Funciones de alto nivel usadas por la interfaz gráfica:
  usuarios, productos, clientes, ventas, caja y reportes.

PostgreSQL se activa mediante DATABASE_URL. Sin esa variable, el
ejecutable y el desarrollo local conservan SQLite.
"""

import sqlite3
import datetime
import json
import os
import re
from contextlib import contextmanager

from config import DATABASE_URL, DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD
from utils.seguridad import hashear_password


# ---------------------------------------------------------------------
# CONEXIÓN
# ---------------------------------------------------------------------

class _PostgresRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _postgres_row_factory(cursor):
    # En los comandos sin conjunto de resultados (CREATE TABLE, INSERT, etc.)
    # psycopg llama al factory con description = None. En ese caso hay que
    # devolver un conversor vacio, porque no se leeran filas.
    if cursor.description is None:
        return lambda valores: None
    nombres = [columna.name for columna in cursor.description]
    return lambda valores: _PostgresRow(zip(nombres, valores))


def _convertir_sql_postgresql(sql: str) -> str:
    ignorar_conflicto = bool(re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.IGNORECASE))
    sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.IGNORECASE)
    sql = sql.replace("?", "%s")
    sql = re.sub(r"\bMAX\(0,\s*saldo_deuda\s*-\s*%s\)", r"GREATEST(0, saldo_deuda - %s)", sql)
    sql = re.sub(r"\bLIKE\b", "ILIKE", sql, flags=re.IGNORECASE)
    if ignorar_conflicto:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class _CursorAdapter:
    def __init__(self, cursor, postgres: bool):
        self._cursor = cursor
        self._postgres = postgres

    def execute(self, sql, parameters=None):
        if self._postgres:
            sql = _convertir_sql_postgresql(sql)
        if parameters is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, parameters)
        return self

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def _crear_cursor(conexion):
    return _CursorAdapter(conexion.cursor(), DATABASE_URL is not None)


def obtener_conexion():
    """
    Abre una conexión nueva a la base de datos.
    Cada operación abre y cierra su propia conexión para evitar
    problemas cuando varias pantallas usan la base al mismo tiempo.
    """
    if DATABASE_URL:
        import psycopg

        return psycopg.connect(DATABASE_URL, row_factory=_postgres_row_factory)
    conexion = sqlite3.connect(DB_PATH)
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.row_factory = sqlite3.Row
    return conexion


@contextmanager
def cursor_db():
    """
    Context manager cómodo:

        with cursor_db() as cur:
            cur.execute(...)

    Hace commit automático al salir si no hubo errores, y rollback
    si hubo una excepción. Cierra la conexión siempre.
    """
    conexion = obtener_conexion()
    try:
        cur = _crear_cursor(conexion)
        yield cur
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


# ---------------------------------------------------------------------
# ESQUEMA
# ---------------------------------------------------------------------

def _migrar_detalle_ventas_si_necesario():
    with cursor_db() as cur:
        if DATABASE_URL:
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
                ("detalle_ventas",),
            )
            if cur.fetchone() is None:
                return
            cur.execute(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
                ("detalle_ventas", "producto_id"),
            )
            columna_producto = cur.fetchone()
            if columna_producto and columna_producto["is_nullable"] == "NO":
                cur.execute("ALTER TABLE detalle_ventas ALTER COLUMN producto_id DROP NOT NULL")
            return

        cur.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'detalle_ventas'")
        if cur.fetchone() is None:
            return

        cur.execute("PRAGMA table_info(detalle_ventas)")
        columnas = cur.fetchall()
        columna_producto = next((col for col in columnas if col[1] == "producto_id"), None)
        if not columna_producto or columna_producto[3] != 1:
            return

        cur.execute("""
            CREATE TABLE detalle_ventas_nueva (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER,
                nombre_producto TEXT NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        """)
        cur.execute(
            """
            INSERT INTO detalle_ventas_nueva (id, venta_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal)
            SELECT id, venta_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal
            FROM detalle_ventas
            """
        )
        cur.execute("DROP TABLE detalle_ventas")
        cur.execute("ALTER TABLE detalle_ventas_nueva RENAME TO detalle_ventas")


def _migrar_usuario_administrador():
    """Actualiza el acceso administrador inicial sin cambiar su ID."""
    ahora = datetime.datetime.now().isoformat(timespec="seconds")

    with cursor_db() as cur:
        cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (ADMIN_USERNAME,))
        usuario_nuevo = cur.fetchone()

        if usuario_nuevo is None:
            password_hash = hashear_password(ADMIN_PASSWORD)
            cur.execute(
                "SELECT id FROM usuarios WHERE usuario IN (?, ?) AND rol = 'admin' ORDER BY CASE usuario WHEN ? THEN 0 ELSE 1 END LIMIT 1",
                ("Nicoloco22", "admin", "Nicoloco22"),
            )
            administrador = cur.fetchone()
            if administrador is not None:
                cur.execute(
                    """UPDATE usuarios
                       SET nombre_completo = ?, usuario = ?, password_hash = ?, rol = 'admin', activo = 1
                       WHERE id = ?""",
                    (ADMIN_USERNAME, ADMIN_USERNAME, password_hash, administrador["id"]),
                )
            else:
                cur.execute(
                    """INSERT INTO usuarios
                       (nombre_completo, usuario, password_hash, rol, activo, fecha_creacion)
                       VALUES (?, ?, ?, 'admin', 1, ?)""",
                    (ADMIN_USERNAME, ADMIN_USERNAME, password_hash, ahora),
                )
        elif os.environ.get("ADMIN_PASSWORD"):
            cur.execute(
                "UPDATE usuarios SET password_hash = ?, activo = 1, rol = 'admin' WHERE id = ?",
                (hashear_password(ADMIN_PASSWORD), usuario_nuevo["id"]),
            )

        cur.execute(
            "UPDATE usuarios SET activo = 0 WHERE usuario IN (?, ?, ?) AND usuario != ?",
            ("admin", "vendedor", "Nicoloco22", ADMIN_USERNAME),
        )


def inicializar_base_datos(sembrar: bool = True):
    """
    Crea todas las tablas si no existen todavía. Es seguro llamar
    esta función cada vez que arranca la app.
    """
    with cursor_db() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_completo TEXT NOT NULL,
                usuario TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL CHECK (rol IN ('admin', 'vendedor')),
                activo INTEGER NOT NULL DEFAULT 1,
                fecha_creacion TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_barras TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                categoria TEXT,
                precio_venta REAL NOT NULL,
                costo REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                unidad TEXT NOT NULL DEFAULT 'unidad',
                activo INTEGER NOT NULL DEFAULT 1
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE COLLATE NOCASE
            )
        """)

        cur.execute("""
            INSERT OR IGNORE INTO categorias (nombre)
            SELECT DISTINCT TRIM(categoria) FROM productos
            WHERE categoria IS NOT NULL AND TRIM(categoria) != ''
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT,
                direccion TEXT,
                limite_credito REAL NOT NULL DEFAULT 0,
                saldo_deuda REAL NOT NULL DEFAULT 0,
                fecha_registro TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                cliente_id INTEGER,
                fecha TEXT NOT NULL,
                total REAL NOT NULL,
                forma_pago TEXT NOT NULL CHECK (forma_pago IN ('efectivo', 'fiado', 'tarjeta')),
                anulada INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS detalle_ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL,
                producto_id INTEGER,
                nombre_producto TEXT NOT NULL,
                cantidad INTEGER NOT NULL,
                precio_unitario REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (venta_id) REFERENCES ventas(id),
                FOREIGN KEY (producto_id) REFERENCES productos(id)
            )
        """)

        _migrar_detalle_ventas_si_necesario()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS abonos_deuda (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                fecha TEXT NOT NULL,
                forma_pago TEXT NOT NULL DEFAULT 'efectivo',
                FOREIGN KEY (cliente_id) REFERENCES clientes(id),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)

        # Migración: agregar forma_pago si la DB ya existe sin esa columna
        if DATABASE_URL:
            cur.execute(
                "ALTER TABLE abonos_deuda ADD COLUMN IF NOT EXISTS forma_pago TEXT NOT NULL DEFAULT 'efectivo'"
            )
        else:
            try:
                cur.execute("ALTER TABLE abonos_deuda ADD COLUMN forma_pago TEXT NOT NULL DEFAULT 'efectivo'")
            except Exception:
                pass  # Ya existe la columna, ignorar

        cur.execute("""
            CREATE TABLE IF NOT EXISTS cierres_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                total_efectivo REAL NOT NULL,
                total_fiado REAL NOT NULL,
                total_tarjeta REAL NOT NULL,
                total_general REAL NOT NULL,
                cantidad_ventas INTEGER NOT NULL,
                detalle_json TEXT DEFAULT '',
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS otros_ingresos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                descripcion TEXT NOT NULL DEFAULT '',
                forma_pago TEXT NOT NULL DEFAULT 'efectivo' CHECK (forma_pago IN ('efectivo', 'tarjeta')),
                fecha TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS otros_egresos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                descripcion TEXT NOT NULL DEFAULT '',
                forma_pago TEXT NOT NULL DEFAULT 'efectivo' CHECK (forma_pago IN ('efectivo', 'tarjeta')),
                fecha TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
            """
        )

        # Migración para bases ya existentes sin la columna forma_pago
        # En PostgreSQL un ALTER fallido aborta la transaccion completa,
        # por eso se usa "IF NOT EXISTS" en vez de capturar la excepcion.
        for nombre_tabla in ("otros_ingresos", "otros_egresos"):
            if DATABASE_URL:
                cur.execute(
                    f"ALTER TABLE {nombre_tabla} ADD COLUMN IF NOT EXISTS forma_pago "
                    "TEXT NOT NULL DEFAULT 'efectivo'"
                )
            else:
                try:
                    cur.execute(
                        f"ALTER TABLE {nombre_tabla} ADD COLUMN forma_pago TEXT NOT NULL DEFAULT 'efectivo'"
                    )
                except Exception:
                    pass  # Ya existe la columna, ignorar

        if DATABASE_URL:
            cur.execute("ALTER TABLE cierres_caja ADD COLUMN IF NOT EXISTS detalle_json TEXT DEFAULT ''")
        else:
            try:
                cur.execute("ALTER TABLE cierres_caja ADD COLUMN detalle_json TEXT DEFAULT ''")
            except Exception:
                pass

        # Equipos (PCs) que ya fueron autorizados con usuario y contraseña.
        # Mientras el sistema corra en uno de estos equipos no volverá a
        # pedir credenciales; en un equipo nuevo sí las pedirá.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS equipos_autorizados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identificador TEXT NOT NULL UNIQUE,
                nombre_equipo TEXT NOT NULL DEFAULT '',
                ip_local TEXT NOT NULL DEFAULT '',
                fecha_autorizacion TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_categorias_nombre_lower ON categorias (LOWER(nombre))"
        )

        # Block de notas (365 paginas). app.py tambien la crea al importar,
        # pero debe formar parte del esquema para que las bases temporales
        # de los tests queden completas.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS block_notas (
                pagina INTEGER PRIMARY KEY,
                fecha TEXT NOT NULL,
                contenido TEXT NOT NULL DEFAULT ''
            )
        """)

    if sembrar:
        sembrar_datos_ejemplo()
        _migrar_usuario_administrador()

# ---------------------------------------------------------------------
# DATOS DE EJEMPLO (SEED)
# ---------------------------------------------------------------------

def _hay_datos():
    with cursor_db() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM usuarios")
        return cur.fetchone()["n"] > 0


def sembrar_datos_ejemplo():
    """
    Si la base está vacía (primera vez que se abre la app), la
    llena con datos de ejemplo de una ferretería ficticia llamada
    "Ferretería El Tornillo Feliz": usuarios, productos de
    tornillería/herramientas y clientes fiado.
    """
    if _hay_datos():
        return

    ahora = datetime.datetime.now().isoformat(timespec="seconds")

    with cursor_db() as cur:
        # --- Usuarios de demo ---
        usuarios_demo = [
            ("Nicoloco22", "Nicoloco22", "Nicoloco22", "admin"),
        ]
        for nombre, usuario, password, rol in usuarios_demo:
            cur.execute(
                """INSERT INTO usuarios
                   (nombre_completo, usuario, password_hash, rol, activo, fecha_creacion)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (nombre, usuario, hashear_password(password), rol, ahora),
            )

        # --- Productos de ejemplo: tornillería y ferretería ---
        productos_demo = [
            ("7501234560012", "Tornillo Phillips 1/4 x 1\"", "Tornillería", 0.15, 0.07, 500, "unidad"),
            ("7501234560029", "Tornillo Phillips 1/4 x 2\"", "Tornillería", 0.20, 0.10, 400, "unidad"),
            ("7501234560036", "Tuerca hexagonal 1/4\"", "Tornillería", 0.10, 0.04, 600, "unidad"),
            ("7501234560043", "Clavo de 2 pulgadas (kg)", "Clavos", 1.80, 1.10, 50, "kg"),
            ("7501234560050", "Clavo de 3 pulgadas (kg)", "Clavos", 1.95, 1.20, 45, "kg"),
            ("7501234560067", "Cinta métrica 5m", "Herramientas", 4.50, 2.80, 25, "unidad"),
            ("7501234560074", "Martillo de uña 16oz", "Herramientas", 9.90, 6.20, 15, "unidad"),
            ("7501234560081", "Destornillador Phillips #2", "Herramientas", 3.25, 1.90, 30, "unidad"),
            ("7501234560098", "Destornillador plano #2", "Herramientas", 3.25, 1.90, 30, "unidad"),
            ("7501234560104", "Candado 40mm", "Seguridad", 6.75, 4.10, 20, "unidad"),
            ("7501234560111", "Alambre galvanizado (kg)", "Ferretería general", 2.30, 1.50, 40, "kg"),
            ("7501234560128", "Silicón transparente 280ml", "Selladores", 3.80, 2.20, 35, "unidad"),
            ("7501234560135", "Cinta aislante negra", "Eléctrico", 1.20, 0.60, 60, "unidad"),
            ("7501234560142", "Foco LED 9W luz blanca", "Eléctrico", 2.90, 1.70, 50, "unidad"),
            ("7501234560159", "Guantes de cuero para trabajo", "Seguridad", 5.50, 3.10, 20, "par"),
            ("7501234560166", "Pintura anticorrosiva 1/4 gal", "Pinturas", 8.90, 5.60, 18, "unidad"),
            ("7501234560173", "Brocha 2 pulgadas", "Pinturas", 2.10, 1.10, 40, "unidad"),
            ("7501234560180", "Llave inglesa 8\"", "Herramientas", 7.40, 4.50, 12, "unidad"),
            ("7501234560197", "Cinta de teflón", "Plomería", 0.80, 0.35, 70, "unidad"),
            ("7501234560203", "Tubo PVC 1/2\" (metro)", "Plomería", 1.50, 0.90, 100, "metro"),
        ]
        for codigo, nombre, categoria, precio, costo, stock, unidad in productos_demo:
            cur.execute(
                """INSERT INTO productos
                   (codigo_barras, nombre, categoria, precio_venta, costo, stock, unidad, activo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (codigo, nombre, categoria, precio, costo, stock, unidad),
            )

        # --- Clientes de ejemplo (algunos con deuda / fiado) ---
        clientes_demo = [
            ("Constructora Los Andes S.A.", "8888-1234", "Av. Central 100", 500.0, 120.50),
            ("Don Ramiro Gómez", "8888-5678", "Barrio San José, casa 12", 100.0, 35.00),
            ("Ferretería El Vecino (reventa)", "8888-9012", "Calle 5, local 3", 300.0, 0.0),
            ("María Fernanda López", "8888-3456", "Residencial Las Flores #22", 80.0, 15.75),
            ("Taller Mecánico El Rayo", "8888-7890", "Zona Industrial km 3", 250.0, 60.00),
        ]
        for nombre, telefono, direccion, limite, deuda in clientes_demo:
            cur.execute(
                """INSERT INTO clientes
                   (nombre, telefono, direccion, limite_credito, saldo_deuda, fecha_registro)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nombre, telefono, direccion, limite, deuda, ahora),
            )


# ---------------------------------------------------------------------
# USUARIOS
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# EQUIPOS AUTORIZADOS (activación por PC)
# ---------------------------------------------------------------------

def equipo_esta_autorizado(identificador: str) -> bool:
    """Devuelve True si este equipo ya fue autorizado con credenciales."""
    if not identificador:
        return False
    with cursor_db() as cur:
        cur.execute(
            "SELECT 1 FROM equipos_autorizados WHERE identificador = ?",
            (identificador,),
        )
        return cur.fetchone() is not None


def autorizar_equipo(identificador: str, nombre_equipo: str = "", ip_local: str = ""):
    """
    Registra este equipo como autorizado. Se llama solo tras un login
    correcto con usuario y contraseña. Si el equipo ya estaba
    registrado, actualiza sus datos sin duplicarlo.
    """
    if not identificador:
        return
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        cur.execute(
            """INSERT INTO equipos_autorizados
               (identificador, nombre_equipo, ip_local, fecha_autorizacion)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(identificador) DO UPDATE SET
                   nombre_equipo = excluded.nombre_equipo,
                   ip_local = excluded.ip_local""",
            (identificador, nombre_equipo, ip_local, ahora),
        )


def listar_equipos_autorizados():
    """Lista los equipos que ya fueron autorizados (para el panel admin)."""
    with cursor_db() as cur:
        cur.execute(
            "SELECT * FROM equipos_autorizados ORDER BY fecha_autorizacion DESC"
        )
        return cur.fetchall()


def autenticar_usuario(usuario: str, password: str):
    """
    Verifica usuario/contraseña. Devuelve el registro del usuario
    (dict-like sqlite3.Row) si es válido y está activo, o None.
    """
    from utils.seguridad import verificar_password

    with cursor_db() as cur:
        cur.execute(
            "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1",
            (usuario,),
        )
        fila = cur.fetchone()

    if fila is None:
        return None
    if verificar_password(password, fila["password_hash"]):
        return fila
    return None


def obtener_usuario_activo(usuario: str):
    with cursor_db() as cur:
        cur.execute(
            "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1",
            (usuario,),
        )
        return cur.fetchone()


def listar_usuarios():
    with cursor_db() as cur:
        cur.execute("SELECT * FROM usuarios ORDER BY nombre_completo")
        return cur.fetchall()


def crear_usuario(nombre_completo, usuario, password, rol):
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        cur.execute(
            """INSERT INTO usuarios
               (nombre_completo, usuario, password_hash, rol, activo, fecha_creacion)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (nombre_completo, usuario, hashear_password(password), rol, ahora),
        )


def cambiar_estado_usuario(usuario_id: int, activo: bool):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE usuarios SET activo = ? WHERE id = ?",
            (1 if activo else 0, usuario_id),
        )


def cambiar_password_usuario(usuario_id: int, nueva_password: str):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE usuarios SET password_hash = ? WHERE id = ?",
            (hashear_password(nueva_password), usuario_id),
        )


# ---------------------------------------------------------------------
# PRODUCTOS
# ---------------------------------------------------------------------

def buscar_producto_por_codigo(codigo_barras: str):
    with cursor_db() as cur:
        cur.execute(
            "SELECT * FROM productos WHERE codigo_barras = ? AND activo = 1",
            (codigo_barras.strip(),),
        )
        return cur.fetchone()


def buscar_productos_por_nombre(texto: str = "", limite: int = 50):
    with cursor_db() as cur:
        texto_limpio = texto.strip()
        if not texto_limpio:
            cur.execute(
                """SELECT * FROM productos
                   WHERE activo = 1
                   ORDER BY nombre
                   LIMIT ?""",
                (limite,),
            )
            return cur.fetchall()

        patron_empieza = f"{texto_limpio.lower()}%"
        patron_palabra = f"% {texto_limpio.lower()}%"
        patron_contiene = f"%{texto_limpio.lower()}%"
        cur.execute(
            """SELECT * FROM productos
               WHERE activo = 1 AND (LOWER(nombre) LIKE ? OR codigo_barras LIKE ?)
               ORDER BY
                   CASE
                       WHEN LOWER(nombre) LIKE ? THEN 1
                       WHEN LOWER(nombre) LIKE ? THEN 2
                       WHEN LOWER(codigo_barras) LIKE ? THEN 3
                       ELSE 4
                   END,
                   nombre
               LIMIT ?""",
            (patron_contiene, patron_contiene, patron_empieza, patron_palabra, patron_empieza, limite),
        )
        return cur.fetchall()


def listar_productos():
    with cursor_db() as cur:
        cur.execute("SELECT * FROM productos WHERE activo = 1 ORDER BY nombre")
        return cur.fetchall()


def listar_todos_productos(solo_activos: bool = False):
    with cursor_db() as cur:
        if solo_activos:
            cur.execute("SELECT * FROM productos WHERE activo = 1 ORDER BY nombre")
        else:
            cur.execute("SELECT * FROM productos ORDER BY nombre")
        return cur.fetchall()


def obtener_producto(producto_id: int):
    with cursor_db() as cur:
        cur.execute("SELECT * FROM productos WHERE id = ?", (producto_id,))
        return cur.fetchone()


def _sincronizar_activo_por_stock(cur, producto_id: int):
    """
    Regla de negocio: un producto solo queda ACTIVO si tiene stock.

    Si el stock llega a 0 el producto se da de baja (deja de aparecer en el
    punto de venta). Si vuelve a tener stock, se reactiva solo.

    Se aplica en todas las vías que mueven stock: ajuste, suma, descuento por
    venta, edicion e importacion desde Excel.
    """
    cur.execute(
        "UPDATE productos "
        "SET activo = CASE WHEN COALESCE(stock, 0) > 0 THEN 1 ELSE 0 END "
        "WHERE id = ?",
        (producto_id,),
    )


def crear_producto(codigo_barras: str, nombre: str, categoria: str,
                   precio_venta: float, costo: float, stock: int,
                   unidad: str = "unidad", activo: int = 1) -> int:
    with cursor_db() as cur:
        if categoria and categoria.strip():
            cur.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (categoria.strip(),))

        # Regla: solo queda activo si tiene stock.
        if int(stock) <= 0:
            activo = 0

        consulta = """INSERT INTO productos
               (codigo_barras, nombre, categoria, precio_venta, costo, stock, unidad, activo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        if DATABASE_URL:
            consulta += " RETURNING id"
        cur.execute(
            consulta,
            (codigo_barras.strip(), nombre.strip(), categoria.strip(),
             float(precio_venta), float(costo), int(stock), unidad.strip(), int(activo)),
        )
        if DATABASE_URL:
            return cur.fetchone()["id"]
        return cur.lastrowid


def actualizar_producto(producto_id: int, codigo_barras: str, nombre: str,
                        categoria: str, precio_venta: float, costo: float,
                        stock: int, unidad: str = "unidad", activo: int = 1):
    with cursor_db() as cur:
        if categoria and categoria.strip():
            cur.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (categoria.strip(),))

        cur.execute(
            """UPDATE productos
               SET codigo_barras = ?, nombre = ?, categoria = ?,
                   precio_venta = ?, costo = ?, stock = ?, unidad = ?, activo = ?
               WHERE id = ?""",
            (codigo_barras.strip(), nombre.strip(), categoria.strip(),
             float(precio_venta), float(costo), int(stock), unidad.strip(),
             int(activo), producto_id),
        )
        # La regla manda: el estado se deduce del stock.
        _sincronizar_activo_por_stock(cur, producto_id)


def cambiar_estado_producto(producto_id: int, activo: bool):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE productos SET activo = ? WHERE id = ?",
            (1 if activo else 0, producto_id),
        )


def eliminar_producto(producto_id: int) -> tuple[bool, str]:
    """
    Intenta eliminar físicamente el producto.
    Si ya fue parte de alguna venta (está en detalle_ventas), no se borra
    para no corromper el historial contable, sino que se desactiva (baja lógica).
    Devuelve (True, 'mensaje_exito') o (False, 'mensaje_error').
    """
    with cursor_db() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM detalle_ventas WHERE producto_id = ?", (producto_id,))
        en_ventas = cur.fetchone()["total"] > 0

        if en_ventas:
            cur.execute("UPDATE productos SET activo = 0 WHERE id = ?", (producto_id,))
            return True, "El producto tiene ventas históricas asociadas. Se desactivó para preservar el historial."
        else:
            cur.execute("DELETE FROM productos WHERE id = ?", (producto_id,))
            return True, "Producto eliminado permanentemente de la base de datos."


def ajustar_stock_producto(producto_id: int, nuevo_stock: int):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE productos SET stock = ? WHERE id = ?",
            (int(nuevo_stock), producto_id),
        )
        _sincronizar_activo_por_stock(cur, producto_id)


def sumar_stock_producto(producto_id: int, cantidad: int):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE productos SET stock = stock + ? WHERE id = ?",
            (int(cantidad), producto_id),
        )
        _sincronizar_activo_por_stock(cur, producto_id)


def importar_o_actualizar_producto_desde_excel(
    codigo_barras: str,
    nombre: str,
    categoria: str = "General",
    precio_venta: float = 0.0,
    costo: float = 0.0,
    stock: int = 0,
    unidad: str = "unidad",
    modo_stock: str = "sumar",
) -> tuple[str, int]:
    """
    Inserta o actualiza un producto importado desde Excel según su código de barras o nombre.
    modo_stock:
        'sumar': suma la cantidad importada al stock existente (ideal para reposición).
        'reemplazar': sobrescribe el stock actual con el valor del Excel.
    Devuelve ('creado' | 'actualizado', producto_id).
    """
    codigo_limpio = (codigo_barras or "").strip()
    nombre_limpio = (nombre or "").strip()
    categoria_limpia = (categoria or "").strip() or "General"
    unidad_limpia = (unidad or "").strip() or "unidad"
    precio_val = max(0.0, float(precio_venta or 0))
    costo_val = max(0.0, float(costo or 0))
    stock_val = int(stock or 0)

    with cursor_db() as cur:
        if categoria_limpia:
            cur.execute("INSERT OR IGNORE INTO categorias (nombre) VALUES (?)", (categoria_limpia,))

        producto_existente = None
        if codigo_limpio:
            cur.execute("SELECT * FROM productos WHERE codigo_barras = ?", (codigo_limpio,))
            producto_existente = cur.fetchone()

        if not producto_existente and nombre_limpio:
            cur.execute("SELECT * FROM productos WHERE LOWER(nombre) = LOWER(?)", (nombre_limpio,))
            producto_existente = cur.fetchone()

        if producto_existente:
            prod_id = producto_existente["id"]
            if modo_stock == "reemplazar":
                nuevo_stock = stock_val
            else:
                nuevo_stock = int(producto_existente["stock"] or 0) + stock_val

            codigo_final = codigo_limpio if codigo_limpio else producto_existente["codigo_barras"]
            nombre_final = nombre_limpio if nombre_limpio else producto_existente["nombre"]
            cat_final = categoria_limpia if categoria_limpia != "General" else (producto_existente["categoria"] or "General")
            precio_final = precio_val if precio_val > 0 else float(producto_existente["precio_venta"] or 0)
            costo_final = costo_val if costo_val > 0 else float(producto_existente["costo"] or 0)
            unidad_final = unidad_limpia if unidad_limpia != "unidad" else (producto_existente["unidad"] or "unidad")

            cur.execute(
                """UPDATE productos
                   SET codigo_barras = ?, nombre = ?, categoria = ?,
                       precio_venta = ?, costo = ?, stock = ?, unidad = ?, activo = 1
                   WHERE id = ?""",
                (codigo_final, nombre_final, cat_final, precio_final, costo_final, nuevo_stock, unidad_final, prod_id),
            )
            # Regla: un producto con stock vuelve a estar activo; sin stock, no.
            _sincronizar_activo_por_stock(cur, prod_id)
            return "actualizado", prod_id
        else:
            if not codigo_limpio:
                import random
                codigo_limpio = str(random.randint(100000000000, 999999999999))

            # Regla: un producto recien importado sin stock queda inactivo.
            activo_importado = 1 if stock_val > 0 else 0
            consulta = """INSERT INTO productos
                   (codigo_barras, nombre, categoria, precio_venta, costo, stock, unidad, activo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
            if DATABASE_URL:
                consulta += " RETURNING id"
            cur.execute(
                consulta,
                (codigo_limpio, nombre_limpio, categoria_limpia, precio_val, costo_val,
                 stock_val, unidad_limpia, activo_importado),
            )
            if DATABASE_URL:
                nuevo_id = cur.fetchone()["id"]
            else:
                nuevo_id = cur.lastrowid
            return "creado", nuevo_id


def listar_categorias() -> list[str]:
    with cursor_db() as cur:
        cur.execute("""
            SELECT nombre FROM categorias
            UNION
            SELECT DISTINCT TRIM(categoria) FROM productos
            WHERE categoria IS NOT NULL AND TRIM(categoria) != ''
            ORDER BY 1 COLLATE NOCASE
        """)
        cats = [fila[0] for fila in cur.fetchall() if fila[0] and fila[0].strip()]
        return cats if cats else ["General"]


def listar_categorias_con_conteo() -> list[dict]:
    categorias = listar_categorias()
    with cursor_db() as cur:
        resultado = []
        for cat in categorias:
            cur.execute(
                "SELECT COUNT(*) AS total FROM productos WHERE LOWER(categoria) = LOWER(?)",
                (cat.strip(),),
            )
            conteo = cur.fetchone()["total"]
            resultado.append({"nombre": cat, "total_productos": conteo})
        return resultado


def crear_categoria(nombre: str) -> bool:
    nombre_limpio = nombre.strip()
    if not nombre_limpio:
        return False
    with cursor_db() as cur:
        cur.execute(
            "INSERT OR IGNORE INTO categorias (nombre) VALUES (?)",
            (nombre_limpio,),
        )
        return True


def renombrar_categoria(nombre_actual: str, nuevo_nombre: str) -> int:
    nombre_actual = nombre_actual.strip()
    nuevo_nombre = nuevo_nombre.strip()
    if not nombre_actual or not nuevo_nombre:
        return 0
    with cursor_db() as cur:
        # Asegurar el nuevo nombre en la tabla categorias
        cur.execute(
            "INSERT OR IGNORE INTO categorias (nombre) VALUES (?)",
            (nuevo_nombre,),
        )
        # Actualizar todos los productos con esta categoría
        cur.execute(
            "UPDATE productos SET categoria = ? WHERE LOWER(categoria) = LOWER(?)",
            (nuevo_nombre, nombre_actual),
        )
        afectados = cur.rowcount
        # Eliminar el nombre viejo si cambió
        if nombre_actual.lower() != nuevo_nombre.lower():
            cur.execute(
                "DELETE FROM categorias WHERE LOWER(nombre) = LOWER(?)",
                (nombre_actual,),
            )
        return afectados


def eliminar_categoria(nombre: str) -> bool:
    nombre_limpio = nombre.strip()
    if not nombre_limpio:
        return False
    with cursor_db() as cur:
        cur.execute(
            "DELETE FROM categorias WHERE LOWER(nombre) = LOWER(?)",
            (nombre_limpio,),
        )
        # Reasignar productos de esta categoría a 'General'
        cur.execute(
            "UPDATE productos SET categoria = 'General' WHERE LOWER(categoria) = LOWER(?)",
            (nombre_limpio,),
        )
        cur.execute(
            "INSERT OR IGNORE INTO categorias (nombre) VALUES ('General')"
        )
        return True


def listar_categorias_productos():
    return listar_categorias()


def obtener_estadisticas_inventario():
    with cursor_db() as cur:
        cur.execute("""
            SELECT
                COUNT(*) AS total_productos,
                COALESCE(SUM(CASE WHEN activo = 1 THEN stock ELSE 0 END), 0) AS unidades_stock,
                COALESCE(SUM(CASE WHEN activo = 1 THEN stock * costo ELSE 0 END), 0) AS valor_costo,
                COALESCE(SUM(CASE WHEN activo = 1 THEN stock * precio_venta ELSE 0 END), 0) AS valor_total_tienda,
                COUNT(CASE WHEN activo = 1 AND stock <= 10 AND stock > 0 THEN 1 END) AS stock_bajo,
                COUNT(CASE WHEN activo = 1 AND stock <= 0 THEN 1 END) AS stock_agotado
            FROM productos
        """)
        return cur.fetchone()


def buscar_productos_avanzado(texto: str = "", categoria: str = "Todas",
                              solo_activos: bool = False, solo_stock_bajo: bool = False):
    consulta = "SELECT * FROM productos WHERE 1=1"
    parametros = []

    if solo_activos:
        consulta += " AND activo = 1"

    if solo_stock_bajo:
        consulta += " AND stock <= 10"

    if categoria and categoria != "Todas":
        consulta += " AND categoria = ?"
        parametros.append(categoria)

    if texto:
        consulta += " AND (codigo_barras LIKE ? OR nombre LIKE ?)"
        patron_contiene = f"%{texto.strip()}%"
        parametros.extend([patron_contiene, patron_contiene])

        patron_empieza = f"{texto.strip().lower()}%"
        patron_palabra = f"% {texto.strip().lower()}%"
        consulta += """ ORDER BY
            CASE
                WHEN LOWER(nombre) LIKE ? THEN 1
                WHEN LOWER(nombre) LIKE ? THEN 2
                WHEN LOWER(codigo_barras) LIKE ? THEN 3
                ELSE 4
            END,
            nombre"""
        parametros.extend([patron_empieza, patron_palabra, patron_empieza])
    else:
        consulta += " ORDER BY nombre"

    with cursor_db() as cur:
        cur.execute(consulta, tuple(parametros))
        return cur.fetchall()


def descontar_stock(producto_id: int, cantidad: int):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE productos SET stock = stock - ? WHERE id = ?",
            (cantidad, producto_id),
        )
        _sincronizar_activo_por_stock(cur, producto_id)


# ---------------------------------------------------------------------
# CLIENTES
# ---------------------------------------------------------------------

def listar_clientes():
    with cursor_db() as cur:
        cur.execute("SELECT * FROM clientes ORDER BY nombre")
        return cur.fetchall()


def obtener_cliente(cliente_id: int):
    with cursor_db() as cur:
        cur.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
        return cur.fetchone()


def crear_cliente(nombre, telefono, direccion, limite_credito):
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        consulta = """INSERT INTO clientes
               (nombre, telefono, direccion, limite_credito, saldo_deuda, fecha_registro)
               VALUES (?, ?, ?, ?, 0, ?)"""
        if DATABASE_URL:
            consulta += " RETURNING id"
        cur.execute(consulta, (nombre, telefono, direccion, limite_credito, ahora))
        # Devuelve el id del cliente recien creado (lo usa la API para
        # registrar ventas a fiado).
        return cur.fetchone()["id"] if DATABASE_URL else cur.lastrowid


def aumentar_deuda_cliente(cliente_id: int, monto: float):
    with cursor_db() as cur:
        cur.execute(
            "UPDATE clientes SET saldo_deuda = saldo_deuda + ? WHERE id = ?",
            (monto, cliente_id),
        )


def registrar_abono_deuda(cliente_id: int, usuario_id: int, monto: float, forma_pago: str = "efectivo"):
    """Registra un abono (pago parcial o total) a la deuda de un cliente.
    Además, actualiza los totales del cierre de caja según la forma de pago (efectivo o tarjeta)."""
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        cur.execute(
            "UPDATE clientes SET saldo_deuda = GREATEST(0, saldo_deuda - ?) WHERE id = ?" if DATABASE_URL else
            "UPDATE clientes SET saldo_deuda = MAX(0, saldo_deuda - ?) WHERE id = ?",
            (monto, cliente_id),
        )
        # La columna forma_pago siempre existe: inicializar_base_datos() la
        # crea o la agrega por migracion. En PostgreSQL un INSERT fallido
        # aborta la transaccion completa, asi que ahi no se intenta un
        # segundo INSERT de respaldo.
        if DATABASE_URL:
            cur.execute(
                """INSERT INTO abonos_deuda (cliente_id, usuario_id, monto, fecha, forma_pago)
                   VALUES (?, ?, ?, ?, ?)""",
                (cliente_id, usuario_id, monto, ahora, forma_pago),
            )
        else:
            try:
                cur.execute(
                    """INSERT INTO abonos_deuda (cliente_id, usuario_id, monto, fecha, forma_pago)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cliente_id, usuario_id, monto, ahora, forma_pago),
                )
            except Exception:
                cur.execute(
                    """INSERT INTO abonos_deuda (cliente_id, usuario_id, monto, fecha)
                       VALUES (?, ?, ?, ?)""",
                    (cliente_id, usuario_id, monto, ahora),
                )
        # Actualizar totales del cierre de caja
        fecha_corte = datetime.datetime.now().date().isoformat()
        cur.execute(
            "SELECT id FROM cierres_caja WHERE usuario_id = ? AND fecha = ?",
            (usuario_id, fecha_corte),
        )
        row = cur.fetchone()
        if row:
            cierre_id = row["id"]
            if forma_pago == "efectivo":
                cur.execute(
                    "UPDATE cierres_caja SET total_efectivo = total_efectivo + ? WHERE id = ?",
                    (monto, cierre_id),
                )
            elif forma_pago == "tarjeta":
                cur.execute(
                    "UPDATE cierres_caja SET total_tarjeta = total_tarjeta + ? WHERE id = ?",
                    (monto, cierre_id),
                )
            # actualizar total_general
            cur.execute(
                "UPDATE cierres_caja SET total_general = total_general + ? WHERE id = ?",
                (monto, cierre_id),
            )
        else:
            total_efectivo = monto if forma_pago == "efectivo" else 0
            total_tarjeta = monto if forma_pago == "tarjeta" else 0
            cur.execute(
                """INSERT INTO cierres_caja (usuario_id, fecha, total_efectivo, total_fiado, total_tarjeta, total_general, cantidad_ventas)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (usuario_id, fecha_corte, total_efectivo, 0, total_tarjeta, monto, 0),
            )


def actualizar_cliente(cliente_id: int, nombre: str, telefono: str, direccion: str, limite_credito: float):
    with cursor_db() as cur:
        cur.execute(
            """UPDATE clientes
               SET nombre = ?, telefono = ?, direccion = ?, limite_credito = ?
               WHERE id = ?""",
            (nombre.strip(), telefono.strip(), direccion.strip(), float(limite_credito), cliente_id),
        )


def eliminar_cliente(cliente_id: int) -> tuple[bool, str]:
    """
    Elimina un cliente si no tiene deuda pendiente.
    Devuelve (True, 'mensaje_exito') o (False, 'mensaje_error').
    """
    with cursor_db() as cur:
        cur.execute("SELECT nombre, saldo_deuda FROM clientes WHERE id = ?", (cliente_id,))
        c = cur.fetchone()
        if not c:
            return False, "El cliente no fue encontrado."

        saldo = c["saldo_deuda"] if c["saldo_deuda"] is not None else 0.0
        if saldo > 0:
            return False, f"No se puede eliminar a «{c['nombre']}» porque mantiene una deuda pendiente de {saldo:,.2f}."

        cur.execute("UPDATE ventas SET cliente_id = NULL WHERE cliente_id = ?", (cliente_id,))
        cur.execute("DELETE FROM abonos_deuda WHERE cliente_id = ?", (cliente_id,))
        cur.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
        return True, f"El cliente «{c['nombre']}» fue eliminado correctamente."


def buscar_clientes(texto: str = ""):
    with cursor_db() as cur:
        texto_limpio = texto.strip()
        if not texto_limpio:
            cur.execute("SELECT * FROM clientes ORDER BY nombre")
            return cur.fetchall()

        patron = f"%{texto_limpio}%"
        cur.execute(
            """SELECT * FROM clientes
               WHERE nombre LIKE ? OR telefono LIKE ? OR direccion LIKE ?
               ORDER BY nombre""",
            (patron, patron, patron),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------
# VENTAS
# ---------------------------------------------------------------------

def registrar_venta(usuario_id: int, cliente_id, carrito: list, forma_pago: str):
    """
    Registra una venta completa de forma atómica (o todo se guarda,
    o nada, si algo falla en medio).

    carrito: lista de dicts con claves:
        producto_id, nombre, cantidad, precio_unitario, subtotal

    forma_pago: 'efectivo', 'tarjeta' o 'fiado'.

    Si es 'fiado', se requiere cliente_id y se incrementa su deuda.

    Devuelve el id de la venta creada.
    """
    _migrar_detalle_ventas_si_necesario()
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    total = sum(item["subtotal"] for item in carrito)

    conexion = obtener_conexion()
    try:
        cur = _crear_cursor(conexion)
        consulta = """INSERT INTO ventas (usuario_id, cliente_id, fecha, total, forma_pago, anulada)
               VALUES (?, ?, ?, ?, ?, 0)"""
        if DATABASE_URL:
            consulta += " RETURNING id"
        cur.execute(
            consulta,
            (usuario_id, cliente_id, ahora, total, forma_pago),
        )
        venta_id = cur.fetchone()["id"] if DATABASE_URL else cur.lastrowid

        for item in carrito:
            producto_id = item.get("producto_id")
            cur.execute(
                """INSERT INTO detalle_ventas
                   (venta_id, producto_id, nombre_producto, cantidad, precio_unitario, subtotal)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    venta_id,
                    producto_id,
                    item["nombre"],
                    item["cantidad"],
                    item["precio_unitario"],
                    item["subtotal"],
                ),
            )
            if producto_id is not None:
                cur.execute(
                    "UPDATE productos SET stock = stock - ? WHERE id = ?",
                    (item["cantidad"], producto_id),
                )
                # Si la venta dejo el stock en 0, el producto se da de baja.
                _sincronizar_activo_por_stock(cur, producto_id)

        if forma_pago == "fiado" and cliente_id:
            cur.execute(
                "UPDATE clientes SET saldo_deuda = saldo_deuda + ? WHERE id = ?",
                (total, cliente_id),
            )

        conexion.commit()
        return venta_id
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


def ventas_del_dia(fecha_iso: str = None):
    """Devuelve las ventas no anuladas de una fecha dada (YYYY-MM-DD)."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT v.*, u.nombre_completo AS vendedor, c.nombre AS cliente
               FROM ventas v
               LEFT JOIN usuarios u ON u.id = v.usuario_id
               LEFT JOIN clientes c ON c.id = v.cliente_id
               WHERE v.fecha LIKE ? AND v.anulada = 0
               ORDER BY v.fecha DESC""",
            (f"{fecha_iso}%",),
        )
        return cur.fetchall()


def productos_vendidos_del_dia(fecha_iso: str = None):
    """Devuelve cada producto vendido, con precio, cantidad y hora."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT dv.id AS detalle_id, dv.venta_id, dv.nombre_producto,
                      dv.cantidad, dv.precio_unitario, dv.subtotal,
                      v.fecha, v.forma_pago, u.nombre_completo AS vendedor
               FROM detalle_ventas dv
               JOIN ventas v ON v.id = dv.venta_id
               LEFT JOIN usuarios u ON u.id = v.usuario_id
               WHERE v.fecha LIKE ? AND v.anulada = 0
               ORDER BY v.fecha DESC, dv.id ASC""",
            (f"{fecha_iso}%",),
        )
        return cur.fetchall()

# ---------------------------------------------------------------------
# CIERRE DE CAJA Y REPORTES
# ---------------------------------------------------------------------

def resumen_caja_del_dia(fecha_iso: str = None):
    """
    Calcula el resumen de caja del día: total en efectivo, total
    fiado, total tarjeta, total general, cantidad de ventas, abonos
    de clientes y otros ingresos/egresos por medio de pago.
    """
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()

    with cursor_db() as cur:
        # Ventas del día
        cur.execute(
            """SELECT forma_pago, COALESCE(SUM(total), 0) AS total, COUNT(*) AS cantidad
               FROM ventas
               WHERE fecha LIKE ? AND anulada = 0
               GROUP BY forma_pago""",
            (f"{fecha_iso}%",),
        )
        filas_ventas = cur.fetchall()

        # Abonos de clientes del día agrupados por forma_pago
        cur.execute(
            """SELECT forma_pago, COALESCE(SUM(monto), 0) AS total
               FROM abonos_deuda
               WHERE fecha LIKE ?
               GROUP BY forma_pago""",
            (f"{fecha_iso}%",),
        )
        filas_abonos = cur.fetchall()

        # Otros ingresos del día agrupados por forma_pago
        cur.execute(
            """SELECT forma_pago, COALESCE(SUM(monto), 0) AS total
               FROM otros_ingresos
               WHERE fecha LIKE ?
               GROUP BY forma_pago""",
            (f"{fecha_iso}%",),
        )
        filas_otros_ingresos = cur.fetchall()

        # Otros egresos del día agrupados por forma_pago
        cur.execute(
            """SELECT forma_pago, COALESCE(SUM(monto), 0) AS total
               FROM otros_egresos
               WHERE fecha LIKE ?
               GROUP BY forma_pago""",
            (f"{fecha_iso}%",),
        )
        filas_otros_egresos = cur.fetchall()

    resumen = {
        "efectivo": 0.0, "fiado": 0.0, "tarjeta": 0.0,
        "cantidad_ventas": 0, "total_general": 0.0,
        "abonos_efectivo": 0.0, "abonos_tarjeta": 0.0,
        "otros_ingresos_efectivo": 0.0, "otros_ingresos_tarjeta": 0.0,
        "otros_egresos_efectivo": 0.0, "otros_egresos_tarjeta": 0.0,
        "efectivo_final": 0.0, "tarjeta_final": 0.0,
    }
    for fila in filas_ventas:
        fp = fila["forma_pago"]
        if fp in resumen:
            resumen[fp] = fila["total"]
        resumen["cantidad_ventas"] += fila["cantidad"]

    for fila in filas_abonos:
        fp = fila["forma_pago"]
        if fp == "efectivo":
            resumen["abonos_efectivo"] = fila["total"]
        elif fp == "tarjeta":
            resumen["abonos_tarjeta"] = fila["total"]

    for fila in filas_otros_ingresos:
        fp = fila["forma_pago"]
        if fp == "efectivo":
            resumen["otros_ingresos_efectivo"] = fila["total"]
        elif fp == "tarjeta":
            resumen["otros_ingresos_tarjeta"] = fila["total"]

    for fila in filas_otros_egresos:
        fp = fila["forma_pago"]
        if fp == "efectivo":
            resumen["otros_egresos_efectivo"] = fila["total"]
        elif fp == "tarjeta":
            resumen["otros_egresos_tarjeta"] = fila["total"]

    resumen["efectivo_final"] = (
        resumen["efectivo"]
        + resumen["abonos_efectivo"]
        + resumen["otros_ingresos_efectivo"]
        - resumen["otros_egresos_efectivo"]
    )
    resumen["tarjeta_final"] = (
        resumen["tarjeta"]
        + resumen["abonos_tarjeta"]
        + resumen["otros_ingresos_tarjeta"]
        - resumen["otros_egresos_tarjeta"]
    )
    resumen["total_general"] = resumen["efectivo_final"] + resumen["tarjeta_final"]
    return resumen


def guardar_cierre_caja(usuario_id: int):
    """Guarda una foto (snapshot) del cierre de caja del día actual."""
    resumen = resumen_caja_del_dia()
    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    detalle_str = json.dumps(resumen)
    with cursor_db() as cur:
        try:
            cur.execute(
                """INSERT INTO cierres_caja
                   (usuario_id, fecha, total_efectivo, total_fiado, total_tarjeta,
                    total_general, cantidad_ventas, detalle_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    usuario_id, ahora, resumen["efectivo"], resumen["fiado"],
                    resumen["tarjeta"], resumen["total_general"], resumen["cantidad_ventas"],
                    detalle_str,
                ),
            )
        except Exception:
            cur.execute(
                """INSERT INTO cierres_caja
                   (usuario_id, fecha, total_efectivo, total_fiado, total_tarjeta,
                    total_general, cantidad_ventas)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    usuario_id, ahora, resumen["efectivo"], resumen["fiado"],
                    resumen["tarjeta"], resumen["total_general"], resumen["cantidad_ventas"],
                ),
            )
        # Eliminar los datos del día para que al volver a abrir la app los totales aparezcan en cero
        fecha_like = f"{datetime.date.today().isoformat()}%"
        # Eliminar detalle de ventas asociado al día
        cur.execute(
            "DELETE FROM detalle_ventas WHERE venta_id IN (SELECT id FROM ventas WHERE fecha LIKE ?)",
            (fecha_like,),
        )
        # Eliminar ventas del día
        cur.execute(
            "DELETE FROM ventas WHERE fecha LIKE ?",
            (fecha_like,),
        )
        # Eliminar abonos del día
        cur.execute(
            "DELETE FROM abonos_deuda WHERE fecha LIKE ?",
            (fecha_like,),
        )
        # Eliminar otros ingresos y egresos del día para que al volver a abrir la app
        # no se dupliquen en el cierre de caja siguiente.
        cur.execute(
            "DELETE FROM otros_ingresos WHERE fecha LIKE ?",
            (fecha_like,),
        )
        cur.execute(
            "DELETE FROM otros_egresos WHERE fecha LIKE ?",
            (fecha_like,),
        )
    return resumen


def obtener_cierres_caja_por_fecha(fecha_iso: str = None):
    """Devuelve los registros de cierre de caja guardados para una fecha dada (YYYY-MM-DD)."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT c.*, u.nombre_completo AS usuario_nombre, u.usuario AS usuario_login
               FROM cierres_caja c
               LEFT JOIN usuarios u ON u.id = c.usuario_id
               WHERE c.fecha LIKE ?
               ORDER BY c.fecha DESC, c.id DESC""",
            (f"{fecha_iso}%",),
        )
        return cur.fetchall()


def resumen_caja_por_fecha(fecha_iso: str = None):
    """
    Calcula el resumen de caja para una fecha dada (YYYY-MM-DD).
    Si existen movimientos en ventas/abonos/ingresos/egresos, calcula el resumen de esos movimientos.
    Si las tablas de movimientos están vacías para ese día pero existe un cierre registrado
    en cierres_caja, reconstruye el resumen a partir de dicho cierre.
    """
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()

    resumen = dict(resumen_caja_del_dia(fecha_iso))
    cierres = obtener_cierres_caja_por_fecha(fecha_iso)

    movimientos_en_cero = (
        resumen.get("cantidad_ventas", 0) == 0 and
        resumen.get("total_general", 0) == 0 and
        resumen.get("efectivo", 0) == 0 and
        resumen.get("tarjeta", 0) == 0 and
        resumen.get("fiado", 0) == 0 and
        resumen.get("otros_ingresos_efectivo", 0) == 0 and
        resumen.get("otros_egresos_efectivo", 0) == 0 and
        resumen.get("abonos_efectivo", 0) == 0
    )

    if movimientos_en_cero and cierres:
        recuperado = False
        for c in cierres:
            c_dict = dict(c)
            d_json = c_dict.get("detalle_json")
            if d_json:
                try:
                    data = json.loads(d_json)
                    for k in resumen:
                        if k in data and isinstance(data[k], (int, float)):
                            resumen[k] = data[k]
                    recuperado = True
                    break
                except Exception:
                    pass

        if not recuperado:
            cierres_formales = [c for c in cierres if "T" in str(c["fecha"])] or cierres
            cierre_ref = cierres_formales[0]
            resumen["efectivo"] = float(cierre_ref["total_efectivo"])
            resumen["fiado"] = float(cierre_ref["total_fiado"])
            resumen["tarjeta"] = float(cierre_ref["total_tarjeta"])
            resumen["total_general"] = float(cierre_ref["total_general"])
            resumen["cantidad_ventas"] = int(cierre_ref["cantidad_ventas"])
            resumen["efectivo_final"] = float(cierre_ref["total_efectivo"])
            resumen["tarjeta_final"] = float(cierre_ref["total_tarjeta"])

    return resumen


def producto_mas_vendido_del_dia(fecha_iso: str = None):
    """Devuelve (nombre_producto, cantidad_total) del producto más vendido hoy, o None."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()

    with cursor_db() as cur:
        cur.execute(
            """SELECT dv.nombre_producto, SUM(dv.cantidad) AS total_unidades
               FROM detalle_ventas dv
               JOIN ventas v ON v.id = dv.venta_id
               WHERE v.fecha LIKE ? AND v.anulada = 0
               GROUP BY dv.nombre_producto
               ORDER BY total_unidades DESC
               LIMIT 1""",
            (f"{fecha_iso}%",),
        )
        fila = cur.fetchone()
        return (fila["nombre_producto"], fila["total_unidades"]) if fila else None


def top_productos_del_dia(fecha_iso: str = None, limite: int = 5):
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT dv.nombre_producto, SUM(dv.cantidad) AS total_unidades,
                      SUM(dv.subtotal) AS total_vendido
               FROM detalle_ventas dv
               JOIN ventas v ON v.id = dv.venta_id
               WHERE v.fecha LIKE ? AND v.anulada = 0
               GROUP BY dv.nombre_producto
               ORDER BY total_unidades DESC
               LIMIT ?""",
            (f"{fecha_iso}%", limite),
        )
        return cur.fetchall()


def clientes_con_deuda():
    with cursor_db() as cur:
        cur.execute(
            "SELECT * FROM clientes WHERE saldo_deuda > 0 ORDER BY saldo_deuda DESC"
        )
        return cur.fetchall()


# ---------------------------------------------------------------------
# OTROS INGRESOS
# ---------------------------------------------------------------------

def registrar_otro_ingreso(usuario_id: int, monto: float, descripcion: str, forma_pago: str = "efectivo"):
    """Registra un ingreso extra (no venta) del día."""
    forma_pago = (forma_pago or "efectivo").strip().lower()
    if forma_pago not in ("efectivo", "tarjeta"):
        forma_pago = "efectivo"

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        cur.execute(
            "INSERT INTO otros_ingresos (usuario_id, monto, descripcion, forma_pago, fecha) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, monto, descripcion.strip(), forma_pago, ahora),
        )


def listar_otros_ingresos_del_dia(fecha_iso: str = None):
    """Devuelve los ingresos extra del día dado (o hoy)."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT oi.id, oi.monto, oi.descripcion, oi.forma_pago, oi.fecha, u.nombre_completo AS usuario
               FROM otros_ingresos oi
               JOIN usuarios u ON u.id = oi.usuario_id
               WHERE oi.fecha LIKE ?
               ORDER BY oi.fecha DESC""",
            (f"{fecha_iso}%",),
        )
        return cur.fetchall()


def total_otros_ingresos_del_dia(fecha_iso: str = None) -> float:
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(monto), 0) AS total FROM otros_ingresos WHERE fecha LIKE ?",
            (f"{fecha_iso}%",),
        )
        return cur.fetchone()["total"]


def eliminar_otro_ingreso(ingreso_id: int):
    with cursor_db() as cur:
        cur.execute("DELETE FROM otros_ingresos WHERE id = ?", (ingreso_id,))


# ---------------------------------------------------------------------
# OTROS EGRESOS
# ---------------------------------------------------------------------

def registrar_otro_egreso(usuario_id: int, monto: float, descripcion: str, forma_pago: str = "efectivo"):
    """Registra un egreso extra (gasto no automatizado) del día."""
    forma_pago = (forma_pago or "efectivo").strip().lower()
    if forma_pago not in ("efectivo", "tarjeta"):
        forma_pago = "efectivo"

    ahora = datetime.datetime.now().isoformat(timespec="seconds")
    with cursor_db() as cur:
        cur.execute(
            "INSERT INTO otros_egresos (usuario_id, monto, descripcion, forma_pago, fecha) VALUES (?, ?, ?, ?, ?)",
            (usuario_id, monto, descripcion.strip(), forma_pago, ahora),
        )


def listar_otros_egresos_del_dia(fecha_iso: str = None):
    """Devuelve los egresos extra del día dado (o hoy)."""
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            """SELECT oe.id, oe.monto, oe.descripcion, oe.forma_pago, oe.fecha, u.nombre_completo AS usuario
               FROM otros_egresos oe
               JOIN usuarios u ON u.id = oe.usuario_id
               WHERE oe.fecha LIKE ?
               ORDER BY oe.fecha DESC""",
            (f"{fecha_iso}%",),
        )
        return cur.fetchall()


def total_otros_egresos_del_dia(fecha_iso: str = None) -> float:
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(monto), 0) AS total FROM otros_egresos WHERE fecha LIKE ?",
            (f"{fecha_iso}%",),
        )
        return cur.fetchone()["total"]


def eliminar_otro_egreso(egreso_id: int):
    with cursor_db() as cur:
        cur.execute("DELETE FROM otros_egresos WHERE id = ?", (egreso_id,))




def total_ventas_del_dia(fecha_iso: str = None) -> float:
    "Suma los subtotales de productos vendidos en ventas no anuladas."
    if fecha_iso is None:
        fecha_iso = datetime.date.today().isoformat()
    with cursor_db() as cur:
        cur.execute(
            '''SELECT COALESCE(SUM(dv.subtotal), 0) AS total
               FROM detalle_ventas dv
               JOIN ventas v ON v.id = dv.venta_id
               WHERE v.fecha LIKE ? AND v.anulada = 0''',
            (f"{fecha_iso}%",),
        )
        total_detalle = float(cur.fetchone()["total"] or 0)
        cur.execute(
            '''SELECT COALESCE(SUM(v.total), 0) AS total
               FROM ventas v
               WHERE v.fecha LIKE ? AND v.anulada = 0
                 AND NOT EXISTS (
                     SELECT 1 FROM detalle_ventas dv WHERE dv.venta_id = v.id
                 )''',
            (f"{fecha_iso}%",),
        )
        total_ventas_sin_detalle = float(cur.fetchone()["total"] or 0)
        return total_detalle + total_ventas_sin_detalle
