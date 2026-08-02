import sys
import os

# Garante que o diretorio raiz do projeto esteja no PATH do Python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

