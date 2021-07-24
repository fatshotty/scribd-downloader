import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "scribdl")))


from scribdl.command_line import _command_line


_command_line()