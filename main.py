import sys
import os

# Garante que os modulos do projeto sejam encontrados
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app  # noqa: F401 - Vercel detecta o objeto "app" aqui

