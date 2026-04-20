# Модель для представлення набору доказів у відповіді EDM версії 2.0
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Дозволені значення classificationNode.
# За потреби можна розширити без зміни логіки моделі.
ALLOWED_CLASSIFICATION_NODES = [
    "MainEvidence",
    "HumanReadableVersion",
    "Translation",
    "Annex",
]


def _generate_cid() -> str:
    """Генерує унікальний CID для XOP/EDMResponse."""
    return f"cid:{uuid.uuid4()}@gov.ua"


def _generate_identifier() -> str:
    """Генерує унікальний ідентифікатор для доказу/набору доказів."""
    return f"urn:uuid:{uuid.uuid4()}"


@dataclass
class Description:
    """Опис набору доказів (наприклад, для UI)."""
    lang: str
    value: str


@dataclass
class Classification:
    classificationNode: str
    classificationScheme: str = 'urn:fdc:oots:classification:edm'
    id: str = field(default_factory=_generate_identifier)

    def __post_init__(self):
        if self.classificationNode not in ALLOWED_CLASSIFICATION_NODES:
            allowed = ", ".join(ALLOWED_CLASSIFICATION_NODES)
            raise ValueError(
                f"Некоректне classificationNode: {self.classificationNode}. "
                f"Дозволені значення: {allowed}"
            )


@dataclass
class RepositoryItemRef:
    title: str
    href: str = field(default_factory=_generate_cid)


@dataclass
class ExtrinsicObjectType:
    """
    Документ доказу
    - основний структурований доказ
    - PDF вадображення цього доказу
    - Переклад
    - додатки
    - то що
    """
    classification: Classification
    EvidenceMetadata: str
    RepositoryItemRef: RepositoryItemRef
    content_type: Optional[str] = None
    content: Optional[Any] = None
    encoding: Optional[str] = None
    id: str = field(default_factory=_generate_identifier)


@dataclass
class RegistryPackageType:
    """
    Логічний доказ.

    Містить кілька представлень (ExtrinsicObjectType) одного й того ж доказу
    у різних форматах, але з єдиними метаданими.
    """
    RegistryPackage: list[ExtrinsicObjectType]
    id: str = field(default_factory=_generate_identifier)
    permit: bool = False


@dataclass
class Evidences:
    """
    Набір доказів у відповіді EDM.

    Верхньорівневий контейнер, який містить:
    - Набір логічних доказів (RegistryPackageType)
    - Опис та превью
    - Унікальний ідентифікатор відповіді
    """
    title: str
    PreviewDescription: list[Description]
    preview: bool
    evidences: list[RegistryPackageType]


async def save_evidences_to_redis(redis_client, key: str, evidences: Evidences) -> None:
    """
    Зберігає Evidences модель до Redis як JSON.

    Args:
        redis_client: Екземпляр UseRedisAsync
        key: Ключ Redis для зберігання
        evidences: Об'єкт Evidences для збереження

    Raises:
        TypeError: Якщо evidences не є Evidences об'єктом
        Exception: Якщо помилка при збереженні до Redis
    """
    if not isinstance(evidences, Evidences):
        raise TypeError(f"Очікувався Evidences, отримано {type(evidences).__name__}")

    # Конвертуємо dataclass у dict для JSON-серіалізації
    evidences_dict = asdict(evidences)

    # Зберігаємо через чинний метод UseRedisAsync
    await redis_client.save_to_redis(key, evidences_dict)


async def get_evidences_from_redis(redis_client, key: str) -> Evidences | None:
    """
    Отримує Evidences модель з Redis і десеріалізує її.

    Args:
        redis_client: Екземпляр UseRedisAsync
        key: Ключ Redis для отримання

    Returns:
        Об'єкт Evidences або None, якщо ключ не знайдено або дані невалідні
    """
    # Отримуємо дані з Redis через чинний метод
    data = await redis_client.get_from_redis(key)

    if data is None:
        return None

    try:
        # Конвертуємо dict назад у модель Evidences
        evidences = _dict_to_evidences(data)
        return evidences
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"Не вдалось десеріалізувати Evidences з Redis: {e}")


def to_legacy_evidences_dict(evidences: Evidences) -> dict:
    """
    Конвертує нову модель Evidences у legacy-структуру словника.

    Формат повернення:
    {
        "title": str,
        "PreviewDescription": [{"UA": "..."}, {"EN": "..."}],
        "preview": bool,
        "exaption": "",
        "evidences": [
            {
                "cid": str,
                "content_type": str,
                "content": Any,
                "permit": bool,
                "metadata": str,
            }
        ]
    }
    """
    if not isinstance(evidences, Evidences):
        raise TypeError(f"Очікувався Evidences, отримано {type(evidences).__name__}")

    preview_description = [{d.lang: d.value} for d in evidences.PreviewDescription]

    legacy_items = []
    for package in evidences.evidences:
        for obj in package.RegistryPackage:
            if obj.classification.classificationNode != "MainEvidence":
                continue

            legacy_items.append(
                {
                    "cid": obj.RepositoryItemRef.href,
                    "content_type": obj.content_type,
                    "content": obj.content,
                    "permit": package.permit,
                    "metadata": obj.EvidenceMetadata,
                }
            )

    return {
        "title": evidences.title,
        "PreviewDescription": preview_description,
        "preview": evidences.preview,
        "exaption": "",
        "evidences": legacy_items,
    }


async def get_legacy_evidences_from_redis(redis_client, key: str) -> dict | None:
    """
    Зчитує з Redis нову або стару структуру і повертає legacy-словник.
    """
    data = await redis_client.get_from_redis(key)
    if data is None:
        return None

    if _is_legacy_evidences_dict(data):
        return _normalize_legacy_evidences_dict(data)

    evidences = _dict_to_evidences(data)
    return to_legacy_evidences_dict(evidences)


def _is_legacy_evidences_dict(data: Any) -> bool:
    """Перевіряє, чи схоже значення на legacy-структуру доказів."""
    if not isinstance(data, dict):
        return False
    if "evidences" not in data or not isinstance(data.get("evidences"), list):
        return False
    items = data.get("evidences", [])
    if not items:
        # Порожній список дозволений і в legacy, і в новому форматі;
        # орієнтуємось на наявність legacy-поля.
        return "exaption" in data
    first = items[0]
    return isinstance(first, dict) and "RegistryPackage" not in first


def _normalize_legacy_evidences_dict(data: dict) -> dict:
    """Нормалізує legacy-структуру до стабільного словника для сумісності."""
    return {
        "title": data.get("title", ""),
        "PreviewDescription": data.get("PreviewDescription", []),
        "preview": data.get("preview", True),
        "exaption": data.get("exaption", ""),
        "evidences": data.get("evidences", []),
    }


def _dict_to_evidences(data: dict) -> Evidences:
    """
    Внутрішня функція для конвертування dict у модель Evidences.

    Args:
        data: Словник з даними Evidences

    Returns:
        Об'єкт Evidences

    Raises:
        KeyError: Якщо відсутні обов'язкові поля
        TypeError: Якщо типи даних некоректні
    """
    # Конвертуємо Description
    descriptions = [
        Description(lang=d["lang"], value=d["value"])
        for d in data.get("PreviewDescription", [])
    ]

    evidences_list = []
    for package_data in data.get("evidences", []):
        package_objects = package_data["RegistryPackage"]

        registry_objects: list[ExtrinsicObjectType] = []
        for obj in package_objects:
            classification_data = obj.get("classification", {})
            classification = Classification(
                id=classification_data["id"],
                classificationScheme=classification_data["classificationScheme"],
                classificationNode=classification_data["classificationNode"],
            )

            repo_item_data = obj.get("RepositoryItemRef", {})
            repository_item = RepositoryItemRef(
                title=repo_item_data["title"],
                href=repo_item_data.get("href", _generate_cid()),
            )

            registry_objects.append(
                ExtrinsicObjectType(
                    content_type=obj["content_type"],
                    content=obj["content"],
                    classification=classification,
                    EvidenceMetadata=obj["EvidenceMetadata"],
                    RepositoryItemRef=repository_item,
                    encoding=obj.get("encoding"),
                    id=obj.get("id", _generate_identifier()),
                )
            )

        evidences_list.append(
            RegistryPackageType(
                RegistryPackage=registry_objects,
                id=package_data.get("id", _generate_identifier()),
                permit=package_data.get("permit", False),
            )
        )

    # Конвертуємо Evidences
    result = Evidences(
        title=data["title"],
        PreviewDescription=descriptions,
        preview=data.get("preview", True),
        evidences=evidences_list,
    )

    return result


__all__ = [
    "Evidences",
    "Description",
    "Classification",
    "RepositoryItemRef",
    "ExtrinsicObjectType",
    "RegistryPackageType",
    "save_evidences_to_redis",
    "get_evidences_from_redis",
    "to_legacy_evidences_dict",
    "get_legacy_evidences_from_redis",
    "ALLOWED_CLASSIFICATION_NODES",
]
