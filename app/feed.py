import json
import httpx
import sys
import time
from pathlib import Path

VESPA_URL = "http://localhost:8080"
DATA_FILE = Path(__file__).parent.parent / "data" / "products.json"
APP_PACKAGE = Path(__file__).parent.parent / "vespa-app"


def wait_for_vespa():
    print("waiting for vespa to be ready...")
    for i in range(30):
        try:
            r = httpx.get(f"{VESPA_URL}/state/v1/health", timeout=5)
            if r.status_code == 200:
                print("vespa is up!")
                return True
        except httpx.ConnectError:
            pass
        time.sleep(2)
    print("vespa didn't come up in time, giving up")
    return False


def deploy_app():
    """Deploy the vespa application package."""
    print("deploying vespa app package...")

    import subprocess
    import tempfile
    import os

    # create a zip of the app package
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            ["tar", "-C", str(APP_PACKAGE), "-czf", tmp_path, "."],
            check=True,
            capture_output=True,
        )

        with open(tmp_path, "rb") as f:
            r = httpx.post(
                "http://localhost:19071/application/v2/tenant/default/prepareandactivate",
                content=f.read(),
                headers={"Content-Type": "application/x-gzip"},
                timeout=30,
            )

        if r.status_code == 200:
            print("app deployed successfully!")
            # give vespa a moment to activate
            print("waiting for config to propagate...")
            time.sleep(10)
            return True
        else:
            print(f"deploy failed: {r.status_code} {r.text}")
            return False
    finally:
        os.unlink(tmp_path)


def feed_products():
    with open(DATA_FILE) as f:
        products = json.load(f)

    print(f"feeding {len(products)} products...")
    success = 0
    failed = 0

    for product in products:
        doc_id = product["id"]
        fields = {k: v for k, v in product.items() if k != "id"}

        r = httpx.post(
            f"{VESPA_URL}/document/v1/default/product/docid/{doc_id}",
            json={"fields": fields},
            timeout=10,
        )

        if r.status_code == 200:
            success += 1
        else:
            failed += 1
            print(f"  failed to feed product {doc_id}: {r.status_code} {r.text}")

    print(f"done! {success} succeeded, {failed} failed")


def main():
    if not wait_for_vespa():
        sys.exit(1)

    if not deploy_app():
        sys.exit(1)

    feed_products()


if __name__ == "__main__":
    main()
