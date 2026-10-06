# SPDX-License-Identifier: LGPL-2.1-or-later
"""Install or verify a complete SHA-pinned, delivered Windows LibPack.

Installation requires a fresh destination. It preserves the original SDK file
bytes, membership and indexed modification times, without overlaying a stock
SDK. Verification of an existing cache checks bytes and membership, allowing
timestamp-only changes; additional Python caches are not original SDK contents.
This helper does not execute the SDK, compile Qt, or change qualification data.
"""

import argparse
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.parse
import urllib.request

CATALOG = Path(__file__).with_name("distribution.json")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAX_CATALOG_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 32 * 1024 * 1024
BLOCK_BYTES = 1024 * 1024
PINS = {
    "3.5.3-x64": {
        "size": 1149392860,
        "sha256": "9d54c145862f0ce004b59cd02a74f92c7a05642bbcc139ae986833c2b9e5445a",
        "files": 60094,
        "directories": 4402,
        "content_bytes": 3140175032,
        "max_file_size": 96850432,
        "index_content_sha256": "dbb699f8677529a83f7b2896f88957112970395d5540e19e2ec5bae87460614c",
    },
    "3.5.5-x64": {
        "size": 1151670631,
        "sha256": "bae3c85fc9e8e9b3fcbe184113f4928bbc3f26322667946cc0b44b7bac6a6958",
        "files": 60130,
        "directories": 4406,
        "content_bytes": 3144711619,
        "max_file_size": 96850432,
        "index_content_sha256": "362afda3bdb1fa8e94178f032bca5032999b4f9b2ae54fcd0238e3ead2e08424",
    },
    "3.5.5-arm64": {
        "size": 1039826386,
        "sha256": "492d75c3e31ad4b6ba1f2b80011107ca22e21949647fcb9e9b8a9547a47bad17",
        "files": 59329,
        "directories": 4355,
        "content_bytes": 3016580282,
        "max_file_size": 88495616,
        "index_content_sha256": "d1ad010cf4b4b093940f184dbc1cd03950627d57b7d5ddf9f94f284be3705fd2",
    },
}
HARDLINKS = {
    f"bin/{name}6.exe": f"bin/{name}.exe"
    for name in ("androiddeployqt", "qmake", "qtdiag", "qtpaths", "wasmdeployqt", "windeployqt")
}
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in "123456789¹²³"
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_BYTES), b""):
            value.update(block)
    return value.hexdigest()


def relative(value):
    require(isinstance(value, str) and value, "Empty/non-string SDK path")
    require(
        not any(ord(character) < 32 or character in '\\:*?"<>|' for character in value),
        f"Unsafe SDK path: {value!r}",
    )
    parts = value.split("/")
    require(
        all(
            part not in ("", ".", "..")
            and not part.endswith((".", " "))
            and part.split(".", 1)[0].casefold() not in RESERVED
            for part in parts
        ),
        f"Unsafe SDK path: {value!r}",
    )
    return PurePosixPath(value)


def reparse(info):
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def physical(path, *, exists=True, directory=False):
    """Reject links/reparse ancestors before following an input or destination."""
    path = Path(os.path.abspath(path))
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not reparse(info), "Linked/reparse path")
        if component != path:
            require(stat.S_ISDIR(info.st_mode), "Non-directory path ancestor")
    if exists:
        info = path.lstat()
        require(
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "Require a physical directory" if directory else "Require a regular file",
        )
        if not directory:
            require(info.st_nlink == 1, "Input must be an independent regular file")
    return path


def separate(left, right):
    left, right = Path(left), Path(right)
    require(
        left != right and left not in right.parents and right not in left.parents,
        "Delivery paths overlap",
    )


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def json_bytes(value):
    return json.loads(value, object_pairs_hook=unique_object)


def validate_index(index, pin):
    require(isinstance(index, dict) and set(index) == {"files", "directories"}, "SDK index shape")
    files, directories = index["files"], index["directories"]
    require(
        isinstance(files, dict)
        and isinstance(directories, list)
        and len(files) == pin["files"]
        and len(directories) == pin["directories"],
        "SDK index counts differ",
    )
    names, total = set(), 0
    for name in [*directories, *files]:
        relative(name)
        require(name.casefold() not in names, "SDK index path collision")
        names.add(name.casefold())
    require(directories == sorted(set(directories)), "SDK directories must be unique and sorted")
    directory_set = set(directories)
    for name in [*directories, *files]:
        require(
            all(
                str(parent) in directory_set
                for parent in relative(name).parents
                if str(parent) != "."
            ),
            "SDK index omits a parent directory",
        )
    for name, item in files.items():
        require(
            isinstance(item, dict)
            and set(item) == {"size", "sha256", "mtime_ns"}
            and integer(item["size"])
            and 0 <= item["size"] <= pin["max_file_size"]
            and sha256(item["sha256"])
            and integer(item["mtime_ns"])
            and 0 <= item["mtime_ns"] < 2**63,
            f"Invalid SDK indexed file: {name}",
        )
        total += item["size"]
    require(total == pin["content_bytes"], "SDK indexed content size differs")
    require(
        max(item["size"] for item in files.values()) == pin["max_file_size"],
        "SDK indexed maximum file size differs",
    )
    return index


def load_delivery(sdk, catalog_path=CATALOG, repository_root=REPOSITORY_ROOT):
    require(sdk in PINS, "Unknown delivered SDK")
    catalog_path = physical(catalog_path)
    require(catalog_path.stat().st_size <= MAX_CATALOG_BYTES, "Oversized distribution catalogue")
    catalog = json_bytes(catalog_path.read_bytes())
    require(
        isinstance(catalog, dict)
        and catalog.get("schema_version") == 1
        and integer(catalog["schema_version"])
        and isinstance(catalog.get("libpacks"), dict)
        and set(catalog["libpacks"]) == set(PINS),
        "Distribution catalogue schema/SDK selection differs",
    )
    delivery, pin = catalog["libpacks"][sdk], PINS[sdk]
    require(isinstance(delivery, dict), "Invalid SDK delivery")
    require(
        delivery.get("size") == pin["size"]
        and integer(delivery["size"])
        and delivery.get("sha256") == pin["sha256"]
        and delivery.get("qt_version") == "6.11.1"
        and sha256(delivery.get("index_sha256")),
        "Delivered SDK archive/Qt pins differ",
    )
    for field, pinned in (
        ("file_count", "files"),
        ("directory_count", "directories"),
        ("unpacked_file_bytes", "content_bytes"),
        ("max_file_size", "max_file_size"),
    ):
        require(
            integer(delivery.get(field)) and delivery[field] == pin[pinned],
            f"Delivered SDK {field} differs",
        )
    require(
        delivery.get("index_uncompressed_sha256") == pin["index_content_sha256"],
        "Original SDK inventory pin differs",
    )
    filename = relative(delivery.get("filename"))
    require(len(filename.parts) == 1 and str(filename).endswith(".tar.gz"), "Invalid SDK filename")
    parsed = urllib.parse.urlsplit(delivery.get("url", ""))
    require(
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(
            r"/zukomgwili/FreeCAD/releases/download/[^/]+/" + re.escape(str(filename)), parsed.path
        ),
        "Require the pinned repository release asset URL",
    )
    index_path = physical(Path(repository_root) / relative(delivery.get("index_path")))
    require(index_path.stat().st_size <= MAX_INDEX_BYTES, "Oversized compressed SDK index")
    require(digest(index_path) == delivery["index_sha256"], "SDK index SHA256 differs")
    with gzip.open(index_path, "rb") as stream:
        raw_index = stream.read(MAX_INDEX_BYTES + 1)
    require(len(raw_index) <= MAX_INDEX_BYTES, "Oversized expanded SDK index")
    require(
        hashlib.sha256(raw_index).hexdigest() == pin["index_content_sha256"],
        "Original SDK inventory bytes differ",
    )
    index = validate_index(json_bytes(raw_index), pin)
    require(delivery.get("hardlinks") == HARDLINKS, "Finite SDK hardlink catalogue differs")
    return (
        delivery,
        index,
        {
            "catalog_sha256": digest(catalog_path),
            "index_sha256": delivery["index_sha256"],
            "index_content_sha256": hashlib.sha256(raw_index).hexdigest(),
            "index_path": delivery["index_path"],
        },
    )


def verify_archive(path, delivery):
    path = physical(path)
    before = archive_identity(path)
    require(path.stat().st_size == delivery["size"], "SDK archive size differs")
    require(digest(path) == delivery["sha256"], "SDK archive SHA256 differs")
    require(archive_identity(path) == before, "SDK archive changed during authentication")
    return path


def archive_identity(path):
    info = physical(path).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, url):
        require(urllib.parse.urlsplit(url).scheme == "https", "Non-HTTPS asset redirect")
        return super().redirect_request(request, file, code, message, headers, url)


def download(delivery, path):
    opener = urllib.request.build_opener(HTTPSRedirect())
    request = urllib.request.Request(delivery["url"], headers={"User-Agent": "FreeCAD-LibPack"})
    value, size = hashlib.sha256(), 0
    with opener.open(request, timeout=60) as source, path.open("xb") as target:
        require(urllib.parse.urlsplit(source.geturl()).scheme == "https", "Non-HTTPS SDK asset")
        advertised = source.headers.get("Content-Length")
        require(
            advertised is None or advertised == str(delivery["size"]), "Asset size header differs"
        )
        while block := source.read(BLOCK_BYTES):
            size += len(block)
            require(size <= delivery["size"], "Oversized SDK asset download")
            target.write(block)
            value.update(block)
    require(
        size == delivery["size"] and value.hexdigest() == delivery["sha256"], "SDK asset differs"
    )
    return verify_archive(path, delivery)


def directory_time(entry):
    try:
        value = Decimal(entry.pax_headers.get("mtime", str(entry.mtime))) * 1_000_000_000
        require(value.is_finite() and 0 <= value < 2**63, "Invalid archived directory time")
        result = int(value)
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise ValueError("Invalid archived directory time") from error
    # Windows FILETIME represents 100 ns ticks; no exact directory ns index exists.
    return result - result % 100 if os.name == "nt" else result


def inventory(root, index, *, timestamps=False):
    root = physical(root, directory=True)
    files, directories, folded = {}, [], set()
    pending = [root]
    while pending:
        parent = physical(pending.pop(), directory=True)
        with os.scandir(parent) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                relative(name)
                require(name.casefold() not in folded, "SDK readback case collision")
                folded.add(name.casefold())
                info = entry.stat(follow_symlinks=False)
                require(
                    not stat.S_ISLNK(info.st_mode) and not reparse(info),
                    "Linked/reparse SDK content",
                )
                if stat.S_ISDIR(info.st_mode):
                    require(name in index["directories"], f"Unexpected SDK directory: {name}")
                    directories.append(name)
                    pending.append(path)
                else:
                    require(
                        stat.S_ISREG(info.st_mode)
                        and info.st_nlink == 1
                        and name in index["files"],
                        f"Unexpected/non-independent SDK file: {name}",
                    )
                    expected = index["files"][name]
                    require(info.st_size == expected["size"], f"SDK file size differs: {name}")
                    actual = {"size": info.st_size, "sha256": digest(path)}
                    require(
                        actual["sha256"] == expected["sha256"], f"SDK file SHA256 differs: {name}"
                    )
                    after = physical(path).stat()
                    require(
                        all(
                            getattr(info, field) == getattr(after, field)
                            for field in (
                                "st_dev",
                                "st_ino",
                                "st_size",
                                "st_mtime_ns",
                                "st_ctime_ns",
                            )
                        ),
                        f"SDK file changed during verification: {name}",
                    )
                    if timestamps:
                        require(
                            info.st_mtime_ns == expected["mtime_ns"],
                            f"SDK file time differs: {name}",
                        )
                    files[name] = actual
    require(
        set(files) == set(index["files"]) and sorted(directories) == index["directories"],
        "SDK readback membership differs",
    )
    return {
        "files": len(files),
        "directories": len(directories),
        "content_bytes": sum(x["size"] for x in files.values()),
    }


def extract(archive, destination, index, pin):
    """Write only a fresh SDK, then require exact original indexed contents."""
    seen, regular, links, directory_times = set(), set(), {}, {}
    actual_files, actual_directories, total = set(), set(), 0
    with tarfile.open(archive, "r|gz") as stream:
        for count, entry in enumerate(stream):
            name = str(relative(entry.name.removesuffix("/")))
            require(
                count < pin["files"] + pin["directories"] + 1 and name.casefold() not in seen,
                "Duplicate/excess TAR member",
            )
            seen.add(name.casefold())
            require(name == "candidate" or name.startswith("candidate/"), "Foreign SDK TAR root")
            require(entry.sparse is None, "Sparse SDK TAR member")
            if name == "candidate":
                require(entry.isdir() and entry.size == 0, "SDK TAR root must be a directory")
                directory_times[""] = directory_time(entry)
                continue
            name = name.removeprefix("candidate/")
            output = destination / relative(name)
            if entry.isdir():
                require(
                    name in index["directories"] and entry.size == 0,
                    f"Unindexed/invalid TAR directory: {name}",
                )
                output.mkdir(parents=True, exist_ok=True)
                actual_directories.add(name)
                directory_times[name] = directory_time(entry)
                continue
            require(entry.isreg() or entry.islnk(), "Linked/device/special SDK TAR member")
            require(name in index["files"], f"Unindexed TAR file: {name}")
            expected = index["files"][name]
            total += expected["size"]
            require(total <= pin["content_bytes"], "Oversized SDK TAR content")
            output.parent.mkdir(parents=True, exist_ok=True)
            if entry.islnk():
                target = str(relative(entry.linkname))
                require(target.startswith("candidate/"), "Foreign SDK hardlink root")
                target = target.removeprefix("candidate/")
                require(
                    HARDLINKS.get(name) == target
                    and target in regular
                    and entry.size == 0
                    and all(
                        index["files"][target][key] == expected[key] for key in ("size", "sha256")
                    ),
                    "Unknown/later/unequal SDK hardlink",
                )
                links[name] = target
                source = (destination / relative(target)).open("rb")
            else:
                require(entry.size == expected["size"], f"SDK TAR file size differs: {name}")
                regular.add(name)
                source = stream.extractfile(entry)
            value, size = hashlib.sha256(), 0
            with source, output.open("xb") as out:
                while block := source.read(BLOCK_BYTES):
                    size += len(block)
                    require(size <= expected["size"], "Oversized SDK TAR file")
                    value.update(block)
                    out.write(block)
            require(
                output.stat().st_size == size == expected["size"]
                and value.hexdigest() == expected["sha256"],
                f"SDK materialized file differs: {name}",
            )
            os.utime(output, ns=(output.stat().st_atime_ns, expected["mtime_ns"]))
            actual_files.add(name)
    require(
        actual_files == set(index["files"])
        and actual_directories == set(index["directories"])
        and "" in directory_times
        and links == HARDLINKS
        and total == pin["content_bytes"],
        "Incomplete SDK TAR/index/finite hardlink membership",
    )
    for name in sorted(directory_times, key=lambda value: value.count("/"), reverse=True):
        path = destination / name
        os.utime(path, ns=(path.stat().st_atime_ns, directory_times[name]))
        require(
            path.stat().st_mtime_ns == directory_times[name],
            "Archived SDK directory time readback differs",
        )
    return inventory(destination, index, timestamps=True), links


def deliver(args):
    delivery, index, bindings = load_delivery(args.sdk)
    destination = physical(args.destination, exists=args.verify, directory=args.verify)
    physical(destination.parent, directory=True)
    receipt_path = physical(args.receipt, exists=False) if args.receipt else None
    if receipt_path:
        separate(destination, receipt_path)
        physical(receipt_path.parent, directory=True)
        require(not receipt_path.exists(), "Delivery receipt must be fresh")
    if args.verify:
        require(args.archive is None, "Cache verification does not consume an archive")
        result, links = inventory(destination, index), None
    else:
        require(not destination.exists(), "SDK destination must be fresh")
        with tempfile.TemporaryDirectory(
            prefix="freecad-libpack-", dir=destination.parent
        ) as temporary:
            archive = (
                verify_archive(args.archive, delivery)
                if args.archive
                else download(delivery, Path(temporary) / delivery["filename"])
            )
            separate(destination, archive)
            archive_before = archive_identity(archive)
            destination.mkdir()
            original = destination.stat()
            try:
                result, links = extract(archive, destination, index, PINS[args.sdk])
                require(
                    archive_identity(archive) == archive_before,
                    "SDK archive changed during installation",
                )
            except BaseException:
                current = destination.lstat()
                if (
                    current.st_dev == original.st_dev
                    and current.st_ino == original.st_ino
                    and not reparse(current)
                ):
                    shutil.rmtree(destination)
                raise
    receipt = {
        "schema_version": 1,
        "status": "verified" if args.verify else "installed",
        "sdk": args.sdk,
        "qt_version": delivery["qt_version"],
        "destination": str(destination),
        "archive": {key: delivery[key] for key in ("filename", "url", "size", "sha256")},
        "archive_authenticated": not args.verify,
        **bindings,
        "helper_sha256": digest(Path(__file__)),
        "inventory": result,
        "file_timestamps": (
            "ignored-during-cache-verification" if args.verify else "original-index-mtime-ns"
        ),
        "directory_timestamps": (
            "ignored-during-cache-verification" if args.verify else "archived-representable-mtime"
        ),
        "hardlinks_materialized": links,
        "sdk_executed": False,
        "qt_compiled": False,
    }
    if receipt_path:
        with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", choices=sorted(PINS), required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--archive", type=Path, help="Use an existing whole SHA-pinned SDK TAR")
    parser.add_argument(
        "--verify", action="store_true", help="Verify exact existing cache contents, ignoring times"
    )
    parser.add_argument("--receipt", type=Path, help="Write a fresh JSON receipt outside the SDK")
    args = parser.parse_args()
    try:
        print(json.dumps(deliver(args), sort_keys=True))
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f"LibPack delivery failed: {error}\n")


if __name__ == "__main__":
    main()
