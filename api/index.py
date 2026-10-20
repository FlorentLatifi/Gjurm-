"""Vercel entry point: GJURMË's API as one Python function (docs/DECISIONS.md, ADR-027).

vercel.json sends /api/*, /health*, /sitemap.xml and link-preview crawlers' /stories/{id} here;
every other path is the static app built from frontend/. The pipeline does not run here: the
"Free hosting" GitHub workflow runs it every 30 minutes against the same database.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from gjurme.api.serverless import VercelPaths, serverless_defaults  # noqa: E402

os.environ.update(serverless_defaults(os.environ))

from gjurme.api.app import create_app  # noqa: E402

app = VercelPaths(create_app())
