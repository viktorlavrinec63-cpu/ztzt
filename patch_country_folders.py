
# patch_country_folders.py
from __future__ import annotations
import os, re, sys

ROOT = os.path.dirname(__file__)
PATH = os.path.join(ROOT, "bazos_bot.py")

MAPPING_BLOCK = 