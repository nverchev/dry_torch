from __future__ import annotations

import sys
import logging

from typing import Callable, Optional, Self, TypeVar, Generic, Generator, cast
import pandas as pd
import torch
from torch.cuda import amp

from dry_torch import checkpoint
from dry_torch import exceptions
from dry_torch import tracking
from dry_torch import model_utils
from dry_torch import structures
from dry_torch import recursive_ops
from dry_torch import protocols
from dry_torch import data_types
from dry_torch import default_logging
from dry_torch import loading

_Input = TypeVar('_Input', bound=data_types.InputType)
_Target = TypeVar('_Target', bound=data_types.TargetType)
_Output = TypeVar('_Output', bound=data_types.OutputType)

logger = logging.getLogger('dry_torch')


class LogMetrics(object):
    def __init__(self, model_name: str, partition: data_types.Split) -> None:

        self.model_name = model_name
        self.partition = partition

    @property
    def model_tracking(self) -> tracking.ModelTracking:
        return tracking.Experiment.current().model[self.model_name]

    def __call__(self,
                 metrics: dict[str, float]) -> None:
        log_msg_list: list[str] = ['Average %(split)s metric(s):']
        log_args: dict[str, str | float] = {
            'split': self.partition.name.lower()
        }

        partition_log: pd.DataFrame = self.model_tracking.log[self.model_name]
        for metric, value in metrics.items():
            partition_log.loc[self.model_tracking.epoch, metric] = value
            log_msg_list.append(f'%({metric})s: %({metric}_value)4e')
            log_args.update({metric: metric, f'{metric}_value': value})
        logger.log(default_logging.INFO_LEVELS.metrics,
                   '\t'.join(log_msg_list),
                   log_args)

    def log_train(self, num_epochs: int) -> Generator[None, None, None]:
        logger.log(default_logging.INFO_LEVELS.training,
                   'Training %(model_name)s.',
                   {'model_name': self.model_name})
        # if self.early_termination:
        #     logger.warning('Attempted to train module after termination.')
        for _ in range(num_epochs):
            self.model_tracking.epoch += 1
            epoch_msg = '====> Epoch %(epoch)4d:'
            logger.log(default_logging.INFO_LEVELS.epoch,
                       epoch_msg, {'epoch': self.model_tracking.epoch})
            try:
                yield
            except exceptions.ConvergenceError as ce:
                logger.error(ce)

        logger.log(default_logging.INFO_LEVELS.training, 'End of training.')


class Test(Generic[_Input, _Target, _Output]):
    partition = data_types.Split.TEST
    max_stored_output: int = sys.maxsize

    """
    Implement the standard Pytorch training and evaluation loop.

    Args:
        model: contain the module and the optimizing strategy.
        loaders: dictionary with loaders for the training, and optionally,
         the validation and test datasets.
        loss_calc: the _loss_calc function, which needs to return batched values
         as in LossAndMetricsProtocol.
        metrics_calc: the test metrics function, returning TestMetricsProtocol.
         If None, _loss_calc will be used instead.
        mixed_precision: whether to use mixed precision computing.
         Optional, default to False.

    Attributes:
        max_stored_output:
        the maximum number of outputs to store when testing.
        update_frequency:
        number of times the progress bar updates in one epoch.
        test_outputs:
            An instance of TorchDictList that stores the last test evaluation.
        save_outputs: if the flag is active store the module outputs in the
            test_outputs attribute. Default to False.

    Methods:
        train:
        run the training session,
        optionally quickly evaluate on the validation dataset.
        test: evaluate on the specified partition of the dataset.
        hook_before_training_epoch:
        property for adding a hook before running the training session.
        hook_after_training_epoch:
        property for adding a hook after running the training session.
    """

    def __init__(
            self,
            model: protocols.ModelProtocol[_Input, _Output],
            /,
            *,
            loader: protocols.LoaderProtocol[_Input, _Target],
            metrics_calc: protocols.MetricsCallable[_Output, _Target],
            save_outputs: bool = False,
    ) -> None:
        self.model = model
        self._loader = loading.TqdmLoader[_Input, _Target](loader)
        self._metrics_calc = metrics_calc
        self.save_outputs = save_outputs
        self.test_outputs = structures.TorchDictList()
        self.log_metrics = LogMetrics(self.model.name,
                                      partition=self.partition)
        return

    @torch.inference_mode()
    def __call__(self) -> None:
        """
        Evaluates the module's performance on the specified partition of the
        dataset.

        Parameters:

        """
        if self.save_outputs:
            self.test_outputs.clear()
        self.model.module.eval()
        metrics = structures.TorchAggregate()
        for batch in self._loader:
            device = self.model.device
            inputs, targets = recursive_ops.recursive_to(batch, device)
            outputs = self.model(inputs)
            if self.save_outputs:
                self.test_outputs.extend(
                    structures.TorchDictList.from_batch(outputs)
                )
            metrics += self._metrics_calc(outputs, targets)
        self.log_metrics(metrics.reduce())
        return

    def __str__(self) -> str:
        return f'Trainer for {self.model.name}.'


class Trainer(protocols.TrainerProtocol, Generic[_Input, _Target, _Output]):
    partition = data_types.Split.TRAIN
    """
    Implement the standard Pytorch training and evaluation loop.

    Args:
        model: contain the module and the optimizing strategy.
        train_loader: dictionary with loaders for the training, and optionally,
         the validation and test datasets.
        loss_calc: the _loss_calc function, which needs to return batched values
         as in LossAndMetricsProtocol.
        mixed_precision: whether to use mixed precision computing.
         Optional, default to False.

    Methods:
        train:
        run the training session,
        optionally quickly evaluate on the validation dataset.

        hook_before_training_epoch:
        property for adding a hook before running the training session.
        hook_after_training_epoch:
        property for adding a hook after running the training session.
    """

    @model_utils.bind_to_model
    def __init__(
            self,
            model: protocols.ModelProtocol[_Input, _Output],
            /,
            *,
            learning_scheme: protocols.LearningProtocol,
            loss_calc: protocols.LossCallable[_Output, _Target],
            train_loader: protocols.LoaderProtocol[_Input, _Target],
            val_loader: Optional[
                protocols.LoaderProtocol[_Input, _Target]
            ] = None,

            mixed_precision: bool = False,
    ) -> None:
        self.model = model
        self.model_optimizer = model_utils.ModelOptimizer(model,
                                                          learning_scheme)
        self._loader = loading.TqdmLoader[_Input, _Target](train_loader)
        device_is_cuda = self.model.device.type == 'cuda'
        enable_mixed_precision = mixed_precision and device_is_cuda
        self._scaler = amp.GradScaler(enabled=enable_mixed_precision)
        self._mixed_precision = mixed_precision

        self._loss_calc = loss_calc
        self._pre_epoch_hooks: list[Callable[[Self], None]] = []
        self._post_epoch_hooks: list[Callable[[Self], None]] = []

        if val_loader is None:
            self.validation_test: Callable[[], None] = lambda: None
        else:
            self.validation_test = Test(
                cast(protocols.ModelProtocol, model),
                loader=val_loader,
                metrics_calc=self._loss_calc.metrics_calc
            )
            self.validation_test.partition = data_types.Split.VAL
            self._activate_validation()

        self.early_termination = False
        self.log_metrics = LogMetrics(self.model.name,
                                      partition=self.partition)
        self.checkpoint = checkpoint.CheckpointIO(
            model,
            self.model_optimizer.optimizer,
        )
        return

    def _activate_validation(self: Self) -> None:
        def validate(instance: Self) -> None:
            instance.validate()
            return

        self._post_epoch_hooks.append(validate)
        return

    def validate(self) -> None:
        self.validation_test()
        return

    def terminate_training(self) -> None:
        self.early_termination = True
        return

    def train(self, num_epoch: int, val_after_train: bool = False) -> None:
        """
        Train the module for the specified number of epochs.

        Parameters:
            num_epoch: the number of epochs for which train the module.
            val_after_train: if the flag is active, evaluate loss function
            on the validation dataset. Default to False.
        """
        train_logger = self.log_metrics.log_train(num_epoch)
        for _ in train_logger:
            if self.early_termination:
                return
            self.model_optimizer.update_learning_rate()
            self.model.module.train()
            self.exec_pre_epoch_hooks()
            try:
                self._run_epoch()
            except exceptions.ConvergenceError as ce:
                train_logger.throw(ce)
                self.early_termination = True
            self.exec_post_epoch_hooks()

    def _run_epoch(
            self,
    ) -> dict[str, torch.Tensor]:
        self.model.module.eval()
        metrics = structures.TorchAggregate()
        for batch in self._loader:
            device = self.model.device
            inputs, targets = recursive_ops.recursive_to(batch, device)
            with torch.autocast(device_type=self.model.device.type,
                                enabled=self._mixed_precision):
                outputs = self.model(inputs)
                batched_performance = self._loss_calc(outputs, targets)
            criterion: torch.Tensor = batched_performance.criterion
            self._loader.send({'Loss': criterion.item()})
            try:
                self._scaler.scale(criterion).backward()
            except ValueError as ve:
                if torch.isinf(criterion) or torch.isnan(criterion):
                    raise exceptions.ConvergenceError(criterion.item())
                raise ve
            self._scaler.step(self.model_optimizer.optimizer)
            self._scaler.update()
            self.model_optimizer.optimizer.zero_grad()
            metrics += self._loss_calc(outputs, targets).metrics
        self.log_metrics(metrics.reduce())
        return batched_performance.metrics

    def save_checkpoint(self) -> None:
        self.checkpoint.save()

    def load_checkpoint(self, epoch=-1) -> None:
        self.checkpoint.load(epoch=epoch)

    def add_pre_epoch_hook(
            self: Self,
            hook: Callable[[Self], None]
    ) -> None:
        self._pre_epoch_hooks.append(hook)
        return

    def add_post_epoch_hook(
            self: Self,
            hook: Callable[[Self], None]
    ) -> None:
        self._post_epoch_hooks.append(hook)
        return

    def exec_pre_epoch_hooks(self: Self) -> None:
        """
        This hook is called before running the training session.
        """
        for hook in self._pre_epoch_hooks:
            hook(self)
        return

    def exec_post_epoch_hooks(self: Self) -> None:
        """
        This hook is called before running the training session.
        """
        for hook in self._post_epoch_hooks:
            hook(self)
        return

    def __str__(self) -> str:
        return f'Trainer for {self.model.name}.'
