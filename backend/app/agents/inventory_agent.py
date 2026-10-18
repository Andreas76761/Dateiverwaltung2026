"""Erweiterung – Inventar-Agent: installierte Programme, LLM-Lösungen und lokale Modelle je Computer.

Liest nur (Paketmanager, Registry, Anwendungsordner, Modell-Caches). Es wird nichts installiert
oder entfernt.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .. import db
from ..jobs import Job

LLM_TOOLS = {
    "ollama": "Ollama", "lms": "LM Studio CLI", "llama-server": "llama.cpp", "llama-cli": "llama.cpp",
    "claude": "Claude Code", "codex": "OpenAI Codex CLI", "gemini": "Gemini CLI", "aider": "Aider",
    "jan": "Jan", "gpt4all": "GPT4All", "vllm": "vLLM", "localai": "LocalAI", "open-webui": "Open WebUI",
    "docker": "Docker", "python3": "Python", "node": "Node.js", "git": "Git", "code": "VS Code", "cursor": "Cursor",
    "nvidia-smi": "NVIDIA-Treiber/CUDA",
}
LLM_APP_KEYWORDS = ["ollama", "lm studio", "gpt4all", "jan", "anythingllm", "msty", "chatgpt", "claude", "copilot",
                    "cursor", "comfyui", "stable diffusion", "automatic1111", "invokeai", "pinokio", "open webui",
                    "whisper", "perplexity", "gemini", "mistral", "llama", "koboldcpp", "text-generation-webui"]
PY_AI_PACKAGES = ["torch", "tensorflow", "transformers", "diffusers", "langchain", "langgraph", "llama-index",
                  "llama_index", "openai", "anthropic", "ollama", "sentence-transformers", "chromadb", "faiss-cpu",
                  "vllm", "accelerate", "peft", "crewai", "autogen", "mcp", "google-genai"]
MODEL_DIRS = [
    ("~/.ollama/models/manifests", "Ollama"),
    ("~/.cache/lm-studio/models", "LM Studio"),
    ("~/.lmstudio/models", "LM Studio"),
    ("~/.cache/huggingface/hub", "Hugging Face"),
    ("~/AppData/Local/nomic.ai/GPT4All", "GPT4All"),
    ("~/jan/models", "Jan"),
]


_LLM_RX = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in LLM_APP_KEYWORDS) + r")(?![a-z0-9])")


def _kind_for(name: str) -> str:
    return "llm-tool" if _LLM_RX.search(name.lower()) else "programm"


def _run(cmd: list[str], timeout=20) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def windows_programs() -> list[dict]:
    import winreg  # type: ignore

    out = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, key in roots:
        try:
            with winreg.OpenKey(hive, key) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                            get = lambda n: winreg.QueryValueEx(sub, n)[0] if n else None
                            name = get("DisplayName")
                            out.append({"name": name, "version": _try(get, "DisplayVersion"), "publisher": _try(get, "Publisher"),
                                        "location": _try(get, "InstallLocation"), "source": "Registry"})
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def _try(fn, arg):
    try:
        return fn(arg)
    except OSError:
        return None


def mac_programs() -> list[dict]:
    out = []
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        for app in Path(base).glob("*.app"):
            out.append({"name": app.stem, "location": str(app), "source": "Applications"})
    return out


def linux_programs() -> list[dict]:
    out = []
    txt = _run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\t${Installed-Size}\n"])
    for line in txt.splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            out.append({"name": p[0], "version": p[1], "publisher": p[2] if len(p) > 2 else None,
                        "size": int(p[3]) * 1024 if len(p) > 3 and p[3].isdigit() else None, "source": "dpkg"})
    for line in _run(["snap", "list"]).splitlines()[1:]:
        p = line.split()
        if p:
            out.append({"name": p[0], "version": p[1] if len(p) > 1 else None, "source": "snap"})
    for line in _run(["flatpak", "list", "--app", "--columns=name,version"]).splitlines():
        p = line.split("\t")
        if p and p[0]:
            out.append({"name": p[0], "version": p[1] if len(p) > 1 else None, "source": "flatpak"})
    return out


def cli_tools() -> list[dict]:
    out = []
    for exe, label in LLM_TOOLS.items():
        path = shutil.which(exe)
        if path:
            ver = _run([exe, "--version"], timeout=8).strip().splitlines()
            kind = "llm-tool" if exe in ("ollama", "lms", "llama-server", "llama-cli", "claude", "codex", "gemini",
                                         "aider", "jan", "gpt4all", "vllm", "localai", "open-webui") else "dev-tool"
            out.append({"name": label, "version": ver[0][:60] if ver else None, "location": path, "kind": kind, "source": "PATH"})
    return out


def python_ai_packages() -> list[dict]:
    from importlib import metadata

    out = []
    for dist in metadata.distributions():
        n = (dist.metadata["Name"] or "").lower()
        if n in PY_AI_PACKAGES:
            out.append({"name": f"python: {n}", "version": dist.version, "kind": "llm-tool", "category": "Python-Bibliothek",
                        "source": "pip"})
    return out


def local_models() -> list[dict]:
    out = []
    txt = _run(["ollama", "list"])
    for line in txt.splitlines()[1:]:
        p = line.split()
        if p:
            out.append({"name": p[0], "version": p[1] if len(p) > 1 else None, "kind": "llm-modell",
                        "category": "Ollama", "source": "ollama list"})
    for d, label in MODEL_DIRS:
        base = Path(os.path.expanduser(d))
        if not base.is_dir():
            continue
        if label == "Hugging Face":
            for m in base.glob("models--*"):
                out.append({"name": m.name.replace("models--", "").replace("--", "/"), "kind": "llm-modell",
                            "category": label, "location": str(m), "source": "HF-Cache"})
        else:
            for m in list(base.rglob("*.gguf"))[:200]:
                out.append({"name": m.name, "kind": "llm-modell", "category": label, "location": str(m),
                            "size": m.stat().st_size, "source": "Modellordner"})
    # Modelle, die beim Datei-Scan gefunden wurden
    for f in db.query("SELECT computer_id, name, path, size FROM files WHERE file_type='KI-Modell' AND missing=0"):
        out.append({"computer_id": f["computer_id"], "name": f["name"], "kind": "llm-modell", "category": "Datei-Scan",
                    "location": f["path"], "size": f["size"], "source": "Datei-Scan"})
    return out


def collect() -> list[dict]:
    system = platform.system()
    try:
        progs = windows_programs() if system == "Windows" else mac_programs() if system == "Darwin" else linux_programs()
    except Exception:
        progs = []
    for p in progs:
        p.setdefault("kind", _kind_for(p.get("name") or ""))
    return [p for p in progs + cli_tools() + python_ai_packages() + local_models() if p.get("name")]


def store(computer_id: str, items: list[dict]) -> int:
    ts = db.now()
    with db.tx() as c:
        for it in items:
            c.execute(
                """INSERT INTO programs(computer_id, name, version, publisher, kind, category, location, size, source, seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(computer_id, name, kind, location) DO UPDATE SET version=excluded.version,
                   publisher=excluded.publisher, category=excluded.category, size=excluded.size, seen_at=excluded.seen_at""",
                (it.get("computer_id") or computer_id, it["name"], it.get("version"), it.get("publisher"),
                 it.get("kind", "programm"), it.get("category"), it.get("location") or "", it.get("size"),
                 it.get("source"), ts),
            )
    return len(items)


def run(job: Job, params: dict) -> dict:
    from ..config import get_settings

    # Der Server inventarisiert sich selbst; andere Computer liefern per Agent (POST /api/agents/inventory).
    computer_id = params.get("computer_id") or next(
        (c["id"] for c in get_settings().computers if c["mode"] == "local"), "server")
    job.update(message=f"Inventar wird erfasst ({platform.system()}) …")
    items = collect()
    n = store(computer_id, items)
    kinds: dict[str, int] = {}
    for it in items:
        kinds[it.get("kind", "programm")] = kinds.get(it.get("kind", "programm"), 0) + 1
    job.update(progress=n, total=n, message="Inventar erfasst")
    return {"einträge": n, "computer": computer_id, "je_art": kinds}


if __name__ == "__main__":
    print(json.dumps(collect()[:20], indent=2, ensure_ascii=False))
