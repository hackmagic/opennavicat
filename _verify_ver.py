"""Verify versions match."""
import re

from open_navicat import __version__
print("Code __version__:", __version__)

v = re.findall(r'version\s*=\s*"(.+?)"', open("pyproject.toml").read())
print("pyproject.toml:", v[0])

for fn in ["version_info.txt", "version_info_cli.txt"]:
    c = open(fn).read()
    filever = re.findall(r"FileVersion', u'([^']+)'", c)
    prodver = re.findall(r"ProductVersion', u'([^']+)'", c)
    ffi = re.findall(r"filevers=\((.+?)\)", c)
    print(f"{fn}: filevers=({ffi[0]}) FileVersion={filever[0]} ProductVersion={prodver[0]}")
