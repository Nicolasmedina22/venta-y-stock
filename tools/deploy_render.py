"""
Despliegue automatizado de "Venta y Stock" en Render.com (plan gratuito).

Uso (desde la raiz del proyecto):

    $env:RENDER_API_KEY   = "rnd_..."      # Render > Account Settings > API Keys
    $env:GITHUB_TOKEN    = "ghp_..."      # opcional: si no, el repo ya esta subido
    $env:GITHUB_REPO     = "usuario/repo" # opcional: nombre del repo en GitHub
    $env:ADMIN_USERNAME  = "mi_usuario"
    $env:ADMIN_PASSWORD  = "mi_clave_larga"
    py tools/deploy_render.py

Que hace:
  1. Crea el PostgreSQL gratuito de Render.
  2. Crea el servicio web (Python) apuntando al repo de GitHub.
  3. Configura las variables de entorno (incluida DATABASE_URL).
  4. Espera el deploy y prueba /health en la URL publica.

El script es idempotente: si el Postgres o el servicio ya existen, los reutiliza.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
RUTA_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLANES = {"render": "free", "region": "oregon", "pg_version": "16"}


# ---------------------------------------------------------------- utilidades
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
        raise SystemExit(f"\n[ERROR] No se pudo conectar con Render: {e}\n")


def generar_secreto(n=48):
    import secrets
    return secrets.token_urlsafe(n)


def subir_a_github(repo, token):
    """Crea el repo en GitHub (si no existe) y sube el commit actual."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}

    def gh(metodo, ruta, cuerpo=None):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request("https://api.github.com" + ruta, data=datos, method=metodo)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                crudo = r.read().decode("utf-8")
                return json.loads(crudo) if crudo.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 422:
                return None  # ya existe
            raise SystemExit(f"[ERROR] GitHub {metodo} {ruta} -> {e.code}: {e.read().decode('utf-8','replace')}")

    datos = gh("GET", f"/repos/{repo}")
    if datos is None:
        usuario, nombre = repo.split("/")
        creado = gh("POST", "/user/repos", {"name": nombre, "private": True,
                                            "description": "Sistema de punto de venta e inventario"})
        if creado is None:
            raise SystemExit("[ERROR] No se pudo crear el repo en GitHub")
        print(f"  repo creado: {creado['html_url']}")
    else:
        print(f"  repo existente: {datos['html_url']}")

    remoto = f"https://{token}@github.com/{repo}.git"
    subprocess.run(["git", "remote", "remove", "origin"], cwd=RUTA_REPO, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remoto], cwd=RUTA_REPO, check=True)
    subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=RUTA_REPO, check=True)
    print(f"  codigo subido a {repo}")


# -------------------------------------------------------------------- pasos
def obtener_owner(token):
    owners = pedir("GET", "/owners", token=token)
    if not owners:
        raise SystemExit("[ERROR] La API de Render no devolvio ningun owner (cuenta?)")
    return owners[0]["id"]


def obtener_o_crear_postgres(token, owner_id):
    existentes = pedir("GET", "/postgres?limit=100", token=token)
    for p in existentes:
        if p["name"] == "venta-y-stock-db":
            print(f"  PostgreSQL ya existente: {p['name']} ({p['id']})")
            return p["id"]
    print("  creando PostgreSQL gratuito...")
    nuevo = pedir("POST", "/postgres", {
        "name": "venta-y-stock-db",
        "databaseName": "ventaystock",
        "databaseUser": "ventaystock",
        "ownerId": owner_id,
        "plan": PLANES["render"],
        "version": PLANES["pg_version"],
        "region": PLANES["region"],
    }, token=token)
    print(f"  PostgreSQL creado: {nuevo['name']} ({nuevo['id']})")
    if nuevo.get("expiresAt"):
        print(f"  ATENCION: la base gratuita caduca el {nuevo['expiresAt']}")
    return nuevo["id"]


def obtener_connection_string(token, pg_id):
    for intento in range(20):
        info = pedir("GET", f"/postgres/{pg_id}/connection-info", token=token)
        cadena = info.get("externalConnectionString")
        if cadena:
            return cadena
        print(f"  esperando connection-string ({intento + 1}/20)...")
        time.sleep(6)
    raise SystemExit("[ERROR] Render no devolvio el connection-string a tiempo")


def obtener_o_crear_servicio(token, owner_id, repo, vars_env):
    existentes = pedir("GET", "/services?limit=100", token=token)
    for s in existentes:
        if s["name"] == "venta-y-stock":
            print(f"  servicio ya existente: {s['name']} ({s['id']})")
            return s["id"], s
    print("  creando servicio web Python...")
    nuevo = pedir("POST", "/services", {
        "type": "web_service",
        "name": "venta-y-stock",
        "ownerId": owner_id,
        "repo": f"https://github.com/{repo}",
        "branch": "main",
        "autoDeploy": True,
        "autoDeployTrigger": "commit",
        "rootDir": "",
        "envVars": [{"key": k, "value": v} for k, v in vars_env.items()],
        "serviceDetails": {
            "runtime": "python",
            "env": "python",
            "plan": PLANES["render"],
            "numInstances": 1,
            "region": PLANES["region"],
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "python serve.py",
            },
        },
    }, token=token)
    print(f"  servicio creado: {nuevo['name']} ({nuevo['id']})")
    return nuevo["id"], nuevo


def fijar_env_vars(token, service_id, vars_env):
    actual = pedir("GET", f"/services/{service_id}/env-vars", token=token)
    claves = {e["envVar"]["key"] for e in actual}
    faltantes = [{"key": k, "value": v} for k, v in vars_env.items() if k not in claves]
    if not faltantes:
        print("  variables de entorno: ya estaban todas")
        return
    print(f"  configurando {len(faltantes)} variable(s) de entorno...")
    for e in faltantes:
        pedir("PUT", f"/services/{service_id}/env-vars/{e['key']}",
              {"key": e["key"], "value": e["value"]}, token=token)


def esperar_deploy(token, service_id, minutos=12):
    limite = time.time() + minutos * 60
    while time.time() < limite:
        deploys = pedir("GET", f"/services/{service_id}/deploys?limit=1", token=token)
        if deploys:
            d = deploys[0]
            estado = d.get("status")
            print(f"  deploy {d.get('id','')[:8]}... estado: {estado}")
            if estado == "live":
                return d
            if estado in ("build_failed", "update_failed", "canceled", "pre_deploy_failed"):
                raise SystemExit(f"[ERROR] El deploy fallo: {estado}")
        time.sleep(12)
    raise SystemExit("[ERROR] Se agoto el tiempo de espera del deploy")


def probar_url(url):
    import urllib.request as u
    for _ in range(10):
        try:
            with u.urlopen(url.rstrip("/") + "/health", timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(6)
    return None


# ------------------------------------------------------------------- main
def main():
    token = os.environ.get("RENDER_API_KEY", "").strip()
    if not token:
        raise SystemExit("Falta la variable de entorno RENDER_API_KEY")

    admin_user = os.environ.get("ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not admin_user or not admin_pass:
        admin_user = admin_user or "admin_ferreteria"
        admin_pass = admin_pass or generar_secreto(12)
        print(f"  credenciales generadas -> usuario: {admin_user} / clave: {admin_pass}")
        print("  GUARDALAS: son las unicas con las que se entra al sistema.")

    print("\n[1/6] Verificando la API de Render...")
    pedir("GET", "/services?limit=1", token=token)
    owner_id = obtener_owner(token)
    print(f"  owner: {owner_id}")

    repo = os.environ.get("GITHUB_REPO", "").strip()
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if repo and github_token:
        print("\n[2/6] Publicando el codigo en GitHub...")
        subir_a_github(repo, github_token)
    else:
        print("\n[2/6] GitHub: se usa el repo ya publicado"
              + (f" ({repo})" if repo else " (indica GITHUB_REPO para crearlo)"))

    print("\n[3/6] Preparando PostgreSQL...")
    pg_id = obtener_o_crear_postgres(token, owner_id)
    connection_string = obtener_connection_string(token, pg_id)
    print(f"  connection-string listo")

    print("\n[4/6] Creando el servicio web...")
    vars_env = {
        "HOSTED_MODE": "1",
        "FLASK_SECRET_KEY": os.environ.get("FLASK_SECRET_KEY", "").strip() or generar_secreto(),
        "ADMIN_USERNAME": admin_user,
        "ADMIN_PASSWORD": admin_pass,
        "SESSION_COOKIE_SECURE": "1",
        "DATABASE_URL": connection_string,
    }
    service_id, servicio = obtener_o_crear_servicio(token, owner_id, repo or "USUARIO/REPO", vars_env)

    print("\n[5/6] Configurando variables de entorno...")
    fijar_env_vars(token, service_id, vars_env)

    print("\n[6/6] Esperando el deploy...")
    deploy = esperar_deploy(token, service_id)
    servicio = pedir("GET", f"/services/{service_id}", token=token)
    url = (servicio.get("serviceDetails") or {}).get("url") or ""
    print(f"\n  URL publica: {url}")
    print(f"  deploy: {deploy.get('status')}")

    print("\n  probando /health...")
    salud = probar_url(url)
    if salud:
        print(f"  /health -> {salud}")
    else:
        print("  /health no respondio a tiempo. Revisa los logs en el panel de Render.")

    print("\n" + "=" * 62)
    print(f"  URL:      {url}")
    print(f"  Usuario:  {admin_user}")
    print(f"  Clave:    {admin_pass}")
    print("=" * 62)


if __name__ == "__main__":
    main()
