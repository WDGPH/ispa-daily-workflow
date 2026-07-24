from __future__ import annotations

import shutil
from pathlib import Path

from panorama_compliance.config import (
    get_outputs_config,
    load_config,
    resolve_config_path,
    resolve_pdf_logo_path,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_copied_profile_example_resolves_committed_local_files(tmp_path: Path) -> None:
    project_root = tmp_path / "checkout"
    profile_path = project_root / "profile"
    shutil.copytree(PROJECT_ROOT / "profile.example", profile_path)
    shutil.copytree(PROJECT_ROOT / "schema", project_root / "schema")

    config, config_path = load_config(profile_path / "config.yaml", required=True)
    assert config_path is not None

    resolved_paths = {
        "reference": resolve_config_path(config["paths"]["reference"], config_path),
        "workdays": resolve_config_path(config["run"]["workdays_csv"], config_path),
        "schemas": resolve_config_path(config["validation"]["schemas"], config_path),
        "logo": resolve_pdf_logo_path(
            outputs_cfg=get_outputs_config(config),
            config_path=config_path,
            project_root=project_root,
        ),
    }

    assert all(path is not None and path.exists() for path in resolved_paths.values())
    assert resolved_paths["reference"] == profile_path / "school_reference.json"
    assert resolved_paths["workdays"] == profile_path / "workdays.csv"
    assert resolved_paths["schemas"] == project_root / "schema"
    assert resolved_paths["logo"] == profile_path / "logo.pdf"
