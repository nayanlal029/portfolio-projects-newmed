#!/usr/bin/env python3
"""
Site assembler for the NewMed case-study hub.

The two products are developed under products/ (each is a complete, standalone
project with its own data pipeline and docs). This script copies each product's
app/ build into the site routes (/copilot, /ops) and injects a link back to the
hub so the deployed pages feel like one site.

Run after changing anything under products/:  python3 build_site.py
"""
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
COPIES = [
    ("products/denial-prevention-copilot/app", "copilot"),
    ("products/ops-bottleneck-analyzer/app", "ops"),
]
HUB_LINK = ' · <a class="softlink" href="../">NewMed case-study hub</a>'
FOOTER_MARK = "product prototype by Nayan Lal"


def main():
    for src, dst in COPIES:
        src_abs, dst_abs = os.path.join(ROOT, src), os.path.join(ROOT, dst)
        if os.path.isdir(dst_abs):
            shutil.rmtree(dst_abs)
        shutil.copytree(src_abs, dst_abs)
        index = os.path.join(dst_abs, "index.html")
        html = open(index).read()
        if FOOTER_MARK in html and "case-study hub" not in html:
            html = html.replace(FOOTER_MARK, FOOTER_MARK + HUB_LINK, 1)
            open(index, "w").write(html)
        print(f"{src} -> {dst}/")
    print("Site assembled. Serve locally:  python3 -m http.server 8803")


if __name__ == "__main__":
    main()
