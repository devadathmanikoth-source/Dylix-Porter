
import io
import json
import zipfile

from pathlib import PurePosixPath

from .texture_mapper import (
    IMAGE_EXTENSIONS,
    MAX_OUTPUT,
    validate_archive,
    build_texture_destination,
    analyze_texture_name,
)


JAVA_PACK_FORMATS = {
    "java:1.21.4": 46,
    "java:1.20.1": 15,
}

DEFAULT_PACK_FORMAT = 46


def convert_bedrock_to_java(data, filename, target_version="auto"):

    if not filename.lower().endswith((".mcpack", ".zip")):
        return None, None, "Upload a Bedrock MCPACK or ZIP file."

    if target_version != "auto" and target_version not in JAVA_PACK_FORMATS:
        return None, None, "Invalid Java target version."

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as source:

            entries = validate_archive(source)
            names = [entry.filename for entry in entries]

            manifest_found = any(
                PurePosixPath(name.lower()).name == "manifest.json"
                for name in names
            )

            if not manifest_found:
                return None, None, "Bedrock manifest.json was not found."

            output_buffer = io.BytesIO()

            converted = []
            unmapped = []
            unsupported = []
            preserved_assets = []
            texture_analysis = []
            used_paths = set()

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
                    lower_name = path.name.lower()
                    extension = path.suffix.lower()

                    # Bedrock pack icon -> Java pack icon.
                    if lower_name == "pack_icon.png":
                        destination = "pack.png"

                        if destination.lower() not in used_paths:
                            output.writestr(
                                destination,
                                source.read(entry)
                            )
                            used_paths.add(destination.lower())
                            preserved_assets.append({
                                "source": original_path,
                                "destination": destination,
                                "type": "pack_icon"
                            })
                        else:
                            unsupported.append({
                                "file": original_path,
                                "reason": "Duplicate pack icon destination"
                            })

                        continue

                    # Handle image textures.
                    if extension in IMAGE_EXTENSIONS:

                        destination, reason = build_texture_destination(
                            original_path,
                            "bedrock_to_java"
                        )

                        if not destination:
                            unsupported.append({
                                "file": original_path,
                                "reason": reason or "No destination available"
                            })
                            continue

                        normalized_destination = destination.lower()

                        if normalized_destination in used_paths:
                            unsupported.append({
                                "file": original_path,
                                "reason": "Duplicate destination path"
                            })
                            continue

                        image_data = source.read(entry)

                        output.writestr(destination, image_data)
                        used_paths.add(normalized_destination)

                        if reason:
                            unmapped.append({
                                "source": original_path,
                                "destination": destination,
                                "reason": reason
                            })
                        else:
                            converted.append(destination)

                        texture_analysis.append({
                            "source": original_path,
                            "destination": destination,
                            "filename_hints": analyze_texture_name(
                                original_path
                            )
                        })

                        continue

                    # Preserve non-image files for manual inspection.
                    # These are NOT converted into functional Java assets.
                    if extension in (".json", ".material", ".lang"):

                        destination = (
                            "pack_porter_unmapped/bedrock/" + original_path
                        )

                        normalized_destination = destination.lower()

                        if normalized_destination in used_paths:
                            unsupported.append({
                                "file": original_path,
                                "reason": "Duplicate preserved asset path"
                            })
                            continue

                        output.writestr(
                            destination,
                            source.read(entry)
                        )

                        used_paths.add(normalized_destination)

                        preserved_assets.append({
                            "source": original_path,
                            "destination": destination,
                            "type": "unconverted_metadata",
                            "warning": (
                                "Preserved for reference only. "
                                "Bedrock JSON is not Java-compatible."
                            )
                        })

                        continue

                    # Other files are reported instead of silently ignored.
                    unsupported.append({
                        "file": original_path,
                        "reason": "Unsupported file type"
                    })

                if not converted and not unmapped:
                    return (
                        None,
                        None,
                        "No usable Bedrock image textures were found."
                    )

                pack_format = JAVA_PACK_FORMATS.get(
                    target_version,
                    DEFAULT_PACK_FORMAT
                )

                metadata = {
                    "pack": {
                        "pack_format": pack_format,
                        "description": "Converted with Pack Porter"
                    }
                }

                output.writestr(
                    "pack.mcmeta",
                    json.dumps(metadata, indent=4)
                )

                report = {
                    "converter": "Pack Porter",
                    "direction": "Bedrock to Java",
                    "target_version": target_version,
                    "java_pack_format": pack_format,

                    "converted_texture_count": len(converted),
                    "unmapped_texture_count": len(unmapped),
                    "unsupported_texture_count": len(unsupported),

                    "preserved_asset_count": len(preserved_assets),

                    "converted_textures": converted,
                    "unmapped_textures": unmapped,
                    "preserved_assets": preserved_assets,
                    "texture_analysis": texture_analysis,
                    "unsupported_files": unsupported,

                    "notes": [
                        "Recognized textures were mapped to Java texture folders.",
                        "Unknown texture folders were preserved under pack_porter_unmapped.",
                        "Bedrock JSON assets were preserved for reference, not converted.",
                        "Bedrock animations, particles and entity definitions are not Java-compatible.",
                        "Preserved assets do not automatically function in Java.",
                        "Texture filename hints are suggestions, not verified identities.",
                        "Check compatibility with the selected Java version."
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
        return None, None, "Invalid ZIP-based resource pack."

    except ValueError as error:
        return None, None, str(error)

    except (OSError, RuntimeError):
        return None, None, "Unable to process this Bedrock pack."
