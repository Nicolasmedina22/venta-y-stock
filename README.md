# Venta y Stock

Sistema de punto de venta **multiusuario** para ferreterías pequeñas y medianas, escrito en Python con Flask y SQLite.

## ¿Qué trae la versión PRO que no trae la gratis?

- **Multiusuario con roles**: administrador y vendedor, cada uno con su propio usuario y contraseña (hasheada con bcrypt, nunca en texto plano).
- **Permisos por rol**: el vendedor solo ve Venta, Clientes/Fiado y Cierre de caja. Historial de caja es exclusivo del administrador.
- **Cliente fiado**: registro de deuda por cliente, abonos parciales, saldo en tiempo real.
- **Cierre de caja**: resumen de efectivo, tarjeta y fiado del día, con historial de cierres.
- **Historial de caja**: calendario para buscar cualquier fecha con botón de búsqueda y desglose completo del resumen de caja (efectivo, transferencias, fiado, abonos, ingresos y egresos).
- **Respaldo en la nube**: copia automática/manual de la base de datos con rotación de las últimas 7 copias, lista para apuntar a una carpeta de Dropbox, OneDrive o Google Drive.

## Requisitos

- Python 3.10 o superior.
- Windows, macOS o Linux para uso local. También puede desplegarse en un hosting Python con almacenamiento persistente.

## Instalación y Ejecución

```bash
pip install -r requirements.txt
```

### Aplicación Flask

```bash
python app.py
```
Abre en tu navegador: [http://127.0.0.1:5000](http://127.0.0.1:5000)

### Despliegue en hosting

Consulta [GUIA_HOSTING.md](GUIA_HOSTING.md) para configurar el servidor WSGI, variables de entorno, HTTPS y almacenamiento persistente.

### Crear el ejecutable para Windows

```bash
pyinstaller --clean --noconfirm "Venta y Stock.spec"
```

El archivo se genera en `dist/Venta y Stock.exe`. Al ejecutarlo, abre la aplicación en `http://127.0.0.1:5000`; la base de datos se crea en la carpeta `data` junto al ejecutable.

## Acceso inicial

| Usuario     | Contraseña    | Rol       |
|-------------|---------------|-----------|
| `Nicoloco22` | `Nicoloco22` | Administrador (ve todo, incluyendo Historial de caja) |

El acceso se mantiene mediante la sesión del navegador. Las cuentas `admin` y `vendedor` de demostración existentes se desactivan al actualizar la base de datos.

### Activación por equipo (una PC = un acceso)

El sistema se "activa" automáticamente en cada PC:

1. La **primera vez** que se abre en una máquina nueva, pide usuario y contraseña.
2. Al ingresar credenciales correctas, esa PC queda registrada como **equipo autorizado** (se guarda su huella de hardware: UUID de placa, MAC e IP local) en la tabla `equipos_autorizados` de la base de datos.
3. En esa misma PC, las siguientes veces **ya no se vuelve a pedir el login** (ni al cerrar y abrir el navegador, ni al reiniciar la computadora).
4. Si el sistema se **copia a otra PC**, esa otra máquina no está registrada y **volverá a pedir usuario y contraseña**. Solo quien conoce las credenciales puede autorizar el nuevo equipo.

El identificador del equipo se calcula en `utils/equipo.py`.

## Estructura de carpetas

```
pos-ferreteria-pro/
├── app.py                     # Punto de entrada Flask
├── config.py                  # Rutas, constantes y configuración de respaldo
├── requirements.txt
├── README.md
├── MANUAL_INSTALACION.md      # Manual paso a paso para el cliente final (no técnico)
├── data/                      # Se crea automáticamente
│   ├── pos_ferreteria.db      # Base de datos SQLite
│   └── respaldos_nube/        # Copias de respaldo con rotación (últimas 7)
├── database/
│   └── db.py                  # Esquema, datos de ejemplo y todas las consultas
├── utils/
│   ├── seguridad.py           # Hash y verificación de contraseñas (bcrypt)
│   └── equipo.py              # Identificación de la PC (activación por equipo)
├── templates/                 # Páginas HTML
├── static/                    # CSS y JavaScript
└── Venta y Stock.spec         # Configuración PyInstaller
```

## Cómo funciona el lector de código de barras

El campo de "código de barras" en la pantalla de Venta es un cuadro de texto normal. Un lector de código de barras USB físico funciona exactamente como un teclado que escribe muy rápido y presiona Enter al final — por eso este mismo campo funciona tanto si el cajero teclea el código a mano como si usa una pistola lectora real, sin configuración adicional.

## Respaldo en la nube

Por defecto, los respaldos se guardan en `data/respaldos_nube/` dentro del propio proyecto. Para que el respaldo realmente "suba a la nube", cambia la ruta `BACKUP_DIR` en `config.py` para que apunte a una carpeta sincronizada por tu servicio de nube preferido, por ejemplo:

- **Dropbox**: `C:\Users\TU_USUARIO\Dropbox\RespaldosFerreteria`
- **OneDrive**: `C:\Users\TU_USUARIO\OneDrive\RespaldosFerreteria`
- **Google Drive** (con Google Drive para escritorio): `G:\Mi unidad\RespaldosFerreteria`

Una vez que `BACKUP_DIR` apunta a esa carpeta, cada respaldo que hagas (botón "Respaldar ahora" en Reportes) se sincroniza solo con la nube, porque la app de Dropbox/OneDrive/Drive vigila esa carpeta en segundo plano. Se conservan automáticamente las últimas 7 copias; las más antiguas se borran solas.

Ver `MANUAL_INSTALACION.md` para instrucciones detalladas paso a paso.

## Licencia de uso

Este código se entrega como parte de una recompensa de Patreon para uso del negocio del suscriptor. No está pensado para redistribución ni reventa como producto independiente.
