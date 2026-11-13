"""
Markdown files in Google Drive: list, read, create and edit .md files.

Shared by the hosted server (server.py registers these on /mcp and /markdown/mcp)
and the local stdio server for VS Code (local_markdown.py).

Deliberately small:
  - No delete, rename, move, share or trash. Nothing here can remove a file.
  - Every edit is exact-text based. A remove or replace whose text is missing,
    or appears more than once, is refused with the count, never guessed at.
  - Every read returns a `version`. Pass it back as `expected_version` and an
    edit refuses to run if the file changed since you read it, so a model can't
    overwrite edits made in between.
  - MARKDOWN_FOLDER_ID, when set, is the only folder any tool will touch.
  - Content is written back as the same file (Drive keeps the revision), never
    converted to a Google Doc.
"""

import difflib
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from mcp.types import ToolAnnotations

MD_MIME_TYPES = ('text/markdown', 'text/x-markdown')
MD_SUFFIXES = ('.md', '.markdown')
MAX_BYTES = 2 * 1024 * 1024  # 2 MB is far past any notes file; refuse rather than stream


class MarkdownError(Exception):
    """A refusal with a message meant for the model to read and act on."""


# ============================================================================
# PURE EDIT LOGIC (no Drive; unit-tested directly)
# ============================================================================

def newline_of(text: str) -> str:
    return '\r\n' if '\r\n' in text else '\n'


def numbered(text: str) -> str:
    """The file with 1-based line numbers, the way the edit tools count lines."""
    lines = split_lines(text)
    if not lines:
        return ''
    width = len(str(len(lines)))
    return '\n'.join(f'{i:>{width}}| {line}' for i, line in enumerate(lines, 1))


def split_lines(text: str) -> List[str]:
    """Lines without their line breaks. A trailing newline doesn't add an empty line."""
    if text == '':
        return []
    nl = newline_of(text)
    body = text[:-len(nl)] if text.endswith(nl) else text
    return body.split(nl)


def _join(lines: List[str], nl: str, trailing: bool) -> str:
    if not lines:
        return ''
    return nl.join(lines) + (nl if trailing else '')


def count_occurrences(text: str, needle: str) -> int:
    if needle == '':
        return 0
    return text.count(needle)


def _require_once(text: str, needle: str, what: str) -> int:
    if needle == '':
        raise MarkdownError(f'{what} is empty. Give the exact text to look for.')
    n = count_occurrences(text, needle)
    if n == 0:
        raise MarkdownError(
            f'{what} was not found in the file. It must match exactly, including spaces, '
            'punctuation and capital letters. Read the file again and copy the text from it.')
    if n > 1:
        raise MarkdownError(
            f'{what} appears {n} times in the file, so it is not clear which one you mean. '
            'Include more of the surrounding text so it matches exactly once.')
    return text.index(needle)


def insert_text(text: str, new_text: str, after_line: Optional[int] = None,
                anchor: Optional[str] = None) -> str:
    """Insert new_text as whole lines after line `after_line` (0 = the very top),
    or after the line on which `anchor` (exactly once) ends."""
    if (after_line is None) == (anchor is None):
        raise MarkdownError('Give exactly one of after_line or anchor.')
    if new_text == '':
        raise MarkdownError('text is empty. Give the text to insert.')
    nl = newline_of(text) if text else '\n'
    trailing = text.endswith(nl) or text == ''
    lines = split_lines(text)
    if anchor is not None:
        idx = _require_once(text, anchor, 'anchor')
        end = idx + len(anchor)
        # The line the anchor ends on (an anchor ending in a newline means the line before it).
        after_line = text[:end].rstrip('\r\n').count('\n') + 1 if text[:end].rstrip('\r\n') else 0
    if not isinstance(after_line, int) or after_line < 0 or after_line > len(lines):
        raise MarkdownError(
            f'after_line must be between 0 (the top) and {len(lines)} (the end); the file has '
            f'{len(lines)} lines.')
    piece = new_text.replace('\r\n', '\n')
    if piece.endswith('\n'):
        piece = piece[:-1]
    new_lines = piece.split('\n')
    return _join(lines[:after_line] + new_lines + lines[after_line:], nl, trailing)


def remove_text(text: str, target: str) -> str:
    """Remove `target` (exactly once). Removing whole lines also removes their line break,
    so no empty line is left behind."""
    idx = _require_once(text, target, 'text')
    end = idx + len(target)
    nl = newline_of(text)
    starts_line = idx == 0 or text[idx - 1] == '\n'
    if starts_line and not target.endswith('\n') and text[end:end + len(nl)] == nl:
        end += len(nl)
    return text[:idx] + text[end:]


def replace_text(text: str, old: str, new: str) -> str:
    idx = _require_once(text, old, 'old_text')
    return text[:idx] + new + text[idx + len(old):]


def diff_summary(before: str, after: str) -> Dict[str, Any]:
    a, b = split_lines(before), split_lines(after)
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ('replace', 'delete'):
            removed += i2 - i1
        if tag in ('replace', 'insert'):
            added += j2 - j1
    return {'lines_added': added, 'lines_removed': removed, 'line_count': len(b)}


GOOGLE_APPS_PREFIX = 'application/vnd.google-apps.'


def is_google_doc(meta: Dict[str, Any]) -> bool:
    """A Google Docs/Sheets/etc. file. Drive keeps an uploaded .md that was opened
    in Docs as a Google Doc still NAMED "x.md"; it has no raw text to download or
    upload, so it is never a Markdown file here."""
    return (meta.get('mimeType') or '').startswith(GOOGLE_APPS_PREFIX)


def is_markdown(meta: Dict[str, Any]) -> bool:
    if is_google_doc(meta):
        return False
    name = (meta.get('name') or '').lower()
    return name.endswith(MD_SUFFIXES) or meta.get('mimeType') in MD_MIME_TYPES


# ============================================================================
# DRIVE ACCESS
# ============================================================================

_FIELDS = 'id, name, mimeType, parents, trashed, size, modifiedTime, headRevisionId, webViewLink'


def _q(value: str) -> str:
    return value.replace('\\', '\\\\').replace("'", "\\'")


class MarkdownDrive:
    """Drive operations for .md files, with the folder and type checks built in."""

    def __init__(self, service_factory: Callable[[], Any], folder_id: Optional[str] = None):
        self._service_factory = service_factory
        self.folder_id = (folder_id or '').strip() or None

    @property
    def service(self):
        return self._service_factory()

    @staticmethod
    def version_of(meta: Dict[str, Any]) -> str:
        return meta.get('headRevisionId') or meta.get('modifiedTime') or ''

    # -- lookups -------------------------------------------------------------
    def _folder(self, folder_id: Optional[str]) -> Optional[str]:
        folder_id = (folder_id or '').strip() or None
        if self.folder_id:
            if folder_id and folder_id != self.folder_id:
                raise MarkdownError('This server only works in its configured folder; leave folder_id out.')
            return self.folder_id
        return folder_id

    def _check(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        if meta.get('trashed'):
            raise MarkdownError(f"{meta.get('name')} is in the trash.")
        if is_google_doc(meta):
            raise MarkdownError(f"{meta.get('name')} is a Google Doc, not a Markdown file (it was converted "
                                "when opened in Docs). Use the docs_* tools for it, or edit the original .md file.")
        if not is_markdown(meta):
            raise MarkdownError(f"{meta.get('name')} is not a Markdown file; only .md files can be read or edited here.")
        if self.folder_id and self.folder_id not in (meta.get('parents') or []):
            raise MarkdownError(f"{meta.get('name')} is outside the folder this server is allowed to use.")
        return meta

    def resolve(self, file: str) -> Dict[str, Any]:
        """A file id, or an exact file name inside the folder."""
        file = (file or '').strip()
        if not file:
            raise MarkdownError('Give the file id or its exact name.')
        if re.fullmatch(r'[A-Za-z0-9_-]{20,}', file):
            try:
                meta = self.service.files().get(fileId=file, fields=_FIELDS, supportsAllDrives=True).execute()
                return self._check(meta)
            except MarkdownError:
                raise
            except Exception:
                pass  # not an id after all; try it as a name
        q = f"name = '{_q(file)}' and trashed = false"
        if self.folder_id:
            q += f" and '{self.folder_id}' in parents"
        found = self.service.files().list(q=q, fields=f'files({_FIELDS})', pageSize=10,
                                          supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
        found = [f for f in found if is_markdown(f)]
        if not found:
            raise MarkdownError(f"No Markdown file named '{file}'. Use markdown_list_files to see the names.")
        if len(found) > 1:
            raise MarkdownError(f"{len(found)} files are named '{file}'. Use the id instead: "
                                + ', '.join(f['id'] for f in found))
        return self._check(found[0])

    def _content(self, meta: Dict[str, Any]) -> str:
        if int(meta.get('size') or 0) > MAX_BYTES:
            raise MarkdownError(f"{meta['name']} is larger than {MAX_BYTES // 1024 // 1024} MB.")
        raw = self.service.files().get_media(fileId=meta['id'], supportsAllDrives=True).execute()
        if isinstance(raw, str):
            return raw
        try:
            return raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise MarkdownError(f"{meta['name']} isn't UTF-8 text, so it can't be edited safely here.")

    # -- operations ------------------------------------------------------------
    def list_files(self, folder_id: Optional[str] = None, name_contains: Optional[str] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
        folder = self._folder(folder_id)
        q = "trashed = false and (name contains '.md' or name contains '.markdown' or mimeType = 'text/markdown' or mimeType = 'text/x-markdown')"
        if folder:
            q += f" and '{folder}' in parents"
        if name_contains:
            q += f" and name contains '{_q(name_contains)}'"
        files = self.service.files().list(q=q, fields=f'files({_FIELDS})', orderBy='name',
                                          pageSize=max(1, min(int(limit), 500)), supportsAllDrives=True,
                                          includeItemsFromAllDrives=True).execute().get('files', [])
        return [{'id': f['id'], 'name': f['name'], 'modified': f.get('modifiedTime'),
                 'version': self.version_of(f), 'link': f.get('webViewLink')}
                for f in files if is_markdown(f)]

    def read(self, file: str) -> Dict[str, Any]:
        meta = self.resolve(file)
        text = self._content(meta)
        return {'id': meta['id'], 'name': meta['name'], 'version': self.version_of(meta),
                'line_count': len(split_lines(text)), 'content': numbered(text),
                'link': meta.get('webViewLink')}

    def create(self, name: str, text: str = '', folder_id: Optional[str] = None) -> Dict[str, Any]:
        from googleapiclient.http import MediaInMemoryUpload
        name = (name or '').strip()
        if not name or '/' in name:
            raise MarkdownError('Give a plain file name, like notes.md.')
        if not name.lower().endswith(MD_SUFFIXES):
            name += '.md'
        folder = self._folder(folder_id)
        q = f"name = '{_q(name)}' and trashed = false"
        q += f" and '{folder}' in parents" if folder else " and 'root' in parents"
        if self.service.files().list(q=q, fields='files(id)', pageSize=1, supportsAllDrives=True,
                                     includeItemsFromAllDrives=True).execute().get('files'):
            raise MarkdownError(f"A file named {name} already exists there. Edit it instead, or pick another name.")
        body: Dict[str, Any] = {'name': name, 'mimeType': 'text/markdown'}
        if folder:
            body['parents'] = [folder]
        media = MediaInMemoryUpload(text.encode('utf-8'), mimetype='text/markdown', resumable=False)
        meta = self.service.files().create(body=body, media_body=media, fields=_FIELDS,
                                           supportsAllDrives=True).execute()
        return {'id': meta['id'], 'name': meta['name'], 'version': self.version_of(meta),
                'line_count': len(split_lines(text)), 'link': meta.get('webViewLink')}

    def edit(self, file: str, change: Callable[[str], str],
             expected_version: Optional[str] = None) -> Dict[str, Any]:
        from googleapiclient.http import MediaInMemoryUpload
        meta = self.resolve(file)
        current = self.version_of(meta)
        if expected_version and expected_version.strip() != current:
            raise MarkdownError('The file changed since you read it; read it again and redo the edit.')
        before = self._content(meta)
        after = change(before)
        if after == before:
            raise MarkdownError('That change leaves the file exactly as it was, so nothing was saved.')
        media = MediaInMemoryUpload(after.encode('utf-8'), mimetype=meta.get('mimeType') or 'text/markdown',
                                    resumable=False)
        new = self.service.files().update(fileId=meta['id'], media_body=media, fields=_FIELDS,
                                          supportsAllDrives=True).execute()
        return {'id': meta['id'], 'name': meta['name'], 'version': self.version_of(new),
                **diff_summary(before, after)}


# ============================================================================
# TOOLS
# ============================================================================

MARKDOWN_INSTRUCTIONS = """Markdown files in the owner's Google Drive. You can list, read, create and edit
.md files. You cannot delete, rename, move or share them.

- Read a file before editing it. markdown_read shows each line with its number and
  gives a `version`; pass that version as expected_version to every edit.
- Edits match text EXACTLY (spaces, punctuation, capitals). Copy the text from what
  markdown_read returned, without the line-number prefix like "12| ".
- If an edit says the text appears more than once, include more surrounding text.
- If an edit says the file changed, read it again and redo the edit.
- Every tool returns JSON with "success"; when it's false, read the error and fix the call.
"""

READ = ToolAnnotations(readOnlyHint=True)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False)


def _ok(**data) -> str:
    return json.dumps({'success': True, **data}, indent=2)


def _fail(e: Exception) -> str:
    msg = str(e) if isinstance(e, MarkdownError) else f'{type(e).__name__}: {e}'
    return json.dumps({'success': False, 'error': msg}, indent=2)


def register_markdown_tools(mcp, service_factory: Callable[[], Any],
                            folder_id: Optional[str] = None) -> MarkdownDrive:
    """Add the six markdown_* tools to a FastMCP server."""
    md = MarkdownDrive(service_factory, folder_id if folder_id is not None else os.environ.get('MARKDOWN_FOLDER_ID'))

    @mcp.tool(name='markdown_list_files', title='Markdown: List Files', annotations=READ)
    async def markdown_list_files(folder_id: Optional[str] = None, name_contains: Optional[str] = None,
                                  limit: int = 100) -> str:
        """List the Markdown (.md) files in the folder, with their ids, names and versions.

        folder_id: the Drive folder to list (not needed when the server has a folder set).
        name_contains: only files whose name contains this text.
        """
        try:
            files = md.list_files(folder_id, name_contains, limit)
            return _ok(folder_id=md._folder(folder_id), count=len(files), files=files)
        except Exception as e:
            return _fail(e)

    @mcp.tool(name='markdown_read', title='Markdown: Read File', annotations=READ)
    async def markdown_read(file: str) -> str:
        """Read a Markdown file. Returns every line with its 1-based line number ("12| text"),
        the line count, and the file's current `version` (pass it as expected_version when editing).

        file: the file id, or its exact name (like notes.md).
        """
        try:
            return _ok(**md.read(file))
        except Exception as e:
            return _fail(e)

    @mcp.tool(name='markdown_create', title='Markdown: Create File', annotations=EDIT)
    async def markdown_create(name: str, text: str = '', folder_id: Optional[str] = None) -> str:
        """Create a new Markdown file. Refuses if a file with that name already exists there.

        name: the file name; ".md" is added if missing.
        text: the starting content (may be empty).
        folder_id: where to create it (not needed when the server has a folder set).
        """
        try:
            return _ok(**md.create(name, text, folder_id))
        except Exception as e:
            return _fail(e)

    @mcp.tool(name='markdown_insert', title='Markdown: Insert Text', annotations=EDIT)
    async def markdown_insert(file: str, text: str, after_line: Optional[int] = None,
                              anchor: Optional[str] = None, expected_version: Optional[str] = None) -> str:
        """Insert text as new lines. Give exactly one of:
        - after_line: insert after this line number (0 = the very top; the line count = the end).
        - anchor: insert after the line on which this exact text ends (it must appear exactly once).

        file: the file id or exact name. text: the lines to insert.
        expected_version: the version from markdown_read; the edit is refused if the file changed since.
        """
        try:
            return _ok(**md.edit(file, lambda t: insert_text(t, text, after_line, anchor), expected_version))
        except Exception as e:
            return _fail(e)

    @mcp.tool(name='markdown_remove_text', title='Markdown: Remove Text', annotations=EDIT)
    async def markdown_remove_text(file: str, text: str, expected_version: Optional[str] = None) -> str:
        """Remove exact text from the file. It must appear exactly once. Removing one or more
        whole lines also removes their line break, so no blank line is left behind.

        file: the file id or exact name. text: the exact text to remove.
        expected_version: the version from markdown_read; the edit is refused if the file changed since.
        """
        try:
            return _ok(**md.edit(file, lambda t: remove_text(t, text), expected_version))
        except Exception as e:
            return _fail(e)

    @mcp.tool(name='markdown_replace_text', title='Markdown: Replace Text', annotations=EDIT)
    async def markdown_replace_text(file: str, old_text: str, new_text: str,
                                    expected_version: Optional[str] = None) -> str:
        """Replace exact text with new text. old_text must appear exactly once.

        file: the file id or exact name.
        expected_version: the version from markdown_read; the edit is refused if the file changed since.
        """
        try:
            return _ok(**md.edit(file, lambda t: replace_text(t, old_text, new_text), expected_version))
        except Exception as e:
            return _fail(e)

    return md
