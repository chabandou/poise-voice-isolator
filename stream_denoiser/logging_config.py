"""
Logging Configuration Module

Provides structured logging that auto-disables in frozen (PyInstaller) builds.
Console output only in development; no file logging.
"""
import logging
import sys
from typing import Optional

# Cache configured loggers to avoid duplicate handlers
_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for the given module name.
    
    In frozen (PyInstaller/exe) builds, logging is disabled to avoid
    console window pop-ups. In development, logs go to console.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
        
    Returns:
        Configured Logger instance
    """
    if name in _loggers:
        return _loggers[name]
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
    
    # Only add console handler in development (not frozen builds)
    if not getattr(sys, 'frozen', False):
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '[%(levelname)s] %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    else:
        # Frozen build: add null handler to suppress all output
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
    
    _loggers[name] = logger
    return logger
