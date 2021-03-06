from __future__ import print_function

import zipfile
import os


MAX_COUNT = 1000
MAX_SIZE = 10 ** 9  # 1GB
OUT_ZIP_FORMAT = "part-%03d.zip"


def create_partitioned_zips_from_dir(
    src, out_dir, max_count=MAX_COUNT, max_size=MAX_SIZE
):
    """
    Given directory, create a set of zips that contain all files in there. No
    filtering is done here.
    """
    zips = Zipper(out_dir, max_count, max_size)

    for (dirpath, dirnames, filenames) in os.walk(src):
        dir_skip = len(src)
        dirname = dirpath[dir_skip:]
        if dirname.startswith("/"):
            dirname = dirname[1:]

        for filename in filenames:
            path = os.path.join(dirpath, filename)
            entry_name = os.path.join(dirname, filename)
            with open(path, "rb") as f:
                zips.append(entry_name, os.path.getsize(path), lambda: f.read())

    return zips.list()


def _find_top_level(zip_objects):
    repodir = None
    toplevel_objects = set()

    # Find if there is a maven-repository subdir under top-level directory.
    for info in zip_objects:
        parts = info.filename.split("/")
        toplevel_objects.add(parts[0])
        if len(parts) < 3:
            # Not a subdirectory of top-level dir or a file in there.
            continue
        if parts[1] == "maven-repository":
            repodir = os.path.join(*parts[:2]) + "/"

    if len(toplevel_objects) > 1:
        raise RuntimeError("Invalid zip file: there are multiple top-level entries.")

    return repodir


def iterate_zip_content(zf, debug=False):
    zip_objects = zf.infolist()
    # Find which directory should be uploaded.
    repodir = _find_top_level(zip_objects)

    # Iterate over all objects in the directory.
    for info in zip_objects:
        if info.filename.endswith("/") and info.file_size == 0:
            # Skip directories for this iteration.
            continue

        filename = info.filename
        # We found maven-repository subdirectory previously, only content from
        # there should be taken.
        if repodir:
            if filename.startswith(repodir):
                # It's in correct location, move to top-level.
                filename = filename[len(repodir):]
            else:
                # Not correct location, ignore it.
                continue
        else:
            # Otherwise we only strip the leading component.
            filename = filename.split("/", 1)[-1]

        if debug:
            print("Mapping %s -> %s" % (info.filename, filename))
        yield filename, info.file_size, info.filename


def create_partitioned_zips_from_zip(
    src, out_dir, max_count=MAX_COUNT, max_size=MAX_SIZE, debug=False
):
    """
    Given a zip archive, split it into smaller chunks and possibly filter out
    only some parts.

    The general structure is like this (given foo-1.0.0-maven-repository.zip):

    foo-1.0-maven-repository/
    foo-1.0-maven-repository/examples/
    foo-1.0-maven-repository/maven-repository/...
    foo-1.0-maven-repository/licenses/
    foo-1.0-maven-repository/example-config.xml

    This function will look for a maven-subdirectory inside the top-level
    directory and only repackage its contents. If there is no such
    subdirectory, all content will be taken without any changes.
    The top-level directory name does not matter at all.

    Alternatively, the content to be published can be directly under the
    top-level directory. In such case the top-level directory is dropped and
    everything else is published.

    If there is more than one top-level entry in the archive, an error is
    reported.
    """
    zips = Zipper(out_dir, max_count, max_size)
    zf = zipfile.ZipFile(src)

    for target, size, source in iterate_zip_content(zf, debug=debug):
        zips.append(target, size, lambda: zf.read(source))

    return zips.list()


class Zipper(object):
    def __init__(self, out_dir, max_count=MAX_COUNT, max_size=MAX_SIZE):
        self.out_dir = out_dir
        self.max_count = max_count
        self.max_size = max_size
        self.file_count = 0
        self.file_size = 0
        self.counter = 0
        self.zip = None

    def should_rollover(self, size):
        return (
            self.zip is None  # No zip created yet
            or self.file_count >= self.max_count  # Maximum file count reached
            or self.file_size + size >= self.max_size  # Maximum size reached
        )

    def rollover(self):
        if self.zip is not None:
            self.zip.close()
            self.counter += 1
            self.file_count = 0
            self.file_size = 0

        self.zip = zipfile.ZipFile(
            os.path.join(self.out_dir, OUT_ZIP_FORMAT % self.counter), mode="w"
        )

    def append(self, filename, size, stream_func):
        if self.should_rollover(size):
            self.rollover()

        self.zip.writestr(filename, stream_func())
        self.file_count += 1
        self.file_size += size

    def close(self):
        if self.zip is not None:
            self.zip.close()

    def list(self):
        return sorted(
            os.path.join(self.out_dir, fname) for fname in os.listdir(self.out_dir)
        )
