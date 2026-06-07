from scoutiq.sources.nba import team_id_for_abbreviation


def test_team_abbreviation_aliases_map_to_nba_ids():
    assert team_id_for_abbreviation("MEM") == 1610612763
    assert team_id_for_abbreviation("ORL") == 1610612753
    assert team_id_for_abbreviation("BRK") == 1610612751
    assert team_id_for_abbreviation("PHO") == 1610612756
