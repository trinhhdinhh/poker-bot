"""Deep Monte Carlo (DMC) self-play, in the style of DouZero.

Each episode is ONE hand (the server gives every player a fresh stack each hand, so hands are independent).
1. Actors play hands in engine/ with an epsilon-greedy policy over Q(state, action), recording
   (state features, action features) for every decision of every seat.
2. When the hand ends, each decision is labelled with that seat's Monte Carlo return:
   chips won minus chips put in, in big blinds.
3. The learner fits Q(state, action) to those returns with mean-squared error.
Opponents per hand: mostly the current network (self-play), plus some rule-based / calling / random
bots and older checkpoints so the policy doesn't overfit to itself.
"""
