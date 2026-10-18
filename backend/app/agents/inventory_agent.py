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
                            est = _try(get, "EstimatedSize")  # KB
                            out.append({"name": name, "version": _try(get, "DisplayVersion"), "publisher": _try(get, "Publisher"),
                                        "location": _try(get, "InstallLocation"), "source": "Registry",
                                        "size": int(est) * 1024 if isinstance(est, int) else None})
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


def _quick_fp(path: Path, size: int) -> str | None:
    """Schneller Fingerabdruck großer Modelldateien: Größe + SHA-256 über erstes und letztes MB."""
    import hashlib
    try:
        h = hashlib.sha256(str(size).encode())
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 20))
            if size > 2 << 20:
                fh.seek(-(1 << 20), 2)
                h.update(fh.read(1 << 20))
        return "q:" + h.hexdigest()[:32]
    except OSError:
        return None


def _dir_size(p: Path, limit_files: int = 20000) -> int:
    total = 0
    for i, f in enumerate(p.rglob("*")):
        if i > limit_files:
            break
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def ollama_models() -> list[dict]:
    """Ollama-Modelle direkt aus den Manifesten (auch wenn Ollama gerade nicht läuft): Größe + Digest der Modellschicht."""
    root = Path(os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models"))
    man = root / "manifests"
    out = []
    if man.is_dir():
        for f in man.rglob("*"):
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rel = f.relative_to(man).parts  # registry/namespace/model/tag
            model, tag = rel[-2], rel[-1]
            ns = rel[-3] if len(rel) >= 3 else "library"
            name = f"{model}:{tag}" if ns == "library" else f"{ns}/{model}:{tag}"
            layers = data.get("layers") or []
            weights = next((l for l in layers if str(l.get("mediaType", "")).endswith(".model")), None)
            out.append({"name": name, "kind": "llm-modell", "category": "Ollama", "location": str(f),
                        "size": sum(int(l.get("size") or 0) for l in layers) or None, "source": "Ollama-Manifest",
                        "fingerprint": weights.get("digest") if weights else None})
    if not out:  # Fallback: laufender Ollama-Dienst
        for line in _run(["ollama", "list"]).splitlines()[1:]:
            p = line.split()
            if p:
                from ..skills.software import fmt_size_text
                size = fmt_size_text(" ".join(p[2:4])) if len(p) >= 4 else None
                out.append({"name": p[0], "version": p[1] if len(p) > 1 else None, "kind": "llm-modell",
                            "category": "Ollama", "size": size, "source": "ollama list"})
    return out


def local_models() -> list[dict]:
    out = ollama_models()
    for d, label in MODEL_DIRS:
        base = Path(os.path.expanduser(d))
        if not base.is_dir() or label == "Ollama":
            continue
        if label == "Hugging Face":
            for m in base.glob("models--*"):
                ref = m / "refs" / "main"
                out.append({"name": m.name.replace("models--", "").replace("--", "/"), "kind": "llm-modell",
                            "category": label, "location": str(m), "source": "HF-Cache", "size": _dir_size(m / "blobs"),
                            "fingerprint": "hf:" + ref.read_text().strip() if ref.is_file() else None})
        else:
            for m in list(base.rglob("*.gguf"))[:500]:
                size = m.stat().st_size
                out.append({"name": m.name, "kind": "llm-modell", "category": label, "location": str(m),
                            "size": size, "source": "Modellordner", "fingerprint": _quick_fp(m, size)})
    return out


def hardware() -> list[dict]:
    """GPU (Grafikspeicher) und Arbeitsspeicher – für „passt das Modell auf diesen Rechner?“."""
    out = []
    txt = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], timeout=8)
    for line in txt.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) == 2 and p[1].isdigit():
            out.append({"name": f"GPU: {p[0]}", "kind": "hardware", "category": "GPU", "size": int(p[1]) * 1024 * 1024,
                        "source": "nvidia-smi"})
    ram = None
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo") as fh:
                ram = int(fh.readline().split()[1]) * 1024
        elif platform.system() == "Darwin":
            ram = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0) or None
            if platform.machine() == "arm64":
                chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
                out.append({"name": f"GPU: {chip} (gemeinsamer Speicher)", "kind": "hardware", "category": "GPU-Unified",
                            "size": ram, "source": "sysctl"})
        elif platform.system() == "Windows":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            ram = int(m.ullTotalPhys)
    except Exception:
        ram = None
    if ram:
        out.append({"name": "Arbeitsspeicher (RAM)", "kind": "hardware", "category": "RAM", "size": ram, "source": "System"})
    return out


def collect() -> list[dict]:
    system = platform.system()
    try:
        progs = windows_programs() if system == "Windows" else mac_programs() if system == "Darwin" else linux_programs()
    except Exception:
        progs = []
    for p in progs:
        p.setdefault("kind", _kind_for(p.get("name") or ""))
    return [p for p in progs + cli_tools() + python_ai_packages() + local_models() + hardware() if p.get("name")]


def normalize(it: dict) -> dict:
    """Vergleichsfelder ergänzen: Programmname ohne Version/Architektur, Modell-Merkmale (Familie, Größe, Variante, Quantisierung)."""
    from ..skills import software

    key, disp = software.program_key(it["name"])
    it = {**it, "norm_key": key, "display": disp}
    if it.get("kind") == "llm-modell":
        m = software.parse_model(it["name"], it.get("category"))
        it.update(model_key=m["key"], quant=m["quant"], format=m["format"] or it.get("category"), display=m["label"] or it["name"])
    return it


def store(computer_id: str, items: list[dict]) -> int:
    """Inventar eines Computers speichern. Nicht mehr gemeldete Einträge werden nur als inaktiv markiert (Verlauf bleibt)."""
    ts = db.now()
    with db.tx() as c:
        c.execute("UPDATE programs SET active=0 WHERE computer_id=?", (computer_id,))
        for it in map(normalize, items):
            c.execute(
                """INSERT INTO programs(computer_id, name, version, publisher, kind, category, location, size, source, seen_at,
                   norm_key, display, model_key, quant, format, fingerprint, active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                   ON CONFLICT(computer_id, name, kind, location) DO UPDATE SET version=excluded.version,
                   publisher=excluded.publisher, category=excluded.category, size=excluded.size, seen_at=excluded.seen_at,
                   source=excluded.source, norm_key=excluded.norm_key, display=excluded.display, model_key=excluded.model_key,
                   quant=excluded.quant, format=excluded.format, fingerprint=excluded.fingerprint, active=1""",
                (computer_id, it["name"], it.get("version"), it.get("publisher"), it.get("kind", "programm"), it.get("category"),
                 it.get("location") or "", it.get("size"), it.get("source"), ts, it["norm_key"], it["display"],
                 it.get("model_key"), it.get("quant"), it.get("format"), it.get("fingerprint")),
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
