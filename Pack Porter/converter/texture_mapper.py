
from pathlib import PurePosixPath


MAX_FILES = 10000
MAX_UNPACKED = 512 * 1024 * 1024
MAX_OUTPUT = 25 * 1024 * 1024

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
}


BEDROCK_TO_JAVA = {
    "blocks": "block",
    "block": "block",
    "terrain": "block",
    "items": "item",
    "item": "item",
    "entity": "entity",
    "entities": "entity",
    "mob": "entity",
    "mobs": "entity",
    "environment": "environment",
    "gui": "gui",
    "font": "font",
    "fonts": "font",
    "painting": "painting",
    "paintings": "painting",
    "particle": "particle",
    "particles": "particle",
}

JAVA_TO_BEDROCK = {
    "block": "blocks",
    "blocks": "blocks",
    "item": "items",
    "items": "items",
    "entity": "entity",
    "environment": "environment",
    "gui": "gui",
    "font": "font",
    "painting": "painting",
    "particle": "particle",
}


def validate_archive(archive):
    entries = archive.infolist()

    if len(entries) > MAX_FILES:
        raise ValueError("Too many files in the archive.")

    total_size = sum(entry.file_size for entry in entries)

    if total_size > MAX_UNPACKED:
        raise ValueError("Archive expands beyond 512 MB.")

    seen_names = set()

    for entry in entries:
        name = entry.filename.replace("\\", "/")
        path = PurePosixPath(name)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe archive path detected.")

        if entry.flag_bits & 1:
            raise ValueError("Encrypted archives are unsupported.")

        if "\x00" in name:
            raise ValueError("Invalid archive filename.")

        normalized = name.casefold()

        if normalized in seen_names:
            raise ValueError("Duplicate archive entries detected.")

        seen_names.add(normalized)

        file_type = (entry.external_attr >> 16) & 0o170000

        if file_type == 0o120000:
            raise ValueError("Symbolic links are unsupported.")

    return entries


def get_texture_category(path, direction):
    path = PurePosixPath(path.replace("\\", "/"))
    parts = list(path.parts)
    lower_parts = [part.lower() for part in parts]

    if direction == "bedrock_to_java":
        if "textures" not in lower_parts:
            return None, [], "No textures directory"

        index = lower_parts.index("textures")
        remaining = parts[index + 1:]

        if not remaining:
            return None, [], "Missing texture category"

        category = BEDROCK_TO_JAVA.get(remaining[0].lower())

        if not category:
            return None, remaining, "Unknown Bedrock texture category"

        return category, remaining[1:], None

    if direction == "java_to_bedrock":
        if "assets" not in lower_parts:
            return None, [], "No Java assets directory"

        index = lower_parts.index("assets")
        remaining = parts[index + 1:]

        if len(remaining) < 3:
            return None, [], "Incomplete Java resource path"

        if remaining[0].lower() != "minecraft":
            return None, remaining, "Non-vanilla namespace"

        if remaining[1].lower() != "textures":
            return None, remaining, "Not a texture directory"

        texture_parts = remaining[2:]

        if not texture_parts:
            return None, [], "Missing texture category"

        category = JAVA_TO_BEDROCK.get(
            texture_parts[0].lower()
        )

        if not category:
            return None, texture_parts, "Unknown Java texture category"

        return category, texture_parts[1:], None

    return None, [], "Unknown conversion direction"


def build_texture_destination(path, direction):
    """
    Return (destination, warning).

    A destination with a warning means the file can be preserved,
    but its Minecraft meaning has not been mapped.
    """

    path = PurePosixPath(path.replace("\\", "/"))
    parts = list(path.parts)
    lower_parts = [part.lower() for part in parts]

    if direction == "bedrock_to_java":

        if "textures" not in lower_parts:
            return None, "No textures directory"

        index = lower_parts.index("textures")
        remaining = parts[index + 1:]

        if not remaining:
            return None, "Missing texture filename"

        category = BEDROCK_TO_JAVA.get(remaining[0].lower())

        if category:
            if len(remaining) < 2:
                return None, "Missing texture filename"

            destination = (
                "assets/minecraft/textures/"
                + category
                + "/"
                + "/".join(remaining[1:])
            )

            return destination, None

        destination = (
            "pack_porter_unmapped/bedrock/"
            + "/".join(remaining)
        )

        return destination, (
            "Custom Bedrock texture category; manual mapping required"
        )

    if direction == "java_to_bedrock":

        if "assets" not in lower_parts:
            return None, "No Java assets directory"

        index = lower_parts.index("assets")
        remaining = parts[index + 1:]

        if len(remaining) < 3:
            return None, "Incomplete Java resource path"

        if remaining[0].lower() != "minecraft":
            return None, "Non-vanilla namespace"

        if remaining[1].lower() != "textures":
            return None, "Not a texture directory"

        texture_parts = remaining[2:]

        if not texture_parts:
            return None, "Missing texture filename"

        category = JAVA_TO_BEDROCK.get(
            texture_parts[0].lower()
        )

        if category:
            if len(texture_parts) < 2:
                return None, "Missing texture filename"

            destination = (
                "textures/"
                + category
                + "/"
                + "/".join(texture_parts[1:])
            )

            return destination, None

        destination = (
            "pack_porter_unmapped/java/"
            + "/".join(texture_parts)
        )

        return destination, (
            "Custom Java texture category; manual mapping required"
        )

    return None, "Unknown conversion direction"


def analyze_texture_name(filename):
    stem = PurePosixPath(filename).stem.lower()

    hints = []

    keywords = {
        "top": "Possible top texture",
        "side": "Possible side texture",
        "bottom": "Possible bottom texture",
        "overlay": "Possible overlay texture",
        "particle": "Possible particle texture",
        "normal": "Possible normal map",
        "height": "Possible height map",
        "emissive": "Possible emissive texture",
        "mer": "Possible MER texture",
    }

    words = stem.replace("-", "_").split("_")

    for word, description in keywords.items():
        if word in words:
            hints.append(description)

    return hints
