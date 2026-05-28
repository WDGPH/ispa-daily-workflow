from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from ispa_daily_workflow.constants import DATE_FORMAT
from ispa_daily_workflow.templates.typst_common import (
    build_typst_footer,
    build_typst_header,
    build_typst_table,
    escape_typst,
)


def build_overdue_typst(
    school: str,
    run_date: date,
    rows: Sequence[Sequence[str]],
    logo_path: Path,
    privacy_notice_typst: str | None = None,
    summary_label: str | None = None,
) -> str:
    header_date = summary_label or run_date.strftime(DATE_FORMAT)
    header = build_typst_header(school, "Student Overdue List", header_date, logo_path)
    count = len(rows)
    date_text = escape_typst(run_date.strftime(DATE_FORMAT))
    if count == 0:
        if summary_label:
            body = (
                '#text(weight: "bold")[All students are up to date.] '
                "There are no overdue students requiring follow-up."
            )
        else:
            body = (
                '#text(weight: "bold")[All students are up to date.] '
                f'As of #text(weight: "bold")[{date_text}], there are no overdue '
                "students requiring follow-up."
            )
    else:
        intro = (
            f'As of #text(weight: "bold")[{date_text}], the following '
            f'#text(weight: "bold")[{count}] students remain overdue:'
        )
        body = intro + "\n" + build_typst_table(rows)
    return (
        header
        + "= Overdue Students\n"
        + body
        + "\n"
        + build_typst_footer(privacy_notice_typst)
    )
