"""
Tests de la activación por equipo (una PC = un acceso).

Verifica que:
- La primera vez en una PC nueva se exige usuario y contraseña.
- Tras un login correcto, ese equipo queda autorizado en la base.
- Al volver a entrar en el MISMO equipo, ya no se pide login.
- Un equipo DISTINTO (otro identificador) vuelve a exigir login.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database import db
from utils.seguridad import hashear_password


class EquipoAutorizadoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta_db = Path(self._tmp.name) / "test.db"
        conexion = sqlite3.connect(self.ruta_db)
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
            ("Admin Local", "jefe", hashear_password("clave-secreta")),
        )
        conexion.commit()
        conexion.close()

        self._patch_db = patch.object(db, "DB_PATH", str(self.ruta_db))
        self._patch_db.start()
        db.inicializar_base_datos()

    def tearDown(self):
        self._patch_db.stop()
        self._tmp.cleanup()

    def test_equipo_nuevo_no_esta_autorizado(self):
        self.assertFalse(db.equipo_esta_autorizado("equipo-pc-1"))

    def test_autorizar_equipo_y_reconocerlo(self):
        db.autorizar_equipo("equipo-pc-1", "PC-Caja", "192.168.1.10")
        self.assertTrue(db.equipo_esta_autorizado("equipo-pc-1"))
        # Otra PC distinta sigue sin estar autorizada
        self.assertFalse(db.equipo_esta_autorizado("equipo-pc-2"))

    def test_autorizar_equipo_es_idempotente(self):
        db.autorizar_equipo("equipo-pc-1", "PC-Caja", "192.168.1.10")
        db.autorizar_equipo("equipo-pc-1", "PC-Caja", "192.168.1.20")
        equipos = db.listar_equipos_autorizados()
        self.assertEqual(len(equipos), 1)
        # Se actualiza el IP, no se duplica el registro
        self.assertEqual(equipos[0]["ip_local"], "192.168.1.20")

    def test_identificador_estable_entre_llamadas(self):
        from utils.equipo import obtener_identificador_equipo
        self.assertEqual(
            obtener_identificador_equipo(),
            obtener_identificador_equipo(),
        )


if __name__ == "__main__":
    unittest.main()
