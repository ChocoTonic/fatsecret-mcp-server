"""Reviewed discovery of latest versioned backend operations."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any

from fatsecret.resources import (
    ClassificationResource,
    DiaryResource,
    ExercisesResource,
    FeedbackResource,
    FoodsResource,
    MealsResource,
    NativeResource,
    ProfileFoodsResource,
    ProfileResource,
    RecipesResource,
    WeightResource,
)

from .settings import Profile

_VERSIONED = re.compile(r"^(?P<family>.+)_v(?P<version>\d+)$")
_WRITE_TERMS = frozenset(
    {"add", "copy", "create", "delete", "edit", "save", "submit", "update"}
)
_DENIED = frozenset({"profile.get_auth"})
EXECUTABLE_READS = {
    "classification.brands_get": "brands_get_v2",
    "classification.categories_get": "categories_get_v2",
    "classification.sub_categories_get": "sub_categories_get_v2",
    "diary.entries_get": "entries_get_v2",
    "diary.entries_get_month": "entries_get_month_v2",
    "exercises.entries_get": "entries_get_v2",
    "exercises.entries_get_month": "entries_get_month_v2",
    "exercises.list": "list_v2",
    "foods.autocomplete": "autocomplete_v2",
    "foods.find_id_for_barcode": "find_id_for_barcode_v2",
    "foods.get": "get_v5",
    "foods.search": "search_v5",
    "meals.get": "get_v2",
    "meals.items_get": "items_get_v2",
    "native.image_recognition": "image_recognition_v2",
    "native.natural_language_processing": "natural_language_processing_v1",
    "profile.get": "get_v1",
    "profile_foods.get_favorites": "get_favorites_v2",
    "profile_foods.get_most_eaten": "get_most_eaten_v2",
    "profile_foods.get_recently_eaten": "get_recently_eaten_v2",
    "recipes.get": "get_v2",
    "recipes.get_favorites": "get_favorites_v2",
    "recipes.search": "search_v3",
    "recipes.types_get": "types_get_v2",
    "weight.get_month": "get_month_v2",
}
_PUBLIC_READS = frozenset(
    name
    for name in EXECUTABLE_READS
    if name.startswith(("classification.", "foods.", "recipes.", "native."))
)
_DIARY_READS = frozenset(
    name
    for name in EXECUTABLE_READS
    if name.startswith(("diary.", "exercises.", "meals.", "profile_foods.", "weight."))
)


def executable_reads_for_profile(profile: Profile) -> frozenset[str]:
    if profile == "bootstrap":
        return frozenset()
    if profile == "discovery":
        return _PUBLIC_READS
    if profile == "diary":
        return _PUBLIC_READS | _DIARY_READS
    if profile == "default":
        return _PUBLIC_READS | _DIARY_READS | {"profile.get"}
    return frozenset(EXECUTABLE_READS)


RESOURCE_CLASSES = {
    "classification": ClassificationResource,
    "diary": DiaryResource,
    "exercises": ExercisesResource,
    "feedback": FeedbackResource,
    "foods": FoodsResource,
    "meals": MealsResource,
    "native": NativeResource,
    "profile_foods": ProfileFoodsResource,
    "profile": ProfileResource,
    "recipes": RecipesResource,
    "weight": WeightResource,
}


@dataclass(frozen=True)
class Capability:
    name: str
    resource: str
    method: str
    family: str
    version: int
    description: str
    mutating: bool
    executable: bool
    parameters: tuple[str, ...]


def latest_capabilities() -> dict[str, Capability]:
    """Return the highest reviewed method version for every operation family."""

    latest: dict[tuple[str, str], Capability] = {}
    for resource_name, resource_class in RESOURCE_CLASSES.items():
        for method_name, method in inspect.getmembers(
            resource_class, inspect.isfunction
        ):
            match = _VERSIONED.match(method_name)
            if match is None:
                continue
            family = match.group("family")
            version = int(match.group("version"))
            words = set(family.split("_"))
            name = f"{resource_name}.{family}"
            if name in _DENIED:
                continue
            capability = Capability(
                name=name,
                resource=resource_name,
                method=method_name,
                family=family,
                version=version,
                description=(inspect.getdoc(method) or "").split("\n", 1)[0],
                mutating=bool(words & _WRITE_TERMS),
                executable=EXECUTABLE_READS.get(name) == method_name,
                parameters=tuple(
                    name
                    for name in inspect.signature(method).parameters
                    if name != "self"
                ),
            )
            key = (resource_name, family)
            if key not in latest or latest[key].version < version:
                latest[key] = capability
    return {capability.name: capability for capability in latest.values()}


def serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, tuple):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    return value
