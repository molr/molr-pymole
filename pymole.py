from flask import Flask, Response
import json
from inspect import getmembers, isfunction, getsource, getfullargspec
from importlib import import_module
import os

app = Flask(__name__)

def jsonify(obj):
	return Response(json.dumps(obj), mimetype='application/json')
        
def load_missions(dir='missions'):
	missions = {}
	submodules = [s[:-3] for s in os.listdir(dir) if s[-3:] == '.py']
	print(submodules)
	for submodule in submodules:
		sub = import_module(dir+'.'+submodule)
		for member in getmembers(sub):
			if isfunction(member[1]):
				missions[submodule+'.'+member[0]] = member[1]
	return missions

def molr_type(pytype):
	if pytype is bool:
		return 'boolean'
	elif pytype is int:
		return 'integer'
	elif pytype is float:
		return 'double'
	else:
		return 'string'

@app.route("/mission/availableMissions")
def available_missions():
	return jsonify({'missionDtoSet': [{'name':mission_name} for mission_name in MISSIONS.keys()]})

@app.route("/mission/<mission>/representation")
def mission_representation(mission):
	source_lines = getsource(MISSIONS[mission]).split('\n')
	root_block = {'id':'root', 'text':mission, 'navigable': True}
	line_blocks = [{'id':num, 'text':line, 'navigable': True} for num,line in enumerate(source_lines)]
	return jsonify({'rootBlockId':root_block['id'], 'blocks':[root_block]+line_blocks,
	                'childrenBlockIds':{root_block['id']:[l['id'] for l in line_blocks]} })

@app.route("/mission/<mission>/parameterDescription")
def mission_parameter_description(mission):
	arg_spec = getfullargspec(MISSIONS[mission])
	parameters = []
	for i,arg in enumerate(arg_spec.args):
		if arg_spec.defaults is not None and len(arg_spec.args)-i <= len(arg_spec.defaults):
			default = arg_spec.defaults[len(arg_spec.defaults)-(len(arg_spec.args)-i)-1]
		else:
			default = None

		if arg in arg_spec.annotations:
			argtype = molr_type(arg_spec.annotations[arg])
		elif default is not None:
			argtype = molr_type(type(default))
		else:
			argtype = 'string'
		
		parameters.append({'name':arg, 'type': argtype, 'required':(default is None), 'defaultValue': default})
	return jsonify({'parameters': parameters})

@app.route("/mission/<mission>/instantiate/<handle>", methods=["POST"])
def instantiate_mission(mission, handle):
	return Response("{}", mimetype='application/json')

@app.route("/instance/<handle>/states")
def instance_states(handle):
	return Response("{}", mimetype='application/json')

@app.route("/instance/<handle>/outputs")
def instance_outputs(handle):
	return Response("{}", mimetype='application/json')

@app.route("/instance/<handle>/representations")
def instance_representations(handle):
	return Response("{}", mimetype='application/json')

@app.route("/instance/<handle>/instruct/<strand>/<command>", methods=["POST"])
def instance_instruct(handle, strand, command):
	return Response("{}", mimetype='application/json')

    
if __name__ == '__main__':
	MISSIONS = load_missions()
	print("loaded missions!", MISSIONS)
	app.run(port=8800)
