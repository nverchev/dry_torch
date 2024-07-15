import abc
from typing import TypeVar, Hashable, Optional, Self

import torch
from dry_torch import protocols as p
from dry_torch import exceptions

_K = TypeVar('_K', bound=Hashable)
_V = TypeVar('_V')

_Output_contra = TypeVar('_Output_contra',
                         bound=p.OutputType,
                         contravariant=True)
_Target_contra = TypeVar('_Target_contra',
                         bound=p.TargetType,
                         contravariant=True)
_Target = TypeVar('_Target', bound=p.TargetType)
_Output = TypeVar('_Output', bound=p.OutputType)


class MetricsCalculatorBase(
    p.MetricsCalculatorProtocol[_Output_contra, _Target_contra],
    metaclass=abc.ABCMeta
):

    def __init__(self) -> None:
        self._metrics: Optional[dict[str, torch.Tensor]] = None

    @property
    def metrics(self: Self) -> dict[str, torch.Tensor]:
        if self._metrics is None:
            raise exceptions.AccessBeforeCalculateError()
        return self._metrics

    def reset_calculated(self) -> None:
        self._metrics = None


class MetricsCalculator(MetricsCalculatorBase[_Output_contra, _Target_contra]):

    def __init__(
            self,
            **metric_fun: p.TensorCallable[_Output_contra, _Target_contra],
    ) -> None:
        super().__init__()
        self.named_metric_fun = metric_fun

    def calculate(self,
                  outputs: _Output_contra,
                  targets: _Target_contra) -> None:
        self._metrics = {name: function(outputs, targets)
                         for name, function in self.named_metric_fun.items()}


class LossCalculatorBase(
    MetricsCalculatorBase[_Output_contra, _Target_contra],
    p.LossCalculatorProtocol[_Output_contra, _Target_contra],
    metaclass=abc.ABCMeta
):

    def __init__(self) -> None:
        super().__init__()
        self._criterion: Optional[torch.Tensor] = None

    @property
    def criterion(self) -> torch.Tensor:
        if self._criterion is None:
            raise exceptions.AccessBeforeCalculateError()
        return self._criterion

    def reset_calculated(self) -> None:
        super().reset_calculated()
        self._criterion = None


class SimpleLossCalculator(LossCalculatorBase[_Output_contra, _Target_contra]):

    def __init__(
            self,
            loss_fun: p.TensorCallable[_Output_contra, _Target_contra],
            **metric_fun: p.TensorCallable[_Output_contra, _Target_contra],
    ) -> None:
        super().__init__()
        self.loss_fun = loss_fun
        self.named_metric_fun = metric_fun

    def calculate(self,
                  outputs: _Output_contra,
                  targets: _Target_contra) -> None:
        criterion = self.loss_fun(outputs, targets)
        self._criterion = criterion
        self._metrics = {name: function(outputs, targets)
                         for name, function in self.named_metric_fun.items()}
        self._metrics.update(criterion=criterion)
        return


# TODO: Test this
class CompositeLossCalculator(
    LossCalculatorBase[_Output_contra, _Target_contra]
):

    def __init__(
            self,
            *components: tuple[
                str,
                float,
                p.TensorCallable[_Output_contra, _Target_contra]
            ],
            **metric_fun: p.TensorCallable[_Output_contra, _Target_contra],

    ) -> None:
        super().__init__()
        self.components = components
        self.named_metric_fun = metric_fun

    def calculate(self,
                  outputs: _Output_contra,
                  targets: _Target_contra) -> None:
        criterion = torch.tensor(0.)
        metrics: dict[str, torch.Tensor] = {}
        for name, weight, function in self.components:
            value = function(outputs, targets)
            if weight:
                criterion += weight * value
            metrics[name] = value
        for name, function in self.named_metric_fun.items():
            metrics[name] = function(outputs, targets)
        self._criterion = criterion
        self._metrics = dict(criterion=criterion) | metrics
        return
