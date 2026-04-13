import os
from typing import Any, Dict, List, Optional

import supervisely as sly
import uvicorn
from supervisely.app.widgets import Button, Card, Checkbox, Container, Field, Input, InputNumber, Text

try:
    from supervisely.app.widgets import Progress
except Exception:
    Progress = None

from main import assign_side_tags_run


image_id_input = Input(value="", placeholder="e.g. 12345")
dataset_id_input = Input(value="", placeholder="e.g. 67890 (optional)")

dry_run_checkbox = Checkbox(content="Dry run (do not upload annotation)", checked=True)

pair_ratio_input = InputNumber(min=1.0, max=5.0, step=0.05, value=1.15)

assign_button = Button("Assign side tags", button_type="primary")

status_text = Text("", status="text")
summary_text = Text("", status="text")
progress_text = Text("", status="text")
eta_text = Text("", status="text")
progress = Progress() if Progress is not None else None


result_widgets: List[Any] = [status_text, summary_text, progress_text, eta_text]
if progress is not None:
    result_widgets.append(progress)


controls = Card(
    title="Car parts side tagging",
    content=Container(
        [
            Field(content=image_id_input, title="Image ID"),
            Field(content=dataset_id_input, title="Dataset ID"),
            Field(content=pair_ratio_input, title="pair_size_ratio_threshold"),
            Field(content=dry_run_checkbox, title="dry_run"),
            assign_button,
        ]
    ),
)

results = Card(title="Status & Summary", content=Container(result_widgets))
layout = Container([controls, results])
app = sly.Application(layout=layout)


def _parse_optional_positive_int(value: Any, field_name: str) -> Optional[int]:
    text = str(value).strip()
    if text == "":
        return None

    parsed = int(text)
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return parsed


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {sec}s"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _set_progress(current: int, total: int) -> None:
    if progress is None:
        return

    try:
        if hasattr(progress, "set_total"):
            progress.set_total(total)

        if hasattr(progress, "set_current_value"):
            progress.set_current_value(current)
        elif hasattr(progress, "set_current"):
            progress.set_current(current)
        elif hasattr(progress, "update"):
            progress.update(current)
    except Exception:
        sly.logger.debug("Progress widget update skipped due to API mismatch")


def _render_image_summary(result: Dict[str, Any]) -> str:
    return (
        "```\n"
        f"image id: {result['image_id']}\n"
        f"view source: {result['view_source']}\n"
        f"used view: {result['used_view']}\n"
        f"scanned labels: {result['scanned_labels']}\n"
        f"eligible objects: {result['eligible_objects']}\n"
        f"assigned: {result['assigned']}\n"
        f"needs_review: {result['needs_review']}\n"
        f"skipped existing: {result['skipped_existing']}\n"
        f"skipped unsupported: {result['skipped_unsupported']}\n"
        f"dry_run: {result['dry_run']}\n"
        "```"
    )


def _render_dataset_summary(result: Dict[str, Any]) -> str:
    return (
        "```\n"
        f"dataset id: {result['dataset_id']}\n"
        f"images total: {result['total_images']}\n"
        f"images processed: {result['processed_images']}\n"
        f"images failed: {result['failed_images']}\n"
        f"scanned labels: {result['scanned_labels']}\n"
        f"eligible objects: {result['eligible_objects']}\n"
        f"assigned: {result['assigned']}\n"
        f"needs_review: {result['needs_review']}\n"
        f"skipped existing: {result['skipped_existing']}\n"
        f"skipped unsupported: {result['skipped_unsupported']}\n"
        f"dry_run: {result['dry_run']}\n"
        f"elapsed: {_format_duration(float(result.get('elapsed_seconds', 0.0)))}\n"
        "```"
    )


@assign_button.click
def run_assignment() -> None:
    try:
        image_id = _parse_optional_positive_int(image_id_input.get_value(), "Image ID")
        dataset_id = _parse_optional_positive_int(dataset_id_input.get_value(), "Dataset ID")
    except Exception as exc:
        status_text.set(f"Error: {exc}", status="error")
        return

    if bool(image_id) == bool(dataset_id):
        status_text.set("Error: provide exactly one field: Image ID or Dataset ID", status="error")
        return

    dry_run = bool(dry_run_checkbox.is_checked())

    pair_ratio = float(pair_ratio_input.get_value())

    status_text.set("Assigning side tags...", status="text")
    summary_text.set("", status="text")
    progress_text.set("", status="text")
    eta_text.set("", status="text")
    _set_progress(0, 1)

    def _on_progress(data: Dict[str, Any]) -> None:
        processed = int(data.get("processed", 0))
        total = int(data.get("total", 0))
        failed = int(data.get("failed", 0))
        assigned = int(data.get("assigned", 0))
        review = int(data.get("needs_review", 0))
        eta = float(data.get("eta_seconds", 0.0))
        avg = float(data.get("avg_seconds_per_image", 0.0))

        _set_progress(processed, max(total, 1))
        progress_text.set(
            f"Progress: {processed}/{total} | failed: {failed} | assigned: {assigned} | review: {review}",
            status="text",
        )
        eta_text.set(f"ETA: {_format_duration(eta)} | avg: {avg:.2f} s/img", status="text")

    try:
        result = assign_side_tags_run(
            image_id=image_id,
            dataset_id=dataset_id,
            dry_run=dry_run,
            pair_size_ratio_threshold=pair_ratio,
            progress_cb=_on_progress,
        )
    except Exception as exc:
        sly.logger.exception("Side tagging failed")
        status_text.set(f"Error: {exc}", status="error")
        return

    if result.get("mode") == "image":
        status_text.set("Done for image", status="success")
        summary_text.set(_render_image_summary(result), status="text")
        _set_progress(1, 1)
        progress_text.set("", status="text")
        eta_text.set("", status="text")
        return

    status_text.set("Done for dataset", status="success")
    summary_text.set(_render_dataset_summary(result), status="text")
    total = int(result.get("total_images", 0))
    _set_progress(total, max(total, 1))


if __name__ == "__main__":
    sly.logger.info("Starting Supervisely app: Car Parts Side Tagger")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app.get_server(), host=host, port=port, log_level="info")

