"""MUST BE REFUSED: the name comes from somewhere this checker cannot follow.

A walk that gave up here and said nothing would be a walk any file could get past by building its
import name out of something opaque. Not knowing where a call goes is not the same as knowing it
goes somewhere harmless.
"""
import importlib
import os

module = importlib.import_module(os.environ.get("WHICHEVER", "json"))
print(module)
