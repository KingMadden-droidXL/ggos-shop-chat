#!/usr/bin/env python3
"""Refresh the shop chat knowledge file from the live Shopify store.

Reads ACTIVE products via the Muse Shopify connector CLI (paginated),
writes data/shop_knowledge.json with title, handle, price, sizes and URL
for every live listing. Draft/archived products are left out on purpose:
the chat widget must never sell something that is not live.

The Heartless 575 tee (gid://shopify/Product/15400019525939) is flagged
contested: its listing carries two different designs and the description
matches neither, so the chat answers it with a "check with Gavin" note
instead of a buy push. Do not remove that flag without his eyes on the
listing first.

Usage:
    python3 scripts/refresh_shop_knowledge.py [--cli /opt/hatch/bin/shopify]
    python3 scripts/refresh_shop_knowledge.py --input page1.json page2.json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "shop_knowledge.json"
SHOP = "noloveappeal575.myshopify.com"

# Do not present this listing as a settled product.
CONTESTED_IDS = {"gid://shopify/Product/15400019525939"}  # Heartless 575 tee

QUERY = """query($after: String) {
  products(first: 100, after: $after) {
    edges { node { id title handle status
      variants(first: 25) { edges { node { price title } } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""


def run_cli(cli: str, after=None):
    args = {"query": QUERY, "variables": {"after": after}}
    proc = subprocess.run(
        [cli, "call-tool", "--name", "graphql_query",
         "--arguments-json", json.dumps(args)],
        capture_output=True, text=True, check=True,
    )
    outer = json.loads(proc.stdout)
    text = outer["result"]["content"][1]["text"]
    return json.loads(text)["data"]["products"]


def load_file(path):
    outer = json.load(open(path))
    text = outer["result"]["content"][1]["text"]
    return json.loads(text)["data"]["products"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default="/opt/hatch/bin/shopify")
    ap.add_argument("--input", nargs="*", default=[])
    args = ap.parse_args()

    pages = []
    if args.input:
        for p in args.input:
            pages.append(load_file(p))
    else:
        page = run_cli(args.cli)
        pages.append(page)
        while page["pageInfo"]["hasNextPage"]:
            page = run_cli(args.cli, after=page["pageInfo"]["endCursor"])
            pages.append(page)

    products = []
    seen = set()
    for page in pages:
        for edge in page["edges"]:
            node = edge["node"]
            if node["status"] != "ACTIVE":
                continue
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            variants = [v["node"] for v in node["variants"]["edges"]]
            prices = [float(v["price"]) for v in variants if v.get("price")]
            sizes = [v["title"] for v in variants
                     if v["title"] not in ("Default Title",)]
            products.append({
                "id": node["id"],
                "title": node["title"],
                "handle": node["handle"],
                "price": f"{min(prices):.2f}" if prices else None,
                "sizes": sizes,
                "url": f"https://{SHOP}/products/{node['handle']}",
                "contested": node["id"] in CONTESTED_IDS,
            })

    products.sort(key=lambda p: p["title"].lower())
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shop": SHOP,
        "product_count": len(products),
        "products": products,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {OUT} — {len(products)} live products")
    contested = [p["title"] for p in products if p["contested"]]
    if contested:
        print("Contested (check-with-Gavin): " + ", ".join(contested))


if __name__ == "__main__":
    sys.exit(main())
