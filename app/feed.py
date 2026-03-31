from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from app.config import settings

DATA_FILE = Path(__file__).parent.parent / "data" / "products.json"
APP_PACKAGE = Path(__file__).parent.parent / "vespa-app"


def wait_for_config_server() -> bool:
    """Wait for the config server (19071) to be ready."""
    print("waiting for vespa config server...")
    for _i in range(60):
        try:
            r = httpx.get(
                f"{settings.vespa_config_url}/state/v1/health",
                timeout=settings.vespa_state_timeout_s,
            )
            if r.status_code == 200:
                print("config server is up!")
                return True
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
            pass
        time.sleep(2)
    print("config server didn't come up in time")
    return False


def deploy_app() -> bool:
    """Deploy the vespa application package via config server."""
    print("deploying vespa app package...")

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            ["tar", "-C", str(APP_PACKAGE), "-czf", tmp_path, "."],
            check=True,
            capture_output=True,
        )

        with open(tmp_path, "rb") as f:
            r = httpx.post(
                f"{settings.vespa_config_url}/application/v2/tenant/default/prepareandactivate",
                content=f.read(),
                headers={"Content-Type": "application/x-gzip"},
                timeout=60,
            )

        if r.status_code == 200:
            print("app deployed successfully!")
            return True
        else:
            print(f"deploy failed: {r.status_code} {r.text}")
            return False
    finally:
        os.unlink(tmp_path)


def wait_for_search_container() -> bool:
    """Wait for the search container (8080) to come up after deploy."""
    print("waiting for search container to start (this can take a minute)...")
    for _i in range(90):
        try:
            r = httpx.get(
                f"{settings.vespa_url}/state/v1/health",
                timeout=settings.vespa_state_timeout_s,
            )
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", {}).get("code", "")
                if status == "up":
                    print("search container is ready!")
                    return True
                else:
                    print(f"  status: {status}, waiting...")
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
            pass
        time.sleep(3)
    print("search container didn't come up in time")
    return False


def feed_products() -> None:
    with open(DATA_FILE) as f:
        products = json.load(f)

    print(f"feeding {len(products)} products...")
    success = 0
    failed = 0

    for product in products:
        doc_id = product["id"]
        fields = {k: v for k, v in product.items() if k != "id"}

        try:
            r = httpx.post(
                f"{settings.vespa_url}/document/v1/default/product/docid/{doc_id}",
                json={"fields": fields},
                timeout=settings.http_timeout_s,
            )

            if r.status_code == 200:
                success += 1
            else:
                failed += 1
                print(f"  failed product {doc_id}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            failed += 1
            print(f"  error feeding product {doc_id}: {e}")

    print(f"done! {success} succeeded, {failed} failed")


def main() -> None:
    if not wait_for_config_server():
        sys.exit(1)

    if not deploy_app():
        sys.exit(1)

    if not wait_for_search_container():
        sys.exit(1)

    feed_products()


if __name__ == "__main__":
    main()
