"""Evidence view-model builders for preview pages."""

from typing import Any


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



def build_evidence_view_model(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Builds unified UI model for both new and legacy evidence formats."""
    results: list[dict[str, Any]] = []

    if is_new_evidences_structure(data):
        for package_index, package in enumerate(data.get("evidences", [])):
            if not isinstance(package, dict):
                continue

            approval_key = str(package.get("id") or f"evidence-{package_index}")
            permit = bool(package.get("permit", False))
            package_objects = package.get("RegistryPackage", [])

            content_items: list[dict[str, Any]] = []
            title = str(package.get("title") or "").strip()

            for content_index, obj in enumerate(package_objects):
                if not isinstance(obj, dict):
                    continue

                classification = obj.get("classification", {})
                class_node = "Unknown"
                if isinstance(classification, dict):
                    class_node = str(classification.get("classificationNode") or "Unknown")

                repo_ref = obj.get("RepositoryItemRef", {})
                ref_title = class_node
                ref_href = ""
                if isinstance(repo_ref, dict):
                    ref_title = str(repo_ref.get("title") or class_node)
                    ref_href = str(repo_ref.get("href") or "")

                ref_title_str = str(ref_title).strip()
                if not title and class_node in {"MainEvidence", "HumanReadableVersion"}:
                    title = ref_title_str

                content_type = str(obj.get("content_type") or "")
                content = obj.get("content")
                label = class_node
                if ref_title_str and ref_title_str != class_node:
                    label = f"{class_node}: {ref_title_str}"

                content_items.append(
                    {
                        "id": f"{approval_key}:{content_index}",
                        "label": label,
                        "classification_node": class_node,
                        "content_type": content_type,
                        "content": content,
                        "cid": ref_href,
                    }
                )

            if not content_items:
                continue

            if not title:
                title = str(approval_key).strip() or f"Evidence {package_index + 1}"

            default_item = next(
                (
                    item for item in content_items
                    if item["classification_node"] == "HumanReadableVersion"
                    and item["content_type"] == "application/pdf"
                ),
                content_items[0],
            )

            results.append(
                {
                    "id": f"evidence-{package_index}",
                    "approval_key": approval_key,
                    "title": title,
                    "permit": permit,
                    "default_content_id": default_item["id"],
                    "contents": content_items,
                }
            )

        return results

    for index, item in enumerate(data.get("evidences", [])):
        if not isinstance(item, dict):
            continue

        cid = str(item.get("cid") or f"legacy-{index}")
        content_type = str(item.get("content_type") or "")
        content = item.get("content")
        content_id = f"legacy-{index}:0"
        title = str(item.get("title") or "").strip() or str(cid).strip() or f"Evidence {index + 1}"

        results.append(
            {
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
                        "content_type": content_type,
                        "content": content,
                        "cid": cid,
                    }
                ],
            }
        )

    return results

