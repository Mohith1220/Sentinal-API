"""
Root conftest.py for SentinelAPI test suite.

Manages sys.path isolation so that each test module imports from the correct
service directory. Without this, pytest's collection order can leave a
previously-added service directory at the front of sys.path, causing the
wrong 'db' module to be imported.
"""

import sys
import os

# ---------------------------------------------------------------------------
# Absolute paths for every service directory
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

SERVICE_DIRS = {
    "discovery-service": os.path.join(_REPO_ROOT, "services", "discovery-service"),
    "classification-service": os.path.join(_REPO_ROOT, "services", "classification-service"),
    "anomaly-detector-service": os.path.join(_REPO_ROOT, "services", "anomaly-detector-service"),
    "risk-scorer-service": os.path.join(_REPO_ROOT, "services", "risk-scorer-service"),
    "stream-processor": os.path.join(_REPO_ROOT, "services", "stream-processor"),
    "graph-service": os.path.join(_REPO_ROOT, "services", "graph-service"),
    "remediation-service": os.path.join(_REPO_ROOT, "services", "remediation-service"),
    "api-gateway": os.path.join(_REPO_ROOT, "services", "api-gateway"),
}

SENTINEL_SHARED_DIR = os.path.join(_REPO_ROOT, "sentinel_shared")

ALL_SERVICE_PATHS = set(SERVICE_DIRS.values())


def _remove_service_paths() -> None:
    """Remove all service directories from sys.path."""
    to_remove = [p for p in sys.path if os.path.abspath(p) in ALL_SERVICE_PATHS]
    for p in to_remove:
        sys.path.remove(p)


def _remove_cached_service_modules() -> None:
    """
    Remove cached module entries that came from service directories so that
    the next import picks up the freshly-inserted path.

    Only removes top-level modules whose __file__ lives inside a service dir.
    """
    to_delete = []
    for mod_name, mod in list(sys.modules.items()):
        mod_file = getattr(mod, "__file__", None) or ""
        if any(mod_file.startswith(p) for p in ALL_SERVICE_PATHS):
            to_delete.append(mod_name)
    for mod_name in to_delete:
        del sys.modules[mod_name]


def activate_service(service_name: str) -> None:
    """
    Switch the active service on sys.path.

    Removes all other service directories and inserts the requested one at
    position 0 so that bare ``import db`` (and similar) resolve correctly.

    Only evicts modules that are known to conflict across services (e.g. ``db``,
    ``main``, ``classifier``). Modules that are unique to a service (e.g.
    ``explainability``, ``detectors``) are left in sys.modules so that lazy
    imports inside test methods continue to work after the path is switched.
    """
    # Modules whose names collide across services and must be re-imported
    # from the newly-activated service directory.
    _CONFLICTING_MODULES = {"db", "main", "classifier", "rule_engine", "scorer",
                            "kafka_consumer", "kafka_publisher", "consumer"}

    _remove_service_paths()

    # Evict only the conflicting module names from the cache
    for mod_name in list(_CONFLICTING_MODULES):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            mod_file = getattr(mod, "__file__", None) or ""
            if any(mod_file.startswith(p) for p in ALL_SERVICE_PATHS):
                del sys.modules[mod_name]

    target = SERVICE_DIRS[service_name]
    if target not in sys.path:
        sys.path.insert(0, target)
