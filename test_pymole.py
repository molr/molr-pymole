import os
import tempfile

import json
import pytest
import pymole
from inspect import getsourcelines


@pytest.fixture
def missions():
    def mission1(someParam:int):
        test_variable = 'test'
        return test_variable
    def mission2(m = '42'):
        raise ValueError(m)
    return {'mission1': mission1, 'mission2': mission2}


@pytest.fixture
def mole(missions):
    pymole.MISSIONS = missions
    pymole.INSTANCES = {}
    pymole.send_states_update()
    mole = pymole.app.test_client()
    return mole


def get_json(mole, url):
    return json.loads(mole.get(url).data.decode('utf-8'))


def get_json_stream(mole, url):
    for update in mole.get(url).iter_encoded():
        yield json.loads(update.decode('utf-8'))


def post_json(mole, url, data={}):
    return json.loads(mole.post(url, data=json.dumps(data).encode('utf-8')).data.decode('utf-8'))


def test_mission_list(mole, missions):
    mission_dto = next(get_json_stream(mole, "/states"))
    assert 'availableMissions' in mission_dto
    mole_missions = [m['name'] for m in mission_dto['availableMissions']]
    assert set(mole_missions) == set(missions.keys())
    assert 'activeMissions' in mission_dto
    assert len(mission_dto['activeMissions']) == 0


def test_mission_params(mole):
    mission_params = get_json(mole, "/mission/mission1/parameterDescription")
    assert 'parameters' in mission_params
    assert mission_params['parameters'] == [{'name': 'someParam', 'type': 'integer',
                                            'required': True, 'defaultValue': None}]
    mission_params = json.loads(mole.get("/mission/mission2/parameterDescription").data.decode('utf-8'))
    assert 'parameters' in mission_params
    assert mission_params['parameters'] == [{'name': 'm', 'type': 'string', 'required': True, 'defaultValue': '42'}]


def test_mission_representation(mole, missions):
    for mission_name in missions.keys():
        mission_repr = get_json(mole, "/mission/%s/representation"%mission_name)
        assert 'rootBlockId' in mission_repr
        assert 'blocks' in mission_repr
        assert 'childrenBlockIds' in mission_repr
        returned_source = [b['text'] for b in mission_repr['blocks']]
        actual_source = [l.rstrip() for l in getsourcelines(missions[mission_name])[0]]
        assert returned_source == actual_source


def run_mission(mole, mission, params):
    handle = post_json(mole, "/mission/%s/instantiate"%mission, params)
    print(handle)
    assert 'id' in handle
    state = get_json_stream(mole, "/instance/%s/states"%handle['id'])
    outputs = get_json_stream(mole, "/instance/%s/outputs"%handle['id'])
    assert next(outputs)['blockOutputs'] == {}
    init_state = next(state)
    assert 'RESUME' in init_state['strandAllowedCommands']['0']
    assert 'STEP_OVER' in init_state['strandAllowedCommands']['0']
    post_json(mole, "/instance/%s/0/instruct/RESUME"%handle['id'])
    for state_update in state:
        if state_update['strandRunStates']['0'] == 'FINISHED':
            last_output = get_json_stream(mole, "/instance/%s/outputs" % handle['id'])
            return state_update, next(last_output)


def test_successful_mission_execution(mole):
    last_state, last_output = run_mission(mole, "mission1", {'someParam': 42})
    assert last_state['result'] == 'SUCCESS'
    assert all([res == 'SUCCESS' for res in last_state['blockResults'].values()])
    assert last_output['blockOutputs']['root']['result'].strip() == 'test'


def test_failed_mission_execution(mole):
    last_state, last_output = run_mission(mole, "mission2", {})
    assert last_state['result'] == 'FAILED'
    assert all([res == 'FAILED' for res in last_state['blockResults'].values()])
    assert last_output['blockOutputs']['root']['exceptions'].strip() == '42'


def test_failed_mission_execution_parametrized(mole):
    last_state, last_output = run_mission(mole, "mission2", {'m': 'exception value'})
    assert last_state['result'] == 'FAILED'
    assert all([res == 'FAILED' for res in last_state['blockResults'].values()])
    assert last_output['blockOutputs']['root']['exceptions'].strip() == 'exception value'
