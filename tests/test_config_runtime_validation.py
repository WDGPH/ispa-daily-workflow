from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from ispa_daily_workflow.config import (
    resolve_pdf_logo_path,
    resolve_profile_privacy_notice_path,
    resolve_school_year_start_month,
    validate_required_runtime_files,
)


class TestRuntimeValidation(unittest.TestCase):
    def test_missing_profile_path_includes_profile_setup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_root = root / "profile"
            missing_workdays = profile_root / "workdays.csv"
            with self.assertRaisesRegex(
                FileNotFoundError,
                "Copy profile.example to profile",
            ):
                validate_required_runtime_files(
                    reference_path=None,
                    require_reference=False,
                    workdays_path=missing_workdays,
                    require_workdays=True,
                    profile_root=profile_root,
                )

    def test_missing_non_profile_path_omits_profile_setup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_workdays = root / "custom" / "workdays.csv"
            with self.assertRaises(FileNotFoundError) as context:
                validate_required_runtime_files(
                    reference_path=None,
                    require_reference=False,
                    workdays_path=missing_workdays,
                    require_workdays=True,
                    profile_root=root / "profile",
                )
            self.assertNotIn("Copy profile.example to profile", str(context.exception))

    def test_existing_required_files_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference_path = root / "school_reference.json"
            workdays_path = root / "workdays.csv"
            logo_path = root / "logo.pdf"
            reference_path.write_text("[]", encoding="utf-8")
            workdays_path.write_text(
                "Date,Holiday,Business Day,Previous Business Day\n"
                "2026-01-02,,TRUE,2025-12-31\n",
                encoding="utf-8",
            )
            logo_path.write_text("%PDF-1.4\n", encoding="utf-8")

            validate_required_runtime_files(
                reference_path=reference_path,
                workdays_path=workdays_path,
                logo_path=logo_path,
                require_workdays=True,
                require_logo=True,
                profile_root=root / "profile",
            )

    def test_reference_optional_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workdays_path = root / "workdays.csv"
            workdays_path.write_text(
                "Date,Holiday,Business Day,Previous Business Day\n"
                "2026-01-05,,TRUE,2026-01-02\n",
                encoding="utf-8",
            )

            validate_required_runtime_files(
                reference_path=None,
                require_reference=False,
                workdays_path=workdays_path,
                require_workdays=True,
                profile_root=root / "profile",
            )

    def test_resolve_pdf_logo_uses_configured_logo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "profile" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}", encoding="utf-8")
            configured_logo = root / "profile" / "custom" / "logo.pdf"
            configured_logo.parent.mkdir(parents=True, exist_ok=True)
            configured_logo.write_text("%PDF-1.4\n", encoding="utf-8")

            resolved = resolve_pdf_logo_path(
                outputs_cfg={"pdf": {"logo": "custom/logo.pdf"}},
                config_path=config_path,
                project_root=root,
            )
            self.assertEqual(resolved, configured_logo)

    def test_resolve_pdf_logo_falls_back_to_profile_logo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "profile" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}", encoding="utf-8")

            fallback_logo = root / "profile" / "logo.pdf"
            fallback_logo.parent.mkdir(parents=True, exist_ok=True)
            fallback_logo.write_text("%PDF-1.4\n", encoding="utf-8")

            resolved = resolve_pdf_logo_path(
                outputs_cfg={},
                config_path=config_path,
                project_root=root,
            )
            self.assertEqual(resolved, fallback_logo)

    def test_resolve_privacy_notice_prefers_config_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "profile" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}", encoding="utf-8")

            sibling_notice = config_path.parent / "privacy_notice.typ"
            sibling_notice.write_text("notice", encoding="utf-8")

            resolved = resolve_profile_privacy_notice_path(
                config_path=config_path,
                project_root=root,
            )
            self.assertEqual(resolved, sibling_notice)

    def test_resolve_privacy_notice_falls_back_to_project_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")

            fallback_notice = root / "profile" / "privacy_notice.typ"
            fallback_notice.parent.mkdir(parents=True, exist_ok=True)
            fallback_notice.write_text("notice", encoding="utf-8")

            resolved = resolve_profile_privacy_notice_path(
                config_path=config_path,
                project_root=root,
            )
            self.assertEqual(resolved, fallback_notice)

    def test_resolve_school_year_start_month_default(self) -> None:
        self.assertEqual(resolve_school_year_start_month({}), 9)

    def test_resolve_school_year_start_month_from_config(self) -> None:
        self.assertEqual(
            resolve_school_year_start_month({"school_year_start_month": "7"}),
            7,
        )

    def test_resolve_school_year_start_month_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "run.school_year_start_month"):
            resolve_school_year_start_month({"school_year_start_month": 0})


if __name__ == "__main__":
    unittest.main()
