from flask import Flask, Response, request
import json
from inspect import getmembers, isfunction, isgenerator, getsource, getfullargspec
from importlib import import_module
import os, time
from queue import Queue

app = Flask(__name__)

def respond_json(obj):
	if isgenerator(obj):
		return Response((json.dumps(o) for o in obj), mimetype='application/stream+json')
	else:
		return Response(json.dumps(obj), mimetype='application/json')

def respond_empty():
	return Response("{}", mimetype='application/json')
        
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
		
def function_block_repr(function):
	source_lines = getsource(function).rstrip().split('\n')
	root_block = {'id':'root', 'text':source_lines[0], 'navigable': True}
	line_blocks = [{'id':num, 'text':line, 'navigable': True} for num,line in enumerate(source_lines[1:])]
	return {'rootBlockId':root_block['id'], 'blocks':[root_block]+line_blocks,
	        'childrenBlockIds':{root_block['id']:[l['id'] for l in line_blocks]}}

@app.route("/mission/availableMissions")
def available_missions():
	return respond_json({'missionDtoSet': [{'name':mission_name} for mission_name in MISSIONS.keys()]})

@app.route("/mission/<mission>/representation")
def mission_representation(mission):
	return respond_json(function_block_repr(MISSIONS[mission]))

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
		
		parameters.append({'name':arg, 'type': argtype, 'required': True, 'defaultValue': default})
	return respond_json({'parameters': parameters})

@app.route("/mission/<mission>/instantiate/<handle>", methods=["POST"])
def instantiate_mission(mission, handle):
	if handle in INSTANCES:
		print("WARN: handle '%s' already in use" % handle)
		return Response("{}", mimetype='application/json')
	params = json.loads(request.data.decode('utf-8'))
	INSTANCES[handle] = MissionInstance(MISSIONS[mission], params)
	return respond_empty()

@app.route("/instance/<handle>/states")
def instance_states(handle):
	return respond_json(INSTANCES[handle].state())

@app.route("/instance/<handle>/outputs")
def instance_outputs(handle):
	return respond_json(INSTANCES[handle].output())

@app.route("/instance/<handle>/representations")
def instance_representations(handle):
	return respond_json(INSTANCES[handle].representation())

@app.route("/instance/<handle>/<strand>/instruct/<command>", methods=["POST"])
def instance_instruct(handle, strand, command):
	INSTANCES[handle].instruct(strand, command)
	return respond_empty()


class MissionInstance(object):
	def __init__(self, function, params):
		self.function = function
		self.params = params
		self.result = None
		self.obs_representation = Observable(function_block_repr(self.function))
		blocks = function_block_repr(self.function)['blocks']
		self.obs_state = Observable({"result":"UNDEFINED",
		                             "strandAllowedCommands":{"0":["STEP_INTO","STEP_OVER","SKIP","RESUME"]},
		                             "strandCursorPositions":{"0":blocks[0]},
		                             "strandRunStates":{"0":"PAUSED"},
		                             "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
		                             "blockResults":{block['id']: "UNDEFINED" for block in blocks},
		                             "blockRunStates":{block['id']: "UNDEFINED" for block in blocks}})
		self.obs_output = Observable({"blockOutputs":{}})
		
	def representation(self):
		return self.obs_representation.observe()

	def state(self):
		return self.obs_state.observe()
		
	def output(self):
		return self.obs_output.observe()
		
	def instruct(self, strand, command):
		print("Getting command %s" % command)
		output = self.obs_output.last_data
		output['blockOutputs'].setdefault('root',{'stdout':''})['stdout'] += 'Command %s has been sent to strand %s\n' % (strand, command)
		print(output)
		self.obs_output.send(output)

class Observable(object):
	def __init__(self, initial_data):
		self.observers = []
		self.last_data = initial_data
	
	def observe(self):
		queue = Queue()
		self.observers.append(queue)
		yield self.last_data
		while True:
			event = queue.get()
			if event is None: break
			else: yield event
		self.observes.remove(queue)
	
	def send(self, data):
		self.last_data = data
		for observer in self.observers:
			observer.put(data)
	
	def finish():
		send(None)	
				
if __name__ == '__main__':
	MISSIONS = load_missions()
	INSTANCES = {}
	print("loaded missions!", MISSIONS)
	app.run(port=8800, threaded=True)
