"""Vercel ASGI entrypoint.

Vercel's Python runtime looks for an exported ASGI variable named ``app`` in a
recognized entry file. Keep the real application in ``app.main`` so local
development can continue to use ``uvicorn app.main:app``.
"""

from app.main import app
