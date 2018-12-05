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
        pass
    return {'mission1': mission1, 'mission2': mission2}


@pytest.fixture
def mole(missions):
    pymole.MISSIONS = missions
    pymole.INSTANCES = {}
    mole = pymole.app.test_client()
    return mole


def test_mission_list(mole, missions):
    mission_dto = json.loads(mole.get("/mission/availableMissions").data.decode('utf-8'))
    assert 'missionDtoSet' in mission_dto
    mole_missions = [m['name'] for m in mission_dto['missionDtoSet']]
    assert set(mole_missions) == set(missions.keys())


def test_mission_params(mole):
    mission_params = json.loads(mole.get("/mission/mission1/parameterDescription").data)
    assert 'parameters' in mission_params
    assert mission_params['parameters'] == [{'name': 'someParam', 'type': 'integer',
                                            'required': True, 'defaultValue': None}]
    mission_params = json.loads(mole.get("/mission/mission2/parameterDescription").data.decode('utf-8'))
    assert 'parameters' in mission_params
    assert mission_params['parameters'] == [{'name': 'm', 'type': 'string', 'required': True, 'defaultValue': '42'}]

def test_mission_representation(mole, missions):
    for mission_name in missions.keys():
        mission_repr = json.loads(mole.get("/mission/%s/representation"%mission_name).data.decode('utf-8'))
        assert 'rootBlockId' in mission_repr
        assert 'blocks' in mission_repr
        assert 'childrenBlockIds' in mission_repr
        returned_source = [b['text'] for b in mission_repr['blocks']]
        actual_source = [l.rstrip() for l in getsourcelines(missions[mission_name])[0]]
        assert returned_source == actual_source
