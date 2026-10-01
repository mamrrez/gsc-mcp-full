"""gsc-mcp-full — a Google Search Console MCP server that understands every language.

The package is split into layers that do not know about each other:

- ``i18n``     pure-Python multilingual query normalisation (no network, no deps)
- ``analysis`` pure functions over Search Analytics rows
- ``store``    the local SQLite history that outlives Google's 16-month window
- ``client``   the thin HTTP layer over the Search Console API
- ``auth``     OAuth / service-account credentials, read-only by default
- ``server``   the MCP tools, which only glue the layers above together
"""

__version__ = "0.2.1"
