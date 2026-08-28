"""
Makes `import app...` work no matter where pytest is invoked from
(repo root, backend/, or backend/tests/). pytest walks conftest.py
files from rootdir down to the test file, so this gets picked up
automatically and inserts backend/ onto sys.path before collection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))