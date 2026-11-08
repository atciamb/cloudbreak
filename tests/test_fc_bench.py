"""fc_bench helpers that don't need the FC: compass id decoding, accel-cal position table, output-map spec."""
import importlib.util
import math
from pathlib import Path

from cloudbreak.common.config import load_toml

spec = importlib.util.spec_from_file_location("fc_bench", Path(__file__).resolve().parents[1] / "scripts" / "fc_bench.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


def test_decode_compass_dev_id_seen_on_the_real_fc():
    # COMPASS_DEV_ID read from the CoreWing at 22:58 with the RMRC M10Q-5883 attached
    assert fb.decode_dev_id(855297) == "QMC5883L on I2C bus 0 addr 0x0d"
    assert fb.decode_dev_id(0) == "none"


def test_accel_positions_are_six_distinct_axis_directions():
    vecs = [v for _, _, v in fb.POSITIONS.values()]
    assert sorted(fb.POSITIONS) == [1, 2, 3, 4, 5, 6]
    assert len(set(vecs)) == 6 and all(math.isclose(sum(c * c for c in v), 1) for v in vecs)
    # level reads -1 g on z (FRD), as the real FC did sitting on the desk (zacc -934 mg)
    assert fb.POSITIONS[1][2] == (0, 0, -1) and fb.POSITIONS[6][2] == (0, 0, 1)
    for a, b in ((2, 3), (4, 5), (1, 6)):
        assert tuple(-c for c in fb.POSITIONS[a][2]) == fb.POSITIONS[b][2]


def test_bench_output_map_matches_config_and_governor_audit():
    outputs = {k: v for k, v in load_toml("fc_params.toml")["outputs"].items() if k.endswith("_FUNCTION")}
    want = {f"SERVO{n}_FUNCTION": f for n, f in fb.WANT_OUTPUTS.items()}
    assert outputs == want
    audit = load_toml("targets.toml")["real"]["param_audit"]
    assert all(audit[k] == [v, 0] for k, v in want.items())
