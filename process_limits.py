"""Keep ordinary HTTP/database opens below the process descriptor limit."""
from __future__ import annotations


def ensure_nofile_headroom(minimum: int = 8192, resource_module=None) -> dict:
    """Raise only a low soft limit, within the existing hard allowance.

    This is startup headroom, not a substitute for bounded resource caches.
    Windows and an unraiseable limit must not prevent the station starting.
    """
    if resource_module is None:
        try:
            import resource as resource_module
        except ImportError:
            return {"ok": False, "supported": False, "changed": False}
    try:
        soft, hard = resource_module.getrlimit(resource_module.RLIMIT_NOFILE)
        result = {"ok": True, "supported": True, "changed": False,
                  "soft": soft, "hard": hard}
        if soft == resource_module.RLIM_INFINITY:
            return result
        wanted = max(1, int(minimum))
        if hard != resource_module.RLIM_INFINITY:
            wanted = min(wanted, hard)
        if wanted <= soft:
            return result
        resource_module.setrlimit(resource_module.RLIMIT_NOFILE, (wanted, hard))
        result.update(changed=True, soft=wanted)
        return result
    except (OSError, ValueError, AttributeError) as error:
        return {"ok": False, "supported": True, "changed": False,
                "why": str(error)[:160]}
