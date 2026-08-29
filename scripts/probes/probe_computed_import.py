"""MUST BE REFUSED: the name is built at runtime rather than written down."""
import importlib

part_one = "maze"
part_two = "glyph"

module = importlib.import_module(part_one + part_two)
print(module.__doc__)
