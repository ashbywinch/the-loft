"""The trial's read options: the model under trial, its key, and the endpoint.

Both experiment runs build their reads through `trial_options`, so the two
edges are pinned here once: an absent base URL is the gateway's own (the model
config's), and a blank one is refused rather than sent to the client as a
request to the root of the internet.
"""

from __future__ import annotations

import argparse

import pytest

from pipeline.evals.eval_crop_grid import endpoint_flag, trial_options
from pipeline.model.ai_client import AIClient


def test_an_absent_base_url_is_the_gateways_own() -> None:
    options = trial_options("z-ai/glm-4.6v", None, "a-key")

    assert options.base_url == AIClient.DEFAULT_BASE_URL
    assert options.model == "z-ai/glm-4.6v"
    assert options.api_key == "a-key"


def test_a_given_base_url_is_the_endpoint() -> None:
    options = trial_options("z-ai/glm-4.6v", "http://localhost:4000/v1", None)

    assert options.base_url == "http://localhost:4000/v1"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_base_url_is_refused(blank: str) -> None:
    with pytest.raises(ValueError, match="non-blank URL"):
        trial_options("z-ai/glm-4.6v", blank, None)


@pytest.mark.parametrize("blank", ["", "   "])
def test_the_command_line_refuses_a_blank_base_url_at_the_flag(blank: str) -> None:
    """A human's blank flag never reaches the trial: argparse names the flag it
    came from, which is the provenance a programmatic error cannot give."""
    with pytest.raises(argparse.ArgumentTypeError, match="blank base URL"):
        endpoint_flag(blank)
