from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_LOCATIONS = (
    Path("profile/config.yaml"),
    Path("config.yaml"),
    Path(__file__).resolve().parents[2] / "profile" / "config.yaml",
    Path(__file__).resolve().parents[2] / "config.yaml",
)


def find_config_path(config_path: Path | None = None) -> Path | None:
    if config_path is not None:
        return config_path if config_path.exists() else None
    for candidate in DEFAULT_CONFIG_LOCATIONS:
        if candidate.exists():
            return candidate
    return None


def load_config(
    config_path: Path | None = None,
    required: bool = False,
) -> tuple[dict[str, Any], Path | None]:
    resolved = find_config_path(config_path)
    if resolved is None:
        if required:
            raise FileNotFoundError(
                "Configuration file not found. Provide --config PATH or create "
                "profile/config.yaml (recommended) or config.yaml (legacy)."
            )
        return {}, None

    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {resolved}")
    return data, resolved


def _get_dict(root: dict[str, Any], key: str) -> dict[str, Any]:
    value = root.get(key, {})
    return value if isinstance(value, dict) else {}


def require_config_mapping(
    root: dict[str, Any], key: str, *, label: str | None = None
) -> dict[str, Any]:
    value = root.get(key)
    if not isinstance(value, dict):
        raise ValueError(
            f"Missing required config mapping: {label or key}. "
            f"Add it to profile/config.yaml."
        )
    return value


def require_config_value(
    root: dict[str, Any],
    key: str,
    *,
    label: str | None = None,
    allow_empty: bool = False,
) -> Any:
    if key not in root:
        raise ValueError(
            f"Missing required config value: {label or key}. "
            f"Add it to profile/config.yaml."
        )
    value = root.get(key)
    if value is None:
        raise ValueError(
            f"Config value cannot be null: {label or key}. Update profile/config.yaml."
        )
    if isinstance(value, str):
        stripped = value.strip()
        if not allow_empty and not stripped:
            raise ValueError(
                f"Config value cannot be empty: {label or key}. "
                f"Update profile/config.yaml."
            )
        return stripped if not allow_empty else value
    return value


def get_paths_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "paths")


def get_validation_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "validation")


def get_logging_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "logging")


def get_outputs_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "outputs")


def get_alerts_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "alerts")


def get_io_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "io")


def get_run_config(config: dict[str, Any]) -> dict[str, Any]:
    return _get_dict(config, "run")


def resolve_config_bool(
    root: dict[str, Any],
    key: str,
    *,
    default: bool,
    label: str | None = None,
) -> bool:
    raw_value = root.get(key, default)
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(raw_value, (int, float)) and raw_value in (0, 1):
        return bool(raw_value)
    raise ValueError(
        f"Invalid boolean config value for {label or key}: {raw_value!r}. "
        "Expected true/false."
    )


def resolve_school_year_start_month(
    run_cfg: dict[str, Any],
    *,
    default: int = 9,
) -> int:
    raw_value = run_cfg.get("school_year_start_month", default)
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid run.school_year_start_month value; expected integer 1-12."
        ) from exc
    if value < 1 or value > 12:
        raise ValueError(
            "Invalid run.school_year_start_month value; expected integer 1-12."
        )
    return value


def resolve_config_path(
    value: str | Path | None, config_path: Path | None
) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and config_path is not None:
        path = (config_path.parent / path).resolve()
    return path


def resolve_required_path(
    value: str | Path | None, config_path: Path | None, label: str
) -> Path:
    path = resolve_config_path(value, config_path)
    if path is None:
        raise ValueError(f"Missing required config path: {label}")
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _looks_like_profile_path(path: Path, profile_root: Path | None) -> bool:
    resolved = path.resolve()
    if profile_root is not None and _is_relative_to(resolved, profile_root):
        return True
    return "profile" in resolved.parts


def _missing_file_message(
    *,
    config_key: str,
    path: Path,
    profile_root: Path | None,
) -> str:
    message = f"Configured file for {config_key} was not found: {path}"
    if _looks_like_profile_path(path, profile_root):
        message += (
            ". Path points into profile/. Copy profile.example to profile and "
            "replace the demonstration values with reviewed local data."
        )
    return message


def validate_required_runtime_files(
    *,
    reference_path: Path | None,
    require_reference: bool = True,
    workdays_path: Path | None = None,
    logo_path: Path | None = None,
    require_workdays: bool = False,
    require_logo: bool = False,
    profile_root: Path | None = None,
) -> None:
    checks = [
        ("paths.reference", reference_path, require_reference),
        ("run.workdays_csv", workdays_path, require_workdays),
        ("outputs.pdf.logo", logo_path, require_logo),
    ]
    for config_key, path, required in checks:
        if not required:
            continue
        if path is None:
            raise ValueError(f"Missing required config path: {config_key}")
        if not path.exists():
            raise FileNotFoundError(
                _missing_file_message(
                    config_key=config_key,
                    path=path,
                    profile_root=profile_root,
                )
            )
        if not path.is_file():
            raise ValueError(f"Configured path for {config_key} must be a file: {path}")


def resolve_pdf_logo_path(
    *,
    outputs_cfg: dict[str, Any],
    config_path: Path | None,
    project_root: Path,
) -> Path:
    pdf_cfg = _get_dict(outputs_cfg, "pdf")
    configured_logo = pdf_cfg.get("logo")
    if configured_logo is not None:
        resolved = resolve_config_path(configured_logo, config_path)
        if resolved is not None:
            return resolved

    return project_root / "profile" / "logo.pdf"


def resolve_profile_privacy_notice_path(
    *,
    config_path: Path | None,
    project_root: Path,
) -> Path:
    if config_path is not None:
        direct = (config_path.parent / "privacy_notice.typ").resolve()
        if direct.exists():
            return direct

        nested = (config_path.parent / "profile" / "privacy_notice.typ").resolve()
        if nested.exists():
            return nested

    return project_root / "profile" / "privacy_notice.typ"
