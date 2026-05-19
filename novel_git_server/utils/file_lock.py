import os
from contextlib import contextmanager
from typing import IO, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def exclusive_file_lock(file_obj: IO[str] | IO[bytes]) -> Iterator[None]:
    if os.name == "nt":
        original_position = file_obj.tell()
        file_obj.flush()
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
        try:
            file_obj.seek(original_position)
            yield
        finally:
            file_obj.flush()
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
            file_obj.seek(original_position)
        return

    fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
