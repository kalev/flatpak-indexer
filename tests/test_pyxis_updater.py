import pytest
import responses
import yaml

from flatpak_indexer.datasource.pyxis import PyxisUpdater
from .utils import get_config, mock_brew, mock_pyxis, setup_client_cert

from .redis import mock_redis


def run_update(updater):
    registry_data = {}

    updater.start()
    try:
        updater.update(registry_data)
    finally:
        updater.stop()

    return registry_data


CONFIG = yaml.safe_load("""
pyxis_url: https://pyxis.example.com/v1
redis_url: redis://localhost
koji_config: brew
registries:
    registry.example.com:
        public_url: https://registry.example.com/
        datasource: pyxis
    fedora:
        public_url: https://registry.fedoraproject.org
        datasource: fedora
indexes:
    amd64:
        architecture: amd64
        registry: registry.example.com
        output: out/test/flatpak-amd64.json
        tag: latest
    all:
        registry: registry.example.com
        output: out/test/flatpak.json
        tag: latest
    # Not a Pyxis-backed index
    fedora-latest:
        registry: fedora
        output: out/fedora/flatpak.json
        bodhi_status: stable
        tag: latest
""")


@pytest.mark.parametrize("server_cert,client_cert",
                         [(False, False),
                          (True,  False),
                          (False, True)])
@mock_brew
@mock_redis
@responses.activate
def test_pyxis_updater(tmp_path, server_cert, client_cert):
    mock_pyxis()

    config = get_config(tmp_path, CONFIG)
    if server_cert:
        config.local_certs['pyxis.example.com'] = 'test.crt'
    if client_cert:
        config.pyxis_client_cert, config.pyxis_client_key = setup_client_cert(tmp_path)

    updater = PyxisUpdater(config, page_size=1)

    registry_data = run_update(updater)
    data = registry_data['registry.example.com']

    assert len(data.repositories) == 2
    aisleriot_repository = data.repositories['aisleriot']
    assert len(aisleriot_repository.images) == 1
    aisleriot_image = next(iter(aisleriot_repository.images.values()))
    assert aisleriot_image.digest == \
        'sha256:bo1dfacec4d226da18ec4a6386263d8b2125fc874c8b4f4f97b31593037ea0bb'
    assert aisleriot_image.labels['org.flatpak.ref'] == \
        'app/org.gnome.Aisleriot/x86_64/stable'
    assert aisleriot_image.labels['org.freedesktop.appstream.icon-128'] == \
        "https://www.example.com/icons/aisleriot.png"


REPOSITORY_OVERRIDE_CONFIG = yaml.safe_load("""
pyxis_url: https://pyxis.example.com/v1
redis_url: redis://localhost
koji_config: brew
registries:
    registry.example.com:
        public_url: https://registry.example.com/
        repositories: ['testrepo']
        datasource: pyxis
indexes:
    amd64:
        architecture: amd64
        registry: registry.example.com
        output: out/test/flatpak-amd64.json
        tag: latest
""")


@mock_brew
@mock_redis
@responses.activate
def test_pyxis_updater_repository_override(tmp_path):
    mock_pyxis()

    config = get_config(tmp_path, REPOSITORY_OVERRIDE_CONFIG)
    updater = PyxisUpdater(config)

    registry_data = run_update(updater)
    amd64_data = registry_data['registry.example.com']

    assert len(amd64_data.repositories) == 1
    testrepo_repository = amd64_data.repositories['testrepo']
    assert testrepo_repository.name == 'testrepo'


KOJI_CONFIG = yaml.safe_load("""
pyxis_url: https://pyxis.example.com/v1
redis_url: redis://localhost
koji_config: brew
registries:
    brew:
        public_url: https://internal.example.com/
        datasource: pyxis
indexes:
    brew-rc:
        registry: brew
        architecture: amd64
        output: out/test/brew.json
        koji_tag: release-candidate
""")


@mock_brew
@mock_redis
@responses.activate
def test_pyxis_updater_koji(tmp_path):
    mock_pyxis()

    config = get_config(tmp_path, KOJI_CONFIG)
    updater = PyxisUpdater(config)

    registry_data = run_update(updater)
    data = registry_data['brew']

    assert len(data.repositories) == 1
    aisleriot_repository = data.repositories['rh-osbs/aisleriot']
    assert aisleriot_repository.name == 'rh-osbs/aisleriot'
    assert len(aisleriot_repository.images) == 1
    aisleriot_image = next(iter(aisleriot_repository.images.values()))
    assert aisleriot_image.digest == \
        'sha256:bo1dfacec4d226da18ec4a6386263d8b2125fc874c8b4f4f97b31593037ea0bb'
