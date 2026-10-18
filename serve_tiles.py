#!/usr/bin/env python3
"""Serve the WoW Forever map app plus PMTiles archive routes over HTTP.

Serves the repository root as static files (index.html, vendor/, data/,
tiles/ as a fallback) and special-cases two routes:

- /tiles/{contig}/{z}/{y}_{x}.webp — answered from the PMTiles archive
- /wow-forever.pmtiles — HTTP byte-range responses for PMTiles-aware clients

Dot-prefixed paths (e.g. .git/config) are never served. Only the Python
standard library is used.
"""

from __future__ import annotations

import argparse
import re
import zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from convert_tiles import HEADER_LEN, parse_header, read_source_tile


TILE_PATH = re.compile(r"^/tiles/(kalimdor|eastern-kingdoms)/(\d+)/(\d+)_(\d+)\.webp$")
ARCHIVE_PATH = "/wow-forever.pmtiles"


def has_hidden_segment(path: str) -> bool:
    """True when any path segment starts with a dot (.git, .env, .DS_Store...)."""
    return any(part.startswith(".") for part in path.split("/") if part)


def make_handler(root: Path, archive: Path):
    data = archive.read_bytes()
    parse_header(data[:HEADER_LEN])
    # Memoize tile lookups: the archive bytes are immutable for the process,
    # so a (contig, z, x, y) result never changes.
    tile_cache: dict[tuple[str, int, int, int], tuple[int, bytes | None]] = {}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def _tile_payload(self, contig: str, z: int, x: int, y: int):
            """Return (status, payload): 404 missing tile, 500 archive failure."""
            key = (contig, z, x, y)
            if key not in tile_cache:
                try:
                    tile_cache[key] = (200, read_source_tile(data, contig, z, x, y))
                except (KeyError, ValueError):
                    tile_cache[key] = (404, None)
                except (OSError, zlib.error) as exc:
                    self.log_error("archive read failure for %s: %s", key, exc)
                    tile_cache[key] = (500, None)
            return tile_cache[key]

        def _respond_tile(self, contig: str, z: int, x: int, y: int, include_body: bool):
            status, payload = self._tile_payload(contig, z, x, y)
            if status != 200 or payload is None:
                self.send_error(status, "Tile not found" if status == 404 else "Archive read error")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            if include_body:
                self.wfile.write(payload)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            match = TILE_PATH.match(path)
            if match:
                contig, z, y, x = match.groups()
                self._respond_tile(contig, int(z), int(x), int(y), include_body=True)
                return

            if path == ARCHIVE_PATH:
                self._serve_archive(data)
                return

            if has_hidden_segment(path):
                self.send_error(404)
                return
            super().do_GET()

        def do_HEAD(self):
            path = unquote(urlsplit(self.path).path)
            match = TILE_PATH.match(path)
            if match:
                contig, z, y, x = match.groups()
                self._respond_tile(contig, int(z), int(x), int(y), include_body=False)
                return

            if path == ARCHIVE_PATH:
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.pmtiles")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return

            if has_hidden_segment(path):
                self.send_error(404)
                return
            super().do_HEAD()

        def _serve_archive(self, archive_bytes: bytes):
            range_header = self.headers.get("Range")
            start, end, status = 0, len(archive_bytes) - 1, 200
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                if not match or not (match.group(1) or match.group(2)):
                    self.send_error(416, "Invalid byte range")
                    return
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = int(last) if last else len(archive_bytes) - 1
                else:
                    start = max(0, len(archive_bytes) - int(last))
                if start >= len(archive_bytes) or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{len(archive_bytes)}")
                    self.end_headers()
                    return
                end = min(end, len(archive_bytes) - 1)
                status = 206
            payload = archive_bytes[start:end + 1]
            self.send_response(status)
            self.send_header("Content-Type", "application/vnd.pmtiles")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(archive_bytes)}")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            print(f"{self.address_string()} - {format % args}")

    return Handler


def main():
    root = Path(__file__).parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=root / "wow-forever.pmtiles")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8731)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(root, args.archive))
    print(f"Serving {root} plus /tiles/* and /wow-forever.pmtiles at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
