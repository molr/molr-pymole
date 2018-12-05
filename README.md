[![Build Status](https://travis-ci.com/molr/molr-pymole.svg?branch=master)](https://travis-ci.com/molr/molr-pymole)

This is a first attempt of a pure python mole implementation. Currently, it looks for python modules in the 'missions'
subdirectory, and exposes any functions of these modules as missions.

This code is still experimental. Currently implemented features:
- Discovery of remote missions
- Arguments/Parameters
- Inspection (lines of codes as blocks)
- Cursor updates (through python ```sys.settrace()```)
- Run, Pause, Step Over, including loops

Missing:
- inspection of nested missions (multi level tree)
- Step into, Step out
- multi-threaded / multi-stranded missions
- redirection of stdout/stderr?
- better exception handling - single lines failing etc.
