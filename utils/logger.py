"""
Módulo de logging centralizado.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config.settings import LOG_PATH, modo


def crear_logger(nombre: str) -> logging.Logger:
    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger
    nivel = logging.DEBUG if modo.verbose_logs else logging.INFO
    logger.setLevel(nivel)
    formato_simple = logging.Formatter(fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    formato_detallado = logging.Formatter(fmt="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S")
    handler_consola = logging.StreamHandler(sys.stdout)
    handler_consola.setFormatter(formato_simple)
    handler_consola.setLevel(nivel)
    logger.addHandler(handler_consola)
    try:
        handler_archivo = RotatingFileHandler(filename=LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3,
                                              encoding="utf-8")
        handler_archivo.setFormatter(formato_detallado)
        handler_archivo.setLevel(logging.DEBUG)
        logger.addHandler(handler_archivo)
    except OSError as e:
        logger.warning(f"No se pudo crear log en archivo: {e}")
    return logger
