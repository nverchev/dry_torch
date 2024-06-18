import pathlib
from typing import Protocol, TypedDict, Optional, Iterator, Callable, TypeVar
from typing import Self, runtime_checkable
import torch
from torch.nn.parameter import Parameter
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


class LoaderProtocol(Protocol[_Input_co, _Target_co]):
    batch_size: int
    dataset_len: int

    def __iter__(self) -> Iterator[tuple[_Input_co, _Target_co]]:
        ...

    def __len__(self) -> int:
        ...


class SchedulerProtocol(Protocol):
    """
    Protocol of a scheduler compatible with the Network class.
    """

    def __call__(self, base_lr: float, epoch: int) -> float:
        ...


class ModuleProtocol(Protocol[_Input_contra, _Output_co]):

    def forward(self,
                inputs: _Input_contra) -> _Output_co:
        ...


class CheckpointPath(TypedDict):
    module: pathlib.Path
    optimizer: pathlib.Path


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


@runtime_checkable
class NetworkProtocol(
    Protocol[_Input_contra, _Output_co]
):
    name: str
    device: torch.device
    module: torch.nn.Module
    epoch: int
    log: data_types.LogsDict

    def __call__(self, inputs: _Input_contra) -> _Output_co:
        ...

    def clone(self, new_name: str) -> Self:
        ...


@runtime_checkable
class ModelProtocol(
    Protocol[_Input, _Target, _Output]
):
    network: NetworkProtocol[_Input, _Output]
    optimizer: torch.optim.Optimizer
    scheduler: SchedulerProtocol
    loss_calc: LossCallable[_Output, _Target]

    def get_base_lr(self) -> list[OptParams]:
        ...

    def update_learning_rate(
            self,
            lr: Optional[float | dict[str, float]] = None
    ) -> None:
        ...


class TrainerProtocol(Protocol):

    def train(self, num_epoch: int, val_after_train: bool) -> None:
        ...

    def validate(self) -> None:
        ...

    def terminate_training(self) -> None:
        ...

    def add_pre_epoch_hook(self, hook: Callable[[Self], None]) -> None:
        ...

    def add_post_epoch_hook(self, hook: Callable[[Self], None]) -> None:
        ...
