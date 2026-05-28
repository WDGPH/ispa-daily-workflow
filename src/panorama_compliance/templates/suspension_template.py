from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

from panorama_compliance.constants import DATE_FORMAT
from panorama_compliance.templates.typst_common import (
    build_typst_footer,
    build_typst_header,
    build_typst_table,
    escape_typst,
)

EMPTY_TABLE_SPACER = "#v(0.2cm)"


def _render_table_or_spacer(rows: Sequence[Sequence[str]]) -> str:
    table = build_typst_table(rows)
    return table if table else EMPTY_TABLE_SPACER


def build_suspension_typst(
    school: str,
    run_date: date,
    prev_business_day: date,
    active_rows: Sequence[Sequence[str]],
    rescind_rows: Sequence[Sequence[str]],
    logo_path: Path,
    privacy_notice_typst: str | None = None,
    summary_label: str | None = None,
    final_rescinded_date: str | None = None,
) -> str:
    header_date = summary_label or run_date.strftime(DATE_FORMAT)
    header = build_typst_header(
        school, "Student Suspension List", header_date, logo_path
    )
    active_count = len(active_rows)
    rescind_count = len(rescind_rows)
    run_date_text = escape_typst(run_date.strftime(DATE_FORMAT))
    prev_date_text = escape_typst(prev_business_day.strftime(DATE_FORMAT))
    up_to_date_text = ""
    final_mode = bool(summary_label) and active_count == 0 and rescind_count == 0
    if final_mode:
        if final_rescinded_date:
            rescind_date_text = escape_typst(final_rescinded_date)
            up_to_date_text = (
                '#text(weight: "bold")[All students are up to date.] '
                "The final suspension for this school was rescinded on "
                f'#text(weight: "bold")[{rescind_date_text}].\n'
                "#v(0.3cm)\n"
            )
        else:
            up_to_date_text = (
                '#text(weight: "bold")[All students are up to date.] '
                "There are no active suspensions and no newly rescinded suspensions.\n"
                "#v(0.3cm)\n"
            )
        active_text = f'The following #text(weight: "bold")[{active_count}] suspensions are active:'
        rescind_text = (
            f'The following #text(weight: "bold")[{rescind_count}] suspensions were '
            "newly rescinded in this reporting window:"
        )
    else:
        if active_count == 0 and rescind_count == 0:
            up_to_date_text = (
                '#text(weight: "bold")[All students are up to date.] '
                f'As of #text(weight: "bold")[{run_date_text}], there are no active '
                f"suspensions and no newly rescinded suspensions since "
                f'#text(weight: "bold")[{prev_date_text}].\n'
                "#v(0.3cm)\n"
            )
        active_text = (
            f'As of #text(weight: "bold")[{run_date_text}], the following '
            f'#text(weight: "bold")[{active_count}] suspensions are active:'
        )
        rescind_text = (
            f'The following #text(weight: "bold")[{rescind_count}] suspensions have been '
            f'rescinded since #text(weight: "bold")[{prev_date_text}]:'
        )
    active_block = active_text + "\n" + _render_table_or_spacer(active_rows)
    rescind_block = rescind_text + "\n" + _render_table_or_spacer(rescind_rows)
    return (
        header
        + up_to_date_text
        + "= Active Suspensions\n"
        + f"{active_block}\n"
        + "#v(0.3cm)\n"
        + "= Rescinded Suspensions\n"
        + f"{rescind_block}\n"
        + build_typst_footer(privacy_notice_typst)
    )
