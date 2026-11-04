"""Create new ZIP, 7z and TAR-family archives without an external program."""
from pathlib import Path
import stat
import tarfile

from .operations import Cancelled, create_zip
from .providers import LocalProvider
from .transfer_status import emit

FORMATS = [('ZIP', 'zip', '.zip'), ('7z / LZMA', '7z', '.7z'),
           ('TAR', 'tar', '.tar'), ('TAR + GZIP', 'tar.gz', '.tar.gz'),
           ('TAR + BZIP2', 'tar.bz2', '.tar.bz2'), ('TAR + XZ', 'tar.xz', '.tar.xz')]


def create_archive(source, source_path, destination_path, entries, cancel, report=lambda *args: None, format='zip'):
    if format not in {key for label, key, extension in FORMATS}:
        raise ValueError('Unsupported archive creation format.')
    if format == 'zip':
        return create_zip(source, source_path, destination_path, entries, cancel, report)
    target = Path(destination_path).resolve()
    if isinstance(source, LocalProvider):
        for entry in entries:
            original = Path(source.join(source_path, entry.name)).resolve()
            if original == target or entry.is_dir and original in target.parents:
                raise ValueError('An archive cannot be created inside the folder being packed.')

    def check():
        if cancel.is_set():
            raise Cancelled('Archive creation canceled.')

    planned = []
    def plan(base, name, entry, depth=0):
        check()
        if depth > 256 or len(planned) >= 250000:
            raise ValueError('The archive selection is too large or too deeply nested.')
        if entry.is_link:
            raise ValueError(f'Archiving symbolic links is not supported: {entry.name}')
        path = source.join(base, entry.name)
        if isinstance(source, LocalProvider):
            info = Path(path).lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) if entry.is_dir else stat.S_ISREG(info.st_mode)):
                raise ValueError(f'Only regular files and folders can be packed: {entry.name}')
            if not entry.is_dir and (info.st_size != entry.size or info.st_mtime != entry.modified):
                raise IOError('A source file changed since it was listed. Refresh and try again.')
        planned.append((name, path, entry))
        if entry.is_dir:
            for child in source.list(path):
                plan(path, name + '/' + child.name, child, depth + 1)

    def produce(output):
        with source.batch():
            for entry in entries:
                plan(source_path, entry.name, entry)
            emit(report, 'plan', bytes=sum(e.size for _, _, e in planned if not e.is_dir), files=sum(not e.is_dir for _, _, e in planned))
            if format == '7z':
                from .archive_runtime import prepare_archive
                prepare_archive()
                import libarchive
                from libarchive.entry import FileType
                with libarchive.fd_writer(output.fileno(), '7zip') as archive:
                    for name, path, entry in planned:
                        check()
                        permission = (entry.mode & 0o777) or (0o755 if entry.is_dir else 0o644)
                        if entry.is_dir:
                            archive.add_file_from_memory(name + '/', 0, b'', filetype=FileType.DIRECTORY, permission=permission, mtime=entry.modified)
                        else:
                            emit(report, 'file', source=path, destination=str(target) + '!/' + name, size=entry.size)
                            def blocks():
                                count = 0
                                with source.open_reader(path) as stream:
                                    while block := stream.read(256 * 1024):
                                        check()
                                        count += len(block)
                                        if count > entry.size:
                                            raise IOError('The source file changed while packing.')
                                        yield block
                                        emit(report, 'advance', bytes=count)
                                        report(f'Packing · {name}', len(block))
                                if count != entry.size:
                                    raise IOError('The source file changed while packing.')
                            archive.add_file_from_memory(name, entry.size, blocks(), permission=permission, mtime=entry.modified)
                            emit(report, 'file_done', path=name, size=entry.size)
            else:
                compression = {'tar': '', 'tar.gz': 'gz', 'tar.bz2': 'bz2', 'tar.xz': 'xz'}[format]
                with tarfile.open(fileobj=output, mode='w|' + compression, format=tarfile.PAX_FORMAT) as archive:
                    for name, path, entry in planned:
                        check()
                        info = tarfile.TarInfo(name + ('/' if entry.is_dir else ''))
                        info.mode = (entry.mode & 0o777) or (0o755 if entry.is_dir else 0o644)
                        info.mtime = entry.modified
                        info.type = tarfile.DIRTYPE if entry.is_dir else tarfile.REGTYPE
                        info.size = 0 if entry.is_dir else entry.size
                        if entry.is_dir:
                            archive.addfile(info)
                        else:
                            emit(report, 'file', source=path, destination=str(target) + '!/' + name, size=entry.size)
                            with source.open_reader(path) as stream:
                                class Reader:
                                    count = 0
                                    def read(self, size):
                                        check()
                                        block = stream.read(size)
                                        self.count += len(block)
                                        emit(report, 'advance', bytes=self.count)
                                        report(f'Packing · {name}', len(block))
                                        return block
                                reader = Reader()
                                archive.addfile(info, reader)
                                if reader.count != entry.size or stream.read(1):
                                    raise IOError('The source file changed while packing.')
                            emit(report, 'file_done', path=name, size=entry.size)
        check()
    LocalProvider().write_with(destination_path, produce, lambda count: check())
