"""The keyword arguments an RL task takes (shared by `Scene.rl_task` and `make_env`), kept free
of Gymnasium so `import simview` doesn't need the `rl` extra."""

TASK_KEYS = frozenset(
    {
        "obs_fn",
        "reward_fn",
        "done_fn",
        "action_space",
        "observation_space",
        "act_fn",
        "rate",
        "max_time",
        "reset_fn",
        "success_fn",
    }
)

MISSING_RL = (
    "SimView's RL features need the rl extra: pip install 'simview[rl]' "
    "(Gymnasium and Stable-Baselines3)"
)
