"""One-command local launcher. Uses only Python's standard library to bootstrap."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".venv-run"
PYTHON = RUNTIME / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(args, *, cwd=ROOT, env=None):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True, env=env)


def fingerprint(paths):
    digest = hashlib.sha256(str(ROOT).encode())
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Install dependencies, build UI and start Teren Oi.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Install/build without starting a server")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ is required: https://www.python.org/downloads/")
    if not 1 <= args.port <= 65535:
        raise RuntimeError("Port must be between 1 and 65535.")
    node, npm = shutil.which("node"), shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise RuntimeError("Install Node.js 22.12+ (includes npm), then run START.bat again: https://nodejs.org/en/download")
    version = json.loads(subprocess.check_output([node, "-p", "JSON.stringify(process.versions.node.split('.').map(Number))"], text=True))
    if version[0] < 22 or (version[0] == 22 and version[1] < 12):
        raise RuntimeError("Node.js 22.12+ is required. Update Node.js and retry.")
    if not args.prepare_only:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", args.port))
            except OSError as exc:
                raise RuntimeError(f"Port {args.port} is busy. Close the previous launcher or use --port 8766.") from exc

    if not PYTHON.exists():
        print("[1/3] Creating an isolated Python environment...", flush=True)
        run([sys.executable, "-m", "venv", RUNTIME])
    dependency_hash = fingerprint([ROOT / "pyproject.toml", ROOT / "constraints.txt"])
    stamp = RUNTIME / ".dependencies.sha256"
    if not stamp.exists() or stamp.read_text() != dependency_hash:
        print("[1/3] Installing Python libraries (first start needs internet)...", flush=True)
        run([PYTHON, "-m", "pip", "install", "-c", "constraints.txt", "-e", "."])
        stamp.write_text(dependency_hash)

    frontend = ROOT / "frontend"
    build_dir = RUNTIME / "frontend"
    build_dir.mkdir(exist_ok=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(frontend / name, build_dir / name)
    npm_hash = fingerprint([frontend / "package.json", frontend / "package-lock.json"])
    npm_stamp = RUNTIME / ".npm.sha256"
    if not (build_dir / "node_modules").exists() or not npm_stamp.exists() or npm_stamp.read_text() != npm_hash:
        print("[2/3] Installing UI libraries...", flush=True)
        run([npm, "ci"], cwd=build_dir)
        npm_stamp.write_text(npm_hash)
    build_files = list(frontend.glob("*.json")) + [frontend / "index.html", frontend / "vite.config.ts"]
    build_files += [path for folder in ("src", "public") for path in (frontend / folder).rglob("*") if path.is_file()]
    build_hash = fingerprint(build_files)
    build_stamp = RUNTIME / ".ui.sha256"
    if not (build_dir / "dist/index.html").exists() or not build_stamp.exists() or build_stamp.read_text() != build_hash:
        print("[2/3] Building the interface...", flush=True)
        for source in frontend.glob("*"):
            if source.is_file() and (source.suffix == ".json" or source.name in ("index.html", "vite.config.ts")):
                shutil.copy2(source, build_dir / source.name)
        for name in ("src", "public"):
            target = build_dir / name
            if not target.resolve().is_relative_to(RUNTIME.resolve()):
                raise RuntimeError("Unexpected build path; refusing to replace files outside the runtime directory.")
            if target.exists():
                shutil.rmtree(target)
            if (frontend / name).exists():
                shutil.copytree(frontend / name, target)
        # Standalone mode always uses the API on this same server. Do not bake
        # a developer's optional remote VITE_API_BASE_URL into the jury build.
        run([npm, "run", "build"], cwd=build_dir, env={**os.environ, "VITE_API_BASE_URL": ""})
        build_stamp.write_text(build_hash)
    if args.prepare_only:
        print("Ready. Next launch can run without installation.")
        return

    url = f"http://127.0.0.1:{args.port}"
    print(f"[3/3] Starting Teren Oi: {url}\nKeep this window open. Ctrl+C stops the application.", flush=True)
    process = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "teren_oi.web:app", "--host", "127.0.0.1", "--port", str(args.port)], cwd=ROOT,
                               env={**os.environ, "TEREN_UI_DIST": str(build_dir / "dist")})
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("API exited during startup. Read the error above.")
            try:
                with urlopen(f"{url}/api/health", timeout=1) as response:
                    ready = response.status == 200
                if ready:
                    if not args.no_browser:
                        webbrowser.open(url)
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Server startup timed out. Read the error above and retry.")
        if process.wait() != 0:
            raise RuntimeError("The application stopped with an error.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTeren Oi stopped.")
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"\nStartup error: {exc}\nFix the issue and run the launcher again.", file=sys.stderr)
        sys.exit(1)
