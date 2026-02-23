# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
sys.path.insert(0, os.path.abspath('..'))

# Mock modules that use internal relative imports (for autodoc on RTD)
autodoc_mock_imports = [
    'printing', 'run_interface', 'script_editing', 'arch_xml_modification',
    'file_handling', 'csv_locations_generator', 'run_flow', 'split_top_module',
    'yaml_file_processing',
]

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'LaZagna'
copyright = '2026, Ismael Youssef'
author = 'Ismael Youssef'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",      # for Google/NumPy docstrings
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "myst_parser",              # for Markdown support
]

# Support both .rst and .md source files
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

# MyST-Parser configuration
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "tasklist",
]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"

html_theme_options = {
    'logo_only': False,
    'prev_next_buttons_location': 'bottom',
    'style_nav_header_background': '#2c3e50',
    'navigation_depth': 4,
}

# -- Logo configuration -----------------------------------------------------
html_logo = "_static/LaZagna_logo.png"

html_static_path = ['_static']

html_css_files = [
    'custom.css',
]

