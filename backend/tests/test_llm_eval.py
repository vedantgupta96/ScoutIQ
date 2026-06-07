import json

from pydantic import ValidationError

from scoutiq.llm.eval_scout_ratings import main
from scoutiq.llm.player_ratings import PlayerScoutReport, aggregate_player_scout_ratings
from scoutiq.llm.schemas import ScoutRatingExtraction
from scoutiq.llm.scoring import score_extractions


def _valid_row():
    return {
        "note_id": "note-1",
        "player_name": "Avery Stone",
        "source_text": "He organized the huddle and stayed late for shooting.",
        "ratings": [
            {
                "trait": "leadership",
                "score": 4,
                "confidence": "high",
                "evidence_span": "organized the huddle",
            },
            {
                "trait": "work_ethic",
                "score": 5,
                "confidence": "medium",
                "evidence_span": "stayed late for shooting",
            },
        ],
    }


def test_schema_accepts_valid_extraction():
    extraction = ScoutRatingExtraction.model_validate(_valid_row())

    assert extraction.note_id == "note-1"
    assert extraction.ratings[0].trait.value == "leadership"
    assert extraction.ratings[1].score == 5


def test_schema_rejects_unknown_trait_out_of_range_score_missing_evidence_and_bad_confidence():
    for patch in [
        {"trait": "motor"},
        {"score": 6},
        {"evidence_span": "  "},
        {"confidence": "certain"},
    ]:
        row = _valid_row()
        row["ratings"][0] = {**row["ratings"][0], **patch}

        try:
            ScoutRatingExtraction.model_validate(row)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"expected validation failure for {patch}")


def test_schema_rejects_duplicate_traits():
    row = _valid_row()
    row["ratings"][1] = {**row["ratings"][1], "trait": "leadership"}

    try:
        ScoutRatingExtraction.model_validate(row)
    except ValidationError:
        pass
    else:
        raise AssertionError("expected duplicate trait validation failure")


def test_scoring_tracks_coverage_agreement_evidence_and_invalid_outputs():
    gold = [ScoutRatingExtraction.model_validate(_valid_row())]
    good_prediction = _valid_row()
    good_prediction["ratings"][0]["score"] = 5
    good_prediction["ratings"] = good_prediction["ratings"][:1]
    invalid_prediction = _valid_row()
    invalid_prediction["note_id"] = "bad-note"
    invalid_prediction["ratings"][0]["score"] = 9

    report = score_extractions(gold, [good_prediction, invalid_prediction]).to_dict()

    assert report["total_notes"] == 1
    assert report["expected_trait_count"] == 2
    assert report["predicted_trait_count"] == 1
    assert report["trait_coverage"] == 0.5
    assert report["exact_score_agreement"] == 0.0
    assert report["within_one_score_agreement"] == 0.5
    assert report["evidence_hit_rate"] == 1.0
    assert report["invalid_output_count"] == 1
    assert report["validation_errors"][0]["note_id"] == "bad-note"


def test_scoring_handles_missing_predictions_without_crashing():
    gold = [ScoutRatingExtraction.model_validate(_valid_row())]

    report = score_extractions(gold, []).to_dict()

    assert report["trait_coverage"] == 0.0
    assert report["exact_score_agreement"] == 0.0
    assert report["within_one_score_agreement"] == 0.0
    assert report["evidence_hit_rate"] == 0.0


def test_cli_fixture_mode_writes_stable_report(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    predictions_path = tmp_path / "predictions.jsonl"
    output_path = tmp_path / "report.json"
    row = _valid_row()
    gold_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    predictions_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    exit_code = main([
        "--gold",
        str(gold_path),
        "--predictions",
        str(predictions_path),
        "--output",
        str(output_path),
    ])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["trait_coverage"] == 1.0
    assert report["exact_score_agreement"] == 1.0
    assert report["invalid_output_count"] == 0


def test_cli_live_without_env_vars_exits_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SCOUTIQ_LLM_MODEL", raising=False)
    gold_path = tmp_path / "gold.jsonl"
    output_path = tmp_path / "report.json"
    gold_path.write_text(json.dumps(_valid_row()) + "\n", encoding="utf-8")

    exit_code = main(["--gold", str(gold_path), "--live", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "ANTHROPIC_API_KEY" in captured.out
    assert "SCOUTIQ_LLM_MODEL" in captured.out
    assert not output_path.exists()


def test_player_scout_rating_aggregation_averages_traits_and_confidence_mix():
    def player_report_row(report_id, ratings):
        row = _valid_row()
        row.pop("note_id")
        return {
            **row,
            "report_id": report_id,
            "player_id": 1,
            "source_label": "synthetic_fixture",
            "ratings": ratings,
        }

    reports = [
        PlayerScoutReport.model_validate(player_report_row("report-1", _valid_row()["ratings"])),
        PlayerScoutReport.model_validate(
            player_report_row(
                "report-2",
                [
                {
                    "trait": "leadership",
                    "score": 2,
                    "confidence": "medium",
                    "evidence_span": "organized the huddle",
                }
                ],
            )
        ),
    ]

    result = aggregate_player_scout_ratings(1, "Avery Stone", reports)

    leadership = next(r for r in result.traits if r.trait.value == "leadership")
    assert result.report_count == 2
    assert leadership.average_score == 3.0
    assert leadership.report_count == 2
    assert leadership.confidence_mix.high == 1
    assert leadership.confidence_mix.medium == 1
    assert leadership.evidence[0] == "organized the huddle"
