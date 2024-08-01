"""This module contains functions for nested containers."""
import copy
from typing import Callable, Type, TypeVar, MutableMapping, MutableSequence, Any

import torch

from dry_torch import exceptions

_T = TypeVar('_T')
_C = TypeVar('_C')


def recursive_apply(obj: _C,
                    expected_type: Type[_T],
                    func: Callable[[_T], _T]) -> _C:
    """
    Function that looks for an expected type and applies a given function.

    The implementation is similar to default_convert in
    github.com/pytorch/pytorch/blob/main/torch/utils/data/_utils/collate.py.
    It makes a copy of a MutableMapping or MutableSequence container and
    modifies the elements of the expected type using the functions or act
    recursively on other containers. In case the obj is a namedtuple, the
    function uses the class constructor to create a new instance with the
    modified elements. Note that when applied after default_convert, the only
    objects of type tuple are namedtuple classes.

    Args:
        obj: a container containing the expected objects and other containers.
        expected_type: the type of the objects to modify.
        func: a function that modifies objects of the expected type.

    Returns:
        The modified object or a copy of obj containing the modified objects.

    Raises:
        FuncNotApplicableError: if the object is of an unexpected type.
        NamedTupleOnlyError: if the tuple object is not a namedtuple.
    """
    if isinstance(obj, expected_type):
        return func(obj)  # type: ignore

    if isinstance(obj, MutableMapping):
        mapping = copy.copy(obj)
        mapping.update(
            **{key: recursive_apply(item, expected_type, func)
               for key, item in obj.items()}
        )
        return mapping  # type: ignore

    if isinstance(obj, MutableSequence):
        sequence = copy.copy(obj)
        for i, value in enumerate(obj):
            sequence[i] = recursive_apply(value, expected_type, func)
        return sequence  # type: ignore
    try:
        if isinstance(obj, tuple):
            new = (recursive_apply(item, expected_type, func) for item in obj)
            if obj.__class__ == tuple:
                return tuple(list(new))  # type: ignore
            try:
                return obj.__class__(*new)  # type: ignore
            except TypeError:
                raise exceptions.NamedTupleOnlyError(obj.__class__.__name__)

    except (TypeError, ValueError):
        raise exceptions.FuncNotApplicableError(func.__name__,
                                                obj.__class__.__name__)

    raise exceptions.FuncNotApplicableError(func.__name__,
                                            obj.__class__.__name__)


def recursive_to(obj: _C, device: torch.device) -> _C:
    """
    Function that changes the device of tensors inside a container.

    Args:
        obj: container with other containers and tensors.
        device: the target device.

    Returns:
        the same container with the tensor on the target device.
    """

    def to_device(tensor: torch.Tensor) -> torch.Tensor:
        return tensor.to(device)

    return recursive_apply(obj,
                           expected_type=torch.Tensor,
                           func=to_device)


def recursive_cpu_detach(obj: _C) -> _C:
    """
    Function that detaches and stores in cpu the tensors inside a container.

    Args:
         obj: container or class containing other containers and tensors.

    Returns:
        the same obj with the tensor on cpu.
    """

    def cpu_detach(tensor: torch.Tensor) -> torch.Tensor:
        return tensor.detach().cpu()

    dict_attr: dict[str, Any] = {}
    if hasattr(obj, '__dict__'):
        dict_attr.update(obj.__dict__)

    if hasattr(obj, '__slots__'):
        dict_attr.update({k: getattr(obj, k) for k in obj.__slots__})

    if dict_attr:
        obj_copy = copy.copy(obj)
        for key, value in dict_attr.items():
            setattr(obj_copy,
                    key,
                    recursive_apply(value,
                                    expected_type=torch.Tensor,
                                    func=cpu_detach)
                    )
        return obj_copy
    else:
        return recursive_apply(obj,
                               expected_type=torch.Tensor,
                               func=cpu_detach)
