from scoutiq.etl import load_scout_reports


def test_merge_unique_players_appends_marquee_without_duplicates():
    ranked = [(1, "Ranked One"), (201939, "Stephen Curry"), (2, "Ranked Two")]
    marquee = [(201939, "Stephen Curry"), (3, "Marquee Three")]

    assert load_scout_reports._merge_unique_players(ranked, marquee) == [
        (1, "Ranked One"),
        (201939, "Stephen Curry"),
        (2, "Ranked Two"),
        (3, "Marquee Three"),
    ]
