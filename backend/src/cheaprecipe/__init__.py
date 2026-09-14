"""cheaprecipe — recipes curated from reduced-price grocery offers."""

import logging

# A library must not configure logging; the application entry point does that
# (see pipeline.main). This only stops "no handler" warnings when it doesn't.
logging.getLogger(__name__).addHandler(logging.NullHandler())
