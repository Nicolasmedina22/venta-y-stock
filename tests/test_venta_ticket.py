import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import construir_ticket_texto, resolver_expresion
from database import db


class TicketVentaTests(unittest.TestCase):
    def test_construye_ticket_con_total_y_productos(self):
        items = [
            {"nombre": "Gaseosa", "cantidad": 2, "precio_unitario": 120.0, "subtotal": 240.0},
            {"nombre": "Pan", "cantidad": 1, "precio_unitario": 80.0, "subtotal": 80.0},
        ]

        texto = construir_ticket_texto(venta_id=25, total=320.0, forma_pago="Efectivo", items=items)

        self.assertIn("Ticket de Venta", texto)
        self.assertIn("Venta #25", texto)
        self.assertIn("Gaseosa", texto)
        self.assertIn("TOTAL", texto)
        self.assertIn("$320.00", texto)

    def test_muestra_transferencia_sin_cambiar_valor_interno(self):
        texto = construir_ticket_texto(venta_id=26, total=100.0, forma_pago="tarjeta", items=[])

        self.assertIn("Pago: Transferencia", texto)
        self.assertNotIn("Pago: Tarjeta", texto)

    def test_registra_venta_con_producto_manual_sin_base_de_datos(self):
        carrito = [{
            "producto_id": None,
            "nombre": "Producto externo",
            "cantidad": 1,
            "precio_unitario": 150.0,
            "subtotal": 150.0,
            "manual": True,
        }]

        # La venta se registra en una base temporal: correr los tests NUNCA
        # debe modificar la base de datos real del negocio.
        with tempfile.TemporaryDirectory() as directorio_temporal:
            with patch.object(db, "DB_PATH", str(Path(directorio_temporal) / "test.db")):
                db.inicializar_base_datos()

                venta_id = db.registrar_venta(
                    usuario_id=1,
                    cliente_id=None,
                    carrito=carrito,
                    forma_pago="efectivo",
                )

                self.assertIsInstance(venta_id, int)
                with db.cursor_db() as cur:
                    cur.execute("SELECT COUNT(*) AS total FROM detalle_ventas WHERE venta_id = ?", (venta_id,))
                    self.assertEqual(cur.fetchone()["total"], 1)

    def test_calculadora_soporta_porcentaje(self):
        self.assertAlmostEqual(resolver_expresion("50+10%"), 55.0)
        self.assertAlmostEqual(resolver_expresion("200*15%"), 30.0)


if __name__ == "__main__":
    unittest.main()
