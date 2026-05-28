from __future__ import annotations

PDF_OUTPUT_IDS = {"sharepoint.overdue.pdf", "sharepoint.suspension.pdf"}
PANORAMA_DIFF_OUTPUT_IDS = {"sharepoint.panorama.diff.xlsx"}
PANORAMA_ONLY_OUTPUT_IDS = PANORAMA_DIFF_OUTPUT_IDS
PEAR_ONLY_OUTPUT_IDS = {"sharepoint.action_queue.xlsx"}
SOURCE_CHOICES = ("panorama", "pear")


def validate_output_source(*, output_id: str, source: str) -> str | None:
    if output_id in PANORAMA_ONLY_OUTPUT_IDS and source != "panorama":
        return f"{output_id} requires --source panorama"
    if output_id in PEAR_ONLY_OUTPUT_IDS and source != "pear":
        return f"{output_id} requires --source pear"
    return None
