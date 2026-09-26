"""Sphinx configuration for the kilocode-client documentation."""

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "kilocode-client"
copyright = "2026, Kilo Code client"
author = "Kilo Code client"
release = "0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}

autodoc_typehints = "description"

always_document_param_types = True
typehints_defaults = "comma"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

html_theme = "furo"
html_static_path = ["_static"]
html_title = "kilocode-client"

root_doc = "index"
