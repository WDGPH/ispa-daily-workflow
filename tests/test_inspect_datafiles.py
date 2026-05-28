from __future__ import annotations

import json

import openpyxl

from ispa_daily_workflow.commands.inspect_datafiles import (
    build_profile,
    render_markdown,
)


def test_csv_profile_does_not_emit_cell_values_by_default(tmp_path) -> None:
    source = tmp_path / "students.csv"
    source.write_text(
        "client_id,student_name,school_id,compliant\n0000000001,Alice Example,1001,\n0000000002,Blake Example,1002,2026-02-24"
        + "\n",
        encoding="utf-8",
    )

    profile = build_profile([source])
    rendered = json.dumps(profile)

    assert "Alice Example" not in rendered
    assert "Blake Example" not in rendered
    table = profile["files"][0]["tables"][0]
    assert table["rows"] == 2
    assert table["column_count"] == 4
    columns = {column["name"]: column for column in table["columns"]}
    assert columns["client_id"]["profiled_unique_count"] == 2
    assert columns["student_name"]["min_length"] == len("Alice Example")
    assert columns["student_name"]["max_length"] == len("Blake Example")


def test_xlsx_profile_counts_rows_and_columns(tmp_path) -> None:
    source = tmp_path / "pear.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Suspension"
    worksheet.append(["client_id", "school_id", "action_required"])
    worksheet.append(["0000000001", "1001", "rescind"])
    worksheet.append(["0000000002", "1002", "delete"])
    workbook.save(source)

    profile = build_profile([source])

    table = profile["files"][0]["tables"][0]
    assert table["name"] == "Suspension"
    assert table["rows"] == 2
    assert table["profiled_rows"] == 2
    assert [column["name"] for column in table["columns"]] == [
        "client_id",
        "school_id",
        "action_required",
    ]


def test_explicit_json_profile_handles_reference_records(tmp_path) -> None:
    source = tmp_path / "school_reference.json"
    source.write_text(
        json.dumps(
            [
                {
                    "school_id": "1001",
                    "school_name": "Alpha Elementary",
                    "wave": "ELEMENTARY1",
                },
                {
                    "school_id": "3001",
                    "school_name": "Beta Secondary",
                    "wave": "SECONDARY1",
                },
            ]
        ),
        encoding="utf-8",
    )

    profile = build_profile([source])

    table = profile["files"][0]["tables"][0]
    assert table["rows"] == 2
    assert [column["name"] for column in table["columns"]] == [
        "school_id",
        "school_name",
        "wave",
    ]


def test_markdown_render_has_table_shape_not_values(tmp_path) -> None:
    source = tmp_path / "students.csv"
    source.write_text(
        "client_id,student_name\n0000000001,Alice Example\n",
        encoding="utf-8",
    )
    profile = build_profile([source])

    rendered = render_markdown(profile)

    assert "| Column | Type | Nulls | Unique | Length |" in rendered
    assert "student_name" in rendered
    assert "Alice Example" not in rendered
