# file_crawler.py
"""File crawler for the Project‑Analysis pipeline inside the AI‑Studio server.

Loads the local `config.yaml` and yields file paths that match the configured extensions.
"""
import pathlib
import yaml
from typing import List, Generator

def load_config(config_path: str | None = None) -> dict:
    """Load the YAML configuration file."""
    path = pathlib.Path(config_path) if config_path else pathlib.Path(__file__).with_name("config.yaml")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_included_extensions(config: dict) -> List[str]:
    exts = config.get("include_extensions", "")
    return [e if e.startswith('.') else f'.{e}' for e in [e.strip() for e in exts.split(',') if e.strip()]]

def crawl_files(project_root: str, extensions: List[str]) -> Generator[str, None, None]:
    """Yield absolute file paths under *project_root* matching any of *extensions*.
    """
    root = pathlib.Path(project_root)
    for path in root.rglob('*.*'):
        if path.suffix.lower() in extensions:
            yield str(path)

if __name__ == "__main__":
    cfg = load_config()
    for fp in crawl_files(cfg["project_root"], get_included_extensions(cfg)):
        print(fp)
