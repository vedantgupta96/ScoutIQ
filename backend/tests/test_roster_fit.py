from scoutiq.model.roster_fit import (
    RoleRecord,
    build_fit_context,
    profile_roster,
    rank_candidates,
    score_candidate,
)


def _features(
    *,
    spacing: float,
    creation: float = 1.0,
    scoring: float = 10.0,
    rebounding: float = 8.0,
    defense: float = 0.5,
    gp: float = 70.0,
    min_pg: float = 28.0,
):
    return {
        "AST_PCT": creation,
        "ast_to_tov": creation,
        "ast_pg": creation,
        "USG_PCT": scoring,
        "fg3m_pg": spacing,
        "TS_PCT": spacing,
        "EFG_PCT": spacing,
        "pts_pg": scoring,
        "OBPM": scoring,
        "REB_PCT": rebounding,
        "reb_pg": rebounding,
        "OREB_PCT": rebounding,
        "DBPM": defense,
        "stock_pg": defense,
        "NET_RATING": defense,
        "DEF_RATING": -defense,
        "gp": gp,
        "min_pg": min_pg,
    }


def _league():
    records = []
    player_id = 1
    # Team 1 has a clear spacing deficit but strong rebounding.
    for _ in range(8):
        records.append(
            RoleRecord(
                player_id,
                1,
                "C",
                _features(spacing=0.2, creation=5, scoring=18, rebounding=14, defense=1),
            )
        )
        player_id += 1
    # Three balanced benchmark teams.
    for team_id in (2, 3, 4):
        for index in range(8):
            records.append(
                RoleRecord(
                    player_id,
                    team_id,
                    "G" if index < 4 else "F",
                    _features(
                        spacing=2.0 + index * 0.1,
                        creation=4.0 + index * 0.2,
                        scoring=14.0 + index,
                        rebounding=7.0 + index * 0.2,
                        defense=0.5 + index * 0.1,
                    ),
                )
            )
            player_id += 1
    shooter_id = player_id
    records.append(
        RoleRecord(shooter_id, None, "SG", _features(spacing=4.5, creation=3, rebounding=4))
    )
    rebounder_id = player_id + 1
    records.append(
        RoleRecord(rebounder_id, None, "C", _features(spacing=0.0, creation=0.5, rebounding=18))
    )
    return records, shooter_id, rebounder_id


def test_spacing_deficit_ranks_shooter_above_redundant_rebounder():
    records, shooter_id, rebounder_id = _league()
    context = build_fit_context(records)
    roster = set(range(1, 9))

    ranked = rank_candidates(context, roster, [rebounder_id, shooter_id])

    assert ranked[0].player_id == shooter_id
    assert ranked[0].fit_score > ranked[1].fit_score
    assert ranked[0].fills[0].key == "spacing"
    assert "top need" in ranked[0].reasons[0].lower()


def test_candidate_reduces_addressed_deficit_without_worsening_other_needs():
    records, shooter_id, _ = _league()
    context = build_fit_context(records)
    roster = set(range(1, 9))
    before = profile_roster(context, roster)
    after = profile_roster(context, {*roster, shooter_id})
    before_by_key = {need.key: need for need in before.needs}
    after_by_key = {need.key: need for need in after.needs}

    assert after_by_key["spacing"].deficit_pct < before_by_key["spacing"].deficit_pct
    assert all(
        after_by_key[key].deficit_pct <= need.deficit_pct
        for key, need in before_by_key.items()
    )


def test_small_feature_perturbation_keeps_directional_ranking():
    records, shooter_id, rebounder_id = _league()
    perturbed = [
        RoleRecord(
            record.player_id,
            record.team_id,
            record.position,
            {
                **record.features,
                "fg3m_pg": (record.features.get("fg3m_pg") or 0) * 1.02,
            },
        )
        for record in records
    ]

    baseline = rank_candidates(build_fit_context(records), set(range(1, 9)), [shooter_id, rebounder_id])
    changed = rank_candidates(build_fit_context(perturbed), set(range(1, 9)), [shooter_id, rebounder_id])

    assert [item.player_id for item in changed] == [item.player_id for item in baseline]


def test_missing_candidate_data_degrades_confidence_instead_of_inventing_fit():
    records, _, _ = _league()
    context = build_fit_context(records)

    result = score_candidate(context, set(range(1, 9)), 999_999)

    assert result.fit_score == 0
    assert result.confidence == "low"
    assert result.fills == []


def test_filling_small_residual_gaps_does_not_score_as_perfect_fit():
    records, shooter_id, _ = _league()
    context = build_fit_context(records)
    balanced_roster = set(range(9, 17))

    result = score_candidate(context, balanced_roster, shooter_id)

    assert sum(need.deficit_pct for need in profile_roster(context, balanced_roster).needs) < 100
    assert result.fit_score < 100
