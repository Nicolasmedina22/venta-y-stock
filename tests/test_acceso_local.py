import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db
from utils.seguridad import hashear_password


class AccesoLocalTests(unittest.TestCase):
    def test_migra_administrador_existente_sin_cambiar_su_id(self):
        with tempfile.TemporaryDirectory() as carpeta_temporal:
            ruta_db = Path(carpeta_temporal) / "test.db"
            conexion = sqlite3.connect(ruta_db)
            conexion.execute(
                """CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_completo TEXT NOT NULL,
                    usuario TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    rol TEXT NOT NULL CHECK (rol IN ('admin', 'vendedor')),
                    activo INTEGER NOT NULL DEFAULT 1,
                    fecha_creacion TEXT NOT NULL
                )"""
            )
            conexion.execute(
                """INSERT INTO usuarios
                   (nombre_completo, usuario, password_hash, rol, activo, fecha_creacion)
                   VALUES (?, ?, ?, 'admin', 1, '2024-01-01')""",
                ("Administrador", "admin", hashear_password("admin123")),
            )
            conexion.commit()
            conexion.close()

            with patch.object(db, "DB_PATH", str(ruta_db)):
                db.inicializar_base_datos()
                usuario = db.autenticar_usuario("Nicoloco22", "Nicoloco22")
                self.assertIsNotNone(usuario)
                self.assertEqual(usuario["id"], 1)
                self.assertIsNone(db.autenticar_usuario("admin", "admin123"))

if __name__ == "__main__":
    unittest.main()