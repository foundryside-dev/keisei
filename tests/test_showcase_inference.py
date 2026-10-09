"""Tests for showcase CPU-only model inference."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
import torch
import torch.nn as nn

from keisei.showcase.inference import (
    ModelCache,
    enforce_cpu_only,
    load_model_for_showcase,
    run_inference,
    run_inference_with_evaluation,
)
from keisei.training.model_registry import build_model


class TestCPUEnforcement:
    def test_enforce_cpu_only_sets_env_var(self) -> None:
        enforce_cpu_only(cpu_threads=2)
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""


class TestModelLoading:
    @pytest.fixture
    def resnet_checkpoint(self, tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
        arch = "resnet"
        params = {"hidden_size": 32, "num_layers": 2}
        model = build_model(arch, params)
        ckpt_path = tmp_path / "weights.pt"
        torch.save(model.state_dict(), ckpt_path)
        return ckpt_path, arch, params

    def test_load_model_returns_eval_mode(self, resnet_checkpoint: tuple[Path, str, dict]) -> None:
        path, arch, params = resnet_checkpoint
        model = load_model_for_showcase(path, arch, params)
        assert not model.training

    def test_load_model_all_params_on_cpu(self, resnet_checkpoint: tuple[Path, str, dict]) -> None:
        path, arch, params = resnet_checkpoint
        model = load_model_for_showcase(path, arch, params)
        for name, param in model.named_parameters():
            assert param.device == torch.device("cpu"), f"{name} on {param.device}"

    def test_load_missing_checkpoint_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_model_for_showcase(tmp_path / "nonexistent.pt", "resnet", {"hidden_size": 32, "num_layers": 2})


class TestInference:
    @pytest.fixture
    def resnet_model(self, tmp_path: Path) -> nn.Module:
        params = {"hidden_size": 32, "num_layers": 2}
        model = build_model("resnet", params)
        model.eval()
        return model

    def test_run_inference_returns_policy_and_value(self, resnet_model: nn.Module) -> None:
        obs = np.random.randn(50, 9, 9).astype(np.float32)  # KataGo observation contract
        policy_logits, win_prob = run_inference(resnet_model, obs, "resnet")
        assert isinstance(policy_logits, np.ndarray)
        assert isinstance(win_prob, float)
        assert 0.0 <= win_prob <= 1.0

    def test_run_inference_se_resnet(self, tmp_path: Path) -> None:
        params = {"channels": 32, "num_blocks": 2}
        model = build_model("se_resnet", params)
        model.eval()
        obs = np.random.randn(50, 9, 9).astype(np.float32)  # Complete KataGo features
        policy_logits, win_prob = run_inference(model, obs, "se_resnet")
        assert isinstance(policy_logits, np.ndarray)
        assert isinstance(win_prob, float)
        assert 0.0 <= win_prob <= 1.0


class TestModelCache:
    @pytest.fixture
    def cache(self) -> ModelCache:
        return ModelCache(max_size=2)

    @pytest.fixture
    def resnet_checkpoint(self, tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
        arch = "resnet"
        params = {"hidden_size": 32, "num_layers": 2}
        model = build_model(arch, params)
        ckpt_path = tmp_path / "weights.pt"
        torch.save(model.state_dict(), ckpt_path)
        return ckpt_path, arch, params

    def test_cache_hit(self, cache: ModelCache, resnet_checkpoint: tuple[Path, str, dict]) -> None:
        path, arch, params = resnet_checkpoint
        m1 = cache.get_or_load("entry-1", str(path), arch, params)
        m2 = cache.get_or_load("entry-1", str(path), arch, params)
        assert m1 is m2

    def test_cache_evicts_oldest(self, cache: ModelCache, tmp_path: Path) -> None:
        params = {"hidden_size": 32, "num_layers": 2}
        paths = []
        for i in range(3):
            model = build_model("resnet", params)
            p = tmp_path / f"weights_{i}.pt"
            torch.save(model.state_dict(), p)
            paths.append(p)

        cache.get_or_load("e1", str(paths[0]), "resnet", params)
        cache.get_or_load("e2", str(paths[1]), "resnet", params)
        cache.get_or_load("e3", str(paths[2]), "resnet", params)  # should evict e1
        assert cache.size == 2

@pytest.mark.parametrize("player", ["black", "white"])
def test_scalar_outcome_preserves_pre_move_perspective(player: str) -> None:
    model = MagicMock(return_value=(torch.zeros(1, 10), torch.tensor([[0.6]])))
    _, legacy, evaluation = run_inference_with_evaluation(
        model, np.zeros((50, 9, 9), dtype=np.float32), "resnet",
        player=player, position_ply=17,
    )
    assert legacy == pytest.approx(0.8)
    assert evaluation == {
        "version": 1, "kind": "outcome_score", "score": pytest.approx(0.8),
        "player": player, "position_ply": 17,
        "source": {"architecture": "resnet", "contract": "scalar"},
    }
    model.assert_called_once()


@pytest.mark.parametrize("wdl,score", [([0.2, 0.7, 0.1], 0.55), ([0.0, 1.0, 0.0], 0.5)])
def test_wdl_outcome_gives_draw_half_credit(wdl: list[float], score: float) -> None:
    model = MagicMock(return_value=SimpleNamespace(
        policy_logits=torch.zeros(1, 9, 9, 139),
        value_logits=torch.tensor([wdl]).log(),
    ))
    _, legacy, evaluation = run_inference_with_evaluation(
        model, np.zeros((50, 9, 9), dtype=np.float32), "se_resnet",
        player="white", position_ply=3,
    )
    assert legacy == pytest.approx(wdl[0])
    assert evaluation["score"] == pytest.approx(score)
    assert evaluation["wdl"] == dict(zip(("win", "draw", "loss"), [pytest.approx(x) for x in wdl]))
    assert evaluation["player"] == "white"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.1, -1.1])
def test_invalid_scalar_evaluation_rejected(value: float) -> None:
    model = MagicMock(return_value=(torch.zeros(1, 10), torch.tensor([[value]])))
    with pytest.raises(ValueError):
        run_inference_with_evaluation(
            model, np.zeros((50, 9, 9), dtype=np.float32), "resnet",
            player="black", position_ply=0,
        )
