"""Configuração de logging."""
import os
import logging
from logging.handlers import RotatingFileHandler
from config.settings import LOG_DIR

logger = logging.getLogger("betauto")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

h_file = RotatingFileHandler(
    os.path.join(LOG_DIR, "betauto.log"),
    maxBytes=2_000_000,
    backupCount=5,
    encoding="utf-8"
)
h_file.setFormatter(_fmt)
h_file.setLevel(logging.INFO)

h_out = logging.StreamHandler()
h_out.setFormatter(_fmt)
h_out.setLevel(logging.INFO)

if not logger.handlers:
    logger.addHandler(h_file)
    logger.addHandler(h_out)

