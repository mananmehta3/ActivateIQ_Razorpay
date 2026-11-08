"""Load the Data Pack and the config."""
from pathlib import Path
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=ROOT / "config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def load_data(cfg):
    path = ROOT / cfg["data_path"]
    apps = pd.read_excel(path, sheet_name="P3_Applications").dropna(how="all")
    catalog = pd.read_excel(path, sheet_name="P3_RejectionCatalog").dropna(how="all")
    return apps, catalog.set_index("code")
