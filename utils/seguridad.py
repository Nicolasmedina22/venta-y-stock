"""
Utilidades de seguridad: hash y verificación de contraseñas.

Usamos bcrypt (librería estándar de la industria para hashear
contraseñas). Cada contraseña se guarda con su propia "sal"
(salt) incluida dentro del hash, por lo que NUNCA guardamos
contraseñas en texto plano en la base de datos.
"""

import bcrypt


def hashear_password(password_plano: str) -> str:
    """
    Convierte una contraseña en texto plano a un hash seguro
    listo para guardar en la base de datos.
    """
    password_bytes = password_plano.encode("utf-8")
    salt = bcrypt.gensalt()
    hash_bytes = bcrypt.hashpw(password_bytes, salt)
    # Guardamos como texto (utf-8) para que quepa cómodo en una
    # columna TEXT de SQLite.
    return hash_bytes.decode("utf-8")


def verificar_password(password_plano: str, hash_guardado: str) -> bool:
    """
    Compara una contraseña en texto plano contra el hash guardado.
    Devuelve True si coinciden, False si no.
    """
    try:
        return bcrypt.checkpw(
            password_plano.encode("utf-8"),
            hash_guardado.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Hash corrupto o con formato inválido
        return False
