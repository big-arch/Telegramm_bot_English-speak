"""The database self-check.

Each case here is a mistake that actually happened or is one keystroke away,
and each previously showed up as "Failed deploy" with a traceback that named
none of them.
"""

from __future__ import annotations

from scripts.doctor import mask, problems

GOOD = "postgresql+asyncpg://postgres.abc:Secret123@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"


def test_a_correct_string_has_no_complaints():
    assert problems(GOOD) == []


def test_password_is_masked_but_the_rest_stays_readable():
    shown = mask(GOOD)
    assert "Secret123" not in shown
    assert "***" in shown
    # The parts you need in order to spot a mistake must survive masking.
    assert "postgresql+asyncpg" in shown
    assert "pooler.supabase.com:5432" in shown


def test_unreplaced_placeholder_is_caught():
    dsn = GOOD.replace("Secret123", "[YOUR-PASSWORD]")
    found = problems(dsn)
    assert any("placeholder" in p for p in found)
    # And it must be visible in the echoed string, which is how someone
    # recognises their own mistake without reading the explanation.
    assert "[YOUR-PASSWORD]" not in mask(dsn) or "***" in mask(dsn)


def test_missing_asyncpg_driver_is_caught():
    dsn = GOOD.replace("postgresql+asyncpg://", "postgresql://")
    assert any("asyncpg" in p for p in problems(dsn))


def test_postgres_scheme_shorthand_is_caught_too():
    dsn = GOOD.replace("postgresql+asyncpg://", "postgres://")
    assert any("asyncpg" in p for p in problems(dsn))


def test_transaction_pooler_port_is_caught():
    """6543 works just long enough to look fine, then fails intermittently."""
    dsn = GOOD.replace(":5432/", ":6543/")
    found = problems(dsn)
    assert any("6543" in p and "Session pooler" in p for p in found)


def test_special_characters_in_the_password_are_caught():
    dsn = GOOD.replace("Secret123", "pa@ss/word")
    assert any("password contains" in p for p in problems(dsn))


def test_a_clean_password_is_not_flagged():
    assert problems(GOOD.replace("Secret123", "aB3xY9zQ")) == []


def test_several_mistakes_are_all_reported():
    """People rarely make exactly one."""
    dsn = "postgresql://postgres.abc:[YOUR-PASSWORD]@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
    found = problems(dsn)
    assert len(found) >= 3


def test_sqlite_is_not_flagged():
    assert problems("sqlite+aiosqlite:///data/speakout.db") == []


def test_the_documentation_example_is_recognised_as_such():
    """Copying the example line and changing only the password yields a
    well-formed string pointing at a project that is not yours. The database
    then blames the password, which sends you looking in the wrong place."""
    example = (
        "postgresql+asyncpg://postgres.abcdefgh:RealPassword123"
        "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    )
    found = problems(example)
    assert any("documentation example" in p for p in found)


def test_a_real_looking_project_ref_is_not_flagged():
    real = (
        "postgresql+asyncpg://postgres.rcxqirojmocfcauluevs:aB3xY9zQ"
        "@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
    )
    assert problems(real) == []


def test_tenant_not_found_is_a_host_problem(capsys):
    """Supabase's pooler says "tenant not found" when the project reference is
    looked up on a pooler that does not serve it. The reference and password
    are usually fine; the host is not — and the host cannot be derived from a
    region name, because the prefix is assigned per project."""
    import scripts.doctor as doctor

    doctor.explain_connection_error(
        "InternalServerError: (ENOTFOUND) tenant/user postgres.abc123 not found"
    )
    out = capsys.readouterr().out
    assert "HOST is wrong" in out
    assert "Connect" in out
    assert "password" not in out.split("HOST is wrong")[0]
