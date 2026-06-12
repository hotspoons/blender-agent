# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Filesystem-backed agent store, ported from Foyer Studio's
``foyer-agent/src/store.rs``: configuration, conversation sessions
(JSONL transcripts), the markdown skills library, and agent memory.

Layout under the data dir (default ``$XDG_DATA_HOME/blender-agent``)::

    config.json
    memory.md
    skills/<name>/SKILL.md
    sessions/<id>/transcript.jsonl
    sessions/<id>/media/<short-id>.<ext>

Skills are backed by the core blmcp skill index (Anthropic SKILL.md
layout): this store's ``skills/`` folder is registered as one source among
builtin/drop-folder/git-repo/extension collections, and legacy flat
``skills/<name>.md`` files migrate to folders on startup.
"""

__all__ = (
    "AgentConfig",
    "AgentStore",
    "SessionBusyError",
    "Skill",
    "search_skills",
)

import contextlib
import dataclasses
import json
import os
import re
import time
import uuid

from typing import Any, Iterator

# Advisory file locking, cross-platform: flock on POSIX, byte-range
# locking on Windows. When neither is available the locks degrade to
# no-ops (single-window behavior, exactly what the code did before).
try:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
except ImportError:  # pragma: no cover - Windows
    try:
        import msvcrt

        def _lock_fd(fd: int) -> None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        def _unlock_fd(fd: int) -> None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except ImportError:
        def _lock_fd(fd: int) -> None:
            pass

        def _unlock_fd(fd: int) -> None:
            pass


class SessionBusyError(RuntimeError):
    """
    Another process holds this session's lock (a second agent window
    on the same session). The caller should surface this rather than
    corrupt the transcript.
    """


class _SessionLock:
    """
    Advisory lock on ``sessions/<id>/.lock``. The lock file is separate
    from the transcript so transcript replaces/deletes never drop a
    held lock. flock is per file description, so this object also
    carries a depth counter for same-process re-entrancy (managed by
    ``AgentStore.session_lock``).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.depth = 0
        self._fd: int | None = None

    def acquire(self, timeout: float) -> None:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock_fd(fd)
                self._fd = fd
                return
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise SessionBusyError(
                        "session is locked by another agent window") from None
                time.sleep(0.05)

    def release(self) -> None:
        if self._fd is not None:
            try:
                _unlock_fd(self._fd)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None



def _default_data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "blender-agent")


@dataclasses.dataclass
class AgentConfig:
    """
    Deployment knobs, persisted to ``config.json``. Environment
    variables override the stored values at load time.
    """

    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    # "ask" pauses destructive tool calls for confirmation; "auto" does not.
    autonomy: str = "ask"
    # Use the in-browser (Transformers.js) model when no endpoint is configured.
    use_local_llm: bool = True
    max_rounds: int = 16
    # At round-budget exhaustion, a context-blind reviewer judges the
    # worker's self-report and may replenish rounds (engine._budget_review).
    budget_review: bool = True
    # Context budget (tokens) for the conversation sent to the model;
    # the engine trims old exchanges to fit. Matters doubly for local
    # models: ORT-web decode slows with sequence length, so a tight
    # budget is also a throughput knob.
    context_tokens: int = 16_384

    @classmethod
    def load(cls, path: str) -> "AgentConfig":
        config = cls()
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                raw = {}
            # Pre-Transformers.js configs stored this under the engine name.
            if "use_local_llm" not in raw and "use_webllm" in raw:
                raw["use_local_llm"] = raw["use_webllm"]
            for field in dataclasses.fields(cls):
                if field.name in raw:
                    setattr(config, field.name, raw[field.name])
        config.endpoint = os.environ.get("BLENDER_AGENT_ENDPOINT", config.endpoint)
        config.model = os.environ.get("BLENDER_AGENT_MODEL", config.model)
        config.api_key = os.environ.get("BLENDER_AGENT_API_KEY", config.api_key)
        return config

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(dataclasses.asdict(self), fh, indent=2)

    def as_public(self) -> dict[str, object]:
        """
        Config as sent to the UI - the API key never leaves the server.
        """
        return {
            "endpoint": self.endpoint,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "autonomy": self.autonomy,
            "use_local_llm": self.use_local_llm,
            "max_rounds": self.max_rounds,
            "budget_review": self.budget_review,
            "context_tokens": self.context_tokens,
        }


@dataclasses.dataclass
class Skill:
    name: str
    summary: str
    body: str

    @classmethod
    def from_markdown(cls, name: str, text: str) -> "Skill":
        summary = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                summary = stripped
                break
        return cls(name=name, summary=summary, body=text)


# No underscore in the token class: identifiers like ``rig_hinge`` must
# match the words "rig" and "hinge".
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    # Naive plural stemming, applied identically to queries and skill text.
    return [
        t[:-1] if len(t) > 3 and t.endswith("s") else t
        for t in _WORD_RE.findall(text.lower())
    ]


def search_skills(skills: list[Skill], query: str, max_results: int = 5) -> list[tuple[Skill, int]]:
    """
    Rank skills against *query*: term frequency over the body, with
    name and summary hits weighted heavily.
    """
    terms = set(_tokenize(query))
    if not terms:
        return []
    scored: list[tuple[Skill, int]] = []
    for skill in skills:
        name_tokens = set(_tokenize(skill.name))
        summary_tokens = set(_tokenize(skill.summary))
        body_tokens = _tokenize(skill.body)
        score = 0
        for term in terms:
            if term in name_tokens:
                score += 50
            if term in summary_tokens:
                score += 20
            score += min(body_tokens.count(term), 10)
        if score > 0:
            scored.append((skill, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0].name))
    return scored[:max_results]


class AgentStore:
    """
    Owns the on-disk agent state. Synchronous I/O on small files; call
    sites run inside request handlers where this is acceptable.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or os.environ.get("BLENDER_AGENT_DATA_DIR") or _default_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self._config_path = os.path.join(self.data_dir, "config.json")
        self.config = AgentConfig.load(self._config_path)
        # Held session locks, for same-process re-entrancy (one store
        # per process; everything runs on the asyncio loop thread).
        self._session_locks: dict[str, _SessionLock] = {}
        self._migrate_legacy_skills()
        self._register_skills_source()

    # ------------------------------------------------------------------
    # Config.

    def save_config(self) -> None:
        self.config.save(self._config_path)

    # ------------------------------------------------------------------
    # Skills.

    @property
    def skills_dir(self) -> str:
        return os.path.join(self.data_dir, "skills")

    def _migrate_legacy_skills(self) -> None:
        """
        One-time migration: flat ``skills/<name>.md`` files (the pre-core
        store format, including previously seeded examples) become
        Anthropic-layout ``skills/<name>/SKILL.md`` folders. The bundled
        examples themselves now ship with core blmcp ("builtin" source),
        so seeding is gone; user-saved copies migrate and override them.
        """
        os.makedirs(self.skills_dir, exist_ok=True)
        for filename in sorted(os.listdir(self.skills_dir)):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(self.skills_dir, filename)
            if not os.path.isfile(path):
                continue
            name = filename[:-3]
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                self.save_skill(name, text)
                os.remove(path)
            except OSError:
                continue

    def _register_skills_source(self) -> None:
        """
        Contribute this store's skills folder to the core blmcp skill
        index. Runtime sources scan last, so user-saved skills override
        builtins of the same name.
        """
        from blmcp.skills import register_skills_source
        register_skills_source("agent-store", self.skills_dir)

    @staticmethod
    def _core_index():
        from blmcp.skills import ensure_index
        return ensure_index()

    def list_skills(self) -> list[Skill]:
        """
        Every skill visible to the agent, via the core index: builtin,
        drop-folder, configured dirs/git repos, tools extensions, and this
        store's own saved skills.
        """
        skills = []
        for core_skill in sorted(self._core_index().skills.values(), key=lambda s: s.name):
            try:
                body = core_skill.body()
            except OSError:
                continue
            skills.append(Skill(name=core_skill.name, summary=core_skill.description, body=body))
        return skills

    def get_skill(self, name: str) -> Skill | None:
        core_skill = self._core_index().skills.get(name)
        if core_skill is None:
            return None
        try:
            body = core_skill.body()
        except OSError:
            return None
        return Skill(name=core_skill.name, summary=core_skill.description, body=body)

    def save_skill(self, name: str, body: str) -> None:
        """
        Write ``skills/<name>/SKILL.md`` (Anthropic layout). A frontmatter
        block is added when *body* lacks one, deriving the description from
        the first non-heading line; the core index is refreshed so the
        skill is immediately visible everywhere.
        """
        safe = os.path.basename(name)
        skill_folder = os.path.join(self.skills_dir, safe)
        os.makedirs(skill_folder, exist_ok=True)
        if not body.startswith("---"):
            description = ""
            for line in body.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped
                    break
            body = "---\nname: {:s}\ndescription: {:s}\n---\n\n{:s}".format(
                safe, description, body)
        with open(os.path.join(skill_folder, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(body)

        from blmcp.skills import ensure_index
        ensure_index(refresh=True)

    # ------------------------------------------------------------------
    # Memory.

    @property
    def _memory_path(self) -> str:
        return os.path.join(self.data_dir, "memory.md")

    def read_memory(self) -> str:
        if not os.path.isfile(self._memory_path):
            return ""
        with open(self._memory_path, encoding="utf-8") as fh:
            return fh.read()

    def write_memory(self, text: str) -> None:
        with open(self._memory_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    # ------------------------------------------------------------------
    # Sessions.

    @property
    def sessions_dir(self) -> str:
        return os.path.join(self.data_dir, "sessions")

    def session_dir(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, os.path.basename(session_id))

    def new_session_id(self) -> str:
        return "{:s}-{:s}".format(time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])

    def list_sessions(self) -> list[dict[str, object]]:
        """
        Session metadata, most recently modified first.
        """
        sessions: list[dict[str, object]] = []
        if not os.path.isdir(self.sessions_dir):
            return sessions
        for session_id in os.listdir(self.sessions_dir):
            transcript = os.path.join(self.sessions_dir, session_id, "transcript.jsonl")
            if not os.path.isfile(transcript):
                continue
            title = ""
            try:
                with open(transcript, encoding="utf-8") as fh:
                    for line in fh:
                        record = json.loads(line)
                        if record.get("role") == "user":
                            title = str(record.get("content", ""))[:80]
                            break
            except (OSError, ValueError):
                pass
            sessions.append({
                "id": session_id,
                "title": title or "(empty session)",
                "modified": os.path.getmtime(transcript),
            })
        sessions.sort(key=lambda s: -float(str(s["modified"])))
        return sessions

    @contextlib.contextmanager
    def session_lock(self, session_id: str, timeout: float = 15.0) -> Iterator[None]:
        """
        Hold the session's cross-process advisory lock. Re-entrant
        within this store, so locked code can call ``append_record`` /
        ``load_records`` freely. Use for multi-step critical sections -
        compaction holds it across its summarization request so the
        ``covers_count`` it computes cannot be invalidated by another
        window appending mid-flight. Raises :class:`SessionBusyError`
        when the lock cannot be acquired in *timeout* seconds.
        """
        sid = os.path.basename(session_id)
        held = self._session_locks.get(sid)
        if held is not None:
            held.depth += 1
            try:
                yield
            finally:
                held.depth -= 1
            return
        directory = self.session_dir(sid)
        os.makedirs(directory, exist_ok=True)
        lock = _SessionLock(os.path.join(directory, ".lock"))
        lock.acquire(timeout)
        lock.depth = 1
        self._session_locks[sid] = lock
        try:
            yield
        finally:
            self._session_locks.pop(sid, None)
            lock.release()

    def append_record(
            self,
            session_id: str,
            record: dict[str, Any],
            timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """
        Append under the session lock and return the freshly re-read
        transcript: with several windows on one session, the on-disk
        file is the merge point, so every write op hands back the true
        record list for the engine to adopt. Raises
        :class:`SessionBusyError` when another window holds the lock
        past *timeout* (e.g. its long compaction step).
        """
        directory = self.session_dir(session_id)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "transcript.jsonl")
        with self.session_lock(session_id, timeout=timeout):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
                fh.flush()
            return self._read_transcript(path)

    def load_records(self, session_id: str) -> list[dict[str, Any]]:
        path = os.path.join(self.session_dir(session_id), "transcript.jsonl")
        if not os.path.isfile(path):
            return []
        try:
            with self.session_lock(session_id, timeout=1.0):
                return self._read_transcript(path)
        except SessionBusyError:
            # Viewing must never block on a window that is writing (or
            # holding the long compaction lock). Append-only JSONL
            # tolerates lockless reads: a torn tail line just fails
            # json.loads and is skipped.
            return self._read_transcript(path)

    @staticmethod
    def _read_transcript(path: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not os.path.isfile(path):
            return records
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
        return records

    def delete_session(self, session_id: str) -> None:
        import shutil

        directory = self.session_dir(session_id)
        if os.path.isdir(directory):
            shutil.rmtree(directory)
