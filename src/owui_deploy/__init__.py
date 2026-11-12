"""owui-deploy: lint, plan and apply Open WebUI Tools and Functions from a git folder."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("owui-deploy")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
