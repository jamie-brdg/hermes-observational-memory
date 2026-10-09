"""Private, session-bound SQLite snapshots. Standard library only; no I/O on import.

The state revision is a CAS token and advances for source AND observation writes.
Generation changes on any logical state change, while identical writes are no-ops. Every write uses BEGIN IMMEDIATE so
independent connections/processes check the authoritative revision/tombstone.
A single bounded JSON snapshot keeps source membership and publication atomic.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading

from .contracts import canonical_json, validate_observations, validate_sources


_SCHEMA_VERSION = 1
_PAYLOAD_KEYS = ("sources", "observations", "covered_ids", "active_ids")
_MAX_RECALL = 4000
_MAX_SEARCH_RESULTS = 20
_MAX_QUERY = 1024
_EXCERPT_CHARS = 400


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum or value > 9223372036854775807:
        raise ValueError("invalid " + name)
    return value


def _identifier(value, name):
    if type(value) is not str or not value or not value.strip() or "\x00" in value:
        raise ValueError("invalid " + name)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("invalid " + name) from None
    return value


def _ids(values, name):
    if type(values) is not list:
        raise ValueError("invalid " + name)
    for value in values:
        _identifier(value, name)
    return list(values)


def _active_ids(values, observations):
    values = _ids(values, "active_ids")
    known = {item["id"] for item in observations}
    if len(set(values)) != len(values) or not set(values).issubset(known):
        raise ValueError("invalid active_ids")
    return values


def _private_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("memory store requires a private regular file")


def _directory(path, create=False):
    """Open each path component without following symlinks; return leaf fd."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            if component == "..":
                raise ValueError("parent traversal is not allowed in memory paths")
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except OSError:
                raise ValueError("memory directory is missing, unsafe or symlinked") from None
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("memory directory must be owner-only (0700)")
        return fd
    except BaseException:
        os.close(fd)
        raise


class MemoryStore:
    """One private database for exactly one profile/session pair.

    Missing recall IDs raise KeyError. Bad inputs, namespace/path violations
    and size limits raise ValueError. Closed or inherited-after-fork instances
    raise RuntimeError; open a fresh instance in each child process. Recall
    limits clamp to 4000 characters, search limits to 20 results. Disabled sync
    is a no-op returning the tombstone revision. Stale/disabled/non-prefix
    publication returns False; malformed observations/active IDs raise ValueError.
    """

    def __init__(self, path: Path, profile_key: str, session_id: str,
                 max_bytes: int = 67108864):
        self.profile_key = _identifier(profile_key, "profile_key")
        self.session_id = _identifier(session_id, "session_id")
        self.max_bytes = _integer(max_bytes, "max_bytes", 1)
        path = Path(path)
        if ".." in path.parts or not path.name:
            raise ValueError("invalid memory path")
        self.path = path if path.is_absolute() else Path.cwd() / path
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._conn = None
        self._dir_fd = None
        self._file_identity = None
        self._closed = False
        try:
            self._dir_fd = _directory(self.path.parent, create=True)
            # Sidecars are checked before SQLite can recover a journal.
            self._check_sidecars()
            self._prepare_file()
            self._check_files()
            self._conn = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, timeout=10,
                isolation_level=None, check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout=10000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.execute("PRAGMA trusted_schema=OFF")
            if self._conn.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("memory store requires DELETE journal mode")
            self._check_files()
            with self._transaction():
                objects = self._conn.execute(
                    "SELECT type, name FROM sqlite_master"
                ).fetchall()
                if objects:
                    if [(r[0], r[1]) for r in objects] != [("table", "memory_state")]:
                        raise ValueError("not a memory store database")
                    self._load()  # Verify namespace before any durable mutation.
                page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
                page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
                max_pages = self.max_bytes // page_size
                if max_pages < max(2, page_count):
                    raise ValueError("memory store size limit exceeded")
                actual = self._conn.execute(
                    "PRAGMA max_page_count=%d" % max_pages
                ).fetchone()[0]
                if actual > max_pages:
                    raise ValueError("memory store size limit exceeded")
                if not objects:
                    self._conn.execute("""
                        CREATE TABLE memory_state (
                            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                            schema_version INTEGER NOT NULL,
                            profile_key TEXT NOT NULL,
                            session_id TEXT NOT NULL,
                            revision INTEGER NOT NULL CHECK (revision >= 0),
                            generation INTEGER NOT NULL CHECK (generation >= 0),
                            disabled INTEGER NOT NULL CHECK (disabled IN (0, 1)),
                            payload TEXT NOT NULL
                        )
                    """)
                    self._conn.execute(
                        "INSERT INTO memory_state VALUES (1, ?, ?, ?, 0, 0, 0, ?)",
                        (_SCHEMA_VERSION, self.profile_key, self.session_id,
                         canonical_json({key: [] for key in _PAYLOAD_KEYS})),
                    )
        except BaseException:
            self.close()
            raise

    def _prepare_file(self):
        # Only SQLite may open/close a published database inode. On POSIX a
        # raw close would discard locks held by *other* SQLite connections in
        # this process, including connections outside MemoryStore.
        # Serialize cooperating constructors on the directory, never the DB.
        # Do not hold this lock while waiting for a SQLite transaction.
        assert self._dir_fd is not None
        fcntl.flock(self._dir_fd, fcntl.LOCK_EX)
        try:
            try:
                info = os.stat(self.path.name, dir_fd=self._dir_fd,
                               follow_symlinks=False)
            except FileNotFoundError:
                staging = ".memory-create-" + secrets.token_hex(16)
                published_identity = None
                fd = os.open(
                    staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode=0o600, dir_fd=self._dir_fd,
                )
                try:
                    try:
                        created = os.fstat(fd)
                        _private_file(created)
                    finally:
                        os.close(fd)  # Close BEFORE the inode is published.
                    try:
                        os.link(staging, self.path.name, src_dir_fd=self._dir_fd,
                                dst_dir_fd=self._dir_fd, follow_symlinks=False)
                    except FileExistsError:
                        pass  # Never overwrite a concurrently created path.
                    else:
                        published_identity = (created.st_dev, created.st_ino)
                finally:
                    os.unlink(staging, dir_fd=self._dir_fd)
                info = os.stat(self.path.name, dir_fd=self._dir_fd,
                               follow_symlinks=False)
                if (published_identity is not None
                        and (info.st_dev, info.st_ino) != published_identity):
                    raise ValueError("memory file was replaced")
            _private_file(info)
            self._file_identity = (info.st_dev, info.st_ino)
        finally:
            fcntl.flock(self._dir_fd, fcntl.LOCK_UN)

    def _check_sidecars(self):
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                info = os.stat(self.path.name + suffix, dir_fd=self._dir_fd,
                               follow_symlinks=False)
            except FileNotFoundError:
                continue
            _private_file(info)

    def _check_files(self):
        # Recheck the pathname, not only retained handles, before every operation.
        assert self._dir_fd is not None and self._file_identity is not None
        directory_fd = _directory(self.path.parent)
        try:
            current = os.fstat(directory_fd)
            opened = os.fstat(self._dir_fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("memory directory was replaced")
        finally:
            os.close(directory_fd)
        info = os.stat(self.path.name, dir_fd=self._dir_fd, follow_symlinks=False)
        _private_file(info)
        if (info.st_dev, info.st_ino) != self._file_identity:
            raise ValueError("memory file was replaced")
        if info.st_size > self.max_bytes:
            raise ValueError("memory store size limit exceeded")
        self._check_sidecars()

    def _check_process(self):
        if os.getpid() != self._pid:
            raise RuntimeError("reopen memory store after fork")

    def _ensure_open(self):
        if self._closed or self._conn is None:
            raise RuntimeError("memory store is closed")
        self._check_files()

    @contextmanager
    def _transaction(self):
        self._check_process()  # Before acquiring a potentially inherited lock.
        with self._lock:
            self._ensure_open()
            assert self._conn is not None
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield
                self._conn.execute("COMMIT")
            except BaseException as exc:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                # Python 3.9 lacks sqlite_errorcode; keep this narrow fallback.
                is_full = (getattr(exc, "sqlite_errorcode", None) == 13
                           or str(exc) == "database or disk is full")
                if isinstance(exc, sqlite3.OperationalError) and is_full:
                    raise ValueError("memory store size limit exceeded") from None
                raise

    def _load(self):
        assert self._conn is not None
        rows = self._conn.execute("SELECT * FROM memory_state").fetchall()
        if len(rows) != 1:
            raise ValueError("invalid memory state")
        row = rows[0]
        if (row["singleton"] != 1 or row["schema_version"] != _SCHEMA_VERSION
                or row["profile_key"] != self.profile_key
                or row["session_id"] != self.session_id):
            raise ValueError("memory store namespace or schema mismatch")
        try:
            payload = json.loads(row["payload"])
            if type(payload) is not dict or set(payload) != set(_PAYLOAD_KEYS):
                raise ValueError("invalid payload")
            sources = validate_sources(payload["sources"])
            covered = _ids(payload["covered_ids"], "covered_ids")
            if covered != [s["id"] for s in sources[:len(covered)]]:
                raise ValueError("invalid coverage")
            observations = validate_observations(
                payload["observations"], sources[:len(covered)]
            )
            if covered and not observations:
                raise ValueError("empty covered observations")
            active = _active_ids(payload["active_ids"], observations)
            revision = _integer(row["revision"], "revision")
            generation = _integer(row["generation"], "generation")
            if type(row["disabled"]) is not int or row["disabled"] not in (0, 1):
                raise ValueError("invalid disabled state")
            if row["disabled"] and any(payload.values()):
                raise ValueError("invalid disabled payload")
        except (ValueError, TypeError, KeyError, RecursionError):
            raise ValueError("invalid stored memory state") from None
        return {
            "revision": revision, "generation": generation,
            "disabled": bool(row["disabled"]), "sources": sources,
            "observations": observations, "covered_ids": covered, "active_ids": active,
        }

    def _save(self, state):
        assert self._conn is not None
        payload = canonical_json({key: state[key] for key in _PAYLOAD_KEYS})
        if len(payload.encode("utf-8")) > self.max_bytes:
            raise ValueError("memory store size limit exceeded")
        self._conn.execute(
            "UPDATE memory_state SET revision=?, generation=?, disabled=?, payload=? "
            "WHERE singleton=1",
            (state["revision"], state["generation"], int(state["disabled"]), payload),
        )

    def read(self) -> dict:
        self._check_process()
        with self._lock:
            self._ensure_open()
            return self._load()

    def sync_sources(self, sources) -> int:
        with self._transaction():
            state = self._load()
            if state["disabled"]:
                return state["revision"]
            sources = validate_sources(sources)
            if sources == state["sources"]:
                return state["revision"]
            common = 0
            for old, new in zip(state["sources"], sources):
                if old != new:
                    break
                common += 1
            covered = state["covered_ids"][:common]
            known = set(covered)
            observations = [o for o in state["observations"]
                            if set(o["source_ids"]).issubset(known)]
            # A retained prefix without any observation is not usable coverage.
            if covered and not observations:
                covered = []
            state["covered_ids"] = covered
            state["observations"] = observations
            valid_ids = {o["id"] for o in observations}
            state["active_ids"] = [oid for oid in state["active_ids"] if oid in valid_ids]
            state["sources"] = sources
            state["revision"] += 1
            state["generation"] += 1
            self._save(state)
            return state["revision"]

    def commit_observation(self, revision: int, covered_ids: list,
                           observations: list, active_ids: list) -> bool:
        with self._transaction():
            _integer(revision, "revision")
            state = self._load()
            if state["disabled"] or state["revision"] != revision:
                return False
            covered = _ids(covered_ids, "covered_ids")
            if covered != [s["id"] for s in state["sources"][:len(covered)]]:
                return False
            observations = validate_observations(
                observations, state["sources"][:len(covered)]
            )
            if covered and not observations:
                raise ValueError("nonempty coverage requires observations")
            active = _active_ids(active_ids, observations)
            if (covered == state["covered_ids"] and observations == state["observations"]
                    and active == state["active_ids"]):
                return True
            state.update(covered_ids=covered, observations=observations, active_ids=active)
            # CAS covers publication as well as source edits. Otherwise a second
            # worker observing the same source revision can replace a newer,
            # longer observation log with its stale shorter snapshot.
            state["revision"] += 1
            state["generation"] += 1
            self._save(state)
            return True

    def recall(self, source_id: str, offset: int = 0, limit: int = 4000) -> dict:
        self._check_process()
        with self._lock:
            self._ensure_open()
            _identifier(source_id, "source_id")
            offset = _integer(offset, "offset")
            limit = min(_integer(limit, "limit", 1), _MAX_RECALL)
            for item in self._load()["sources"]:
                if item["id"] == source_id:
                    text = item["text"][offset:offset + limit]
                    end = offset + len(text)
                    more = end < len(item["text"])
                    return {"source_id": source_id, "role": item["role"], "text": text,
                            "offset": offset, "next_offset": end if more else None,
                            "has_more": more}
            raise KeyError("source not found in this session")

    def search(self, query: str, limit: int = 8) -> list:
        self._check_process()
        with self._lock:
            self._ensure_open()
            if (type(query) is not str or not query.strip() or "\x00" in query
                    or len(query) > _MAX_QUERY):
                raise ValueError("invalid search query")
            limit = min(_integer(limit, "limit", 1), _MAX_SEARCH_RESULTS)
            query_folded = query.casefold()
            results = []
            for item in self._load()["sources"]:
                text = item["text"]
                folded = text.casefold()
                match = folded.find(query_folded)
                if match < 0:
                    continue
                # Casefold can expand a character (e.g. sharp-s). Map the match
                # to original codepoint offsets so excerpts remain exact text.
                if len(folded) == len(text):
                    position = match
                else:
                    position, folded_offset = 0, 0
                    for position, char in enumerate(text):
                        folded_offset += len(char.casefold())
                        if folded_offset > match:
                            break
                start = max(0, position - 80)
                end = min(len(text), start + _EXCERPT_CHARS)
                results.append({
                    "source_id": item["id"], "role": item["role"],
                    "text": text[start:end], "offset": start,
                    "next_offset": end if end < len(text) else None,
                    "has_more": end < len(text),
                })
                if len(results) == limit:
                    break
            return results

    def forget(self) -> None:
        with self._transaction():
            state = self._load()
            if state["disabled"]:
                return
            state.update({key: [] for key in _PAYLOAD_KEYS})
            state["disabled"] = True
            state["revision"] += 1
            state["generation"] += 1
            self._save(state)

    def close(self) -> None:
        self._check_process()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self._conn is not None:
                    self._conn.close()
            finally:
                self._conn = None
                if self._dir_fd is not None:
                    os.close(self._dir_fd)
                    self._dir_fd = None
