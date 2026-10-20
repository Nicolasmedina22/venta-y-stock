"""
Aplicación Web Flask para Venta y Stock.

Punto de entrada web:
    python app.py

Aplicación web para ventas e inventario con Flask y SQLite.
"""

import os
import ast
import math
import re
import datetime
import sys
import threading
import webbrowser
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, flash, send_file
)
import io

from config import NOMBRE_APP, VERSION_APP, MONEDA, DB_PATH, HOSTED_MODE, FLASK_SECRET_KEY
from database import db
from utils.equipo import (
    obtener_identificador_equipo, obtener_ip_local, obtener_nombre_equipo,
)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY or "pos-ferreteria-pro-secret-key-2026"

# Las cookies de sesion viajan como "Secure" (solo por HTTPS) cuando la app
# esta en modo hosting. En un entorno local de pruebas que se sirve por HTTP
# plano hay que poner SESSION_COOKIE_SECURE=0, porque el navegador no
# devuelve las cookies seguras fuera de HTTPS.
SESSION_COOKIE_SECURE = (
    HOSTED_MODE
    and os.environ.get("SESSION_COOKIE_SECURE", "1").strip().lower() not in {"0", "false", "no"}
)

app.config.update(
    HOSTED_MODE=HOSTED_MODE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
)

# Asegurar que la base de datos esté inicializada
db.inicializar_base_datos()


# ---------------------------------------------------------------------
# TABLA PARA BLOCK DE NOTAS (Persistencia de las 365 páginas)
# ---------------------------------------------------------------------
def _inicializar_tabla_notas():
    with db.cursor_db() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS block_notas (
                pagina INTEGER PRIMARY KEY,
                fecha TEXT NOT NULL,
                contenido TEXT NOT NULL DEFAULT ''
            )
        """)

_inicializar_tabla_notas()


# ---------------------------------------------------------------------
# CONSTRUCCIÓN DE TICKET DE TEXTO (idéntico a ui/venta_view.py)
# ---------------------------------------------------------------------
def construir_ticket_texto(venta_id: int, total: float, forma_pago: str, items: list) -> str:
    etiqueta_forma_pago = "Transferencia" if forma_pago == "tarjeta" else forma_pago.capitalize()
    lineas = [
        "================================",
        "        Ticket de Venta        ",
        "================================",
        f"Venta #{venta_id}",
        f"Pago: {etiqueta_forma_pago}",
        "--------------------------------",
    ]

    for item in items:
        nombre = str(item.get("nombre", ""))[:24]
        cantidad = int(item.get("cantidad", 1))
        precio = float(item.get("precio_unitario", 0))
        subtotal = float(item.get("subtotal", precio * cantidad))
        lineas.append(f"{nombre:<24} {cantidad:>2} x {MONEDA}{precio:,.2f}")
        lineas.append(f"{MONEDA}{subtotal:,.2f}")

    lineas.extend([
        "--------------------------------",
        "TOTAL",
        f"{MONEDA}{float(total):,.2f}",
        "================================",
    ])
    return "\n".join(lineas)


# ---------------------------------------------------------------------
# EVALUADOR DE CALCULADORA (idéntico a ui/main_window.py)
# ---------------------------------------------------------------------
def normalizar_porcentaje(expresion: str) -> str:
    texto = expresion.strip()
    if not texto:
        return texto
    patrones = [
        (r"(?P<izq>\d+(?:\.\d+)?)\s*(?P<op>[+\-])\s*(?P<valor>\d+(?:\.\d+)?)%",
         lambda m: f"{m.group('izq')} {m.group('op')} ({m.group('izq')}*{m.group('valor')}/100)"),
        (r"(?P<izq>\d+(?:\.\d+)?)\s*(?P<op>[*/])\s*(?P<valor>\d+(?:\.\d+)?)%",
         lambda m: f"{m.group('izq')} {m.group('op')} ({m.group('valor')}/100)"),
    ]
    for patron, reemplazo in patrones:
        texto = re.sub(patron, reemplazo, texto)
    texto = re.sub(r"(?<![A-Za-z0-9_])(?P<valor>\d+(?:\.\d+)?)%", r"(\g<valor>/100)", texto)
    return texto


def resolver_expresion(expresion: str) -> float:
    texto = expresion.strip().replace("x", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    if not texto:
        raise ValueError("Ingresa una operación válida.")

    texto = normalizar_porcentaje(texto)
    if not texto:
        raise ValueError("Ingresa una operación válida.")

    nombres_permitidos = {
        "pi": math.pi, "e": math.e, "sqrt": math.sqrt, "sin": math.sin,
        "cos": math.cos, "tan": math.tan, "log": math.log, "exp": math.exp,
        "abs": abs, "round": round, "pow": pow, "min": min, "max": max,
    }

    def evaluar_nodo(node):
        if isinstance(node, ast.Expression):
            return evaluar_nodo(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            izq = evaluar_nodo(node.left)
            der = evaluar_nodo(node.right)
            if isinstance(node.op, ast.Add): return izq + der
            if isinstance(node.op, ast.Sub): return izq - der
            if isinstance(node.op, ast.Mult): return izq * der
            if isinstance(node.op, ast.Div): return izq / der
            if isinstance(node.op, ast.FloorDiv): return izq // der
            if isinstance(node.op, ast.Mod): return izq % der
            if isinstance(node.op, ast.Pow): return izq ** der
            raise ValueError("Operación no soportada.")
        if isinstance(node, ast.UnaryOp):
            valor = evaluar_nodo(node.operand)
            if isinstance(node.op, ast.UAdd): return +valor
            if isinstance(node.op, ast.USub): return -valor
            raise ValueError("Operación unaria no soportada.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Solo se permiten funciones simples.")
            nombre = node.func.id
            if nombre not in nombres_permitidos:
                raise ValueError(f"Función no permitida: {nombre}")
            args = [evaluar_nodo(arg) for arg in node.args]
            kwargs = {kw.arg: evaluar_nodo(kw.value) for kw in node.keywords}
            return nombres_permitidos[nombre](*args, **kwargs)
        if isinstance(node, ast.Name):
            if node.id in nombres_permitidos:
                return nombres_permitidos[node.id]
            raise ValueError(f"Nombre no permitido: {node.id}")
        raise ValueError("Expresión no válida.")

    arbol = ast.parse(texto, mode="eval")
    resultado = evaluar_nodo(arbol)
    if isinstance(resultado, float) and math.isfinite(resultado):
        return resultado
    raise ValueError("La operación no devolvió un valor válido.")


# ---------------------------------------------------------------------
# DECORADORES DE SEGURIDAD Y PERMISOS
# ---------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        if session.get("usuario_rol") != "admin":
            flash("Acceso denegado: solo administradores pueden acceder a esta sección.", "error")
            return redirect(url_for("venta"))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_global_vars():
    usuario_actual = None
    if "usuario_id" in session:
        usuario_actual = {
            "id": session.get("usuario_id"),
            "nombre_completo": session.get("usuario_nombre"),
            "usuario": session.get("usuario_login"),
            "rol": session.get("usuario_rol"),
        }
    return {
        "NOMBRE_APP": NOMBRE_APP,
        "VERSION_APP": VERSION_APP,
        "MONEDA": MONEDA,
        "usuario_actual": usuario_actual,
        "hoy_str": datetime.date.today().strftime("%d/%m/%Y"),
        "hoy_str_iso": datetime.date.today().isoformat(),
    }


# ---------------------------------------------------------------------
# RUTAS DE AUTENTICACIÓN
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    # Identificador único de ESTA PC. Sirve para no volver a pedir
    # credenciales en el mismo equipo y exigirlas en uno nuevo.
    id_equipo = obtener_identificador_equipo()

    # Si este equipo ya fue autorizado alguna vez, se omite el login
    # por completo (salvo que la sesión se haya cerrado con /logout,
    # en cuyo caso se vuelve a pedir usuario y contraseña).
    if not app.config["HOSTED_MODE"] and "usuario_id" not in session and db.equipo_esta_autorizado(id_equipo):
        usuario_admin = _usuario_admin_por_defecto()
        if usuario_admin is not None:
            _iniciar_sesion(usuario_admin)
            return redirect(url_for("venta"))

    # Ya hay sesión activa: ir directo a la venta.
    if "usuario_id" in session:
        return redirect(url_for("venta"))

    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")

        if not usuario or not password:
            error = "Ingresa usuario y contraseña."
        else:
            fila_usuario = db.autenticar_usuario(usuario, password)
            if fila_usuario is None:
                error = "Usuario o contraseña incorrectos."
            else:
                # Credenciales correctas: autorizamos este equipo de
                # forma permanente. Desde ahora esta PC no pedirá más
                # el login. Otra PC distinta sí lo pedirá.
                if not app.config["HOSTED_MODE"]:
                    db.autorizar_equipo(id_equipo, obtener_nombre_equipo(), obtener_ip_local())
                _iniciar_sesion(fila_usuario)
                return redirect(url_for("venta"))

    return render_template("login.html", error=error)


def _iniciar_sesion(fila_usuario):
    """Guarda en la sesión Flask los datos del usuario autenticado."""
    session["usuario_id"] = fila_usuario["id"]
    session["usuario_nombre"] = fila_usuario["nombre_completo"]
    session["usuario_login"] = fila_usuario["usuario"]
    session["usuario_rol"] = fila_usuario["rol"]


def _usuario_admin_por_defecto():
    """
    Devuelve un usuario administrador activo para la sesión automática
    en un equipo ya autorizado. Si no hay ninguno, devuelve None.
    """
    usuarios = db.listar_usuarios()
    for u in usuarios:
        if u["rol"] == "admin" and u["activo"]:
            return u
    return None


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("venta"))


@app.route("/health")
def health():
    """
    Sonda de salud para el hosting (Render, Railway, etc.).

    No pide credenciales ni toca datos de negocio: solo confirma que el
    proceso de Python esta vivo y responde. El proveedor la usa para
    decidir si la instancia esta lista.
    """
    return jsonify({
        "ok": True,
        "app": NOMBRE_APP,
        "version": VERSION_APP,
        "hosted_mode": bool(HOSTED_MODE),
    })


# ---------------------------------------------------------------------
# 1. PUNTO DE VENTA (🛒 Venta)
# ---------------------------------------------------------------------
@app.route("/venta")
@login_required
def venta():
    clientes = [dict(c) for c in db.listar_clientes()]
    productos_recientes = [dict(p) for p in db.buscar_productos_por_nombre("", limite=40)]
    return render_template(
        "venta.html",
        clientes=clientes,
        productos_iniciales=productos_recientes,
        pagina_activa="venta"
    )


# ---------------------------------------------------------------------
# 2. PRODUCTOS E INVENTARIO (📦 Productos)
# ---------------------------------------------------------------------
@app.route("/productos")
@login_required
def productos():
    categoria_filtro = request.args.get("categoria", "Todas")
    busqueda = request.args.get("q", "").strip()

    todas_categorias = db.listar_categorias()
    kpis = dict(db.obtener_estadisticas_inventario())

    productos_lista = [dict(p) for p in db.listar_todos_productos()]

    # Filtrar según búsqueda y categoría priorizando los que comienzan con las letras escritas
    if busqueda:
        busq_lower = busqueda.lower()
        productos_filtrados = [
            p for p in productos_lista
            if busq_lower in p["nombre"].lower() or busq_lower in (p["codigo_barras"] or "").lower()
        ]

        def _prioridad_busqueda(p):
            nom = (p.get("nombre") or "").lower()
            cod = (p.get("codigo_barras") or "").lower()
            # 1: Comienza exactamente con las letras buscadas en el nombre
            if nom.startswith(busq_lower):
                return (1, nom)
            # 2: Alguna palabra del nombre comienza con esas letras (ej: "Phillips" en "Destornillador Phillips")
            palabras = nom.split()
            if any(pal.startswith(busq_lower) for pal in palabras):
                return (2, nom)
            # 3: El código de barras comienza con las letras/números
            if cod.startswith(busq_lower):
                return (3, nom)
            # 4: Contiene las letras en cualquier parte del nombre
            if busq_lower in nom:
                return (4, nom)
            # 5: Cualquier otra coincidencia
            return (5, nom)

        productos_lista = sorted(productos_filtrados, key=_prioridad_busqueda)

    if categoria_filtro and categoria_filtro != "Todas":
        productos_lista = [
            p for p in productos_lista
            if (p["categoria"] or "").lower() == categoria_filtro.lower()
        ]

    return render_template(
        "productos.html",
        productos=productos_lista,
        categorias=todas_categorias,
        categoria_seleccionada=categoria_filtro,
        busqueda_actual=busqueda,
        kpis=kpis,
        pagina_activa="productos"
    )


# ---------------------------------------------------------------------
# 3. CLIENTES Y FIADO (👥 Clientes / Fiado)
# ---------------------------------------------------------------------
@app.route("/clientes")
@login_required
def clientes():
    busqueda = request.args.get("q", "").strip()
    clientes_lista = [dict(c) for c in db.buscar_clientes(busqueda)]
    return render_template(
        "clientes.html",
        clientes=clientes_lista,
        busqueda_actual=busqueda,
        pagina_activa="clientes"
    )


# ---------------------------------------------------------------------
# 4. CIERRE DE CAJA (🧾 Cierre de caja)
# ---------------------------------------------------------------------
@app.route("/caja")
@login_required
def caja():
    resumen = dict(db.resumen_caja_del_dia())
    return render_template(
        "caja.html",
        resumen=resumen,
        pagina_activa="caja"
    )


# ---------------------------------------------------------------------
# 5. OTROS INGRESOS Y EGRESOS (⬆️ Otros Ingresos / Egresos)
# ---------------------------------------------------------------------
@app.route("/ingresos_egresos")
@login_required
def ingresos_egresos():
    ingresos = [dict(i) for i in db.listar_otros_ingresos_del_dia()]
    egresos = [dict(e) for e in db.listar_otros_egresos_del_dia()]
    total_ing = db.total_otros_ingresos_del_dia()
    total_egr = db.total_otros_egresos_del_dia()

    return render_template(
        "ingresos_egresos.html",
        ingresos=ingresos,
        egresos=egresos,
        total_ingresos=total_ing,
        total_egresos=total_egr,
        pagina_activa="ingresos_egresos"
    )


# ---------------------------------------------------------------------
# 6. HISTORIAL DE CAJA (📅 Historial de caja - Solo Admin)
# ---------------------------------------------------------------------
@app.route("/historial_caja", endpoint="historial_caja")
@app.route("/reportes", endpoint="reportes")
@admin_required
def historial_caja():
    fecha_req = request.args.get("fecha", "").strip()
    hoy = datetime.date.today()
    hoy_iso = hoy.isoformat()

    if not fecha_req:
        fecha_req = hoy_iso

    try:
        fecha_obj = datetime.date.fromisoformat(fecha_req)
        fecha_iso = fecha_obj.isoformat()
    except ValueError:
        fecha_obj = hoy
        fecha_iso = hoy_iso

    fecha_anterior = (fecha_obj - datetime.timedelta(days=1)).isoformat()
    fecha_siguiente = (fecha_obj + datetime.timedelta(days=1)).isoformat()

    dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses_es = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    dia_nom = dias_es[fecha_obj.weekday()]
    mes_nom = meses_es[fecha_obj.month - 1]
    fecha_larga = f"{dia_nom}, {fecha_obj.day} de {mes_nom} de {fecha_obj.year}"
    fecha_corta = fecha_obj.strftime("%d/%m/%Y")

    resumen = dict(db.resumen_caja_por_fecha(fecha_iso))

    return render_template(
        "historial_caja.html",
        resumen=resumen,
        fecha_seleccionada=fecha_iso,
        fecha_larga=fecha_larga,
        fecha_corta=fecha_corta,
        fecha_anterior=fecha_anterior,
        fecha_siguiente=fecha_siguiente,
        hoy_iso=hoy_iso,
        hoy_str_iso=hoy_iso,
        pagina_activa="historial_caja"
    )

@app.route("/ventas_dia")
@admin_required
def ventas_dia():
    fecha_req = request.args.get("fecha", "").strip()
    try:
        fecha_obj = datetime.date.fromisoformat(fecha_req) if fecha_req else datetime.date.today()
    except ValueError:
        fecha_obj = datetime.date.today()
    fecha_iso = fecha_obj.isoformat()
    productos_vendidos = [dict(producto) for producto in db.productos_vendidos_del_dia(fecha_iso)]
    # Usar exactamente los mismos subtotales que se envían a la plantilla.
    total_productos_vendidos = sum(
        float(producto["subtotal"] or 0) for producto in productos_vendidos
    )
    cantidad_ventas = len({producto.get("venta_id") for producto in productos_vendidos})
    return render_template(
        "ventas_dia.html",
        productos_vendidos=productos_vendidos,
        total_productos_vendidos=total_productos_vendidos,
        cantidad_ventas=cantidad_ventas,
        fecha_seleccionada=fecha_iso,
        fecha_corta=fecha_obj.strftime("%d/%m/%Y"),
        hoy_str_iso=datetime.date.today().isoformat(),
        pagina_activa="ventas_dia",
    )

# =====================================================================
# ENDPOINTS API (AJAX PARA EXPERIENCIA DINÁMICA FLUIDA)
# =====================================================================

# --- Búsqueda de productos ---
@app.route("/api/productos/buscar")
@login_required
def api_buscar_productos():
    q = request.args.get("q", "").strip()
    productos = [dict(p) for p in db.buscar_productos_por_nombre(q, limite=40)]
    return jsonify(productos)


@app.route("/api/productos/codigo/<codigo>")
@login_required
def api_buscar_codigo(codigo):
    p = db.buscar_producto_por_codigo(codigo.strip())
    if p:
        return jsonify({"encontrado": True, "producto": dict(p)})
    return jsonify({"encontrado": False})


# --- Confirmación de venta ---
@app.route("/api/ventas/confirmar", methods=["POST"])
@login_required
def api_confirmar_venta():
    data = request.get_json(silent=True) or {}
    carrito = data.get("carrito", [])
    forma_pago = data.get("forma_pago", "efectivo")
    cliente_id = data.get("cliente_id")

    if not carrito:
        return jsonify({"ok": False, "mensaje": "El carrito está vacío."}), 400

    if forma_pago == "fiado":
        if not cliente_id:
            return jsonify({"ok": False, "mensaje": "Debes seleccionar un cliente para cuenta fiada."}), 400
        cliente = db.obtener_cliente(int(cliente_id))
        if not cliente:
            return jsonify({"ok": False, "mensaje": "El cliente seleccionado no existe."}), 400

    try:
        # Validar y convertir cliente_id
        c_id = int(cliente_id) if (cliente_id and forma_pago == "fiado") else None
        usuario_id = session.get("usuario_id")

        venta_id = db.registrar_venta(
            usuario_id=usuario_id,
            cliente_id=c_id,
            carrito=carrito,
            forma_pago=forma_pago,
        )

        total = sum(item["subtotal"] for item in carrito)
        ticket_texto = construir_ticket_texto(venta_id, total, forma_pago, carrito)

        return jsonify({
            "ok": True,
            "venta_id": venta_id,
            "total": total,
            "ticket": ticket_texto,
            "mensaje": f"Venta #{venta_id} confirmada con éxito.",
        })
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 500


# --- Gestión de Productos (CRUD y Stock) ---
@app.route("/api/productos/crear", methods=["POST"])
@login_required
def api_crear_producto():
    data = request.form if request.form else (request.get_json(silent=True) or {})
    try:
        codigo = str(data.get("codigo_barras", "")).strip()
        nombre = str(data.get("nombre", "")).strip()
        categoria = str(data.get("categoria", "")).strip() or "General"
        costo = float(data.get("costo", 0) or 0)
        precio_venta = float(data.get("precio_venta", 0) or 0)
        stock = int(data.get("stock", 0) or 0)
        unidad = str(data.get("unidad", "unidad")).strip()

        if not codigo or not nombre:
            return jsonify({"ok": False, "mensaje": "Código y nombre son obligatorios."}), 400

        producto_id = db.crear_producto(
            codigo_barras=codigo,
            nombre=nombre,
            categoria=categoria,
            precio_venta=precio_venta,
            costo=costo,
            stock=stock,
            unidad=unidad,
        )
        return jsonify({"ok": True, "producto_id": producto_id, "mensaje": "Producto guardado con éxito."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/productos/editar/<int:prod_id>", methods=["POST"])
@login_required
def api_editar_producto(prod_id):
    data = request.form if request.form else (request.get_json(silent=True) or {})
    try:
        codigo = str(data.get("codigo_barras", "")).strip()
        nombre = str(data.get("nombre", "")).strip()
        categoria = str(data.get("categoria", "")).strip() or "General"
        costo = float(data.get("costo", 0) or 0)
        precio_venta = float(data.get("precio_venta", 0) or 0)
        stock = int(data.get("stock", 0) or 0)
        unidad = str(data.get("unidad", "unidad")).strip()

        if not codigo or not nombre:
            return jsonify({"ok": False, "mensaje": "Código y nombre son obligatorios."}), 400

        db.actualizar_producto(
            producto_id=prod_id,
            codigo_barras=codigo,
            nombre=nombre,
            categoria=categoria,
            precio_venta=precio_venta,
            costo=costo,
            stock=stock,
            unidad=unidad,
        )
        return jsonify({"ok": True, "mensaje": "Producto actualizado correctamente."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/productos/ajustar_stock/<int:prod_id>", methods=["POST"])
@login_required
def api_ajustar_stock(prod_id):
    data = request.get_json(silent=True) or request.form
    try:
        nuevo_stock = int(data.get("stock", 0))
        db.ajustar_stock_producto(prod_id, nuevo_stock)
        return jsonify({"ok": True, "mensaje": f"Stock actualizado a {nuevo_stock}."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/productos/sumar_stock/<int:prod_id>", methods=["POST"])
@login_required
def api_sumar_stock(prod_id):
    data = request.get_json(silent=True) or request.form
    try:
        cantidad = int(data.get("cantidad", 0))
        if cantidad <= 0:
            return jsonify({"ok": False, "mensaje": "La cantidad debe ser mayor a 0."}), 400
        db.sumar_stock_producto(prod_id, cantidad)
        return jsonify({"ok": True, "mensaje": f"Se sumaron {cantidad} unidades al stock."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/productos/cambiar_estado/<int:prod_id>", methods=["POST"])
@login_required
def api_cambiar_estado_producto(prod_id):
    data = request.get_json(silent=True) or request.form
    try:
        activo = int(data.get("activo", 1))
        db.cambiar_estado_producto(prod_id, activo)
        estado_str = "activado" if activo else "desactivado"
        return jsonify({"ok": True, "mensaje": f"Producto {estado_str}."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/productos/eliminar/<int:prod_id>", methods=["POST"])
@login_required
def api_eliminar_producto(prod_id):
    try:
        db.eliminar_producto(prod_id)
        return jsonify({"ok": True, "mensaje": "Producto eliminado del inventario."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


# --- Importación de productos desde Excel ---
@app.route("/api/productos/importar_excel", methods=["POST"])
@login_required
def api_importar_productos_excel():
    if "archivo" not in request.files:
        return jsonify({"ok": False, "mensaje": "No se seleccionó ningún archivo."}), 400

    archivo = request.files["archivo"]
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "mensaje": "El archivo seleccionado no es válido."}), 400

    modo_stock = request.form.get("modo_stock", "sumar").strip().lower()
    if modo_stock not in ("sumar", "reemplazar"):
        modo_stock = "sumar"

    try:
        import openpyxl
        wb = openpyxl.load_workbook(archivo, data_only=True)
    except Exception as e:
        return jsonify({"ok": False, "mensaje": f"No se pudo leer el archivo Excel (.xlsx): {e}"}), 400

    hoja = wb.active
    filas = list(hoja.iter_rows(values_only=True))
    if not filas:
        return jsonify({"ok": False, "mensaje": "El archivo Excel está completamente vacío."}), 400

    # Normalizar texto para mapeo de encabezados
    def _norm(s):
        if s is None:
            return ""
        s = str(s).strip().lower()
        reemplazos = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"))
        for a, b in reemplazos:
            s = s.replace(a, b)
        return re.sub(r"[^a-z0-9]", "", s)

    mapa = {}
    indice_fila_encabezado = 0
    encontrado = False

    for idx, f in enumerate(filas[:10]):
        textos = [_norm(c) for c in f if c is not None]
        tiene_nombre = any(any(k in c for k in ("nombre", "producto", "descripcion", "articulo")) for c in textos)
        if tiene_nombre:
            indice_fila_encabezado = idx
            encontrado = True
            for col_idx, valor in enumerate(f):
                col_norm = _norm(valor)
                if not col_norm:
                    continue
                if any(k in col_norm for k in ("codigo", "barcode", "cod", "barras", "ean", "sku")) and "codigo" not in mapa:
                    mapa["codigo"] = col_idx
                elif any(k in col_norm for k in ("nombre", "producto", "descripcion", "articulo")) and "nombre" not in mapa:
                    mapa["nombre"] = col_idx
                elif any(k in col_norm for k in ("categoria", "rubro", "grupo", "seccion")) and "categoria" not in mapa:
                    mapa["categoria"] = col_idx
                elif any(k in col_norm for k in ("precio", "venta", "pvp")) and "precio" not in mapa:
                    mapa["precio"] = col_idx
                elif any(k in col_norm for k in ("costo", "compra")) and "costo" not in mapa:
                    mapa["costo"] = col_idx
                elif any(k in col_norm for k in ("stock", "cantidad", "cant", "unidades", "existencia")) and "stock" not in mapa:
                    mapa["stock"] = col_idx
                elif any(k in col_norm for k in ("unidad", "medida", "ud")) and "unidad" not in mapa:
                    mapa["unidad"] = col_idx
            break

    # Si no se detectaron encabezados con nombre, usar columnas por defecto:
    # 0: Código, 1: Nombre, 2: Categoría, 3: Costo, 4: Precio, 5: Stock, 6: Unidad
    if not encontrado:
        mapa = {
            "codigo": 0,
            "nombre": 1,
            "categoria": 2,
            "costo": 3,
            "precio": 4,
            "stock": 5,
            "unidad": 6,
        }
        filas_datos = filas
    else:
        filas_datos = filas[indice_fila_encabezado + 1 :]

    col_cod = mapa.get("codigo")
    col_nom = mapa.get("nombre")
    col_cat = mapa.get("categoria")
    col_cost = mapa.get("costo")
    col_prec = mapa.get("precio")
    col_stk = mapa.get("stock")
    col_uni = mapa.get("unidad")

    def _safe_float(val):
        if val is None:
            return 0.0
        s = str(val).strip().replace("$", "").replace(" ", "")
        if not s:
            return 0.0
        # Manejo de formatos numéricos con coma decimal
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    def _safe_int(val):
        fl = _safe_float(val)
        return int(round(fl))

    creados = 0
    actualizados = 0
    ignorados = 0
    errores = []

    for num_fila, fila in enumerate(filas_datos, start=indice_fila_encabezado + 2 if encontrado else 1):
        if not fila or all(c is None or str(c).strip() == "" for c in fila):
            continue

        codigo = str(fila[col_cod]).strip() if col_cod is not None and col_cod < len(fila) and fila[col_cod] is not None else ""
        nombre = str(fila[col_nom]).strip() if col_nom is not None and col_nom < len(fila) and fila[col_nom] is not None else ""
        categoria = str(fila[col_cat]).strip() if col_cat is not None and col_cat < len(fila) and fila[col_cat] is not None else "General"
        costo = _safe_float(fila[col_cost]) if col_cost is not None and col_cost < len(fila) else 0.0
        precio = _safe_float(fila[col_prec]) if col_prec is not None and col_prec < len(fila) else 0.0
        stock = _safe_int(fila[col_stk]) if col_stk is not None and col_stk < len(fila) else 0
        unidad = str(fila[col_uni]).strip() if col_uni is not None and col_uni < len(fila) and fila[col_uni] is not None else "unidad"

        # Si el código se leyó con notación científica o decimal en Excel (ej: 1234.0)
        if codigo.endswith(".0"):
            codigo = codigo[:-2]

        if not nombre:
            # Si no hay nombre pero hay código, intentar usar el código como referencia
            if codigo:
                nombre = f"Producto {codigo}"
            else:
                ignorados += 1
                continue

        try:
            accion, _ = db.importar_o_actualizar_producto_desde_excel(
                codigo_barras=codigo,
                nombre=nombre,
                categoria=categoria,
                precio_venta=precio,
                costo=costo,
                stock=stock,
                unidad=unidad,
                modo_stock=modo_stock,
            )
            if accion == "creado":
                creados += 1
            else:
                actualizados += 1
        except Exception as ex:
            errores.append(f"Fila {num_fila} ({nombre}): {ex}")
            ignorados += 1

    total_procesados = creados + actualizados
    resumen_txt = f"Importación finalizada: {creados} producto(s) nuevo(s) creados, {actualizados} actualizado(s)."
    if ignorados > 0:
        resumen_txt += f" ({ignorados} fila(s) omitida(s) o sin nombre)."

    return jsonify({
        "ok": True,
        "mensaje": resumen_txt,
        "creados": creados,
        "actualizados": actualizados,
        "ignorados": ignorados,
        "total": total_procesados,
        "errores": errores[:5],
    })


@app.route("/api/productos/descargar_plantilla_excel")
@login_required
def api_descargar_plantilla_excel():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Productos"

    encabezados = ["Código", "Nombre", "Categoría", "Costo", "Precio Venta", "Stock", "Unidad"]
    ws.append(encabezados)

    ejemplos = [
        ["7791234567890", "Tornillo autoperforante 1/4", "Ferretería", 15.50, 25.00, 100, "unidad"],
        ["7791234567891", "Pintura sintética blanca 1L", "Pinturería", 3200.00, 4800.00, 15, "litro"],
        ["7791234567892", "Cable unipolar 2.5mm", "Electricidad", 120.00, 190.00, 50, "metro"],
    ]
    for ej in ejemplos:
        ws.append(ej)

    # Ancho de columnas sugerido
    anchos = {"A": 18, "B": 35, "C": 18, "D": 12, "E": 14, "F": 10, "G": 12}
    for col, w in anchos.items():
        ws.column_dimensions[col].width = w

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="plantilla_productos.xlsx",
    )


# --- Categorías ---
@app.route("/api/categorias/crear", methods=["POST"])
@login_required
def api_crear_categoria():
    data = request.get_json(silent=True) or request.form
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"ok": False, "mensaje": "Nombre no puede estar vacío."}), 400
    try:
        db.crear_categoria(nombre)
        return jsonify({"ok": True, "mensaje": f"Categoría «{nombre}» creada con éxito."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/categorias/renombrar", methods=["POST"])
@login_required
def api_renombrar_categoria():
    data = request.get_json(silent=True) or request.form
    viejo = str(data.get("nombre_actual", "")).strip()
    nuevo = str(data.get("nuevo_nombre", "")).strip()
    if not viejo or not nuevo:
        return jsonify({"ok": False, "mensaje": "Los nombres no pueden estar vacíos."}), 400
    try:
        db.renombrar_categoria(viejo, nuevo)
        return jsonify({"ok": True, "mensaje": f"Categoría renombrada a «{nuevo}»."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/categorias/eliminar", methods=["POST"])
@login_required
def api_eliminar_categoria():
    data = request.get_json(silent=True) or request.form
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"ok": False, "mensaje": "Nombre no válido."}), 400
    try:
        db.eliminar_categoria(nombre)
        return jsonify({"ok": True, "mensaje": f"Categoría «{nombre}» eliminada."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


# --- Gestión de Clientes ---
@app.route("/api/clientes/crear", methods=["POST"])
@login_required
def api_crear_cliente():
    data = request.get_json(silent=True) or request.form
    try:
        nombre = str(data.get("nombre", "")).strip()
        telefono = str(data.get("telefono", "")).strip()
        direccion = str(data.get("direccion", "")).strip()
        limite = float(data.get("limite_credito", 0) or 0)

        if not nombre:
            return jsonify({"ok": False, "mensaje": "El nombre del cliente es obligatorio."}), 400

        c_id = db.crear_cliente(nombre, telefono, direccion, limite)
        return jsonify({"ok": True, "cliente_id": c_id, "mensaje": "Cliente registrado exitosamente."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/clientes/editar/<int:cliente_id>", methods=["POST"])
@login_required
def api_editar_cliente(cliente_id):
    data = request.get_json(silent=True) or request.form
    try:
        nombre = str(data.get("nombre", "")).strip()
        telefono = str(data.get("telefono", "")).strip()
        direccion = str(data.get("direccion", "")).strip()
        limite = float(data.get("limite_credito", 0) or 0)

        if not nombre:
            return jsonify({"ok": False, "mensaje": "El nombre del cliente es obligatorio."}), 400

        db.actualizar_cliente(cliente_id, nombre, telefono, direccion, limite)
        return jsonify({"ok": True, "mensaje": "Cliente actualizado correctamente."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/clientes/eliminar/<int:cliente_id>", methods=["POST"])
@login_required
def api_eliminar_cliente(cliente_id):
    ok, msg = db.eliminar_cliente(cliente_id)
    return jsonify({"ok": ok, "mensaje": msg}), (200 if ok else 400)


@app.route("/api/clientes/abono", methods=["POST"])
@login_required
def api_abono_cliente():
    data = request.get_json(silent=True) or request.form
    try:
        cliente_id = int(data.get("cliente_id"))
        monto = float(data.get("monto", 0))
        forma_pago = str(data.get("forma_pago", "efectivo")).strip().lower()
        usuario_id = session.get("usuario_id")

        if monto <= 0:
            return jsonify({"ok": False, "mensaje": "El monto del abono debe ser mayor a 0."}), 400

        cliente = db.obtener_cliente(cliente_id)
        if not cliente:
            return jsonify({"ok": False, "mensaje": "Cliente no encontrado."}), 404

        saldo_actual = cliente["saldo_deuda"] or 0.0
        if monto > saldo_actual + 0.01:
            return jsonify({"ok": False, "mensaje": f"El monto ({MONEDA}{monto:,.2f}) no puede superar la deuda actual ({MONEDA}{saldo_actual:,.2f})."}), 400

        db.registrar_abono_deuda(cliente_id, usuario_id, monto, forma_pago)
        return jsonify({"ok": True, "mensaje": f"Abono de {MONEDA}{monto:,.2f} registrado exitosamente."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


# --- Cierre de Caja ---
@app.route("/api/caja/cerrar", methods=["POST"])
@login_required
def api_cerrar_caja():
    try:
        usuario_id = session.get("usuario_id")
        cierre_id = db.guardar_cierre_caja(usuario_id)
        return jsonify({
            "ok": True,
            "cierre_id": cierre_id,
            "mensaje": f"Cierre de caja #{cierre_id} guardado con éxito en el historial."
        })
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 500


@app.route("/api/caja/historial")
@admin_required
def api_historial_caja():
    fecha_req = request.args.get("fecha", "").strip()
    if not fecha_req:
        fecha_req = datetime.date.today().isoformat()
    try:
        fecha_obj = datetime.date.fromisoformat(fecha_req)
        fecha_iso = fecha_obj.isoformat()
    except ValueError:
        fecha_iso = datetime.date.today().isoformat()

    resumen = dict(db.resumen_caja_por_fecha(fecha_iso))
    cierres = [dict(c) for c in db.obtener_cierres_caja_por_fecha(fecha_iso)]
    return jsonify({
        "ok": True,
        "fecha": fecha_iso,
        "resumen": resumen,
        "cierres": cierres,
    })


# --- Otros Ingresos / Egresos ---
@app.route("/api/ingresos_egresos/ingreso", methods=["POST"])
@login_required
def api_nuevo_ingreso():
    data = request.get_json(silent=True) or request.form
    try:
        descripcion = str(data.get("descripcion", "")).strip()
        monto = float(data.get("monto", 0))
        forma_pago = str(data.get("forma_pago", "efectivo")).lower()
        usuario_id = session.get("usuario_id")

        if monto <= 0:
            return jsonify({"ok": False, "mensaje": "El monto debe ser mayor a cero."}), 400
        if not descripcion:
            return jsonify({"ok": False, "mensaje": "Ingresa una descripción."}), 400

        db.registrar_otro_ingreso(usuario_id, monto, descripcion, forma_pago)
        return jsonify({"ok": True, "mensaje": "Ingreso registrado con éxito."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/ingresos_egresos/egreso", methods=["POST"])
@login_required
def api_nuevo_egreso():
    data = request.get_json(silent=True) or request.form
    try:
        descripcion = str(data.get("descripcion", "")).strip()
        monto = float(data.get("monto", 0))
        forma_pago = str(data.get("forma_pago", "efectivo")).lower()
        usuario_id = session.get("usuario_id")

        if monto <= 0:
            return jsonify({"ok": False, "mensaje": "El monto debe ser mayor a cero."}), 400
        if not descripcion:
            return jsonify({"ok": False, "mensaje": "Ingresa una descripción."}), 400

        db.registrar_otro_egreso(usuario_id, monto, descripcion, forma_pago)
        return jsonify({"ok": True, "mensaje": "Egreso registrado con éxito."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/ingresos_egresos/ingreso/eliminar/<int:item_id>", methods=["POST"])
@login_required
def api_eliminar_ingreso(item_id):
    try:
        db.eliminar_otro_ingreso(item_id)
        return jsonify({"ok": True, "mensaje": "Registro eliminado."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


@app.route("/api/ingresos_egresos/egreso/eliminar/<int:item_id>", methods=["POST"])
@login_required
def api_eliminar_egreso(item_id):
    try:
        db.eliminar_otro_egreso(item_id)
        return jsonify({"ok": True, "mensaje": "Registro eliminado."})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400


# --- Block de Notas Persistente ---
@app.route("/api/notas/<int:pagina>", methods=["GET", "POST"])
@login_required
def api_notas(pagina):
    fecha_base = datetime.date.today() + datetime.timedelta(days=pagina)
    fecha_str = fecha_base.strftime("%d/%m/%Y")

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        contenido = data.get("contenido", "")
        with db.cursor_db() as cur:
            cur.execute("""
                INSERT INTO block_notas (pagina, fecha, contenido)
                VALUES (?, ?, ?)
                ON CONFLICT(pagina) DO UPDATE SET contenido = excluded.contenido, fecha = excluded.fecha
            """, (pagina, fecha_str, contenido))
        return jsonify({"ok": True, "mensaje": "Nota guardada."})

    # GET
    with db.cursor_db() as cur:
        cur.execute("SELECT contenido, fecha FROM block_notas WHERE pagina = ?", (pagina,))
        fila = cur.fetchone()
        contenido = fila["contenido"] if fila else ""
        fecha_guardada = fila["fecha"] if fila else fecha_str

    return jsonify({"pagina": pagina, "fecha": fecha_guardada, "contenido": contenido})


# --- Calculadora API ---
@app.route("/api/calculadora/calcular", methods=["POST"])
@login_required
def api_calculadora():
    data = request.get_json(silent=True) or {}
    expr = str(data.get("expresion", "")).strip()
    try:
        val = resolver_expresion(expr)
        if abs(val - round(val)) < 1e-9:
            res_str = str(int(round(val)))
        else:
            res_str = f"{val:,.2f}"
        return jsonify({"ok": True, "resultado": res_str, "valor": val})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------------------------------------------------------------------
# ARRANQUE DE LA APLICACIÓN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Iniciando {NOMBRE_APP} v{VERSION_APP}...")
    print("Servidor web disponible en: http://127.0.0.1:5000")
    if getattr(sys, "frozen", False):
        threading.Timer(1.0, webbrowser.open, args=("http://127.0.0.1:5000",)).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
