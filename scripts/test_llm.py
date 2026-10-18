"""Claude-/LLM-Analyse an echten Dateien testen – ohne die Datenbank zu verändern.

    cd backend && python ../scripts/test_llm.py [--provider anthropic] [--model claude-opus-5-5] [--content] [DATEI ...]

Ohne Dateiangabe werden einige Demo-Dateien aus ./demo verwendet. Vergleicht das LLM-Ergebnis
mit den Offline-Regeln und zeigt Tokenverbrauch und Laufzeit.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import llm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.rules_provider import RulesProvider  # noqa: E402
from app.skills import extract, ocr  # noqa: E402
from app.skills.filetype import detect  # noqa: E402

DEMO = ["Scan_2023_04_12.pdf", "Mietvertrag_Lindenstr_12.pdf", "Q3_Review_SCM_2025.pptx", "Lebenslauf_Andreas_2025.docx",
        "IMG_20240518_beleg.jpg", "GenAI_Strategie_2026.pptx", "system_prompt_vertragspruefung.md", "Budget_2026_Planung.xlsx"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "ollama", "rules"])
    ap.add_argument("--model")
    ap.add_argument("--content", action="store_true", help="Dateiinhalte an die Cloud-API senden (sonst nur Metadaten)")
    ap.add_argument("files", nargs="*")
    a = ap.parse_args()
    s = get_settings()
    s.llm["provider"] = a.provider
    s.llm["send_content_to_cloud"] = a.content or s.llm.get("send_content_to_cloud", False)
    if a.model:
        s.llm["anthropic_model" if a.provider == "anthropic" else "ollama_model"] = a.model

    paths = [Path(f) for f in a.files] or [p for n in DEMO for p in (ROOT / "demo").rglob(n)][: len(DEMO)]
    if not paths:
        sys.exit("Keine Dateien gefunden – zuerst `python scripts/make_demo.py` ausführen oder Dateien angeben.")
    provider = llm.get_provider()
    print(f"Provider: {provider.name}  Modell: {getattr(provider, 'model', '-')}  Inhalte senden: {s.llm['send_content_to_cloud']}\n")
    tot_in = tot_out = 0
    ok = 0
    for p in paths:
        ext, ftype, _ = detect(p.name)
        text, pages = extract.extract_text(str(p), ext)
        text = (text + " " + ocr.run(str(p), ext, text)).strip()
        st = p.stat()
        meta = {"name": p.name, "path": str(p), "ext": ext, "file_type": ftype, "size": st.st_size,
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime)), "page_count": pages}
        rules = llm.normalize(RulesProvider().analyze(meta, text))
        t0 = time.perf_counter()
        try:
            r = llm.normalize(provider.analyze(meta, text))
        except Exception as exc:
            print(f"✗ {p.name}: {exc}")
            if isinstance(exc, llm.FatalLLMError):
                break
            continue
        ms = (time.perf_counter() - t0) * 1000
        ok += 1
        u = getattr(provider, "last_usage", None) or {}
        tot_in += u.get("input", 0)
        tot_out += u.get("output", 0)
        same = "=" if r["category_id"] == rules["category_id"] else "≠"
        print(f"✓ {p.name}  ({ms:.0f} ms, {u.get('input', '?')}/{u.get('output', '?')} Tokens)")
        print(f"    LLM:    {r['category_id']:<14} Wichtigkeit {r['importance']:>3}  Sicherheit {r['confidence']:.2f}  {same} Regeln: {rules['category_id']}")
        print(f"    Labels: {', '.join(r['labels'])}   Unterordner: {r['subfolder'] or '-'}")
        print(f"    {r['summary']}\n")
    print(f"{ok}/{len(paths)} erfolgreich · Tokens gesamt: {tot_in} ein / {tot_out} aus")
    sys.exit(0 if ok == len(paths) else 1)


if __name__ == "__main__":
    main()
