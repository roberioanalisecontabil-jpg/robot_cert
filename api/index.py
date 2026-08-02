import sys
import os

# Garante que a raiz do projeto esteja no sys.path para resolução dos módulos da pasta `app`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: F401
