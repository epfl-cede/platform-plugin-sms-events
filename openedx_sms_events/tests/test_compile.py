"""
Byte-compile every module in the package.

``signals.py`` imports ``xmodule`` / ``opaque_keys`` at module level, so it is
never imported during the unit-test run (the test settings deliberately do not
install the app, and the signal tests skip outside the openedx image). That
means a syntax error in ``signals.py`` would slip through the suite unnoticed.
This test guards against that by byte-compiling every ``.py`` in the package,
so a broken module fails the suite regardless of whether it is importable.
"""

import os

import pkgutil

import openedx_sms_events


def _package_py_files():
    """Yield the path of every ``.py`` file shipped in the package."""
    pkg_dir = os.path.dirname(openedx_sms_events.__file__)
    for dirpath, _dirs, files in os.walk(pkg_dir):
        # Skip bytecode caches.
        if "__pycache__" in dirpath:
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_all_package_modules_compile():
    """Every ``.py`` in the package must byte-compile (no syntax errors)."""
    import py_compile

    errors = []
    for path in sorted(_package_py_files()):
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{path}: {exc}")
    assert not errors, "syntax errors in package modules:\n" + "\n".join(errors)


# Sanity check: we are actually scanning the package, not an empty tree.
def test_finds_signals_module():
    paths = list(_package_py_files())
    assert any(p.endswith(os.path.join("openedx_sms_events", "signals.py")) for p in paths)
