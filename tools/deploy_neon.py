"""
Provisiona la base de datos PostgreSQL en Neon (plan gratuito) para
"Venta y Stock" y devuelve la variable DATABASE_URL.

Uso (desde la raiz del proyecto):

    $env:NEON_API_KEY   = "..."      # Neon Console > Account Settings > API Keys
    $env:NEON_PROJECT  = "venta-y-stock"   # opcional, nombre por defecto
    $env:NEON_REGION   = "aws-us-east-2"  # opcional
    py tools/deploy_neon.py

Que hace:
  1. Crea (o reutiliza) el proyecto PostgreSQL en Neon.
  2. Crea una rama "main" si hace falta.
  3. Obtiene la cadena de conexion POOLED (con PgBouncer) de la rama main.
  4. Opcionalmente verifica la conexion con psycopg.

Notas:
  - El plan gratuito de Neon NO caduca (a diferencia del Postgres gratis de
    Render, que caduca a los 30 dias).
  - Se usa la cadena "pooled" porque la app abre y cierra una conexion en
    cada operacion; el pooler evita agotar las conexiones del compute.
  - La rama "main" es la que se expone al hosting. Las ramas de prueba sirven
    para experimenting sin tocar los datos reales.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://console.neon.tech/api/v2"

PROYECTO_POR_DEFECTO = "venta-y-stock"
REGION_POR_DEFECTO = "aws-us-east-2"
RAMA = "main"
BASE_DATOS = "neondb"


def pedir(metodo, ruta, cuerpo=None, token=None):
    url = API + ruta
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            crudo = r.read().decode("utf-8")
            return json.loads(crudo) if crudo.strip() else {}
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")
        raise SystemExit(f"\n[ERROR] {metodo} {ruta} -> HTTP {e.code}\n{detalle}\n")
    except urllib.error.URLError as e:
        raise SystemExit(f"\n[ERROR] No se pudo conectar con Neon: {e}\n")


def buscar_organizacion(token):
    """Si la API key es personal, hace falta indicar la organizacion."""
    try:
        orgs = pedir("GET", "/users/me/organizations", token=token)
        if orgs:
            return orgs[0]["id"]
    except SystemExit:
        pass
    return None


def obtener_o_crear_proyecto(token, nombre, region, org_id):
    proyectos = pedir("GET", "/projects?limit=100", token=token)
    for p in proyectos.get("projects", []):
        if p.get("name") == nombre:
            print(f"  proyecto existente: {p['name']} ({p['id']})")
            return p
    print(f"  creando proyecto '{nombre}' en {region}...")
    cuerpo = {"project": {"name": nombre, "region_id": region, "pg_version": 16}}
    if org_id:
        cuerpo["project"]["org_id"] = org_id
    nuevo = pedir("POST", "/projects", cuerpo, token=token)
    print(f"  proyecto creado: {nuevo['name']} ({nuevo['id']})")
    return nuevo


def obtener_o_crear_rama(token, project_id):
    ramas = pedir("GET", f"/projects/{project_id}/branches?limit=100", token=token)
    for b in ramas.get("branches", []):
        if b.get("name") == RAMA:
            print(f"  rama existente: {b['name']} ({b['id']})")
            return b
    print(f"  creando rama '{RAMA}'...")
    nueva = pedir("POST", f"/projects/{project_id}/branches",
                  {"branch": {"name": RAMA}}, token=token)
    print(f"  rama creada: {nueva['name']} ({nueva['id']})")
    return nueva


def obtener_connection_uri(token, project_id, rama_id):
    params = urllib.parse.urlencode({
        "database_name": BASE_DATOS,
        "role_name": "neondb_owner",
        "branch_id": rama_id,
        "pooled": "true",
    })
    datos = pedir("GET", f"/projects/{project_id}/connection_uri?{params}", token=token)
    uri = datos.get("uri")
    if not uri:
        raise SystemExit("[ERROR] Neon no devolvio la connection string")
    return uri


def probar_conexion(uri):
    try:
        import psycopg
    except ImportError:
        print("  (psycopg no esta instalado, se omite la prueba)")
        return None
    try:
        with psycopg.connect(uri, connect_timeout=25) as con:
            with con.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
                print(f"  conexion OK -> {version.split(',')[0]}")
        return True
    except Exception as e:
        print(f"  ATENCION: no se pudo conectar: {e}")
        return False


def main():
    token = os.environ.get("NEON_API_KEY", "").strip()
    if not token:
        raise SystemExit("Falta la variable de entorno NEON_API_KEY")

    nombre = os.environ.get("NEON_PROJECT", PROYECTO_POR_DEFECTO).strip()
    region = os.environ.get("NEON_REGION", REGION_POR_DEFECTO).strip()

    print("[1/5] Verificando la API de Neon...")
    pedir("GET", "/projects?limit=1", token=token)
    print("  API accesible")

    print("\n[2/5] Organizacion y proyecto...")
    org_id = buscar_organizacion(token)
    if org_id:
        print(f"  organizacion: {org_id}")
    proyecto = obtener_o_crear_proyecto(token, nombre, region, org_id)
    project_id = proyecto["id"]

    print("\n[3/5] Rama...")
    rama = obtener_o_crear_rama(token, project_id)
    rama_id = rama["id"]

    print("\n[4/5] Connection string (pooled)...")
    uri = obtener_connection_uri(token, project_id, rama_id)
    print(f"  {uri.split('@')[-1]}")

    print("\n[5/5] Probando la conexion...")
    probar_conexion(uri)

    print("\n" + "=" * 66)
    print("  DATABASE_URL para el hosting:")
    print(f"  {uri}")
    print()
    print("  Usalo asi:")
    print("    $env:DATABASE_URL = '<la cadena de arriba>'")
    print("    py tools/deploy_render.py")
    print("=" * 66)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "neon_database_url.txt"),
              "w", encoding="utf-8") as f:
        f.write(uri + "\n")
    print("\n  (tambien guardada en neon_database_url.txt, no se sube al repo)")


if __name__ == "__main__":
    main()
