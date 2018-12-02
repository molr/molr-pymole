import time
def someTask():
	return "Hello World"
	
def sayHello(to='Python'):
	return "Hello %s"%to
	
def aThirdTask(howmany=10):
	for i in range(0,howmany):
		print("I'm a mole on a secret mission! %d" % i)
		time.sleep(1)
	return "Success!"