# -*- coding: utf-8 -*-
# Test suite global sandbox fixture. Strictly zero emojis.

try:
    from . import sandbox  # noqa: F401
except ImportError:
    import sandbox  # noqa: F401
