"""The page renderer — the one module a frontend rewrite touches.

The rendering boundary ruling (step 6): everything presentational lives in
this package — templates, static assets, view-model helpers — and it consumes
only the published serving surfaces (the ``Report`` contract, the JSON/SSE
routes) exactly as an external frontend would. The composition root attaches
it over the JSON app, so the dependency arrow points one way: this package
imports the contracts; ``serve.app`` never learns a renderer exists. Swapping
the frontend later means replacing this package, nothing below it.
"""

from steamlens.serve.web.pages import attach_web
from steamlens.serve.web.view import ReportPageData

__all__ = ["ReportPageData", "attach_web"]
