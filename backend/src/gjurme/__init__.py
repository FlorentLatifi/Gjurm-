"""GJURMË — AI-powered Albanian & Balkan news intelligence."""

import os

# The release this process runs: the git SHA CI builds into the image (GJURME_VERSION), so
# /api/v1/status and deploy.sh can tell which release is answering. The package version outside
# an image.
__version__ = os.environ.get("GJURME_VERSION") or "1.0.0"
