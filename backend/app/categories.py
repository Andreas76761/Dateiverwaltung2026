"""60 Kategorien, gruppiert nach Privat / Beruf / GenAI / Sonstiges – unter Beruf mit dem eigenen Kapitel oneSCM.

Jede Kategorie hat Schlüsselwörter (für den regelbasierten Klassifikator und als
Hinweis für das LLM), typische Dateiendungen, ein Wichtigkeitsgewicht (0..40) und
einen Ordnernamen für die neue Struktur.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GROUPS = ["Privat", "Beruf", "GenAI", "Sonstiges"]
GROUP_FOLDERS = {"Privat": "01_Privat", "Beruf": "02_Beruf", "GenAI": "03_GenAI", "Sonstiges": "04_Sonstiges"}


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    group: str
    weight: int
    keywords: tuple[str, ...] = ()
    exts: tuple[str, ...] = ()
    subfolders: tuple[str, ...] = field(default=())
    chapter: str = ""  # Kapitel innerhalb des Bereichs (z. B. oneSCM unter Beruf) → eigener Ordner

    @property
    def short(self) -> str:
        """Name ohne Kapitel-Präfix („oneSCM – Test & Rollout“ → „Test & Rollout“)."""
        p = f"{self.chapter} – "
        return self.name[len(p):] if self.chapter and self.name.startswith(p) else self.name

    @property
    def folder(self) -> str:
        base = self.short.replace(" & ", "_").replace(" ", "_").replace("/", "-")
        return f"{self.chapter}/{base}" if self.chapter else base


def C(id, name, group, weight, keywords="", exts="", subfolders="", chapter=""):
    split = lambda s: tuple(x.strip() for x in s.split(",") if x.strip())
    if chapter:
        name = f"{chapter} – {name}"
    return Category(id, name, group, weight, split(keywords), split(exts), split(subfolders), chapter)


CATEGORIES: list[Category] = [
    # ---------------- Privat (17) ----------------
    C("p_finanzen", "Finanzen & Bank", "Privat", 32, "kontoauszug,bank,iban,depot,kredit,darlehen,sparkasse,volksbank,ing,überweisung,dkb,comdirect,aktie,etf", "", "Kontoauszüge,Depot,Kredite"),
    C("p_steuern", "Steuern", "Privat", 38, "steuer,finanzamt,steuererklärung,elster,lohnsteuer,einkommensteuer,steuerbescheid,steuer-id,steuerberater", "", "Erklärungen,Bescheide,Belege"),
    C("p_versicherung", "Versicherungen", "Privat", 34, "versicherung,police,haftpflicht,hausrat,kfz-versicherung,krankenversicherung,allianz,huk,beitrag,versicherungsschein", "", "Policen,Schadensfälle"),
    C("p_wohnen", "Wohnen & Miete", "Privat", 30, "miete,mietvertrag,vermieter,nebenkosten,wohnung,hausverwaltung,strom,gas,heizkosten,grundbuch,immobilie", "", "Mietvertrag,Nebenkosten,Energie"),
    C("p_gesundheit", "Gesundheit", "Privat", 33, "arzt,befund,krankenkasse,diagnose,impfung,impfpass,klinik,labor,attest,zahnarzt,aok,tk,physiotherapie,heilmittelverordnung,praxis,therapie", "", "Befunde,Rezepte,Krankenkasse"),
    C("p_familie", "Familie & Kinder", "Privat", 26, "kinder,kita,schule,elterngeld,kindergeld,geburt,hochzeit,familie,taufe", "", ""),
    C("p_fotos", "Fotos & Bilder", "Privat", 14, "urlaub,foto,img_,dsc_,pxl_,familie,geburtstag", ".jpg,.jpeg,.heic,.png,.raw,.cr2,.nef,.arw,.dng", ""),
    C("p_videos", "Videos privat", "Privat", 10, "video,vid_,urlaub,clip", ".mp4,.mov,.avi,.mkv,.m4v", ""),
    C("p_musik", "Musik & Audio", "Privat", 6, "musik,album,song,podcast,playlist", ".mp3,.flac,.wav,.m4a,.aac,.ogg", ""),
    C("p_reisen", "Reisen", "Privat", 16, "reise,flug,boarding,hotel,buchung,booking,lufthansa,bahn,ticket,reiseplan,visum", "", "Buchungen,Tickets"),
    C("p_auto", "Auto & Mobilität", "Privat", 22, "kfz,fahrzeugschein,tüv,werkstatt,auto,autohaus,inspektion,fahrzeug,reifen,leasing,zulassung,führerschein", "", ""),
    C("p_vertraege", "Verträge privat", "Privat", 34, "vertrag,kündigung,mobilfunk,handyvertrag,abo,mitgliedschaft,fitnessstudio,laufzeit", "", "Aktiv,Gekündigt"),
    C("p_rechnungen", "Rechnungen & Belege privat", "Privat", 24, "rechnung,quittung,beleg,kassenbon,amazon,bestellung,zahlungsbestätigung", "", ""),
    C("p_behoerden", "Behörden & Ausweise", "Privat", 38, "personalausweis,reisepass,meldebescheinigung,geburtsurkunde,behörde,amt,urkunde,rentenversicherung,bescheid", "", "Ausweise,Urkunden,Bescheide"),
    C("p_bildung", "Bildung & Zeugnisse", "Privat", 30, "zeugnis,abitur,diplom,bachelor,master,studium,universität,hochschule,urkunde,transcript", "", ""),
    C("p_garantie", "Kaufbelege & Garantie", "Privat", 18, "garantie,gewährleistung,bedienungsanleitung,handbuch,seriennummer,kaufbeleg", "", "Anleitungen,Garantien"),
    C("p_hobby", "Hobby & Freizeit", "Privat", 8, "rezept,kochen,backen,zutaten,personen,teig,kuchen,ofen,lasagne,pasta,sport,garten,basteln,spiel,verein", "", ""),
    # ---------------- Beruf (17) ----------------
    C("b_projekte", "Projekte", "Beruf", 30, "projekt,projektplan,meilenstein,roadmap,lastenheft,pflichtenheft,kickoff,statusbericht,gantt", "", "Aktiv,Abgeschlossen"),
    C("b_praesentationen", "Präsentationen", "Beruf", 24, "präsentation,folie,pitch,deck,vortrag,keynote", ".pptx,.ppt,.key,.odp", ""),
    C("b_berichte", "Berichte & Analysen", "Beruf", 26, "bericht,report,analyse,auswertung,quartal,kpi,dashboard,jahresbericht", "", ""),
    C("b_vertraege", "Verträge geschäftlich", "Beruf", 38, "rahmenvertrag,nda,geheimhaltung,dienstleistungsvertrag,sla,auftragsverarbeitung,avv,lizenzvertrag", "", ""),
    C("b_angebote", "Angebote & Aufträge", "Beruf", 28, "angebot,auftrag,bestellung,kostenvoranschlag,ausschreibung,rfq,rfp,purchase order", "", ""),
    C("b_rechnungen", "Rechnungen geschäftlich", "Beruf", 30, "rechnung,invoice,gutschrift,mahnung,zahlungserinnerung,ust-id,netto,brutto", "", "Eingang,Ausgang"),
    C("b_personal", "Personal & Bewerbung", "Beruf", 34, "bewerbung,lebenslauf,cv,arbeitsvertrag,gehaltsabrechnung,lohnabrechnung,arbeitszeugnis,personalakte", "", "Bewerbungen,Abrechnungen,Verträge"),
    C("b_meetings", "Meetings & Protokolle", "Beruf", 20, "protokoll,meeting,besprechung,agenda,minutes,jour fixe,teams,notizen", "", ""),
    C("b_strategie", "Strategie & Konzepte", "Beruf", 28, "strategie,konzept,businessplan,vision,okr,ziele,positionierung,whitepaper", "", ""),
    C("b_prozesse", "Prozesse & Dokumentation", "Beruf", 22, "prozess,richtlinie,handbuch,dokumentation,sop,arbeitsanweisung,wiki,howto,anleitung", "", ""),
    C("b_schulung", "Schulungen & Zertifikate", "Beruf", 22, "schulung,zertifikat,training,seminar,workshop,weiterbildung,certificate,kurs", "", ""),
    C("b_kunden", "Kunden & Korrespondenz", "Beruf", 24, "kunde,anfrage,korrespondenz,e-mail,brief,schreiben,crm,kontakt", ".msg,.eml", ""),
    C("b_tabellen", "Tabellen & Kalkulationen", "Beruf", 20, "kalkulation,budget,planung,forecast,liste,übersicht,tabelle", ".xlsx,.xls,.csv,.ods", ""),
    C("b_marketing", "Marketing & Design", "Beruf", 16, "marketing,kampagne,flyer,logo,corporate design,newsletter,social media,branding", ".psd,.ai,.indd,.fig,.sketch", ""),
    C("b_software", "Softwareentwicklung", "Beruf", 18, "def ,class ,function,import ,repository,api,backend,frontend", ".py,.js,.ts,.tsx,.java,.cs,.go,.rs,.cpp,.c,.h,.php,.rb,.sql,.sh,.ps1", ""),
    C("b_it", "IT & Infrastruktur", "Beruf", 18, "server,netzwerk,firewall,vpn,backup,konfiguration,docker,kubernetes,azure,aws,active directory", ".yaml,.yml,.conf,.ini,.tf", ""),
    C("b_scm", "Einkauf & Lieferkette (SCM)", "Beruf", 26, "lieferant,supply chain,scm,lieferschein,einkauf,beschaffung,logistik,lager,disposition", "", ""),
    # ---------------- Beruf › Kapitel oneSCM (10) ----------------
    # Nur für Dateien, die erkennbar zu oneSCM gehören (Name, Pfad oder Inhalt nennt oneSCM – siehe CHAPTERS)
    C("o_programm", "Programm & Steuerung", "Beruf", 32, "programm,programmleitung,steering,lenkungskreis,roadmap,statusbericht,status report,meilenstein,projektplan,budget,ressourcenplanung", "", "", "oneSCM"),
    C("o_prozesse", "Prozesse & Design", "Beruf", 28, "prozess,blueprint,fit-gap,fit gap,soll-prozess,ist-prozess,bpmn,prozesslandkarte,prozessdesign,anforderung,requirement,konzept", ".vsdx,.bpmn", "", "oneSCM"),
    C("o_planung", "Planung & Disposition", "Beruf", 26, "demand,forecast,absatzplanung,s&op,ibp,disposition,mrp,bestandsplanung,kapazität,produktionsplanung,bedarfsplanung", "", "", "oneSCM"),
    C("o_einkauf", "Einkauf & Lieferanten", "Beruf", 28, "lieferant,supplier,sourcing,beschaffung,einkauf,purchase,rahmenvertrag,ausschreibung,lieferantenbewertung,bestellung", "", "", "oneSCM"),
    C("o_logistik", "Logistik & Lager", "Beruf", 24, "logistik,lager,warehouse,ewm,transport,tms,versand,spedition,wareneingang,warenausgang,kommissionierung,zoll", "", "", "oneSCM"),
    C("o_systeme", "Systeme & Stammdaten", "Beruf", 26, "sap,s/4hana,s4hana,stammdaten,materialstamm,schnittstelle,interface,datenmigration,migration,customizing,datenmodell,berechtigung", "", "", "oneSCM"),
    C("o_test", "Test & Rollout", "Beruf", 28, "test,testfall,testplan,testprotokoll,uat,integrationstest,cutover,go-live,golive,rollout,hypercare,welle", "", "", "oneSCM"),
    C("o_change", "Schulung & Change", "Beruf", 22, "schulung,training,key user,keyuser,change management,kommunikation,newsletter,e-learning,trainingsunterlage,stakeholder", "", "", "oneSCM"),
    C("o_kpi", "KPIs & Reporting", "Beruf", 24, "kpi,dashboard,reporting,report,otif,liefertreue,reichweite,bestandsreichweite,auswertung,kennzahl,power bi", "", "", "oneSCM"),
    C("o_meetings", "Meetings & Entscheidungen", "Beruf", 26, "protokoll,meeting,agenda,entscheidung,decision log,risiko,raid,issue,offene punkte,jour fixe,workshop", "", "", "oneSCM"),
    # ---------------- GenAI (10) ----------------
    C("g_prompts", "Prompts & Prompt-Bibliothek", "GenAI", 22, "prompt,system prompt,few-shot,anweisung an das modell,you are a,du bist ein", "", ""),
    C("g_modelle", "LLM-Modelle & Gewichte", "GenAI", 16, "gguf,safetensors,checkpoint,lora,weights,quantized,llama,mistral,qwen", ".gguf,.safetensors,.ckpt,.pt,.pth,.onnx,.bin", ""),
    C("g_datensaetze", "Datensätze & Training", "GenAI", 18, "dataset,datensatz,training data,jsonl,finetune,fine-tuning,annotation,label", ".jsonl,.parquet,.arrow", ""),
    C("g_notebooks", "Notebooks & Experimente", "GenAI", 18, "notebook,experiment,jupyter,colab,evaluation,benchmark", ".ipynb", ""),
    C("g_agenten", "KI-Agenten & Workflows", "GenAI", 24, "agent,langchain,langgraph,crewai,autogen,mcp,tool use,workflow,n8n,claude code", "", ""),
    C("g_rag", "RAG & Wissensdatenbanken", "GenAI", 22, "rag,retrieval,embedding,vektor,vector store,chroma,pinecone,qdrant,faiss,chunk", "", ""),
    C("g_medien", "KI-generierte Medien", "GenAI", 10, "midjourney,dall-e,stable diffusion,comfyui,sdxl,flux,generated,ai-art", "", ""),
    C("g_forschung", "KI-Forschung & Papers", "GenAI", 20, "arxiv,paper,transformer,attention,neural,llm,large language model,abstract,benchmark", "", ""),
    C("g_tools", "KI-Tools & Konfiguration", "GenAI", 18, "openai,anthropic,claude,chatgpt,gemini,ollama,lm studio,api key,huggingface,copilot", "", ""),
    C("g_strategie", "GenAI-Strategie & Use Cases", "GenAI", 26, "genai,generative ki,ki-strategie,use case,ki-governance,ai act,ki-richtlinie,copilot rollout", "", ""),
    # ---------------- Sonstiges (6) ----------------
    C("s_software", "Installer & Software", "Sonstiges", 4, "setup,installer,install", ".exe,.msi,.dmg,.pkg,.deb,.rpm,.apk,.iso", ""),
    C("s_archive", "Archive & Komprimiert", "Sonstiges", 6, "archiv,backup", ".zip,.rar,.7z,.tar,.gz,.tgz,.bz2", ""),
    C("s_backups", "Backups & Exporte", "Sonstiges", 8, "backup,sicherung,export,dump,bak", ".bak,.dump,.sqlite,.db", ""),
    C("s_system", "System & Logs", "Sonstiges", 1, "log,debug,cache,temp", ".log,.dll,.sys,.tmp,.dat,.ini", ""),
    C("s_ebooks", "E-Books & Literatur", "Sonstiges", 10, "ebook,buch,roman,kapitel,isbn", ".epub,.mobi,.azw3", ""),
    C("s_unbekannt", "Unsortiert", "Sonstiges", 2, "", "", ""),
]

assert len(CATEGORIES) == 60, len(CATEGORIES)

# Kapitel: eigene Kategorien innerhalb eines Bereichs, die nur greifen, wenn die Datei erkennbar dazugehört.
# triggers: Schreibweisen im Dateinamen, Pfad oder Inhalt; default: Kategorie, wenn sonst nichts genauer passt;
# doc_types: allgemeine Dokumentart (Protokoll, Zertifikat …) → passende Kapitel-Kategorie
CHAPTERS: dict[str, dict] = {
    "oneSCM": {
        "group": "Beruf",
        "triggers": ("onescm", "one scm", "one-scm", "one_scm"),
        "default": "o_programm",
        "doc_types": {"b_meetings": "o_meetings", "b_schulung": "o_change", "b_berichte": "o_kpi",
                      "b_angebote": "o_einkauf", "b_vertraege": "o_einkauf"},
        "beschreibung": "Eigenes Kapitel unter Beruf: alles, was zu oneSCM gehört, landet in 02_Beruf/oneSCM/…",
    },
}

BY_ID = {c.id: c for c in CATEGORIES}
BY_NAME = {c.name.lower(): c for c in CATEGORIES}

# Wichtige Labels, die die Wichtigkeit erhöhen
IMPORTANT_LABELS = {
    "Vertrag": 12, "Rechnung": 6, "Steuer": 12, "Frist": 14, "Unterschrift": 10, "Original": 8,
    "Ausweis": 14, "Urkunde": 14, "Zeugnis": 10, "Versicherung": 8, "Vertraulich": 10, "Personenbezogen": 6,
    "Finanzen": 6, "Gesundheit": 8, "Kündigung": 10, "Bescheid": 10, "Rechtlich": 8, "Aufbewahrungspflicht": 10,
}


def find_category(name_or_id: str | None) -> Category:
    if not name_or_id:
        return BY_ID["s_unbekannt"]
    k = name_or_id.strip()
    if k in BY_ID:
        return BY_ID[k]
    c = BY_NAME.get(k.lower())
    if c:
        return c
    for cat in CATEGORIES:  # tolerant gegenüber leichten LLM-Abweichungen
        if k.lower() in cat.name.lower() or cat.name.lower() in k.lower():
            return cat
    return BY_ID["s_unbekannt"]


def as_dicts() -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "short": c.short, "chapter": c.chapter, "group": c.group, "weight": c.weight, "folder": c.folder,
         "keywords": list(c.keywords), "exts": list(c.exts), "subfolders": list(c.subfolders)}
        for c in CATEGORIES
    ]
