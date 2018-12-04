import time

def someTask():
	phrase = "Hello"
	time.sleep(1)
	phrase += " "
	time.sleep(2)
	phrase += "World!"
	time.sleep(1)
	print("Happyily debugging me?")
	time.sleep(1)
	return phrase
	
def sayHello(to='Python'):
	return "Hello %s"%to
	
def aThirdTask(howmany=10):
	for i in range(0,howmany):
		print("I'm a mole on a secret mission! %d" % i)
		time.sleep(1)
	return "Success!"