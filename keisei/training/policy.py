"""Shared legal-action distribution for collection and PPO likelihoods."""
from __future__ import annotations

import torch
from torch.distributions import Categorical


def masked_categorical(logits: torch.Tensor, legal_masks: torch.Tensor) -> Categorical:
    """Normalize float32 logits without probability-to-log epsilon clamping."""
    if logits.shape != legal_masks.shape:
        raise ValueError('Policy logits and legal masks must have identical shapes')
    if not legal_masks.any(dim=-1).all():
        raise RuntimeError('Policy contains a sample with zero legal actions')
    if not torch.isfinite(logits).all():
        raise RuntimeError('Non-finite raw policy logits')
    return Categorical(logits=logits.float().masked_fill(~legal_masks, float('-inf')), validate_args=False)
