from pathlib import Path

from ethnos.precalc_benchmark import (
    load_precalculus_benchmark,
    run_precalculus_benchmark,
)


BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "precalculus_model_benchmark.json"
)


def test_precalculus_fixture_is_valid():
    benchmark = load_precalculus_benchmark(BENCHMARK_PATH)

    assert len(benchmark.items) == 18
    assert {item.category for item in benchmark.items} >= {
        "algebra",
        "functions",
        "trigonometry",
    }


def test_precalculus_benchmark_scores_structured_answers():
    benchmark = load_precalculus_benchmark(BENCHMARK_PATH)

    def fake_structured_chat(**kwargs):
        item_index = fake_structured_chat.calls
        fake_structured_chat.calls += 1
        selected = benchmark.items[item_index].answer
        return type(
            "FakeResult",
            (),
            {
                "parsed_json": {
                    "selected_option": selected,
                    "work": "Derived the result and checked it by substitution.",
                    "final_answer": selected,
                },
                "validation_status": "valid",
                "validation_error": None,
                "raw_response": "{}",
                "response_summary": {"done_reason": "stop"},
            },
        )()

    fake_structured_chat.calls = 0
    report = run_precalculus_benchmark(
        benchmark=benchmark,
        client=object(),
        model_name="test-model",
        num_predict=128,
        num_ctx=4096,
        max_questions=3,
        structured_chat=fake_structured_chat,
    )

    assert report["total"] == 3
    assert report["correct"] == 3
    assert report["invalid"] == 0


def test_precalculus_benchmark_rejects_schema_invalid_work():
    benchmark = load_precalculus_benchmark(BENCHMARK_PATH)

    def fake_structured_chat(**kwargs):
        return type(
            "FakeResult",
            (),
            {
                "parsed_json": {
                    "work": "guessed",
                    "selected_option": benchmark.items[0].answer,
                    "final_answer": benchmark.items[0].answer,
                },
                "validation_status": "valid",
                "validation_error": None,
                "raw_response": "{}",
                "response_summary": {"done_reason": "stop"},
            },
        )()

    report = run_precalculus_benchmark(
        benchmark=benchmark,
        client=object(),
        model_name="test-model",
        num_predict=128,
        num_ctx=4096,
        max_questions=1,
        structured_chat=fake_structured_chat,
    )

    assert report["correct"] == 0
    assert report["invalid"] == 1
    assert report["items"][0]["validation_status"] == "validation_error"
