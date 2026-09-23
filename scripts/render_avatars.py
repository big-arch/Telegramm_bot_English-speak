"""Rasterise the persona portraits to JPEG for Telegram.

Telegram will not send an SVG as a photo, so the chat needs raster images while the Mini
App uses the SVGs directly. JPEG rather than PNG because the film grain that
makes them look printed is exactly what PNG compresses worst — 750 KB each
against about a sixth of that. They are committed rather than generated at
start-up: rendering needs a headless browser, and a production container that
ships Chromium to draw seven pictures once is a bad trade.

Run after changing bot/webapp/avatars.py:

    python -m scripts.render_avatars

Needs node with the playwright package, and a Chromium it can find
(PLAYWRIGHT_BROWSERS_PATH). Both exist in the development container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "personas"

# Kept tiny and in node on purpose: the Python playwright package is a heavy
# dependency for something that runs on a developer's machine a few times a
# year, and node's is already present wherever this is likely to run.
RENDER_JS = r"""
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const jobs = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 800, height: 800 } });
  for (const job of jobs) {
    await page.setContent(
      `<html><body style="margin:0">${job.svg}</body></html>`,
      { waitUntil: "load" },
    );
    await page.screenshot({ path: job.out, type: "jpeg", quality: 90, clip: { x: 0, y: 0, width: 800, height: 800 } });
    console.log("rendered", job.out);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _playwright_module() -> str:
    """Where node can find playwright: local, or the global install."""
    node_root = subprocess.run(
        ["npm", "root", "-g"], capture_output=True, text=True, check=False
    ).stdout.strip()
    candidate = Path(node_root) / "playwright"
    return str(candidate) if candidate.exists() else "playwright"


def main() -> int:
    os.environ.setdefault("BOT_TOKEN", "0:render-only")
    sys.path.insert(0, str(ROOT))
    from bot import personas
    from bot.webapp import avatars

    if shutil.which("node") is None:
        print("node is required to render the portraits", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        {"svg": avatars.svg(p.key, p.name), "out": str(OUT / f"{p.key}.jpg")}
        for p in personas.PERSONAS
    ]

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "render.js"
        data = Path(tmp) / "jobs.json"
        script.write_text(RENDER_JS)
        data.write_text(json.dumps(jobs))
        env = {**os.environ, "PLAYWRIGHT_MODULE": _playwright_module()}
        result = subprocess.run(["node", str(script), str(data)], env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
