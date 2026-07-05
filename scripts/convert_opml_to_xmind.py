#!/usr/bin/env python3
"""
Convert OPML file to modern XMind (.xmind) format with professional theming.
"""

import json
import zipfile
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET
import argparse


def generate_id():
    return str(uuid.uuid4())


def get_default_theme():
    """Return a professional XMind theme (similar to high-quality mind maps)."""
    return {
        "map": {
            "id": generate_id(),
            "properties": {
                "svg:fill": "#ffffff",
                "multi-line-colors": "#F9423A #F6A04D #F3D321 #00BC7B #486AFF #4D49BE",
                "color-list": "#000229 #1F2766 #52CC83 #4D86DB #99142F #245570",
                "line-tapered": "none"
            }
        },
        "centralTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "30pt",
                "fo:font-weight": "500",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
                "svg:fill": "#000229",
                "fill-pattern": "solid",
                "line-width": "3pt",
                "line-color": "#000229",
                "line-pattern": "solid",
                "border-line-color": "inherited",
                "border-line-width": "0pt",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.curve",
                "arrow-end-class": "org.xmind.arrowShape.none",
                "alignment-by-level": "inherited"
            }
        },
        "mainTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "18pt",
                "fo:font-weight": "500",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
                "svg:fill": "inherited",
                "fill-pattern": "solid",
                "line-width": "2pt",
                "line-color": "inherited",
                "line-pattern": "inherited",
                "border-line-color": "inherited",
                "border-line-width": "0pt",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "arrow-end-class": "inherited",
                "alignment-by-level": "inherited"
            }
        },
        "subTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "14pt",
                "fo:font-weight": "400",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
                "svg:fill": "inherited",
                "fill-pattern": "solid",
                "line-width": "2pt",
                "line-color": "inherited",
                "line-pattern": "inherited",
                "border-line-color": "inherited",
                "border-line-width": "0pt",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "arrow-end-class": "inherited",
                "alignment-by-level": "inherited"
            }
        },
        "floatingTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "14pt",
                "fo:font-weight": "500",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
                "svg:fill": "#EEEBEE",
                "fill-pattern": "solid",
                "line-width": "2pt",
                "line-color": "inherited",
                "line-pattern": "solid",
                "border-line-color": "#EEEBEE",
                "border-line-width": "0pt",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "arrow-end-class": "org.xmind.arrowShape.none",
                "alignment-by-level": "inherited"
            }
        },
        "summaryTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "14pt",
                "fo:font-weight": "400",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
                "svg:fill": "#000229",
                "fill-pattern": "none",
                "line-width": "inherited",
                "line-color": "inherited",
                "line-pattern": "inherited",
                "border-line-color": "#000229",
                "border-line-width": "inherited",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "arrow-end-class": "inherited",
                "alignment-by-level": "inherited"
            }
        },
        "calloutTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "14pt",
                "fo:font-weight": "400",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "left",
                "svg:fill": "#000229",
                "fill-pattern": "solid",
                "line-width": "inherited",
                "line-color": "inherited",
                "line-pattern": "inherited",
                "border-line-color": "#000229",
                "border-line-width": "inherited",
                "border-line-pattern": "inherited",
                "shape-class": "org.xmind.topicShape.roundedRect",
                "line-class": "org.xmind.branchConnection.roundedElbow",
                "arrow-end-class": "inherited",
                "alignment-by-level": "inherited"
            }
        },
        "importantTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-weight": "bold",
                "svg:fill": "#460400",
                "fill-pattern": "solid",
                "border-line-color": "#460400",
                "border-line-width": "0"
            }
        },
        "minorTopic": {
            "id": generate_id(),
            "properties": {
                "fo:font-weight": "bold",
                "svg:fill": "#703D00",
                "fill-pattern": "solid",
                "border-line-color": "#703D00",
                "border-line-width": "0"
            }
        },
        "expiredTopic": {
            "id": generate_id(),
            "properties": {
                "fo:text-decoration": "line-through",
                "fill-pattern": "none"
            }
        },
        "boundary": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "14pt",
                "fo:font-weight": "400",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
                "svg:fill": "#000229",
                "fill-pattern": "solid",
                "line-width": "2",
                "line-color": "#000229",
                "line-pattern": "dash",
                "shape-class": "org.xmind.boundaryShape.roundedRect"
            }
        },
        "summary": {
            "id": generate_id(),
            "properties": {
                "line-width": "2pt",
                "line-color": "#000229",
                "line-pattern": "solid",
                "shape-class": "org.xmind.summaryShape.round"
            }
        },
        "relationship": {
            "id": generate_id(),
            "properties": {
                "fo:font-family": "NeverMind",
                "fo:font-size": "13pt",
                "fo:font-weight": "400",
                "fo:font-style": "normal",
                "fo:color": "inherited",
                "fo:text-transform": "manual",
                "fo:text-decoration": "none",
                "fo:text-align": "center",
                "line-width": "2",
                "line-color": "#000229",
                "line-pattern": "dash",
                "shape-class": "org.xmind.relationshipShape.curved",
                "arrow-begin-class": "org.xmind.arrowShape.none",
                "arrow-end-class": "org.xmind.arrowShape.triangle"
            }
        },
        "skeletonThemeId": "db4a5df4db39a8cd1310ea55ea",
        "colorThemeId": "Rainbow-#000229-MULTI_LINE_COLORS"
    }


def parse_opml(opml_path):
    """Parse OPML and return the root outline structure."""
    tree = ET.parse(opml_path)
    root = tree.getroot()

    body = root.find('body')
    if body is None:
        raise ValueError("Invalid OPML: no <body> element found")

    outline = body.find('outline')
    if outline is None:
        raise ValueError("Invalid OPML: no root <outline> element found")

    return outline


def build_topic(outline_element):
    """Recursively build XMind topic structure from OPML outline."""
    title = outline_element.get('text', 'Untitled')

    topic = {
        "id": generate_id(),
        "title": title,
        "class": "topic"
    }

    # Add children
    children = []
    for child in outline_element.findall('outline'):
        children.append(build_topic(child))

    if children:
        topic["children"] = {
            "attached": children
        }

    # Handle _note attribute
    note = outline_element.get('_note')
    if note:
        topic["notes"] = {
            "plain": {
                "content": note
            }
        }

    return topic


def create_xmind_content(opml_root, title=None):
    """Create the full content.json structure for XMind with theming."""
    if title is None:
        title = opml_root.get('text', 'Converted from OPML')

    central_topic = build_topic(opml_root)
    central_topic["title"] = title
    central_topic["structureClass"] = "org.xmind.ui.map.clockwise"

    sheet = {
        "id": generate_id(),
        "class": "sheet",
        "title": "Sheet 1",
        "rootTopic": central_topic,
        "extensions": [
            {
                "provider": "org.xmind.ui.skeleton.structure.style",
                "content": {
                    "centralTopic": "org.xmind.ui.map.clockwise"
                }
            }
        ],
        "theme": get_default_theme()
    }

    return [sheet]


def create_xmind_file(opml_path, output_path, title=None):
    """Convert OPML to a rich .xmind file."""
    print(f"Parsing OPML: {opml_path}")
    opml_root = parse_opml(opml_path)

    print("Building rich XMind structure with theme...")
    content = create_xmind_content(opml_root, title)

    metadata = {
        "dataStructureVersion": "2",
        "creator": {
            "name": "opml-to-xmind skill",
            "version": "2.0"
        },
        "layoutEngineVersion": "3"
    }

    manifest = {
        "file-entries": {
            "content.json": {},
            "metadata.json": {}
        }
    }

    output_path = Path(output_path)
    print(f"Creating professional XMind file: {output_path}")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('content.json', json.dumps(content, indent=2, ensure_ascii=False))
        zf.writestr('metadata.json', json.dumps(metadata, indent=2))
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    print(f"✅ Successfully created rich XMind file: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Convert OPML to rich XMind (.xmind) with professional theming")
    parser.add_argument("input", help="Input OPML file")
    parser.add_argument("output", help="Output .xmind file")
    parser.add_argument("--title", help="Custom title for the central topic")

    args = parser.parse_args()

    create_xmind_file(args.input, args.output, args.title)


if __name__ == "__main__":
    main()
