# Configuration file for Sphinx documentation

project = 'libdnf-p2p-sharing'
copyright = '2024, libdnf-p2p-sharing contributors'
author = 'libdnf-p2p-sharing contributors'
version = '0.3'
release = '0.3.3'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
]

html_theme = 'alabaster'
master_doc = 'index'

man_pages = [
    (master_doc, 'libdnf-p2p-sharing', 'libdnf-p2p-sharing Documentation',
     [author], 8)
]

