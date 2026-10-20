import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import app
from database import db


class FlaskAppTests(unittest.TestCase):
    def setUp(self):
        # IMPORTANTE: los tests NUNCA deben tocar la base de datos real del
        # negocio. Cada prueba corre contra una base temporal descartable.
        self._directorio_temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self._directorio_temporal.cleanup)
        self._patch_db = patch.object(
            db, "DB_PATH", str(Path(self._directorio_temporal.name) / "test.db")
        )
        self._patch_db.start()
        self.addCleanup(self._patch_db.stop)
        db.inicializar_base_datos()

        self.client = app.test_client()
        self.client.testing = True
        # Empezamos cada prueba con esta PC SIN autorizar, para simular
        # una instalación nueva. Así el login debe mostrarse siempre.
        with db.cursor_db() as cur:
            cur.execute("DELETE FROM equipos_autorizados")
            cur.execute("DELETE FROM productos WHERE codigo_barras LIKE 'EXCEL%' OR codigo_barras LIKE 'TEST%'")

    def test_login_get(self):
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Venta y Stock", res.data)
        self.assertIn(b"Iniciar sesi", res.data)

    def test_login_post_valido(self):
        res = self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.location.endswith("/venta"))

    def test_acceso_rutas_con_sesion(self):
        # Iniciar sesión
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        rutas = ["/venta", "/productos", "/clientes", "/caja", "/ingresos_egresos", "/reportes", "/historial_caja"]
        for ruta in rutas:
            res = self.client.get(ruta)
            self.assertEqual(res.status_code, 200, f"Fallo al abrir {ruta}")

        venta = self.client.get("/venta")
        self.assertNotIn(b"Usuarios", venta.data)
        self.assertNotIn(b"Nicoloco", venta.data)
        self.assertNotIn(b"btn-logout", venta.data)
        self.assertIn("Historial de caja".encode("utf-8"), venta.data)
        self.assertNotIn(b"Reportes", venta.data)

    def test_gestion_usuarios_no_disponible(self):
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        rutas = [
            ("GET", "/usuarios"),
            ("POST", "/api/usuarios/crear"),
            ("POST", "/api/usuarios/cambiar_estado/1"),
            ("POST", "/api/usuarios/cambiar_password/1"),
        ]
        for metodo, ruta in rutas:
            res = self.client.open(ruta, method=metodo)
            self.assertEqual(res.status_code, 404, f"La ruta {ruta} debería estar eliminada")

    def test_equipo_autorizado_omite_login(self):
        # PC nueva: /login muestra el formulario (302 ocurre solo si ya hay sesión)
        res = self.client.get("/login")
        self.assertEqual(res.status_code, 200)

        # Login correcto -> autoriza esta PC
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=False)

        # Un cliente NUEVO (navegador reiniciado) en la MISMA PC ya no pide login:
        # /login redirige directo a /venta.
        cliente_nuevo = app.test_client()
        res = cliente_nuevo.get("/login", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.location.endswith("/venta"))

    def test_cambiar_credenciales_admin_desactiva_usuario_inicial(self):
        usuario_original = db.ADMIN_USERNAME
        password_original = db.ADMIN_PASSWORD
        try:
            with tempfile.TemporaryDirectory() as directorio_temporal:
                with patch.object(db, "DB_PATH", str(Path(directorio_temporal) / "hosting.db")):
                    db.ADMIN_USERNAME = usuario_original
                    db.ADMIN_PASSWORD = password_original
                    db.inicializar_base_datos()
                    db.ADMIN_USERNAME = "administrador_hosting"
                    db.ADMIN_PASSWORD = "clave-segura-de-prueba"
                    db._migrar_usuario_administrador()

                    with db.cursor_db() as cur:
                        cur.execute("SELECT id FROM usuarios WHERE usuario = ?", ("Nicoloco22",))
                        usuario_inicial = cur.fetchone()
                        cur.execute("SELECT activo FROM usuarios WHERE usuario = ?", ("administrador_hosting",))
                        usuario_configurado = cur.fetchone()

                    self.assertIsNone(usuario_inicial)
                    self.assertEqual(usuario_configurado["activo"], 1)
        finally:
            db.ADMIN_USERNAME = usuario_original
            db.ADMIN_PASSWORD = password_original

    def test_hosting_siempre_pide_login_en_cada_navegador(self):
        app.config["HOSTED_MODE"] = True
        try:
            self.client.post("/login", data={
                "usuario": "Nicoloco22",
                "password": "Nicoloco22",
            }, follow_redirects=False)

            cliente_nuevo = app.test_client()
            res = cliente_nuevo.get("/login", follow_redirects=False)
            self.assertEqual(res.status_code, 200)
            self.assertIn(b"Iniciar sesi", res.data)
        finally:
            app.config["HOSTED_MODE"] = False

    def test_api_calculadora(self):
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        res = self.client.post("/api/calculadora/calcular", json={"expresion": "100+15%"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["valor"], 115.0)

    def test_api_block_notas_persistencia(self):
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        # Guardar nota en página 0
        res = self.client.post("/api/notas/0", json={"contenido": "Nota de prueba automatizada"})
        self.assertEqual(res.status_code, 200)

        # Obtener nota
        res_get = self.client.get("/api/notas/0")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.get_json()["contenido"], "Nota de prueba automatizada")

    def test_ventas_del_dia_muestra_suma_de_ventas_registradas(self):
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        detalles = [
            {"venta_id": 1, "subtotal": 125.50},
            {"venta_id": 2, "subtotal": 74.50},
        ]
        with patch.object(db, "productos_vendidos_del_dia", return_value=detalles):
            res = self.client.get("/ventas_dia?fecha=2026-10-18")

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"$200.00", res.data)
        self.assertIn(b"2 venta(s) registrada(s)", res.data)

    def test_historial_caja_y_busqueda_calendario(self):
        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        # 1. Carga inicial de /historial_caja muestra calendario y botón Buscar
        res = self.client.get("/historial_caja")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Historial de caja", res.data)
        self.assertIn(b'id="fecha-historial"', res.data)
        self.assertIn(b'type="date"', res.data)
        self.assertIn("Buscar".encode("utf-8"), res.data)
        self.assertIn(b"Ventas efectivo", res.data)
        self.assertIn(b"Total general", res.data)

        # 2. Búsqueda por fecha con calendario / querystring
        res_fecha = self.client.get("/historial_caja?fecha=2026-10-18")
        self.assertEqual(res_fecha.status_code, 200)
        self.assertIn(b"18/10/2026", res_fecha.data)
        self.assertIn(b"Ventas del d", res_fecha.data)

        # 3. API JSON de historial de caja
        res_api = self.client.get("/api/caja/historial?fecha=2026-10-18")
        self.assertEqual(res_api.status_code, 200)
        data = res_api.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["fecha"], "2026-10-18")
        self.assertIn("resumen", data)
        self.assertIn("efectivo", data["resumen"])
        self.assertIn("total_general", data["resumen"])

    def test_importar_productos_excel(self):
        import io
        import openpyxl

        self.client.post("/login", data={
            "usuario": "Nicoloco22",
            "password": "Nicoloco22",
        }, follow_redirects=True)

        # 1. Verificar que el botón de Importar productos esté en /productos
        res_prod = self.client.get("/productos")
        self.assertEqual(res_prod.status_code, 200)
        self.assertIn("Importar productos".encode("utf-8"), res_prod.data)
        self.assertIn(b"modal-importar-excel", res_prod.data)

        # 2. Descargar plantilla Excel
        res_plantilla = self.client.get("/api/productos/descargar_plantilla_excel")
        self.assertEqual(res_plantilla.status_code, 200)
        self.assertIn("spreadsheetml", res_plantilla.content_type)

        # 3. Importar archivo Excel nuevo
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Código", "Nombre", "Categoría", "Costo", "Precio Venta", "Stock", "Unidad"])
        ws.append(["EXCEL001", "Martillo Galponero 500g", "Herramientas", 1500.0, 2900.0, 12, "unidad"])
        ws.append(["EXCEL002", "Cinta Aisladora 20m", "Electricidad", 200.0, 450.0, 40, "unidad"])

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)

        res_imp = self.client.post("/api/productos/importar_excel", data={
            "archivo": (stream, "import_test.xlsx"),
            "modo_stock": "sumar",
        }, content_type="multipart/form-data")

        self.assertEqual(res_imp.status_code, 200)
        data = res_imp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["creados"], 2)

        p1 = db.buscar_producto_por_codigo("EXCEL001")
        self.assertIsNotNone(p1)
        self.assertEqual(p1["stock"], 12)
        self.assertEqual(p1["precio_venta"], 2900.0)

        # 4. Re-importar sumando stock
        wb2 = openpyxl.Workbook()
        ws2 = wb2.active
        ws2.append(["Código", "Nombre", "Stock"])
        ws2.append(["EXCEL001", "Martillo Galponero 500g", 8])

        stream2 = io.BytesIO()
        wb2.save(stream2)
        stream2.seek(0)

        res_imp2 = self.client.post("/api/productos/importar_excel", data={
            "archivo": (stream2, "import_test2.xlsx"),
            "modo_stock": "sumar",
        }, content_type="multipart/form-data")

        self.assertEqual(res_imp2.status_code, 200)
        p1_actualizado = db.buscar_producto_por_codigo("EXCEL001")
        self.assertEqual(p1_actualizado["stock"], 20)


if __name__ == "__main__":
    unittest.main()

