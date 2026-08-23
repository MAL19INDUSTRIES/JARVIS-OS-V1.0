"""Native PowerPoint 3D-model discovery and placement.

PowerPoint stores editable 3D objects as DrawingML ``graphicFrame`` elements
related to embedded GLB package parts.  ``python-pptx`` preserves those unknown
parts, but it does not expose an API for creating them.  This module provides a
small, package-native bridge so JARVIS can inventory models in a supplied deck
and place a real (rotatable) model into newly generated slides.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import posixpath
import re
import uuid
import zipfile

from lxml import etree


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MODEL3D_URI = "http://schemas.microsoft.com/office/drawing/2017/model3d"
MODEL3D_REL = "http://schemas.microsoft.com/office/2017/06/relationships/model3d"
MODEL3D_CONTENT_TYPE = "model/gltf.binary"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "model"


def _slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _resolve_part(source_part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


@dataclass(frozen=True)
class Native3DAsset:
    """A reusable native model view discovered inside a PowerPoint deck."""

    asset_ref: str
    source_path: Path
    source_slide: int
    name: str
    description: str
    model_part: str
    poster_part: str | None
    frame_xml: bytes

    def metadata(self) -> dict[str, object]:
        return {
            "asset_ref": self.asset_ref,
            "name": self.name,
            "description": self.description,
            "source_slide": self.source_slide,
            "model_part": self.model_part,
            "has_poster": bool(self.poster_part),
            "native_powerpoint_3d": True,
        }


def inspect_native_3d(path: Path) -> list[Native3DAsset]:
    """Return one reusable native asset for each unique GLB in ``path``."""
    path = Path(path)
    if path.suffix.lower() != ".pptx" or not path.is_file() or not zipfile.is_zipfile(path):
        return []

    discovered: list[Native3DAsset] = []
    seen_model_parts: set[str] = set()
    with zipfile.ZipFile(path) as package:
        slide_names = sorted(
            (
                name for name in package.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ),
            key=_slide_number,
        )
        for slide_name in slide_names:
            slide_xml = package.read(slide_name)
            if b"model3d" not in slide_xml.lower():
                continue
            rels_name = (
                f"{posixpath.dirname(slide_name)}/_rels/"
                f"{posixpath.basename(slide_name)}.rels"
            )
            if rels_name not in package.namelist():
                continue
            rel_root = etree.fromstring(package.read(rels_name))
            relationships = {
                rel.get("Id"): (
                    rel.get("Type") or "",
                    _resolve_part(slide_name, rel.get("Target") or ""),
                )
                for rel in rel_root
            }
            root = etree.fromstring(slide_xml)
            frames = root.xpath(
                ".//*[local-name()='graphicFrame'][.//*[local-name()='graphicData' "
                "and contains(@uri, 'model3d')]]"
            )
            for frame in frames:
                model_nodes = frame.xpath(".//*[local-name()='model3d']")
                if not model_nodes:
                    continue
                model_rid = model_nodes[0].get(f"{{{R_NS}}}embed")
                rel_type, model_part = relationships.get(model_rid, ("", ""))
                if rel_type != MODEL3D_REL or not model_part or model_part in seen_model_parts:
                    continue
                if model_part not in package.namelist():
                    continue

                poster_part = None
                blips = model_nodes[0].xpath(".//*[local-name()='raster']//*[local-name()='blip']")
                if blips:
                    poster_rid = blips[0].get(f"{{{R_NS}}}embed")
                    poster_type, candidate = relationships.get(poster_rid, ("", ""))
                    if poster_type.endswith("/image") and candidate in package.namelist():
                        poster_part = candidate

                properties = frame.xpath("./*[local-name()='nvGraphicFramePr']/*[local-name()='cNvPr']")
                name = properties[0].get("name", "3D Model") if properties else "3D Model"
                description = properties[0].get("descr", "") if properties else ""
                ordinal = len(discovered) + 1
                label = description or name or f"model-{ordinal}"
                asset_ref = (
                    f"powerpoint-3d://{_slug(path.stem)}/"
                    f"{ordinal}-{_slug(label)}"
                )
                discovered.append(Native3DAsset(
                    asset_ref=asset_ref,
                    source_path=path.resolve(),
                    source_slide=_slide_number(slide_name),
                    name=name,
                    description=description,
                    model_part=model_part,
                    poster_part=poster_part,
                    frame_xml=etree.tostring(frame),
                ))
                seen_model_parts.add(model_part)
    return discovered


def native_3d_lookup(paths: list[Path]) -> dict[str, Native3DAsset]:
    """Build a case-insensitive lookup for native 3D assets in PPTX sources."""
    lookup: dict[str, Native3DAsset] = {}
    for path in paths:
        for asset in inspect_native_3d(path):
            lookup[asset.asset_ref.lower()] = asset
            lookup.setdefault(asset.name.lower(), asset)
            if asset.description:
                lookup.setdefault(asset.description.lower(), asset)
    return lookup


def add_native_3d_model(
    slide,
    asset: Native3DAsset,
    x_emu: int,
    y_emu: int,
    width_emu: int,
    height_emu: int,
    model_part_cache: dict[tuple[str, str], object] | None = None,
):
    """Place ``asset`` on ``slide`` as an editable PowerPoint 3D object."""
    from pptx.opc.package import Part

    cache = model_part_cache if model_part_cache is not None else {}
    package = slide.part.package
    cache_key = (str(asset.source_path), asset.model_part)
    model_part = cache.get(cache_key)
    with zipfile.ZipFile(asset.source_path) as source:
        if model_part is None:
            partname = package.next_partname("/ppt/media/model3d%d.glb")
            model_part = Part(
                partname,
                MODEL3D_CONTENT_TYPE,
                package,
                source.read(asset.model_part),
            )
            cache[cache_key] = model_part
        model_rid = slide.part.relate_to(model_part, MODEL3D_REL)

        poster_rid = ""
        if asset.poster_part:
            _, poster_rid = slide.part.get_or_add_image_part(
                BytesIO(source.read(asset.poster_part))
            )

    frame = etree.fromstring(asset.frame_xml)
    model_nodes = frame.xpath(".//*[local-name()='model3d']")
    if not model_nodes:
        raise ValueError(f"Native 3D frame is missing its model node: {asset.asset_ref}")
    model_nodes[0].set(f"{{{R_NS}}}embed", model_rid)
    blips = model_nodes[0].xpath(".//*[local-name()='raster']//*[local-name()='blip']")
    if blips:
        if poster_rid:
            blips[0].set(f"{{{R_NS}}}embed", poster_rid)
        else:
            raster = blips[0].getparent()
            if raster is not None:
                raster.getparent().remove(raster)

    frame_xfrm = frame.xpath("./*[local-name()='xfrm']")
    if frame_xfrm:
        off = frame_xfrm[0].xpath("./*[local-name()='off']")
        ext = frame_xfrm[0].xpath("./*[local-name()='ext']")
        if off:
            off[0].set("x", str(int(x_emu)))
            off[0].set("y", str(int(y_emu)))
        if ext:
            ext[0].set("cx", str(int(width_emu)))
            ext[0].set("cy", str(int(height_emu)))
    model_ext = model_nodes[0].xpath(
        "./*[local-name()='spPr']/*[local-name()='xfrm']/*[local-name()='ext']"
    )
    if model_ext:
        model_ext[0].set("cx", str(int(width_emu)))
        model_ext[0].set("cy", str(int(height_emu)))

    ids = []
    for node in slide._element.xpath(".//*[local-name()='cNvPr']"):
        try:
            ids.append(int(node.get("id", "0")))
        except ValueError:
            pass
    properties = frame.xpath("./*[local-name()='nvGraphicFramePr']/*[local-name()='cNvPr']")
    if properties:
        properties[0].set("id", str(max(ids or [1]) + 1))
        # PowerPoint Morph treats matching names prefixed with ``!!`` as the
        # same object across slides, allowing a native model to move cleanly.
        properties[0].set("name", f"!!JARVIS 3D — {asset.description or asset.name}")
    for creation_id in frame.xpath(".//*[local-name()='creationId']"):
        creation_id.set("id", "{" + str(uuid.uuid4()).upper() + "}")

    shape_tree = slide.shapes._spTree
    ext_list = next(
        (child for child in shape_tree if etree.QName(child).localname == "extLst"),
        None,
    )
    if ext_list is None:
        shape_tree.append(frame)
    else:
        ext_list.addprevious(frame)
    return frame
