"""MUST BE REFUSED: this file imports a helper beside it, and the helper imports the package."""
import probe_helper

print(probe_helper.answer())
