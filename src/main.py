import argparse
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import supervisely as sly


SUPPORTED_VIEWS = {
    "back",
    "back-left",
    "back-right",
    "front",
    "front-left",
    "front-right",
    "left",
    "other",
    "right",
}

LEFT_VIEWS = {"left", "front-left", "back-left"}
RIGHT_VIEWS = {"right", "front-right", "back-right"}
OBLIQUE_VIEWS = {"front-left", "front-right", "back-left", "back-right"}

SIDE_DOMINANT_CLASSES = {
    "Mirror",
    "Front-window",
    "Back-window",
    "Front-door",
    "Back-door",
    "Front-wheel",
    "Back-wheel",
    "Fender",
    "Quarter-panel",
    "Rocker-panel",
}

PAIRABLE_CLASSES = SIDE_DOMINANT_CLASSES | {"Headlight", "Tail-light"}

UNSUPPORTED_OR_CENTRAL_CLASSES = {
    "Roof",
    "Hood",
    "Trunk",
    "Grille",
    "License-plate",
    "Windshield",
    "Back-windshield",
    "Front-bumper",
    "Back-bumper",
}

DEFAULT_VIEW_TAG_CANDIDATES = ["view", "car_view"]


@dataclass
class GeometryInfo:
    bbox_left: float
    bbox_top: float
    bbox_right: float
    bbox_bottom: float
    center_x: float
    width: float
    height: float
    bbox_area: float
    approx_area: float


@dataclass
class SideDecision:
    side: Optional[str]
    needs_review: bool
    reason: str


_CLASS_ALIAS_MAP = {
    "headlight": "Headlight",
    "head-light": "Headlight",
    "tail-light": "Tail-light",
    "taillight": "Tail-light",
    "tail-lights": "Tail-light",
    "tail-light": "Tail-light",
    "tail light": "Tail-light",
    "mirror": "Mirror",
    "front-window": "Front-window",
    "front window": "Front-window",
    "back-window": "Back-window",
    "back window": "Back-window",
    "front-door": "Front-door",
    "front door": "Front-door",
    "back-door": "Back-door",
    "back door": "Back-door",
    "front-wheel": "Front-wheel",
    "front wheel": "Front-wheel",
    "back-wheel": "Back-wheel",
    "back wheel": "Back-wheel",
    "fender": "Fender",
    "quarter-panel": "Quarter-panel",
    "quarter panel": "Quarter-panel",
    "rocker-panel": "Rocker-panel",
    "rocker panel": "Rocker-panel",
    "roof": "Roof",
    "hood": "Hood",
    "trunk": "Trunk",
    "grille": "Grille",
    "license-plate": "License-plate",
    "license plate": "License-plate",
    "windshield": "Windshield",
    "back-windshield": "Back-windshield",
    "back windshield": "Back-windshield",
    "front-bumper": "Front-bumper",
    "front bumper": "Front-bumper",
    "back-bumper": "Back-bumper",
    "back bumper": "Back-bumper",
}


def _normalize_token(value: str) -> str:
    return "-".join(str(value).strip().lower().replace("_", " ").split())


def normalize_class_name(name: str) -> Optional[str]:
    token = _normalize_token(name)
    return _CLASS_ALIAS_MAP.get(token)


def normalize_view_name(view: str) -> Optional[str]:
    token = _normalize_token(view)
    return token if token in SUPPORTED_VIEWS else None


def _build_tag_meta(name: str, value_type: sly.TagValueType, possible_values: Optional[List[str]] = None) -> sly.TagMeta:
    kwargs: Dict[str, Any] = {}
    if possible_values is not None:
        kwargs["possible_values"] = possible_values

    if hasattr(sly, "TagApplicableTo"):
        tag_applicable_to = sly.TagApplicableTo
        applicable_to = (
            getattr(tag_applicable_to, "OBJECTS", None)
            or getattr(tag_applicable_to, "OBJECTS_ONLY", None)
            or getattr(tag_applicable_to, "ALL", None)
        )
        if applicable_to is not None:
            kwargs["applicable_to"] = applicable_to

    try:
        return sly.TagMeta(name=name, value_type=value_type, **kwargs)
    except TypeError:
        kwargs.pop("applicable_to", None)
        return sly.TagMeta(name=name, value_type=value_type, **kwargs)


def ensure_side_tag_metas(api: sly.Api, project_id: int) -> Tuple[sly.ProjectMeta, Dict[str, sly.TagMeta]]:
    project_meta = sly.ProjectMeta.from_json(api.project.get_meta(project_id))
    updates_required = False

    required = {
        "side": (sly.TagValueType.ONEOF_STRING, ["left", "right"]),
        "side_source": (sly.TagValueType.ONEOF_STRING, ["auto"]),
        "needs_review": (sly.TagValueType.ONEOF_STRING, ["yes", "no"]),
        "side_reason": (sly.TagValueType.ANY_STRING, None),
    }

    metas: Dict[str, sly.TagMeta] = {}
    for name, (value_type, values) in required.items():
        tag_meta = project_meta.get_tag_meta(name)
        if tag_meta is None:
            tag_meta = _build_tag_meta(name=name, value_type=value_type, possible_values=values)
            project_meta = project_meta.add_tag_meta(tag_meta)
            updates_required = True
        metas[name] = tag_meta

    if updates_required:
        api.project.update_meta(project_id, project_meta.to_json())

    return project_meta, metas


def _extract_bbox_coords(bbox: Any) -> Tuple[float, float, float, float]:
    left = getattr(bbox, "left", None)
    top = getattr(bbox, "top", None)
    right = getattr(bbox, "right", None)
    bottom = getattr(bbox, "bottom", None)

    left = left() if callable(left) else left
    top = top() if callable(top) else top
    right = right() if callable(right) else right
    bottom = bottom() if callable(bottom) else bottom

    if None not in (left, top, right, bottom):
        return float(left), float(top), float(right), float(bottom)

    data = bbox.to_json() if hasattr(bbox, "to_json") else {}
    if "left" in data and "top" in data and "right" in data and "bottom" in data:
        return float(data["left"]), float(data["top"]), float(data["right"]), float(data["bottom"])

    exterior = data.get("points", {}).get("exterior", None)
    if exterior and len(exterior) >= 2:
        x_values = [float(p[0]) for p in exterior]
        y_values = [float(p[1]) for p in exterior]
        return min(x_values), min(y_values), max(x_values), max(y_values)

    raise RuntimeError("Failed to extract bbox coordinates")


def get_geometry_info(label: sly.Label) -> GeometryInfo:
    bbox = label.geometry.to_bbox()
    left, top, right, bottom = _extract_bbox_coords(bbox)

    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    bbox_area = width * height

    geom_area = None
    area_attr = getattr(label.geometry, "area", None)
    if callable(area_attr):
        try:
            geom_area = float(area_attr())
        except Exception:
            geom_area = None
    elif area_attr is not None:
        try:
            geom_area = float(area_attr)
        except Exception:
            geom_area = None

    approx_area = geom_area if geom_area is not None and geom_area > 0 else bbox_area

    return GeometryInfo(
        bbox_left=left,
        bbox_top=top,
        bbox_right=right,
        bbox_bottom=bottom,
        center_x=left + width / 2.0,
        width=width,
        height=height,
        bbox_area=bbox_area,
        approx_area=approx_area,
    )


def _find_existing_view(ann: sly.Annotation, view_tag_candidates: List[str]) -> Tuple[Optional[str], Optional[str]]:
    tag_map = {_normalize_token(name): name for name in view_tag_candidates}

    for tag in ann.img_tags:
        normalized_name = _normalize_token(tag.meta.name)
        if normalized_name not in tag_map:
            continue

        normalized_view = normalize_view_name(str(tag.value))
        if normalized_view is not None:
            return normalized_view, tag.meta.name

    return None, None


def _decisions_by_area_dominance(
    objects: List[Tuple[int, GeometryInfo]],
    dominant_side: str,
    ratio_threshold: float,
    reason_prefix: str,
) -> Dict[int, SideDecision]:
    if len(objects) != 2:
        return {idx: SideDecision(side=None, needs_review=True, reason="not exactly two objects") for idx, _ in objects}

    sorted_objects = sorted(objects, key=lambda item: item[1].approx_area, reverse=True)
    large_idx, large_geom = sorted_objects[0]
    small_idx, small_geom = sorted_objects[1]

    if small_geom.approx_area <= 0:
        return {
            large_idx: SideDecision(side=None, needs_review=True, reason="invalid area for pair comparison"),
            small_idx: SideDecision(side=None, needs_review=True, reason="invalid area for pair comparison"),
        }

    ratio = large_geom.approx_area / small_geom.approx_area
    if ratio < ratio_threshold:
        reason = f"{reason_prefix}; size ratio {ratio:.2f} < {ratio_threshold:.2f}"
        return {
            large_idx: SideDecision(side=None, needs_review=True, reason=reason),
            small_idx: SideDecision(side=None, needs_review=True, reason=reason),
        }

    opposite = "right" if dominant_side == "left" else "left"
    return {
        large_idx: SideDecision(
            side=dominant_side,
            needs_review=False,
            reason=f"{reason_prefix}; larger object interpreted as visible {dominant_side} side (ratio {ratio:.2f})",
        ),
        small_idx: SideDecision(
            side=opposite,
            needs_review=False,
            reason=f"{reason_prefix}; smaller object interpreted as opposite side (ratio {ratio:.2f})",
        ),
    }


def _assign_side_for_headlight(
    objects: List[Tuple[int, GeometryInfo]],
    view: str,
    image_width: int,
    ratio_threshold: float,
) -> Dict[int, SideDecision]:
    if view == "front":
        if len(objects) == 2:
            by_x = sorted(objects, key=lambda item: item[1].center_x)
            left_idx = by_x[0][0]
            right_idx = by_x[1][0]
            return {
                left_idx: SideDecision(side="right", needs_review=False, reason="front view: left image headlight is car right"),
                right_idx: SideDecision(side="left", needs_review=False, reason="front view: right image headlight is car left"),
            }

        if len(objects) == 1:
            idx, geom = objects[0]
            left_zone = image_width * 0.45
            right_zone = image_width * 0.55
            if geom.center_x < left_zone:
                return {idx: SideDecision(side="right", needs_review=False, reason="front view: headlight in left image half")}
            if geom.center_x > right_zone:
                return {idx: SideDecision(side="left", needs_review=False, reason="front view: headlight in right image half")}
            return {
                idx: SideDecision(
                    side=None,
                    needs_review=True,
                    reason="front view: single headlight too central to decide",
                )
            }

        return {idx: SideDecision(side=None, needs_review=True, reason="front view: unsupported headlight count") for idx, _ in objects}

    if view in {"front-left", "front-right"}:
        dominant = "left" if view == "front-left" else "right"
        if len(objects) == 1:
            idx, _ = objects[0]
            return {idx: SideDecision(side=dominant, needs_review=False, reason=f"{view}: dominant visible side")}
        if len(objects) == 2:
            return _decisions_by_area_dominance(
                objects=objects,
                dominant_side=dominant,
                ratio_threshold=ratio_threshold,
                reason_prefix=f"{view}: pair by area",
            )
        return {idx: SideDecision(side=None, needs_review=True, reason=f"{view}: unsupported headlight count") for idx, _ in objects}

    if view in {"left", "right"}:
        dominant = "left" if view == "left" else "right"
        if len(objects) == 1:
            idx, _ = objects[0]
            return {idx: SideDecision(side=dominant, needs_review=False, reason=f"{view}: single visible headlight")}
        return {idx: SideDecision(side=None, needs_review=True, reason=f"{view}: ambiguous headlight count") for idx, _ in objects}

    return {idx: SideDecision(side=None, needs_review=True, reason=f"view {view}: ambiguous for headlight") for idx, _ in objects}


def _assign_side_for_tail_light(
    objects: List[Tuple[int, GeometryInfo]],
    view: str,
    image_width: int,
    ratio_threshold: float,
) -> Dict[int, SideDecision]:
    if view == "back":
        if len(objects) == 2:
            by_x = sorted(objects, key=lambda item: item[1].center_x)
            left_idx = by_x[0][0]
            right_idx = by_x[1][0]
            return {
                left_idx: SideDecision(side="left", needs_review=False, reason="back view: left image tail-light is car left"),
                right_idx: SideDecision(side="right", needs_review=False, reason="back view: right image tail-light is car right"),
            }

        if len(objects) == 1:
            idx, geom = objects[0]
            left_zone = image_width * 0.45
            right_zone = image_width * 0.55
            if geom.center_x < left_zone:
                return {idx: SideDecision(side="left", needs_review=False, reason="back view: tail-light in left image half")}
            if geom.center_x > right_zone:
                return {idx: SideDecision(side="right", needs_review=False, reason="back view: tail-light in right image half")}
            return {
                idx: SideDecision(
                    side=None,
                    needs_review=True,
                    reason="back view: single tail-light too central to decide",
                )
            }

        return {idx: SideDecision(side=None, needs_review=True, reason="back view: unsupported tail-light count") for idx, _ in objects}

    if view in {"back-left", "back-right"}:
        dominant = "left" if view == "back-left" else "right"
        if len(objects) == 1:
            idx, _ = objects[0]
            return {idx: SideDecision(side=dominant, needs_review=False, reason=f"{view}: dominant visible side")}
        if len(objects) == 2:
            return _decisions_by_area_dominance(
                objects=objects,
                dominant_side=dominant,
                ratio_threshold=ratio_threshold,
                reason_prefix=f"{view}: pair by area",
            )
        return {idx: SideDecision(side=None, needs_review=True, reason=f"{view}: unsupported tail-light count") for idx, _ in objects}

    return {idx: SideDecision(side=None, needs_review=True, reason=f"view {view}: ambiguous for tail-light") for idx, _ in objects}


def _assign_side_for_side_dominant(
    class_name: str,
    objects: List[Tuple[int, GeometryInfo]],
    view: str,
    ratio_threshold: float,
) -> Dict[int, SideDecision]:
    if view in LEFT_VIEWS or view in RIGHT_VIEWS:
        dominant = "left" if view in LEFT_VIEWS else "right"

        if len(objects) == 1:
            idx, _ = objects[0]
            return {
                idx: SideDecision(
                    side=dominant,
                    needs_review=False,
                    reason=f"{class_name}: single object in {view} assigned to visible side",
                )
            }

        if len(objects) == 2 and view in OBLIQUE_VIEWS:
            return _decisions_by_area_dominance(
                objects=objects,
                dominant_side=dominant,
                ratio_threshold=ratio_threshold,
                reason_prefix=f"{class_name} in {view}",
            )

        return {
            idx: SideDecision(
                side=None,
                needs_review=True,
                reason=f"{class_name}: ambiguous object count ({len(objects)}) for view {view}",
            )
            for idx, _ in objects
        }

    return {
        idx: SideDecision(
            side=None,
            needs_review=True,
            reason=f"{class_name}: view {view} does not allow confident side",
        )
        for idx, _ in objects
    }


def assign_side_decisions(
    labels: List[sly.Label],
    view: Optional[str],
    image_width: int,
    ratio_threshold: float = 1.15,
) -> Dict[int, SideDecision]:
    decisions: Dict[int, SideDecision] = {}

    eligible_by_class: Dict[str, List[Tuple[int, GeometryInfo]]] = {}
    for idx, label in enumerate(labels):
        class_name = normalize_class_name(label.obj_class.name)
        if class_name not in PAIRABLE_CLASSES:
            continue

        eligible_by_class.setdefault(class_name, []).append((idx, get_geometry_info(label)))

    if view is None:
        for objects in eligible_by_class.values():
            for idx, _ in objects:
                decisions[idx] = SideDecision(side=None, needs_review=True, reason="view tag is missing")
        return decisions

    if view == "other":
        for objects in eligible_by_class.values():
            for idx, _ in objects:
                decisions[idx] = SideDecision(side=None, needs_review=True, reason="view is other")
        return decisions

    for class_name, objects in eligible_by_class.items():
        if class_name == "Headlight":
            class_decisions = _assign_side_for_headlight(
                objects=objects,
                view=view,
                image_width=image_width,
                ratio_threshold=ratio_threshold,
            )
        elif class_name == "Tail-light":
            class_decisions = _assign_side_for_tail_light(
                objects=objects,
                view=view,
                image_width=image_width,
                ratio_threshold=ratio_threshold,
            )
        else:
            class_decisions = _assign_side_for_side_dominant(
                class_name=class_name,
                objects=objects,
                view=view,
                ratio_threshold=ratio_threshold,
            )

        decisions.update(class_decisions)

    return decisions


def _replace_controlled_object_tags(
    existing_tags: sly.TagCollection,
    metas: Dict[str, sly.TagMeta],
    decision: SideDecision,
    overwrite: bool,
) -> Tuple[sly.TagCollection, bool]:
    controlled_names = set(metas.keys())
    existing_list = list(existing_tags)

    if not overwrite and any(tag.meta.name == "side" for tag in existing_list):
        return existing_tags, True

    filtered = [tag for tag in existing_list if tag.meta.name not in controlled_names]

    if decision.side is not None:
        filtered.append(sly.Tag(meta=metas["side"], value=decision.side))
    filtered.append(sly.Tag(meta=metas["side_source"], value="auto"))
    filtered.append(sly.Tag(meta=metas["needs_review"], value="yes" if decision.needs_review else "no"))
    filtered.append(sly.Tag(meta=metas["side_reason"], value=decision.reason[:2000]))

    return sly.TagCollection(filtered), False


def _format_image_summary(summary: Dict[str, Any]) -> str:
    lines = [
        f"image id: {summary['image_id']}",
        f"view source: {summary['view_source']}",
        f"used view: {summary['used_view']}",
        f"scanned labels: {summary['scanned_labels']}",
        f"eligible objects: {summary['eligible_objects']}",
        f"assigned: {summary['assigned']}",
        f"needs_review: {summary['needs_review']}",
        f"skipped existing: {summary['skipped_existing']}",
        f"skipped unsupported: {summary['skipped_unsupported']}",
        f"dry_run: {summary['dry_run']}",
    ]
    return "\n".join(lines)


def assign_side_tags_to_image(
    api: sly.Api,
    image_id: int,
    dry_run: bool,
    pair_size_ratio_threshold: float,
    view_tag_candidates: Optional[List[str]] = None,
    project_meta: Optional[sly.ProjectMeta] = None,
    side_tag_metas: Optional[Dict[str, sly.TagMeta]] = None,
) -> Dict[str, Any]:
    image_info = api.image.get_info_by_id(image_id)
    if image_info is None:
        raise ValueError(f"Image not found by id: {image_id}")

    dataset_info = api.dataset.get_info_by_id(image_info.dataset_id)
    if dataset_info is None:
        raise ValueError(f"Dataset not found by id: {image_info.dataset_id}")

    if project_meta is None or side_tag_metas is None:
        project_meta, side_tag_metas = ensure_side_tag_metas(api=api, project_id=dataset_info.project_id)

    ann_json = api.annotation.download_json(image_id)
    ann = sly.Annotation.from_json(ann_json, project_meta)

    view_candidates = view_tag_candidates or DEFAULT_VIEW_TAG_CANDIDATES
    view, used_tag_name = _find_existing_view(ann=ann, view_tag_candidates=view_candidates)
    view_source = f"existing tag ({used_tag_name})" if view is not None else "missing"

    decisions = assign_side_decisions(
        labels=list(ann.labels),
        view=view,
        image_width=int(image_info.width or 0),
        ratio_threshold=pair_size_ratio_threshold,
    )

    scanned_labels = len(ann.labels)
    eligible_objects = 0
    assigned = 0
    needs_review = 0
    skipped_existing = 0
    skipped_unsupported = 0
    changed = 0

    new_labels: List[sly.Label] = []

    for idx, label in enumerate(ann.labels):
        canonical_name = normalize_class_name(label.obj_class.name)
        if canonical_name in PAIRABLE_CLASSES:
            eligible_objects += 1
            decision = decisions.get(
                idx,
                SideDecision(side=None, needs_review=True, reason="no decision from rules"),
            )

            updated_tags, skipped = _replace_controlled_object_tags(
                existing_tags=label.tags,
                metas=side_tag_metas,
                decision=decision,
                overwrite=False,
            )

            if skipped:
                skipped_existing += 1
                new_labels.append(label)
                sly.logger.info(
                    f"image_id={image_id} obj={canonical_name} action=skip-existing-side"
                )
                continue

            if decision.side is not None:
                assigned += 1
            if decision.needs_review:
                needs_review += 1

            sly.logger.info(
                "image_id=%s obj=%s side=%s review=%s reason=%s",
                image_id,
                canonical_name,
                decision.side,
                decision.needs_review,
                decision.reason,
            )

            if updated_tags != label.tags:
                changed += 1

            new_labels.append(label.clone(tags=updated_tags))
            continue

        skipped_unsupported += 1
        new_labels.append(label)

    new_ann = ann.clone(labels=new_labels)

    if not dry_run and changed > 0:
        api.annotation.upload_ann(image_id, new_ann)

    image_summary = {
        "image_id": image_id,
        "view_source": view_source,
        "used_view": view if view is not None else "missing",
        "scanned_labels": scanned_labels,
        "eligible_objects": eligible_objects,
        "assigned": assigned,
        "needs_review": needs_review,
        "skipped_existing": skipped_existing,
        "skipped_unsupported": skipped_unsupported,
        "dry_run": dry_run,
        "changed_objects": changed,
        "summary_text": "```\n" + _format_image_summary(
            {
                "image_id": image_id,
                "view_source": view_source,
                "used_view": view if view is not None else "missing",
                "scanned_labels": scanned_labels,
                "eligible_objects": eligible_objects,
                "assigned": assigned,
                "needs_review": needs_review,
                "skipped_existing": skipped_existing,
                "skipped_unsupported": skipped_unsupported,
                "dry_run": dry_run,
            }
        ) + "\n```",
    }
    return image_summary


def assign_side_tags_to_dataset(
    dataset_id: int,
    dry_run: bool,
    pair_size_ratio_threshold: float,
    view_tag_candidates: Optional[List[str]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    api = sly.Api.from_env()

    dataset_info = api.dataset.get_info_by_id(dataset_id)
    if dataset_info is None:
        raise ValueError(f"Dataset not found by id: {dataset_id}")

    project_meta, side_tag_metas = ensure_side_tag_metas(api=api, project_id=dataset_info.project_id)
    images = api.image.get_list(dataset_id)

    started = time.monotonic()

    aggregate = {
        "dataset_id": dataset_id,
        "total_images": len(images),
        "processed_images": 0,
        "failed_images": 0,
        "scanned_labels": 0,
        "eligible_objects": 0,
        "assigned": 0,
        "needs_review": 0,
        "skipped_existing": 0,
        "skipped_unsupported": 0,
        "dry_run": dry_run,
        "image_summaries": [],
        "errors": [],
    }

    if progress_cb is not None:
        progress_cb(
            {
                "processed": 0,
                "total": len(images),
                "failed": 0,
                "assigned": 0,
                "needs_review": 0,
                "eta_seconds": 0.0,
                "avg_seconds_per_image": 0.0,
            }
        )

    for idx, image_info in enumerate(images, start=1):
        try:
            result = assign_side_tags_to_image(
                api=api,
                image_id=image_info.id,
                dry_run=dry_run,
                pair_size_ratio_threshold=pair_size_ratio_threshold,
                view_tag_candidates=view_tag_candidates,
                project_meta=project_meta,
                side_tag_metas=side_tag_metas,
            )
            aggregate["processed_images"] += 1
            aggregate["scanned_labels"] += int(result["scanned_labels"])
            aggregate["eligible_objects"] += int(result["eligible_objects"])
            aggregate["assigned"] += int(result["assigned"])
            aggregate["needs_review"] += int(result["needs_review"])
            aggregate["skipped_existing"] += int(result["skipped_existing"])
            aggregate["skipped_unsupported"] += int(result["skipped_unsupported"])
            if len(aggregate["image_summaries"]) < 20:
                aggregate["image_summaries"].append(result)
        except Exception as exc:
            aggregate["failed_images"] += 1
            sly.logger.exception("Failed to process image id=%s", image_info.id)
            if len(aggregate["errors"]) < 20:
                aggregate["errors"].append({"image_id": image_info.id, "error": str(exc)})

        processed = aggregate["processed_images"] + aggregate["failed_images"]
        elapsed = time.monotonic() - started
        avg = elapsed / processed if processed > 0 else 0.0
        eta = avg * max(0, len(images) - processed)

        if progress_cb is not None:
            progress_cb(
                {
                    "processed": processed,
                    "total": len(images),
                    "failed": aggregate["failed_images"],
                    "assigned": aggregate["assigned"],
                    "needs_review": aggregate["needs_review"],
                    "eta_seconds": eta,
                    "avg_seconds_per_image": avg,
                }
            )

        if idx % 25 == 0 or idx == len(images):
            sly.logger.info(
                "dataset=%s processed=%s/%s failed=%s assigned=%s review=%s",
                dataset_id,
                processed,
                len(images),
                aggregate["failed_images"],
                aggregate["assigned"],
                aggregate["needs_review"],
            )

    elapsed_total = time.monotonic() - started
    aggregate["elapsed_seconds"] = elapsed_total
    aggregate["avg_seconds_per_image"] = elapsed_total / len(images) if images else 0.0
    return aggregate


def assign_side_tags_run(
    image_id: Optional[int],
    dataset_id: Optional[int],
    dry_run: bool,
    pair_size_ratio_threshold: float,
    view_tag_candidates: Optional[List[str]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    if bool(image_id) == bool(dataset_id):
        raise ValueError("Provide exactly one: image_id or dataset_id")

    if dataset_id is not None:
        return {
            "mode": "dataset",
            **assign_side_tags_to_dataset(
                dataset_id=dataset_id,
                dry_run=dry_run,
                pair_size_ratio_threshold=pair_size_ratio_threshold,
                view_tag_candidates=view_tag_candidates,
                progress_cb=progress_cb,
            ),
        }

    api = sly.Api.from_env()
    image_summary = assign_side_tags_to_image(
        api=api,
        image_id=int(image_id),
        dry_run=dry_run,
        pair_size_ratio_threshold=pair_size_ratio_threshold,
        view_tag_candidates=view_tag_candidates,
    )
    return {"mode": "image", **image_summary}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assign side tags to pair car parts in Supervisely")
    parser.add_argument("--image-id", type=int, help="Supervisely image id")
    parser.add_argument("--dataset-id", type=int, help="Supervisely dataset id")
    parser.add_argument("--dry-run", action="store_true", help="Do not upload annotation updates")
    parser.add_argument("--pair-size-ratio-threshold", type=float, default=1.15)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = assign_side_tags_run(
        image_id=args.image_id,
        dataset_id=args.dataset_id,
        dry_run=bool(args.dry_run),
        pair_size_ratio_threshold=float(args.pair_size_ratio_threshold),
    )
    print(result)


if __name__ == "__main__":
    main()


