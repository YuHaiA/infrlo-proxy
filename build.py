"""Run the complete build inside the hosting platform's build container."""
from pathlib import Path
import subprocess
import sys

from install_xray import main as install_xray


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(root / "requirements.txt")], cwd=root, check=True)
    install_xray()
