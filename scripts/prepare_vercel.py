"""Copy the built UI into the static directory expected by Vercel."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
built = root / "app" / "static"
output = root / "dist"
if not (built / "index.html").is_file():
    raise SystemExit("Build the frontend first: npm ci && npm run build")
if output.exists():
    shutil.rmtree(output)
output.mkdir()
shutil.copy2(built / "index.html", output / "index.html")
shutil.copytree(built, output / "assets")
shutil.copy2(built / "sw.js", output / "sw.js")
print("Prepared Vercel static files in dist/")
