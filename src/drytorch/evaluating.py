"""Module containing classes for the evaluation of a model."""

import copy
import sys
from typing import Any, Iterator, Mapping, TypeVar
import warnings
from typing_extensions import override

import torch

from drytorch import exceptions
from drytorch import loading
from drytorch import log_events
from drytorch import metrics
from drytorch import protocols as p
from drytorch import registering
from drytorch.utils import apply_ops
from drytorch.utils import repr_utils

_Input = TypeVar('_Input', bound=p.InputType)
_Target = TypeVar('_Target', bound=p.TargetType)
_Output = TypeVar('_Output', bound=p.OutputType)


class Source(repr_utils.Versioned):
    """
    Class that documents itself when the model is first called.

    Attributes:
        model: the model containing the weights to evaluate.
    """

    def __init__(self, model: p.ModelProtocol):
        """
        Args:
            model: the model containing the weights to evaluate.
        """
        super().__init__()
        self.model = model
        self._registered = False
        return

    def __call__(self) -> None:
        """Record call."""
        if not self._registered:
            registering.record_model_call(self, self.model)

        self._registered = True
        return


class Evaluation(Source, p.EvaluationProtocol[_Input, _Target, _Output]):
    """
    Class for evaluating a model on a given dataset.

    It coordinates the batching from a loader with the processing of the
    model output. Subclasses need to implement the __call__ method for training,
    validating or testing the model.

    Attributes:
        model: the model containing the weights to evaluate.
        loader: provides inputs and targets in batches.
        objective: processes the model outputs and targets.
        mixed_precision: whether to use mixed precision computing.
        outputs_list: list of optionally stored outputs
    """
    max_stored_output: int = sys.maxsize
    _name = repr_utils.DefaultName()

    def __init__(
            self,
            model: p.ModelProtocol[_Input, _Output],
            /,
            *,
            loader: p.LoaderProtocol[tuple[_Input, _Target]],
            metric: p.MetricCalculatorProtocol[_Output, _Target],
            name: str = '',
            mixed_precision: bool = False,
    ) -> None:
        """
        Args:
            model: the model containing the weights to evaluate.
            loader: provides inputs and targets in batches.
            metric: processes the model outputs and targets.
            name: the name for the object for logging purposes.
                Defaults to class name plus eventual counter.
            mixed_precision: whether to use mixed precision computing.
                Defaults to False.
        """
        super().__init__(model)
        self.model = model
        self._name = name
        self.loader = loader
        self.objective = copy.deepcopy(metric)
        self.objective.reset()
        self.mixed_precision = mixed_precision
        self.outputs_list = list[_Output]()
        return

    def __repr__(self) -> str:
        return str(self.name) + f' for model {self.model.name}'

    @property
    def name(self) -> str:
        """The name of the model."""
        return self._name

    def _get_batches(self) -> Iterator[tuple[_Input, _Target]]:
        """
        Get the batches ready for use.

        Returns:
            Batches of data on the same device as the model.
        """
        return (apply_ops.apply_to(batch, self.model.device)
                for batch in self.loader)

    def _run_backwards(self, outputs: _Output, targets: _Target) -> None:
        self.objective.update(outputs, targets)

    def _run_batch(self, batch: tuple[_Input, _Target], ) -> _Output:
        inputs, targets = batch
        outputs = self._run_forward(inputs)
        self._run_backwards(outputs, targets)
        return outputs

    def _run_epoch(self, store_outputs: bool):
        self.outputs_list.clear()
        self.objective.reset()
        num_samples = loading.check_dataset_length(self.loader.dataset)
        pbar = log_events.IterateBatch(self.name,
                                       self.loader.batch_size,
                                       len(self.loader),
                                       num_samples)
        for batch in self._get_batches():
            outputs = self._run_batch(batch)
            pbar.update(metrics.repr_metrics(self.objective))
            if store_outputs:
                self._store(outputs)

        self._log_metrics(metrics.repr_metrics(self.objective))

    def _run_forward(self, inputs: _Input) -> _Output:
        with torch.autocast(device_type=self.model.device.type,
                            enabled=self.mixed_precision):
            return self.model(inputs)

    def _log_metrics(self, computed_metrics: Mapping[str, Any]) -> None:
        log_events.Metrics(model_name=self.model.name,
                           source_name=self.name,
                           epoch=self.model.epoch,
                           metrics=computed_metrics)
        return

    def _store(self, outputs: _Output) -> None:
        try:
            outputs = apply_ops.apply_cpu_detach(outputs)
        except (exceptions.FuncNotApplicableError,
                exceptions.NamedTupleOnlyError) as err:
            warnings.warn(exceptions.CannotStoreOutputWarning(err))
        else:
            self.outputs_list.append(outputs)


class Diagnostic(Evaluation[_Input, _Target, _Output]):
    """
    Evaluate model on inference mode.

    It could be used for testing or validating a model (see subclasses) but
    also for diagnosing a problem in its training.

    Attributes:
        model: the model containing the weights to evaluate.
        loader: provides inputs and targets in batches.
        objective: processes the model outputs and targets.
        mixed_precision: whether to use mixed precision computing.
        outputs_list: list of optionally stored outputs
    """

    @override
    @torch.inference_mode()
    def __call__(self, store_outputs: bool = False) -> None:
        """
        Run epoch without tracking gradients and in eval mode.

        Args:
            store_outputs: whether to store model outputs. Defaults to False
        """
        super().__call__()
        self.model.module.eval()
        self._run_epoch(store_outputs)
        return


class Validation(Diagnostic[_Input, _Target, _Output]):
    """
    Evaluate model performance on a validation dataset.

    Attributes:
        model: the model containing the weights to evaluate.
        loader: provides inputs and targets in batches.
        objective: processes the model outputs and targets.
        mixed_precision: whether to use mixed precision computing.
        outputs_list: list of optionally stored outputs.
    """


class Test(Diagnostic[_Input, _Target, _Output]):
    """
    Evaluate model performance on a test dataset.

    Attributes:
        model: the model containing the weights to evaluate.
        loader: provides inputs and targets in batches.
        objective: processes the model outputs and targets.
        mixed_precision: whether to use mixed precision computing.
        outputs_list: list of optionally stored outputs.
    """

    @override
    def __call__(self, store_outputs: bool = False) -> None:
        """
        Test the model on the dataset.

        Args:
            store_outputs: whether to store model outputs. Defaults to False
        """
        log_events.StartTest(self.name, self.model.name)
        super().__call__(store_outputs)
        log_events.EndTest(self.name, self.model.name)
        return
