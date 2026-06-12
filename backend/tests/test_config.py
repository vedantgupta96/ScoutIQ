from scoutiq.config import Settings


def test_cors_origins_parses_comma_separated_list():
    s = Settings(CORS_ORIGINS=" https://scoutiq.vercel.app , http://localhost:3000 ,, ")
    assert s.cors_origins == ["https://scoutiq.vercel.app", "http://localhost:3000"]


def test_cors_origins_default_is_local_dev():
    s = Settings(CORS_ORIGINS="http://localhost:3000")
    assert s.cors_origins == ["http://localhost:3000"]
