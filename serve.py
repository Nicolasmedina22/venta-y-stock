"""Servidor WSGI de producción para despliegues en hosting."""

import os

os.environ.setdefault("HOSTED_MODE", "1")

from waitress import serve

from app import app


if __name__ == "__main__":
	serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))