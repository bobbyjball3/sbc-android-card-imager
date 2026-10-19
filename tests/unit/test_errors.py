import pytest

from sbc_imager.errors import (
    AssemblerError,
    CommandError,
    ConfigError,
    SafetyError,
    SbcImagerError,
    SourceError,
    VerificationError,
)


@pytest.mark.parametrize(
    ("error_type", "exit_code"),
    [
        (SbcImagerError, 1),
        (ConfigError, 2),
        (SafetyError, 2),
        (SourceError, 1),
        (AssemblerError, 1),
        (VerificationError, 1),
    ],
)
def test_error_when_raised_exposes_exit_code(
    error_type: type[SbcImagerError], exit_code: int
) -> None:
    error = error_type("something broke", "try this")

    assert error.exit_code == exit_code
    assert error.message == "something broke"
    assert error.hint == "try this"
    assert str(error) == "something broke"


def test_error_when_hint_omitted_defaults_to_none() -> None:
    error = ConfigError("bad config")

    assert error.message == "bad config"
    assert error.hint is None


def test_command_error_when_constructed_captures_process_details() -> None:
    error = CommandError(7, ["python", "-c", "raise SystemExit(7)"], "boom\n")

    assert isinstance(error, SbcImagerError)
    assert error.exit_code == 1
    assert error.returncode == 7
    assert error.command == ("python", "-c", "raise SystemExit(7)")
    assert error.stderr == "boom\n"
    assert "7" in error.message
    assert "python" in error.message


def test_command_error_when_argv_contains_credentials_redacts_them() -> None:
    error = CommandError(128, ["git", "fetch", "https://user:secret@example.com/repo.git"], "")

    assert "user:secret" not in str(error)
    assert "user:secret" not in error.message
    assert "https://example.com/repo.git" in error.message
