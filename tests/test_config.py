from copy import deepcopy
import os

from pytest import raises
import yaml

from flatpak_indexer.config import ConfigError
from flatpak_indexer.utils import SubstitutionError
from .utils import get_config, setup_client_cert

BASIC_CONFIG = yaml.safe_load("""
pyxis_url: https://pyxis.example.com/v1
redis_url: redis://localhost
koji_config: brew
deltas_dir: /flatpaks/deltas/
deltas_uri: https://flatpaks.example.com/deltas
icons_dir: /flatpaks/icons/
icons_uri: https://flatpaks.example.com/icons
daemon:
    update_interval: 1800
registries:
    registry.example.com:
        repositories: ['repo1', 'repo2']
        public_url: https://registry.example.com/
        datasource: pyxis
    brew:
        public_url: https://private.example.com/
        datasource: pyxis
    fedora:
        public_url: https://registry.fedoraproject.org/
        datasource: fedora
indexes:
    amd64:
        architecture: amd64
        registry: registry.example.com
        output: /flatpaks/flatpak-amd64.json
        tag: latest
        extract_icons: true
    brew-rc:
        registry: brew
        output: /flatpaks/rc-amd64.json
        koji_tag: release-candidate
    fedora-testing:
        registry: fedora
        output: /fedora/flatpak-testing.json
        bodhi_status: testing
        tag: testing
        delta_keep_days: 7
""")


def test_config_empty(tmp_path):
    with raises(ConfigError, match="Top level of config.yaml must be an object with keys"):
        get_config(tmp_path, None)


def test_config_basic(tmp_path):
    conf = get_config(tmp_path, BASIC_CONFIG)
    assert conf.pyxis_url == "https://pyxis.example.com/v1/"


def test_key_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['redis_url']
    with raises(ConfigError, match=r'A value is required for redis_url'):
        get_config(tmp_path, config_data)


def test_str_type(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['pyxis_url'] = 42
    with raises(ConfigError, match="pyxis_url must be a string"):
        get_config(tmp_path, config_data)


def test_bool_type(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['indexes']['amd64']['extract_icons'] = 42
    with raises(ConfigError, match="indexes/amd64/extract_icons must be a boolean"):
        get_config(tmp_path, config_data)


def test_int_type(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['daemon']['update_interval'] = "FOO"
    with raises(ConfigError, match="daemon/update_interval must be an integer"):
        get_config(tmp_path, config_data)


def test_str_list_type(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['registries']['registry.example.com']['repositories'] = "FOO"
    with raises(ConfigError,
                match="registries/registry.example.com/repositories must be a list of strings"):
        get_config(tmp_path, config_data)


def test_dict_list_type(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['local_certs'] = "FOO"
    with raises(ConfigError,
                match="local_certs must be a mapping with string values"):
        get_config(tmp_path, config_data)

    config_data['local_certs'] = {"FOO": 1}
    with raises(ConfigError,
                match="local_certs must be a mapping with string values"):
        get_config(tmp_path, config_data)


def test_environment_variable(tmp_path):
    os.environ["DOMAIN_NAME"] = 'pyxis.example.com'
    CONFIG = {
        'pyxis_url': 'https://${DOMAIN_NAME}/v1',
        'redis_url': 'redis://localhost',
        'koji_config': 'brew',
    }
    conf = get_config(tmp_path, CONFIG)
    assert conf.pyxis_url == "https://pyxis.example.com/v1/"


def test_environment_variable_default(tmp_path):
    if "DOMAIN_NAME" in os.environ:
        del os.environ["DOMAIN_NAME"]
    CONFIG = {
        'pyxis_url': 'https://${DOMAIN_NAME:pyxis.example.com}/v1',
        'redis_url': 'redis://localhost',
        'koji_config': 'brew',
    }
    conf = get_config(tmp_path, CONFIG)
    assert conf.pyxis_url == "https://pyxis.example.com/v1/"


def test_environment_variable_missing(tmp_path):
    if "DOMAIN_NAME" in os.environ:
        del os.environ["DOMAIN_NAME"]
    CONFIG = {
        'pyxis_url': 'https://${DOMAIN_NAME}/v1',
        'koji_config': 'brew',
    }
    with raises(SubstitutionError, match=r'environment variable DOMAIN_NAME is not set'):
        get_config(tmp_path, CONFIG)


def test_cert_relative(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['local_certs'] = {
        'pyxis.example.com': 'test.crt'
    }
    conf = get_config(tmp_path, config_data)
    cert = conf.find_local_cert('https://pyxis.example.com')
    assert os.path.isabs(cert)
    assert os.path.exists(cert)


def test_cert_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['local_certs'] = {
        'pyxis.example.com': str(tmp_path / "nothere.crt")
    }
    with raises(ConfigError, match="nothere.crt does not exist"):
        get_config(tmp_path, config_data)


def test_client_cert(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['pyxis_client_cert'], config_data['pyxis_client_key'] = \
        setup_client_cert(tmp_path)

    config = get_config(tmp_path, config_data)
    assert config.pyxis_client_cert == str(tmp_path / "client.crt")
    assert config.pyxis_client_key == str(tmp_path / "client.key")


def test_client_cert_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['pyxis_client_cert'], config_data['pyxis_client_key'] = \
        setup_client_cert(tmp_path, create_cert=False)

    with raises(ConfigError,
                match="client.crt does not exist"):
        get_config(tmp_path, config_data)


def test_client_key_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['pyxis_client_cert'], config_data['pyxis_client_key'] = \
        setup_client_cert(tmp_path, create_key=False)

    with raises(ConfigError,
                match="client.key does not exist"):
        get_config(tmp_path, config_data)


def test_client_key_mismatch(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['pyxis_client_cert'], config_data['pyxis_client_key'] = \
        setup_client_cert(tmp_path)

    del config_data['pyxis_client_cert']

    with raises(ConfigError,
                match="pyxis_client_cert and pyxis_client_key must be set together"):
        get_config(tmp_path, config_data)


def test_pyxis_url_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['pyxis_url']
    with raises(ConfigError,
                match=r'registry/[a-z].*: pyxis_url must be configured for the pyxis datasource'):
        get_config(tmp_path, config_data)


def test_datasource_invalid(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['registries']['registry.example.com']['datasource'] = 'INVALID'
    with raises(ConfigError,
                match="registry/registry.example.com: datasource must be 'pyxis' or 'fedora'"):
        get_config(tmp_path, config_data)


def test_registry_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['registries']['registry.example.com']
    with raises(ConfigError,
                match="indexes/amd64: No registry config found for registry.example.com"):
        get_config(tmp_path, config_data)


def test_koji_tag_and_tag(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['indexes']['brew-rc']['tag'] = 'FOO'
    with raises(ConfigError,
                match="indexes/brew-rc: tag and koji_tag cannot both be set"):
        get_config(tmp_path, config_data)


def test_no_koji_tag_or_tag(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['indexes']['brew-rc']['koji_tag']
    with raises(ConfigError,
                match="indexes/brew-rc: One of tag or koji_tag must be set"):
        get_config(tmp_path, config_data)


def test_index_output_tag(tmp_path):
    config = get_config(tmp_path, BASIC_CONFIG)
    for index in config.indexes:
        if index.name == 'amd64':
            assert index.output_tag == 'latest'
        elif index.name == 'brew-rc':
            assert index.output_tag == 'release-candidate'


def test_koji_tag_extra(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['indexes']['fedora-testing']['tag']
    config_data['indexes']['fedora-testing']['koji_tag'] = 'f30'
    with raises(ConfigError,
                match="indexes/fedora-testing: koji_tag can only be set for the pyxis datasource"):
        get_config(tmp_path, config_data)


def test_bodhi_status_extra(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['indexes']['amd64']['bodhi_status'] = 'stable'
    with raises(ConfigError,
                match="indexes/amd64: bodhi_status can only be set for the fedora datasource"):
        get_config(tmp_path, config_data)


def test_bodhi_status_invalid(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    config_data['indexes']['fedora-testing']['bodhi_status'] = 'INVALID'
    with raises(ConfigError,
                match="indexes/fedora-testing: bodhi_status must be set to 'testing' or 'stable'"):
        get_config(tmp_path, config_data)


def test_icons_dir_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['icons_dir']
    with raises(ConfigError,
                match="indexes/amd64: extract_icons is set, but no icons_dir is configured"):
        get_config(tmp_path, config_data)


def test_icons_uri_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['icons_uri']
    with raises(ConfigError, match="icons_dir is configured, but not icons_uri"):
        get_config(tmp_path, config_data)


def test_deltas_dir_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['deltas_dir']
    with raises(ConfigError,
                match=("indexes/fedora-testing: " +
                       "delta_keep_days is set, but no deltas_dir is configured")):
        get_config(tmp_path, config_data)


def test_deltas_uri_missing(tmp_path):
    config_data = deepcopy(BASIC_CONFIG)
    del config_data['deltas_uri']
    with raises(ConfigError, match="deltas_dir is configured, but not deltas_uri"):
        get_config(tmp_path, config_data)
