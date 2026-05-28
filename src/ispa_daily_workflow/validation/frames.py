from __future__ import annotations

import polars as pl


def normalized_school_id_expr(
    *,
    column: str = "school_id",
    alias: str | None = None,
) -> pl.Expr:
    target = alias or column
    digits = (
        pl.col(column)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.replace(r"\.0$", "")
        .str.replace_all(r"\D", "")
    )
    return pl.when(digits == "").then(None).otherwise(digits).alias(target)


def filter_by_school_ids(
    frame: pl.DataFrame,
    *,
    school_ids: set[str] | list[str],
    school_id_column: str = "school_id",
) -> pl.DataFrame:
    if not school_ids:
        return frame
    if school_id_column not in frame.columns:
        return frame.head(0)

    allowed = sorted({str(value).strip() for value in school_ids if str(value).strip()})
    if not allowed:
        return frame.head(0)

    normalized_column = "_school_id_norm"
    return (
        frame.with_columns(
            normalized_school_id_expr(column=school_id_column, alias=normalized_column)
        )
        .filter(pl.col(normalized_column).is_in(allowed))
        .drop(normalized_column)
    )


def ensure_school_label_column(
    frame: pl.DataFrame,
    *,
    school_label_column: str = "school_label",
    school_name_column: str = "school_name",
    school_id_column: str = "school_id",
) -> pl.DataFrame:
    if school_label_column in frame.columns:
        return frame
    if (
        school_name_column not in frame.columns
        and school_id_column not in frame.columns
    ):
        return frame

    output = frame
    if school_name_column not in output.columns:
        output = output.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias(school_name_column)
        )
    if school_id_column not in output.columns:
        output = output.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias(school_id_column)
        )

    return output.with_columns(
        pl.when(
            pl.col(school_name_column).is_not_null()
            & pl.col(school_id_column).is_not_null()
        )
        .then(
            pl.concat_str(
                [
                    pl.col(school_name_column),
                    pl.lit(" - "),
                    pl.col(school_id_column),
                ]
            )
        )
        .when(pl.col(school_name_column).is_not_null())
        .then(pl.col(school_name_column))
        .otherwise(pl.col(school_id_column))
        .alias(school_label_column)
    )


def collect_school_labels(
    frame: pl.DataFrame,
    *,
    school_label_column: str = "school_label",
) -> list[str]:
    if school_label_column not in frame.columns:
        return []
    return (
        frame.select(
            pl.col(school_label_column)
            .cast(pl.Utf8, strict=False)
            .alias(school_label_column)
        )
        .drop_nulls()
        .unique()
        .sort(school_label_column)
        .to_series()
        .drop_nulls()
        .to_list()
    )
