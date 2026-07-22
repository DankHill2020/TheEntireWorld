"""Infer loose input/output contracts for workflow composition."""

from __future__ import annotations

import re


CAPABILITY_KEYWORDS = {
    "image": ("image", "img", "png", "jpg", "jpeg", "tif", "texture", "picture", "photo"),
    "mesh": ("mesh", "geometry", "geo", "obj", "fbx", "usd", "surface", "vertices", "vertex"),
    "file": ("file", "path", "filepath", "filename", "directory", "folder", "browse", "select"),
    "bone": ("bone", "joint", "skeleton", "hierarchy", "root", "slot", "influence"),
    "animation": ("anim", "animation", "keyframe", "bake", "take", "clip"),
    "rig": ("rig", "rigs", "control", "controls", "ctrl", "constraint", "ik", "fk"),
    "material": ("material", "shader", "texture", "uv"),
    "scene_object": ("object", "node", "transform", "selection", "selected"),
}


TERM_EXPANSIONS_BY_CONTEXT = {
    "rig": {
        "rig": ("rigging",),
        "rigs": ("rig", "rigging"),
        "rigging": ("rig", "rigs"),
        "control": ("controls", "ctrl"),
        "controls": ("control", "ctrl"),
        "ctrl": ("control", "controls"),
        "joint": ("joints", "skeleton"),
        "joints": ("joint", "skeleton"),
        "constraint": ("constraints",),
        "constraints": ("constraint",),
    },
    "ui": {
        "control": ("controls", "widget", "qwidget"),
        "controls": ("control", "widget", "qwidget"),
        "widget": ("widgets", "qwidget", "control"),
        "widgets": ("widget", "qwidget", "control"),
        "button": ("buttons", "btn", "qpushbutton"),
        "buttons": ("button", "btn", "qpushbutton"),
        "dialog": ("dialogs", "window"),
        "window": ("dialog", "windows"),
    },
    "vcs": {
        "source": ("version", "vcs"),
        "version": ("source", "vcs"),
        "control": ("vcs",),
        "git": ("github",),
        "github": ("git",),
        "perforce": ("p4",),
        "p4": ("perforce",),
    },
}


def infer_term_context(text: str = "", terms: list[str] | tuple[str, ...] | set[str] = ()) -> set[str]:
    """Infer which domain ambiguous terms belong to."""
    lowered = (text or "").replace("\\", "/").lower()
    tokens = set(tokenize(" ".join([lowered, " ".join(str(term) for term in terms or [])])))
    contexts: set[str] = set()
    if (
        {"source", "version"} & tokens
        and "control" in tokens
    ) or tokens & {"vcs", "git", "github", "perforce", "p4", "svn"}:
        contexts.add("vcs")
    if tokens & {"qt", "qwidget", "widget", "button", "btn", "dialog", "window", "ui", "menu"}:
        contexts.add("ui")
    if (
        tokens & {"maya", "rig", "rigs", "rigging", "joint", "joints", "skeleton", "ik", "fk", "constraint", "character"}
        or "maya_tools/rigging" in lowered
        or "/rigging/" in lowered
    ):
        contexts.add("rig")
    if "vcs" in contexts:
        contexts.discard("rig")
        contexts.discard("ui")
    return contexts


def expand_terms(
    terms: list[str] | tuple[str, ...] | set[str],
    *,
    context: str = "",
    contexts: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Expand search terms through request-aware capability terminology."""
    ordered: list[str] = []

    def add(term: str):
        value = (term or "").strip().lower()
        if value and value not in ordered:
            ordered.append(value)

    for term in terms or []:
        add(str(term))
    inferred_contexts = set(contexts or infer_term_context(context, ordered))
    for context_key in sorted(inferred_contexts):
        expansions = TERM_EXPANSIONS_BY_CONTEXT.get(context_key) or {}
        for term in list(ordered):
            for keyword in expansions.get(term, ()):
                add(keyword)
    return ordered


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or "")]


def classify_text(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(tokenize(lowered))
    categories = set()
    for category, keywords in CAPABILITY_KEYWORDS.items():
        if any(keyword in lowered or keyword in tokens for keyword in keywords):
            categories.add(category)
    if "image" in categories:
        categories.add("file")
    if "mesh" in categories:
        categories.add("file")
    return categories


def infer_symbol_contract(symbol: dict) -> dict:
    params = symbol.get("params") or []
    returns = symbol.get("returns") or []
    source_context = " ".join(
        str(symbol.get(key, ""))
        for key in ("name", "signature", "docstring", "file_path", "source", "return_annotation")
    )

    inputs = []
    for param in params:
        name = param.get("name", "")
        annotation = param.get("annotation", "")
        categories = sorted(classify_text(f"{name} {annotation} {source_context}"))
        inputs.append({"name": name, "types": categories})

    outputs = []
    return_annotation = symbol.get("return_annotation", "")
    for ret in returns:
        categories = sorted(classify_text(f"{ret} {return_annotation} {source_context}"))
        outputs.append({"name": ret, "types": categories})

    if not outputs:
        inferred = sorted(classify_text(f"{symbol.get('name', '')} {return_annotation} {source_context}"))
        if inferred:
            outputs.append({"name": "output", "types": inferred})

    contract = {
        "inputs": inputs,
        "outputs": outputs,
        "categories": sorted(classify_text(source_context)),
    }
    return contract


def annotate_symbol(symbol: dict) -> dict:
    item = dict(symbol)
    item["contract"] = infer_symbol_contract(item)
    return item


def annotate_symbols(symbols: list[dict]) -> list[dict]:
    return [annotate_symbol(symbol) for symbol in symbols]


def _types_compatible(output_types: set[str], input_types: set[str], output_name: str = "", input_name: str = "") -> bool:
    overlap = output_types & input_types
    if not overlap:
        return False
    output_name = (output_name or "").lower()
    input_name = (input_name or "").lower()
    if "mesh" in output_name and "mesh" not in input_name:
        return False
    if "image" in input_name and "image" not in output_name and "img" not in output_name:
        return False
    if overlap == {"file"} and (output_types - {"file"}) and (input_types - {"file"}):
        return False
    return True


def suggest_links(upstream_symbols: list[dict], downstream_symbols: list[dict], limit: int = 8) -> list[str]:
    suggestions = []
    seen = set()
    for upstream in annotate_symbols(upstream_symbols):
        upstream_name = upstream.get("name") or "upstream"
        for output in upstream.get("contract", {}).get("outputs", []):
            output_types = set(output.get("types") or [])
            if not output_types:
                continue
            for downstream in annotate_symbols(downstream_symbols):
                downstream_name = downstream.get("name") or "downstream"
                for input_item in downstream.get("contract", {}).get("inputs", []):
                    input_types = set(input_item.get("types") or [])
                    if not _types_compatible(
                        output_types,
                        input_types,
                        output.get("name", ""),
                        input_item.get("name", ""),
                    ):
                        continue
                    link = f"{upstream_name}.{output.get('name', 'output')} -> {downstream_name}.{input_item.get('name', 'input')}"
                    if link in seen:
                        continue
                    seen.add(link)
                    suggestions.append(link)
                    if len(suggestions) >= limit:
                        return suggestions
    return suggestions


def recommend_workflow_connections(
    anchor_symbols: list[dict],
    internal_candidates: list[dict],
    external_candidates: list[dict],
    limit: int = 8,
) -> dict:
    """Recommend links in either direction, preferring project-internal functions before ingested tools."""
    selected_names = {symbol.get("name") for symbol in anchor_symbols if symbol.get("name")}
    internal_downstream = [
        symbol
        for symbol in internal_candidates
        if symbol.get("name") not in selected_names
    ]

    internal_links = []
    internal_links.extend(suggest_links(internal_downstream, anchor_symbols, limit=limit))
    remaining = max(limit - len(internal_links), 0)
    if remaining:
        internal_links.extend(suggest_links(anchor_symbols, internal_downstream, limit=remaining))
    internal_upstream_links = suggest_links(internal_downstream, anchor_symbols, limit=limit)
    if internal_links:
        directions = []
        if internal_upstream_links:
            directions.append("upstream")
        if any(link not in internal_upstream_links for link in internal_links):
            directions.append("downstream")
        return {
            "source": "internal",
            "direction": "+".join(directions) or "matched",
            "links": internal_links,
            "message": "Suggested internal prerequisite/follow-up function links.",
        }

    external_links = []
    external_links.extend(suggest_links(external_candidates, anchor_symbols, limit=limit))
    remaining = max(limit - len(external_links), 0)
    if remaining:
        external_links.extend(suggest_links(anchor_symbols, external_candidates, limit=remaining))
    external_upstream_links = suggest_links(external_candidates, anchor_symbols, limit=limit)
    if external_links:
        directions = []
        if external_upstream_links:
            directions.append("upstream")
        if any(link not in external_upstream_links for link in external_links):
            directions.append("downstream")
        return {
            "source": "github",
            "direction": "+".join(directions) or "matched",
            "links": external_links,
            "message": "Suggested ingested GitHub/tool prerequisite/follow-up links.",
        }

    return {
        "source": "missing",
        "direction": "",
        "links": [],
        "message": "No matching internal or ingested follow-up function was inferred.",
    }


def format_contract(symbol: dict) -> str:
    contract = symbol.get("contract") or infer_symbol_contract(symbol)
    inputs = ", ".join(
        f"{item.get('name')}:{'/'.join(item.get('types') or ['unknown'])}"
        for item in contract.get("inputs", [])
    )
    outputs = ", ".join(
        f"{item.get('name')}:{'/'.join(item.get('types') or ['unknown'])}"
        for item in contract.get("outputs", [])
    )
    pieces = []
    if inputs:
        pieces.append(f"in[{inputs}]")
    if outputs:
        pieces.append(f"out[{outputs}]")
    return " ".join(pieces)
