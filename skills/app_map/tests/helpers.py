"""Temp repos for the app map tests: the made-up acme/shop project only."""
import os
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    "-C", str(repo), *args], check=True, capture_output=True)


def write(repo: Path, rel: str, text: str = "x\n") -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def init(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    return repo


def add_all(repo: Path, commit: bool = False) -> None:
    git(repo, "add", ".")
    if commit:
        git(repo, "commit", "-q", "-m", "init")


def gradle_repo(root: Path) -> Path:
    repo = init(root / "shop")
    write(repo, "settings.gradle", "rootProject.name = 'shop'\ninclude ':core', ':orders'\ninclude(\":web\")\n")
    write(repo, "orders/build.gradle",
          "dependencies {\n  implementation project(':core')\n  testImplementation project(\":web\")\n}\n")
    write(repo, "web/build.gradle.kts", "dependencies {\n  implementation(projects.orders)\n}\n")
    write(repo, "core/build.gradle", "")
    write(repo, "core/src/main/java/com/acme/core/Util.java")
    write(repo, "orders/src/main/java/com/acme/orders/Order.java")
    write(repo, "orders/src/main/java/com/acme/orders/Cart.java")
    write(repo, "web/src/main/java/com/acme/web/Page.java")
    return repo


def maven_repo(root: Path) -> Path:
    repo = init(root / "mshop")
    write(repo, "pom.xml", "<project xmlns=\"http://maven.apache.org/POM/4.0.0\"><groupId>com.acme</groupId>"
                           "<artifactId>shop-parent</artifactId><packaging>pom</packaging>"
                           "<modules><module>shop-core</module><module>shop-app</module></modules></project>")
    write(repo, "shop-core/pom.xml", "<project><parent><groupId>com.acme</groupId><artifactId>shop-parent</artifactId>"
                                     "</parent><artifactId>shop-core</artifactId></project>")
    write(repo, "shop-app/pom.xml",
          "<project><parent><groupId>com.acme</groupId><artifactId>shop-parent</artifactId></parent>"
          "<artifactId>shop-app</artifactId><dependencies>"
          "<dependency><groupId>com.acme</groupId><artifactId>shop-core</artifactId></dependency>"
          "<dependency><groupId>com.acme</groupId><artifactId>shop-core</artifactId><scope>test</scope></dependency>"
          "<dependency><groupId>org.other</groupId><artifactId>lib</artifactId></dependency>"
          "</dependencies></project>")
    write(repo, "shop-core/src/main/java/com/acme/core/A.java")
    write(repo, "shop-app/src/main/java/com/acme/app/B.java")
    write(repo, "shop-app/src/main/java/com/acme/app/C.java")
    return repo
