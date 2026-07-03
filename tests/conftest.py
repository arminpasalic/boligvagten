"""Make the repo root importable (sources/, filters, monitor) without packaging."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
