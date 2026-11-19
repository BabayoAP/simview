"""Altitude hold as a block diagram (`altitude.svd`), the same loop as `script.py`.

simview examples/drone_altitude/blocks.py      # the Diagram tab shows the loop
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import RATE, make_scene  # noqa: E402

scene = make_scene()
scene.add_diagram("altitude.svd", rate=RATE)
