"""Previewable rename masks with one-based, inclusive Total Commander ranges."""
from datetime import datetime
from pathlib import PurePosixPath
import re

from .providers import safe_name

TOKEN = re.compile(r'\[\[\]|\[\]\]|\[[^][]+\]')


def literal_mask(text):
    return ''.join('[[]' if c == '[' else '[]]' if c == ']' else c for c in text)


def character_range(text, specification):
    if not specification:
        return text
    match = re.fullmatch(r'(-?\d+)(?:,(\d+)|-(-?\d*))?', specification)
    if not match or int(match[1]) == 0:
        raise ValueError('Invalid character range. Use [N1-5], [N2,5] or [N-4-].')
    start = int(match[1])
    index = start - 1 if start > 0 else len(text) + start
    index = max(0, index)
    if match[2] is not None:
        return text[index:index + int(match[2])]
    if match[3] is None:
        return text[index:index + 1]
    if match[3] == '':
        return text[index:]
    end = int(match[3])
    if not end:
        raise ValueError('Character positions start at 1, not 0.')
    if start < 0 and end > 0:
        end = -end
    stop = end if end > 0 else len(text) + end + 1
    return text[index:max(0, stop)]


def expand_mask(template, entry, index, start, digits, step, parent):
    path = PurePosixPath(entry.name)
    stem, suffix = (entry.name, '') if entry.is_dir else (path.stem, path.suffix[1:])
    folder = PurePosixPath(parent.replace('\\', '/'))
    fields = {'N': stem, 'E': suffix, 'P': folder.name, 'G': folder.parent.name}
    date = datetime.fromtimestamp(entry.modified) if entry.modified else None
    date_fields = dict(zip('YMDhms', ('%Y', '%m', '%d', '%H', '%M', '%S')))
    mode, result, offset = 'n', [], 0

    def append(text):
        result.append(text.upper() if mode == 'U' else text.lower() if mode == 'L' else text.title() if mode == 'F' else text)

    for match in TOKEN.finditer(template):
        literal = template[offset:match.start()]
        if '[' in literal or ']' in literal:
            raise ValueError('Escape literal brackets with [[] and []].')
        append(literal)
        token = match[0][1:-1]
        if token in ('[', ']'):
            append(token)
        elif token in ('U', 'L', 'F', 'n'):
            mode = token
        elif token[0] in fields:
            append(character_range(fields[token[0]], token[1:]))
        elif token[0] == 'C':
            counter = re.fullmatch(r'C(-?\d+)?([+-]\d+)?(?::(\d+))?', token)
            if not counter:
                raise ValueError('Invalid counter. Use [C] or [C10+5:3].')
            first = int(counter[1]) if counter[1] is not None else start
            increment = int(counter[2]) if counter[2] is not None else step
            width = int(counter[3]) if counter[3] is not None else digits
            if not 1 <= width <= 12 or abs(first) > 10**12 or abs(increment) > 10**12:
                raise ValueError('Invalid numbering.')
            append(str(first + index * increment).zfill(width))
        elif all(c in date_fields for c in token):
            append(date.strftime(''.join(date_fields[c] for c in token)) if date else '')
        elif token in ('d', 't'):
            append(date.strftime('%Y-%m-%d' if token == 'd' else '%H.%M.%S') if date else '')
        else:
            raise ValueError('Unknown rename placeholder: [' + token + ']')
        offset = match.end()
    literal = template[offset:]
    if '[' in literal or ']' in literal:
        raise ValueError('Escape literal brackets with [[] and []].')
    append(literal)
    return ''.join(result)


def build_names(entries, mask='[N]', extension='[E]', find='', replacement='', case='keep', start=1, digits=1,
                *, step=1, parent='', regex=False, case_sensitive=True, replace_extension=True,
                first_only=False, check_duplicates=True):
    if not (abs(start) <= 10**12 and abs(step) <= 10**12 and 1 <= digits <= 12):
        raise ValueError('Invalid numbering.')
    try:
        search = re.compile(find if regex else re.escape(find), 0 if case_sensitive else re.IGNORECASE) if find else None
    except re.error as exc:
        raise ValueError('Invalid search expression: ' + str(exc)) from exc
    names = []
    for index, entry in enumerate(entries):
        name = expand_mask(mask, entry, index, start, digits, step, parent)
        ext = expand_mask(extension, entry, index, start, digits, step, parent) if not entry.is_dir else ''
        value = name + ('.' + ext if ext else '')
        if search:
            subject = value if replace_extension else name
            try:
                subject = search.sub(replacement if regex else lambda match: replacement, subject, count=1 if first_only else 0)
            except re.error as exc:
                raise ValueError('Invalid replacement expression: ' + str(exc)) from exc
            value = subject if replace_extension else subject + ('.' + ext if ext else '')
        value = value.lower() if case == 'lower' else value.upper() if case == 'upper' else value.title() if case == 'title' else value.capitalize() if case == 'sentence' else value
        safe_name(value)
        names.append(value)
    if check_duplicates and len({n.casefold() for n in names}) != len(names):
        raise ValueError('Multiple items would receive the same name.')
    return names
