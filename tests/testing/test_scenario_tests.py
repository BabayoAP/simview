"""PRD §5.13 scenario tests: ST-01 definitions and criteria, ST-02 suites + `simview test`,
ST-03 baselines and the regression gate."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import simview as sv
from simview.cli import main as cli
from simview.investigate.runs import RunData, read_info
from simview.runner.headless import load_scene
from simview.testing import (
    Criterion,
    SuiteError,
    TestScenario,
    TestSuite,
    compare_baseline,
    load_suite,
    run_suite,
)
from simview.testing.baseline import gate_passed

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCENE = FIXTURES / "pid_cart.py"
SUITE = FIXTURES / "suite.toml"
CRITERIA = [
    "must_not: cart.x > 1.05",
    "must: abs(err) < 0.02 for 0.5 s within 3 s",
    "must_not: abs(cart.v) > 3",
]


@pytest.fixture(scope="module")
def pid_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("pid") / "run.parquet"
    sv.run(load_scene(SCENE, params={"kd": 2.0}), 4.0, out=out)  # overshoots to ~1.2 m
    return RunData(read_info(out))


# -- ST-01 ------------------------------------------------------------------------------------
def test_criteria_parse_and_check_with_evidence(pid_run):
    over = Criterion("must_not: cart.x > 1.05").check(pid_run)
    assert not over.passed and over.windows and 0.3 < over.windows[0].start < 1.0
    (finding,) = over.findings(pid_run)[:1]  # RI-03: run, signals, window
    assert finding.signals == ("cart.x",) and finding.run.path == pid_run.info.path
    assert Criterion("must_not: abs(cart.v) > 30").check(pid_run).passed
    settle = Criterion("must: abs(err) < 0.02 for 0.2 s within 3.5 s").check(pid_run)
    assert settle.passed
    late = Criterion("must: abs(err) < 0.02 for 0.2 s within 0.3 s").check(pid_run)
    assert not late.passed and "never held by 0.3 s" in late.message
    assert late.windows[0].start == 0 and late.windows[0].end == pytest.approx(0.3)
    assert Criterion("must: cart.x > 1.1").check(pid_run).passed  # existence, no deadline
    missing = Criterion("must_not: nosuch.x > 0").check(pid_run)
    assert not missing.passed and missing.message == "missing signals: nosuch.x"


@pytest.mark.parametrize(
    "text, match",
    [
        ("cart.x > 1", "must start with"),
        ("must_not: cart.x > 1 within 2 s", "only goes with"),
        ("must: cart.x >", "criterion"),
        ("must: __import__('os')", "criterion"),
    ],
)
def test_bad_criteria_are_rejected(text, match):
    with pytest.raises(SuiteError, match=match):
        Criterion(text)


def test_scenario_from_toml_and_python_give_the_same_verdicts(tmp_path):
    """ST-01 acceptance: 2 parameters and 3 criteria, from TOML and from Python, pass/fail per
    criterion, failures carry evidence windows."""
    from_toml = load_suite(SUITE)
    (sc_toml,) = from_toml.scenarios
    assert len(sc_toml.params) == 2 and len(sc_toml.criteria) == 3
    assert sc_toml.scene == SCENE and isinstance(sc_toml.params["x0"], sv.Uniform)
    py = tmp_path / "suite.py"
    py.write_text(
        "import simview as sv\n"
        f"suite = sv.TestSuite('pid cart', [sv.TestScenario(\n"
        f"    name='step', scene={str(SCENE)!r}, duration=4, samples=1, seed=3,\n"
        "    metrics=['settling_time', 'overshoot'],\n"
        "    params={'x0': sv.Uniform(-0.1, 0.1), 'noise': 0.002}, grid={'kd': [6.0, 2.0]},\n"
        f"    criteria=['must_not: cart.x > 1.05', 'must: abs(err) < 0.02 for 0.5 s within 3 s',\n"
        "              sv.testing.Criterion('must_not: abs(cart.v) > 3', name='speed limit')],\n"
        ")])\n",
        encoding="utf-8",
    )
    from_py = load_suite(py)
    a = run_suite(from_toml, tmp_path / "a", workers=0)
    b = run_suite(from_py, tmp_path / "b", workers=0)
    verdicts = [[(cr.criterion.name, cr.passed) for cr in c.criteria] for c in a.cases]
    assert verdicts == [[(cr.criterion.name, cr.passed) for cr in c.criteria] for c in b.cases]
    ok, bad = a.cases
    assert ok.status == "passed" and bad.status == "failed" and bad.params["kd"] == 2.0
    (fail,) = bad.failures
    assert fail.criterion.text == "must_not: cart.x > 1.05" and fail.windows
    assert set(ok.metrics) == {"settling_time", "overshoot"}


@pytest.mark.parametrize(
    "body, match",
    [
        ('[[scenario]]\nname = "x"\nduration = 1\ncriteria = ["must: t > 0"]', "missing 'scene'"),
        (
            "[[scenario]]\nname='x'\nscene='a.py'\nduration=1\ncriteria=['must: t > 0']\nfoo=1",
            "unknown",
        ),
        ("[[scenario]]\nname='x'\nscene='a.py'\nduration=1\ncriteria=[]", "no criteria"),
        (
            "[[scenario]]\nname='x'\nscene='a.py'\nduration=1\ncriteria=['must: t > 0']\n"
            "[scenario.params]\ng = { triangle = [0, 1] }",
            "uniform / normal / choice",
        ),
        ("name = 'empty'", "no scenarios"),
        ("not toml [", "suite.toml"),
    ],
)
def test_bad_suites_name_the_problem(tmp_path, body, match):
    path = tmp_path / "suite.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(SuiteError, match=match):
        load_suite(path)


def test_initial_conditions_are_parameters(tmp_path):
    sc = TestScenario("start", SCENE, 0.2, ["must: cart.x < -0.4"], params={"x0": -0.5})
    result = run_suite(TestSuite("ic", [sc]), tmp_path, workers=0)
    assert result.passed


def test_a_scene_error_is_an_error_case(tmp_path):
    sc = TestScenario("bad", SCENE, 0.2, ["must: t > 0"], params={"nosuch": 1.0})
    (case,) = run_suite(TestSuite("err", [sc]), tmp_path, workers=0).cases
    assert case.status == "error" and "nosuch" in case.error


# -- ST-02 ------------------------------------------------------------------------------------
def _junit_cases(path):
    root = ET.parse(path).getroot()
    return {
        tc.get("name"): [f.get("message") for f in tc.findall("failure")]
        for tc in root.iter("testcase")
    }


def test_cli_planted_failure_exits_1_names_it_and_repeats(tmp_path, capsys):
    """ST-02 acceptance: exit code 1, the JUnit file names the case and criterion, the same
    command gives the same result twice (run in parallel worker processes)."""
    results = []
    for k in range(2):
        out = tmp_path / f"r{k}"
        code = cli(["test", str(SUITE), "--out", str(out), "--workers", "2", "-q"])
        assert code == 1
        cases = _junit_cases(out / "junit.xml")
        failing = {name: msgs for name, msgs in cases.items() if msgs}
        assert len(cases) == 2 and len(failing) == 1
        ((name, msgs),) = failing.items()
        assert name.startswith("step #1 (kd=2") and msgs[0].startswith("must_not: cart.x > 1.05")
        report = (out / "report.html").read_text(encoding="utf-8")
        assert "FAILED" in report and "<svg" in report and name in report
        results.append(cases)
    assert results[0] == results[1]
    assert "1 passed, 1 failed" in capsys.readouterr().out


def test_cli_passing_suite_exits_0(tmp_path):
    suite = tmp_path / "ok.toml"
    suite.write_text(
        f"name = 'ok'\n[[scenario]]\nname = 'step'\nscene = {SCENE.as_posix()!r}\n"
        "duration = 3\ncriteria = ['must_not: cart.x > 1.05']\n",
        encoding="utf-8",
    )
    assert cli(["test", str(suite), "--out", str(tmp_path / "o"), "--workers", "0", "-q"]) == 0
    assert cli(["test", str(tmp_path / "nosuch.toml")]) == 2


# -- ST-03 ------------------------------------------------------------------------------------
def _suite_file(tmp_path, name, kp):
    path = tmp_path / name
    path.write_text(
        f"name = 'gate'\n[[scenario]]\nname = 'step'\nscene = {SCENE.as_posix()!r}\n"
        "duration = 4\nsamples = 2\nmetrics = ['settling_time']\ntolerance = 0.1\n"
        "criteria = ['must_not: cart.x > 1.05']\n"
        f"[scenario.params]\nkp = {kp}\nx0 = {{ uniform = [-0.05, 0.05] }}\n",
        encoding="utf-8",
    )
    return path


def test_lower_gain_is_a_regression_unchanged_model_is_not(tmp_path, capsys):
    """ST-03 acceptance: a PID gain change that worsens settling time >10% is flagged naming
    the scenario and metric; re-running an unchanged model reports zero differences."""
    base = tmp_path / "base.json"
    same = _suite_file(tmp_path, "same.toml", 14.0)
    args = ["--workers", "0", "-q"]
    assert (
        cli(["test", str(same), "--out", str(tmp_path / "a"), "--save-baseline", str(base), *args])
        == 0
    )
    capsys.readouterr()
    assert (
        cli(["test", str(same), "--out", str(tmp_path / "b"), "--baseline", str(base), *args]) == 0
    )
    assert "baseline: no differences" in capsys.readouterr().out
    slower = _suite_file(tmp_path, "slower.toml", 10.0)
    code = cli(["test", str(slower), "--out", str(tmp_path / "c"), "--baseline", str(base), *args])
    out = capsys.readouterr().out
    assert code == 1  # every case still passes its criteria; the gate fails on the drift
    assert "regression: metric drift step#0: settling_time" in out
    assert "regression: metric drift step#1: settling_time" in out
    report = (tmp_path / "c" / "report.html").read_text(encoding="utf-8")
    assert "Against the baseline" in report and "settling_time" in report


def test_baseline_new_failures_and_newly_passing(tmp_path):
    from simview.testing.baseline import load_baseline, save_baseline

    sc = TestScenario("step", SCENE, 3.0, ["must_not: cart.x > 1.05"], grid={"kd": [6.0, 2.0]})
    before = run_suite(TestSuite("g", [sc]), tmp_path / "a", workers=0)
    base = load_baseline(save_baseline(before, tmp_path / "b.json"))
    flipped = TestScenario("step", SCENE, 3.0, ["must_not: cart.x > 1.05"], grid={"kd": [2.0, 6.0]})
    after = run_suite(TestSuite("g", [flipped]), tmp_path / "c", workers=0)
    diff = compare_baseline(after, base)
    assert diff.new_failures == [("step#0", "must_not: cart.x > 1.05")]
    assert diff.newly_passing == [("step#1", "must_not: cart.x > 1.05")]
    assert not gate_passed(after, diff)
    known = compare_baseline(before, base)  # a failure already in the baseline
    assert known.differences == 0 and gate_passed(before, known) and not gate_passed(before, None)


def test_the_hero_demo_checks_run_as_a_suite(tmp_path):
    """M12: the hero demo's checks (deliveries, EKF inside 4 sigma, on route) as a suite."""
    from simview.templates import scene_path

    suite = load_suite(scene_path("drone_delivery").parent / "checks.toml")
    (sc,) = suite.scenarios
    assert sc.scene == scene_path("drone_delivery") and len(sc.criteria) == 7
    sc.samples = 2  # the shipped suite runs 8; the first 2 samples are mild cases
    result = run_suite(suite, tmp_path, workers=2)
    assert result.passed, [(c.label, [f.message for f in c.failures]) for c in result.cases]
    for case in result.cases:
        assert 20 < case.metrics["delivery_time"] < 28 and case.metrics["max_deviation"] < 5
