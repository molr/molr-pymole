import os, sys, json, uuid, ast
from flask import Flask, Response, request
from inspect import getmembers, isfunction, isgenerator, getsourcelines, getfullargspec
from importlib import import_module
from queue import Queue
from threading import Thread, Condition
from enum import Enum


app = Flask(__name__)


def respond_json(obj):
	if isgenerator(obj):
		return Response(('data: {0}\n\n'.format(json.dumps(o)) for o in obj), mimetype='text/event-stream')
	else:
		return Response(json.dumps(obj), mimetype='application/json')


def respond_empty():
	return Response("{}", mimetype='application/json')


class Observable(object):
	END_STREAM = None

	def __init__(self, initial_data):
		self.observers = []
		self.last_data = initial_data

	def observe(self):
		queue = Queue()
		self.observers.append(queue)
		queue.put(self.last_data)
		while True:
			event = queue.get()
			if event is Observable.END_STREAM:
				break
			else:
				yield event
		self.observers.remove(queue)

	def send(self, data):
		self.last_data = data
		for observer in self.observers:
			observer.put(data)

	def finish(self):
		self.send(Observable.END_STREAM)


def load_missions(dir='missions'):
	missions = {}
	submodules = [s[:-3] for s in os.listdir(dir) if s[-3:] == '.py']
	print(submodules)
	for submodule in submodules:
		sub_file = dir+'/'+submodule+'.py'
		with open(sub_file,'r') as sub_fd:
			sub_source = sub_fd.read()
		sub_ast = ast.parse(sub_source)
		sub_code = compile(sub_ast, sub_file, 'exec')
		sub_globals = {}
		exec(sub_code, sub_globals)
		for name,member in sub_globals.items():
			if isfunction(member):
				missions[submodule+'.'+name] = member
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
	source = getsourcelines(function)
	source_lines = [s.rstrip() for s in source[0]]
	root_block = {'id':'root', 'text':source_lines[0], 'navigable': True}
	line_blocks = [{'id':num+source[1]+1, 'text':line, 'navigable': True} for num,line in enumerate(source_lines[1:])]
	return {'rootBlockId':root_block['id'], 'blocks':[root_block]+line_blocks,
	        'childrenBlockIds':{root_block['id']:[l['id'] for l in line_blocks]}}


STATE = Observable({'availableMissions':[], 'missionInstances': []})

def send_states_update():
	STATE.send({'availableMissions': [{'name':mission_name} for mission_name in MISSIONS.keys()],
				'activeMissions': [{'handle': handle, 'mission':instance.mission_name}
								   for handle, instance in INSTANCES.items()]})

@app.route("/states")
def mole_state():
	return respond_json(STATE.observe())


@app.route("/mission/<mission>/representation")
def mission_representation(mission):
	return respond_json(function_block_repr(MISSIONS[mission]))


@app.route("/mission/<mission>/parameterDescription")
def mission_parameter_description(mission):
	arg_spec = getfullargspec(MISSIONS[mission])
	parameters = []
	for i,arg in enumerate(arg_spec.args):
		if arg_spec.defaults is not None and len(arg_spec.args)-i <= len(arg_spec.defaults):
			default = arg_spec.defaults[i-(len(arg_spec.args)-len(arg_spec.defaults))]
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


@app.route("/mission/<mission>/instantiate", methods=["POST"])
def instantiate_mission(mission):
	handle = mission + '-' + uuid.uuid1().hex
	params = json.loads(request.data.decode('utf-8'))
	INSTANCES[handle] = MissionInstance(mission, MISSIONS[mission], params)
	send_states_update()
	return respond_json({'id': handle})


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

@app.route("/instance/<handle>/instructRoot/<command>", methods=["POST"])
def instance_instruct_root(handle, command):
	INSTANCES[handle].instruct("0", command)
	return respond_empty()


class RunState(Enum):
	RUNNING = 1
	STEPPING_INTO = 2
	STEPPING_OVER = 3
	STEPPING_OUT = 4
	PAUSED = 5
	FINISHED = 6
	FAILED = 7
	
	def is_running(self):
		return self in [RunState.RUNNING, RunState.STEPPING_INTO,
		                RunState.STEPPING_OVER, RunState.STEPPING_OUT]
	
	def is_paused(self):
		return self in [RunState.PAUSED]
		
	def is_active(self):
		return self.is_running() or self.is_paused()


class MissionInstance(object):
	def __init__(self, mission_name, function, arguments):
		self.mission_name = mission_name
		self.function = function
		self.arguments = arguments
		self.result = None
		self.cursor_pos = 'root'
		self.executed_blocks = []
		self.run_state = RunState.PAUSED
		self.obs_representation = Observable(function_block_repr(self.function))
		self.obs_state = Observable(self._fake_obs_state())
		self.obs_output = Observable({"blockOutputs":{}})
		self.task_thread_command_lck = Condition()
		self.task_thread = Thread(target=self._run_func, name='MissionRunner-'+self.function.__name__)
		self.task_thread.start()

	def _run_state_commands(self):
		if self.run_state.is_paused():
			return ["RESUME", "STEP_OVER"]
		else:
			return ["PAUSE"]
			
	def _run_state_str(self):
		if self.run_state.is_running():
			return "RUNNING"
		elif self.run_state.is_paused():
			return "PAUSED"
		else:
			return "NOT_STARTED"
		
	def _block_state(self, block):
		if block['id'] == self.cursor_pos or block['id'] == 'root':
			return self._run_state_str()
		elif block['id'] in self.executed_blocks:
			return "FINISHED"
		else:
			return "NOT_STARTED"

	def _block_result(self, block):
		if block['id'] == self.cursor_pos or block['id'] == 'root':
			return "UNDEFINED"
		elif block['id'] in self.executed_blocks:
			return "SUCCESS"
		else:
			return "UNDEFINED"

	def _fake_obs_state(self):
		blocks = self.obs_representation.last_data['blocks']
		if self.run_state.is_active():
			return {"result":"UNDEFINED",
			        "strandAllowedCommands":{"0":self._run_state_commands()},
			        "strandCursorBlockIds":{"0":self.cursor_pos},
			        "strandRunStates":{"0":self._run_state_str()},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']:self._block_result(block) for block in blocks},
			        "blockRunStates":{block['id']:self._block_state(block) for block in blocks}}
		elif self.run_state == RunState.FINISHED:
			return {"result":"SUCCESS",
			        "strandAllowedCommands":{"0":[]},
			        "strandCursorBlockIds":{"0":self.cursor_pos},
			        "strandRunStates":{"0":"FINISHED"},
			        "parentToChildrenStrands":{}, "strands":[{"id":"0"}],
			        "blockResults":{block['id']: "SUCCESS" for block in blocks},
			        "blockRunStates":{block['id']: "FINISHED" for block in blocks}}
		elif self.run_state == RunState.FAILED:
			return {"result":"FAILED",
			        "strandAllowedCommands":{"0":[]},
			        "strandCursorBlockIds":{"0":self.cursor_pos},
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
		with self.task_thread_command_lck:
			if self.run_state.is_paused():
				if command == 'RESUME':
					self.run_state = RunState.RUNNING
				elif command == 'STEP_OVER':
					self.run_state = RunState.STEPPING_OVER
				print("setting run_state = %s" % self.run_state)
				self.task_thread_command_lck.notify()
			elif self.run_state == RunState.RUNNING:
				if command == 'PAUSE':
					self.run_state = RunState.PAUSED

	def _trace_func(self, frame, event, arg):
		print("trace %s -- %s" % (event, frame))
		with self.task_thread_command_lck:
			if event == 'call':
				if frame.f_code == self.function.__code__:
					return self._trace_func
				else:
					return None # for step into ... later
			elif event == 'line':
				self.executed_blocks.append(self.cursor_pos)
				self.cursor_pos = frame.f_lineno
				if self.run_state == RunState.STEPPING_OVER or self.run_state == RunState.STEPPING_INTO:
					self.run_state = RunState.PAUSED
			while self.run_state.is_paused():
				self.obs_state.send(self._fake_obs_state())
				self.task_thread_command_lck.wait()
			self.obs_state.send(self._fake_obs_state())
			print("trace: executing next")

	def _run_func(self):
		try:
			print("running %s with args %s"%(self.function, self.arguments))
			sys.settrace(self._trace_func)
			result = self.function(**self.arguments)
			sys.settrace(None)
			self._append_output('result', str(result))
			self.run_state = RunState.FINISHED
		except Exception as ex:
			sys.settrace(None)
			print("error running %s: %s"%(self.function, str(ex)))
			self._append_output('exceptions', str(ex))
			self.run_state = RunState.FAILED
		self.obs_state.send(self._fake_obs_state())
		print("execution finished")


if __name__ == '__main__':
	MISSIONS = load_missions()
	INSTANCES = {}
	print("loaded missions!", MISSIONS)
	send_states_update()
	app.run(port=8800, threaded=True)
