"""TSM Desktop App for Linux."""

__all__ = ["__version__"]

try:
    from tsm._version import __version__ as __version__
except ImportError:
    __version__ = "0.0.0"
