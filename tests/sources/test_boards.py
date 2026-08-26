import pytest

from app.sources.boards import board_from_careers_url, merge_boards, public_board_url


@pytest.mark.parametrize(
    ("url", "provider", "token"),
    [
        ("https://boards.greenhouse.io/acme", "greenhouse", "acme"),
        ("https://boards.greenhouse.io/acme/", "greenhouse", "acme"),
        ("https://job-boards.greenhouse.io/acme?gh_src=abc", "greenhouse", "acme"),
        ("https://boards.greenhouse.io/embed/job_board?for=acme", "greenhouse", "acme"),
        ("https://jobs.lever.co/globex", "lever", "globex"),
        ("https://jobs.lever.co/globex/abc-123", "lever", "globex"),
        ("HTTPS://JOBS.LEVER.CO/globex#team", "lever", "globex"),
    ],
)
def test_recognised_boards(url: str, provider: str, token: str) -> None:
    assert board_from_careers_url(" Acme ", url) == {
        "company": "Acme",
        "provider": provider,
        "token": token,
    }


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://acme.example/careers",
        "https://boards.greenhouse.io/",
        "https://boards.greenhouse.io/embed/job_board",
        "https://www.workatastartup.com/companies/acme",
        "https://wellfound.com/company/acme/jobs",
        "not a url",
    ],
)
def test_unrecognised_urls_derive_nothing(url: str | None) -> None:
    assert board_from_careers_url("Acme", url) is None


def test_public_board_url() -> None:
    assert public_board_url("greenhouse", "acme") == "https://boards.greenhouse.io/acme"
    assert public_board_url("lever", "globex") == "https://jobs.lever.co/globex"
    assert public_board_url("workday", "x") is None


def test_merge_boards_dedupes_and_prefers_configured() -> None:
    base = [{"company": "Acme (ops)", "provider": "greenhouse", "token": "acme"}]
    extra = [
        {"company": "Acme", "provider": "greenhouse", "token": "ACME"},
        {"company": "Globex", "provider": "lever", "token": "globex"},
        {"company": "Broken", "provider": "", "token": ""},
    ]
    merged = merge_boards(base, extra)
    assert merged == [
        {"company": "Acme (ops)", "provider": "greenhouse", "token": "acme"},
        {"company": "Globex", "provider": "lever", "token": "globex"},
    ]
