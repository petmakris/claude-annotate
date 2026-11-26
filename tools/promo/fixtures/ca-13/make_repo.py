"""make_repo.py <dest>: build the invented `shop` repo the ca-13 app map is drawn from.

Thirteen Gradle modules of a made-up web shop, a CODEOWNERS file with four
invented teams, and one commit by Dana Example at a fixed date, so the file
counts and the sha are the same on every run. Nothing here is a real project.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# module folder -> (package folders with their file counts)
MODULES = {
    "storefront": {"pages": 9, "components": 14},
    "mobile-api": {"routes": 7, "dto": 6},
    "admin": {"screens": 8},
    "catalog": {"products": 11, "categories": 4, "search": 5},
    "cart": {"cart": 8},
    "accounts": {"accounts": 9},
    "pricing": {"rules": 10},
    "checkout": {"flow": 6, "payment": 7, "retry": 3, "receipts": 4},
    "orders": {"place": 6, "track": 5, "returns": 5, "refunds": 3},
    "pay-gateway": {"client": 5},
    "inventory": {"stock": 7},
    "shipping": {"carriers": 6},
    "notify": {"mail": 4, "push": 3},
}

# user module -> the modules it uses (Gradle `implementation project(...)`)
USES = {
    "storefront": ["catalog", "cart"],
    "mobile-api": ["accounts"],
    "admin": ["orders"],
    "catalog": ["pricing"],
    "cart": ["pricing", "checkout"],
    "checkout": ["pay-gateway", "inventory"],
    "orders": ["shipping", "notify"],
}

ROLES = ["Service", "Controller", "Repository", "Mapper", "Policy", "Handler", "Client", "Config",
         "Event", "Request", "Response", "Validator", "Job", "Store"]

CODEOWNERS = """\
/storefront/   @acme/web
/mobile-api/   @acme/web
/admin/        @acme/web
/catalog/      @acme/catalog
/cart/         @acme/checkout
/checkout/     @acme/checkout
/orders/       @acme/checkout
/accounts/     @acme/platform
/pricing/      @acme/catalog
/inventory/    @acme/platform
/notify/       @acme/platform
/pay-gateway/  @acme/checkout
/shipping/     @acme/platform
"""


def main():
    dest = Path(sys.argv[1])
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "settings.gradle").write_text(
        "rootProject.name = 'shop'\n" + "".join(f"include '{m}'\n" for m in MODULES))
    (dest / "CODEOWNERS").write_text(CODEOWNERS)
    for mod, pkgs in MODULES.items():
        base = dest / mod
        (base).mkdir()
        deps = "".join(f"    implementation project(':{u}')\n" for u in USES.get(mod, []))
        (base / "build.gradle").write_text("plugins { id 'java' }\ndependencies {\n" + deps + "}\n")
        for pkg, n in pkgs.items():
            d = base / "src/main/java/com/acme/shop" / mod.replace("-", "") / pkg
            d.mkdir(parents=True)
            for i in range(n):
                (d / f"{pkg.capitalize()}{ROLES[i]}.java").write_text(
                    f"package com.acme.shop.{mod.replace('-', '')}.{pkg};\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="Dana Example", GIT_AUTHOR_EMAIL="dana@example.com",
               GIT_COMMITTER_NAME="Dana Example", GIT_COMMITTER_EMAIL="dana@example.com",
               GIT_AUTHOR_DATE="2026-03-02T09:00:00Z", GIT_COMMITTER_DATE="2026-03-02T09:00:00Z")
    run = lambda *a: subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=dest, env=env,
                                    check=True, stdout=subprocess.DEVNULL)
    run("init", "-q", "-b", "main")
    run("add", "-A")
    run("commit", "-q", "-m", "shop: thirteen modules")
    print(dest)


if __name__ == "__main__":
    main()
