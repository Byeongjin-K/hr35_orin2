"""Lock the parameter schema against the shipped YAML.

The project treats config as the single source of truth, which only holds if the
two cannot drift. A parameter added in code but missing from the YAML silently
keeps a hardcoded default; one present in YAML but never declared is ignored just
as silently. This was checked by hand once; now it is checked every run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from excavator_ar_overlay.params import SCHEMA

CONFIG = (
    Path(__file__).resolve().parents[1] / "config" / "lidar_projection_params.yaml"
)


def flatten(node, prefix=""):
    out = {}
    for key, value in node.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, name + "."))
        else:
            out[name] = value
    return out


@pytest.fixture(scope="module")
def yaml_params():
    if not CONFIG.is_file():
        pytest.fail(f"config file missing: {CONFIG}")
    doc = yaml.safe_load(CONFIG.read_text())
    assert "/**" in doc, "config must use the '/**' wildcard so any node name matches"
    return flatten(doc["/**"]["ros__parameters"])


def test_every_declared_parameter_is_in_the_config(yaml_params):
    missing = sorted({name for name, _, _ in SCHEMA} - set(yaml_params))
    assert not missing, f"declared in code but absent from the SSOT yaml: {missing}"


def test_config_has_no_undeclared_parameters(yaml_params):
    extra = sorted(set(yaml_params) - {name for name, _, _ in SCHEMA})
    assert not extra, f"present in yaml but never declared: {extra}"


def test_config_values_keep_the_declared_type(yaml_params):
    for name, default, _ in SCHEMA:
        value = yaml_params[name]
        if isinstance(default, bool):
            assert isinstance(value, bool), name
        elif isinstance(default, int):
            assert isinstance(value, int) and not isinstance(value, bool), name
        elif isinstance(default, float):
            assert isinstance(value, (int, float)) and not isinstance(
                value, bool
            ), name
        elif isinstance(default, str):
            assert isinstance(value, str), name
        elif isinstance(default, list):
            assert isinstance(value, list) and len(value) == len(default), name


def test_schema_names_are_unique():
    names = [name for name, _, _ in SCHEMA]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate declarations: {duplicates}"


def test_every_parameter_carries_a_description():
    undocumented = [name for name, _, desc in SCHEMA if not desc or len(desc) < 15]
    assert not undocumented, f"missing a useful description: {undocumented}"


def test_no_topic_name_is_empty(yaml_params):
    topics = {k: v for k, v in yaml_params.items() if k.startswith("topics.")}
    assert topics, "no topics declared"
    for name, value in topics.items():
        assert value.startswith("/"), f"{name} must be an absolute topic: {value!r}"


def test_swing_axis_row_is_declared_at_the_top_level():
    """It must keep this exact name so ai_grid_calibration.yaml loads unchanged."""
    names = {name for name, _, _ in SCHEMA}
    assert "swing_axis_row_in_gui_grid" in names


def test_publish_rate_and_size_are_sane(yaml_params):
    assert 0.1 <= yaml_params["publish.rate_hz"] <= 30.0
    assert yaml_params["publish.width"] > 0
    assert yaml_params["publish.height"] > 0
    assert 1 <= yaml_params["publish.jpeg_quality"] <= 100


def test_extrinsic_vectors_have_three_elements(yaml_params):
    assert len(yaml_params["extrinsic.xyz"]) == 3
    assert len(yaml_params["extrinsic.rpy"]) == 3


def test_lidar_colour_ramp_is_ordered(yaml_params):
    assert yaml_params["lidar.far_m"] > yaml_params["lidar.near_m"]
