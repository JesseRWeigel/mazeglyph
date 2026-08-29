"""MUST BE ACCEPTED: standard library only, and a local helper that is also clean."""
import json

import probe_clean_helper

print(json.dumps({"helper": probe_clean_helper.value()}))
