"""Skill: Programme und LLM-Modelle vergleichbar machen.

- Programme: Versionsnummern, Architektur- und Sprachzusätze entfernen, Aliasse zusammenführen
  („Python 3.12.1 (64-bit)“, „python3“ → „Python“; „Microsoft Visual Studio Code (User)“, „code“ → „VS Code“).
- Modelle: Familie, Größe (Parameter), Variante und Quantisierung aus dem Namen lesen – unabhängig vom Tool:
  „llama3.1:8b“ (Ollama), „llama-3.1-8b-instruct-Q4_K_M.gguf“ (LM Studio), „meta-llama/Llama-3.1-8B-Instruct“ (Hugging Face)
  sind dasselbe Modell (llama 3.1 · 8B · instruct), nur in anderem Format.
- Rollen für LLM-Lösungen (Modell-Runner, Chat-Oberfläche, Coding-Assistent, Bild-KI …), um Überschneidungen zu finden.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- Programme

ALIASES = {
    "visual studio code": "VS Code", "microsoft visual studio code": "VS Code", "code": "VS Code", "vs code": "VS Code",
    "vscode": "VS Code", "python": "Python", "python3": "Python", "python launcher": "Python", "node.js": "Node.js",
    "nodejs": "Node.js", "node": "Node.js", "git": "Git", "git for windows": "Git", "docker desktop": "Docker Desktop",
    "docker": "Docker", "docker.io": "Docker", "docker-ce": "Docker", "ollama": "Ollama", "lm studio": "LM Studio",
    "lm studio cli": "LM Studio", "lms": "LM Studio", "gpt4all": "GPT4All", "jan": "Jan", "cursor": "Cursor",
    "claude": "Claude", "claude code": "Claude Code", "chatgpt": "ChatGPT", "anythingllm": "AnythingLLM", "msty": "Msty",
    "comfyui": "ComfyUI", "comfyui desktop": "ComfyUI", "open webui": "Open WebUI", "open-webui": "Open WebUI",
    "google chrome": "Google Chrome", "chrome": "Google Chrome", "mozilla firefox": "Firefox", "firefox": "Firefox",
    "microsoft edge": "Microsoft Edge", "7-zip": "7-Zip", "vlc media player": "VLC", "vlc": "VLC",
    "nvidia-treiber/cuda": "NVIDIA-Treiber/CUDA", "nvidia graphics driver": "NVIDIA-Treiber/CUDA",
    "llama.cpp": "llama.cpp", "openai codex cli": "OpenAI Codex CLI", "codex": "OpenAI Codex CLI", "gemini cli": "Gemini CLI",
    "aider": "Aider", "github copilot": "GitHub Copilot", "microsoft office": "Microsoft Office", "microsoft 365": "Microsoft Office",
}
_NOISE = re.compile(
    r"\((?:x64|x86|64-bit|32-bit|arm64|user|system|machine|en-us|de-de)[^)]*\)|\b(?:x64|x86_64|x86|amd64|arm64|64-bit|32-bit|"
    r"win64|win32|setup|installer|for windows|for mac|desktop app|version)\b", re.I)
_VERSION_TAIL = re.compile(r"[\s_-]*v?\d+(?:[._]\d+)*(?:[a-z]\d*)?(?:\s*\(.*\))?\s*$", re.I)


def program_key(name: str) -> tuple[str, str]:
    """-> (Vergleichsschlüssel, Anzeigename)"""
    n = (name or "").strip()
    if n.lower().startswith("python: "):  # Python-Bibliothek: Name bleibt, wie er ist
        return n.lower(), n
    base = _NOISE.sub(" ", n)
    for _ in range(2):
        base = _VERSION_TAIL.sub("", base).strip(" -_")
    base = re.sub(r"\s{2,}", " ", base).strip()
    low = base.lower()
    if low in ALIASES:
        return ALIASES[low].lower(), ALIASES[low]
    for prefix in ("microsoft office", "python 3", "python"):  # „Microsoft Office Professional Plus 2021“ → Office
        if low.startswith(prefix) and prefix != "python":
            disp = ALIASES.get(prefix, base)
            return disp.lower(), disp
    return low or n.lower(), base or n


def version_tuple(v: str | None) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:4])


# ---------------------------------------------------------------- Rollen (LLM-Lösungen)

ROLES = {
    "Modell-Runner": ["ollama", "lm studio", "gpt4all", "jan", "llama.cpp", "vllm", "localai", "koboldcpp", "text-generation-webui", "msty"],
    "Chat-Oberfläche": ["open webui", "anythingllm", "chatgpt", "claude", "msty", "jan", "lm studio", "gpt4all", "perplexity", "gemini"],
    "Coding-Assistent": ["claude code", "openai codex cli", "gemini cli", "aider", "cursor", "github copilot", "copilot"],
    "Bild-KI": ["comfyui", "automatic1111", "stable diffusion", "invokeai", "fooocus", "pinokio"],
    "Sprache/Audio": ["whisper", "macwhisper", "superwhisper"],
}


def roles(key: str) -> list[str]:
    k = key.lower()
    return [r for r, names in ROLES.items() if any(k == n or k.startswith(n + " ") for n in names)]


# ---------------------------------------------------------------- Modelle

_QUANT = re.compile(r"(?<![a-z0-9])(i?q\d(?:_[a-z0-9]+)*|f16|fp16|bf16|f32|fp32|int4|int8|q\d+bit|\d+bit|awq|gptq|exl2|mlx)(?![a-z0-9])", re.I)
_PARAMS = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s?([bm])(?![a-z0-9])", re.I)
_MOE = re.compile(r"(?<![a-z0-9])(\d+x\d+(?:\.\d+)?b)(?![a-z0-9])", re.I)
# Spezialisierung vor „instruct“: Qwen2.5-Coder-7B-Instruct ist ein Coder-Modell
VARIANTS = ["coder", "code", "vision", "vl", "embed", "embedding", "math", "lora", "uncensored", "instruct", "chat", "it", "base"]
FAMILIES = ["llama", "mistral", "mixtral", "qwen", "gemma", "phi", "deepseek", "deepseek-r1", "deepseek-coder", "deepseek-v3", "codellama", "starcoder", "falcon", "yi",
            "command-r", "nomic-embed-text", "mxbai-embed", "llava", "sdxl", "stable-diffusion", "flux", "whisper", "granite",
            "smollm", "olmo", "gpt-oss", "tinyllama", "orca", "vicuna", "nous-hermes", "openchat", "solar", "minicpm"]
EXT_FORMAT = {".gguf": "GGUF", ".safetensors": "safetensors", ".ckpt": "ckpt", ".pt": "PyTorch", ".pth": "PyTorch", ".onnx": "ONNX"}


def parse_model(name: str, tool: str | None = None) -> dict:
    """Modellname → {family, params, variant, quant, format, key, label}"""
    raw = (name or "").strip()
    fmt = next((f for e, f in EXT_FORMAT.items() if raw.lower().endswith(e)), None)
    if not fmt and tool:
        fmt = {"Ollama": "Ollama", "Hugging Face": "Hugging Face"}.get(tool)
    s = raw.lower()
    for e in EXT_FORMAT:
        s = s.removesuffix(e)
    s = s.split("/")[-1] if "/" in s and not s.startswith("models--") else s  # „meta-llama/Llama-3.1-8B“ → Repo-Name
    s = s.replace(":", " ").replace("_", "-")
    s = re.sub(r"^(meta|mistralai|google|microsoft|thebloke|bartowski|lmstudio-community)-", "", s)
    s = re.sub(r"-gguf$", "", s)
    if "gguf" in raw.lower() and not fmt:
        fmt = "GGUF"
    quant = None
    m = _QUANT.search(raw.replace(":", " ").replace("-", " ").replace(".", " "))
    if m:
        quant = m.group(1).upper().replace("FP16", "F16")
    params = None
    m = _MOE.search(s) or _PARAMS.search(s.replace("-", " "))
    if m:
        params = (m.group(1) if m.re is _MOE else f"{m.group(1)}{m.group(2)}").upper().replace(".0B", "B")
    variant = next((v for v in VARIANTS if re.search(rf"(?<![a-z0-9]){v}(?![a-z0-9])", s)), None)
    if variant in ("it", "chat"):
        variant = "instruct"
    if variant == "embedding":
        variant = "embed"
    if variant == "vl":
        variant = "vision"
    if variant == "code":
        variant = "coder"
    if variant is None and tool == "Ollama" and "embed" not in s:
        variant = "instruct"  # Standard-Tags der Ollama-Bibliothek sind die Chat-/Instruct-Fassungen
    fam_txt = re.split(r"[\s-](?=\d+(?:\.\d+)?[bm](?![a-z0-9]))", s.replace(" ", "-"), maxsplit=1)[0]
    family = None
    for f in sorted(FAMILIES, key=len, reverse=True):
        if fam_txt.replace("-", "").startswith(f.replace("-", "")):
            rest = fam_txt.replace("-", "")[len(f.replace("-", "")):]
            ver = re.match(r"\d+(?:\.\d+)?(?!\d*x)", rest)
            family = f + (" " + ver.group(0) if ver else "")
            break
    if not family:
        family = re.sub(r"-(instruct|chat|q\d.*|f16|bf16)$", "", fam_txt).strip("-") or s
    if params is None and variant is None and quant is None and family == s:
        key = family
    else:
        key = "|".join([family, params or "?", variant or ""])
    label = " · ".join(x for x in (family, params, variant) if x)
    return {"family": family, "params": params, "variant": variant, "quant": quant, "format": fmt, "key": key, "label": label}


def generation(family: str) -> tuple[str, float | None]:
    """„llama 3.1“ → ("llama", 3.1) – für „ältere Modellgeneration vorhanden“."""
    m = re.match(r"(.+?)\s(\d+(?:\.\d+)?)$", family or "")
    return (m.group(1), float(m.group(2))) if m else (family, None)


def fmt_size_text(text: str | None) -> int | None:
    """„4.7 GB“ → Bytes (z. B. aus `ollama list`)."""
    m = re.match(r"\s*([\d.,]+)\s*([KMGT]?B)", text or "", re.I)
    if not m:
        return None
    mult = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2).upper()]
    return int(float(m.group(1).replace(",", ".")) * mult)
