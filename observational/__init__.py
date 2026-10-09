"""Native Hermes ContextEngine plugin; no import-time state/network work."""
__version__ = "0.1.0"
__all__ = ["ObservationalEngine"]


def __getattr__(name):
    if name == "ObservationalEngine":
        from .engine import ObservationalEngine
        return ObservationalEngine
    raise AttributeError(name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
