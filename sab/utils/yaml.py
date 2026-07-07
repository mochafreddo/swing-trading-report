from __future__ import annotations

from typing import Any

_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


def unique_key_safe_loader(yaml_module: Any, error_cls: type[Exception]) -> type[Any]:
    def construct_mapping_key_for_duplicate_check(
        loader: Any, key_node: Any, deep: bool
    ) -> Any:
        if getattr(key_node, "tag", None) == _YAML_MERGE_TAG:
            return "<<"
        return loader.construct_object(key_node, deep=deep)

    def reject_duplicate_mapping_keys(loader: Any, node: Any, deep: bool) -> None:
        seen_keys: set[Any] = set()
        for key_node, _value_node in node.value:
            key = construct_mapping_key_for_duplicate_check(loader, key_node, deep)
            try:
                hash(key)
            except TypeError as exc:
                raise error_cls(f"unhashable YAML key {key!r}") from exc
            if key in seen_keys:
                raise error_cls(f"duplicate YAML key {key!r}")
            seen_keys.add(key)

    def construct_mapping_without_duplicate_keys(
        loader: Any, node: Any, deep: bool = False
    ) -> dict[Any, Any]:
        reject_duplicate_mapping_keys(loader, node, deep)
        loader.flatten_mapping(node)
        reject_duplicate_mapping_keys(loader, node, deep)

        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            value = loader.construct_object(value_node, deep=deep)
            try:
                mapping[key] = value
            except TypeError as exc:
                raise error_cls(f"unhashable YAML key {key!r}") from exc

        return mapping

    class UniqueKeySafeLoader(yaml_module.SafeLoader):
        pass

    UniqueKeySafeLoader.add_constructor(
        yaml_module.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping_without_duplicate_keys,
    )
    return UniqueKeySafeLoader
