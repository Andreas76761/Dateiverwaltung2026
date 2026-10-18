"""Programme & LLMs organisieren: Vergleich über alle Computer, Speicherbedarf und Empfehlungen zum Zusammenführen.

Reine Auswertung des Inventars (plus beim Datei-Scan gefundener Modelldateien). Die App installiert, entfernt
oder verschiebt nichts – Empfehlungen beschreiben nur, was man selbst tun könnte, und wie viel Platz das brächte.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict

from .. import db
from ..skills import software

MIN_SAVING = 50 * 1024 * 1024        # kleinere Einsparungen lohnen keine Empfehlung
ROLE_LIMITS = {"Modell-Runner": 2, "Chat-Oberfläche": 3, "Coding-Assistent": 3, "Bild-KI": 2}
WATCH_KINDS = ("llm-tool", "dev-tool")
PRIO = {1: "hoch", 2: "mittel", 3: "niedrig"}


# ---------------------------------------------------------------- Daten

def items() -> list[dict]:
    """Aktuelles Inventar aller Computer + Modelldateien aus dem Datei-Scan (ohne doppelte Pfade)."""
    rows = db.query("""SELECT p.*, COALESCE(c.name, p.computer_id) computer_name FROM programs p
                       LEFT JOIN computers c ON c.id=p.computer_id WHERE COALESCE(p.active, 1)=1""")
    seen = {(r["computer_id"], r["location"]) for r in rows if r["location"]}
    for f in db.query("""SELECT f.id file_id, f.computer_id, c.name computer_name, f.name, f.path, f.size, f.sha256, f.quick_hash
                         FROM files f JOIN computers c ON c.id=f.computer_id WHERE f.file_type='KI-Modell' AND f.missing=0"""):
        if (f["computer_id"], f["path"]) in seen:
            continue
        m = software.parse_model(f["name"])
        rows.append({"id": None, "file_id": f["file_id"], "computer_id": f["computer_id"], "computer_name": f["computer_name"],
                     "name": f["name"], "display": m["label"] or f["name"], "kind": "llm-modell", "category": "Datei-Scan",
                     "location": f["path"], "size": f["size"], "source": "Datei-Scan", "version": None,
                     "norm_key": f["name"].lower(), "model_key": m["key"], "quant": m["quant"], "format": m["format"],
                     "fingerprint": f["sha256"] or (f"q:{f['quick_hash']}" if f["quick_hash"] else None)})
    for r in rows:
        if not r.get("norm_key"):  # ältere Einträge vor der Normalisierung
            r["norm_key"], r["display"] = software.program_key(r["name"])
        if r["kind"] == "llm-modell" and not r.get("model_key"):
            m = software.parse_model(r["name"], r.get("category"))
            r.update(model_key=m["key"], quant=m["quant"], format=m["format"], display=m["label"])
        r["tool"] = r.get("category") or r.get("source")
    return rows


def computers() -> list[dict]:
    comps = db.query("SELECT id, name, os, mode, last_seen FROM computers WHERE id!='cloud-api' ORDER BY name")
    free = {r["computer_id"]: r for r in db.query(
        "SELECT computer_id, SUM(total_bytes) total, SUM(free_bytes) free FROM volumes WHERE kind!='cloud-api' GROUP BY 1")}
    for c in comps:
        c["disk_total"], c["disk_free"] = (free.get(c["id"]) or {}).get("total"), (free.get(c["id"]) or {}).get("free")
    return comps


def _hw(rows: list[dict]) -> dict[str, dict]:
    hw: dict[str, dict] = defaultdict(dict)
    for r in rows:
        if r["kind"] != "hardware":
            continue
        if r["category"] in ("GPU", "GPU-Unified"):
            g = hw[r["computer_id"]]
            if (r["size"] or 0) > (g.get("vram") or 0):
                g.update(gpu=r["name"].removeprefix("GPU: "), vram=r["size"], unified=r["category"] == "GPU-Unified")
        elif r["category"] == "RAM":
            hw[r["computer_id"]]["ram"] = r["size"]
    return hw


# ---------------------------------------------------------------- Vergleich

def compare(kind: str | None = None, q: str | None = None) -> dict:
    """Matrix: je Programm/Modell eine Zeile, je Computer eine Spalte (Version bzw. Größe/Varianten)."""
    rows = [r for r in items() if r["kind"] != "hardware" and (not kind or r["kind"] == kind)]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in (r["name"] or "").lower() or ql in (r.get("display") or "").lower()]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:  # Programme über die Art hinweg zusammenführen (VS Code als „Programm“ und als „Entwickler-Tool“)
        groups[("m", r["model_key"]) if r["kind"] == "llm-modell" else ("p", r["norm_key"])].append(r)
    rank = {"llm-tool": 0, "dev-tool": 1, "programm": 2}
    out = []
    for (_, key), members in groups.items():
        k = "llm-modell" if members[0]["kind"] == "llm-modell" else min((m["kind"] for m in members), key=lambda x: rank.get(x, 9))
        cells: dict[str, dict] = {}
        for m in members:
            c = cells.setdefault(m["computer_id"], {"versions": set(), "size": 0, "count": 0, "variants": set(), "tools": set()})
            if m.get("version"):
                c["versions"].add(m["version"])
            c["size"] += m.get("size") or 0
            c["count"] += 1
            if m.get("quant") or m.get("format"):
                c["variants"].add(" ".join(x for x in (m.get("format"), m.get("quant")) if x))
            if m.get("tool"):
                c["tools"].add(m["tool"])
        versions = {v for c in cells.values() for v in c["versions"]}
        newest = max(versions, key=software.version_tuple) if versions else None
        for c in cells.values():
            c["outdated"] = bool(newest and c["versions"] and max(c["versions"], key=software.version_tuple) != newest
                                 and software.version_tuple(max(c["versions"], key=software.version_tuple)) < software.version_tuple(newest))
            for f in ("versions", "variants", "tools"):
                c[f] = sorted(c[f])
        out.append({"key": key, "kind": k, "display": members[0].get("display") or members[0]["name"],
                    "names": sorted({m["name"] for m in members})[:6], "roles": software.roles(key) if k != "llm-modell" else [],
                    "computers": len(cells), "count": len(members), "size": sum(c["size"] for c in cells.values()),
                    "versions": sorted(versions, key=software.version_tuple), "newest": newest,
                    "drift": len(versions) > 1 and any(c["outdated"] for c in cells.values()), "cells": cells})
    order = {"llm-modell": 0, "llm-tool": 1, "dev-tool": 2, "programm": 3}
    out.sort(key=lambda r: (order.get(r["kind"], 9), -r["computers"], -r["size"], r["display"].lower()))
    with_data = {cid for r in out for cid in r["cells"]}
    return {"computers": [c for c in computers() if c["id"] in with_data], "rows": out}


# ---------------------------------------------------------------- Speicherbedarf

def storage() -> dict:
    rows = items()
    hw = _hw(rows)
    per: dict[str, dict] = {}
    for c in computers():
        per[c["id"]] = {**c, "models": 0, "models_n": 0, "programs": 0, "programs_known": 0, "by_tool": defaultdict(int),
                        **hw.get(c["id"], {})}
    for r in rows:
        p = per.get(r["computer_id"])
        if not p or r["kind"] == "hardware":
            continue
        if r["kind"] == "llm-modell":
            p["models"] += r.get("size") or 0
            p["models_n"] += 1
            p["by_tool"][r["tool"] or "?"] += r.get("size") or 0
        elif r.get("size"):
            p["programs"] += r["size"]
            p["programs_known"] += 1
    largest = sorted((r for r in rows if r["kind"] == "llm-modell" and r.get("size")), key=lambda r: -r["size"])[:15]
    for p in per.values():
        p["by_tool"] = dict(sorted(p["by_tool"].items(), key=lambda kv: -kv[1]))
    return {"computers": list(per.values()),
            "largest": [{k: r.get(k) for k in ("computer_id", "computer_name", "name", "display", "tool", "quant", "format", "size", "location")}
                        for r in largest],
            "models_total": sum(p["models"] for p in per.values())}


# ---------------------------------------------------------------- Empfehlungen

def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _it(r: dict) -> dict:
    return {k: r.get(k) for k in ("computer_id", "computer_name", "name", "display", "tool", "version", "quant", "format",
                                  "size", "location", "fingerprint")}


def recommendations() -> list[dict]:
    rows = items()
    hw = _hw(rows)
    comps = {c["id"]: c for c in computers()}
    models = [r for r in rows if r["kind"] == "llm-modell"]
    recs: list[dict] = []

    def add(kind, prio, title, detail, members, saving=0, hint=""):
        ids = sorted(f"{m['computer_id']}:{m.get('location') or m['name']}" for m in members)
        recs.append({"key": _key(kind, *ids), "type": kind, "priority": prio, "priority_text": PRIO[prio], "title": title,
                     "detail": detail, "computers": sorted({m["computer_name"] for m in members}), "items": [_it(m) for m in members],
                     "saving": int(saving), "hint": hint})

    # 1. Identische Modelldatei mehrfach auf demselben Computer
    by_fp: dict[tuple, list[dict]] = defaultdict(list)
    for m in models:
        if m.get("fingerprint"):
            by_fp[(m["computer_id"], m["fingerprint"])].append(m)
    dup_fp = set()
    for (cid, fp), ms in by_fp.items():
        if len(ms) > 1:
            dup_fp.add((cid, fp))
            size = max(x.get("size") or 0 for x in ms)
            add("doppelt", 1, f"{ms[0]['display']}: identische Datei {len(ms)}× auf {ms[0]['computer_name']}",
                f"Dieselbe Modelldatei liegt in {len(ms)} Ordnern ({', '.join(sorted({x['tool'] for x in ms}))}).",
                ms, size * (len(ms) - 1),
                "Eine Kopie behalten und das andere Tool auf denselben Modellordner zeigen lassen (z. B. LM Studio „Models Directory“, "
                "Ollama per Modelfile FROM <datei>.gguf).")

    # 2. Gleiches Modell in mehreren Tools/Formaten/Quantisierungen auf demselben Computer
    by_model: dict[tuple, list[dict]] = defaultdict(list)
    for m in models:
        if m.get("model_key") and "|" in m["model_key"]:
            by_model[(m["computer_id"], m["model_key"])].append(m)
    for (cid, mk), ms in by_model.items():
        distinct = {}
        for x in ms:  # identische Dateien (gleicher Fingerabdruck) nur einmal zählen – die meldet Regel 1
            distinct.setdefault(x.get("fingerprint") or x["location"] or x["name"], x)
        if len(distinct) < 2:
            continue
        sizes = sorted((x.get("size") or 0 for x in distinct.values()), reverse=True)
        saving = sum(sizes) - sizes[0]
        tools = sorted({x["tool"] for x in ms})
        variants = sorted({" ".join(v for v in (x.get("format"), x.get("quant")) if v) for x in ms} - {""})
        same_tool = len(tools) == 1
        add("mehrfach", 1 if saving > 5 * 1024 ** 3 else 2,
            f"{ms[0]['display']}: {len(ms)} Fassungen auf {ms[0]['computer_name']}",
            ("Mehrere Quantisierungen im selben Tool" if same_tool else f"Dasselbe Modell in {', '.join(tools)}")
            + (f" ({', '.join(variants)})" if variants else "") + ".",
            ms, saving,
            "Eine Fassung als Standard wählen (für 8–16 GB Grafikspeicher meist Q4_K_M) und die übrigen im jeweiligen Tool entfernen. "
            "GGUF-Dateien lassen sich in Ollama importieren, statt sie doppelt zu laden.")

    # 3. Dasselbe Modell auf mehreren Computern → zentral bereitstellen
    across: dict[str, list[dict]] = defaultdict(list)
    for m in models:
        if m.get("model_key") and "|" in m["model_key"]:
            across[m["model_key"]].append(m)
    for mk, ms in across.items():
        cids = {x["computer_id"] for x in ms}
        if len(cids) < 2:
            continue
        per_c = defaultdict(int)
        for x in ms:
            per_c[x["computer_id"]] += x.get("size") or 0
        saving = sum(per_c.values()) - max(per_c.values())
        if saving < MIN_SAVING:
            continue
        identical = len({x.get("fingerprint") for x in ms if x.get("fingerprint")}) == 1 and all(x.get("fingerprint") for x in ms)
        best = max(cids, key=lambda c: (hw.get(c, {}).get("vram") or 0, hw.get(c, {}).get("ram") or 0))
        add("zentral", 3, f"{ms[0]['display']}: auf {len(cids)} Computern",
            ("Identische Dateien" if identical else "Gleiches Modell") + f" auf {', '.join(sorted({x['computer_name'] for x in ms}))}.",
            ms, saving,
            f"Optional zentral auf {comps.get(best, {}).get('name', best)} (stärkste Hardware) betreiben und von den anderen Computern "
            "über das Netzwerk nutzen (z. B. Ollama mit OLLAMA_HOST=0.0.0.0, Open WebUI). Lokale Kopien sind nur für den Offline-Betrieb nötig.")

    # 4. Ältere Modellgeneration neben neuerer
    by_family: dict[tuple, list[dict]] = defaultdict(list)
    for m in models:
        fam = (m.get("model_key") or "").split("|")[0]
        base, gen = software.generation(fam)
        if gen is not None:
            by_family[(m["computer_id"], base)].append({**m, "_gen": gen})
    for (cid, base), ms in by_family.items():
        top = max(x["_gen"] for x in ms)
        old = [x for x in ms if x["_gen"] < top]
        if old and sum(x.get("size") or 0 for x in old) >= MIN_SAVING:
            add("veraltet", 3, f"Ältere {base}-Generation auf {old[0]['computer_name']}",
                f"{', '.join(sorted({x['display'] for x in old}))} neben {base} {top:g}.", old,
                sum(x.get("size") or 0 for x in old), "Prüfen, ob die ältere Generation noch gebraucht wird (z. B. für bestehende Workflows).")

    # 5. Überschneidende LLM-Lösungen auf einem Computer
    tools = [r for r in rows if r["kind"] in ("llm-tool", "programm", "dev-tool") and not r["norm_key"].startswith("python: ")]
    for cid in {r["computer_id"] for r in tools}:
        for role, limit in ROLE_LIMITS.items():
            ms = {}
            for r in tools:
                if r["computer_id"] == cid and role in software.roles(r["norm_key"]):
                    ms.setdefault(r["norm_key"], r)
            if len(ms) >= limit:
                vals = list(ms.values())
                add("ueberschneidung", 2, f"{len(vals)} {role}-Lösungen auf {vals[0]['computer_name']}",
                    f"{', '.join(sorted(v['display'] for v in vals))} erfüllen dieselbe Aufgabe.", vals, 0,
                    "Eine Lösung als Standard festlegen – das spart Speicher (jede bringt eigene Modelle mit), Updates und Lizenzkosten.")

    # 6. Unterschiedliche Versionen desselben Tools
    for row in compare()["rows"]:
        minors = {software.version_tuple(v)[:2] for v in row["versions"]}
        if row["kind"] in WATCH_KINDS and row["drift"] and len(minors) > 1 and not row["key"].startswith("python: "):
            ms = [r for r in tools if r["norm_key"] == row["key"]]
            top = software.version_tuple(row["newest"])[:2]
            old = sorted(comps[c]["name"] for c, cell in row["cells"].items() if c in comps and cell["versions"]
                         and software.version_tuple(max(cell["versions"], key=software.version_tuple))[:2] < top)
            add("version", 2, f"{row['display']}: unterschiedliche Versionen",
                f"Neueste Version {row['newest']}; älter auf {', '.join(old)}.", ms, 0,
                "Auf allen Computern auf den gleichen Stand bringen – gleiche Ergebnisse und weniger Überraschungen bei Modellen/Plugins.")

    # 7. Modell zu groß für die Hardware
    for m in models:
        h = hw.get(m["computer_id"], {})
        size = m.get("size") or 0
        if size < 1024 ** 3 or m.get("tool") in ("Hugging Face", "Datei-Scan"):  # nur direkt lauffähige Modelle (Ollama, GGUF)
            continue
        limit = (h.get("vram") * 0.75 if h.get("unified") else h.get("vram")) if h.get("vram") else (h.get("ram") * 0.6 if h.get("ram") else None)
        if limit and size > limit:
            better = [c for c, x in hw.items() if c != m["computer_id"] and (x.get("vram") or 0) * (0.75 if x.get("unified") else 1) > size]
            where = (" Besser geeignet: " + ", ".join(comps[c]["name"] for c in better if c in comps) + ".") if better else ""
            add("hardware", 2, f"{m['display']} ist zu groß für {m['computer_name']}",
                f"Modell {size / 1024 ** 3:.1f} GB, verfügbar {(h.get('vram') or h.get('ram')) / 1024 ** 3:.0f} GB "
                f"({'gemeinsamer Speicher' if h.get('unified') else 'Grafikspeicher' if h.get('vram') else 'Arbeitsspeicher'}) – "
                f"läuft nur teilweise auf der GPU bzw. sehr langsam.{where}", [m], 0,
                "Kleinere Quantisierung (z. B. Q4_K_M) oder kleinere Modellgröße nutzen – oder auf dem stärkeren Rechner betreiben.")

    # 8. Wenig freier Speicher und viele Modelle
    st = {c["id"]: c for c in storage()["computers"]}
    for cid, c in st.items():
        if c.get("disk_total") and c.get("disk_free") is not None and c["models"] > 5 * 1024 ** 3:
            if c["disk_free"] < max(0.1 * c["disk_total"], 20 * 1024 ** 3):
                ms = [m for m in models if m["computer_id"] == cid]
                add("speicher", 1, f"Wenig Speicher frei auf {c['name']}",
                    f"Frei {c['disk_free'] / 1024 ** 3:.0f} GB von {c['disk_total'] / 1024 ** 3:.0f} GB, davon belegen Modelle "
                    f"{c['models'] / 1024 ** 3:.0f} GB.", ms, 0,
                    "Selten genutzte Modelle auf eine externe Platte oder ein NAS auslagern (Ollama: OLLAMA_MODELS auf das Laufwerk zeigen).")

    state = {r["key"]: r for r in db.query("SELECT * FROM program_recs")}
    for r in recs:
        s = state.get(r["key"])
        r["status"], r["note"] = (s["status"], s["note"]) if s else ("offen", None)
    recs.sort(key=lambda r: (r["status"] != "offen", r["priority"], -r["saving"]))
    return recs


def summary() -> dict:
    recs = recommendations()
    open_ = [r for r in recs if r["status"] == "offen"]
    return {"empfehlungen": len(open_), "einsparung": sum(r["saving"] for r in open_),
            "je_art": {t: sum(1 for r in open_ if r["type"] == t) for t in {r["type"] for r in open_}}}
