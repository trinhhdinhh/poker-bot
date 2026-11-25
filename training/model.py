"""Q-network: MLP over concat(state features, action features) -> expected return in big blinds.

Shared by training and bot/policy.py. Saved to results/checkpoints/ with ENCODING_VERSION so the bot
refuses a model trained on a different feature layout.
"""

import torch.nn as nn

class QNetwork(nn.Module):
    def __init__(self, state_dim, num_actions, hidden_dim=256):
        super().__init__()
        self.input_layer = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU()
        )
        self.res_block = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim)
        )
        self.relu = nn.ReLU()
        self.head = nn.Linear(hidden_dim, num_actions)

    def forward(self, x):
        h = self.input_layer(x)
        h = self.relu(h + self.res_block(h))
        return self.head(h)
    
