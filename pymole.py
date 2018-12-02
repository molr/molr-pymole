from flask import Flask, Response, request
import json
from inspect import getmembers, isfunction, isgenerator, getsource, getfullargspec
from importlib import import_module
import os, time
from queue import Queue
from threading import Thread
from enum import Enum


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

class RunState(Enum):
	RUNNING = 1
	PAUSED = 2
	FINISHED = 3
	FAILED = 4

class MissionInstance(object):
	def __init__(self, function, arguments):
		self.function = function
		self.arguments = arguments
		self.result = None
		self.obs_representation = Observable(function_block_repr(self.function))
		self.run_state = RunState.PAUSED
		self.obs_state = Observable(self._fake_obs_state())
		self.obs_output = Observable({"blockOutputs":{}})
	
	def _fake_obs_state(self):
		blocks = function_block_repr(self.function)['blocks']
		if self.run_state == RunState.PAUSED:
			return {"result":"UNDEFINED",
			        "strandAllowedCommands":{"0":["RESUME"]},
			        "strandCursorPositions":{"0":blocks[0]},
			        "strandRunStates":{"0":"PAUSED"},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']: "UNDEFINED" for block in blocks},
			        "blockRunStates":{block['id']: "UNDEFINED" for block in blocks}}
		elif self.run_state == RunState.RUNNING:
			return {"result":"UNDEFINED",
			        "strandAllowedCommands":{"0":[]},
			        "strandCursorPositions":{"0":blocks[0]},
			        "strandRunStates":{"0":"RUNNING"},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']: "UNDEFINED" for block in blocks},
			        "blockRunStates":{block['id']: "RUNNING" for block in blocks}}
		elif self.run_state == RunState.FINISHED:
			return {"result":"SUCCESS",
			        "strandAllowedCommands":{"0":[]},
			        "strandCursorPositions":{"0":blocks[0]},
			        "strandRunStates":{"0":"FINISHED"},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']: "SUCCESS" for block in blocks},
			        "blockRunStates":{block['id']: "FINISHED" for block in blocks}}
		elif self.run_state == RunState.FAILED:
			return {"result":"FAILED",
			        "strandAllowedCommands":{"0":[]},
			        "strandCursorPositions":{"0":blocks[0]},
			        "strandRunStates":{"0":"FINISHED"},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']: "FAILED" for block in blocks},
			        "blockRunStates":{block['id']: "FINISHED" for block in blocks}}
	
	def representation(self):
		return self.obs_representation.observe()

	def state(self):
		return self.obs_state.observe()
		
	def output(self):
		return self.obs_output.observe()
		
	def _append_output(self, topic, data):
		output = self.obs_output.last_data
		output['blockOutputs'].setdefault('root',{}).setdefault(topic,'');
		output['blockOutputs']['root'][topic] += data + "\n"
		self.obs_output.send(output)

	def instruct(self, strand, command):
		print("Getting command %s" % command)
		self._append_output('commands', 'Command %s has been sent to strand %s' % (command, strand))
		if command == 'RESUME' and self.run_state == RunState.PAUSED:
			self.run_state = RunState.RUNNING
			self.obs_state.send(self._fake_obs_state())
			self.task_thread = Thread(target=self._run_func, name='MissionRunner-'+self.function.__name__)
			self.task_thread.start()
	
	def _run_func(self):
		try:
			print("running %s with args %s"%(self.function, self.arguments))
			result = self.function(**self.arguments)
			self._append_output('result', str(result))
			self.run_state = RunState.FINISHED
		except Exception as ex:
			print("error running %s: %s"%(self.function, str(ex)))
			self._append_output('exceptions', str(ex))
			self.run_state = RunState.FAILED
		self.obs_state.send(self._fake_obs_state())
		print("execution finished")
			
		

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
		self.observers.remove(queue)
	
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
