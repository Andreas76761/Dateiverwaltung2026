"""Demo-Inventar für die 4 Demo-Computer (Programme, LLM-Tools, lokale Modelle, Hardware).

    cd backend && python ../scripts/demo_inventory.py

Schreibt nur in die Datenbank der App (wie ein Agent, der sein Inventar meldet).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import db  # noqa: E402
from app.agents.inventory_agent import store  # noqa: E402

GB = 1024 ** 3
MB = 1024 ** 2
D_LLAMA = "sha256:8eeb52dfb3bb9aefdf9d1ef24b3bdbcfbe82238798c4b918278320b6fcef18fe"
Q4_FP = "q:4f1c0a9e7b2d3c5a6e8f90123456789a"


def prog(name, version=None, size=None, publisher=None, kind=None, category=None, location="", source="Demo"):
    return {"name": name, "version": version, "size": size, "publisher": publisher, "kind": kind or "programm",
            "category": category, "location": location, "source": source}


def tool(name, version, location=""):
    return prog(name, version, kind="llm-tool", location=location, source="PATH")


def ollama(name, size, digest=None):
    return {"name": name, "kind": "llm-modell", "category": "Ollama", "size": int(size), "fingerprint": digest,
            "location": f"~/.ollama/models/manifests/registry.ollama.ai/library/{name.replace(':', '/')}", "source": "Ollama-Manifest"}


def gguf(name, size, tool_name="LM Studio", fp=None, folder="~/.lmstudio/models/lmstudio-community"):
    return {"name": name, "kind": "llm-modell", "category": tool_name, "size": int(size), "fingerprint": fp,
            "location": f"{folder}/{name}", "source": "Modellordner"}


def hw(name, size, cat):
    return {"name": name, "kind": "hardware", "category": cat, "size": int(size), "source": "System"}


INVENTORY = {
    "pc-buero": [
        prog("Microsoft Office Professional Plus 2021", "16.0.17928", 3.1 * GB, "Microsoft"),
        prog("Microsoft Visual Studio Code (User)", "1.95.3", 380 * MB, "Microsoft"),
        prog("Python 3.12.7 (64-bit)", "3.12.7", 110 * MB, "Python Software Foundation"),
        prog("Docker Desktop", "4.36.0", 2.4 * GB, "Docker Inc."),
        prog("Claude", "0.9.3", 410 * MB, "Anthropic", kind="llm-tool"),
        prog("ChatGPT", "1.2025.1", 320 * MB, "OpenAI", kind="llm-tool"),
        prog("GitHub Copilot", "1.250", 60 * MB, "GitHub", kind="llm-tool"),
        prog("Google Chrome", "130.0.6723.117", 520 * MB, "Google"),
        prog("7-Zip 23.01 (x64)", "23.01", 5 * MB, "Igor Pavlov"),
        tool("Ollama", "0.5.7"), ollama("qwen2.5:14b", 9.0 * GB, "sha256:qwen14"),
        hw("GPU: NVIDIA GeForce RTX 3060", 12 * GB, "GPU"), hw("Arbeitsspeicher (RAM)", 32 * GB, "RAM"),
    ],
    "laptop": [
        prog("Microsoft Visual Studio Code (User)", "1.85.2", 350 * MB, "Microsoft"),
        prog("Python 3.11.4 (64-bit)", "3.11.4", 105 * MB, "Python Software Foundation"),
        prog("LM Studio", "0.3.5", 600 * MB, "Element Labs", kind="llm-tool"),
        prog("GPT4All", "3.4.2", 450 * MB, "Nomic", kind="llm-tool"),
        prog("Jan", "0.5.9", 380 * MB, "Jan", kind="llm-tool"),
        prog("Cursor", "0.42.3", 520 * MB, "Anysphere", kind="llm-tool"),
        prog("Claude", "0.8.1", 400 * MB, "Anthropic", kind="llm-tool"),
        tool("Ollama", "0.3.12"),
        ollama("llama3.1:8b", 4.9 * GB, D_LLAMA), ollama("mistral:7b", 4.1 * GB, "sha256:mistral7"),
        gguf("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf", 4.9 * GB, fp=Q4_FP),
        gguf("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf", 4.9 * GB, "GPT4All", fp=Q4_FP, folder="~/AppData/Local/nomic.ai/GPT4All"),
        hw("Arbeitsspeicher (RAM)", 16 * GB, "RAM"),
    ],
    "workstation": [
        prog("code", "1.95.3", 380 * MB, kind="dev-tool"),
        prog("Python", "3.12.3", kind="dev-tool"), prog("Docker", "27.3.1", kind="dev-tool"),
        tool("Ollama", "0.5.7"), tool("Open WebUI", "0.4.4"), tool("Claude Code", "2.1.0"), tool("Aider", "0.65.1"),
        tool("OpenAI Codex CLI", "0.9.0"), prog("ComfyUI", "0.3.4", kind="llm-tool"),
        prog("python: torch", "2.5.1", kind="llm-tool", category="Python-Bibliothek", source="pip"),
        prog("python: transformers", "4.46.2", kind="llm-tool", category="Python-Bibliothek", source="pip"),
        ollama("llama3.1:8b", 4.9 * GB, D_LLAMA), ollama("qwen2.5-coder:7b", 4.7 * GB, "sha256:coder7"),
        ollama("deepseek-r1:14b", 9.0 * GB, "sha256:r1-14"), ollama("llama2:7b", 3.8 * GB, "sha256:llama2"),
        ollama("nomic-embed-text:latest", 274 * MB, "sha256:nomic"),
        gguf("Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf", 4.9 * GB, fp=Q4_FP),
        gguf("Meta-Llama-3.1-8B-Instruct-Q8_0.gguf", 8.5 * GB, fp="q:8bit"),
        {"name": "meta-llama/Llama-3.1-8B-Instruct", "kind": "llm-modell", "category": "Hugging Face", "size": int(16.1 * GB),
         "fingerprint": "hf:0e9e39f249a16976918f6564b8830bc894c89659", "location": "~/.cache/huggingface/hub/models--meta-llama--Llama-3.1-8B-Instruct",
         "source": "HF-Cache"},
        hw("GPU: NVIDIA GeForce RTX 4070 Ti SUPER", 16 * GB, "GPU"), hw("Arbeitsspeicher (RAM)", 64 * GB, "RAM"),
    ],
    "mac": [
        prog("Visual Studio Code", "1.95.3", 410 * MB), prog("Python", "3.12.7", kind="dev-tool"),
        prog("LM Studio", "0.3.5", 640 * MB, kind="llm-tool"), prog("Msty", "1.4.1", 300 * MB, kind="llm-tool"),
        prog("Claude", "0.9.3", 420 * MB, kind="llm-tool"), prog("ChatGPT", "1.2025.1", 330 * MB, kind="llm-tool"),
        prog("Microsoft Excel", "16.90", 2.1 * GB), prog("ComfyUI", "0.3.4", 1.2 * GB, kind="llm-tool"),
        tool("Ollama", "0.5.7"), ollama("llama3.1:70b", 40 * GB, "sha256:llama70"), ollama("llama3.1:8b", 4.9 * GB, D_LLAMA),
        gguf("gemma-2-9b-it-Q4_K_M.gguf", 5.8 * GB, fp="q:gemma9"),
        hw("GPU: Apple M3 Pro (gemeinsamer Speicher)", 36 * GB, "GPU-Unified"), hw("Arbeitsspeicher (RAM)", 36 * GB, "RAM"),
    ],
}


def main():
    db.init_db()
    for cid, items in INVENTORY.items():
        print(cid, store(cid, items), "Einträge")


if __name__ == "__main__":
    main()
