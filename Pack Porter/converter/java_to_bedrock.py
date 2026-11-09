
import io
import json
import uuid
import zipfile

from pathlib import PurePosixPath

from .texture_mapper import (
    IMAGE_EXTENSIONS,
    MAX_OUTPUT,
    validate_archive,
    build_texture_destination,
    analyze_texture_name,
)


BEDROCK_VERSIONS = {
    "bedrock:1.21.50": [1, 21, 50],
    "bedrock:1.20.80": [1, 20, 80],
}

DEFAULT_BEDROCK_VERSION = [1, 21, 50]


def convert_java_to_bedrock(data, filename, target_version="auto"):

    if not filename.lower().endswith(".zip"):
        return None, None, "Upload a Java resource-pack ZIP."

    if target_version != "auto" and target_version not in BEDROCK_VERSIONS:
        return None, None, "Invalid Bedrock target version."

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as source:

            entries = validate_archive(source)

            pack_metadata = None

            for entry in entries:
                if PurePosixPath(entry.filename.lower()).name == "pack.mcmeta":
                    pack_metadata = entry
                    break

            if pack_metadata is None:
                return None, None, "Java pack.mcmeta was not found."

            try:
                metadata = json.loads(source.read(pack_metadata))
            except (ValueError, UnicodeDecodeError):
                return None, None, "Invalid pack.mcmeta."

            if not isinstance(metadata.get("pack"), dict):
                return None, None, "Invalid Java pack metadata."

            output_buffer = io.BytesIO()

            converted = []
            unmapped = []
            unsupported = []
            texture_analysis = []
            used_paths = set()

            terrain_textures = {}
            item_textures = {}

            with zipfile.ZipFile(
                output_buffer,
                "w",
                compression=zipfile.ZIP_DEFLATED
            ) as output:

                for entry in entries:

                    if entry.is_dir():
                        continue

                    original_path = entry.filename.replace("\\", "/")
                    path = PurePosixPath(original_path)

                    # Convert Java pack icon to Bedrock pack icon.
                    if path.name.lower() == "pack.png":
                        destination = "pack_icon.png"

                        if destination.casefold() not in used_paths:
                            output.writestr(
                                destination,
                                source.read(entry)
                            )
                            used_paths.add(destination.casefold())

                        continue

                    if path.suffix.lower() not in IMAGE_EXTENSIONS:
                        continue

                    destination, warning = build_texture_destination(
                        original_path,
                        "java_to_bedrock"
                    )

                    if destination is None:
                        unsupported.append({
                            "file": original_path,
                            "reason": warning
                        })
                        continue

                    normalized_destination = destination.casefold()

                    if normalized_destination in used_paths:
                        unsupported.append({
                            "file": original_path,
                            "reason": "Duplicate destination path"
                        })
                        continue

                    output.writestr(
                        destination,
                        source.read(entry)
                    )

                    used_paths.add(normalized_destination)

                    if warning:
                        unmapped.append({
                            "source": original_path,
                            "preserved_as": destination,
                            "reason": warning
                        })
                        continue

                    converted.append(destination)

                    bedrock_category = destination.split("/")[1]

                    texture_analysis.append({
                        "source": original_path,
                        "destination": destination,
                        "category": bedrock_category,
                        "filename_hints": analyze_texture_name(
                            original_path
                        )
                    })

                    # Generate basic atlas entries for blocks and items.
                    texture_path = destination.rsplit(".", 1)[0]
                    texture_name = PurePosixPath(destination).stem

                    if bedrock_category == "blocks":
                        terrain_textures[texture_name] = {
                            "textures": texture_path
                        }

                    elif bedrock_category == "items":
                        item_textures[texture_name] = {
                            "textures": texture_path
                        }

                if not converted and not unmapped:
                    return (
                        None,
                        None,
                        "No usable Java textures were found."
                    )

                engine_version = BEDROCK_VERSIONS.get(
                    target_version,
                    DEFAULT_BEDROCK_VERSION
                )

                manifest = {
                    "format_version": 2,
                    "header": {
                        "name": "Pack Porter Converted Pack",
                        "description": "Converted with Pack Porter",
                        "uuid": str(uuid.uuid4()),
                        "version": [1, 0, 0],
                        "min_engine_version": engine_version
                    },
                    "modules": [
                        {
                            "type": "resources",
                            "uuid": str(uuid.uuid4()),
                            "version": [1, 0, 0]
                        }
                    ]
                }

                output.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=4)
                )

                if terrain_textures:
                    terrain_atlas = {
                        "resource_pack_name": "Pack Porter",
                        "texture_name": "atlas.terrain",
                        "texture_data": terrain_textures
                    }

                    output.writestr(
                        "textures/terrain_texture.json",
                        json.dumps(terrain_atlas, indent=4)
                    )

                if item_textures:
                    item_atlas = {
                        "resource_pack_name": "Pack Porter",
                        "texture_name": "atlas.items",
                        "texture_data": item_textures
                    }

                    output.writestr(
                        "textures/item_texture.json",
                        json.dumps(item_atlas, indent=4)
                    )

                report = {
                    "converter": "Pack Porter",
                    "direction": "Java to Bedrock",
                    "target_version": target_version,
                    "min_engine_version": engine_version,
                    "converted_texture_count": len(converted),
                    "unmapped_texture_count": len(unmapped),
                    "unsupported_texture_count": len(unsupported),
                    "converted_textures": converted,
                    "texture_analysis": texture_analysis,
                    "preserved_unmapped_textures": unmapped,
                    "unsupported_files": unsupported,
                    "notes": [
                        "Recognized textures were mapped to Bedrock paths.",
                        "Unknown texture folders were preserved separately.",
                        "Preserved unmapped textures are not guaranteed to work in Bedrock.",
                        "Basic Bedrock texture atlas files were generated.",
                        "Texture identifiers may require manual adjustment.",
                        "Java-specific models, shaders and rendering features were not converted.",
                        "The Java pack icon was copied as pack_icon.png.",
                        "Check compatibility with the selected Bedrock version."
                    ]
                }

                output.writestr(
                    "conversion_report.json",
                    json.dumps(report, indent=4)
                )

            result = output_buffer.getvalue()

            if len(result) > MAX_OUTPUT:
                return None, None, "Output exceeds the 25 MB limit."

            return result, report, None

    except zipfile.BadZipFile:
        return None, None, "Invalid ZIP archive."

    except ValueError as error:
        return None, None, str(error)

    except (OSError, RuntimeError):
        return None, None, "Unable to process this Java pack."
