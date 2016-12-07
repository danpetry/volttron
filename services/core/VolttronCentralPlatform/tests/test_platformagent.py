import os
import tempfile
import uuid

import pytest
import requests
from volttron.platform.agent.known_identities import (
    VOLTTRON_CENTRAL_PLATFORM)
from volttron.platform.auth import AuthEntry, AuthFile
from volttron.platform.keystore import KeyStore
from volttron.platform.messaging.health import STATUS_GOOD
from volttron.platform.vip.agent.connection import Connection
from volttron.platform.web import DiscoveryInfo
from zmq.utils import jsonapi


def get_new_keypair():
    tf = tempfile.NamedTemporaryFile()
    ks = KeyStore(tf.name)
    ks.generate()
    return ks.public, ks.secret


def add_to_auth(volttron_home, publickey, capabilities=None):
    authfile = AuthFile(os.path.join(volttron_home, 'auth.json'))
    entry = AuthEntry(
        credentials=publickey, mechanism="CURVE", capabilities=capabilities
    )
    authfile.add(entry)


def do_rpc(jsonrpc_address, method, params=None, authentication=None ):

    json_package = {
        'jsonrpc': '2.0',
        'id': '2503402',
        'method': method,
    }

    if authentication:
        json_package['authorization'] = authentication

    if params:
        json_package['params'] = params

    return requests.post(jsonrpc_address, data=jsonapi.dumps(json_package))


def get_auth_token(jsonrpc_address):

    params = {'username': 'admin', 'password': 'admin'}

    return do_rpc(jsonrpc_address, 'get_authorization',
                  params).json()['result']


def values_not_none(keylist, lookup):
    for k in keylist:
        names = k.split('.')
        obj = lookup
        for i in xrange(len(names)):
            if i == len(names) - 1:
                return names[i] in obj and obj[names[i]] is not None
            try:
                obj = obj[names[i]]
            except KeyError:
                return False
    # passes a None keylist?
    return False


def contains_keys(keylist, lookup):
    for k in keylist:
        names = k.split('.')
        obj = lookup
        for i in xrange(len(names)):
            if i == len(names) - 1:
                return names[i] in obj
            try:
                obj = obj[names[i]]
            except KeyError:
                return False
    # passes a None keylist?
    return False


@pytest.mark.pa
def test_listagents(pa_instance):
    try:
        wrapper, agent_uuid = pa_instance

        os.environ['VOLTTRON_HOME'] = wrapper.volttron_home
        agent = Connection(wrapper.local_vip_address, VOLTTRON_CENTRAL_PLATFORM)
        params = dict(id='foo', method='list_agents')
        agent_list = agent.call(
            'route_request', 'foo', 'list_agents', None)
        assert 1 <= len(agent_list)
        expected_keys = ['name', 'uuid', 'tag', 'priority', 'process_id', 'health',
                         'health.status', 'heatlh.context', 'health.last_updated',
                         'error_code', 'permissions', 'permissions.can_restart',
                         'permissions.can_remove', 'can_stop', 'can_start']
        expected_key_set = set(expected_keys)
        none_key_set = set(['tag', 'priority', 'health.context', 'error_code'])
        not_none_key_set = expected_key_set.difference(none_key_set)
        for a in agent_list:
            assert contains_keys(expected_keys, a)
            assert values_not_none(not_none_key_set, a)
    finally:
        os.environ.pop('VOLTTRON_HOME')



@pytest.mark.pa
@pytest.mark.xfail(reason="Need to upgrade")
def test_manage_agent(pa_instance):
    """ Test that we can manage a `VolttronCentralPlatform`.

    This test is concerned with managing a `VolttronCentralPlatform` from the
    same platform.  Though in principal that should not matter.  We do this
    from a secondary platform in a diffferent integration test.
    """
    wrapper, agent_uuid = pa_instance
    publickey, secretkey = get_new_keypair()

    agent = wrapper.build_agent(
        serverkey=wrapper.serverkey, publickey=publickey, secretkey=secretkey)
    peers = agent.vip.peerlist().get(timeout=2)
    assert VOLTTRON_CENTRAL_PLATFORM in peers

    # Make a call to manage which should return to us the publickey of the
    # platform.agent on the instance.
    papublickey = agent.vip.rpc.call(
        VOLTTRON_CENTRAL_PLATFORM, 'manage', wrapper.vip_address,
        wrapper.serverkey, agent.core.publickey).get(timeout=2)
    assert papublickey


@pytest.mark.pa
@pytest.mark.xfail(reason="Need to upgrade")
def test_can_get_agentlist(pa_instance):
    """ Test that we can retrieve an agent list from an agent.

    The agent must have the "manager" capability.
    """
    wrapper, agent_uuid = pa_instance
    publickey, secretkey = get_new_keypair()

    agent = wrapper.build_agent(
        serverkey=wrapper.serverkey, publickey=publickey, secretkey=secretkey)
    peers = agent.vip.peerlist().get(timeout=2)
    assert VOLTTRON_CENTRAL_PLATFORM in peers

    # Make a call to manage which should return to us the publickey of the
    # platform.agent on the instance.
    papublickey = agent.vip.rpc.call(
        VOLTTRON_CENTRAL_PLATFORM, 'manage', wrapper.vip_address,
        wrapper.serverkey, agent.core.publickey).get(timeout=2)
    assert papublickey

    agentlist = agent.vip.rpc.call(
        VOLTTRON_CENTRAL_PLATFORM, "list_agents"
    ).get(timeout=2)

    assert isinstance(agentlist, list)
    assert len(agentlist) == 1
    retagent = agentlist[0]
    assert retagent['uuid'] == agent_uuid
    checkkeys = ('process_id', 'error_code', 'is_running', 'permissions',
                 'health')
    for k in checkkeys:
        assert k in retagent.keys()

    # make sure can stop is determined to be false
    assert retagent['permissions']['can_stop'] == False


@pytest.mark.pa
@pytest.mark.xfail(reason="Need to upgrade")
def test_agent_can_be_managed(pa_instance):
    wrapper = pa_instance[0]
    publickey, secretkey = get_new_keypair()
    add_to_auth(wrapper.volttron_home, publickey, capabilities=['managed_by'])
    agent = wrapper.build_agent(
        serverkey=wrapper.serverkey, publickey=publickey, secretkey=secretkey)
    peers = agent.vip.peerlist().get(timeout=2)
    assert VOLTTRON_CENTRAL_PLATFORM in peers

    # This step is required because internally we are really connecting
    # to the same platform.  If this were two separate installments this
    # transaction would be easier.
    pa_info = DiscoveryInfo.request_discovery_info(wrapper.bind_web_address)
    add_to_auth(wrapper.volttron_home, pa_info.serverkey,
                capabilities=['can_be_managed'])
    print(wrapper.vip_address)
    returnedid = agent.vip.rpc.call(
        VOLTTRON_CENTRAL_PLATFORM, 'manage', wrapper.vip_address,
        wrapper.serverkey, agent.core.publickey).get(timeout=2)
    assert returnedid


@pytest.mark.pa
def test_status_good_when_agent_starts(pa_instance):
    wrapper = pa_instance[0]
    connection = wrapper.build_connection(peer=VOLTTRON_CENTRAL_PLATFORM)

    assert connection.is_connected()
    status = connection.call('health.get_status')
    assert isinstance(status, dict)
    assert status
    assert STATUS_GOOD == status['status']

