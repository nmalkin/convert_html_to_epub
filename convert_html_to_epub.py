"""
This script converts an HTML file to an EPUB (Electronic Publication) file.
"""

import argparse
import base64
import html
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone


def create_epub(html_file, output_file):
    """
    Converts an HTML file to an EPUB file.

    Args:
        html_file: Path to the input HTML file.
        output_file: Path to the output EPUB file.
    """
    if not os.path.exists(html_file):
        raise FileNotFoundError(f"HTML file not found: {html_file}")

    temp_dir = "epub_temp"
    # Clean up previous temp dir if it exists
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

    try:  # Use try...finally for cleanup
        # 1. mimetype file (uncompressed, ASCII)
        mimetype_path = os.path.join(temp_dir, "mimetype")
        with open(mimetype_path, "w", encoding="ascii") as f:
            f.write("application/epub+zip")

        # 2. META-INF/container.xml
        meta_inf_dir = os.path.join(temp_dir, "META-INF")
        os.makedirs(meta_inf_dir, exist_ok=True)
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
        with open(
            os.path.join(meta_inf_dir, "container.xml"), "w", encoding="utf-8"
        ) as f:
            f.write(container_xml)

        # 3. OEBPS directory
        oebps_dir = os.path.join(temp_dir, "OEBPS")
        os.makedirs(oebps_dir, exist_ok=True)

        # Extract title, content, and images from HTML
        title, content, images = extract_html_data(html_file)

        # Generate unique identifiers and date
        book_id = f"urn:uuid:{uuid.uuid4()}"  # Use URN format for UUID
        # Use ISO 8601 format (required by EPUB spec for dcterms:modified)
        date = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        # 4. OEBPS/content.opf (metadata and manifest)
        opf_content = build_opf(book_id, title, date, images)
        with open(os.path.join(oebps_dir, "content.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)

        # 5. OEBPS/content.xhtml (actual content)
        xhtml_content = build_xhtml(title, content)
        with open(os.path.join(oebps_dir, "content.xhtml"), "w", encoding="utf-8") as f:
            f.write(xhtml_content)

        # 6. OEBPS/toc.ncx (Navigation Control file for XML - for compatibility)
        toc_ncx_content = create_toc_ncx(book_id, title)
        with open(os.path.join(oebps_dir, "toc.ncx"), "w", encoding="utf-8") as f:
            f.write(toc_ncx_content)

        # 7. OEBPS/nav.xhtml (EPUB 3 Navigation Document)
        nav_xhtml_content = build_nav_xhtml(title)
        with open(os.path.join(oebps_dir, "nav.xhtml"), "w", encoding="utf-8") as f:
            f.write(nav_xhtml_content)

        # 8. OEBPS/images/ (images)
        if images:
            images_dir = os.path.join(oebps_dir, "images")
            os.makedirs(images_dir, exist_ok=True)
            for image_name, image_data in images.items():
                try:
                    # Ensure padding is correct for base64 decoding
                    missing_padding = len(image_data) % 4
                    if missing_padding:
                        image_data += "=" * (4 - missing_padding)
                    decoded_data = base64.b64decode(image_data)
                    with open(os.path.join(images_dir, image_name), "wb") as f:
                        f.write(decoded_data)
                except base64.binascii.Error as e:
                    print(
                        f"Warning: Could not decode base64 image data for {image_name}. Skipping. Error: {e}"
                    )
                except Exception as e:
                    print(
                        f"Warning: Could not write image {image_name}. Skipping. Error: {e}"
                    )

        # --- Create the EPUB file (ZIP archive) ---
        # Create the zip file and add mimetype first (uncompressed)
        with zipfile.ZipFile(output_file, "w") as epub_zip:
            epub_zip.write(
                mimetype_path, arcname="mimetype", compress_type=zipfile.ZIP_STORED
            )

        # Re-open in append mode to add the rest (compressed)
        with zipfile.ZipFile(output_file, "a", zipfile.ZIP_DEFLATED) as epub_zip:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    if arcname != "mimetype":  # Don't add mimetype again
                        epub_zip.write(file_path, arcname)

        print(f"EPUB file created: {output_file}")

    finally:
        # --- Cleanup ---
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def extract_html_data(html_file):
    """
    Extracts the title, body content, and images from the HTML file.

    Args:
        html_file: Path to the HTML file.

    Returns:
        A tuple containing the title (str), body content (str),
        and a dictionary of images {filename: base64_data}.
    """
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            html_content = f.read()
    except UnicodeDecodeError:
        # Fallback to another common encoding if UTF-8 fails
        with open(html_file, "r", encoding="iso-8859-1") as f:
            html_content = f.read()

    # Extract title
    title_match = re.search(
        r"<title>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL
    )
    # Unescape HTML entities in title (e.g., &amp; -> &)
    title = html.unescape(title_match.group(1).strip()) if title_match else "Untitled"

    # Extract body content (basic extraction, between <body> tags)
    # Use DOTALL to match across newlines
    body_match = re.search(
        r"<body[^>]*>(.*?)</body>", html_content, re.IGNORECASE | re.DOTALL
    )
    body_content = (
        body_match.group(1).strip() if body_match else html_content
    )  # Fallback to whole content if no body tag

    # Extract images and prepare for replacement
    images = {}
    processed_content = body_content
    # Find all image tags with base64 data
    # Improved regex to capture the whole tag for replacement
    img_matches = list(
        re.finditer(
            r'(<img[^>]+src="data:image/([^;]+);base64,([^"]+)"[^>]*>)',
            body_content,
            re.IGNORECASE,
        )
    )

    replacements = {}  # Store original tag -> new tag mappings

    for i, match in enumerate(img_matches):
        full_match_text = match.group(1)
        # Only process if not already handled (prevents issues with duplicate src attributes)
        if full_match_text in replacements:
            continue

        image_type = match.group(2).lower()
        image_data = match.group(3)

        # Standardize common image types for extensions
        if image_type == "jpeg":
            ext = "jpg"
        elif image_type == "svg+xml":
            ext = "svg"
        elif image_type in ["png", "gif", "bmp", "webp"]:
            ext = image_type
        else:
            ext = "img"  # Fallback extension if type is unknown/uncommon

        # Create a unique filename using index and part of UUID
        image_name = f"image_{i}_{uuid.uuid4().hex[:8]}.{ext}"
        images[image_name] = image_data

        # Try to preserve alt text, escape it for XHTML attribute
        alt_match = re.search(r'alt="([^"]*)"', full_match_text, re.IGNORECASE)
        # Escape quotes and other special chars within the alt text
        alt_text = html.escape(alt_match.group(1), quote=True) if alt_match else "image"

        # The replacement tag pointing to the file
        new_img_tag = f'<img src="images/{image_name}" alt="{alt_text}"/>'
        replacements[full_match_text] = new_img_tag

    # Perform replacements after finding all matches
    for original_tag, new_tag in replacements.items():
        processed_content = processed_content.replace(original_tag, new_tag)

    # Basic cleanup if body extraction failed (no <body> tag found)
    if not body_match:
        processed_content = re.sub(
            r"<head>.*?</head>", "", processed_content, flags=re.DOTALL | re.IGNORECASE
        )
        processed_content = re.sub(
            r"<!DOCTYPE[^>]*>", "", processed_content, flags=re.IGNORECASE
        )
        processed_content = re.sub(
            r"<html[^>]*>", "", processed_content, flags=re.IGNORECASE
        )
        processed_content = re.sub(
            r"</html>", "", processed_content, flags=re.IGNORECASE
        )

    return title, processed_content.strip(), images


def build_opf(book_id, title, date, images):
    """
    Builds the content.opf file content.

    Args:
        book_id: Unique identifier for the book.
        title: Title of the book.
        date: Modification date (ISO 8601 format).
        images: Dictionary of images {filename: base64_data}.

    Returns:
        The content of the content.opf file as a string.
    """
    escaped_title = html.escape(title)
    image_items = ""
    for i, image_name in enumerate(images.keys()):
        # Create a valid XML ID (starts with letter or underscore)
        image_id = f"img_{i}"
        ext = image_name.split(".")[-1].lower()

        # Determine media type from extension (common types)
        if ext == "jpg" or ext == "jpeg":
            media_type = "image/jpeg"
        elif ext == "png":
            media_type = "image/png"
        elif ext == "gif":
            media_type = "image/gif"
        elif ext == "svg":
            media_type = "image/svg+xml"
        elif ext == "bmp":
            media_type = "image/bmp"
        elif ext == "webp":
            media_type = "image/webp"
        else:
            media_type = "application/octet-stream"  # Fallback media type

        image_items += f'    <item id="{image_id}" href="images/{image_name}" media-type="{media_type}"/>\n'

    # Added rendition metadata common for reflowable ebooks
    # Declared prefix 'rendition'
    # Specified nav property on the correct item ('toc' which links to nav.xhtml)
    opf_template = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">{book_id}</dc:identifier>
    <dc:title>{escaped_title}</dc:title>
    <dc:language>en</dc:language> <!-- Consider making this configurable or detect from HTML -->
    <meta property="dcterms:modified">{date}</meta>
    <meta property="rendition:layout">reflowable</meta>
    <meta property="rendition:orientation">auto</meta>
    <meta property="rendition:spread">auto</meta>
  </metadata>
  <manifest>
    <item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>
    <item id="toc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
{image_items}
  </manifest>
  <spine toc="ncx">
    <itemref idref="content"/>
    <!-- Add more itemrefs here if the book is split into multiple XHTML files -->
  </spine>
</package>
"""
    return opf_template


def build_xhtml(title, content):
    """
    Builds the content.xhtml file content.

    Args:
        title: Title of the book.
        content: HTML body content of the book.

    Returns:
        The content of the content.xhtml file as a string.
    """
    escaped_title = html.escape(title)
    # Basic XHTML5 structure. Added xml:lang and lang attributes. Added charset meta tag.
    xhtml_template = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
  <head>
    <meta charset="UTF-8"/>
    <title>{escaped_title}</title>
    <!-- Link to a CSS file if needed -->
    <!-- <link href="style.css" rel="stylesheet" type="text/css"/> -->
  </head>
  <body>
    <!-- Content should ideally be structured, e.g., within <section> or <article> -->
    {content}
  </body>
</html>
"""
    return xhtml_template


def build_nav_xhtml(title):
    """
    Builds the nav.xhtml file content (EPUB 3 Navigation Document).

    Args:
        title: Title of the book.

    Returns:
        The content of the nav.xhtml file as a string.
    """
    escaped_title = html.escape(title)
    # Basic single-entry nav doc with TOC and Landmarks
    # Added charset meta tag. Added xml:lang and lang attributes.
    nav_xhtml_template = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Table of Contents</title>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>{escaped_title}</h1>
    <ol>
      <li><a href="content.xhtml">Content</a></li>
      <!-- TODO: Generate more detailed ToC if HTML has headings (h1, h2, etc.) -->
    </ol>
  </nav>
  <nav epub:type="landmarks" hidden="">
    <h2>Guide</h2>
    <ol>
      <li><a epub:type="bodymatter" href="content.xhtml">Content</a></li>
      <!-- TODO: Add other landmarks like cover, title page if applicable -->
    </ol>
  </nav>
</body>
</html>
"""
    return nav_xhtml_template


def create_toc_ncx(book_id, title):
    """
    Creates the toc.ncx file content (for EPUB 2 compatibility).

    Args:
        book_id: Unique identifier for the book (must match OPF).
        title: Title of the book.

    Returns:
        The content of the toc.ncx file as a string.
    """
    escaped_title = html.escape(title)
    # Basic NCX structure. Added xml:lang attribute.
    toc_ncx_template = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"
 "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="en">
  <head>
    <!-- The UID must match the unique-identifier in content.opf -->
    <meta name="dtb:uid" content="{book_id}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle>
    <text>{escaped_title}</text>
  </docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel>
        <text>Content</text> <!-- Use a generic label or the main title -->
      </navLabel>
      <content src="content.xhtml"/>
    </navPoint>
    <!-- TODO: Generate more navPoints if HTML has headings -->
  </navMap>
</ncx>
"""
    return toc_ncx_template


def main():
    parser = argparse.ArgumentParser(description="Convert HTML to EPUB.")
    parser.add_argument("html_file", help="Path to the input HTML file.")
    parser.add_argument(
        "-o",
        "--output_file",
        help="Path to the output EPUB file. Defaults to <html_file_name>.epub.",
    )
    args = parser.parse_args()

    html_file = args.html_file
    output_file = args.output_file or os.path.splitext(html_file)[0] + ".epub"

    try:
        create_epub(html_file, output_file)
    except FileNotFoundError as e:
        print(f"Error: Input file not found - {e}")
        exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
