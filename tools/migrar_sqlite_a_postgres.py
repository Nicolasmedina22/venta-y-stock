"""
Migracion de datos del ejecutable de escritorio (SQLite) a una base
PostgreSQL de hosting (Neon, Render, etc.).

Uso (desde la raiz del proyecto):

    $env:DATABASE_URL = "postgresql://usuario:clave@host/neondb?sslmode=require"
    py tools/migrar_sqlite_a_postgres.py

Que hace:
  1. Crea el esquema en PostgreSQL (mismas tablas que inicializar_base_datos).
  2. Copia usuarios, categorias, productos, clientes, ventas, detalle_ventas,
     cierres_caja, otros ingresos, otros egresos y abonos de deuda.
  3. Verifica los conteos al final.

Importante:
  - La app usa el traductor SQL de database/db.py, asi que las sentencias se
    escriben igual que en SQLite y se traducen solas a PostgreSQL.
  - Si la base de destino ya tiene datos, se vacian las tablas antes de copiar
    (usa TRUNCATE ... CASCADE para respetar las claves foraneas).
  - La copia es de los datos; el usuario administrador lo crea la app al
    arrancar con ADMIN_USERNAME / ADMIN_PASSWORD.
"""

import os
import re
import sqlite3
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

# Tablas en orden: primero las que no dependen de otras.
TABLAS = [
    "usuarios",
    "categorias",
    "productos",
    "clientes",
    "ventas",
    "detalle_ventas",
    "cierres_caja",
    "otros_ingresos",
    "otros_egresos",
    "abonos_deuda",
    "equipos_autorizados",
    "block_notas",
]

# Columnas que existen en el esquema actual. Si el SQLite tiene columnas
# viejas que ya no existen en el destino, se descartan.
COLUMNAS = {
    "usuarios": ["id", "nombre_completo", "usuario", "password_hash", "rol", "activo", "fecha_creacion"],
    "categorias": ["id", "nombre"],
    "productos": ["id", "codigo_barras", "nombre", "categoria", "precio_venta", "costo",
                  "stock", "unidad", "activo"],
    "clientes": ["id", "nombre", "telefono", "direccion", "limite_credito", "saldo_deuda",
                 "fecha_registro"],
    "ventas": ["id", "usuario_id", "cliente_id", "fecha", "total", "forma_pago", "anulada"],
    "detalle_ventas": ["id", "venta_id", "producto_id", "nombre_producto", "cantidad",
                       "precio_unitario", "subtotal"],
    "cierres_caja": ["id", "usuario_id", "fecha", "total_efectivo", "total_fiado",
                     "total_tarjeta", "total_general", "cantidad_ventas", "detalle_json"],
    "otros_ingresos": ["id", "usuario_id", "monto", "descripcion", "forma_pago", "fecha"],
    "otros_egresos": ["id", "usuario_id", "monto", "descripcion", "forma_pago", "fecha"],
    "abonos_deuda": ["id", "cliente_id", "usuario_id", "monto", "fecha", "forma_pago"],
    "equipos_autorizados": ["id", "identificador", "nombre_equipo", "ip_local", "fecha_autorizacion"],
    "block_notas": ["pagina", "fecha", "contenido"],
}


def main():
    import psycopg
    from database import db

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Falta la variable de entorno DATABASE_URL")
    origen = os.environ.get("SQLITE_ORIGEN", os.path.join(RAIZ, "data", "pos_ferreteria.db"))
    if not os.path.exists(origen):
        raise SystemExit(f"No existe la base SQLite de origen: {origen}")

    print(f"Origen : {origen}")
    print(f"Destino: {url.split('@')[-1]}")

    src = sqlite3.connect(origen)
    src.row_factory = sqlite3.Row

    # 1. Esquema en el destino
    print("\n[1/3] Creando el esquema en PostgreSQL...")
    db.inicializar_base_datos(sembrar=False)

    destino = psycopg.connect(url)
    destino.autocommit = True
    with destino.cursor() as cur:
        cur.execute("SELECT current_database(), current_user")
        bd, usuario = cur.fetchone()
        print(f"  conectado a '{bd}' como '{usuario}'")

    # 2. Copia
    print("\n[2/3] Copiando datos...")
    total_filas = 0
    for tabla in TABLAS:
        cols = COLUMNAS[tabla]
        existe = src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
        ).fetchone()
        if not existe:
            print(f"  {tabla}: no existe en el origen, se omite")
            continue

        disponibles = {r["name"] for r in src.execute(f'PRAGMA table_info("{tabla}")')}
        cols = [c for c in cols if c in disponibles]
        if not cols:
            print(f"  {tabla}: sin columnas en comun, se omite")
            continue

        filas = [dict(r) for r in src.execute(f'SELECT {", ".join(cols)} FROM "{tabla}"')]
        if not filas:
            print(f"  {tabla}: 0 filas")
            continue

        destino.autocommit = False
        with destino.cursor() as cur:
            cur.execute(f'TRUNCATE TABLE "{tabla}" CASCADE')
            marcadores = ", ".join(["%s"] * len(cols))
            nombres = ", ".join(f'"{c}"' for c in cols)
            for f in filas:
                cur.execute(
                    f'INSERT INTO "{tabla}" ({nombres}) VALUES ({marcadores})',
                    [f[c] for c in cols],
                )
        destino.commit()
        destino.autocommit = True
        total_filas += len(filas)
        print(f"  {tabla}: {len(filas)} filas")

    # 2b. Resync de las secuencias de PostgreSQL.
    # Al copiar con el id explicito, la secuencia BIGSERIAL no avanza y el
    # siguiente INSERT sin id choca con una clave primaria ya usada.
    print("\n[2b] Sincronizando secuencias...")
    destino.autocommit = False
    with destino.cursor() as cur:
        for tabla in TABLAS:
            if tabla == "block_notas":
                continue  # su clave primaria es 'pagina', no tiene secuencia
            # Los nombres de tabla vienen de la lista fija TABLAS, no de
            # entrada del usuario.
            assert re.fullmatch(r"[a-z_]+", tabla), tabla
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM \"{tabla}\"), 1), true)"
            )
            valor = cur.fetchone()[0]
            print(f"  {tabla}: secuencia en {valor}")
    destino.commit()
    destino.autocommit = True

    # 3. Verificacion
    print("\n[3/3] Verificacion...")
    with destino.cursor() as cur:
        for tabla in TABLAS:
            cur.execute(f'SELECT COUNT(*) FROM "{tabla}"')
            destino_n = cur.fetchone()[0]
            existe = src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
            ).fetchone()
            origen_n = 0
            if existe:
                origen_n = src.execute(f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]
            marca = "OK " if destino_n == origen_n else "!! "
            print(f"  {marca}{tabla}: origen={origen_n} destino={destino_n}")

    destino.close()
    src.close()
    print(f"\nMigracion completa: {total_filas} filas copiadas.")


if __name__ == "__main__":
    main()
