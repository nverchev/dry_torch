import collections
from typing import Generic, Iterable, SupportsIndex, Optional, Iterator
from typing import KeysView, ValuesView, Self, Hashable, overload
from typing import MutableSequence, TypeVar, Mapping

import numpy as np
import torch
import numpy.typing as npt
from dry_torch import exceptions
from dry_torch import protocols as p

_K = TypeVar('_K', bound=Hashable)
_V = TypeVar('_V')


class TorchAggregate:
    __slots__ = ('aggregate', 'counts')

    def __init__(self,
                 iterable: Iterable[tuple[str, torch.Tensor]] = (),
                 /,
                 **kwargs: torch.Tensor):
        self.aggregate = collections.defaultdict[str, float](float)
        self.counts = collections.defaultdict[str, int](int)
        for key, value in iterable:
            self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def __add__(self, other: Self | Mapping[str, torch.Tensor]) -> Self:
        if isinstance(other, Mapping):
            other = self.__class__(**other)
        out = self.__copy__()
        out += other
        return out

    def __iadd__(self, other: Self | Mapping[str, torch.Tensor]) -> Self:
        if isinstance(other, Mapping):
            other = self.__class__(**other)
        for key, value in other.aggregate.items():
            self.aggregate[key] += value
        for key, count in other.counts.items():
            self.counts[key] += count
        return self

    def __setitem__(self, key: str, value: torch.Tensor) -> None:
        key = self._format_key(key)
        self.aggregate[key] = self._aggregate(value)
        self.counts[key] = self._count(value)
        return

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.aggregate == other.aggregate and self.counts == other.counts

    def reduce(self) -> dict[str, float]:
        return {key: value / self.counts[key]
                for key, value in self.aggregate.items()}

    def __copy__(self) -> Self:
        copied = self.__class__()
        copied.aggregate = self.aggregate.copy()
        copied.counts = self.counts.copy()
        return copied

    @staticmethod
    def _format_key(key: str) -> str:
        return key[0].upper() + key[1:]  # Better than capitalize for acronyms

    @staticmethod
    def _count(value: torch.Tensor) -> int:
        return value.numel()

    @staticmethod
    def _aggregate(value: torch.Tensor) -> float:
        try:
            return value.sum(0).item()
        except RuntimeError:
            raise exceptions.NotBatchedError(list(value.shape))


class DictList(MutableSequence, Generic[_K, _V]):
    """
    A list-like data structure that stores dictionaries with a fixed set of
    keys.

    Args:
        iterable: An iterable of dictionaries to initialize the list with.

    Methods:
        keys(): analogue of the keys method in dictionaries.
        get(key): analogue of the get method in dictionaries.
        to_dict(key): create a dictionary of list values.

    Raises: KeysAlreadySet if the input dictionaries have keys that are not
    present in the list.

    """

    def __init__(self, iterable: Iterable[dict[_K, _V]] = zip(), /) -> None:
        self._keys: tuple[_K, ...] = ()
        self._tuple_list = list(self._validate_iterable(iterable))

    def append(self, input_dict: dict[_K, _V], /) -> None:
        """
        Standard append implementation that validates the input.
        """
        self._tuple_list.append(self._validate_dict(input_dict))

    def clear(self) -> None:
        self._tuple_list.clear()

    def copy(self) -> Self:
        cloned_self = self.__class__()
        cloned_self.set_keys(self._keys)
        cloned_self._tuple_list = self._tuple_list.copy()
        return cloned_self

    def extend(self, iterable: Iterable[dict[_K, _V]], /) -> None:
        """
        Standard extend implementation that validates the input.
        """
        if isinstance(iterable, self.__class__):
            # prevents self-alimenting extension
            if self._keys == iterable._keys:
                # more efficient implementation for the common case
                self._tuple_list.extend(iterable._tuple_list)
                return
        self._tuple_list.extend(self._validate_iterable(iterable))

    def keys(self) -> KeysView[_K]:
        """
        Usual syntax for keys in a dictionary.
        """
        # workaround to produce a KeysView object
        return {key: None for key in self._keys}.keys()

    def insert(self, index: SupportsIndex, input_dict: dict[_K, _V], /) -> None:
        """
        Standard insert implementation that validates the input.
        """
        self._tuple_list.insert(index, self._validate_dict(input_dict))

    def pop(self, index: SupportsIndex = -1, /) -> dict[_K, _V]:
        """
        Standard pop implementation that converts stored values back into
         dictionaries.
        """
        return self._item_to_dict(self._tuple_list.pop(index))

    def get(self,
            key: _K,
            /,
            default: Optional[_V] = None) -> list[_V] | list[None]:
        """
        Analogous to the get method in dictionaries.

        Args:
            key: The key for which to retrieve the values.
            default: The default value to return if the key is not present in
            the list.

        Returns:
            the values for the key in the list or a list of default values.
        """
        try:
            return [item[key] for item in self]
        except KeyError:
            if default is None:
                return [None] * len(self)
            # make sure items are not the same object
            return [default for _ in range(len(self))]

    def set_keys(self, value=Iterable[_K]) -> None:
        if self._keys:
            raise exceptions.KeysAlreadySetError(self._keys, value)
        else:
            self._keys = tuple(value)
        return

    def _validate_dict(self,
                       input_dict: dict[_K, _V],
                       /) -> tuple[_V, ...]:
        """
        Validate an input dictionary's keys.

        Args:
            input_dict: The input dictionary to validate.

        Side Effects:
            creates self.list_Keys if it does not already exist.

        Returns:
            the values from the input dictionary ordered consistently with the
             existing keys.

        Raises:
            KeysAlreadySet if the input dictionary has keys that are not
            present        in the list.

        """
        if set(self._keys) != set(input_dict.keys()):
            self.set_keys(tuple(input_dict.keys()))
            # throws a KeysAlreadySet if keys are already present.
        return tuple(input_dict[key] for key in self._keys)

    def _validate_iterable(self,
                           iterable: Iterable[dict[_K, _V]],
                           /) -> Iterable[tuple[_V, ...]]:
        """
        Validate an iterable of input dictionaries.

        Args:
            iterable: the input iterable of dictionaries to validate.

        Returns:
            an iterable with validated dictionaries.
        """
        return map(self._validate_dict, iterable)

    def _item_to_dict(self, item: tuple) -> dict[_K, _V]:
        """
        Convert a stored item back into a dictionary.

        Returns:
            the dictionary corresponding to the item.
        """
        return dict(zip(self._keys, item))

    def to_dict(self) -> dict[_K, list[_V]]:
        """
        Convert the list into a dictionary.

        Returns:
            the dictionary representation of the list.
        """
        # more efficient than self.get
        return {key: [item[index] for item in self._tuple_list]
                for index, key in enumerate(self._keys)}

    def __add__(self, other: Iterable[dict[_K, _V]], /) -> Self:
        out = self.copy()
        out.extend(other)
        return out

    def __contains__(self, item) -> bool:
        return self._keys.__contains__(item)

    def __delitem__(self, index: SupportsIndex | slice) -> None:
        """
        Standard __setitem__ implementation that validates the input.
        """
        self._tuple_list.__delitem__(index)

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, self.__class__) and
                self._keys == other._keys and
                self._tuple_list == other._tuple_list)

    @overload
    def __getitem__(self, index: SupportsIndex, /) -> dict[_K, _V]:
        ...

    @overload
    def __getitem__(self, input_slice: slice, /) -> Self:
        ...

    def __getitem__(
            self,
            index_or_slice: SupportsIndex | slice,
            /,
    ) -> dict[_K, _V] | Self:
        """
        Standard __getitem__ implementation that converts stored values back
        into dictionaries.
        """
        if isinstance(index_or_slice, slice):
            sliced = map(self._item_to_dict,
                         self._tuple_list.__getitem__(index_or_slice))
            return self.__class__(sliced)
        return self._item_to_dict(self._tuple_list.__getitem__(index_or_slice))

    def __len__(self) -> int:
        return self._tuple_list.__len__()

    def __iter__(self) -> Iterator[dict[_K, _V]]:
        self_iter = self._tuple_list.__iter__()
        for item in self_iter:
            yield self._item_to_dict(item)

    @overload
    def __setitem__(
            self,
            index_or_slice: SupportsIndex,
            value: dict[_K, _V],
            /
    ) -> None:
        ...

    @overload
    def __setitem__(
            self,
            index_or_slice: slice,
            value: Iterable[dict[_K, _V]],
            /
    ) -> None:
        ...

    def __setitem__(
            self,
            index_or_slice: SupportsIndex | slice,
            value: dict[_K, _V] | Iterable[dict[_K, _V]],
            /,
    ) -> None:
        """
        Standard __setitem__ implementation that validates the input.
        """
        if isinstance(value, dict):
            if not isinstance(index_or_slice, SupportsIndex):
                raise exceptions.MustSupportIndex(index_or_slice)

            tuple_value = self._validate_dict(value)
            self._tuple_list.__setitem__(index_or_slice, tuple_value)
        else:
            if not isinstance(index_or_slice, slice):
                raise exceptions.NotASliceError(index_or_slice)
            iterable_value = self._validate_iterable(value)
            self._tuple_list.__setitem__(index_or_slice, iterable_value)

    def __repr__(self) -> str:
        return f'DictList({self.to_dict().__repr__()}'


class NumpyDictList(DictList[str, npt.NDArray | tuple[npt.NDArray, ...]]):
    """
    Add support to a Dict List with Tensor and Tensor list values.

    Methods:
        from_batch: transforms batched Tensors into lists of Tensors
        referring to the same sample.
    """

    @classmethod
    def from_batch(cls, tensor_batch: p.OutputType) -> Self:
        """
        Instantiate the class so that each element has named tensor referring
        to the same sample.

        Args:
            tensor_batch: a batched tensor, or a list or dictionary of batched
            tensors.
        """
        instance = cls()
        TensorDict: Mapping[str, torch.Tensor | Iterable[torch.Tensor]]
        if isinstance(tensor_batch, (torch.Tensor, list, tuple)):
            tensor_dict = dict(outputs=tensor_batch)
        elif hasattr(tensor_batch, 'to_dict'):
            tensor_dict = tensor_batch.to_dict()
        else:
            raise exceptions.NoToDictMethodError(tensor_batch)
        instance.set_keys(tuple(tensor_dict.keys()))
        instance._tuple_list = cls._enlist(tensor_dict.values())
        return instance

    @classmethod
    def _enlist(
            cls,
            tensor_values: ValuesView[torch.Tensor | Iterable[torch.Tensor]],
            /,
    ) -> list[tuple[npt.NDArray | tuple[npt.NDArray, ...], ...]]:
        """
        Change the structure of batched Tensors and lists of Tensors. Args:
        tensor_iterable: an Iterable containing bathed tensors or lists of
        batched tensors.

        Return:
            a list containing a tuple of tensors and list of tensors for
             each element of the batch.
        """

        _check_tensor_have_same_length(tensor_values)
        numpy_values = map(_to_numpy, tensor_values)
        return list(zip(*map(_conditional_zip, numpy_values)))


def _to_numpy(
        elem: torch.Tensor | Iterable[torch.Tensor],
) -> npt.NDArray | Iterable[npt.NDArray]:
    if isinstance(elem, torch.Tensor):
        return _tensor_to_numpy(elem)
    else:
        return (_tensor_to_numpy(item) for item in elem)


def _tensor_to_numpy(elem: torch.Tensor) -> npt.NDArray:
    return elem.detach().cpu().numpy()


def _conditional_zip(
        elem: npt.NDArray | Iterable[npt.NDArray],
) -> npt.NDArray | Iterator[tuple[npt.NDArray, ...]]:
    return elem if isinstance(elem, np.ndarray) else zip(*elem)


def _check_tensor_have_same_length(
        tensor_values=ValuesView[p.Tensors]
) -> None:
    """
    Check that all the contained tensors have the same length and return
     its value.
    Args:
        tensor_values: an Iterable containing bathed tensors or lists of
         batched tensors.
    Raises:
       DifferentBatchSizeError if the length of the lists and of the
            sub-lists is not the same.
       NotATensorError if items are note tensors or lists of tensors.
    Returns:
        only_len: the length of all the list and sub-lists.
    """

    if not len(tensor_values):
        return

    # this set should only have at most one element
    tensor_len_set: set[int] = set()

    for value in tensor_values:
        if isinstance(value, torch.Tensor):
            tensor_len_set.add(len(value))
        elif isinstance(value, (list, tuple)):
            for elem in value:
                if isinstance(elem, torch.Tensor):
                    tensor_len_set.add(len(elem))
                else:
                    raise exceptions.NotATensorError(elem)
        else:
            raise exceptions.NotATensorError(value)

        if len(tensor_len_set) > 1:
            raise exceptions.DifferentBatchSizeError(tensor_len_set)
    return
