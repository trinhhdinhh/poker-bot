"""Q-network: MLP over concat(state features, action features) -> expected return in big blinds.

Shared by training and bot/policy.py. Saved to results/checkpoints/ with ENCODING_VERSION so the bot
refuses a model trained on a different feature layout.
"""
