from typing import Type
from textwrap import dedent
from abc import ABCMeta, abstractmethod

import numpy as np
from custom_trainer.doc_utils import add_docstring

call_docstring: str = dedent("""
    Call the scheduler for the decay of the learning rate.
    
    Args:
        base_lr: initial learning rate when epoch is 0.
        epoch: the variable of decaying curve.
    Returns:
        decayed value for the learning rate.
    """)


class Scheduler(metaclass=ABCMeta):
    """
    Base class for a scheduler compatible with the Trainer class.
    """

    @abstractmethod
    def __call__(self, base_lr: float, epoch: int) -> float:
        ...

    @abstractmethod
    def __str__(self) -> str:
        ...


class ConstantScheduler(Scheduler):
    """
    Constant learning rate.
    """

    @add_docstring(call_docstring)
    def __call__(self, base_lr: float, epoch: int) -> float:
        return base_lr

    def __str__(self) -> str:
        return 'Constant learning rate'


class ExponentialScheduler(Scheduler):
    """
    Learning rate with exponential decay.
    Args:
        exp_decay: the exponential decay parameter d for the curve f(x) = Ce^(dx).
    """

    def __init__(self, exp_decay: float = .975) -> None:
        self.exp_decay = exp_decay

    @add_docstring(call_docstring)
    def __call__(self, base_lr: float, epoch: int) -> float:
        return base_lr * self.exp_decay ** epoch

    def __str__(self) -> str:
        return f'Exponential schedule with exponential decay = {self.exp_decay}'


class CosineScheduler(Scheduler):
    """
    Learning rate with cosine decay. It remains constant after reaching the minimum value.
    The cosine function is f(x) = C0 + C(1 + cos(C2x)) specified by the following parameters.

    Args:
        decay_steps: the epochs (C2 * pi) were the schedule follows a cosine curve until its minimum C0.
        min_decay: the fraction of the initial value that it returned at the end (C0 + C) / C0.
    """

    def __init__(self, decay_steps: int = 250, min_decay: float = 0.01):
        """

        """
        self.decay_steps = decay_steps
        self.min_decay = min_decay

    @add_docstring(call_docstring)
    def __call__(self, base_lr: float, epoch: int) -> float:
        min_lr = self.min_decay * base_lr
        if epoch >= self.decay_steps:
            return min_lr
        return min_lr + (base_lr - min_lr) * ((1 + np.cos(np.pi * epoch / self.decay_steps)) / 2)

    def __str__(self) -> str:
        return f'Cosine schedule with {self.decay_steps} decay steps and {self.min_decay} min_decay factor'


def get_scheduler(scheduler_name: str) -> Type[Scheduler]:
    map_scheduler: dict[str, Type[Scheduler]] = {'Constant': ConstantScheduler,
                                                 'Exponential': ExponentialScheduler,
                                                 'Cosine': CosineScheduler}
    return map_scheduler[scheduler_name]
