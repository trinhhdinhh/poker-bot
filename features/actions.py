"""Action menu and action encoding, SHARED by training and the live bot.

DMC scores Q(state, action) for each legal menu action and picks the best one.
Menu: fold, check/call, raise to 1/2 pot, raise to pot, raise to 2x pot, all-in.
- `legal_menu(obs)`: menu entries that are legal here (sizes below the min raise collapse into it).
- `encode_action(a)`: the action's input features (one-hot over the menu).
- `raise_target(obs, a)`: street-total chip target the server expects.
Opponents' off-menu sizes are kept as real pot fractions in the betting-history features.
"""
