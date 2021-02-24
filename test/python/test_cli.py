"""
Tests for command line interface wrapper.

These tests just check that the various command line parameters route to the
correct functionionality. They use a lot of monkeypatching to avoid executing
the actual functions.
"""
from pathlib import Path

import pytest

import nominatim.cli
import nominatim.clicmd.api
import nominatim.clicmd.refresh
import nominatim.clicmd.admin
import nominatim.indexer.indexer
import nominatim.tools.admin
import nominatim.tools.check_database
import nominatim.tools.freeze
import nominatim.tools.refresh

from mocks import MockParamCapture

SRC_DIR = (Path(__file__) / '..' / '..' / '..').resolve()

def call_nominatim(*args):
    return nominatim.cli.nominatim(module_dir='build/module',
                                   osm2pgsql_path='build/osm2pgsql/osm2pgsql',
                                   phplib_dir=str(SRC_DIR / 'lib-php'),
                                   data_dir=str(SRC_DIR / 'data'),
                                   phpcgi_path='/usr/bin/php-cgi',
                                   sqllib_dir=str(SRC_DIR / 'lib-sql'),
                                   config_dir=str(SRC_DIR / 'settings'),
                                   cli_args=args)


@pytest.fixture
def mock_run_legacy(monkeypatch):
    mock = MockParamCapture()
    monkeypatch.setattr(nominatim.cli, 'run_legacy_script', mock)
    return mock

@pytest.fixture
def mock_func_factory(monkeypatch):
    def get_mock(module, func):
        mock = MockParamCapture()
        monkeypatch.setattr(module, func, mock)
        return mock

    return get_mock

def test_cli_help(capsys):
    """ Running nominatim tool without arguments prints help.
    """
    assert 1 == call_nominatim()

    captured = capsys.readouterr()
    assert captured.out.startswith('usage:')


@pytest.mark.parametrize("command,script", [
                         (('import', '--continue', 'load-data'), 'setup'),
                         (('special-phrases',), 'specialphrases'),
                         (('add-data', '--tiger-data', 'tiger'), 'setup'),
                         (('add-data', '--file', 'foo.osm'), 'update'),
                         (('export',), 'export')
                         ])
def test_legacy_commands_simple(mock_run_legacy, command, script):
    assert 0 == call_nominatim(*command)

    assert mock_run_legacy.called == 1
    assert mock_run_legacy.last_args[0] == script + '.php'


def test_freeze_command(mock_func_factory, temp_db):
    mock_drop = mock_func_factory(nominatim.tools.freeze, 'drop_update_tables')
    mock_flatnode = mock_func_factory(nominatim.tools.freeze, 'drop_flatnode_file')

    assert 0 == call_nominatim('freeze')

    assert mock_drop.called == 1
    assert mock_flatnode.called == 1


@pytest.mark.parametrize("params", [('--warm', ),
                                    ('--warm', '--reverse-only'),
                                    ('--warm', '--search-only')])
def test_admin_command_legacy(mock_func_factory, params):
    mock_run_legacy = mock_func_factory(nominatim.clicmd.admin, 'run_legacy_script')

    assert 0 == call_nominatim('admin', *params)

    assert mock_run_legacy.called == 1


@pytest.mark.parametrize("func, params", [('analyse_indexing', ('--analyse-indexing', ))])
def test_admin_command_tool(temp_db, mock_func_factory, func, params):
    mock = mock_func_factory(nominatim.tools.admin, func)

    assert 0 == call_nominatim('admin', *params)
    assert mock.called == 1


def test_admin_command_check_database(mock_func_factory):
    mock = mock_func_factory(nominatim.tools.check_database, 'check_database')

    assert 0 == call_nominatim('admin', '--check-database')
    assert mock.called == 1


@pytest.mark.parametrize("name,oid", [('file', 'foo.osm'), ('diff', 'foo.osc'),
                                      ('node', 12), ('way', 8), ('relation', 32)])
def test_add_data_command(mock_run_legacy, name, oid):
    assert 0 == call_nominatim('add-data', '--' + name, str(oid))

    assert mock_run_legacy.called == 1
    assert mock_run_legacy.last_args == ('update.php', '--import-' + name, oid)


@pytest.mark.parametrize("params,do_bnds,do_ranks", [
                          ([], 1, 1),
                          (['--boundaries-only'], 1, 0),
                          (['--no-boundaries'], 0, 1),
                          (['--boundaries-only', '--no-boundaries'], 0, 0)])
def test_index_command(mock_func_factory, temp_db_cursor, params, do_bnds, do_ranks):
    temp_db_cursor.execute("CREATE TABLE import_status (indexed bool)")
    bnd_mock = mock_func_factory(nominatim.indexer.indexer.Indexer, 'index_boundaries')
    rank_mock = mock_func_factory(nominatim.indexer.indexer.Indexer, 'index_by_rank')

    assert 0 == call_nominatim('index', *params)

    assert bnd_mock.called == do_bnds
    assert rank_mock.called == do_ranks


@pytest.mark.parametrize("command,params", [
                         ('wiki-data', ('setup.php', '--import-wikipedia-articles')),
                         ('importance', ('update.php', '--recompute-importance')),
                         ])
def test_refresh_legacy_command(mock_func_factory, temp_db, command, params):
    mock_run_legacy = mock_func_factory(nominatim.clicmd.refresh, 'run_legacy_script')

    assert 0 == call_nominatim('refresh', '--' + command)

    assert mock_run_legacy.called == 1
    assert len(mock_run_legacy.last_args) >= len(params)
    assert mock_run_legacy.last_args[:len(params)] == params

@pytest.mark.parametrize("command,func", [
                         ('postcodes', 'update_postcodes'),
                         ('word-counts', 'recompute_word_counts'),
                         ('address-levels', 'load_address_levels_from_file'),
                         ('functions', 'create_functions'),
                         ('website', 'setup_website'),
                         ])
def test_refresh_command(mock_func_factory, temp_db, command, func):
    func_mock = mock_func_factory(nominatim.tools.refresh, func)

    assert 0 == call_nominatim('refresh', '--' + command)
    assert func_mock.called == 1


def test_refresh_importance_computed_after_wiki_import(mock_func_factory, temp_db):
    mock_run_legacy = mock_func_factory(nominatim.clicmd.refresh, 'run_legacy_script')

    assert 0 == call_nominatim('refresh', '--importance', '--wiki-data')

    assert mock_run_legacy.called == 2
    assert mock_run_legacy.last_args == ('update.php', '--recompute-importance')


def test_serve_command(mock_func_factory):
    func = mock_func_factory(nominatim.cli, 'run_php_server')

    call_nominatim('serve')

    assert func.called == 1

@pytest.mark.parametrize("params", [
                         ('search', '--query', 'new'),
                         ('reverse', '--lat', '0', '--lon', '0'),
                         ('lookup', '--id', 'N1'),
                         ('details', '--node', '1'),
                         ('details', '--way', '1'),
                         ('details', '--relation', '1'),
                         ('details', '--place_id', '10001'),
                         ('status',)
                         ])
def test_api_commands_simple(mock_func_factory, params):
    mock_run_api = mock_func_factory(nominatim.clicmd.api, 'run_api_script')

    assert 0 == call_nominatim(*params)

    assert mock_run_api.called == 1
    assert mock_run_api.last_args[0] == params[0]
