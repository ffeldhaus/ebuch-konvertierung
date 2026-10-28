#!/usr/bin/env python3
"""
E-Buch Dependency & AI Model Freshness Checker (Husky Pre-Commit Hook)

Checks that all Python dependencies, Node/NPM packages, and local AI model weights
are up-to-date programmatically. Exits with code 1 to block commits if newer versions
exist, unless --warn-only or ALLOW_OUTDATED=1 is set.
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import importlib.metadata
from typing import Dict, List, Tuple, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Key Python dependencies to check
PYTHON_PACKAGES = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "python-docx",
    "pypdfium2",
    "docling",
    "mlx",
    "mlx-metal",
    "mlx-vlm",
    "pytest",
]

# Key NPM packages to check
NPM_PACKAGES = [
    "@playwright/test",
    "tailwindcss",
    "@tailwindcss/vite",
    "typescript",
    "vite",
    "husky",
]

# Local model repositories to check on Hugging Face
HF_MODELS = {
    "lightonocr-3-0.8b": {
        "repo_id": "lightonai/LightOnOCR-3-0.8B",
        "local_path": os.path.join(PROJECT_ROOT, "assets", "models", "lightonocr"),
    },
    "infinity-parser2-flash": {
        "repo_id": "infly/Infinity-Parser2-Flash",
        "local_path": os.path.join(PROJECT_ROOT, "assets", "models", "infinity_parser2_flash"),
    },
    "gemma-4-12b-it": {
        "repo_id": "google/gemma-4-12b-it",
        "local_path": os.path.join(PROJECT_ROOT, "assets", "models", "gemma"),
    }
}


def fetch_json(url: str, timeout: float = 5.0) -> Optional[dict]:
    """Fetches JSON from URL with timeout."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ebuch-dependency-checker/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def get_latest_pypi_version(package_name: str) -> Optional[str]:
    """Queries PyPI API for the latest released version."""
    data = fetch_json(f"https://pypi.org/pypi/{package_name}/json")
    if data and "info" in data and "version" in data["info"]:
        return data["info"]["version"]
    return None


def get_latest_npm_version(package_name: str) -> Optional[str]:
    """Queries NPM registry for the latest released version."""
    url = f"https://registry.npmjs.org/{package_name}/latest"
    data = fetch_json(url)
    if data and "version" in data:
        return data["version"]
    return None


def get_latest_hf_commit(repo_id: str) -> Optional[str]:
    """Queries Hugging Face API for the latest commit SHA."""
    data = fetch_json(f"https://huggingface.co/api/models/{repo_id}")
    if data and "sha" in data:
        return data["sha"]
    return None


# Packages pinned to specific versions due to peer dependency constraints:
# - mlx-vlm==0.7.2: required by rapid-mlx 0.4.2
# - typescript==5.9.3: required by @typescript-eslint (<6.0.0)
# - vite==5.4.21: required by @tailwindcss/vite peer range
COMPATIBILITY_PINNED_VERSIONS = {
    "fastapi": "0.155.0",
    "mlx-vlm": "0.7.2",
    "@playwright/test": "1.62.1",
    "typescript": "5.9.3",
    "vite": "5.4.21",
}


def check_python_dependencies() -> List[Dict[str, str]]:
    """Checks installed Python packages against PyPI."""
    outdated = []
    for pkg in PYTHON_PACKAGES:
        try:
            installed = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            continue

        if COMPATIBILITY_PINNED_VERSIONS.get(pkg) == installed:
            continue

        latest = get_latest_pypi_version(pkg)
        if latest and installed != latest:
            # Check if installed is older
            outdated.append({
                "type": "Python (PyPI)",
                "package": pkg,
                "installed": installed,
                "latest": latest,
                "action": f"pip install --upgrade {pkg}",
            })
    return outdated


def check_npm_dependencies() -> List[Dict[str, str]]:
    """Checks package.json dependencies against NPM registry."""
    outdated = []
    pkg_json_path = os.path.join(PROJECT_ROOT, "package.json")
    if not os.path.exists(pkg_json_path):
        return outdated

    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            pkg_data = json.load(f)
    except Exception:
        return outdated

    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
    
    for pkg in NPM_PACKAGES:
        installed_spec = deps.get(pkg)
        if not installed_spec:
            continue
        
        # Clean specifier (e.g. ^1.2.3 -> 1.2.3)
        installed = installed_spec.lstrip("^~>=<")
        if COMPATIBILITY_PINNED_VERSIONS.get(pkg) == installed:
            continue
        latest = get_latest_npm_version(pkg)
        if latest and installed != latest:
            outdated.append({
                "type": "Node (NPM)",
                "package": pkg,
                "installed": installed,
                "latest": latest,
                "action": f"npm install --save-dev {pkg}@latest",
            })
    return outdated


def check_ai_models() -> List[Dict[str, str]]:
    """Checks local AI model weights for upstream updates."""
    outdated = []
    for model_name, info in HF_MODELS.items():
        repo_id = info["repo_id"]
        local_dir = info["local_path"]
        
        latest_sha = get_latest_hf_commit(repo_id)
        if not latest_sha:
            continue

        version_file = os.path.join(local_dir, ".hf_commit_sha")
        local_sha = None
        if os.path.exists(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    local_sha = f.read().strip()
            except Exception:
                pass

        if local_sha and local_sha != latest_sha:
            outdated.append({
                "type": "AI Model (Hugging Face)",
                "package": model_name,
                "installed": local_sha[:8],
                "latest": latest_sha[:8],
                "action": f"huggingface-cli download {repo_id} --local-dir {local_dir}",
            })
    return outdated


def main():
    parser = argparse.ArgumentParser(description="Check for newer versions of dependencies and AI models.")
    parser.add_argument("--warn-only", action="store_true", help="Print warnings but do not exit with error")
    args = parser.parse_args()

    print("🔍 [E-Buch Pre-Commit] Checking for newer dependencies and AI models...")

    if os.environ.get("ALLOW_OUTDATED") == "1":
        print("⚠️ ALLOW_OUTDATED=1 detected. Skipping blocking check.")
        sys.exit(0)

    outdated_items = []
    
    # 1. Python packages
    py_outdated = check_python_dependencies()
    outdated_items.extend(py_outdated)

    # 2. Node packages
    npm_outdated = check_npm_dependencies()
    outdated_items.extend(npm_outdated)

    # 3. AI Models
    model_outdated = check_ai_models()
    outdated_items.extend(model_outdated)

    if not outdated_items:
        print("✅ [E-Buch Pre-Commit] All dependencies and AI models are up-to-date!")
        sys.exit(0)

    print("\n" + "=" * 80)
    print("🚨 [E-Buch Pre-Commit] BLOCKING COMMIT: Newer versions are available!")
    print("=" * 80)
    print(f"{'Ecosystem':<25} | {'Package / Model':<22} | {'Installed':<10} | {'Latest':<10}")
    print("-" * 80)
    for item in outdated_items:
        print(f"{item['type']:<25} | {item['package']:<22} | {item['installed']:<10} | {item['latest']:<10}")
    print("-" * 80)
    print("\n💡 Suggested Upgrade Commands:")
    for item in outdated_items:
        print(f"  • {item['action']}")
    print("\n⚠️ To bypass this check in an emergency, use: ALLOW_OUTDATED=1 git commit -m '...'")
    print("=" * 80 + "\n")

    if args.warn_only:
        print("⚠️ Running in --warn-only mode. Allowing commit.")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
