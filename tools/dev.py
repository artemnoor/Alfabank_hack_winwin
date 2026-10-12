#!/usr/bin/env python3
"""Pinned local toolchain and PostgreSQL bootstrap for the AlfaBank framework."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "toolchain.lock.json"
LOCAL = ROOT / ".local" / "t00"
TOOLCHAIN_DIR = ROOT / ".local" / "toolchain"
DOWNLOAD_DIR = TOOLCHAIN_DIR / "downloads"
PYTHON_DIR = TOOLCHAIN_DIR / "python"
BIN_DIR = TOOLCHAIN_DIR / "bin"
NODE_DIR = TOOLCHAIN_DIR / "node"
RUNTIME_PATH = LOCAL / "runtime.json"
COMPOSE_FILE = ROOT / "compose.yaml"
MAX_ARCHIVE_BYTES = 160 * 1024 * 1024

if os.name == "nt":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class SetupError(RuntimeError):
    pass


def read_lock() -> dict:
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"Не удалось прочитать {LOCK_PATH.name}: {exc}") from exc
    return data


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def run(args: list[str], *, cwd: Path = ROOT, input_text: str | None = None,
        env: dict[str, str] | None = None, timeout: int = 120,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        if check:
            raise SetupError(f"Не удалось выполнить команду {Path(args[0]).name}: {exc}") from exc
        return subprocess.CompletedProcess(args, 127, "", str(exc))
    if result.returncode and check:
        raise SetupError(
            f"Команда {Path(args[0]).name} завершилась с кодом {result.returncode}. "
            "Подробный вывод может содержать данные окружения и не печатается."
        )
    return result


def version_text(binary: Path, *args: str) -> str:
    result = run([str(binary), *args], timeout=30)
    return result.stdout.strip() or result.stderr.strip()


def verify_spec_inputs(lock: dict, *, require_lockfiles: bool = True) -> None:
    expected = {
        ROOT / ".python-version": lock["python"]["version"],
        ROOT / ".node-version": lock["node"]["version"],
    }
    for path, version in expected.items():
        if not path.is_file() or path.read_text(encoding="utf-8").strip() != version:
            raise SetupError(f"{path.name} расходится с toolchain.lock.json")

    package = json.loads((ROOT / "apps" / "playground" / "package.json").read_text(encoding="utf-8"))
    if package.get("engines", {}).get("node") != f"={lock['node']['version']}":
        raise SetupError("Node.js version в package.json расходится с toolchain.lock.json")
    if package.get("engines", {}).get("npm") != f"={lock['node']['npm_version']}":
        raise SetupError("npm version в package.json расходится с toolchain.lock.json")
    if package.get("packageManager") != f"npm@{lock['node']['npm_version']}":
        raise SetupError("packageManager в package.json расходится с toolchain.lock.json")
    if require_lockfiles and not (ROOT / "apps" / "playground" / "package-lock.json").is_file():
        raise SetupError("Не найден apps/playground/package-lock.json")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if f'required-version = "=={lock["uv"]["version"]}"' not in pyproject:
        raise SetupError("uv required-version в pyproject.toml расходится с toolchain.lock.json")
    if require_lockfiles and not (ROOT / "uv.lock").is_file():
        raise SetupError("Не найден uv.lock")
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    if lock["postgres"]["image"] not in compose:
        raise SetupError("Образ PostgreSQL в compose.yaml расходится с toolchain.lock.json")
    if "127.0.0.1:" not in compose or "driver: bridge" not in compose:
        raise SetupError("PostgreSQL должен использовать отдельную bridge network и loopback binding")


def host_platform(lock: dict) -> tuple[str, dict]:
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        key = "windows-x64"
    elif sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        key = "linux-x64"
    else:
        raise SetupError(
            f"Для платформы {sys.platform}/{machine} T00 пока не закрепил проверенные бинарные архивы."
        )
    return key, lock["node"]["downloads"][key]


def uv_download(lock: dict) -> dict:
    key, archive = host_platform(lock)
    return key, archive, lock["uv"]["downloads"][key]


def secure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        whoami = run(["whoami.exe", "/user", "/fo", "csv", "/nh"], timeout=15)
        fields = whoami.stdout.strip().strip('"').split('","')
        sid = fields[-1].strip('"') if fields else ""
        if not sid.startswith("S-"):
            raise SetupError("Не удалось определить SID текущего пользователя для ACL .local/t00")
        acl = run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            timeout=15,
            check=False,
        )
        if acl.returncode:
            raise SetupError("Не удалось ограничить ACL каталога .local/t00")
    else:
        path.chmod(0o700)


def secure_secret_file(path: Path) -> None:
    if os.name == "nt":
        whoami = run(["whoami.exe", "/user", "/fo", "csv", "/nh"], timeout=15)
        fields = whoami.stdout.strip().strip('"').split('","')
        sid = fields[-1].strip('"') if fields else ""
        if not sid.startswith("S-"):
            raise SetupError("Не удалось проверить ACL секретного файла")
        acl = run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
            timeout=15,
            check=False,
        )
        if acl.returncode:
            raise SetupError("Не удалось ограничить ACL файла .local/t00")
    else:
        path.chmod(0o600)


def secret_value(name: str) -> str:
    path = LOCAL / name
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise SetupError(f"Секретный путь {path.name} не является обычным файлом")
        secure_secret_file(path)
        try:
            value = path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise SetupError(f"Не удалось прочитать локальный секрет {path.name}") from exc
        if len(value) < 40 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
            raise SetupError(f"Локальный секрет {path.name} имеет неверный формат; он не был заменён")
        return value

    value = secrets.token_urlsafe(48)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as secret_file:
        secret_file.write(value + "\n")
    secure_secret_file(path)
    return value


def download_verified(url: str, digest: str, filename: str) -> Path:
    if not url.startswith(("https://github.com/astral-sh/uv/releases/", "https://nodejs.org/dist/")):
        raise SetupError("URL скачивания отсутствует в разрешённом toolchain registry")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = DOWNLOAD_DIR / filename
    if destination.exists():
        if not destination.is_file() or destination.is_symlink():
            raise SetupError(f"Архив {filename} имеет небезопасный тип")
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == digest:
            return destination
        raise SetupError(f"Локальный архив {filename} не совпадает с закреплённым SHA-256; он сохранён")

    request = urllib.request.Request(url, headers={"User-Agent": "alfabank-framework-t00/1.0"})
    descriptor, partial_name = tempfile.mkstemp(prefix=destination.name + ".partial-", dir=DOWNLOAD_DIR)
    os.close(descriptor)
    partial = Path(partial_name)
    hasher = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise SetupError(f"Архив {filename} превышает установленный предел размера")
                hasher.update(chunk)
                output.write(chunk)
        if hasher.hexdigest() != digest:
            raise SetupError(f"Архив {filename} не прошёл проверку SHA-256; частичный файл сохранён")
        partial.replace(destination)
    except Exception:
        # Preserve a partial download for diagnosis; it is never used as an archive.
        raise
    return destination


def safe_archive_member(name: str, expected_root: str) -> tuple[str, ...] | None:
    if "\\" in name or ":" in name:
        raise SetupError("Архив содержит путь с разделителем или префиксом диска")
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts or not member.parts:
        raise SetupError("Архив содержит недопустимый путь")
    if member.parts[0] != expected_root:
        return None
    return member.parts


def install_uv(lock: dict) -> Path:
    key, archive, spec = uv_download(lock)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    executable_name = "uv.exe" if os.name == "nt" else "uv"
    executable = BIN_DIR / executable_name
    if executable.is_file():
        actual = version_text(executable, "--version")
        expected_target = "x86_64-pc-windows-msvc" if os.name == "nt" else "x86_64-unknown-linux-gnu"
        if actual.startswith(f"uv {lock['uv']['version']} (") and expected_target in actual:
            return executable
        raise SetupError(f"Локальный uv не соответствует закреплённой версии; файл сохранён: {actual}")

    archive_name = spec["url"].rsplit("/", 1)[-1]
    downloaded = download_verified(spec["url"], spec["sha256"], archive_name)
    if spec["format"] == "zip":
        with zipfile.ZipFile(downloaded) as bundle:
            candidates = [i for i in bundle.infolist() if PurePosixPath(i.filename).name == executable_name]
            if len(candidates) != 1:
                raise SetupError("В архиве uv нет единственного ожидаемого бинарного файла")
            info = candidates[0]
            if info.file_size > MAX_ARCHIVE_BYTES:
                raise SetupError("Бинарный файл uv превышает установленный предел размера")
            executable.write_bytes(bundle.read(info))
    elif spec["format"] == "tar.gz":
        with tarfile.open(downloaded, "r:gz") as bundle:
            members = [m for m in bundle.getmembers() if m.name == spec["binary"]]
            if len(members) != 1 or not members[0].isfile():
                raise SetupError("В архиве uv нет единственного ожидаемого бинарного файла")
            source = bundle.extractfile(members[0])
            if source is None:
                raise SetupError("Не удалось прочитать бинарный файл uv")
            executable.write_bytes(source.read(MAX_ARCHIVE_BYTES + 1))
            executable.chmod(0o755)
    else:
        raise SetupError("Для uv не поддержан формат архива")
    actual = version_text(executable, "--version")
    if not actual.startswith(f"uv {lock['uv']['version']} "):
        raise SetupError("Скачанный uv сообщил неожиданную версию")
    print(f"uv {lock['uv']['version']}: загружен и проверен SHA-256 ({key})")
    return executable


def install_node(lock: dict) -> tuple[Path, Path]:
    key, spec = host_platform(lock)
    install_dir = NODE_DIR / f"node-{lock['node']['version']}-{key}"
    node_binary = install_dir / spec["archive_root"] / spec["node_binary"]
    npm_cli = install_dir / spec["archive_root"] / spec["npm_cli"]
    if node_binary.is_file() and npm_cli.is_file():
        version = version_text(node_binary, "--version")
        npm_version = version_text(node_binary, str(npm_cli), "--version")
        if version == f"v{lock['node']['version']}" and npm_version == lock["node"]["npm_version"]:
            return node_binary, npm_cli
        raise SetupError("Локальная установка Node.js повреждена или не совпадает с pins; она сохранена")

    spec = lock["node"]["downloads"][key]
    archive_name = spec["url"].rsplit("/", 1)[-1]
    downloaded = download_verified(spec["url"], spec["sha256"], archive_name)
    NODE_DIR.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="node-extract-", dir=NODE_DIR))
    try:
        if spec["format"] == "zip":
            with zipfile.ZipFile(downloaded) as bundle:
                for info in bundle.infolist():
                    parts = safe_archive_member(info.filename, spec["archive_root"])
                    if parts is None or len(parts) == 1:
                        continue
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        continue
                    target = staging.joinpath(*parts)
                    if not path_is_within(target, staging):
                        raise SetupError("Архив Node.js вышел за пределы каталога установки")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        if info.file_size > MAX_ARCHIVE_BYTES:
                            raise SetupError("Файл в архиве Node.js превышает установленный предел")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(bundle.read(info))
        elif spec["format"] == "tar.xz":
            with tarfile.open(downloaded, "r:xz") as bundle:
                for member in bundle.getmembers():
                    parts = safe_archive_member(member.name, spec["archive_root"])
                    if parts is None or len(parts) == 1:
                        continue
                    if not (member.isdir() or member.isfile()):
                        continue
                    target = staging.joinpath(*parts)
                    if not path_is_within(target, staging):
                        raise SetupError("Архив Node.js вышел за пределы каталога установки")
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        if member.size > MAX_ARCHIVE_BYTES:
                            raise SetupError("Файл в архиве Node.js превышает установленный предел")
                        source = bundle.extractfile(member)
                        if source is None:
                            raise SetupError("Не удалось прочитать файл из архива Node.js")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        if os.name != "nt":
                            target.chmod(member.mode & 0o755)
        else:
            raise SetupError("Для Node.js не поддержан формат архива")

        staged_root = staging / spec["archive_root"]
        if not (staged_root / spec["node_binary"]).is_file() or not (staged_root / spec["npm_cli"]).is_file():
            raise SetupError("В архиве нет Node.js или npm CLI по ожидаемому пути")
        if install_dir.exists():
            raise SetupError("Каталог версии Node.js уже содержит файлы; существующие данные сохранены")
        staging.rename(install_dir)
    except Exception:
        # A failed extraction remains contained under .local for inspection.
        raise

    version = version_text(node_binary, "--version")
    npm_version = version_text(node_binary, str(npm_cli), "--version")
    if version != f"v{lock['node']['version']}" or npm_version != lock["node"]["npm_version"]:
        raise SetupError("Node.js/npm из проверенного архива сообщили неожиданные версии")
    print(f"Node.js {version}, npm {npm_version}: архив проверен SHA-256 ({key})")
    return node_binary, npm_cli


def choose_port() -> int:
    for port in range(55432, 55533):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SetupError("Не найден свободный loopback порт в диапазоне 55432–55532")


def instance_settings() -> dict:
    path_hash = hashlib.sha256(str(ROOT.resolve()).casefold().encode("utf-8")).hexdigest()[:10]
    expected_id = f"alfa-{path_hash}"
    if RUNTIME_PATH.exists():
        if not RUNTIME_PATH.is_file() or RUNTIME_PATH.is_symlink():
            raise SetupError("runtime.json имеет небезопасный тип")
        try:
            current = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SetupError("runtime.json повреждён; он сохранён для диагностики") from exc
        if current.get("instance_id") != expected_id or not isinstance(current.get("postgres_port"), int):
            raise SetupError("runtime.json не соответствует этому checkout; он сохранён без изменений")
        if not 1 <= current["postgres_port"] <= 65535:
            raise SetupError("PostgreSQL port в runtime.json вне диапазона")
        return current
    if LOCAL.exists() and not LOCAL.is_dir():
        raise SetupError("Путь .local/t00 занят не каталогом")
    secure_private_dir(LOCAL)
    settings = {"format_version": 1, "instance_id": expected_id, "postgres_port": choose_port()}
    temp = RUNTIME_PATH.with_suffix(".json.tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(settings, output, indent=2)
        output.write("\n")
    temp.replace(RUNTIME_PATH)
    return settings


def compose_prefix(settings: dict) -> list[str]:
    compose_env = LOCAL / "compose.env"
    expected = f"ALFALAB_PG_PORT={settings['postgres_port']}\n"
    if compose_env.exists():
        if compose_env.read_text(encoding="ascii") != expected:
            raise SetupError("compose.env расходится с runtime.json; существующие файлы сохранены")
    else:
        compose_env.write_text(expected, encoding="ascii", newline="\n")
    return [
        "docker", "compose", "--project-name", settings["instance_id"],
        "--env-file", str(compose_env), "--file", str(COMPOSE_FILE),
    ]


def docker_prerequisites() -> tuple[str, str]:
    docker = shutil.which("docker")
    if docker is None:
        raise SetupError("Не найден Docker CLI. Установите Docker Desktop/Engine с Compose plugin v2.")
    result = run([docker, "info", "--format", "{{.ServerVersion}} {{.OSType}} {{.Architecture}}"], timeout=30)
    compose = run([docker, "compose", "version", "--short"], timeout=30)
    server = result.stdout.strip()
    compose_version = compose.stdout.strip().lstrip("v")
    if not server or not compose_version:
        raise SetupError("Docker daemon или Compose plugin не отвечает")
    return server, compose_version


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def provision_sql(dev_password: str, test_password: str) -> str:
    roles = [
        ("alfalab_development", "alfalab_development", dev_password),
        ("alfalab_testing", "alfalab_testing", test_password),
    ]
    lines = [
        "SET password_encryption = 'scram-sha-256';",
        "REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;",
        "REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;",
    ]
    for role, database, password in roles:
        lines.append(
            "DO $t00$ BEGIN "
            f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {sql_quote(role)}) THEN "
            "EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', "
            f"{sql_quote(role)}, {sql_quote(password)}); "
            "ELSE "
            "EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', "
            f"{sql_quote(role)}, {sql_quote(password)}); "
            "END IF; END $t00$;"
        )
        lines.extend([
            "SELECT format('CREATE DATABASE %I OWNER %I', "
            f"{sql_quote(database)}, {sql_quote(role)}) "
            f"WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = {sql_quote(database)}) \\gexec",
            "DO $t00$ BEGIN "
            f"IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = {sql_quote(database)}) "
            f"<> {sql_quote(role)} THEN RAISE EXCEPTION 'unexpected owner for isolated database'; END IF; "
            "END $t00$;",
            f"REVOKE CONNECT ON DATABASE {database} FROM PUBLIC;",
            f"GRANT CONNECT ON DATABASE {database} TO {role};",
        ])
    return "\n".join(lines) + "\n"


def psql_admin_command() -> list[str]:
    return [
        "sh", "-ec",
        'export PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"; '
        "exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 --username=postgres --dbname=postgres",
    ]


def psql_server_version_command() -> list[str]:
    return [
        "sh", "-ec",
        'export PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"; '
        'exec psql -X --no-psqlrc --username=postgres --dbname=postgres '
        '--tuples-only --no-align --command "SHOW server_version"',
    ]


def psql_role_command(role: str, database: str, password_secret: str,
                      sql: str) -> list[str]:
    script = (
        'export PGPASSWORD="$(cat "$1")"; shift; '
        'exec psql -X --no-psqlrc --set=ON_ERROR_STOP=1 "$@"'
    )
    return [
        "sh", "-ec", script, "t00-probe", f"/run/secrets/{password_secret}",
        "--username", role, "--dbname", database, "--tuples-only", "--no-align",
        "--command", sql,
    ]


def compose_exec(settings: dict, args: list[str], *, input_text: str | None = None,
                 check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([*compose_prefix(settings), "exec", "--no-TTY", "postgres", *args],
               input_text=input_text, timeout=60, check=check)


def create_runtime_credentials(settings: dict) -> None:
    LOCAL.mkdir(parents=True, exist_ok=True)
    secret_dev = secret_value("development-password")
    secret_test = secret_value("testing-password")
    dev_settings = {
        "host": "127.0.0.1", "port": settings["postgres_port"],
        "database": "alfalab_development", "username": "alfalab_development",
        "password": secret_dev, "sslmode": "disable",
    }
    test_settings = {
        "host": "127.0.0.1", "port": settings["postgres_port"],
        "database": "alfalab_testing", "username": "alfalab_testing",
        "password": secret_test, "sslmode": "disable",
    }
    for name, value in (("development.json", dev_settings), ("testing.json", test_settings)):
        path = LOCAL / name
        encoded = json.dumps(value, indent=2) + "\n"
        if path.exists():
            secure_secret_file(path)
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SetupError(f"{path.name} повреждён; сохранён без изменений") from exc
            if existing != value:
                raise SetupError(f"{path.name} расходится с локальными credentials; файл сохранён")
        else:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
            secure_secret_file(path)


def create_lockfiles(lock: dict, uv: Path, node_binary: Path, npm_cli: Path) -> None:
    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(PYTHON_DIR)
    env["UV_PYTHON_DOWNLOADS"] = "automatic"
    if not (ROOT / "uv.lock").exists():
        run([str(uv), "lock", "--python", lock["python"]["version"]], env=env, timeout=300)
    package_lock = ROOT / "apps" / "playground" / "package-lock.json"
    if not package_lock.exists():
        run([str(node_binary), str(npm_cli), "install", "--package-lock-only",
             "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=ROOT / "apps" / "playground", timeout=300)
    print("Проверены или созданы uv.lock и apps/playground/package-lock.json")


def install_dependencies(lock: dict, uv: Path, node_binary: Path, npm_cli: Path) -> None:
    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(PYTHON_DIR)
    env["UV_PYTHON_DOWNLOADS"] = "automatic"
    if not (ROOT / "uv.lock").exists() or not (ROOT / "apps" / "playground" / "package-lock.json").exists():
        raise SetupError("Lockfile не создан; существующие файлы не менялись")
    run([str(uv), "lock", "--check"], env=env, timeout=120)
    run([str(uv), "sync", "--locked", "--python", lock["python"]["version"]],
        env=env, timeout=600)

    npm_ci = [str(node_binary), str(npm_cli), "ci", "--ignore-scripts", "--no-audit", "--no-fund"]
    run(npm_ci, cwd=ROOT / "apps" / "playground", timeout=300)
    print("Python и frontend toolchain синхронизированы по lock-файлам")


def start_database(settings: dict) -> None:
    prefix = compose_prefix(settings)
    run([*prefix, "config", "--quiet"], timeout=60)
    run([*prefix, "pull", "postgres"], timeout=900)
    run([*prefix, "up", "-d", "postgres"], timeout=300)
    deadline = time.monotonic() + 120
    last_error = ""
    while time.monotonic() < deadline:
        check = compose_exec(
            settings,
            ["pg_isready", "--username=postgres", "--dbname=postgres"],
            check=False,
        )
        if check.returncode == 0:
            print("PostgreSQL принимает подключения на loopback")
            return
        last_error = (check.stderr or check.stdout).strip()
        time.sleep(2)
    raise SetupError(f"PostgreSQL не стал готов за 120 секунд. Последняя проверка: {last_error[:240]}")


def provision_database(settings: dict) -> None:
    dev = secret_value("development-password")
    test = secret_value("testing-password")
    compose_exec(
        settings,
        psql_admin_command(),
        input_text=provision_sql(dev, test),
    )
    print("Изолированные development/testing базы и роли подготовлены")


def check_database_profiles(settings: dict, selected: str = "all") -> list[str]:
    failures: list[str] = []
    profiles = [
        ("development", "alfalab_development", "alfalab_development", "development-password"),
        ("testing", "alfalab_testing", "alfalab_testing", "testing-password"),
    ]
    for profile, role, database, password_secret in profiles:
        if selected != "all" and selected != profile:
            continue
        try:
            result = compose_exec(
                settings,
                psql_role_command(role, database, password_secret,
                                  "SELECT current_user || ':' || current_database()"),
                check=False,
            )
        except SetupError:
            failures.append(f"{profile}: подключение к своей БД не выполнено")
            continue
        expected = f"{role}:{database}"
        if result.returncode or result.stdout.strip() != expected:
            failures.append(f"{profile}: подключение к своей БД не прошло проверку")

        for other in ["postgres", "template1", "alfalab_testing" if profile == "development" else "alfalab_development"]:
            denied = compose_exec(
                settings,
                psql_role_command(role, other, password_secret, "SELECT 1"),
                check=False,
            )
            if denied.returncode == 0:
                failures.append(f"{profile}: роль получила запрещённый доступ к базе {other}")
    return failures


def bootstrap() -> int:
    if not (3, 12) <= sys.version_info[:2] < (3, 13):
        raise SetupError("Для запуска bootstrap нужна предварительная CPython 3.12; точная версия установится локально")
    lock = read_lock()
    verify_spec_inputs(lock, require_lockfiles=False)
    docker, compose = docker_prerequisites()
    print(f"Docker Engine {docker}; Compose {compose}")

    secure_private_dir(LOCAL)
    settings = instance_settings()
    secret_value("postgres-admin-password")
    create_runtime_credentials(settings)

    uv = install_uv(lock)
    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(PYTHON_DIR)
    env["UV_PYTHON_DOWNLOADS"] = "automatic"
    install_cmd = run(
        [str(uv), "python", "install", lock["python"]["version"], "--install-dir", str(PYTHON_DIR)],
        env=env,
        timeout=900,
        check=False,
    )
    if install_cmd.returncode:
        raise SetupError(f"Не удалось подготовить CPython {lock['python']['version']}; локальная диагностика сохранена")
    node_binary, npm_cli = install_node(lock)
    create_lockfiles(lock, uv, node_binary, npm_cli)
    verify_spec_inputs(lock)
    install_dependencies(lock, uv, node_binary, npm_cli)
    start_database(settings)
    provision_database(settings)
    failures = check_database_profiles(settings)
    if failures:
        raise SetupError("Проверка доступа PostgreSQL не прошла: " + "; ".join(failures))
    print("Bootstrap завершён. Секреты не выводились; API и ключи моделей не создавались.")
    return doctor("all", report_only=True)


def doctor(profile: str, *, report_only: bool = False) -> int:
    lock = read_lock()
    verify_spec_inputs(lock)
    errors: list[str] = []
    checks: list[tuple[str, bool, str]] = []

    bootstrap_python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info[:2] == (3, 12)
    checks.append(("Python bootstrap", py_ok, bootstrap_python))
    if not py_ok:
        errors.append("Запустите tools/dev.py под CPython 3.12")

    uv_path = BIN_DIR / ("uv.exe" if os.name == "nt" else "uv")
    if uv_path.is_file():
        uv_version = version_text(uv_path, "--version")
        uv_ok = uv_version.startswith(f"uv {lock['uv']['version']} ")
        checks.append(("uv", uv_ok, uv_version))
        if not uv_ok:
            errors.append("Локальный uv имеет неверную версию")
        env = os.environ.copy()
        env["UV_PYTHON_INSTALL_DIR"] = str(PYTHON_DIR)
        python_check = run(
            [str(uv_path), "run", "--locked", "--no-sync", "--python", lock["python"]["version"],
             "python", "--version"],
            env=env, timeout=90, check=False,
        )
        py_output = (python_check.stdout or python_check.stderr).strip()
        exact_python_ok = python_check.returncode == 0 and py_output == f"Python {lock['python']['version']}"
        checks.append(("CPython lock", exact_python_ok, py_output or "недоступен"))
        if not exact_python_ok:
            errors.append("Не найден закреплённый локальный CPython; выполните bootstrap")
        uv_lock_check = run([str(uv_path), "lock", "--check"], timeout=90, check=False)
        checks.append(("uv.lock", uv_lock_check.returncode == 0,
                       "проверен" if uv_lock_check.returncode == 0 else "не совпадает с pyproject.toml"))
        if uv_lock_check.returncode:
            errors.append("uv.lock не согласован с pyproject.toml")
    else:
        checks.append(("uv", False, "не установлен локальный pinned binary"))
        errors.append("Выполните bootstrap для установки uv")

    try:
        key, node_spec = host_platform(lock)
        install_dir = NODE_DIR / f"node-{lock['node']['version']}-{key}"
        node_binary = install_dir / node_spec["archive_root"] / node_spec["node_binary"]
        npm_cli = install_dir / node_spec["archive_root"] / node_spec["npm_cli"]
        node_version = version_text(node_binary, "--version") if node_binary.is_file() else "не установлен"
        npm_version = version_text(node_binary, str(npm_cli), "--version") if npm_cli.is_file() else "не установлен"
        node_ok = node_version == f"v{lock['node']['version']}" and npm_version == lock["node"]["npm_version"]
        checks.append(("Node.js/npm", node_ok, f"{node_version} / npm {npm_version}"))
        if not node_ok:
            errors.append("Pinned Node.js/npm отсутствуют; выполните bootstrap")
    except SetupError as exc:
        checks.append(("Node.js/npm", False, str(exc)))
        errors.append("Платформа Node.js не поддерживается этим lockfile")

    if profile in {"all", "development", "testing"}:
        try:
            docker_version, compose_version = docker_prerequisites()
            checks.append(("Docker Engine/Compose", True, f"{docker_version} / Compose {compose_version}"))
        except SetupError:
            checks.append(("Docker Engine/Compose", False, "CLI или daemon недоступен"))
            errors.append("Запустите Docker Desktop/Engine с Compose plugin v2")

        if RUNTIME_PATH.is_file():
            try:
                settings = instance_settings()
                prefix = compose_prefix(settings)
                config_check = run([*prefix, "config", "--quiet"], timeout=60, check=False)
                checks.append(("Compose config", config_check.returncode == 0,
                               "валиден" if config_check.returncode == 0 else "невалиден"))
                if config_check.returncode:
                    errors.append("Compose configuration невалиден")
                health = compose_exec(settings, ["pg_isready", "--username=postgres", "--dbname=postgres"], check=False)
                healthy = health.returncode == 0
                checks.append(("PostgreSQL", healthy,
                               "принимает подключения" if healthy else "недоступен"))
                if not healthy:
                    errors.append("Локальная PostgreSQL недоступна; запустите bootstrap")
                else:
                    server_version = compose_exec(settings, psql_server_version_command(), check=False)
                    actual_version = server_version.stdout.strip()
                    container_image = run(
                        ["docker", "inspect", "--format", "{{.Config.Image}}",
                         settings["instance_id"] + "-postgres-1"], check=False,
                    )
                    server_version_number = actual_version.split(" ", 1)[0]
                    image_ok = (server_version.returncode == 0
                                and server_version_number == lock["postgres"]["version"]
                                and container_image.returncode == 0
                                and container_image.stdout.strip() == lock["postgres"]["image"])
                    checks.append(("PostgreSQL pin", image_ok,
                                   f"server {actual_version or 'unknown'}; image digest "
                                   f"{'matches' if image_ok else 'does not match'} lock"))
                    if not image_ok:
                        errors.append("Версия PostgreSQL или image digest расходится с lockfile")

                    profile_failures = check_database_profiles(settings, profile)
                    profiles_ok = not profile_failures
                    checks.append(("Изоляция профилей", profiles_ok,
                                   "dev/test credentials и cross-database отказ проверены" if profiles_ok
                                   else "; ".join(profile_failures)))
                    errors.extend(profile_failures)
                    network_name = settings["instance_id"] + "_local_database"
                    network = run(["docker", "network", "inspect", network_name], check=False)
                    network_ok = False
                    if network.returncode == 0:
                        try:
                            network_data = json.loads(network.stdout)[0]
                            peers = list(network_data.get("Containers", {}).values())
                            network_ok = (network_data.get("Driver") == "bridge"
                                          and network_data.get("Internal") is False
                                          and len(peers) == 1
                                          and peers[0].get("Name") == settings["instance_id"] + "-postgres-1")
                        except (IndexError, KeyError, TypeError, json.JSONDecodeError):
                            network_ok = False
                    checks.append(("Docker network", network_ok,
                                   "отдельная bridge network; подключён только PostgreSQL" if network_ok
                                   else "сеть содержит другие контейнеры или отличается от ожиданий"))
                    if not network_ok:
                        errors.append("PostgreSQL network не изолирована от соседних контейнеров")

                    bindings = run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}",
                                    settings["instance_id"] + "-postgres-1"], check=False)
                    binding_ok = False
                    if bindings.returncode == 0:
                        try:
                            entries = json.loads(bindings.stdout).get("5432/tcp", [])
                            binding_ok = (len(entries) == 1
                                          and entries[0].get("HostIp") == "127.0.0.1"
                                          and entries[0].get("HostPort") == str(settings["postgres_port"]))
                        except (IndexError, TypeError, json.JSONDecodeError):
                            binding_ok = False
                    try:
                        with socket.create_connection(("127.0.0.1", settings["postgres_port"]), timeout=3):
                            port_open = True
                    except OSError:
                        port_open = False
                    published_ok = binding_ok and port_open
                    checks.append(("PostgreSQL loopback port", published_ok,
                                   f"127.0.0.1:{settings['postgres_port']}" if published_ok
                                   else "port не опубликован или недоступен с хоста"))
                    if not published_ok:
                        errors.append("Проверьте loopback port binding Docker Desktop/Engine")
            except SetupError as exc:
                checks.append(("PostgreSQL", False, str(exc)))
                errors.append("Не удалось проверить локальную PostgreSQL")
        else:
            checks.append(("PostgreSQL", False, "bootstrap ещё не выполнялся"))
            errors.append("Выполните bootstrap для локальной PostgreSQL")

    for name, ok, detail in checks:
        print(f"{'OK' if ok else 'FAIL'}  {name}: {detail}")
    if errors:
        print("\nДействия:")
        for error in dict.fromkeys(errors):
            print(f"- {error}")
        return 1
    if not report_only:
        print("\nПроверки T00 пройдены. Это ещё не Framework Ready.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Локальный toolchain и PostgreSQL для T00")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="установить закреплённые runtimes и изолированную PostgreSQL")
    check = sub.add_parser("doctor", help="проверить закреплённые tools, locks, DB и изоляцию")
    check.add_argument("--profile", choices=["all", "development", "testing"], default="all")
    args = parser.parse_args()
    try:
        if args.command == "bootstrap":
            return bootstrap()
        return doctor(args.profile)
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Операция прервана. Созданные файлы/volume сохранены; повторите bootstrap.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
