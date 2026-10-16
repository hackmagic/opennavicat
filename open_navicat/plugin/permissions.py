"""Plugin permission vocabulary.

A plugin declares the permissions it needs in its manifest.  The manager
grants them at install time and enforces them at *hook registration*: a hook
that needs a permission the plugin never declared simply never gets wired up.

MVP scope, stated plainly: there is **no OS-level sandbox**.  A plugin runs in
the interpreter with the user's privileges and can ``import socket``.  What
this module buys is (a) a human-readable disclosure at install time, (b) an
auditable record of what a plugin asked for, and (c) a deny-by-default gate so
an unknown permission name fails install instead of being ignored.  Treat the
permission list as informed consent, not as a security boundary.
"""

from __future__ import annotations

from open_navicat.errors import PluginPermissionError

__all__ = [
    "PERMISSION_CATALOG",
    "HOOK_PERMISSIONS",
    "normalize_permissions",
    "check_hook_permissions",
]

#: permission -> human description.  This is the whole vocabulary; adding a
#: permission means editing this dict, which is deliberate (every grant is a
#: reviewed decision).
PERMISSION_CATALOG: dict[str, str] = {
    "filesystem.read": "read files the user selects",
    "filesystem.write": "write files to locations the user selects",
    "network.http": "make outbound HTTP requests",
    "network.raw": "open raw sockets",
    "database.query": "execute queries on configured connections",
    "database.schema": "read and modify table structure",
    "clipboard.read": "read the system clipboard",
    "clipboard.write": "write to the system clipboard",
    "config.read": "read application settings",
    "config.write": "change application settings",
    "ui.menu": "add entries to application menus",
    "ui.dialog": "show dialogs and prompts",
    "notification.send": "send notifications to the user",
    "credentials.read": "read stored connection passwords",
}

#: hook name -> permissions it requires.  The manager consults this before
#: wiring a hook, so a plugin that declares nothing cannot register a hook
#: that talks to the database even if it returns one.
HOOK_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "get_export_formats": ("filesystem.write",),
    "get_mask_rules": (),
    "get_notification_backends": ("notification.send",),
    "get_connection_providers": ("database.query",),
    "get_sql_dialects": ("database.query",),
    "get_result_actions": ("ui.menu",),
    "get_settings_pages": ("config.read", "ui.dialog"),
    "get_commands": ("ui.menu",),
}


def normalize_permissions(requested: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Validate and de-duplicate a manifest's permission list.

    Raises :class:`PluginPermissionError` on the first unknown name -- the
    caller cannot tell a typo from an attempt to smuggle in a capability, so
    it must fail rather than guess.
    """
    out: list[str] = []
    for item in requested:
        name = item.strip()
        if name not in PERMISSION_CATALOG:
            raise PluginPermissionError(f"unknown permission {name!r}")
        if name not in out:
            out.append(name)
    return tuple(out)


def check_hook_permissions(
    hook: str,
    granted: tuple[str, ...],
    plugin_id: str,
) -> None:
    """Raise if ``hook`` needs a permission ``plugin_id`` was not granted.

    Called by the manager right before wiring a hook; the message names both
    the plugin and the missing permission so the log tells the user exactly
    what to add to the manifest.
    """
    needed = HOOK_PERMISSIONS.get(hook)
    if not needed:
        return
    missing = [p for p in needed if p not in granted]
    if missing:
        raise PluginPermissionError(
            f"plugin {plugin_id} may not register {hook}: "
            f"missing permission(s) {', '.join(missing)}"
        )
