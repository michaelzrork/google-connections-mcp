"""The markdown_* edit logic and its Drive guards, against a fake Drive."""
import json

import pytest

from google_connections_mcp import markdown_drive as M
from google_connections_mcp.markdown_drive import MarkdownDrive, MarkdownError

FOLDER = 'folder-allowed-0000000000'


# -- pure edit logic -----------------------------------------------------------

def test_numbered_and_split():
    assert M.split_lines('a\nb\n') == ['a', 'b']
    assert M.split_lines('a\nb') == ['a', 'b']
    assert M.split_lines('') == []
    assert M.numbered('a\nb\n') == '1| a\n2| b'


def test_insert_after_line_and_bounds():
    t = 'one\ntwo\nthree\n'
    assert M.insert_text(t, 'top', after_line=0) == 'top\none\ntwo\nthree\n'
    assert M.insert_text(t, 'mid', after_line=2) == 'one\ntwo\nmid\nthree\n'
    assert M.insert_text(t, 'end\n', after_line=3) == 'one\ntwo\nthree\nend\n'
    assert M.insert_text('', 'first', after_line=0) == 'first\n'
    with pytest.raises(MarkdownError, match='between 0'):
        M.insert_text(t, 'x', after_line=4)
    with pytest.raises(MarkdownError, match='between 0'):
        M.insert_text(t, 'x', after_line=-1)
    with pytest.raises(MarkdownError, match='exactly one'):
        M.insert_text(t, 'x')
    with pytest.raises(MarkdownError, match='exactly one'):
        M.insert_text(t, 'x', after_line=1, anchor='one')


def test_insert_after_anchor_and_uniqueness():
    t = '# Title\n\n## Notes\n- a\n'
    assert M.insert_text(t, '- new', anchor='## Notes') == '# Title\n\n## Notes\n- new\n- a\n'
    assert M.insert_text(t, '- new', anchor='## Notes\n') == '# Title\n\n## Notes\n- new\n- a\n'
    with pytest.raises(MarkdownError, match='not found'):
        M.insert_text(t, 'x', anchor='## Missing')
    with pytest.raises(MarkdownError, match='appears 2 times'):
        M.insert_text('x\nx\n', 'y', anchor='x')


def test_crlf_is_kept():
    t = 'a\r\nb\r\n'
    assert M.insert_text(t, 'c', after_line=2) == 'a\r\nb\r\nc\r\n'
    assert M.remove_text(t, 'a') == 'b\r\n'


def test_remove_text():
    t = '- a\n- b\n- c\n'
    assert M.remove_text(t, '- b') == '- a\n- c\n'          # a whole line goes with its break
    assert M.remove_text('the big dog\n', 'big ') == 'the dog\n'  # inside a line, only the text
    with pytest.raises(MarkdownError, match='appears 2 times'):
        M.remove_text('x x\n', 'x')
    with pytest.raises(MarkdownError, match='not found'):
        M.remove_text(t, '- z')
    with pytest.raises(MarkdownError, match='empty'):
        M.remove_text(t, '')


def test_replace_text():
    assert M.replace_text('Status: draft\n', 'draft', 'final') == 'Status: final\n'
    with pytest.raises(MarkdownError, match='appears 3 times'):
        M.replace_text('a a a', 'a', 'b')


def test_diff_summary():
    assert M.diff_summary('a\nb\n', 'a\nc\nd\n') == {'lines_added': 2, 'lines_removed': 1, 'line_count': 3}


# -- fake Drive ------------------------------------------------------------------

class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeFiles:
    def __init__(self, drive):
        self.d = drive

    def get(self, fileId, fields=None, supportsAllDrives=None):
        def run():
            if fileId not in self.d.meta:
                raise Exception('404 not found')
            return dict(self.d.meta[fileId])
        return _Call(run)

    def get_media(self, fileId, supportsAllDrives=None):
        return _Call(lambda: self.d.content[fileId].encode())

    def list(self, q, fields=None, pageSize=None, supportsAllDrives=None, includeItemsFromAllDrives=None, orderBy=None):
        self.d.queries.append(q)

        def run():
            out = []
            for m in self.d.meta.values():
                if m.get('trashed'):
                    continue
                if "name = '" in q and f"name = '{m['name']}'" not in q:
                    continue
                if " in parents" in q:
                    parent = q.split("' in parents")[0].rsplit("'", 1)[1]
                    if parent not in m.get('parents', []):
                        continue
                out.append(dict(m))
            return {'files': out}
        return _Call(run)

    def create(self, body, media_body, fields=None, supportsAllDrives=None):
        def run():
            fid = f'new-file-{len(self.d.meta):020d}'
            self.d.meta[fid] = {'id': fid, 'name': body['name'], 'mimeType': body['mimeType'],
                                'parents': body.get('parents', ['root']), 'headRevisionId': 'r1'}
            self.d.content[fid] = media_body.getbytes(0, media_body.size()).decode()
            return dict(self.d.meta[fid])
        return _Call(run)

    def update(self, fileId, media_body, fields=None, supportsAllDrives=None):
        def run():
            self.d.content[fileId] = media_body.getbytes(0, media_body.size()).decode()
            self.d.uploads.append((fileId, media_body.mimetype()))
            m = self.d.meta[fileId]
            m['headRevisionId'] = 'r' + str(int(m['headRevisionId'][1:]) + 1)
            return dict(m)
        return _Call(run)

    def delete(self, **kw):  # pragma: no cover - must never be reached
        raise AssertionError('markdown tools must never delete')


class FakeDrive:
    def __init__(self):
        self.meta = {}
        self.content = {}
        self.queries = []
        self.uploads = []

    def add(self, fid, name, text, parents=(FOLDER,), mime='text/markdown'):
        self.meta[fid] = {'id': fid, 'name': name, 'mimeType': mime, 'parents': list(parents),
                          'headRevisionId': 'r1', 'size': str(len(text))}
        self.content[fid] = text

    def files(self):
        return FakeFiles(self)


ID_IN = 'inside-file-0000000000001'
ID_OUT = 'outside-file-000000000001'
ID_TXT = 'not-markdown-000000000001'


@pytest.fixture
def drive():
    d = FakeDrive()
    d.add(ID_IN, 'notes.md', '# Notes\n- a\n')
    d.add(ID_OUT, 'elsewhere.md', 'secret\n', parents=('other-folder',))
    d.add(ID_TXT, 'data.csv', 'a,b\n', mime='text/csv')
    return d


@pytest.fixture
def md(drive):
    return MarkdownDrive(lambda: drive, FOLDER)


def test_read_by_id_and_name(md):
    r = md.read(ID_IN)
    assert r['version'] == 'r1' and r['content'] == '1| # Notes\n2| - a' and r['line_count'] == 2
    assert md.read('notes.md')['id'] == ID_IN


def test_folder_restriction(md, drive):
    with pytest.raises(MarkdownError, match='outside the folder'):
        md.read(ID_OUT)
    with pytest.raises(MarkdownError, match='outside the folder'):
        md.edit(ID_OUT, lambda t: t + 'x')
    assert drive.content[ID_OUT] == 'secret\n'
    with pytest.raises(MarkdownError, match='configured folder'):
        md.list_files(folder_id='other-folder')


def test_only_markdown(md):
    with pytest.raises(MarkdownError, match='not a Markdown file'):
        md.read(ID_TXT)


def test_version_mismatch_refuses(md, drive):
    with pytest.raises(MarkdownError, match='changed since you read it'):
        md.edit(ID_IN, lambda t: M.insert_text(t, '- b', after_line=2), expected_version='r0')
    assert drive.content[ID_IN] == '# Notes\n- a\n' and not drive.uploads


def test_edit_writes_back_same_type_and_new_version(md, drive):
    r = md.edit(ID_IN, lambda t: M.insert_text(t, '- b', after_line=2), expected_version='r1')
    assert drive.content[ID_IN] == '# Notes\n- a\n- b\n'
    assert r['version'] == 'r2' and r['lines_added'] == 1 and r['lines_removed'] == 0
    assert drive.uploads == [(ID_IN, 'text/markdown')]


def test_no_op_edit_is_refused(md):
    with pytest.raises(MarkdownError, match='exactly as it was'):
        md.edit(ID_IN, lambda t: t)


def test_create(md, drive):
    r = md.create('todo', '- first\n')
    assert r['name'] == 'todo.md' and drive.meta[r['id']]['parents'] == [FOLDER]
    assert drive.content[r['id']] == '- first\n'
    with pytest.raises(MarkdownError, match='already exists'):
        md.create('notes.md')


def test_no_delete_capability():
    names = [n for n in dir(MarkdownDrive) if not n.startswith('_')]
    assert not any(w in n for n in names for w in ('delete', 'trash', 'rename', 'move', 'share'))


def test_registered_tools():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP('t')
    M.register_markdown_tools(server, lambda: FakeDrive(), FOLDER)
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    assert set(tools) == {'markdown_list_files', 'markdown_read', 'markdown_create', 'markdown_insert',
                          'markdown_remove_text', 'markdown_replace_text'}
    assert tools['markdown_read'].annotations.readOnlyHint is True
    assert tools['markdown_insert'].annotations.destructiveHint is False


@pytest.mark.anyio
async def test_tool_returns_json_errors():
    from mcp.server.fastmcp import FastMCP
    d = FakeDrive()
    d.add(ID_IN, 'notes.md', 'x x\n')
    server = FastMCP('t')
    M.register_markdown_tools(server, lambda: d, FOLDER)
    out = await server._tool_manager.call_tool('markdown_remove_text', {'file': ID_IN, 'text': 'x'})
    data = json.loads(out)
    assert data['success'] is False and 'appears 2 times' in data['error']


def test_google_doc_named_md_is_not_markdown(drive):
    # Drive keeps an uploaded .md that was opened in Docs as a Google Doc still named
    # "x.md"; it has no raw text, and the raw download fails with a 403.
    gdoc = 'google-doc-named-md-00001'
    drive.add(gdoc, 'Policy.md', '', mime='application/vnd.google-apps.document')
    md = MarkdownDrive(lambda: drive, FOLDER)
    assert not M.is_markdown(drive.meta[gdoc])
    with pytest.raises(MarkdownError, match='is a Google Doc'):
        md.read(gdoc)
    with pytest.raises(MarkdownError, match='is a Google Doc'):
        md.edit(gdoc, lambda t: t + 'x')
    assert gdoc not in [f['id'] for f in md.list_files()]
