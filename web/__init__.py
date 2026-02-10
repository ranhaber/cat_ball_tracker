"""Web server module"""
try:
    from .app import create_app
    __all__ = ["create_app"]
except ImportError:
    # Flask not installed (e.g., running unit tests on dev machine)
    create_app = None
    __all__ = []
