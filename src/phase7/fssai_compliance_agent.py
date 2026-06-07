"""FSSAI Compliance Agent — checks food-business compliance with India's
Food Safety and Standards Authority of India (FSSAI) regulations.

Outputs:

* License-type recommendation (Basic / State / Central) based on turnover,
  capacity, and business type.
* Mandatory label-element checklist (per FoP/Legal metrology + FSSAI).
* Common non-conformances for the business category.
* A documentation checklist (FSSAI forms, declarations, lab reports).
* Audit-ready evidence pack manifest.

Heuristic + LLM-driven.  Works offline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

BUSINESS_CATEGORIES = (
    "manufacturer", "repacker", "relabeller", "importer", "exporter",
    "retailer", "distributor", "transporter", "warehouser", "e_commerce",
    "restaurant", "cloud_kitchen", "caterer", "baker", "sweet_shop",
    "dairy", "meat", "beverages", "supplements", "other",
)


def fssai_compliance_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    business = (args.get("business") or args.get("description") or "").strip()
    if not business:
        return {"summary": "No business description supplied.", "error": "business is required",
                "checklist": []}

    category = (args.get("category") or _guess_category(business)).lower()
    if category not in BUSINESS_CATEGORIES:
        category = "other"
    turnover_cr = float(args.get("turnover_cr") or 0.0)  # ₹ crore
    daily_capacity_kg = float(args.get("daily_capacity_kg") or 0.0)
    state = args.get("state") or "unspecified"
    products: List[str] = args.get("products") or []
    sells_online = bool(args.get("sells_online", False))
    interstate = bool(args.get("interstate", False))

    license_type = _recommend_license(turnover_cr, daily_capacity_kg, interstate, category)
    label_checklist = _label_checklist(category, products, sells_online)
    non_conformances = _non_conformances(category, sells_online)
    doc_checklist = _documents(license_type, category, sells_online)
    llm_notes = _llm_notes(business, category, license_type, label_checklist, non_conformances)

    payload = {
        "summary": _summary(category, license_type, len(non_conformances), llm_notes),
        "business": business,
        "category": category,
        "state": state,
        "license_recommended": license_type,
        "label_checklist": label_checklist,
        "non_conformances": non_conformances,
        "documents_required": doc_checklist,
        "llm_notes": llm_notes,
        "evidence_pack": [f"docs/{d}" for d in doc_checklist],
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", category).strip("_") or "fssai"
    _save("phase7/fssai", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("fssai_compliance_agent", category, f"license={license_type} nc={len(non_conformances)}")
    return payload


# ---------------------------------------------------------------------------

def _guess_category(text: str) -> str:
    t = text.lower()
    for c in BUSINESS_CATEGORIES:
        if c.replace("_", " ") in t:
            return c
    if "cloud kitchen" in t: return "cloud_kitchen"
    if "restaurant" in t or "hotel" in t or "cafe" in t: return "restaurant"
    if "manufact" in t or "factory" in t: return "manufacturer"
    if "import" in t: return "importer"
    if "export" in t: return "exporter"
    if "shop" in t or "kirana" in t or "retail" in t: return "retailer"
    return "other"


def _recommend_license(turnover_cr: float, capacity_kg: float, interstate: bool, category: str) -> str:
    if category in {"importer", "exporter"}:
        return "Central FSSAI License (Import/Export)"
    if interstate or turnover_cr >= 20 or capacity_kg >= 2000:
        return "Central FSSAI License"
    if turnover_cr >= 0.0 or capacity_kg > 0:
        return "State FSSAI License"
    return "Basic FSSAI Registration"


def _label_checklist(category: str, products: List[str], online: bool) -> List[Dict[str, str]]:
    base = [
        {"item": "Product name", "rule": "FSSAI Packaging & Labelling Regulations, 2011"},
        {"item": "List of ingredients (in descending order of weight)", "rule": "Reg. 2.2.1(7)"},
        {"item": "Nutritional information (energy, protein, carbs, fat, sugar, sodium)", "rule": "Reg. 2.2.1(8)"},
        {"item": "Veg / Non-veg symbol (green/brown)", "rule": "Reg. 2.2.1(9)"},
        {"item": "Net quantity (SI units)", "rule": "Legal Metrology (Packaged Commodities) Rules, 2011"},
        {"item": "Manufacturer name & address", "rule": "Reg. 2.2.1(1)"},
        {"item": "FSSAI logo + 14-digit license number", "rule": "Reg. 2.2.1(10)"},
        {"item": "Batch / Lot number", "rule": "Reg. 2.2.1(13)"},
        {"item": "Best-before / Use-by date", "rule": "Reg. 2.2.1(12)"},
        {"item": "Country of origin for imported food", "rule": "Reg. 2.2.1(2)"},
        {"item": "Customer-care contact (phone/email)", "rule": "Reg. 2.2.1(15)"},
        {"item": "Declaration of additives / added colours / flavours", "rule": "Reg. 2.2.1(11)"},
    ]
    if online:
        base.append({"item": "E-commerce declaration (seller details visible on listing)", "rule": "FSSAI e-commerce guidelines 2022"})
    if any(p.lower() in {"organic"} for p in products):
        base.append({"item": "India Organic / USDA Organic certification mark", "rule": "NPOP + FSSAI"})
    return base


def _non_conformances(category: str, online: bool) -> List[Dict[str, str]]:
    common = [
        {"issue": "Missing FSSAI logo or logo below 14-digit license", "severity": "high", "fix": "Display FSSAI logo with the 14-digit license number on the principal display panel."},
        {"issue": "Allergen not declared", "severity": "high", "fix": "Add 'Contains: ...' line listing allergens (milk, nuts, soy, gluten) per FSSAI Allergen labelling 2022."},
        {"issue": "Veg / Non-veg symbol wrong colour / missing", "severity": "medium", "fix": "Use a 3mm minimum green square (veg) or brown triangle (non-veg) on the principal panel."},
        {"issue": "Use-by date format not DD/MM/YY or DD/MM/YYYY", "severity": "low", "fix": "Use DD/MM/YYYY format preceded by 'Best before' or 'Use by'."},
    ]
    if category in {"restaurant", "cloud_kitchen", "caterer", "baker", "sweet_shop"}:
        common.append({"issue": "Display board missing FSSAI license number", "severity": "high", "fix": "Display license number at the entrance/counter in a clearly-readable font."})
    if online:
        common.append({"issue": "Listing not linked to FSSAI license", "severity": "high", "fix": "Upload the 14-digit FSSAI license on the e-commerce seller dashboard."})
    return common


def _documents(license_type: str, category: str, online: bool) -> List[str]:
    base = [
        "Form A (Basic) or Form B (State/Central) — duly filled",
        "Blueprint/layout of the premises (food safety view)",
        "List of directors / partners / proprietor with ID proof",
        "List of food categories manufactured / handled",
        "Water analysis report (potability) from NABL-accredited lab",
        "Pest-control contract / certificate",
        "Waste-disposal contract / NOC from local body",
        "Photo of premises + equipment",
        "Proof of possession of premises (rent/lease deed)",
    ]
    if category == "manufacturer":
        base += ["Equipment list", "Process flow diagram", "Recall plan", "HACCP/ISO 22000 cert (if any)"]
    if category in {"importer", "exporter"}:
        base += ["IEC code", "Customs registration", "Foreign supplier agreement", "Country-of-origin certificate"]
    if online:
        base += ["E-commerce seller agreement", "Website/product-listing screenshots"]
    return base


def _llm_notes(business: str, category: str, license_type: str, labels: List[Dict[str, Any]], nc: List[Dict[str, Any]]) -> Dict[str, Any]:
    system = (
        "You are an FSSAI compliance expert.  Return ONLY a JSON object: "
        "{\"summary\": str, \"top_priorities\": [str], \"common_mistakes\": [str]}  "
        "No prose, no fences."
    )
    user = (
        f"Business: {business}\nCategory: {category}\nLicense: {license_type}\n\n"
        f"Label items ({len(labels)}): {json.dumps(labels)[:2000]}\n"
        f"Non-conformances ({len(nc)}): {json.dumps(nc)[:1500]}"
    )
    raw = _llm(user, system, "fssai_compliance_agent")
    return _parse_json(raw, fallback={"summary": "", "top_priorities": [], "common_mistakes": []})


def _summary(category: str, license_type: str, n_nc: int, notes: Dict[str, Any]) -> str:
    return (f"FSSAI ({category}): {license_type}; "
            f"{n_nc} common non-conformances. "
            f"{len(notes.get('top_priorities', []))} priority actions.")
