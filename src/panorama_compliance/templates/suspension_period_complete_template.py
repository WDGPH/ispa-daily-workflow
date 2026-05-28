from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from panorama_compliance.templates.typst_common import (
    build_typst_footer,
    build_typst_header,
    escape_typst,
)


def build_suspension_period_complete_typst(
    school: str,
    run_date: date,
    suspension_window_end: date,
    logo_path: Path,
    privacy_notice_typst: str | None = None,
) -> str:
    header = build_typst_header(
        school,
        "ISPA Status Notice",
        "Suspension Period Complete",
        logo_path,
    )
    notice_date = suspension_window_end + timedelta(days=1)
    notice_date_text = escape_typst(
        f"{notice_date.strftime('%B')} {notice_date.day}, {notice_date.year}"
    )
    body = (
        f"This notice confirms that, as of {notice_date_text}, the ISPA suspension "
        "period for this school is complete. Students previously suspended under "
        "#emph[Immunization of School Pupils Act, R.S.O. 1990, c. I.1] may return "
        "to school. No further ISPA suspension notices will be issued for the "
        "current school year. "
        "Thank you for your cooperation."
    )
    return (
        header
        + "#v(2.2cm)\n"
        + "#align(center)[\n"
        + "  #block(\n"
        + "    width: 85%,\n"
        + "    inset: 14pt,\n"
        + '    stroke: 0.8pt + rgb("9AA7B0"),\n'
        + "    radius: 8pt,\n"
        + '    fill: rgb("FCFCFA"),\n'
        + "  )[\n"
        + "    #set par(justify: true)\n"
        + "    #set align(left)\n"
        + f"    {body}\n"
        + "  ]\n"
        + "]\n"
        + build_typst_footer(privacy_notice_typst)
    )
