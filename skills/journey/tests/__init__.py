"""Pin the journey tool's settings to the repo's own example, so no config of yours under ~ reaches the tests."""
import os
from pathlib import Path

os.environ["JOURNEY_CONFIG"] = os.devnull
os.environ["JOURNEY_APPS"] = str(Path(__file__).resolve().parents[1] / "apps.example.json")
