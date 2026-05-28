from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

DEFAULT_PRIVACY_NOTICE_TYPST = (
    "The information in this document was collected under the authority of the "
    "#emph[Health Protection and Promotion Act] in accordance with the "
    "#emph[Municipal Freedom of Information and Protection of Privacy Act] and the "
    "#emph[Personal Health Information Protection Act]. This information is used for "
    "the delivery of public health programs and services; the administration of the "
    "agency; and the maintenance of healthcare databases, registries and related "
    "research, in compliance with legal and regulatory requirements. Any questions "
    "about the management of this information should be addressed to your "
    "organization's Chief Privacy Officer."
)


def escape_typst(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\\": "\\\\",
        "#": "\\\\#",
        "[": "\\\\[",
        "]": "\\\\]",
        "*": "\\\\*",
        "_": "\\\\_",
        "@": "\\\\@",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def build_typst_table(rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    cells: list[str] = []
    for row in rows:
        cells.extend(
            [
                f"[{escape_typst(str(row[0]))}]",
                f"[{escape_typst(str(row[1]))}]",
                f"[{escape_typst(str(row[2]))}]",
            ]
        )
    body = ",\n  ".join(cells)
    return (
        "#table(\n"
        "  columns: (1fr, 1fr, 1fr),\n"
        "  stroke: 0.4pt,\n"
        "  inset: (x: 4pt, y: 3pt),\n"
        "  align: (left, left, center),\n"
        "  table.header([\n"
        '    #text(weight: "bold")[LAST NAME]\n'
        "  ], [\n"
        '    #text(weight: "bold")[FIRST NAME]\n'
        "  ], [\n"
        '    #text(weight: "bold")[DATE OF BIRTH]\n'
        "  ]),\n"
        f"  {body}\n"
        ")\n"
    )


def build_typst_header(school: str, title: str, run_date: str, logo_path: Path) -> str:
    school_text = escape_typst(school)
    title_text = escape_typst(title)
    logo_text = "/" + str(logo_path).replace("\\\\", "/").lstrip("/")
    date_text = escape_typst(run_date)
    return (
        "#set page(\n"
        '  paper: "us-letter",\n'
        "  margin: 2cm,\n"
        '  numbering: "1",\n'
        "  footer: context [\n"
        "    #align(center)[\n"
        "      Page #counter(page).display() of #counter(page).final().at(0)\n"
        "    ]\n"
        "  ]\n"
        ")\n"
        '#set text(font: "FreeSans")\n'
        f"#align(center)[{school_text}]\n"
        "#v(0.5cm)\n"
        "#grid(\n"
        "  columns: (1fr, 1fr),\n"
        "  align: (left + horizon, right + horizon),\n"
        f'  image("{logo_text}", width: 6cm),\n'
        "  [\n"
        f'    #text(size: 20pt, weight: "bold")[{title_text}] \\\n'
        f"    #text(size: 14pt)[{date_text}]\n"
        "  ]\n"
        ")\n"
        "#v(0.5cm)\n"
    )


def build_typst_footer(privacy_notice_typst: str | None = None) -> str:
    notice = (
        privacy_notice_typst.strip()
        if privacy_notice_typst
        else DEFAULT_PRIVACY_NOTICE_TYPST
    )
    lines = notice.splitlines() or [DEFAULT_PRIVACY_NOTICE_TYPST]
    notice_block = "\n".join(f"  {line}" if line else "" for line in lines)

    return (
        "#v(1fr)\n"
        "#block(breakable: false)[\n"
        "  #set par(justify: true)\n"
        "  #text(size: 9pt)[\n"
        f"{notice_block}\n"
        "  ]\n"
        "] <doc-end>\n"
    )
