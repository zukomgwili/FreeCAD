# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reversible SDK input protection for disposable Windows native captures.

WRITE_DAC remains available for exact restoration. This cooperative runtime
policy is not a hostile-process boundary. Original content/mtime inventories
must still compare equal after the child processes exit.
"""

import base64
from contextlib import contextmanager
import ctypes
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import struct
import sys

DENY_MASK = 0x00010156  # write/append/EA/attributes, delete and delete-child
MUTATION_RIGHTS = (0x2, 0x4, 0x10, 0x40, 0x100, 0x10000)
READ_EXECUTE_RESTORE = 0x001600A9  # read data/EA/attributes, execute, RC/S/WDAC
MAX_ENTRIES = 250000
MAX_DESCRIPTOR = 16384
MAX_MANIFEST = 512 * 1024 * 1024
DACL_CONTROL = 0x150C  # present/defaulted/auto-inherit-requested/inherited/protected
DACL_WRITE_POLICY = "legacy-SetFileSecurityW/auto-inherited-SetNamedSecurityInfoW-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(path, value):
    Path(path).write_bytes(json_bytes(value))


def write_gzip(path, values):
    total = 0
    with Path(path).open("xb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            for value in values:
                data = json_bytes(value)
                total += len(data)
                require(total <= MAX_MANIFEST, "SDK protection evidence is too large")
                stream.write(data)
    return total


def read_gzip(path, limit=MAX_MANIFEST):
    with gzip.open(path, "rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "Oversized SDK protection evidence")
    return data


def sid_at(data, offset=0):
    require(offset + 8 <= len(data), "Truncated SID")
    revision, count = data[offset : offset + 2]
    size = 8 + count * 4
    require(revision == 1 and 1 <= count <= 15 and offset + size <= len(data), "Invalid SID")
    return data[offset : offset + size]


def sid_text(sid):
    sid = sid_at(sid)
    authority = int.from_bytes(sid[2:8], "big")
    values = struct.unpack_from("<" + "L" * sid[1], sid, 8)
    return "S-1-" + str(authority) + "".join("-" + str(value) for value in values)


def acl_parts(descriptor):
    require(20 <= len(descriptor) <= MAX_DESCRIPTOR, "Invalid security descriptor size")
    revision, _, control, owner, group, sacl, offset = struct.unpack_from("<BBHLLLL", descriptor)
    require(revision == 1 and control & 0x8000, "Require self-relative security descriptor")
    require(control & 4 and offset >= 20, "Require a present non-NULL original DACL")
    require(owner >= 20 and group >= 20 and sacl == 0, "Invalid owner/group/SACL descriptor")
    sid_at(descriptor, owner)
    sid_at(descriptor, group)
    require(offset + 8 <= len(descriptor), "Truncated original DACL")
    acl_revision, _, size, count, _ = struct.unpack_from("<BBHHH", descriptor, offset)
    require(acl_revision in (2, 4) and size >= 8, "Invalid original ACL header")
    require(offset + size <= len(descriptor), "Truncated original ACL")
    acl = descriptor[offset : offset + size]
    cursor = 8
    for _ in range(count):
        require(cursor + 4 <= size, "Truncated original ACE")
        ace_size = struct.unpack_from("<H", acl, cursor + 2)[0]
        require(
            ace_size >= 4 and ace_size % 4 == 0 and cursor + ace_size <= size,
            "Invalid original ACE size",
        )
        cursor += ace_size
    return control, acl, cursor, count


def protected_descriptor(descriptor, sid):
    control, acl, end, count = acl_parts(descriptor)
    sid = sid_at(sid)
    ace = struct.pack("<BBHL", 1, 0, 8 + len(sid), DENY_MASK) + sid
    size = 8 + len(ace) + end - 8
    require(size <= 65535 and count < 65535, "Original DACL has no room for protection ACE")
    protected = struct.pack("<BBHHH", acl[0], 0, size, count + 1, 0) + ace + acl[8:end]
    # Noninheritable explicit deny before all original ACEs. No original ACE
    # is edited, and each child gets its own independent policy.
    result = bytearray(descriptor)
    while len(result) % 4:
        result.append(0)
    struct.pack_into("<L", result, 16, len(result))
    result.extend(protected)
    require(len(result) <= MAX_DESCRIPTOR, "Protected descriptor is too large")
    return bytes(result), control


def dacl_identity(descriptor):
    control, acl, _, _ = acl_parts(descriptor)
    return {"control": control & DACL_CONTROL, "sha256": hashlib.sha256(acl).hexdigest()}


def dacl_write_api(descriptor):
    control, _, _, _ = acl_parts(descriptor)
    return (
        "SetNamedSecurityInfoW/DACL_SECURITY_INFORMATION+original_inheritance_protection"
        if control & 0x400
        else "SetFileSecurityW/DACL_SECURITY_INFORMATION"
    )


def physical(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "Require canonical physical SDK path")
    for part in (path, *path.parents):
        info = part.lstat()
        require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "SDK protection rejects reparse/symbolic paths",
        )
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "Non-regular SDK entry")
    return (info.st_dev, info.st_ino, stat.S_ISDIR(info.st_mode))


class WindowsSecurity:
    """Windows boundary; portable protocol controls use a separate backend."""

    def __init__(self):
        require(sys.platform == "win32", "SDK runtime DACLs require Windows")
        from ctypes import wintypes as w

        self.w = w
        self.api = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        ptr = ctypes.c_void_p
        signatures = {
            "GetFileSecurityW": (
                [w.LPCWSTR, w.DWORD, ptr, w.DWORD, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            "SetNamedSecurityInfoW": (
                [w.LPWSTR, ctypes.c_int, w.DWORD, ptr, ptr, ptr, ptr],
                w.DWORD,
            ),
            "SetFileSecurityW": ([w.LPCWSTR, w.DWORD, ptr], w.BOOL),
            "OpenProcessToken": ([w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL),
            "GetTokenInformation": (
                [w.HANDLE, ctypes.c_int, ptr, w.DWORD, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            "DuplicateToken": ([w.HANDLE, ctypes.c_int, ctypes.POINTER(w.HANDLE)], w.BOOL),
            "AccessCheck": (
                [
                    ptr,
                    w.HANDLE,
                    w.DWORD,
                    ptr,
                    ptr,
                    ctypes.POINTER(w.DWORD),
                    ctypes.POINTER(w.DWORD),
                    ctypes.POINTER(w.BOOL),
                ],
                w.BOOL,
            ),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes, self.kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        token, self.token = w.HANDLE(), w.HANDLE()
        self.check(
            self.api.OpenProcessToken(self.kernel.GetCurrentProcess(), 0xA, ctypes.byref(token))
        )
        try:
            self.check(self.api.DuplicateToken(token, 2, ctypes.byref(self.token)))
            size = w.DWORD()
            self.api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            require(0 < size.value <= MAX_DESCRIPTOR, "Invalid current runner token")
            buffer = ctypes.create_string_buffer(size.value)
            self.check(self.api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
            address = ctypes.cast(buffer, ctypes.POINTER(ptr))[0]
            head = ctypes.string_at(address, 8)
            self.sid = sid_at(ctypes.string_at(address, 8 + head[1] * 4))
        finally:
            self.kernel.CloseHandle(token)

    def check(self, result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.token:
            self.kernel.CloseHandle(self.token)
            self.token = None

    def read(self, path):
        size = self.w.DWORD()
        self.api.GetFileSecurityW(str(path), 7, None, 0, ctypes.byref(size))
        require(0 < size.value <= MAX_DESCRIPTOR, "Invalid SDK security descriptor length")
        buffer = ctypes.create_string_buffer(size.value)
        self.check(self.api.GetFileSecurityW(str(path), 7, buffer, size, ctypes.byref(size)))
        descriptor = buffer.raw[: size.value]
        acl_parts(descriptor)
        return descriptor

    def write(self, path, descriptor):
        control, _, _, _ = acl_parts(descriptor)
        buffer = ctypes.create_string_buffer(descriptor)
        offset = struct.unpack_from("<L", descriptor, 16)[0]
        # SetNamedSecurityInfo converts legacy DACLs to the current inheritance
        # model, including descendants, so it cannot retain the observed
        # original legacy control state. SetFileSecurity writes the full legacy
        # descriptor's DACL only and does not propagate to children. Existing
        # auto-inherited descriptors keep the original inheritance-aware route.
        # Neither API promises a universal raw roundtrip: exact readback and
        # effective access checks remain mandatory for every path.
        if not control & 0x400:
            self.check(self.api.SetFileSecurityW(str(path), 4, buffer))
            return
        information = 4 | (0x80000000 if control & 0x1000 else 0x20000000)
        error = self.api.SetNamedSecurityInfoW(
            str(path), 1, information, None, None, ctypes.byref(buffer, offset), None
        )
        if error:
            raise ctypes.WinError(error)

    def allowed(self, descriptor, mask):
        class Mapping(ctypes.Structure):
            _fields_ = [(name, self.w.DWORD) for name in ("read", "write", "execute", "all")]

        mapping = Mapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        privilege = ctypes.create_string_buffer(4096)
        size, granted, status = self.w.DWORD(4096), self.w.DWORD(), self.w.BOOL()
        buffer = ctypes.create_string_buffer(descriptor)
        self.check(
            self.api.AccessCheck(
                buffer,
                self.token,
                mask,
                ctypes.byref(mapping),
                privilege,
                ctypes.byref(size),
                ctypes.byref(granted),
                ctypes.byref(status),
            )
        )
        return bool(status.value)


def raise_walk_error(error):
    raise error


def roots_and_paths(roots, evidence):
    require(1 <= len(roots) <= 3, "Require one to three SDK input roots")
    roots = [Path(root) for root in roots]
    require(
        len({str(root).casefold() for root in roots}) == len(roots),
        "Duplicate/case-colliding SDK roots",
    )
    for root in roots:
        require(physical(root)[2] and root.parent != root, "Invalid SDK input root")
        require(
            all(root == other or not root.is_relative_to(other) for other in roots),
            "Nested SDK input roots",
        )
    require(evidence.is_absolute() and not evidence.exists(), "Fresh external evidence required")
    require(evidence.parent.resolve() == evidence.parent, "Nonphysical evidence parent")
    require(
        all(
            not evidence.is_relative_to(root) and not root.is_relative_to(evidence)
            for root in roots
        ),
        "Protection evidence overlaps SDK input",
    )
    entries = []
    for number, root in enumerate(roots):
        names = set()
        entries.append((number, ".", root, physical(root)))
        for parent, directories, files in os.walk(
            root, followlinks=False, onerror=raise_walk_error
        ):
            for name in sorted(directories + files):
                path = Path(parent) / name
                relative = path.relative_to(root).as_posix()
                require(relative.casefold() not in names, "Case-colliding SDK entries")
                names.add(relative.casefold())
                entries.append((number, relative, path, physical(path)))
                require(len(entries) <= MAX_ENTRIES, "Too many SDK protection entries")
    return roots, entries


def inventory_delta(before, after):
    left, right = before["files"], after["files"]
    result = {
        "added": sorted(right.keys() - left.keys()),
        "removed": sorted(left.keys() - right.keys()),
        "changed": {},
        "added_directories": sorted(set(after["directories"]) - set(before["directories"])),
        "removed_directories": sorted(set(before["directories"]) - set(after["directories"])),
    }
    for name in sorted(left.keys() & right.keys()):
        fields = [
            key for key in ("size", "sha256", "mtime_ns") if left[name][key] != right[name][key]
        ]
        if fields:
            result["changed"][name] = {"fields": fields, "before": left[name], "after": right[name]}
    return result


class Policy:
    def __init__(self, roots, evidence, helper, backend, purpose="native-capture"):
        require(purpose in ("native-capture", "preflight"), "Unknown SDK protection purpose")
        self.roots, self.entries = roots_and_paths(roots, evidence)
        self.evidence, self.helper, self.backend = evidence, helper, backend
        self.before, self.saved, self.mismatches = [], [], []
        self.prepared = self.application_started = False
        self.report = {
            "schema_version": 1,
            "purpose": purpose,
            "status": "failed",
            "qualified": False,
            "source_sha256": digest(__file__),
            "roots": [str(root) for root in self.roots],
            "sid": sid_text(backend.sid),
            "deny_mask": DENY_MASK,
            "read_execute_restore_mask": READ_EXECUTE_RESTORE,
            "dacl_write_policy": DACL_WRITE_POLICY,
            "dacl_mismatch_count": 0,
            "entry_count": len(self.entries),
            "protected": False,
            "dacl_mutation_started": False,
            "effective_rights_checked": False,
            "dacl_restored": False,
            "inventories_unchanged": False,
            "snapshots": [],
        }
        evidence.mkdir()
        write_json(evidence / "sdk-readonly.json", self.report)

    def prepare(self):
        self.snapshot("before")
        self.before = self.current
        for number, relative, path, identity in self.entries:
            descriptor = self.backend.read(path)
            protected, _ = protected_descriptor(descriptor, self.backend.sid)
            require(
                self.backend.allowed(descriptor, READ_EXECUTE_RESTORE),
                "SDK input lacks read/execute/DACL restoration access: " + relative,
            )
            self.saved.append(
                {
                    "root": number,
                    "relative": relative,
                    "identity": identity,
                    "descriptor": descriptor,
                    "protected": protected,
                    "write_api": dacl_write_api(descriptor),
                }
            )
        write_gzip(
            self.evidence / "original-dacls.jsonl.gz",
            (
                {
                    "root": entry["root"],
                    "relative": entry["relative"],
                    "identity": entry["identity"],
                    "descriptor": base64.b64encode(entry["descriptor"]).decode(),
                    "original_dacl": dacl_identity(entry["descriptor"]),
                    "protected_dacl": dacl_identity(entry["protected"]),
                    "write_api": entry["write_api"],
                }
                for entry in self.saved
            ),
        )
        self.prepared = True

    def readback_equal(self, entry, observed, expected, stage):
        if dacl_identity(observed) == dacl_identity(expected):
            return True
        self.report["dacl_mismatch_count"] += 1
        if len(self.mismatches) < 20:
            self.mismatches.append(
                {
                    "stage": stage,
                    "root": entry["root"],
                    "relative": entry["relative"],
                    "write_api": entry["write_api"],
                    "expected_dacl": dacl_identity(expected),
                    "observed_dacl": dacl_identity(observed),
                    "expected_control": acl_parts(expected)[0],
                    "observed_control": acl_parts(observed)[0],
                    "observed_descriptor": base64.b64encode(observed).decode(),
                }
            )
            write_json(self.evidence / "dacl-readback-mismatches.json", self.mismatches)
        return False

    def snapshot(self, stage):
        require(
            re.fullmatch(r"[a-z][a-z0-9-]{0,47}", stage) is not None, "Invalid SDK snapshot stage"
        )
        require(
            stage not in [item["stage"] for item in self.report["snapshots"]], "Repeated SDK stage"
        )
        require(len(self.report["snapshots"]) < 12, "Too many SDK snapshots")
        self.current, records = [], []
        for number, root in enumerate(self.roots):
            inventory = self.helper.inventory(root)
            self.current.append(inventory)
            filename = f"{stage}-{number}.json.gz"
            write_gzip(self.evidence / filename, (inventory,))
            records.append(
                {
                    "name": filename,
                    "sha256": digest(self.evidence / filename),
                    "file_count": len(inventory["files"]),
                    "directory_count": len(inventory["directories"]),
                }
            )
        self.report["snapshots"].append({"stage": stage, "inventories": records})
        if self.before:
            write_json(
                self.evidence / (stage + "-delta.json"),
                [
                    inventory_delta(before, after)
                    for before, after in zip(self.before, self.current)
                ],
            )

    def apply(self):
        require(
            self.prepared and len(self.saved) == len(self.entries),
            "All original SDK DACLs must be saved before application",
        )
        self.application_started = self.report["dacl_mutation_started"] = True
        observed_rows = []
        for entry in self.saved:
            path = self.roots[entry["root"]] / entry["relative"]
            require(physical(path) == entry["identity"], "SDK entry changed before DACL protection")
            self.backend.write(path, entry["protected"])
            observed = self.backend.read(path)
            require(
                self.readback_equal(entry, observed, entry["protected"], "protected"),
                "SDK protected DACL readback differs: " + entry["relative"],
            )
            require(
                self.backend.allowed(observed, READ_EXECUTE_RESTORE),
                "SDK protection removed read/execute/DACL restoration access",
            )
            denied = [not self.backend.allowed(observed, mask) for mask in MUTATION_RIGHTS]
            require(all(denied), "SDK mutation access remains effective: " + entry["relative"])
            observed_rows.append(
                {
                    "root": entry["root"],
                    "relative": entry["relative"],
                    "dacl": dacl_identity(observed),
                    "mutation_denied": denied,
                    "read_execute_restore_allowed": True,
                }
            )
        write_gzip(self.evidence / "protected-dacls.jsonl.gz", observed_rows)
        self.report["protected"] = self.report["effective_rights_checked"] = True
        self.snapshot("protected")
        require(self.current == self.before, "SDK inputs changed while applying runtime protection")

    def finish(self, error):
        failures = []
        try:
            self.snapshot("after-runtime")
        except BaseException as snapshot_error:
            failures.append("after-runtime: " + str(snapshot_error)[:300])
        # Before application starts, no DACL write is needed or safe: a
        # preparation error may leave descendants without saved descriptors.
        # Once application starts, every original has already been saved.
        if self.application_started:
            for entry in self.saved:
                path = self.roots[entry["root"]] / entry["relative"]
                try:
                    require(physical(path) == entry["identity"], "SDK entry identity changed")
                    self.backend.write(path, entry["descriptor"])
                except BaseException as restore_error:
                    if len(failures) < 20:
                        failures.append(entry["relative"][:180] + ": " + str(restore_error)[:180])
        verified = 0
        restored_rows = []
        for entry in self.saved:
            path = self.roots[entry["root"]] / entry["relative"]
            try:
                descriptor = self.backend.read(path)
                observed = dacl_identity(descriptor)
                require(
                    self.readback_equal(entry, descriptor, entry["descriptor"], "restored"),
                    "Original SDK DACL readback differs",
                )
                restored_rows.append(
                    {"root": entry["root"], "relative": entry["relative"], "dacl": observed}
                )
                verified += 1
            except BaseException as readback_error:
                if len(failures) < 20:
                    failures.append(entry["relative"][:180] + ": " + str(readback_error)[:180])
        write_gzip(self.evidence / "restored-dacls.jsonl.gz", restored_rows)
        self.report["dacl_restored"] = verified == len(self.saved)
        try:
            self.snapshot("restored")
            self.report["inventories_unchanged"] = self.current == self.before
        except BaseException as snapshot_error:
            failures.append("restored: " + str(snapshot_error)[:300])
        if error is not None:
            self.report["runtime_error"] = type(error).__name__ + ": " + str(error)[:500]
        if failures:
            self.report["protection_errors"] = failures[:20]
        if (
            error is None
            and not failures
            and all(
                self.report[key]
                for key in (
                    "protected",
                    "dacl_mutation_started",
                    "effective_rights_checked",
                    "dacl_restored",
                    "inventories_unchanged",
                )
            )
        ):
            self.report["status"] = "preserved"
        self.report["evidence_sha256"] = {
            path.name: digest(path)
            for path in sorted(self.evidence.iterdir())
            if path.is_file() and path.name != "sdk-readonly.json"
        }
        write_json(self.evidence / "sdk-readonly.json", self.report)
        require(
            self.report["status"] == "preserved" or error is not None,
            "SDK runtime protection/preservation failed; inspect sdk-readonly.json",
        )
        require(self.report["dacl_restored"], "SDK original DACL restoration failed")


@contextmanager
def protect(roots, evidence_dir, helper, *, backend=None, purpose="native-capture"):
    """Protect already-restored SDK inputs only while native processes run."""
    require(
        sys.platform == "win32"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == "zukomgwili/FreeCAD",
        "SDK DACL protection is restricted to disposable own-repository Windows CI",
    )
    security = backend or WindowsSecurity()
    policy = None
    error = None
    try:
        policy = Policy(roots, Path(evidence_dir), helper, security, purpose)
        policy.prepare()
        policy.apply()
        yield policy
    except BaseException as caught:
        error = caught
        raise
    finally:
        try:
            if policy is not None:
                policy.finish(error)
        finally:
            security.close()


def validate_receipt(report, roots=None, source_sha256=None, purpose="native-capture"):
    """Portable strict admission of a completed producer protection receipt."""
    require(
        isinstance(report, dict)
        and purpose in ("native-capture", "preflight")
        and report.get("purpose") == purpose,
        "Invalid SDK protection receipt/purpose",
    )
    require(
        report.get("schema_version") == 1
        and report.get("status") == "preserved"
        and report.get("qualified") is False,
        "SDK protection receipt did not preserve inputs",
    )
    require(
        report.get("source_sha256") == (source_sha256 or digest(__file__)),
        "SDK protection helper changed",
    )
    require(
        report.get("deny_mask") == DENY_MASK
        and report.get("read_execute_restore_mask") == READ_EXECUTE_RESTORE
        and report.get("dacl_write_policy") == DACL_WRITE_POLICY
        and type(report.get("dacl_mismatch_count")) is int
        and report["dacl_mismatch_count"] == 0,
        "SDK protection rights changed",
    )
    require(
        all(
            report.get(key) is True
            for key in (
                "protected",
                "dacl_mutation_started",
                "effective_rights_checked",
                "dacl_restored",
                "inventories_unchanged",
            )
        ),
        "Incomplete SDK protection/restoration checks",
    )
    require(
        not report.get("runtime_error") and not report.get("protection_errors"),
        "SDK protection receipt contains failures",
    )
    recorded = report.get("roots")
    require(
        isinstance(recorded, list)
        and 1 <= len(recorded) <= 3
        and all(isinstance(root, str) and PureWindowsPath(root).is_absolute() for root in recorded)
        and len({root.casefold() for root in recorded}) == len(recorded),
        "Invalid SDK protection roots",
    )
    if roots is not None:
        require(recorded == [str(root) for root in roots], "SDK protection roots changed")
    require(
        type(report.get("entry_count")) is int and 0 < report["entry_count"] <= MAX_ENTRIES,
        "Invalid SDK protection entry count",
    )
    require(
        re.fullmatch(r"S-1-\d+(?:-\d+){1,15}", report.get("sid", "")) is not None,
        "Invalid SDK protection runner SID",
    )
    snapshots = report.get("snapshots", [])
    stages = [item.get("stage") for item in snapshots]
    expected_stages = (
        ["before", "protected", "actual-denial-probes", "after-runtime", "restored"]
        if purpose == "preflight"
        else [
            "before",
            "protected",
            "baseline-finished",
            "patched-finished",
            "after-runtime",
            "restored",
        ]
    )
    require(stages == expected_stages, "Missing/reordered SDK protection snapshots")
    for snapshot in snapshots:
        rows = snapshot.get("inventories", [])
        require(len(rows) == len(recorded), "Missing SDK input snapshot")
        for number, row in enumerate(rows):
            require(
                row.get("name") == f"{snapshot['stage']}-{number}.json.gz"
                and re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", "")) is not None
                and type(row.get("file_count")) is int
                and row["file_count"] > 0
                and type(row.get("directory_count")) is int
                and row["directory_count"] >= 0,
                "Invalid SDK snapshot receipt",
            )
    evidence = report.get("evidence_sha256", {})
    require(
        isinstance(evidence, dict)
        and {
            "original-dacls.jsonl.gz",
            "protected-dacls.jsonl.gz",
            "restored-dacls.jsonl.gz",
        }.issubset(evidence)
        and all(
            PurePosixPath(name).name == name and re.fullmatch(r"[0-9a-f]{64}", sha) is not None
            for name, sha in evidence.items()
        ),
        "Invalid SDK protection evidence index",
    )
    return report


def sid_from_text(value):
    require(re.fullmatch(r"S-1-\d+(?:-\d+){1,15}", value) is not None, "Invalid runner SID")
    parts = [int(part) for part in value[4:].split("-")]
    authority, values = parts[0], parts[1:]
    require(
        authority < 2**48 and all(value < 2**32 for value in values), "Invalid runner SID values"
    )
    return (
        bytes((1, len(values)))
        + authority.to_bytes(6, "big")
        + struct.pack("<" + "L" * len(values), *values)
    )


def manifest_rows(path):
    rows = [json.loads(line) for line in read_gzip(path).splitlines()]
    require(0 < len(rows) <= MAX_ENTRIES, "Invalid SDK DACL manifest count")
    keys = []
    for row in rows:
        root, name = row.get("root"), row.get("relative")
        require(
            type(root) is int
            and 0 <= root < 3
            and isinstance(name, str)
            and (
                name == "."
                or (
                    not PurePosixPath(name).is_absolute()
                    and not any(part in ("", ".", "..") for part in name.split("/"))
                    and "\\" not in name
                    and ":" not in name
                )
            ),
            "Unsafe SDK DACL manifest path",
        )
        keys.append((root, name.casefold()))
    require(len(set(keys)) == len(keys), "Colliding SDK DACL manifest entries")
    return rows


def validate_evidence(
    report_path, *, roots=None, inventories=None, source_sha256=None, purpose="native-capture"
):
    """Portable byte readback; no recorded Windows paths are opened or repaired."""
    report_path = Path(report_path)
    physical(report_path)
    require(
        report_path.name == "sdk-readonly.json" and report_path.stat().st_size <= 1024 * 1024,
        "Invalid SDK protection report path/size",
    )
    report = validate_receipt(json.loads(report_path.read_bytes()), roots, source_sha256, purpose)
    evidence = report_path.parent
    index = report["evidence_sha256"]
    require(
        {path.name for path in evidence.iterdir()} == set(index) | {report_path.name},
        "SDK protection evidence membership changed",
    )
    for name, sha in index.items():
        path = evidence / name
        require(
            not physical(path)[2] and digest(path) == sha,
            "SDK protection evidence bytes changed: " + name,
        )
    before = []
    for snapshot in report["snapshots"]:
        observed = []
        for row in snapshot["inventories"]:
            require(index.get(row["name"]) == row["sha256"], "SDK snapshot digest differs")
            inventory = json.loads(read_gzip(evidence / row["name"]))
            require(
                set(inventory) == {"files", "directories"}
                and len(inventory["files"]) == row["file_count"]
                and len(inventory["directories"]) == row["directory_count"],
                "SDK snapshot inventory count changed",
            )
            names = list(inventory["files"]) + inventory["directories"]
            require(
                len({name.casefold() for name in names}) == len(names)
                and all(
                    name != "."
                    and not PurePosixPath(name).is_absolute()
                    and "\\" not in name
                    and ":" not in name
                    and not any(part in ("", ".", "..") for part in name.split("/"))
                    for name in names
                ),
                "Unsafe SDK snapshot inventory path",
            )
            for metadata in inventory["files"].values():
                require(
                    set(metadata) == {"size", "mtime_ns", "sha256"}
                    and type(metadata["size"]) is int
                    and metadata["size"] >= 0
                    and type(metadata["mtime_ns"]) is int
                    and re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is not None,
                    "Invalid SDK snapshot file receipt",
                )
            observed.append(inventory)
        if snapshot["stage"] == "before":
            before = observed
            if inventories is not None:
                require(
                    before == inventories, "SDK protection inputs differ from admitted originals"
                )
        else:
            require(observed == before, "SDK inputs changed in runtime protection snapshot")
            delta = snapshot["stage"] + "-delta.json"
            require(
                delta in index
                and json.loads((evidence / delta).read_bytes())
                == [inventory_delta(left, right) for left, right in zip(before, observed)],
                "SDK protection delta changed",
            )
    original = manifest_rows(evidence / "original-dacls.jsonl.gz")
    protected = manifest_rows(evidence / "protected-dacls.jsonl.gz")
    restored = manifest_rows(evidence / "restored-dacls.jsonl.gz")
    expected = {
        (number, name)
        for number, inventory in enumerate(before)
        for name in [".", *inventory["files"], *inventory["directories"]]
    }
    keys = {(row["root"], row["relative"]) for row in original}
    require(
        len(original) == report["entry_count"]
        and keys == expected
        and [[(row["root"], row["relative"]) for row in rows] for rows in (protected, restored)]
        == [[(row["root"], row["relative"]) for row in original]] * 2,
        "Incomplete or reordered SDK DACL readback manifests",
    )
    sid = sid_from_text(report["sid"])
    for saved, applied, final in zip(original, protected, restored):
        descriptor = base64.b64decode(saved["descriptor"], validate=True)
        protected_sd, _ = protected_descriptor(descriptor, sid)
        identity = saved["identity"]
        require(
            isinstance(identity, list)
            and len(identity) == 3
            and all(type(value) is int and value >= 0 for value in identity[:2])
            and type(identity[2]) is bool
            and identity[2]
            == (
                saved["relative"] == "."
                or saved["relative"] in before[saved["root"]]["directories"]
            ),
            "Invalid SDK original physical identity",
        )
        require(
            saved["original_dacl"] == dacl_identity(descriptor)
            and saved["write_api"] == dacl_write_api(descriptor)
            and saved["protected_dacl"] == dacl_identity(protected_sd)
            and applied["dacl"] == saved["protected_dacl"]
            and final["dacl"] == saved["original_dacl"]
            and applied["mutation_denied"] == [True] * len(MUTATION_RIGHTS)
            and applied["read_execute_restore_allowed"] is True,
            "SDK DACL/effective access proof changed",
        )
    return report


def validate_preflight_report(report, protection_path):
    """Authenticate the exact public Windows denial-probe receipt portably.

    CPython's FileIO opens use the C runtime and report errno without winerror;
    the remaining filesystem probes expose Windows ERROR_ACCESS_DENIED too.
    This same contract must pass before restoration and during native capture.
    """
    protection = Path(protection_path)
    require(
        not physical(protection)[2]
        and protection.name == "sdk-readonly.json"
        and protection.stat().st_size <= 1024 * 1024,
        "Invalid preflight protection report path/size",
    )
    expected_operations = (
        "overwrite",
        "append",
        "create",
        "create-directory",
        "mtime",
        "delete",
        "rename",
    )
    require(
        isinstance(report, dict)
        and set(report)
        == {
            "schema_version",
            "status",
            "qualified",
            "source_sha256",
            "operations",
            "protection_sha256",
        }
        and type(report["schema_version"]) is int
        and report["schema_version"] == 1
        and report["status"] == "passed"
        and report["qualified"] is False
        and report["source_sha256"] == digest(__file__)
        and report["protection_sha256"] == digest(protection)
        and isinstance(report["operations"], list)
        and len(report["operations"]) == len(expected_operations),
        "Real Windows SDK protection preflight differs",
    )
    for number, (entry, operation) in enumerate(zip(report["operations"], expected_operations)):
        require(
            isinstance(entry, dict)
            and set(entry) == {"operation", "denied", "errno", "winerror"}
            and entry["operation"] == operation
            and entry["denied"] is True
            and type(entry["errno"]) is int
            and entry["errno"] == errno.EACCES
            and (
                entry["winerror"] is None
                if number < 3
                else type(entry["winerror"]) is int and entry["winerror"] == 5
            ),
            "Real Windows SDK protection preflight differs: " + operation,
        )
    return report


def preflight(work_dir, helper):
    """Real Windows enforcement/restoration probe before costly SDK restoration.

    Uses only a fresh, owned tiny fixture; no SDK files or application binaries
    are read, executed or modified. Failure must stop the subsequent capture.
    """
    work = Path(work_dir)
    require(
        not work.exists() and work.is_absolute() and work.parent.resolve() == work.parent,
        "DACL preflight needs a fresh physical work directory",
    )
    work.mkdir()
    root = work / "input"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    path = nested / "probe.bin"
    path.write_bytes(b"SDK runtime protection probe\x00\xff\n")
    original = path.read_bytes()
    operations = []
    with protect([root], work / "evidence", helper, purpose="preflight") as policy:
        require(path.read_bytes() == original, "Protected input is not readable")
        attempts = {
            "overwrite": lambda: path.write_bytes(b"changed"),
            "append": lambda: append_probe(path),
            "create": lambda: (nested / "new.bin").write_bytes(b"new"),
            "create-directory": lambda: (nested / "new-directory").mkdir(),
            "mtime": lambda: os.utime(path, ns=(1, 1)),
            "delete": lambda: path.unlink(),
            "rename": lambda: path.rename(nested / "moved.bin"),
        }
        for name, operation in attempts.items():
            try:
                operation()
            except PermissionError as error:
                operations.append(
                    {
                        "operation": name,
                        "denied": True,
                        "errno": error.errno,
                        "winerror": error.winerror,
                    }
                )
            else:
                raise ValueError("Actual Windows SDK mutation was not denied: " + name)
        policy.snapshot("actual-denial-probes")
    report = {
        "schema_version": 1,
        "status": "passed",
        "qualified": False,
        "source_sha256": digest(__file__),
        "operations": operations,
        "protection_sha256": digest(work / "evidence/sdk-readonly.json"),
    }
    write_json(work / "preflight.json", report)
    validate_preflight_report(report, work / "evidence/sdk-readonly.json")
    validate_evidence(work / "evidence/sdk-readonly.json", roots=[root], purpose="preflight")
    return work / "preflight.json"


def append_probe(path):
    with path.open("ab") as stream:
        stream.write(b"changed")
