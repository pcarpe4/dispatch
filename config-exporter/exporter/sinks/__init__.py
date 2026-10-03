"""Sink registry. Add a new destination by writing a class with
`send(records)` and registering it with @register("type-name")."""
_REGISTRY = {}


def register(type_name):
    def deco(cls):
        _REGISTRY[type_name] = cls
        return cls
    return deco


def build(sink_cfg):
    type_name = sink_cfg["type"]
    if type_name not in _REGISTRY:
        raise ValueError(f"unknown sink type '{type_name}'; known: {sorted(_REGISTRY)}")
    return _REGISTRY[type_name](sink_cfg)


# Import built-ins so they self-register.
from . import stdout, http, postgres  # noqa: E402,F401
