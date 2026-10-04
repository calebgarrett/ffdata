"""ONE ROOT (harness, 10-04).

Every data path the engine reads or writes resolves here. FF_ROOT (env) names the
engine root whose data/ directory is used; default /home/claude/bsb2 (the live
session and the pump's symlinked checkout). The scenario harness points FF_ROOT
at a throwaway directory built from a fixture so a scenario can never read or
write the live data. Code is always imported from the checkout the entry point
lives in; FF_ROOT moves only the data.

  root()              -> FF_ROOT or /home/claude/bsb2
  data(*parts)        -> <root>/data/<parts...>   (data('') ends in '/')
"""
import os

DEFAULT = '/home/claude/bsb2'

def root():
    return os.environ.get('FF_ROOT') or DEFAULT

def data(*parts):
    return os.path.join(root(), 'data', *parts)

def code():
    """The checkout this module was imported from (not FF_ROOT)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
