"""Download the original MLG-ULB benchmark from Kaggle."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

SOURCE = json.loads(Path(__file__).with_name("source.json").read_text(encoding="utf-8"))
URL = SOURCE["download_url"]
TARGET = Path(__file__).with_name("creditcard.csv")

if __name__ == "__main__":
    if TARGET.exists():
        print(f"Already present: {TARGET}")
    else:
        with tempfile.TemporaryDirectory(dir=TARGET.parent) as folder:
            archive = Path(folder) / "dataset.zip"
            copy = Path(folder) / TARGET.name
            with urlopen(Request(URL, headers={"User-Agent": "EGZH8-Education"}), timeout=45) as response:
                with archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
            with ZipFile(archive) as source:
                with source.open(TARGET.name) as csv, copy.open("wb") as output:
                    shutil.copyfileobj(csv, output)
            digest = hashlib.sha256()
            with copy.open("rb") as csv:
                for block in iter(lambda: csv.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != SOURCE["sha256"]:
                raise ValueError(f"Unexpected SHA-256: {digest.hexdigest()}")
            copy.replace(TARGET)
        print(TARGET)
