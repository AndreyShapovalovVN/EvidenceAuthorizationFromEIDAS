"""Evidence view-model builders for preview pages."""

from typing import Any

_PRIMARY_NODES = {"MainEvidence", "HumanReadableVersion"}


def is_new_evidences_structure(data: dict[str, Any]) -> bool:
    evidences = data.get("evidences")
    if not isinstance(evidences, list) or not evidences:
        return False
    first = evidences[0]
    return isinstance(first, dict) and isinstance(first.get("RegistryPackage"), list)


def normalize_preview_descriptions(data: dict[str, Any]) -> list[str]:
    descriptions: list[str] = []
    raw = data.get("PreviewDescription", [])
    if not isinstance(raw, list):
        return descriptions

    for item in raw:
        if isinstance(item, dict):
            if "value" in item:
                descriptions.append(str(item.get("value", "")))
            else:
                descriptions.extend(str(value) for value in item.values())

    return [value for value in descriptions if value]


# ── helpers ───────────────────────────────────────────────────────────────────

def _classification_node(obj: dict[str, Any]) -> str:
    classification = obj.get("classification", {})
    if not isinstance(classification, dict):
        return "Unknown"
    return str(classification.get("classificationNode") or "Unknown")


def _repo_ref_info(obj: dict[str, Any], fallback_title: str) -> tuple[str, str]:
    """Returns (title, href) from RepositoryItemRef."""
    repo_ref = obj.get("RepositoryItemRef", {})
    if not isinstance(repo_ref, dict):
        return fallback_title, ""
    return str(repo_ref.get("title") or fallback_title).strip(), str(repo_ref.get("href") or "")


def _content_label(class_node: str, ref_title: str) -> str:
    if ref_title and ref_title != class_node:
        return f"{class_node}: {ref_title}"
    return class_node


def _default_content_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        (
            item for item in items
            if item["classification_node"] == "HumanReadableVersion"
            and item["content_type"] == "application/pdf"
        ),
        items[0],
    )


# ── per-item builders ─────────────────────────────────────────────────────────

def _build_content_item(obj: dict[str, Any], approval_key: str, index: int) -> dict[str, Any]:
    class_node = _classification_node(obj)
    ref_title, ref_href = _repo_ref_info(obj, class_node)
    return {
        "id": f"{approval_key}:{index}",
        "label": _content_label(class_node, ref_title),
        "classification_node": class_node,
        "content_type": str(obj.get("content_type") or ""),
        "content": obj.get("content"),
        "cid": ref_href,
    }


def _resolve_package_title(
    package: dict[str, Any],
    content_items: list[dict[str, Any]],
    approval_key: str,
    package_index: int,
) -> str:
    title = str(package.get("title") or "").strip()
    if not title:
        title = next(
            (
                item["label"].split(": ", 1)[-1]
                for item in content_items
                if item["classification_node"] in _PRIMARY_NODES
            ),
            "",
        )
    return title or str(approval_key).strip() or f"Evidence {package_index + 1}"


def _build_new_evidence_entry(package: dict[str, Any], package_index: int) -> dict[str, Any] | None:
    approval_key = str(package.get("id") or f"evidence-{package_index}")
    content_items = [
        _build_content_item(obj, approval_key, i)
        for i, obj in enumerate(package.get("RegistryPackage", []))
        if isinstance(obj, dict)
    ]
    if not content_items:
        return None
    title = _resolve_package_title(package, content_items, approval_key, package_index)
    return {
        "id": f"evidence-{package_index}",
        "approval_key": approval_key,
        "title": title,
        "permit": bool(package.get("permit", False)),
        "default_content_id": _default_content_item(content_items)["id"],
        "contents": content_items,
    }


def _build_legacy_evidence_entry(item: dict[str, Any], index: int) -> dict[str, Any]:
    cid = str(item.get("cid") or f"legacy-{index}")
    content_id = f"legacy-{index}:0"
    title = str(item.get("title") or "").strip() or cid or f"Evidence {index + 1}"
    return {
        "id": f"legacy-{index}",
        "approval_key": cid,
        "title": title,
        "permit": bool(item.get("permit", False)),
        "default_content_id": content_id,
        "contents": [
            {
                "id": content_id,
                "label": f"MainEvidence: {cid}",
                "classification_node": "MainEvidence",
                "content_type": str(item.get("content_type") or ""),
                "content": item.get("content"),
                "cid": cid,
            }
        ],
    }


# ── public API ────────────────────────────────────────────────────────────────

def build_evidence_view_model(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Builds unified UI model for both new and legacy evidence formats."""
    evidences: list[Any] = data.get("evidences") or []

    if is_new_evidences_structure(data):
        return [
            entry
            for i, pkg in enumerate(evidences)
            if isinstance(pkg, dict)
            for entry in [_build_new_evidence_entry(pkg, i)]
            if entry is not None
        ]

    return [
        _build_legacy_evidence_entry(item, i)
        for i, item in enumerate(evidences)
        if isinstance(item, dict)
    ]

