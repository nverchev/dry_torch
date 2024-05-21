from pathlib import Path
from typing import Protocol, TypedDict, Optional, Iterator, Callable, TypeVar
from typing import runtime_checkable
import torch
from torch.nn.parameter import Parameter
from torch.utils import data
from dry_torch import data_types

_Input_co = TypeVar('_Input_co', bound=data_types.InputType, covariant=True)
_Target_co = TypeVar('_Target_co', bound=data_types.InputType, covariant=True)
_Output_co = TypeVar('_Output_co', bound=data_types.OutputType, covariant=True)

_Input_contra = TypeVar('_Input_contra',
                        bound=data_types.InputType,
                        contravariant=True)
_Target_contra = TypeVar('_Target_contra',
                         bound=data_types.TargetType,
                         contravariant=True)
_Output_contra = TypeVar('_Output_contra',
                         bound=data_types.OutputType,
                         contravariant=True)

_Input = TypeVar('_Input', bound=data_types.InputType)
_Target = TypeVar('_Target', bound=data_types.TargetType)
_Output = TypeVar('_Output', bound=data_types.OutputType)


class OptParams(TypedDict):
    params: Iterator[Parameter]
    lr: float


class LoadersProtocol(Protocol[_Input_co, _Target_co]):
    batch_size: int
    datasets_length: data_types.PartitionsLength

    def get_loader(
            self,
            partition: data_types.Split,
    ) -> data.DataLoader[tuple[_Input_co, _Target_co]]:
        ...


class SchedulerProtocol(Protocol):
    """
    Protocol of a scheduler compatible with the ModelOptimizer class.
    """

    def __call__(self, base_lr: float, epoch: int) -> float:
        ...

    def __str__(self) -> str:
        ...


class ModuleProtocol(Protocol[_Input_contra, _Output_co]):

    def forward(self,
                inputs: _Input_contra) -> _Output_co:
        ...


@runtime_checkable
class ModelOptimizerProtocol(
    Protocol[_Input_contra, _Output_co]
):
    name: str
    device: torch.device
    model: torch.nn.Module
    scheduler: SchedulerProtocol
    optimizer: torch.optim.Optimizer

    def get_base_lr(self) -> list[OptParams]:
        ...

    def update_learning_rate(
            self,
            lr: Optional[float | dict[str, float]] = None) -> None:
        ...

    def __call__(self,
                 inputs: _Input_contra) -> _Output_co:
        ...


class CheckpointPath(TypedDict):
    model: Path
    optimizer: Path


class MetricsProtocol(Protocol):
    metrics: dict[str, torch.Tensor]


class LossAndMetricsProtocol(Protocol):
    criterion: torch.Tensor
    metrics: dict[str, torch.Tensor]


class TensorCallable(Protocol[_Output_contra, _Target_contra]):

    def __call__(self,
                 outputs: _Output_contra,
                 targets: _Target_contra) -> torch.Tensor:
        ...


class MetricsCallable(Protocol[_Output_contra, _Target_contra]):

    def __call__(self,
                 outputs: _Output_contra,
                 targets: _Target_contra) -> MetricsProtocol:
        ...


class LossCallable(Protocol[_Output_contra, _Target_contra]):

    def __call__(self,
                 outputs: _Output_contra,
                 targets: _Target_contra) -> LossAndMetricsProtocol:
        ...


class TrainerProtocol(Protocol[_Input, _Target, _Output]):
    _model_optimizer: ModelOptimizerProtocol[_Input, _Output]
    _data_loaders: LoadersProtocol[_Input, _Target]
    _loss_calc: Callable[[_Output, _Target], LossAndMetricsProtocol]

    def train(self, num_epoch: int, val_after_train: bool) -> None:
        ...

    def test(self, partition: data_types.Split, save_outputs: bool) -> None:
        ...

    def _run_epoch(self,
                   partition: data_types.Split,
                   save_outputs: bool,
                   use_test_metrics: bool) -> None: ...

    def _run_batch(self,
                   inputs: _Input,
                   targets: _Target,
                   use_test_metrics: bool) -> (
            tuple[LossAndMetricsProtocol | MetricsProtocol, _Output]):
        ...

    def exec_hooks_before_epoch_training(self) -> None:
        ...

    def exec_hooks_after_epoch_training(self) -> None:
        ...
