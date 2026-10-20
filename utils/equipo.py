"""
Identificación del equipo (PC) donde corre el sistema.

Objetivo de negocio:
    El sistema debe "activarse" una sola vez por PC. Cuando el dueño
    (que conoce el usuario y la contraseña) ingresa por primera vez en
    una máquina, esa máquina queda registrada como autorizada. A partir
    de ahí, ese equipo ya no vuelve a pedir credenciales. Si el sistema
    se copia a OTRA PC (otro equipo), se vuelve a pedir usuario y
    contraseña para autorizar esa nueva máquina.

¿Cómo identificamos la PC?
    La opción más fiable en Windows es el UUID de la placa base
    (Motherboard), que no cambia aunque se cambie la red. Lo obtenemos
    con "wmic csproduct get uuid". Si no está disponible, caemos a la
    MAC de la primera tarjeta de red y, como último recurso, al nombre
    de host. Además guardamos el IP local como dato informativo.

    IMPORTANTE: el objetivo no es una seguridad criptográfica perfecta,
    sino evitar que el sistema "se pase" de una PC a otra sin que el
    dueño lo autorice con sus credenciales. Es una protección práctica,
    no una licencia bancaria.
"""

import hashlib
import os
import platform
import socket
import subprocess
import uuid


def _obtener_uuid_placa() -> str:
    """
    Devuelve el UUID de la placa base (Windows). Cadena vacía si no
    se puede obtener (por ejemplo, en Linux/Mac o si wmic no existe).
    """
    if platform.system() != "Windows":
        return ""
    try:
        salida = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lineas = [l.strip() for l in salida.decode(errors="ignore").splitlines()]
        # La primera línea es el encabezado "UUID"; la segunda el valor.
        for linea in lineas:
            if linea and linea.upper() != "UUID":
                return linea
    except Exception:
        pass
    return ""


def _obtener_mac() -> str:
    """Devuelve la MAC del equipo como texto hexadecimal (sin separadores)."""
    try:
        valor = uuid.getnode()
        # uuid.getnode() siempre devuelve algo; si el bit 40 está activo
        # significa que el valor es aleatorio y no una MAC real.
        if (valor >> 40) % 2 == 0:
            return f"{valor:012x}"
    except Exception:
        pass
    return ""


def obtener_identificador_equipo() -> str:
    """
    Construye un identificador ESTABLE y único para esta PC.

    Combina varias fuentes de hardware y las resume con un hash para
    que quede un texto corto y legible. Se calcula igual cada vez que
    arranca el sistema en la misma máquina y cambia en otra PC.
    """
    partes = [
        _obtener_uuid_placa(),
        _obtener_mac(),
        platform.node(),
        platform.machine(),
    ]
    semilla = "|".join(p for p in partes if p)
    if not semilla:
        # Último recurso: usar el nombre de usuario del sistema operativo.
        semilla = os.environ.get("USERNAME") or os.environ.get("USER") or "equipo-desconocido"
    return hashlib.sha256(semilla.encode("utf-8")).hexdigest()


def obtener_ip_local() -> str:
    """
    Devuelve el IP local de esta PC en la red (informativo). Si no hay
    red, devuelve '127.0.0.1'.
    """
    try:
        # Abrimos un socket UDP "falso" para descubrir la IP de salida
        # sin enviar tráfico real a ningún servidor.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def obtener_nombre_equipo() -> str:
    """Nombre de red del equipo (para mostrarlo en la interfaz de admin)."""
    try:
        return socket.gethostname()
    except Exception:
        return "PC-desconocida"
