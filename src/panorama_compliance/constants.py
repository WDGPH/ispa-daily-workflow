from __future__ import annotations

import re


DATE_FORMAT = "%Y-%m-%d"
OUTDATED_PDF_PATTERN = re.compile(
    r"^(?:"
    r"\d{8}_.+_(?:OVERDUE|SUSPENSION|UPDATED_SUSPENSION)_LIST"
    r")\.pdf$",
    re.IGNORECASE,
)
